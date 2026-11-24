"""AI point classification inside the guided setup (plan-workflow-ai W0: `point_class` wired into the setup).

After the rules have classified a step's points (the submittal's point schedule, the BMS objects no document
mentions), the points the rules leave below AUTO_ACCEPT go to the `point_class` job, the same job and path the BMS
mapper uses (`mapper/llm.py`):

1. One question per distinct point: the same description, short name, object type and units on the same class of
   equipment is asked once and the answer applied to every unit (typicals repeat one point on dozens of boxes).
2. The model gets a short candidate list from the knowledge model, never the full Brick list: the rules' class and
   its runners-up, the more specific classes under the rules' class, the classes sharing a word with the point, and
   the generic function classes (Sensor, Command, Setpoint...) so it can correct the function.
3. Its answer becomes the proposal (method `llm`). Its confidence is the model's own, calibrated for the job and
   model (`calibration.py`, fitted by `scripts/eval.py point_class --fit`), then capped at AI_CAP, below AUTO_ACCEPT:
   a person reviews it. The rules' guess stays in the fact's data (`rule_class`), and the model's answer, reason, model and
   call ids in `data.ai`. A null answer ("none of these") leaves the rules' guess as it was.
4. Every call goes through the job runner, so every attempt is a row in llm_calls (input, output, cost, latency).
   Answers are kept in the building's state, so re-reading a step asks again only what changed.

With PM_AI=off or no credentials nothing is called and the facts are exactly the rules' facts.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from ..calibration import calibrate_model
from .state import AUTO_ACCEPT

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data/kg.sqlite"  # the app's store, where llm_calls are logged
JOB = "point_class"
AI_BELOW = AUTO_ACCEPT  # the points a person would review anyway
AI_CAP = 0.85  # a model's confidence is not calibrated: its answer is a proposal, never auto-accepted
BATCH = 8  # questions asked at the same time
MAX_QUESTIONS = 400  # per step read; the rest stay with the rules' guess and say so
MAX_CANDIDATES = 15
KINDS = ("point", "bms_object")


@dataclass
class Question:
    key: str
    values: dict
    candidates: list[str]
    facts: list[dict] = field(default_factory=list)
    answer: dict | None = None


def _matcher():
    from .submittal import _matcher
    return _matcher()


def candidates(description: str, short: str = "", limit: int = MAX_CANDIDATES) -> list[str]:
    """A short list of knowledge-model point classes for one point, most likely first."""
    m = _matcher()
    km, words_of = m.km, m.class_words
    g = m.classify(re.sub(r"\(.*?\)", "", description))
    words = set(g.words) | (set(m.classify(short).words) if short else set())

    def overlap(c: str) -> int:
        return len(words & words_of[c])

    def by_overlap(cs) -> list[str]:
        return sorted(cs, key=lambda c: (-overlap(c), len(words_of[c]), c))

    out = ([g.cls] if g.cls else []) + [c for c, _ in g.alternatives]
    if g.cls:
        out += by_overlap(c for c in words_of if c != g.cls and km.is_a(c, g.cls))[:4]
    out += by_overlap(c for c in words_of if overlap(c))
    functions = [f.capitalize() for f in km.class_matching.functions]
    seen, picked = set(), []
    for c in out:
        if c in words_of and c not in seen:
            seen.add(c)
            picked.append(c)
    picked = picked[:max(1, limit - len(functions))]
    picked += [f for f in functions if f in words_of and f not in picked]
    return picked[:limit]


def _point_text(d: dict) -> tuple[str, str]:
    short = d.get("short") or d["ref"].rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    io = d.get("io") or d.get("object") or ""
    extra = " · ".join(x for x in (io, d.get("units") or "") if x)
    return short, f"{short} · {d.get('description') or short}" + (f" · {extra}" if extra else "")


def _questions(facts: list[dict], equip_class: dict[str, str], cache: dict, prompt_ref: str) -> list[Question]:
    from projectmodel.mapper.llm import class_definition

    km = _matcher().km
    out: dict[str, Question] = {}
    for f in facts:
        d = f["data"]
        if f["kind"] not in KINDS or f["method"] != "rule" or f["conf"] >= AI_BELOW or "description" not in d:
            continue
        short, name = _point_text(d)
        eq = equip_class.get(d.get("device") or "")
        cands = candidates(d["description"], short)
        key = json.dumps([prompt_ref, name, eq, cands])
        q = out.get(key)
        if q is None:
            lines = [f"- {c}" + (f": {x}" if (x := class_definition(km, c)) else "") for c in cands]
            q = out[key] = Question(key, {"name": name, "path": d.get("device") or "(none)",
                                          "equipment_class": eq or "(unknown)", "candidates": "\n".join(lines),
                                          "candidate_list": cands}, cands, answer=cache.get(key))
        q.facts.append(f)
    return list(out.values())


def questions_for(facts: list[dict], equipment: list[dict], cache: dict | None = None, prompt_ref: str | None = None
                  ) -> list[Question]:
    """The questions `refine` would ask about these facts (equipment classes from `equipment`, devices from the
    controller and alias facts among `facts` or `equipment`). The eval harness asks the same questions."""
    from projectmodel.ai.prompts import load_prompt

    eq_class = {e["data"]["normal"]: e["data"].get("class") for e in equipment if e.get("kind", "equipment") == "equipment"}
    equip_class = {f["data"]["device"]: eq_class.get(f["data"].get("equip"))
                   for f in [*facts, *equipment] if f.get("kind") in ("controller", "alias") and f["data"].get("equip")}
    return _questions(facts, equip_class, {} if cache is None else cache, prompt_ref or load_prompt(JOB).ref)


def _ask(q: Question, router, store, project: str) -> dict:
    """One run of the job. Returns the answer, or {"error"} when every model failed."""
    from projectmodel.ai.jobs import run_job
    from projectmodel.ai.providers import ModelError

    try:
        res = run_job(JOB, q.values, router=router, store=store, project=project)
    except ModelError as e:
        return {"error": str(e)[:300]}
    out = res.output
    return {"class": out["class"], "confidence": float(out["confidence"]), "why": out["why"], "model": res.model,
            "calls": [a["call"] for a in res.attempts if a["call"]], "cost_usd": res.cost_usd,
            "latency_s": res.latency_s}


def _apply(f: dict, q: Question, cached: bool) -> str:
    """Write the model's answer into the fact. Returns what happened: changed, agreed, none or error."""
    a, d = q.answer, f["data"]
    d["rule_class"], d["rule_conf"] = d.get("class"), f["conf"]
    d["ai"] = {"job": JOB, "candidates": q.candidates, "cached": cached,
               **{k: a[k] for k in ("class", "confidence", "why", "model", "calls", "error") if k in a}}
    if a.get("error") or not a.get("class"):
        return "error" if a.get("error") else "none"
    agreed = a["class"] == d.get("class")
    # The model's own number, calibrated for this job and model (calibration.py), then capped below auto-accept.
    calibrated = calibrate_model(JOB, a["confidence"], a.get("model"))
    d["ai"]["calibrated"] = calibrated
    model_conf = min(calibrated, AI_CAP)
    d["class"] = a["class"]
    f["method"] = "llm"
    f["conf"] = round(max(f["conf"], model_conf) if agreed else model_conf, 2)
    return "agreed" if agreed else "changed"


