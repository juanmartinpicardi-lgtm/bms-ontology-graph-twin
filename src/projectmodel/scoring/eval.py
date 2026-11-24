"""The eval harness (plan-workflow-ai §6.3): one function per job turns a run on a dev set into scored items, and
`report` prints accuracy, calibration and cost for every model row. `scripts/eval.py <job>` is the command.

An item is one answer the job gave, scored against the answer key:
  raw     the confidence the job produced (calibration off)
  cls     its class; true: the answer key's class; ok: exact; broad: right or broader (the true class, or a parent)
  keys    calibration strata (calibration.py); group: the equipment it sits on (cross-validation folds)
Jobs:
  mapper       rules + templates on Alpha (names_paths, names_only); points with a ground-truth class
  intake       the guided setup's readers on Troop D (submittal and BMS points); rules only
  point_class  the AI job, model by model: Troop D's points the readers leave below auto-accept, and Alpha's points
               the mapper leaves below its threshold. One question per distinct point, as the setup asks it
  plan_meaning the AI plan reader, model by model, on the keyed plan sheets of the real dev sets (msu_mbb,
               itd_d1_lab; data/ground_truth/<set>/plans.yaml): rooms and tag placements, rules alone vs rules + model
Dev sets only. The held-out real set (liberty_boe) is never read here.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from .. import calibration as cal

ROOT = Path(__file__).resolve().parents[3]
SETS = {
    "mapper": ["alpha/names_paths", "alpha/names_only"],
    "intake": ["troop_d"],
    "point_class": ["troop_d", "alpha/names_paths", "alpha/names_only"],
    "plan_meaning": ["msu_mbb", "itd_d1_lab"],
}
HELD_OUT = {"liberty_boe"}


def _km():
    from ..knowledge_model import load_knowledge_model
    return _cache("km", load_knowledge_model)


_CACHE: dict = {}


def _cache(key, fn):
    if key not in _CACHE:
        _CACHE[key] = fn()
    return _CACHE[key]


def broader_or_same(pred: str | None, true: str) -> bool:
    """Right or broader: the true class, or one of its parents (never the bare Point)."""
    if not pred:
        return False
    if pred == true:
        return True
    km = _km()
    return pred != "Point" and pred in km.classes and true in km.classes and km.is_a(true, pred)


def _item(raw, cls, true, keys, group, **extra) -> dict:
    return {"raw": float(raw), "cls": cls, "true": true, "ok": cls == true, "broad": broader_or_same(cls, true),
            "keys": list(keys), "group": group, **extra}


# mapper ------------------------------------------------------------------------------------------------------------

def mapper_run(variant: str) -> dict:
    """Run the mapper (rules + templates, no model) on one Alpha blind export with raw confidences."""
    from ..adapters.haystack import read_blind_export
    from ..conventions import apply_conventions, load_layers, scopes_for
    from ..db.store import Store
    from ..mapper.pipeline import Mapper

    project = variant if "/" in variant else f"alpha/{variant}"
    site, name = project.split("/")
    if site in HELD_OUT:
        raise ValueError(f"{site} is held out")
    records = read_blind_export(ROOT / "data/blind" / site / f"{name}.csv")
    km = apply_conventions(_km(), load_layers(scopes_for(project)))
    mapper = Mapper(km)
    store = Store(":memory:")
    with cal.disabled():
        t0 = time.perf_counter()
        mapper.run(records, store, project)
        seconds = time.perf_counter() - t0
    groups, member = mapper.group(records)
    guesses = mapper.classify_points(records)
    return {"project": project, "site": site, "store": store, "records": records, "member": member,
            "guesses": guesses, "seconds": seconds, "mapper": mapper}


def mapper_items(project: str) -> tuple[list[dict], dict]:
    from .score import load_ground_truth

    run = _cache(("mapper", project), lambda: mapper_run(project))
    gt = _cache(("gt", run["site"]), lambda: load_ground_truth(run["site"]))
    items = []
    has_path = {f"pt:{r.source_id}": bool(r.path) for r in run["records"]}
    for n in run["store"].nodes(project, "point"):
        a = json.loads(n["attrs"])
        p = gt.points[gt.key[a["source_id"]]["point_id"]]
        if not p["brick_class"]:
            continue
        g = run["guesses"][n["id"]]
        items.append(_item(n["confidence"], n["class"], p["brick_class"],
                           cal.mapper_keys(n["class"], n["method"], has_path.get(n["id"])), p["equip_id"] or n["id"],
                           id=n["id"], name=n["label"], method=n["method"], hint=bool(g.hint), set=project,
                           # calibration leaves a convention's class hint as it is
                           fixed=bool(g.hint) or n["method"] not in ("rule", "template")))
    cost = {"items": len(items), "points": len(run["records"]), "calls": 0, "usd": 0.0,
            "seconds": run["seconds"]}
    return items, cost


# intake ------------------------------------------------------------------------------------------------------------

def intake_run(site: str = "troop_d"):
    """The guided setup's readers on the Troop D test package, rules only, raw confidences."""
    import os

    from ..ai.calls import set_default_router
    from ..ai.config import load_config
    from ..intake import steps
    from ..intake.state import Intake

    if site != "troop_d":
        raise ValueError("the intake answer key exists for troop_d only")
    old = os.environ.get("PM_AI")
    os.environ["PM_AI"] = "off"
    load_config.cache_clear()
    set_default_router(None)
    try:
        with cal.disabled():
            it = Intake.create("eval-intake", root=Path(tempfile.mkdtemp()))
            t0 = time.perf_counter()
            for s in steps.STEPS[:-1]:
                it.add_file(s.id, s.test_file, (steps.TEST_PACKAGE / s.test_file).read_bytes())
                steps.run(it, s.id, lambda m: None)
            seconds = time.perf_counter() - t0
    finally:
        if old is None:
            os.environ.pop("PM_AI", None)
        else:
            os.environ["PM_AI"] = old
        load_config.cache_clear()
        set_default_router(None)
    return {"intake": it, "seconds": seconds}


def _gt_points(site: str) -> dict[str, dict]:
    import csv
    return {r["bms_name"]: r for r in csv.DictReader((ROOT / "data/ground_truth" / site / "points.csv").open())}


def intake_point_facts(it) -> list[dict]:
    """The point facts the readers classified: submittal points and BMS objects no document mentions."""
    return [f for f in it.facts(kind="point") + it.facts(kind="bms_object")
            if "description" in f["data"] and f["method"] == "rule"]


def intake_items(site: str = "troop_d") -> tuple[list[dict], dict]:
    run = _cache(("intake", site), lambda: intake_run(site))
    gt = _gt_points(site)
    items = []
    for f in intake_point_facts(run["intake"]):
        d = f["data"]
        if d["ref"] not in gt or not gt[d["ref"]]["brick_class"]:
            continue
        items.append(_item(f["conf"], d.get("class"), gt[d["ref"]]["brick_class"], cal.intake_keys(d.get("class"), f["step"]),
                           d.get("device") or d["ref"], id=f["id"], name=d.get("description"), method=f["method"],
                           set=site, term=bool(d.get("term")), fixed=bool(d.get("term"))))
    cost = {"items": len(items), "points": len(items), "calls": 0, "usd": 0.0, "seconds": run["seconds"]}
    return items, cost


