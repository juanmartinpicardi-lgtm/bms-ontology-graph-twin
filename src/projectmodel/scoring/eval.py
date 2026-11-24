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
Dev sets only. The held-out real set (liberty_boe) is never read here.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from .. import calibration as cal

ROOT = Path(__file__).resolve().parents[3]
SETS = {
    "mapper": ["alpha/names_paths", "alpha/names_only"],
    "intake": ["troop_d"],
    "point_class": ["troop_d", "alpha/names_paths", "alpha/names_only"],
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
    for n in run["store"].nodes(project, "point"):
        a = json.loads(n["attrs"])
        p = gt.points[gt.key[a["source_id"]]["point_id"]]
        if not p["brick_class"]:
            continue
        g = run["guesses"][n["id"]]
        items.append(_item(n["confidence"], n["class"], p["brick_class"],
                           cal.mapper_keys(n["class"], n["method"]), p["equip_id"] or n["id"],
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


def _answers() -> dict:
    return _cache("answers", lambda: json.loads(ANSWERS.read_text()) if ANSWERS.exists() else {})


def _save_answers() -> None:
    ANSWERS.parent.mkdir(parents=True, exist_ok=True)
    ANSWERS.write_text(json.dumps(_answers(), indent=0, sort_keys=True))


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
    from .score import DEFAULT_ACCEPT

    items, _ = mapper_items(source)
    run = _CACHE[("mapper", source)]
    rec = {f"pt:{r.source_id}": r for r in run["records"]}
    groups, member = run["mapper"].group(run["records"])
    m = run["mapper"]
    for g in groups.values():
        m.type_equipment(g, run["guesses"])
    mapper_cal = cal.load("mapper")
    out: dict[str, dict] = {}
    for i in items:
        conf = i["raw"] if i["fixed"] else mapper_cal.apply(i["raw"], tuple(i["keys"]))
        if conf >= DEFAULT_ACCEPT:
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


def ask(q: dict, model: str, router, store) -> dict:
    """The model's answer to one question (from the saved answers when already asked)."""
    from ..ai.jobs import run_job
    from ..ai.prompts import load_prompt
    from ..ai.providers import ModelError

    ref = load_prompt("point_class").ref
    akey = json.dumps([model, ref, q["key"]])
    saved = _answers().get(akey)
    if saved is not None:
        return dict(saved, cached=True)
    try:
        res = run_job("point_class", q["values"], router=router, store=store, project="eval:point_class", model=model)
        a = {"class": res.output["class"], "confidence": float(res.output["confidence"]), "cost_usd": res.cost_usd,
             "latency_s": res.latency_s, "calls": len(res.attempts)}
    except ModelError as e:
        a = {"error": str(e)[:300], "cost_usd": 0.0, "latency_s": 0.0, "calls": 1}
        if "not enabled" in str(e).lower() or "404" in str(e) or "403" in str(e):
            a["not_enabled"] = True
            return a  # not saved: asked again once the model is enabled
    _answers()[akey] = a
    return a


def _ask_all(qs: list[dict], model: str, router, store, log, source: str, batch: int = 8) -> list[dict]:
    """Every question's answer: the first alone (a model that is not enabled stops there), then `batch` at a time,
    one store connection per thread."""
    import threading
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
        done[0] += 1
        if done[0] % 25 == 0:
            log(f"   {model} on {source}: {done[0] + 1}/{len(qs)} questions")
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
            items.append(_item(raw, cls, true, (model,), group, id=fid, rule_cls=rule_cls, set=source, model=model,
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


def _accept() -> dict[str, float]:
    from ..intake.state import AUTO_ACCEPT
    from .score import DEFAULT_ACCEPT
    return {"mapper": DEFAULT_ACCEPT, "intake": AUTO_ACCEPT}


class _Accept(dict):
    def __missing__(self, job):
        self.update(_accept())
        return self[job]


ACCEPT = _Accept()  # each job's auto-accept threshold, as its pipeline uses it


def _auto(items: list[dict], heldout: list[float], threshold: float) -> dict:
    """Items at or above auto-accept, and how many of them are wrong: raw vs calibrated (held out)."""
    def at(conf):
        idx = [n for n, c in enumerate(conf) if c >= threshold]
        return {"n": len(idx), "pct": _pct(len(idx), len(items)), "wrong": sum(not items[n]["ok"] for n in idx)}
    return {"threshold": threshold, "raw": at([i["raw"] for i in items]), "calibrated": at(heldout)}


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
    out = {"job": job, "sets": sets, "k_folds": K_FOLDS, "min_n": cal.MIN_N, "tolerance": cal.TOLERANCE,
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
            row["auto_accept"] = _auto(its, [held[id(i)] for i in its], ACCEPT[job])
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
                answered = [i for its, _ in per_set.values() for i in its if i["answered"]]
                held = dict(zip(map(id, answered), _heldout(job, answered)))
                for s, (its, cost) in per_set.items():
                    ans = [i for i in its if i["answered"]]
                    row = _row(f"{s} · {m}", its, [held.get(id(i), 0.0) for i in its], cost, "model")
                    row["set"], row["model"] = s, m
                    # Calibration is judged on the answers the model gave (a "none" keeps the rules' guess).
                    row["calibrated"] = cal.band_table([held[id(i)] for i in ans], [i["ok"] for i in ans])
                    row["raw"] = cal.band_table([i["raw"] for i in ans], [i["ok"] for i in ans])
                    row["raw_worst_gap"], row["calibrated_worst_gap"] = (cal.worst_gap(row["raw"]),
                                                                         cal.worst_gap(row["calibrated"]))
                    row["answered"] = len(ans)
                    row["reachable_pct"] = _pct(sum(i["reachable"] for i in its), len(its))
                    row["rules_exact_pct"] = _pct(sum(i["rule_cls"] == i["true"] for i in its), len(its))
                    row["verdict"] = cal.verdict(metric=row["exact_pct"], rules_metric=row["rules_exact_pct"],
                                                 table=row["calibrated"], usd_per_1000=row["usd_per_1000"],
                                                 budget=budget)
                    out["rows"].append(row)
                fit_items += answered
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
        out(f"    calibration     {'band':9}{'raw: n':>8} {'conf':>6} {'right':>6}   {'calibrated, held-out: n':>24} "
            f"{'conf':>6} {'right':>6}")
        for a, b in zip(row["raw"], row["calibrated"]):
            if not a["n"] and not b["n"]:
                continue
            out(f"                    {a['band']:9}{a['n']:>8} {_fmt(a['mean_conf_pct']):>6} {_fmt(a['accuracy_pct']):>6}"
                f"   {b['n']:>24} {_fmt(b['mean_conf_pct']):>6} {_fmt(b['accuracy_pct']):>6}")
        out(f"    worst gap (bands of {cal.MIN_N}+): raw {_fmt(row['raw_worst_gap'])} pts, calibrated "
            f"{_fmt(row['calibrated_worst_gap'])} pts (target ≤ {cal.TOLERANCE:g})")
        out(f"    verdict         {row['verdict']['says']}")


def write_report(r: dict, reports: Path = ROOT / "reports/eval") -> Path:
    reports.mkdir(parents=True, exist_ok=True)
    p = reports / f"{r['job']}.json"
    p.write_text(json.dumps(r, indent=1) + "\n")
    return p
