"""Sequences with AI (plan-workflow-ai W8, §5.3): a sequence's prose as control logic, read by the `sequence_read` job.

The rules (sequence_text.py) find each sequence, its sections and the units it applies to; sequence_links.py gives
the ids its logic may use. For each sequence the model gets:
1. the section text the rules read;
2. the candidates: the points of the sequence's units (one id per point of a unit type, with its template role), the
   points of the units it is tied to, the equipment, and the template roles no point fills;
3. the declared control relations (knowledge_model/ba_extension.ttl).
It answers with loops, interlocks, resets and modes as relations between those ids, plus the gaps and conflicts it
sees. Candidates in, ids out (§6.1): `check` refuses an answer that is mostly ids outside the list; the reader then
drops every relation whose ids are not candidates or whose relation is not declared or does not fit its ends, and
says so.

Merged with the rules' own reading (sequence_links.rule_relations): a relation both give is the model's, with the
rules' agreement noted; one only the rules give stays at the rules' confidence. The model's confidence is calibrated
for the job (calibration.py, `knowledge_model/calibration/sequence_read.json`), then capped below auto-accept: every
relation is a proposal a person confirms.

Gaps and conflicts are never silent: each becomes an issue with a question on the sequences step, next to the
rules' own (lettering skips, reheat with no heater). A relation that names a template role the units lack, or a point
only some of the units have, is a gap the rules add themselves.

Published by `statements` (hooked into intake/publish.py) as the setup's own source `setup:sequence_logic`: ba:
relations between the building's points, on every unit of the type (sequence_links.edges). With PM_AI=off, or no
credentials, nothing is asked and nothing is written: the rules-only setup is exactly as before.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data/kg.sqlite"
JOB = "sequence_read"
CALLER = "intake"  # calibration stratum: model|intake
SOURCE = "setup:sequence_logic"
AI_CAP = 0.85  # below auto-accept (0.9): a person confirms the logic
RULE_CONF = 0.5  # a relation only the rules read
BATCH = 5
MAX_BAD_SHARE = 0.25  # an answer with more relations outside the candidates than this is refused (and escalates)
# The declared control relations (knowledge_model.CONTROL_RELATIONS; tests check they are the same).
RELATIONS = ("drives", "feedback", "requires", "resets", "requests", "switches")
KINDS = ("loop", "interlock", "reset", "mode")
STATE_KEY = "ai_sequence_read"  # the building's saved answers
LOGIC_KEY = "sequence_logic"  # the merged logic, read by statements()

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["relations", "gaps", "conflicts"],
    "properties": {
        "relations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["from", "rel", "to", "kind", "loop", "section", "confidence", "why"],
            "properties": {
                "from": {"type": "string", "description": "A candidate id."},
                "rel": {"type": "string", "enum": list(RELATIONS)},
                "to": {"type": "string", "description": "A candidate id."},
                "kind": {"type": "string", "enum": list(KINDS)},
                "loop": {"type": "string", "description": "The loop's name for a loop relation, else empty."},
                "section": {"type": "string", "description": "The section letter or number it is read from."},
                "confidence": {"type": "number", "description": "Probability the relation is right, 0 to 1."},
                "why": {"type": "string", "description": "The words of the section it is read from, short."}}}},
        "gaps": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["section", "text"],
            "properties": {"section": {"type": "string"}, "text": {"type": "string"}}}},
        "conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["sections", "text"],
            "properties": {"sections": {"type": "array", "items": {"type": "string"}}, "text": {"type": "string"}}}},
    },
}


def relation_problem(r: dict, kinds: dict[str, str]) -> str | None:
    """Why one relation fails the rules' check, or None: both ids are candidates, the relation is declared, and its
    ends fit it (only `requests` ends on equipment; `resets` ends on a setpoint)."""
    a, z, rel = r.get("from"), r.get("to"), r.get("rel")
    for x in (a, z):
        if x not in kinds:
            return f"{x!r} is not a candidate id"
    if rel not in RELATIONS:
        return f"{rel!r} is not a declared control relation"
    if a == z:
        return f"{a} {rel} itself"
    if rel == "requests":
        if kinds[z] != "unit" or kinds[a] == "unit":
            return "requests runs from a point to equipment (unit:)"
    elif "unit" in (kinds[a], kinds[z]):
        return f"{rel} runs between points; only requests ends on equipment"
    if rel == "resets" and kinds[z] not in ("setpoint", "role_setpoint"):
        return f"resets ends on a setpoint; {z} is not one"
    return None


def check(out: dict, values: dict) -> str | None:
    """The job's check: confidences in range, and no more than a quarter of the relations off the candidate list."""
    rels = out.get("relations", [])
    if any(not 0 <= r["confidence"] <= 1 for r in rels):
        return "confidence must be between 0 and 1"
    kinds = values.get("candidate_kinds") or {}
    bad = [p for r in rels if (p := relation_problem(r, kinds))]
    if rels and len(bad) > MAX_BAD_SHARE * len(rels):
        return f"{len(bad)} of {len(rels)} relations fail the checks (first: {bad[0]})"
    return None