# point_class -------------------------------------------------------------------------------------------------------

ANSWERS = ROOT / "data/eval/point_class_answers.json"  # answers already paid for, by model and question (git-ignored)
_LOCK = threading.Lock()  # the answers dict is filled from several threads


def _answers() -> dict:
    return _cache("answers", lambda: json.loads(ANSWERS.read_text()) if ANSWERS.exists() else {})


def _save_answers() -> None:
    ANSWERS.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:  # one writer at a time: the threads share the temporary file
        tmp = ANSWERS.with_suffix(".tmp")
        tmp.write_text(json.dumps(_answers(), indent=0, sort_keys=True))
        tmp.replace(ANSWERS)


def point_class_questions(source: str) -> list[dict]:
    """Questions as the job would get them: [{key, values, candidates, items: [(group, true class, rule class, id)]}].

    troop_d: the readers' points below auto-accept after the intake's calibration, asked as `intake/point_ai.py` asks.
    alpha/<variant>: the mapper's points below the mapper's auto-accept threshold after its calibration, asked as
    `mapper/llm.py` asks (the rules' runners-up as candidates)."""
    if source == "troop_d":
        from ..intake import point_ai

        run = _cache(("intake", "troop_d"), lambda: intake_run("troop_d"))
        it = run["intake"]
        facts = [dict(f, data=dict(f["data"])) for f in intake_point_facts(it)]
        cal_intake = cal.load("intake")
        for f in facts:  # the setup's confidences are calibrated before the questions are picked
            if not f["data"].get("term"):
                f["conf"] = cal_intake.apply(f["conf"], cal.intake_keys(f["data"].get("class"), f["step"]))
        qs = point_ai.questions_for(facts, it.facts(kind="equipment") + it.facts(kind="controller")
                                    + it.facts(kind="alias"))
        gt = _gt_points("troop_d")
        return [{"key": q.key, "values": q.values, "candidates": q.candidates,
                 "items": [(f["data"].get("device"), gt[f["data"]["ref"]]["brick_class"], f["data"].get("class"),
                            f["id"]) for f in q.facts if f["data"]["ref"] in gt and gt[f["data"]["ref"]]["brick_class"]]}
                for q in qs]
    from ..mapper.llm import class_definition
    items, _ = mapper_items(source)
    run = _CACHE[("mapper", source)]
    rec = {f"pt:{r.source_id}": r for r in run["records"]}
    groups, member = run["mapper"].group(run["records"])
    m = run["mapper"]
    for g in groups.values():
        m.type_equipment(g, run["guesses"])
    mapper_cal = cal.load("mapper")
    accept = auto_accept()
    out: dict[str, dict] = {}
    for i in items:
        conf = i["raw"] if i["fixed"] else mapper_cal.apply(i["raw"], tuple(i["keys"]))
        if conf >= accept:
            continue
        r, guess = rec[i["id"]], run["guesses"][i["id"]]
        eq = groups.get(member.get(i["id"], ""))
        cands = [c for c, _ in guess.alternatives]
        if not cands:
            continue
        values = {"name": r.name, "path": r.path or "(none)", "equipment_class": (eq.cls if eq else None) or "(unknown)",
                  "candidates": "\n".join(f"- {c}" + (f": {d}" if (d := class_definition(m.km, c)) else "")
                                          for c in cands), "candidate_list": cands}
        # One question per distinct point, as the setup asks it: typicals (the same name on 138 boxes of one class)
        # are asked once, with the first box's path.
        key = json.dumps(["mapper", r.name, values["equipment_class"], cands])
        q = out.setdefault(key, {"key": key, "values": values, "candidates": cands, "items": []})
        q["items"].append((i["group"], i["true"], i["cls"], i["id"]))
    return list(out.values())


def logged_answer(store, model: str, values: dict) -> dict | None:
    """A point_class answer already paid for: the latest successful call in the call log with this exact request,
    model and prompt version, whose output still passes the job's checks. So a run that was stopped, or a fresh
    answers file, never pays for the same call twice."""
    from ..ai.calls import parse_json, request_log
    from ..ai.jobs import check_output, job_request
    from ..ai.models import get_model
    from ..ai.providers import ModelError

    if store is None:
        return None
    req, prompt = job_request("point_class", values)
    rows = store.conn.execute(
        "SELECT output, cost_usd, latency_s FROM llm_calls WHERE job = 'point_class' AND ok = 1 AND model = ?"
        " AND prompt = ? AND input = ? ORDER BY id DESC", (get_model(model).id, prompt.ref, request_log(req))).fetchall()
    for r in rows:
        try:
            blocks = json.loads(r["output"] or "[]")
            out = parse_json("".join(b.get("text", "") for b in blocks if b.get("type") == "text"))
        except (ModelError, ValueError, AttributeError):
            continue
        if check_output("point_class", out, values) is None:
            return {"class": out["class"], "confidence": float(out["confidence"]), "cost_usd": r["cost_usd"],
                    "latency_s": r["latency_s"], "calls": 1}
    return None


def ask(q: dict, model: str, router, store) -> dict:
    """The model's answer to one question: from the saved answers, else from the call log, else asked now."""
    from ..ai.jobs import run_job
    from ..ai.prompts import load_prompt
    from ..ai.providers import ModelError

    ref = load_prompt("point_class").ref
    akey = json.dumps([model, ref, q["key"]])
    saved = _answers().get(akey)
    if saved is not None and not saved.get("error"):  # failures saved by older runs are asked again
        return dict(saved, cached=True)
    if (a := logged_answer(store, model, q["values"])) is not None:
        with _LOCK:
            _answers()[akey] = a
        return dict(a, cached=True)
    try:
        res = run_job("point_class", q["values"], router=router, store=store, project="eval:point_class", model=model)
        a = {"class": res.output["class"], "confidence": float(res.output["confidence"]), "cost_usd": res.cost_usd,
             "latency_s": res.latency_s, "calls": len(res.attempts)}
    except ModelError as e:
        a = {"error": str(e)[:300], "cost_usd": 0.0, "latency_s": 0.0, "calls": 1}
        if "not enabled" in str(e).lower() or "404" in str(e) or "403" in str(e):
            a["not_enabled"] = True
        return a  # not saved: a failure (a timeout, a model not enabled yet) is asked again on the next run
    with _LOCK:
        _answers()[akey] = a
    return a


def _ask_all(qs: list[dict], model: str, router, store, log, source: str, batch: int = 8) -> list[dict]:
    """Every question's answer: the first alone (a model that is not enabled stops there), then `batch` at a time,
    one store connection per thread."""
    from concurrent.futures import ThreadPoolExecutor

    if not qs:
        return []
    first = ask(qs[0], model, router, store)
    if first.get("not_enabled") or len(qs) == 1:
        return [first] + [first] * (len(qs) - 1) if first.get("not_enabled") else [first]
    local = threading.local()
    done = [0]

    def one(q):
        st = store
        if store is not None and store.path != ":memory:":
            if not hasattr(local, "store"):
                from ..db.store import Store
                local.store = Store(store.path)
            st = local.store
        a = ask(q, model, router, st)
        with _LOCK:
            done[0] += 1
            n = done[0]
        if n % 25 == 0:
            _save_answers()  # a stopped run keeps what it paid for
            log(f"   {model} on {source}: {n + 1}/{len(qs)} questions")
        return a

    workers = 1 if store is not None and store.path == ":memory:" else batch
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rest = list(pool.map(one, qs[1:]))
    _save_answers()
    return [first, *rest]