def refine(facts: list[dict], equipment: list[dict], log, *, project: str, cache: dict | None = None,
           router=None, store=None, batch: int = BATCH, max_questions: int = MAX_QUESTIONS) -> dict:
    """Ask `point_class` about the step's points below AUTO_ACCEPT and write its answers into `facts` (in place).
    `cache` (the building's saved answers) is read and filled. Returns a summary for the log and the scorer."""
    from projectmodel.ai.calls import default_router
    from projectmodel.ai.prompts import load_prompt
    from projectmodel.ai.providers import ModelUnavailable

    cache = {} if cache is None else cache
    qs = questions_for(facts, equipment, cache, load_prompt(JOB).ref)
    summary = {"points": sum(len(q.facts) for q in qs), "questions": len(qs), "asked": 0, "cached": 0, "calls": 0,
               "cost_usd": 0.0, "seconds": 0.0, "changed": 0, "agreed": 0, "none": 0, "error": 0, "skipped": 0,
               "models": {}, "off": ""}
    if not qs:
        return summary
    router = router or default_router()
    if not router.ready:  # rules only, exactly as before (saved answers are not applied either)
        summary["off"] = router.why_not_ready()
        log(f"AI point classification off ({summary['off']}): {summary['points']} points below "
            f"{round(AI_BELOW * 100)}% keep the rules' guess for review.")
        return summary
    todo = [q for q in qs if q.answer is None]
    new = {q.key for q in todo}
    if len(todo) > max_questions:
        summary["skipped"] = len(todo) - max_questions
        todo = todo[:max_questions]
    t0 = time.perf_counter()
    if todo:
        if store is None:
            from projectmodel.db.store import Store
            store = Store(DB)
        if not router.learnt and hasattr(router, "learn"):
            router.learn(store)  # skip the models this GCP project has not enabled
        log(f"AI point classification: {summary['points']} points below {round(AI_BELOW * 100)}% → "
            f"{len(qs)} questions to {JOB} ({len(todo)} new)…")
        local = threading.local()

        def ask(q: Question) -> dict:
            st = store
            if store.path != ":memory:":  # one SQLite connection per thread
                if not hasattr(local, "store"):
                    from projectmodel.db.store import Store
                    local.store = Store(store.path)
                st = local.store
            return _ask(q, router, st, project)

        try:
            # The first question alone: the router learns which models answer before the others run.
            first, rest = todo[:1], todo[1:]
            for q in first:
                q.answer = ask(q)
            # Then `batch` at a time, each slot taking the next question as soon as it is free. An in-memory store
            # (tests) cannot be shared across threads: one at a time.
            if store.path == ":memory:" or batch <= 1:
                for q in rest:
                    q.answer = ask(q)
                rest = []
            with ThreadPoolExecutor(max_workers=max(1, batch)) as pool:
                futures = {pool.submit(ask, q): q for q in rest}
                try:
                    for n, fut in enumerate(as_completed(futures), start=2):
                        futures[fut].answer = fut.result()
                        if n % 20 == 0:
                            log(f"AI point classification: {n}/{len(todo)} questions")
                except ModelUnavailable:
                    for fut in futures:
                        fut.cancel()
                    raise
        except ModelUnavailable as e:
            summary["off"] = str(e)
            log(f"AI point classification stopped ({e}); the rest keep the rules' guess.")
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    for q in qs:
        if q.answer is None:
            continue
        cached = q.key not in new
        if cached:
            summary["cached"] += 1
        else:
            summary["asked"] += 1
            summary["calls"] += len(q.answer.get("calls", []))
            summary["cost_usd"] += q.answer.get("cost_usd", 0.0)
            if not q.answer.get("error"):
                cache[q.key] = q.answer  # failures are asked again next time
        if m := q.answer.get("model"):
            summary["models"][m] = summary["models"].get(m, 0) + 1
        for f in q.facts:
            summary[_apply(f, q, cached)] += 1
    summary["cost_usd"] = round(summary["cost_usd"], 4)
    if summary["asked"] or summary["cached"]:
        models = ", ".join(f"{k} {v}" for k, v in summary["models"].items()) or "none"
        log(f"AI point classification: {summary['changed']} points changed class, {summary['agreed']} agreed with "
            f"the rules, {summary['none']} no candidate fits, {summary['error']} failed; {summary['asked']} asked "
            f"({summary['calls']} calls, ${summary['cost_usd']:.3f}, {summary['seconds']} s), {summary['cached']} "
            f"from earlier answers; models: {models}. Proposals stay below {round(AUTO_ACCEPT * 100)}% for review.")
    if summary["skipped"]:
        log(f"AI point classification: {summary['skipped']} more questions over the limit of {max_questions} keep "
            "the rules' guess.")
    return summary