# questions ---------------------------------------------------------------------------------------------------------

@dataclass
class Question:
    seq: dict           # the sequence fact
    cands: dict         # sequence_links.candidates
    values: dict
    key: str = ""
    answer: dict | None = None
    rules: list[dict] = field(default_factory=list)


def _kind(x: dict, what: str) -> str:
    if what == "unit":
        return "unit"
    if what == "role":
        return "role_setpoint" if x.get("setpoint") else "role"
    return "setpoint" if x.get("setpoint") else "point"


def _point_line(p: dict) -> str:
    bits = [p["id"], p["description"], p["io"] or "?", p["cls"] or "unclassified"]
    if p.get("role"):
        bits.append(f"role {p['role']}")
    if len(p["units"]) < p["of"]:
        bits.append(f"on {len(p['units'])} of {p['of']} units ({', '.join(p['units'][:3])}…)")
    return "- " + " · ".join(bits)


def values_for(c: dict) -> dict:
    """The prompt's placeholders for one sequence, plus what the check needs (candidate_kinds)."""
    own = [p for p in c["points"].values() if p["own"]]
    other = [p for p in c["points"].values() if not p["own"]]
    secs = "\n".join(f"{x['letter']}. {x['title']}: " + " ".join(x["text"].split()) for x in c["sections"])
    units = "\n".join(f"- {u['id']} · {u['cls'] or u['family']} · {', '.join(u['units'][:6])}"
                      f"{'…' if len(u['units']) > 6 else ''} ({len(u['units'])})" + ("" if u["own"] else " · related")
                      for u in c["units"].values())
    roles = "\n".join(f"- {r['id']} · {' or '.join(r['classes'])}" for r in c["roles"].values()) or "(none)"
    applies = c["applies_to"]
    kinds = {p["id"]: _kind(p, "point") for p in c["points"].values()}
    kinds |= {u: "unit" for u in c["units"]}
    kinds |= {r: _kind(x, "role") for r, x in c["roles"].items()}
    return {"title": c["title"], "family": (c["family"] or "unknown").upper(),
            "applies": f"{len(applies)} units: {', '.join(applies[:8])}{'…' if len(applies) > 8 else ''}",
            "sections": secs, "points": "\n".join(map(_point_line, own)) or "(none yet: no submittal points)",
            "related_points": "\n".join(map(_point_line, other)) or "(none)", "units": units or "(none)",
            "roles": roles, "relations": ", ".join(RELATIONS), "candidate_kinds": kinds}


def questions(b: dict, km=None) -> list[Question]:
    """One question per sequence the rules read, with the candidates the building has now."""
    from . import sequence_links
    from .submittal import _matcher

    km = km if km is not None else _matcher().km
    out = []
    for s in b["sequences"]:
        if s.get("status") == "rejected":
            continue
        c = sequence_links.candidates(b, s, km)
        q = Question(s, c, values_for(c))
        q.rules = sequence_links.rule_relations(c)
        out.append(q)
    return out