def point_class_items(source: str, model: str, router, store, log=print, max_questions: int | None = None
                      ) -> tuple[list[dict], dict]:
    qs = _cache(("pcq", source), lambda: point_class_questions(source))
    if max_questions:
        qs = qs[:max_questions]
    items, cost = [], {"items": 0, "points": 0, "questions": len(qs), "calls": 0, "usd": 0.0, "seconds": 0.0,
                       "asked": 0, "cached": 0, "failed": 0, "none": 0}
    answers = _ask_all(qs, model, router, store, log, source)
    caller = "intake" if source == "troop_d" else "mapper"
    for n, (q, a) in enumerate(zip(qs, answers), 1):
        if a.get("not_enabled"):
            return [], {**cost, "skipped": f"{model}: not enabled on this GCP project ({a['error'][:120]})"}
        cost["cached" if a.get("cached") else "asked"] += 1
        cost["usd"] += a.get("cost_usd", 0.0)
        cost["seconds"] += a.get("latency_s", 0.0)
        cost["calls"] += a.get("calls", 0)
        if a.get("error"):
            cost["failed"] += 1
        elif not a.get("class"):
            cost["none"] += 1
        for group, true, rule_cls, fid in q["items"]:
            cls = a.get("class") or rule_cls  # "none of these" or a failure keeps the rules' guess
            raw = a.get("confidence", 0.0) if a.get("class") else 0.0
            # One answer is one observation of the model, whatever number of typicals it is applied to: the folds
            # split by question, so copies of one answer never sit on both sides.
            items.append(_item(raw, cls, true, cal.model_keys(model, caller), f"{source}:{q['key']}", unit=group,
                               id=fid, rule_cls=rule_cls, set=source, model=model,
                               answered=bool(a.get("class")), reachable=true in q["candidates"], fixed=False))
    _save_answers()
    cost["items"] = cost["points"] = len(items)
    return items, cost


# evaluate and report -----------------------------------------------------------------------------------------------

K_FOLDS = 5


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def _row(label: str, items: list[dict], heldout: list[float], cost: dict, kind: str) -> dict:
    """One row: accuracy, raw and held-out calibration tables, cost per 1,000 items."""
    n = len(items)
    per_k = 1000 / cost["points"] if cost.get("points") else 0.0
    row = {"label": label, "kind": kind, "n": n,
           "exact_pct": _pct(sum(i["ok"] for i in items), n),
           "right_or_broader_pct": _pct(sum(i["broad"] for i in items), n),
           "raw": cal.band_table([i["raw"] for i in items], [i["ok"] for i in items]),
           "calibrated": cal.band_table(heldout, [i["ok"] for i in items]),
           "calls_per_1000": round(cost.get("calls", 0) * per_k, 1),
           "usd_per_1000": round(cost.get("usd", 0.0) * per_k, 4),
           "seconds_per_1000": round(cost.get("seconds", 0.0) * per_k, 2),
           "cost": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in cost.items()}}
    row["raw_worst_gap"] = cal.worst_gap(row["raw"])
    row["calibrated_worst_gap"] = cal.worst_gap(row["calibrated"])
    return row


def auto_accept() -> float:
    """The confidence at or above which a machine row is confirmed with no person: the store's own rule
    (`db.store.AutoAccept`, PM_AUTO_ACCEPT, 0.9 by default), the one `settle()` applies to the mapper's and the
    setup's rows. The setup's in-session `intake.state.AUTO_ACCEPT` is the same 0.9. `scoring.score.DEFAULT_ACCEPT`
    (0.8) is not a confirm rule: it is the H2 cut `scripts/score.py` reports. PM_AUTO_ACCEPT=off: nothing is."""
    from ..db.store import AutoAccept

    t = AutoAccept.from_env().threshold
    return float("inf") if t is None else t


def _auto(items: list[dict], heldout: list[float], threshold: float) -> dict:
    """Items at or above auto-accept, and how many of them are wrong: raw vs calibrated (held out)."""
    def at(conf):
        idx = [n for n, c in enumerate(conf) if c >= threshold]
        return {"n": len(idx), "pct": _pct(len(idx), len(items)), "wrong": sum(not items[n]["ok"] for n in idx)}
    return {"threshold": threshold, "raw": at([i["raw"] for i in items]), "calibrated": at(heldout)}


def by_question(items: list[dict]) -> list[dict]:
    """One item per question (`group`): its points' share right as `ok`, a fraction PAV takes as it is."""
    out: dict[str, dict] = {}
    for i in items:
        q = out.setdefault(i["group"], dict(i, ok=0.0, n_points=0))
        q["ok"] += i["ok"]
        q["n_points"] += 1
    for q in out.values():
        q["ok"] /= q["n_points"]
    return list(out.values())


def _heldout(job: str, items: list[dict]) -> list[float]:
    """Held-out calibrated confidence per item; fixed items (a person's statement) keep theirs."""
    fit_items = [i for i in items if not i["fixed"]]
    cv = cal.cross_validate(job, fit_items, K_FOLDS) if fit_items else []
    by = {id(i): c for i, c in zip(fit_items, cv)}
    return [by.get(id(i), i["raw"]) for i in items]


