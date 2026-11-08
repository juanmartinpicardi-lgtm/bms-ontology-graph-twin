"""One command: map (unless --no-run) and score the dev and test sets.

Usage:
  .venv/bin/python scripts/score.py                 # map + score alpha (dev) and bravo (test), both variants
  .venv/bin/python scripts/score.py --no-run        # score what is in the database now (e.g. after review)
  .venv/bin/python scripts/score.py --sites alpha --variants names_paths --json

Bravo is the held-out test set: read its numbers, never tune rules or prompts on them.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.adapters.haystack import read_blind_export  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.mapper.llm import get_provider  # noqa: E402
from projectmodel.mapper.pipeline import Mapper  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, load_ground_truth, score_project  # noqa: E402

ROLE = {"alpha": "dev", "bravo": "TEST"}
ROWS = [
    ("H1  grouped on right equipment", "H1_grouped_right_pct", "%"),
    ("    ungrouped points", "H1_points_ungrouped", ""),
    ("H2  class exact (all labelled)", "H2_exact_pct", "%"),
    ("    class compatible (parent/child ok)", "H2_compatible_pct", "%"),
    ("    auto-accepted (share of labelled)", "H2_auto_accepted_pct_of_labelled", "%"),
    ("    class exact among auto-accepted", "H2_auto_accepted_exact_pct", "%"),
    ("    true class not in knowledge model", "H2_unreachable_classes", ""),
    ("Sent to review", "review_pct", "%"),
    ("Decided by a human", "human_decided", ""),
    ("Equipment class exact (matched)", "equipment_class_exact_pct", "%"),
    ("LLM calls", "llm_calls", ""),
    ("Cost per 1,000 points (USD)", "cost_usd_per_1000_points", ""),
    ("Time per 1,000 points (s)", "seconds_per_1000_points", ""),
]


def fmt(v, unit):
    return "-" if v is None else f"{v}{unit}"


def print_report(results: list[dict]) -> None:
    cols = [r["project"] + f" [{ROLE.get(r['project'].split('/')[0], '?')}]" for r in results]
    w = max(38, *(len(c) for c in cols))
    print(f"\nScore report (auto-accept at confidence >= {results[0]['accept_threshold']})\n")
    print(" " * 40 + "".join(c.rjust(w - 8) for c in cols))
    for label, key, unit in ROWS:
        print(label.ljust(40) + "".join(fmt(r[key], unit).rjust(w - 8) for r in results))
    for rel in ("hasPart", "feeds"):
        print(f"{rel} precision / recall".ljust(40) + "".join(
            f"{fmt(r[rel]['precision_pct'], '%')} / {fmt(r[rel]['recall_pct'], '%')}".rjust(w - 8) for r in results))
    print("H2 exact, BMS names / dis fallback".ljust(40) + "".join(
        f"{fmt(r['by_name_source']['source']['exact_pct'], '%')} / {fmt(r['by_name_source']['dis']['exact_pct'], '%')}"
        .rjust(w - 8) for r in results))
    print("\nCalibration: class exact % by confidence band (n)")
    for i, band in enumerate(results[0]["calibration"]):
        print(f"  {band['conf']}".ljust(40) + "".join(
            f"{fmt(r['calibration'][i]['exact_pct'], '%')} ({r['calibration'][i]['n']})".rjust(w - 8) for r in results))
    if any(ROLE.get(r["project"].split("/")[0]) == "TEST" for r in results):
        print("\nTEST columns are held out: do not tune rules, templates or prompts on them.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=["alpha", "bravo"])
    ap.add_argument("--variants", nargs="+", default=["names_paths", "names_only"])
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    ap.add_argument("--accept", type=float, default=DEFAULT_ACCEPT)
    ap.add_argument("--llm", default="none")
    ap.add_argument("--no-run", action="store_true", help="score the database as it is")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    km = load_knowledge_model()
    store = Store(args.db)
    mapper = Mapper(km, llm=get_provider(args.llm))
    results = []
    for site in args.sites:
        gt = load_ground_truth(site)
        for variant in args.variants:
            project = f"{site}/{variant}"
            if not args.no_run:
                mapper.run(read_blind_export(ROOT / "data/blind" / site / f"{variant}.csv"), store, project)
            results.append(score_project(store, project, gt, km, args.accept))
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)
