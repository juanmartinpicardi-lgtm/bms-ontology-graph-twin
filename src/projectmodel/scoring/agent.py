"""The agent's question set (W11): answer correctness and citation correctness on Troop D, rules evidence against the
model's answer, and the cost per question.

    r = evaluate(["troop_d"], models=["argon"], router=router, store=store)   # scripts/eval.py agent
    print_report(r)

The key is data/ground_truth/troop_d/agent_questions.yaml (written before the prompt was tuned). Per question:
  rules evidence   the question's `rules` tool calls run with no model: a fact counts when one of its citation
                   patterns matches an id in what the tools return (the evidence was there for the model to use)
  answer           a fact is stated when all its `answer` regexes match the answer text
  citations        a fact is cited when the answer cites an id matching one of its `cite` patterns, and that id came
                   from a tool result of the turn (TurnResult.bad_cites lists the others)
  precision        cited ids that came from a tool and resolve, over all cited ids
  forbid           an answer matching a `forbid` regex (a value given as live, "is running") is flagged
Optional facts are reported, not counted. The graph is agent/projects.troop_d(): the rules-only setup plus W8's
frozen sequence_read answers, so every run scores the same graph. Model calls are logged to llm_calls in `store`.
"""
from __future__ import annotations

import fnmatch
import json
import re
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
KEY = ROOT / "data" / "ground_truth" / "{site}" / "agent_questions.yaml"
SETS = ["troop_d"]
ID_PREFIXES = ("unit:", "pt:", "rel:", "src:", "seq:", "issue:", "check:", "graphic:", "ctrl:", "room:", "net:",
               "floor:", "eq:")


def load_key(site: str = "troop_d") -> dict:
    return yaml.safe_load(Path(str(KEY).format(site=site)).read_text())


def ids_in(x) -> set[str]:
    """Every string in a tool result that looks like a citation id."""
    out: set[str] = set()
    if isinstance(x, dict):
        for v in x.values():
            out |= ids_in(v)
    elif isinstance(x, list):
        for v in x:
            out |= ids_in(v)
    elif isinstance(x, str) and x.startswith(ID_PREFIXES):
        out.add(x)
    return out


def matches(patterns: list[str], ids) -> list[str]:
    return [i for i in ids if any(fnmatch.fnmatchcase(i, p) for p in patterns)]


def stated(fact: dict, text: str) -> bool:
    return all(re.search(rx, text, re.I) for rx in fact.get("answer") or [])


def rules_evidence(tools, q: dict) -> tuple[dict, set[str]]:
    """Run the question's rule tool calls. Returns ({fact id: found}, the ids in the evidence)."""
    from ..agent_tools import call
    ids: set[str] = set()
    for c in q.get("rules") or []:
        ids |= ids_in(call(tools, c["tool"], c.get("args") or {}))
    return {f["id"]: bool(matches(f["cite"], ids)) for f in q["facts"] if f.get("cite")}, ids


def score_answer(q: dict, text: str, cited: list[str], bad: list[str], tools=None) -> dict:
    good = [c for c in cited if c not in bad]
    facts = {}
    for f in q["facts"]:
        hit = stated(f, text)
        cites = matches(f["cite"], good) if f.get("cite") else []
        facts[f["id"]] = {"stated": hit, "cited": bool(cites) if f.get("cite") else None, "cites": cites[:3],
                          "optional": bool(f.get("optional"))}
    req = [v for v in facts.values() if not v["optional"]]
    with_cite = [v for v in req if v["cited"] is not None]
    return {
        "facts": facts,
        "answer": sum(v["stated"] for v in req) / len(req) if req else 1.0,
        "citation": sum(v["cited"] for v in with_cite) / len(with_cite) if with_cite else 1.0,
        "correct": sum(v["stated"] and v["cited"] is not False for v in req) / len(req) if req else 1.0,
        "precision": len(good) / len(cited) if cited else None,
        "cited": len(cited), "bad_cites": bad,
        "forbidden": [rx for rx in q.get("forbid") or [] if re.search(rx, text, re.I)],
    }


def _agent_turn(tools, q: dict, model: str | None, router, store, km) -> dict:
    from ..agent.chat import Agent
    from ..agent.context import ScreenState, chips_for, context_packet
    from ..memory import load_knowledge

    state = ScreenState(page="eval", title="Agent eval", project=tools.project, project_label="Troop D")
    packet = context_packet(chips_for(state), state, tools)
    agent = Agent(router, tools=tools, knowledge=load_knowledge(km=km), project=tools.project, store=store)
    t0 = time.perf_counter()
    res = agent.run([], q["question"], packet, model=model)
    return {"text": res.text, "model": res.model, "steps": [s["name"] for s in res.steps], "cost_usd": res.cost_usd,
            "seconds": round(time.perf_counter() - t0, 1), "cited": res.cited, "bad_cites": res.bad_cites,
            "repaired": res.repaired, "error": res.error, "calls": res.calls, "note": res.note}