def evaluate(job: str, sets: list[str] | None = None, models: list[str] | None = None, *, router=None, store=None,
             fit: bool = False, budget: float | None = None, max_questions: int | None = None, log=print) -> dict:
    """Run a job on its dev sets, score it, cross-validate its calibration and (with `fit`) store the calibration
    fitted on all its dev items. Returns the report written to reports/eval/<job>.json."""
    sets = sets or SETS[job]
    if any(s.split("/")[0] in HELD_OUT for s in sets):
        raise ValueError(f"held-out sets are never evaluated here: {sets}")
    out = {"job": job, "sets": sets, "k_folds": K_FOLDS, "min_n": cal.MIN_N, "band_n": cal.BAND_N,
           "tolerance": cal.TOLERANCE,
           "budget_usd_per_1000": budget, "calibration_before": cal.load(job).ref or "none", "rows": [], "skipped": []}
    fit_items: list[dict] = []
    if job in ("mapper", "intake"):
        per_set = {s: (mapper_items(s) if job == "mapper" else intake_items(s)) for s in sets}
        allitems = [i for its, _ in per_set.values() for i in its]
        held = dict(zip(map(id, allitems), _heldout(job, allitems)))  # folds across all the job's dev sets
        for s, (its, cost) in per_set.items():
            row = _row(f"{s} · rules", its, [held[id(i)] for i in its], cost, "rules")
            row["set"], row["verdict"] = s, {
                "says": "rules: calibrated" if cal.calibrated(row["calibrated"]) else "rules: not calibrated yet"}
            row["auto_accept"] = _auto(its, [held[id(i)] for i in its], auto_accept())
            out["rows"].append(row)
        fit_items = [i for i in allitems if not i["fixed"]]
    elif job == "point_class":
        from ..ai.calls import Router
        from ..ai.jobs import get_job

        models = models or [*get_job("point_class").chain, *get_job("point_class").contender]
        router = router or Router()
        if not router.ready:
            out["skipped"] = [{"model": m, "why": router.why_not_ready() or "model calls are off"} for m in models]
            log(f"point_class: model rows skipped ({out['skipped'][0]['why']})")
        else:
            if store is None:
                from ..db.store import Store
                store = Store(ROOT / "data/kg.sqlite")
            for m in models:
                per_set, skipped = {}, None
                for s in sets:
                    its, cost = point_class_items(s, m, router, store, log, max_questions)
                    if cost.get("skipped"):
                        skipped = cost["skipped"]
                        break
                    per_set[s] = (its, cost)
                if skipped:
                    out["skipped"].append({"model": m, "why": skipped})
                    log(f"point_class: {skipped}")
                    continue
                # A model's calibration is measured per answer: one question is one judgment, however many typicals
                # it is applied to (Troop D asks once for 100+ boxes). Points get their question's calibrated value.
                questions = by_question([i for its, _ in per_set.values() for i in its if i["answered"]])
                held = dict(zip((q["group"] for q in questions), _heldout(job, questions)))
                for s, (its, cost) in per_set.items():
                    ans = [i for i in its if i["answered"]]
                    qs = [q for q in questions if q["set"] == s]
                    row = _row(f"{s} · {m}", its, [held.get(i["group"], 0.0) for i in its], cost, "model")
                    row["set"], row["model"], row["answered"], row["questions_answered"] = s, m, len(ans), len(qs)
                    # Calibration is judged on the answers the model gave (a "none" keeps the rules' guess): per
                    # answer (the verdict's table), and per point for reference.
                    row["calibrated"] = cal.band_table([held[q["group"]] for q in qs], [q["ok"] for q in qs])
                    row["raw"] = cal.band_table([q["raw"] for q in qs], [q["ok"] for q in qs])
                    row["calibrated_by_point"] = cal.band_table([held[i["group"]] for i in ans], [i["ok"] for i in ans])
                    row["raw_by_point"] = cal.band_table([i["raw"] for i in ans], [i["ok"] for i in ans])
                    row["raw_worst_gap"], row["calibrated_worst_gap"] = (cal.worst_gap(row["raw"]),
                                                                         cal.worst_gap(row["calibrated"]))
                    row["calibrated_by_point_worst_gap"] = cal.worst_gap(row["calibrated_by_point"])
                    row["reachable_pct"] = _pct(sum(i["reachable"] for i in its), len(its))
                    row["rules_exact_pct"] = _pct(sum(i["rule_cls"] == i["true"] for i in its), len(its))
                    row["verdict"] = cal.verdict(metric=row["exact_pct"], rules_metric=row["rules_exact_pct"],
                                                 table=row["calibrated"], usd_per_1000=row["usd_per_1000"],
                                                 budget=budget)
                    out["rows"].append(row)
                fit_items += questions
    elif job == "plan_meaning":
        rows, fit_items, skipped = plan_meaning_rows(sets, models, router=router, store=store, budget=budget, log=log)
        out["rows"] += rows
        out["skipped"] += skipped
    else:
        raise KeyError(f"no eval for job {job!r}; known: {sorted(SETS)}")

    if fit:
        if not fit_items:
            log(f"{job}: nothing to fit (no scored items); the stored calibration is unchanged")
        else:
            c = cal.fit(job, fit_items)
            p = cal.save(c, {"sets": sets, "n": len(fit_items), "k_folds": K_FOLDS, "min_n": cal.MIN_N,
                             "strata": sorted(k for k in c.curves if k != "*"),
                             "heldout_worst_gap": {r["label"]: r["calibrated_worst_gap"] for r in out["rows"]}})
            out["calibration_after"] = c.ref
            log(f"{job}: calibration {c.ref} written to {p.relative_to(ROOT)}")
    return out


def _fmt(v, unit="") -> str:
    return "-" if v is None else f"{v}{unit}"


def print_report(r: dict, out=print) -> None:
    out(f"\n=== {r['job']} · sets {', '.join(r['sets'])} · calibration {r.get('calibration_after') or r['calibration_before']}")
    for s in r["skipped"]:
        out(f"  skipped {s['model']}: {s['why']}")
    for row in r["rows"]:
        out(f"\n  {row['label']}")
        if row["kind"] == "plan":
            print_plan_row(row, out)
            continue
        acc = (f"    accuracy        exact {_fmt(row['exact_pct'], '%')}, right or broader "
               f"{_fmt(row['right_or_broader_pct'], '%')} (n {row['n']})")
        if row["kind"] == "model":
            acc += (f"; rules alone on the same points {_fmt(row['rules_exact_pct'], '%')}; answered {row['answered']}, "
                    f"true class among the candidates {_fmt(row['reachable_pct'], '%')}")
        out(acc)
        out(f"    per 1,000       {row['calls_per_1000']} calls, ${row['usd_per_1000']}, {row['seconds_per_1000']} s")
        if a := row.get("auto_accept"):
            out(f"    auto-accepted   at {a['threshold']}: raw {a['raw']['n']} ({_fmt(a['raw']['pct'], '%')}), "
                f"{a['raw']['wrong']} wrong; calibrated {a['calibrated']['n']} ({_fmt(a['calibrated']['pct'], '%')}), "
                f"{a['calibrated']['wrong']} wrong")
        if row["kind"] == "model":
            out(f"    calibration     per answer ({row['questions_answered']} questions); per point, calibrated worst "
                f"gap {_fmt(row['calibrated_by_point_worst_gap'])} pts")
        out(f"    calibration     {'band':9}{'raw: n':>8} {'conf':>6} {'right':>6}   {'calibrated, held-out: n':>24} "
            f"{'conf':>6} {'right':>6}")
        for a, b in zip(row["raw"], row["calibrated"]):
            if not a["n"] and not b["n"]:
                continue
            out(f"                    {a['band']:9}{a['n']:>8} {_fmt(a['mean_conf_pct']):>6} {_fmt(a['accuracy_pct']):>6}"
                f"   {b['n']:>24} {_fmt(b['mean_conf_pct']):>6} {_fmt(b['accuracy_pct']):>6}")
        out(f"    worst gap (bands of {cal.BAND_N}+): raw {_fmt(row['raw_worst_gap'])} pts, calibrated "
            f"{_fmt(row['calibrated_worst_gap'])} pts (target ≤ {cal.TOLERANCE:g})")
        out(f"    verdict         {row['verdict']['says']}")


def write_report(r: dict, reports: Path = ROOT / "reports/eval") -> Path:
    reports.mkdir(parents=True, exist_ok=True)
    p = reports / f"{r['job']}.json"
    p.write_text(json.dumps(r, indent=1) + "\n")
    return p