def question_key(q: Question, prompt_ref: str) -> str:
    text = json.dumps([prompt_ref, {k: v for k, v in q.values.items() if isinstance(v, str)}], sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()


# asking ------------------------------------------------------------------------------------------------------------

def logged_answer(store, model: str, values: dict) -> dict | None:
    """An answer already paid for: the latest successful call in llm_calls with this exact request, model and prompt
    version, whose output still passes the check. A re-run never pays twice."""
    from ..ai.calls import parse_json, request_log
    from ..ai.jobs import check_output, job_request
    from ..ai.models import get_model
    from ..ai.providers import ModelError

    if store is None:
        return None
    req, prompt = job_request(JOB, values)
    rows = store.conn.execute(
        "SELECT id, output, cost_usd, latency_s FROM llm_calls WHERE job = ? AND ok = 1 AND model = ? AND prompt = ?"
        " AND input = ? ORDER BY id DESC", (JOB, get_model(model).id, prompt.ref, request_log(req))).fetchall()
    for r in rows:
        try:
            blocks = json.loads(r["output"] or "[]")
            out = parse_json("".join(b.get("text", "") for b in blocks if b.get("type") == "text"))
        except (ModelError, ValueError, AttributeError):
            continue
        if check_output(JOB, out, values) is None:
            return {"output": out, "model": model, "calls": [r["id"]], "cost_usd": 0.0, "paid_usd": r["cost_usd"],
                    "latency_s": r["latency_s"], "logged": True}
    return None


def ask(values: dict, router, store, project: str, model: str | None = None) -> dict:
    """One run of the job (escalating unless `model` is given), or the logged answer to the same request."""
    from ..ai.jobs import get_job, run_job
    from ..ai.providers import ModelError

    for m in ([model] if model else [k for k in (*get_job(JOB).chain, *get_job(JOB).contender)
                                     if k not in getattr(router, "not_enabled", {})]):
        if (a := logged_answer(store, m, values)) is not None:
            return a
        if not model:
            break  # only the first model the router would call is looked up: the others answer after a failure
    try:
        res = run_job(JOB, values, router=router, store=store, project=project, model=model)
    except ModelError as e:
        return {"error": str(e)[:400]}
    return {"output": res.output, "model": res.model, "calls": [a["call"] for a in res.attempts if a["call"]],
            "cost_usd": res.cost_usd, "latency_s": res.latency_s}


def ask_all(qs: list[Question], router, store, project: str, model: str | None = None, batch: int = BATCH,
            log=lambda m: None) -> None:
    """Fill q.answer for the questions without one: the first alone (the router learns which models answer), then
    `batch` at a time with one store connection per thread."""
    todo = [q for q in qs if q.answer is None]
    if not todo:
        return
    local = threading.local()

    def one(q: Question) -> None:
        st = store
        if store is not None and store.path != ":memory:":
            if not hasattr(local, "store"):
                from ..db.store import Store
                local.store = Store(store.path)
            st = local.store
        q.answer = ask(q.values, router, st, project, model)
        a = q.answer
        log(f"  {q.cands['title']}: " + (f"failed ({a['error'][:120]})" if a.get("error") else
                                         f"{len(a['output']['relations'])} relations from {a['model']}"
                                         + (" (logged answer)" if a.get("logged") else
                                            f", ${a['cost_usd']:.4f}, {a['latency_s']:.0f} s")))

    one(todo[0])
    if store is None or store.path == ":memory:" or batch <= 1:
        for q in todo[1:]:
            one(q)
        return
    with ThreadPoolExecutor(max_workers=batch) as pool:
        list(pool.map(one, todo[1:]))


# merging, gaps and conflicts -----------------------------------------------------------------------------------------

def merge(q: Question, calibrate: bool = True) -> dict:
    """The sequence's logic: the model's checked relations and the rules', its gaps and conflicts, and what the rules'
    check dropped. With no model answer, the rules' relations alone (what the bake-off scores as rules alone)."""
    from ..calibration import calibrate_model

    kinds = q.values["candidate_kinds"]
    a = q.answer or {}
    out = a.get("output") or {}
    model = a.get("model")
    rels, dropped, seen = [], [], {}
    for r in out.get("relations", []):
        if p := relation_problem(r, kinds):
            dropped.append({**r, "problem": p})
            continue
        key = (r["from"], r["rel"], r["to"])
        if key in seen:
            continue
        raw = float(r["confidence"])
        cal = calibrate_model(JOB, raw, model, CALLER) if calibrate else raw
        x = {"from": r["from"], "rel": r["rel"], "to": r["to"], "kind": r["kind"], "loop": r.get("loop", ""),
             "section": r.get("section", ""), "why": r.get("why", "")[:240], "method": "llm", "model": model,
             "raw": raw, "calibrated": round(cal, 4), "confidence": round(min(cal, AI_CAP), 4)}
        seen[key] = x
        rels.append(x)
    # The model read the same step another way when it gives the same relation from the same point (or to the same
    # point) in the same section: the rules' version is a narrower reading of that step and is left out.
    ends = {(r["section"], r["rel"], side, r[side]) for r in rels for side in ("from", "to")}
    for r in q.rules:
        key = (r["from"], r["rel"], r["to"])
        if key in seen:
            seen[key]["rule_agrees"] = True
            continue
        if out and any((r["section"], r["rel"], side, r[side]) in ends for side in ("from", "to")):
            continue
        seen[key] = x = dict(r, confidence=RULE_CONF if out else r["confidence"])
        rels.append(x)
    gaps = [{"section": g.get("section", ""), "text": g["text"], "by": "llm"} for g in out.get("gaps", [])]
    conflicts = [{"sections": c.get("sections", []), "text": c["text"], "by": "llm"} for c in out.get("conflicts", [])]
    # The rules' own gaps in the model's relations: a template role the units lack, a point only some units have.
    pts, used = q.cands["points"], {}
    for r in rels:
        for end in (r["from"], r["to"]):
            if end.startswith("role:") or ((p := pts.get(end)) and p["own"] and len(p["units"]) < p["of"]):
                used.setdefault(end, []).append(r)
    for end, rs in used.items():
        secs = sorted({r["section"] for r in rs if r["section"]})
        steps = "; ".join(f"{r['rel']} {r['from']} → {r['to']}" for r in rs[:3]) + ("…" if len(rs) > 3 else "")
        if end.startswith("role:"):
            text = f"the units have no point for the {end.split('.', 1)[1].replace('_', ' ')} slot ({steps})"
        else:
            p = pts[end]
            text = f"{end} is on {len(p['units'])} of the {p['of']} {p['type']} units only ({steps})"
        gaps.append({"section": secs[0] if len(secs) == 1 else "", "by": "rule", "text": text})
    gaps = list({(g["section"], g["text"]): g for g in gaps}.values())
    return {"relations": rels, "gaps": gaps, "conflicts": conflicts, "dropped": dropped, "model": model,
            "error": a.get("error"), "calls": a.get("calls", []), "cost_usd": a.get("cost_usd", 0.0)}


def _issue(q: Question, n: str, text: str, section: str | list, by: str) -> dict:
    sid = q.seq["id"].split(":", 1)[-1]
    secs = [section] if isinstance(section, str) else section
    bbox = next((x["bbox"] for x in q.cands["sections"] if x["letter"] in secs), None) or q.seq["src"].get("bbox")
    h = hashlib.sha1(text.encode()).hexdigest()[:8]
    label = f"Sequence '{q.cands['title']}' {', '.join(s for s in secs if s)}: {text}".replace(" : ", ": ")
    return {"id": f"issue:ai-{sid}-{n}-{h}", "kind": "issue", "label": label,
            "data": {"text": label, "severity": "check", "ai": {"job": JOB, "by": by, "kind": n}},
            "src": dict(q.seq["src"], bbox=bbox), "method": "llm" if by == "llm" else "rule", "conf": 0.5,
            "step": "sequences", "ask": {"q": label, "field": None, "options": []}}


def issues(q: Question, logic: dict) -> list[dict]:
    """Every gap and conflict as an issue with a question on the sequences step."""
    out = [_issue(q, "gap", g["text"], g["section"], g["by"]) for g in logic["gaps"]]
    out += [_issue(q, "conflict", c["text"], c["sections"], c["by"]) for c in logic["conflicts"]]
    return list({f["id"]: f for f in out}.values())


# the setup ---------------------------------------------------------------------------------------------------------

def read(it, log=lambda m: None, *, router=None, store=None, batch: int = BATCH) -> dict:
    """Ask `sequence_read` about every sequence of the building (saved answers are reused), merge with the rules, put
    the gaps and conflicts on the sequences step as issues and keep the logic in the building's state. Returns a
    summary. With model calls off nothing changes (summary["off"] says why)."""
    from ..ai.calls import default_router
    from ..ai.prompts import load_prompt
    from ..ai.providers import ModelUnavailable
    from .model import building

    summary = {"sequences": 0, "asked": 0, "cached": 0, "relations": 0, "gaps": 0, "conflicts": 0, "dropped": 0,
               "failed": 0, "cost_usd": 0.0, "off": ""}
    if not it.done("sequences"):
        return summary
    b = building(it)
    qs = questions(b)
    summary["sequences"] = len(qs)
    if not qs:
        return summary
    router = router or default_router()
    if not router.ready:  # rules only, exactly as before: an earlier model reading is not applied either
        summary["off"] = router.why_not_ready()
        step = it.s["facts"].get("sequences", {})
        old = [f for f in step if f.startswith("issue:ai-")]
        if old or it.s.get(LOGIC_KEY):
            for fid in old:
                del step[fid]
            it.s.pop(LOGIC_KEY, None)
            it.save()
        return summary
    ref = load_prompt(JOB).ref
    cache = it.s.setdefault(STATE_KEY, {})
    for q in qs:
        q.key = question_key(q, ref)
        q.answer = cache.get(q.key)
    if any(q.answer is None for q in qs):
        if store is None:
            from ..db.store import Store
            store = Store(DB)
        if not router.learnt and hasattr(router, "learn"):
            router.learn(store)
        log(f"AI sequence reading: {sum(q.answer is None for q in qs)} of {len(qs)} sequences to {JOB}…")
        new = {q.key for q in qs if q.answer is None}
        try:
            ask_all(qs, router, store, f"intake:{it.slug}", batch=batch, log=log)
        except ModelUnavailable as e:
            summary["off"] = str(e)
            log(f"AI sequence reading stopped ({e}).")
        for q in qs:
            if q.key in new and q.answer is not None:
                summary["asked"] += 1
                summary["cost_usd"] += q.answer.get("cost_usd", 0.0)
                if not q.answer.get("error"):
                    cache[q.key] = q.answer  # failures are asked again next time
    summary["cached"] = sum(1 for q in qs if q.answer is not None) - summary["asked"]
    logic, cands, facts = {}, {}, []
    for q in qs:
        if q.answer is None or q.answer.get("error"):
            summary["failed"] += q.answer is not None
            continue
        m = merge(q)
        logic[q.seq["id"]] = m
        cands[q.seq["id"]] = q.cands
        facts += issues(q, m)
        for k in ("relations", "gaps", "conflicts", "dropped"):
            summary[k] += len(m[k])
        for d in m["dropped"]:
            log(f"  {q.cands['title']}: dropped {d['from']} {d['rel']} {d['to']} ({d['problem']})")
    step = it.s["facts"].get("sequences", {})
    for fid in [f for f in step if f.startswith("issue:ai-")]:
        del step[fid]
    step |= {f["id"]: f for f in facts}
    it.s[LOGIC_KEY] = {"prompt": ref, "logic": logic, "candidates": cands}
    it.save()
    summary["cost_usd"] = round(summary["cost_usd"], 4)
    log(f"AI sequence reading: {summary['relations']} control relations in {len(logic)} sequences, "
        f"{summary['gaps']} gaps and {summary['conflicts']} conflicts as issues, {summary['dropped']} relations "
        f"dropped by the checks; {summary['asked']} asked (${summary['cost_usd']:.3f}), {summary['cached']} saved.")
    return summary


def statements(it, out: dict, log=lambda m: None, *, router=None, store=None) -> dict:
    """The publish hook: {SOURCE: {nodes, edges, claims}} with the sequences' control relations as ba: edges between
    the nodes the other sources write (`out`, publish.statements), or {} when there is no model reading (PM_AI=off:
    the setup publishes exactly what it did before)."""
    from . import sequence_links

    if read(it, log, router=router, store=store)["off"] and not it.s.get(LOGIC_KEY):
        return {}
    saved = it.s.get(LOGIC_KEY) or {}
    if not saved.get("logic"):
        return {}
    present = {n.id for st in out.values() for n in st.get("nodes", [])}
    logic = {sid: m["relations"] for sid, m in saved["logic"].items()}
    edges, skipped = sequence_links.edges(saved["candidates"], logic, present)
    if skipped:
        log(f"Sequence logic: {len(skipped)} relations not stored (an end is not in the graph).")
    return {SOURCE: {"nodes": [], "edges": edges, "claims": []}}