def evaluate(sets: list[str] | None = None, models: list[str] | None = None, *, router=None, store=None,
             questions: list[str] | None = None, log=print) -> dict:
    """Score the rules' evidence, and each model's answers when model calls are on."""
    from ..agent.chat import pick_model
    from ..agent.projects import open_project
    from ..agent_tools import GraphTools
    from ..ai.calls import default_router
    from ..knowledge_model import load_knowledge_model

    sets = sets or SETS
    km = load_knowledge_model()
    router = router or default_router()
    out = {"job": "agent", "sets": sets, "rows": [], "skipped": []}
    for site in sets:
        if site != "troop_d":
            raise ValueError("the agent question set exists for troop_d only")
        key = load_key(site)
        kstore, project, docs = open_project(site)
        tools = GraphTools(kstore, km, project, docs)
        qs = [q for q in key["questions"] if not questions or q["id"] in questions]
        # rules evidence
        per_q = {}
        for q in qs:
            found, _ = rules_evidence(tools, q)
            req = [f for f in q["facts"] if f.get("cite") and not f.get("optional")]
            per_q[q["id"]] = {"found": found, "share": sum(found[f["id"]] for f in req) / len(req) if req else 1.0}
        n_req = sum(1 for q in qs for f in q["facts"] if f.get("cite") and not f.get("optional"))
        n_found = sum(per_q[q["id"]]["found"][f["id"]] for q in qs for f in q["facts"]
                      if f.get("cite") and not f.get("optional"))
        out["rows"].append({"label": f"{site} · rules evidence", "kind": "rules", "questions": len(qs),
                            "facts": n_req, "evidence_pct": round(100 * n_found / n_req, 1) if n_req else None,
                            "per_question": per_q})
        log(f"{site} · rules evidence: {n_found}/{n_req} facts in what the tools return")
        if not router.ready:
            out["skipped"].append(f"models: {router.why_not_ready()}")
            continue
        if store is not None and not router.learnt and hasattr(router, "learn"):
            router.learn(store)
        for m in models or [pick_model(router, "agent_chat")]:
            answers = []
            for q in qs:
                tools.issued.clear()
                a = _agent_turn(tools, q, m, router, store, km)
                s = score_answer(q, a["text"], a["cited"], a["bad_cites"], tools)
                answers.append({"id": q["id"], "question": q["question"], **a, **s})
                log(f"  {m} · {q['id']}: answer {s['answer']:.0%}, citations {s['citation']:.0%}, "
                    f"${a['cost_usd']:.4f}, {a['seconds']} s" + (f", ERROR {a['error']}" if a["error"] else ""))
            n = len(answers)
            mean = lambda k: round(100 * sum(x[k] for x in answers) / n, 1) if n else None  # noqa: E731
            prec = [x["precision"] for x in answers if x["precision"] is not None]
            cost = sum(x["cost_usd"] for x in answers)
            out["rows"].append({
                "label": f"{site} · {m}", "kind": "model", "model": m, "questions": n,
                "answer_pct": mean("answer"), "citation_pct": mean("citation"), "correct_pct": mean("correct"),
                "precision_pct": round(100 * sum(prec) / len(prec), 1) if prec else None,
                "forbidden": sum(bool(x["forbidden"]) for x in answers),
                "errors": sum(bool(x["error"]) for x in answers), "repaired": sum(x["repaired"] for x in answers),
                "usd": round(cost, 4), "usd_per_question": round(cost / n, 4) if n else None,
                "seconds_per_question": round(sum(x["seconds"] for x in answers) / n, 1) if n else None,
                "answers": answers})
    return out


def print_report(r: dict, out=print) -> None:
    out("agent · question set (data/ground_truth/<set>/agent_questions.yaml)")
    for row in r["rows"]:
        if row["kind"] == "rules":
            out(f"  {row['label']:32} {row['questions']} questions, {row['facts']} facts: "
                f"{row['evidence_pct']}% have their citation in the tools' evidence")
            for qid, v in row["per_question"].items():
                miss = [f for f, ok in v["found"].items() if not ok]
                out(f"      {qid:26} {v['share']:.0%}" + (f"  missing: {', '.join(miss)}" if miss else ""))
            continue
        out(f"  {row['label']:32} answer {row['answer_pct']}% · citations {row['citation_pct']}% · both "
            f"{row['correct_pct']}% · cited ids from tools {row['precision_pct']}% · forbidden {row['forbidden']} · "
            f"errors {row['errors']} · rewrites {row['repaired']} · ${row['usd_per_question']} and "
            f"{row['seconds_per_question']} s per question (${row['usd']} in all)")
        for a in row["answers"]:
            miss = [f"{k}{'' if v['stated'] else ' (not stated)'}{' (not cited)' if v['cited'] is False else ''}"
                    for k, v in a["facts"].items() if not v["optional"] and (not v["stated"] or v["cited"] is False)]
            out(f"      {a['id']:26} answer {a['answer']:.0%} citations {a['citation']:.0%}  "
                f"${a['cost_usd']:.4f}" + (f"  missing: {'; '.join(miss)}" if miss else "")
                + (f"  BAD CITES {a['bad_cites'][:3]}" if a["bad_cites"] else "")
                + (f"  FORBIDDEN {a['forbidden']}" if a["forbidden"] else ""))
    for s in r.get("skipped", []):
        out(f"  skipped: {s}")


def dumps(r: dict) -> str:
    return json.dumps(r, indent=1, ensure_ascii=False)