# plan_meaning ------------------------------------------------------------------------------------------------------
# The AI plan reader (intake/plan_ai.py) on the keyed plan sheets of the real dev sets. The answer key
# (data/ground_truth/<set>/plans.yaml) was written by hand before the prompt. Scored per building:
#   room       a keyed room number read on the right floor with the right name
#   placement  a keyed tag placed on the right floor, in one of the key's rooms (or in none, for a roof unit)
#   false room a room read on a keyed sheet whose number is not a room there
# The headline is right / (keyed rooms + keyed tags + false rooms), for the rules alone and for rules + model.
# Calibration items are the model's own answers (one per room and per placement on each sheet), after plan_ai's checks.

PLAN_ANSWERS = ROOT / "data/eval/plan_meaning_answers.json"  # answers already paid for (not in the repo)


def plan_key(site: str) -> dict:
    import yaml
    if site in HELD_OUT:
        raise ValueError(f"{site} is held out")
    return yaml.safe_load((ROOT / "data/ground_truth" / site / "plans.yaml").read_text())


def plan_pdf(site: str) -> Path:
    """The keyed sheets of the set's drawing PDF, in key order, as one PDF (page i = key sheet i)."""
    import pypdfium2 as pdfium
    key = plan_key(site)
    out = ROOT / "data/eval" / f"plans_{site}.pdf"
    if not out.exists():
        src = pdfium.PdfDocument(ROOT / "data/raw" / site / key["file"])
        doc = pdfium.PdfDocument.new()
        doc.import_pages(src, [s["page"] - 1 for s in key["sheets"]])
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out)
    return out


def _norm_name(t: str | None) -> str:
    import re
    return re.sub(r"[^A-Z0-9]", "", (t or "").upper())


def plan_rules_facts(site: str) -> list[dict]:
    """The floor-plan rules alone on the keyed sheets (raw confidences)."""
    import copy

    from ..intake import floorplans

    def run():
        with cal.disabled():
            return floorplans.read(plan_pdf(site), plan_pdf(site).name, lambda m: None)
    return copy.deepcopy(_cache(("plan_rules", site), run))


def plan_score(site: str, facts: list[dict]) -> dict:
    """Rooms and placements in `facts` against the key: counts and the headline percentage."""
    from ..intake.plan_ai import normal_of

    key = plan_key(site)
    rooms: dict[str, tuple[str, str]] = {}  # number -> (floor, name)
    for s in key["sheets"]:
        fl = next((f for f in s["floors"] if f != "RF"), s["floors"][0])
        for num, name in (s["rooms"] or {}).items():
            rooms.setdefault(str(num), (fl, name))
    got = {}
    for f in facts:
        if f["kind"] == "room":
            got.setdefault(f["data"]["number"], f)
    place = {f["data"]["normal"]: f for f in facts if f["kind"] == "placement"}
    r = {"rooms": len(rooms), "rooms_found": 0, "rooms_floor": 0, "rooms_named": 0, "rooms_ok": 0,
         "false_rooms": sorted(n for n in got if n not in rooms), "tags": 0, "placed": 0, "placements_ok": 0,
         "wrong": []}
    for num, (fl, name) in rooms.items():
        f = got.get(num)
        if not f:
            continue
        r["rooms_found"] += 1
        floor_ok = f["data"].get("floor") == fl
        name_ok = _norm_name(f["data"].get("name")) == _norm_name(name)
        r["rooms_floor"] += floor_ok
        r["rooms_named"] += name_ok
        r["rooms_ok"] += floor_ok and name_ok
    for tag, k in key["tags"].items():
        r["tags"] += 1
        f = place.get(normal_of(tag))
        if not f:
            continue
        r["placed"] += 1
        room, fl = f["data"].get("room"), f["data"].get("floor")
        ok = fl == k["floor"] and (room in [str(x) for x in k["rooms"]] if k["rooms"] else room is None)
        r["placements_ok"] += ok
        if not ok:
            r["wrong"].append(f"{tag}: {fl}/{room} (key {k['floor']}/{'|'.join(map(str, k['rooms'])) or '-'})")
    r["n"] = r["rooms"] + r["tags"] + len(r["false_rooms"])
    r["right"] = r["rooms_ok"] + r["placements_ok"]
    r["pct"] = _pct(r["right"], r["n"])
    return r


def _plan_answers() -> dict:
    return _cache("plan_answers", lambda: json.loads(PLAN_ANSWERS.read_text()) if PLAN_ANSWERS.exists() else {})


def plan_model_run(site: str, model: str, router, store, log=print) -> dict:
    """Rules + the model on the keyed sheets: the merged facts, the checked answers per page, the cost."""
    from ..intake import plan_ai

    pdf = plan_pdf(site)
    facts = plan_rules_facts(site)
    cache = _plan_answers()
    with cal.disabled():
        results = plan_ai.read_pages(pdf, pdf.name, list(range(len(plan_key(site)["sheets"]))), router=router,
                                     store=store, project="eval:plan_meaning", cache=cache, model=model,
                                     log=lambda m: log(f"   {m}"))
        PLAN_ANSWERS.parent.mkdir(parents=True, exist_ok=True)
        PLAN_ANSWERS.write_text(json.dumps(cache, indent=0, sort_keys=True, default=str))
        plan_ai.merge(facts, results, pdf.name, lambda m: None)
    answered = [r for r in results if r["answer"] and not r["answer"].get("error")]
    failed = [r for r in results if r["answer"] and r["answer"].get("error")]
    cost = {"sheets": len(results), "answered": len(answered), "failed": len(failed),
            "usd": round(sum(r["answer"].get("cost_usd", 0.0) for r in answered), 5),
            "seconds": round(sum(r["answer"].get("latency_s", 0.0) for r in answered), 1),
            "calls": sum(len(r["answer"].get("calls", [])) for r in answered),
            "cached": sum(bool(r["answer"].get("cached")) for r in answered)}
    if failed and any("not enabled" in r["answer"]["error"].lower() or "404" in r["answer"]["error"]
                      for r in failed):
        cost["skipped"] = f"{model}: not enabled on this GCP project ({failed[0]['answer']['error'][:120]})"
    return {"facts": facts, "results": results, "cost": cost}


