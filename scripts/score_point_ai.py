"""Point classification in the guided setup, rules only vs rules + the point_class job, on the Troop D test package,
scored with the intake scorer (intake/score.py) against the answer key.

    .venv/bin/python scripts/score_point_ai.py                 # rules only, then with AI (needs Vertex AI)
    .venv/bin/python scripts/score_point_ai.py --db /tmp/x.sqlite  # log the calls somewhere else

Every model call is logged to llm_calls in --db (default: the app's data/kg.sqlite). Prints point class exact and
"right or broader", the calls, and $ and seconds per 1,000 points. Results also go to reports/point_ai.json.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from projectmodel.ai.calls import set_default_router  # noqa: E402
from projectmodel.ai.config import load_config  # noqa: E402
from projectmodel.intake import point_ai, score, steps  # noqa: E402
from projectmodel.intake.state import Intake  # noqa: E402

MEASURES = ("Points found", "Point class exact", "Point class right or broader")


def run(ai: bool) -> dict:
    if ai:
        os.environ.pop("PM_AI", None)
    else:
        os.environ["PM_AI"] = "off"
    load_config.cache_clear()
    set_default_router(None)
    summaries = []
    orig = point_ai.refine

    def refine(*a, **k):
        s = orig(*a, **k)
        summaries.append(s)
        return s

    point_ai.refine = refine
    it = Intake.create("point-ai", root=Path(tempfile.mkdtemp()))
    t0 = time.time()
    try:
        for s in steps.STEPS[:-1]:
            it.add_file(s.id, s.test_file, (steps.TEST_PACKAGE / s.test_file).read_bytes())
            steps.run(it, s.id, lambda m: print("   ", m) if "AI point" in m else None)
    finally:
        point_ai.refine = orig
    rows = {r["measure"]: (r["machine"], r["out of"]) for r in score.score(it, "troop_d")}
    points = len(it.facts(kind="point")) + sum(1 for f in it.facts(kind="bms_object") if not f["data"]["matched"])
    tot = {k: sum(s[k] for s in summaries) for k in ("questions", "asked", "calls", "cost_usd", "seconds",
                                                    "changed", "agreed", "none", "error")}
    models = {}
    for s in summaries:
        for m, n in s["models"].items():
            models[m] = models.get(m, 0) + n
    per_k = 1000 / points if points else 0
    return {"ai": ai, "off": next((s["off"] for s in summaries if s["off"]), ""), "points": points,
            "below_threshold": sum(s["points"] for s in summaries),
            "score": {m: rows[m] for m in MEASURES}, **tot, "models": models, "cost_usd": round(tot["cost_usd"], 4),
            "usd_per_1000_points": round(tot["cost_usd"] * per_k, 3),
            "ai_seconds_per_1000_points": round(tot["seconds"] * per_k, 1),
            "llm_methods": sum(1 for f in it.facts(kind="point") if f["method"] == "llm"),
            "wall_seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(point_ai.DB))
    ap.add_argument("--rules-only", action="store_true")
    args = ap.parse_args()
    point_ai.DB = Path(args.db)
    res = [run(False)] + ([] if args.rules_only else [run(True)])
    for r in res:
        print(f"\n## {'rules + point_class' if r['ai'] else 'rules only'}" + (f" (AI off: {r['off']})" if r['off'] else ""))
        for m, (n, of) in r["score"].items():
            print(f"   {m:30s} {n}/{of} ({n / of:.0%})" if of else f"   {m:30s} {n}/{of}")
        if r["ai"]:
            print(f"   {r['points']} points, {r['below_threshold']} below {point_ai.AI_BELOW:.0%} -> {r['questions']} "
                  f"questions, {r['asked']} asked, "
                  f"{r['calls']} calls, models {r['models']}")
            print(f"   changed {r['changed']}, agreed {r['agreed']}, none {r['none']}, failed {r['error']}; "
                  f"${r['cost_usd']} ({r['usd_per_1000_points']} per 1,000 points), {r['seconds']} s of AI "
                  f"({r['ai_seconds_per_1000_points']} s per 1,000 points); wall {r['wall_seconds']} s")
    out = ROOT / "reports/point_ai.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
