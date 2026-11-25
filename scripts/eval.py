"""The eval harness (plan-workflow-ai §6.3): one command per job prints accuracy, calibration and cost, model by model,
and the bake-off verdict (§6.4). Results go to reports/eval/<job>.json.

    .venv/bin/python scripts/eval.py mapper                  # rules + templates on Alpha, names_paths and names_only
    .venv/bin/python scripts/eval.py intake                  # the guided setup's readers on Troop D
    .venv/bin/python scripts/eval.py point_class             # the AI job, every model in its chain (Vertex AI)
    .venv/bin/python scripts/eval.py point_class --models argon --set troop_d
    .venv/bin/python scripts/eval.py plan_meaning            # the AI plan reader on the real dev sets' keyed sheets
    .venv/bin/python scripts/eval.py all --fit               # recompute every job's calibration, in order
    .venv/bin/python scripts/eval.py learning                # the learning loop on Alpha (scripts/learning_loop.py)
    .venv/bin/python scripts/eval.py sequence_read --models argon hydrogen --fit   # sequences vs the hand-built key
    .venv/bin/python scripts/eval.py agent --models argon    # the agent's question set on Troop D (scoring/agent.py)

Accuracy is exact and right-or-broader (the true class or a parent). Calibration is shown raw and calibrated; the
calibrated column is held out: k-fold by equipment, each fold calibrated by a curve fitted on the others. `--fit`
then stores the curve fitted on all dev items in knowledge_model/calibration/<job>.json (version + 1 when it
changed), which the mapper and the setup load at run time. Fit in order (`all` does): the point_class questions are
the points the mapper's and the readers' calibrated confidences leave below auto-accept.

Dev sets only (Alpha, Troop D; msu_mbb and itd_d1_lab for plan_meaning). The held-out set (liberty_boe) is refused.
With PM_AI=off or no credentials the model rows are skipped and say so. Model answers are saved in data/eval/
(git-ignored) so a refit doesn't pay twice; every call is logged to llm_calls in --db.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import calibration as cal  # noqa: E402
from projectmodel.scoring import eval as ev  # noqa: E402

ORDER = ["mapper", "intake", "point_class", "plan_meaning", "sequence_read"]
EXTRA = ["learning", "agent"]  # not in `all`, not calibrated jobs: the learning loop (W10), the agent (W11)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", choices=[*ORDER, *EXTRA, "all"])
    ap.add_argument("--set", nargs="+", dest="sets", help="dev sets (default: the job's own)")
    ap.add_argument("--models", nargs="+",
                    help="point_class, plan_meaning, sequence_read: models to run (default: the job's chain and "
                         "contender)")
    ap.add_argument("--fit", action="store_true", help="store the calibration fitted on all dev items")
    ap.add_argument("--budget", type=float, default=None,
                    help=f"bake-off budget, USD per 1,000 items (default: PM_BUDGET_USD_PER_1000, else the "
                         f"provisional {cal.DEFAULT_BUDGET_USD_PER_1000})")
    ap.add_argument("--max-questions", type=int, help="point_class: ask at most this many questions per set")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"), help="where model calls are logged")
    args = ap.parse_args()

    budget = args.budget if args.budget is not None else cal.budget_usd_per_1000()
    store = None
    if args.job in ("point_class", "plan_meaning", "sequence_read", "agent", "all"):
        from projectmodel.db.store import Store
        store = Store(args.db)
    for job in ORDER if args.job == "all" else [args.job]:
        r = ev.evaluate(job, args.sets if args.job != "all" else None, args.models, store=store, fit=args.fit,
                        budget=budget, max_questions=args.max_questions)
        ev.print_report(r)
        print(f"\n  -> {ev.write_report(r).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