def plan_items(site: str, run: dict, model: str) -> list[dict]:
    """One item per answer the model gave (a room or a placement on one sheet), scored against the key."""
    from ..intake.plan_ai import normal_of

    key = plan_key(site)
    key_tags = {normal_of(t): k for t, k in key["tags"].items()}
    items = []
    for r in run["results"]:
        ch = r["checked"]
        if not ch:
            continue
        sheet = key["sheets"][r["page"]]
        fl = next((f for f in sheet["floors"] if f != "RF"), sheet["floors"][0])
        rooms = {str(k): v for k, v in (sheet["rooms"] or {}).items()}
        for x in ch["rooms"]:
            ok = x["number"] in rooms and x["floor"] == fl and _norm_name(x["name"]) == _norm_name(rooms[x["number"]])
            items.append({"raw": x["raw"], "ok": bool(ok), "keys": list(cal.model_keys(model, "room")),
                          "group": f"{site}:{r['page']}:R{x['number']}", "set": site, "kind": "room",
                          "fixed": False, "cls": None, "true": None, "broad": bool(ok)})
        for p in ch["placements"]:
            k = key_tags.get(p["normal"])
            if k is None:
                continue  # unsure or not keyed: not scored
            ok = p["floor"] == k["floor"] and (p["room"] in [str(v) for v in k["rooms"]] if k["rooms"]
                                               else p["room"] is None)
            items.append({"raw": p["raw"], "ok": bool(ok), "keys": list(cal.model_keys(model, "placement")),
                          "group": f"{site}:{r['page']}:T{p['normal']}", "set": site, "kind": "placement",
                          "fixed": False, "cls": None, "true": None, "broad": bool(ok)})
    return items


def plan_meaning_rows(sets: list[str], models: list[str] | None, *, router=None, store=None, budget=None,
                      log=print) -> tuple[list[dict], list[dict], list[dict]]:
    from ..ai.calls import Router
    from ..ai.jobs import get_job

    rows, fit_items, skipped = [], [], []
    rules = {s: plan_score(s, plan_rules_facts(s)) for s in sets}
    for s in sets:
        rows.append({"label": f"{s} · rules", "kind": "plan", "set": s, "score": rules[s], "n": rules[s]["n"],
                     "exact_pct": rules[s]["pct"], "raw": [], "calibrated": [], "calibrated_worst_gap": None,
                     "raw_worst_gap": None, "verdict": {"says": "rules alone"}})
    job = get_job("plan_meaning")
    models = models or list(dict.fromkeys([*job.chain, *job.contender]))
    router = router or Router()
    if not router.ready:
        skipped = [{"model": m, "why": router.why_not_ready() or "model calls are off"} for m in models]
        log(f"plan_meaning: model rows skipped ({skipped[0]['why']})")
        return rows, fit_items, skipped
    if store is None:
        from ..db.store import Store
        store = Store(ROOT / "data/kg.sqlite")
    if not router.learnt:
        router.learn(store)
    for m in models:
        if m in router.not_enabled:
            skipped.append({"model": m, "why": f"{m}: not enabled on this GCP project"})
            continue
        runs, why = {}, None
        for s in sets:
            log(f"plan_meaning · {m} · {s}")
            run = plan_model_run(s, m, router, store, log)
            if run["cost"].get("skipped"):
                why = run["cost"]["skipped"]
                break
            runs[s] = run
        if why:
            skipped.append({"model": m, "why": why})
            log(f"plan_meaning: {why}")
            continue
        per_set = {s: plan_items(s, runs[s], m) for s in sets}
        allitems = [i for its in per_set.values() for i in its]
        held = dict(zip(map(id, allitems), _heldout("plan_meaning", allitems)))
        for s in sets:
            its, run = per_set[s], runs[s]
            sc = plan_score(s, run["facts"])
            c = run["cost"]
            heldout = [held[id(i)] for i in its]
            row = {"label": f"{s} · {m}", "kind": "plan", "set": s, "model": m, "score": sc, "rules": rules[s],
                   "n": sc["n"], "exact_pct": sc["pct"], "rules_exact_pct": rules[s]["pct"], "answers": len(its),
                   "answers_right_pct": _pct(sum(i["ok"] for i in its), len(its)),
                   "raw": cal.band_table([i["raw"] for i in its], [i["ok"] for i in its]),
                   "calibrated": cal.band_table(heldout, [i["ok"] for i in its]),
                   "cost": c, "usd_per_sheet": round(c["usd"] / c["answered"], 4) if c["answered"] else None,
                   "usd_per_1000": round(1000 * c["usd"] / len(its), 4) if its else None,
                   "seconds_per_sheet": round(c["seconds"] / c["answered"], 1) if c["answered"] else None,
                   "verdict": {"says": "see the all-dev-sets row"}}
            row["raw_worst_gap"], row["calibrated_worst_gap"] = (cal.worst_gap(row["raw"]),
                                                                 cal.worst_gap(row["calibrated"]))
            rows.append(row)
        # The bake-off verdict is judged on both dev sets together: calibration needs bands of 30+ answers.
        mine = [r for r in rows if r.get("model") == m]
        both = cal.band_table([held[id(i)] for i in allitems], [i["ok"] for i in allitems])
        usd = sum(runs[s]["cost"]["usd"] for s in sets)
        sheets = sum(runs[s]["cost"]["answered"] for s in sets)
        total = {"label": f"all dev sets · {m}", "kind": "plan", "set": "+".join(sets), "model": m,
                 "n": sum(r["score"]["n"] for r in mine),
                 "exact_pct": _pct(sum(r["score"]["right"] for r in mine), sum(r["score"]["n"] for r in mine)),
                 "rules_exact_pct": _pct(sum(rules[s]["right"] for s in sets), sum(rules[s]["n"] for s in sets)),
                 "answers": len(allitems), "answers_right_pct": _pct(sum(i["ok"] for i in allitems), len(allitems)),
                 "raw": cal.band_table([i["raw"] for i in allitems], [i["ok"] for i in allitems]),
                 "calibrated": both, "cost": {"usd": round(usd, 5), "sheets": sheets},
                 "usd_per_sheet": round(usd / sheets, 4) if sheets else None,
                 "usd_per_1000": round(1000 * usd / len(allitems), 4) if allitems else None}
        total["raw_worst_gap"], total["calibrated_worst_gap"] = cal.worst_gap(total["raw"]), cal.worst_gap(both)
        total["verdict"] = cal.verdict(metric=total["exact_pct"], rules_metric=total["rules_exact_pct"], table=both,
                                       usd_per_1000=total["usd_per_1000"], budget=budget)
        rows.append(total)
        fit_items += allitems
    return rows, fit_items, skipped


def print_plan_row(row: dict, out=print) -> None:
    sc = row.get("score")
    if sc:
        out(f"    rooms           {sc['rooms_ok']}/{sc['rooms']} right (found {sc['rooms_found']}, floor right "
            f"{sc['rooms_floor']}, name right {sc['rooms_named']}); {len(sc['false_rooms'])} false rooms")
        out(f"    placements      {sc['placements_ok']}/{sc['tags']} right ({sc['placed']} placed)")
    out(f"    headline        {_fmt(row['exact_pct'], '%')} right of {row['n']} (keyed rooms + tags + false rooms)"
        + (f"; rules alone {_fmt(row['rules_exact_pct'], '%')}" if row.get("rules_exact_pct") is not None else ""))
    if row.get("model"):
        out(f"    answers         {row['answers']} ({_fmt(row['answers_right_pct'], '%')} right); "
            f"${row['cost']['usd']} for {row['cost'].get('sheets')} sheets = ${row['usd_per_sheet']} per sheet, "
            f"${row['usd_per_1000']} per 1,000 answers")
        out(f"    calibration     {'band':9}{'raw: n':>8} {'conf':>6} {'right':>6}   {'calibrated, held-out: n':>24} "
            f"{'conf':>6} {'right':>6}")
        for a, b in zip(row["raw"], row["calibrated"]):
            if a["n"] or b["n"]:
                out(f"                    {a['band']:9}{a['n']:>8} {_fmt(a['mean_conf_pct']):>6} "
                    f"{_fmt(a['accuracy_pct']):>6}   {b['n']:>24} {_fmt(b['mean_conf_pct']):>6} "
                    f"{_fmt(b['accuracy_pct']):>6}")
        out(f"    worst gap (bands of {cal.BAND_N}+): raw {_fmt(row['raw_worst_gap'])} pts, calibrated "
            f"{_fmt(row['calibrated_worst_gap'])} pts (target ≤ {cal.TOLERANCE:g})")
    out(f"    verdict         {row['verdict']['says']}")
# sequence_read (W8) ------------------------------------------------------------------------------------------------
# The sequences of operation as control logic, scored per relation against the hand-built key
# (data/ground_truth/<site>/sequences.yaml, scoring/sequences.py). Rows: the rules alone, each model alone, each model
# plus the rules (the setup's reading). Calibration items are the model's relations (one judgment each), right when
# the key has them; folds split by sequence section. Cost is per sequence and per 1,000 relations proposed.

SETS["sequence_read"] = ["troop_d"]


def sequence_read_questions(site: str = "troop_d") -> list:
    """The job's questions on a dev set, as the setup asks them after its rules-only readers."""
    from ..intake import sequence_ai
    from ..intake.model import building

    if site.split("/")[0] in HELD_OUT:
        raise ValueError(f"{site} is held out")
    run = _cache(("intake", site), lambda: intake_run(site))
    return sequence_ai.questions(building(run["intake"]))


def _sequence_rule_gaps(site: str) -> dict[str, list[dict]]:
    """The rules' own gaps and conflicts per sequence (sequence_text's issues: lettering, reheat with no heater)."""
    it = _cache(("intake", site), lambda: intake_run(site))["intake"]
    out: dict[str, list[dict]] = {}
    for f in it.facts(step="sequences", kind="issue"):
        sid = next((s["id"] for s in it.facts(kind="sequence") if f["id"].startswith("issue:" + s["id"][4:] + "-")),
                   None)
        if sid:
            out.setdefault(sid, []).append({"section": "", "text": f["label"]})
    return out


def _sequence_row(label: str, kind: str, logic: dict[str, dict], key: dict, rule_gaps: dict, cost: dict) -> dict:
    from . import sequences as sq

    per = {}
    gaps_hit = gaps_n = conf_hit = conf_n = 0
    for sid, k in key["sequences"].items():
        m = logic.get(f"seq:{sid}", {"relations": [], "gaps": [], "conflicts": []})
        per[sid] = sq.score(m["relations"], sq.key_relations(k))
        g = sq.gaps_found(m["gaps"] + rule_gaps.get(f"seq:{sid}", []), k.get("gaps", []))
        c = sq.conflicts_found(m["conflicts"], k.get("conflicts", []))
        gaps_hit, gaps_n, conf_hit, conf_n = gaps_hit + sum(g), gaps_n + len(g), conf_hit + sum(c), conf_n + len(c)
        per[sid]["gaps"] = {"key": len(g), "found": sum(g), "said": len(m["gaps"]) + len(rule_gaps.get(f"seq:{sid}", []))}
        per[sid]["conflicts"] = {"key": len(c), "found": sum(c), "said": len(m["conflicts"])}
    s = sq.summary(per)
    n_rel = sum(len(m["relations"]) for m in logic.values())
    row = {"label": label, "kind": kind, **s, "relations": n_rel,
           "gaps": {"key": gaps_n, "found": gaps_hit}, "conflicts": {"key": conf_n, "found": conf_hit},
           "usd_per_sequence": round(cost.get("usd", 0.0) / max(1, cost.get("sequences", 1)), 4),
           "usd_per_1000": round(1000 * cost.get("usd", 0.0) / n_rel, 4) if n_rel else 0.0,
           "seconds_per_sequence": round(cost.get("seconds", 0.0) / max(1, cost.get("sequences", 1)), 1),
           "cost": cost,
           "per_sequence": {sid: {k: v for k, v in x.items() if k not in ("hits", "false", "missed", "labels")}
                            | {"missed": [f"{k['section']} {sorted(k['from'])[0]} {'/'.join(sorted(k['rel']))} "
                                          f"{sorted(k['to'])[0]}" for k in x["missed"]],
                               "false": [f"{r.get('section')} {r['from']} {r['rel']} {r['to']}" for r in x["false"]]}
                            for sid, x in per.items()}}
    row["_labels"] = {sid: x["labels"] for sid, x in per.items()}
    return row


def sequence_read_evaluate(sets: list[str] | None = None, models: list[str] | None = None, *, router=None,
                           store=None, fit: bool = False, budget: float | None = None, log=print) -> dict:
    from ..ai.calls import Router
    from ..ai.jobs import get_job
    from ..ai.prompts import load_prompt
    from ..intake import sequence_ai
    from . import sequences as sq

    job = "sequence_read"
    sets = sets or SETS[job]
    if any(s.split("/")[0] in HELD_OUT for s in sets):
        raise ValueError(f"held-out sets are never evaluated here: {sets}")
    out = {"job": job, "sets": sets, "k_folds": K_FOLDS, "min_n": cal.MIN_N, "band_n": cal.BAND_N,
           "tolerance": cal.TOLERANCE, "budget_usd_per_1000": budget, "prompt": load_prompt(job).ref,
           "calibration_before": cal.load(job).ref or "none", "rows": [], "skipped": []}
    fit_items: list[dict] = []
    for site in sets:
        key = sq.load_key(site)
        qs = _cache(("seqq", site), lambda: sequence_read_questions(site))
        rule_gaps = _sequence_rule_gaps(site)
        out["key"] = {"sequences": len(key["sequences"]),
                      "relations": sum(len(sq.key_relations(k)) for k in key["sequences"].values()),
                      "required": sum(not r["optional"] for k in key["sequences"].values()
                                      for r in sq.key_relations(k)),
                      "loops": sum(len(k.get("loops", [])) for k in key["sequences"].values()),
                      "gaps": sum(len(k.get("gaps", [])) for k in key["sequences"].values()),
                      "conflicts": sum(len(k.get("conflicts", [])) for k in key["sequences"].values())}
        rules_logic = {}
        for q in qs:
            q.answer = None
            rules_logic[q.seq["id"]] = sequence_ai.merge(q, calibrate=False)
        rules = _sequence_row(f"{site} · rules", "rules", rules_logic, key, rule_gaps,
                              {"sequences": len(qs), "usd": 0.0, "seconds": 0.0, "calls": 0})
        rules["set"] = site
        rules["verdict"] = {"says": "rules: the baseline"}
        rules.pop("_labels")
        out["rows"].append(rules)
        models_ = models or [*get_job(job).chain, *get_job(job).contender]
        router = router or Router()
        if not router.ready:
            out["skipped"] += [{"model": m, "why": router.why_not_ready() or "model calls are off"} for m in models_]
            log(f"{job}: model rows skipped ({out['skipped'][0]['why']})")
            continue
        if store is None:
            from ..db.store import Store
            store = Store(ROOT / "data/kg.sqlite")
        for m in models_:
            for q in qs:
                q.answer = None
            sequence_ai.ask_all(qs, router, store, f"eval:{job}", model=m, log=log)
            failed = [q for q in qs if q.answer.get("error")]
            if failed and all(("404" in q.answer["error"] or "not enabled" in q.answer["error"].lower())
                              for q in failed) and len(failed) == len(qs):
                out["skipped"].append({"model": m, "why": failed[0].answer["error"][:160]})
                log(f"{job}: {m} skipped ({failed[0].answer['error'][:120]})")
                continue
            cost = {"sequences": len(qs), "failed": len(failed), "calls": sum(len(q.answer.get("calls", [])) for q in qs),
                    "usd": round(sum(q.answer.get("cost_usd", 0.0) or q.answer.get("paid_usd", 0.0) for q in qs), 4),
                    "seconds": round(sum(q.answer.get("latency_s", 0.0) for q in qs), 1),
                    "logged": sum(bool(q.answer.get("logged")) for q in qs)}
            both = {q.seq["id"]: sequence_ai.merge(q, calibrate=False) for q in qs if not q.answer.get("error")}
            alone = {sid: dict(x, relations=[r for r in x["relations"] if r["method"] == "llm"])
                     for sid, x in both.items()}
            row_m = _sequence_row(f"{site} · {m}", "model", alone, key, rule_gaps, cost)
            row_b = _sequence_row(f"{site} · {m} + rules", "model+rules", both, key, rule_gaps, cost)
            items = []
            for sid, x in alone.items():
                labels = row_m["_labels"].get(sid[4:], {})
                for r in x["relations"]:
                    lab = labels.get((r["from"], r["rel"], r["to"]))
                    if lab is None:
                        continue
                    items.append({"raw": r["raw"], "ok": lab != "fp", "keys": list(cal.model_keys(m, sequence_ai.CALLER)),
                                  "group": f"{sid}:{r['section']}", "fixed": False, "set": site})
            held = _heldout(job, items) if items else []
            for row in (row_m, row_b):
                row.pop("_labels")
                row["set"], row["model"] = site, m
                row["raw"] = cal.band_table([i["raw"] for i in items], [i["ok"] for i in items])
                row["calibrated"] = cal.band_table(held, [i["ok"] for i in items])
                row["raw_worst_gap"], row["calibrated_worst_gap"] = (cal.worst_gap(row["raw"]),
                                                                     cal.worst_gap(row["calibrated"]))
                row["model_relations"] = len(items)
                row["rules_f1"] = rules["f1"]
            row_b["verdict"] = cal.verdict(metric=row_b["f1"], rules_metric=rules["f1"], table=row_b["calibrated"],
                                           usd_per_1000=row_b["usd_per_1000"], budget=budget)
            row_m["verdict"] = {"says": "model alone, for reference (the setup uses model + rules)"}
            out["rows"] += [row_m, row_b]
            fit_items += items
    if fit:
        if not fit_items:
            log(f"{job}: nothing to fit (no model relations); the stored calibration is unchanged")
        else:
            c = cal.fit(job, fit_items)
            p = cal.save(c, {"sets": sets, "n": len(fit_items), "k_folds": K_FOLDS, "min_n": cal.MIN_N,
                             "strata": sorted(k for k in c.curves if k != "*"),
                             "heldout_worst_gap": {r["label"]: r.get("calibrated_worst_gap") for r in out["rows"]
                                                   if r["kind"] == "model+rules"}})
            out["calibration_after"] = c.ref
            log(f"{job}: calibration {c.ref} written to {p.relative_to(ROOT)}")
    return out


def sequence_read_print(r: dict, out=print) -> None:
    out(f"\n=== {r['job']} · sets {', '.join(r['sets'])} · prompt {r['prompt']} · calibration "
        f"{r.get('calibration_after') or r['calibration_before']}")
    if k := r.get("key"):
        out(f"  key: {k['sequences']} sequences, {k['loops']} loops, {k['relations']} relations "
            f"({k['required']} required), {k['gaps']} gaps, {k['conflicts']} conflicts")
    for s in r["skipped"]:
        out(f"  skipped {s['model']}: {s['why']}")
    for row in r["rows"]:
        out(f"\n  {row['label']}")
        out(f"    relations       precision {_fmt(row['precision_pct'], '%')} ({row['tp']} right, {row['fp']} not in "
            f"the key, {row['dup']} repeats), recall {_fmt(row['recall_pct'], '%')} ({row['found']} of "
            f"{row['required']}), F1 {row['f1']}")
        out("    by kind         " + ", ".join(f"{k} {v['found']}/{v['key']}" for k, v in row["by_kind"].items()
                                               if v["key"]))
        out(f"    gaps found      {row['gaps']['found']} of {row['gaps']['key']}; conflicts found "
            f"{row['conflicts']['found']} of {row['conflicts']['key']}")
        if row["kind"] != "rules":
            c = row["cost"]
            out(f"    cost            ${row['usd_per_sequence']} per sequence, ${row['usd_per_1000']} per 1,000 "
                f"relations, {row['seconds_per_sequence']} s per sequence ({c['calls']} calls, {c['logged']} logged "
                f"answers reused, {c['failed']} failed)")
            out(f"    calibration     {'band':9}{'raw: n':>8} {'conf':>6} {'right':>6}   "
                f"{'calibrated, held-out: n':>24} {'conf':>6} {'right':>6}   ({row['model_relations']} model relations)")
            for a, b in zip(row["raw"], row["calibrated"]):
                if a["n"] or b["n"]:
                    out(f"                    {a['band']:9}{a['n']:>8} {_fmt(a['mean_conf_pct']):>6} "
                        f"{_fmt(a['accuracy_pct']):>6}   {b['n']:>24} {_fmt(b['mean_conf_pct']):>6} "
                        f"{_fmt(b['accuracy_pct']):>6}")
            out(f"    worst gap (bands of {cal.BAND_N}+): raw {_fmt(row['raw_worst_gap'])} pts, calibrated "
                f"{_fmt(row['calibrated_worst_gap'])} pts (target ≤ {cal.TOLERANCE:g})")
        out(f"    verdict         {row['verdict']['says']}")


_evaluate_jobs = evaluate
_print_jobs = print_report


def evaluate(job: str, sets: list[str] | None = None, models: list[str] | None = None, *, router=None,  # noqa: F811
             store=None, fit: bool = False, budget: float | None = None, max_questions: int | None = None,
             log=print) -> dict:
    if job == "sequence_read":
        return sequence_read_evaluate(sets, models, router=router, store=store, fit=fit, budget=budget, log=log)
    return _evaluate_jobs(job, sets, models, router=router, store=store, fit=fit, budget=budget,
                          max_questions=max_questions, log=log)


def print_report(r: dict, out=print) -> None:  # noqa: F811
    if r["job"] == "sequence_read":
        return sequence_read_print(r, out)
    return _print_jobs(r, out)
