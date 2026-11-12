"""One command: map (unless --no-run) and score the dev set.

Usage:
  .venv/bin/python scripts/score.py                 # map + score alpha (dev), both variants
  .venv/bin/python scripts/score.py --no-run        # score what is in the database now (e.g. after review)
  .venv/bin/python scripts/score.py --sites alpha --variants names_paths --json
  .venv/bin/python scripts/score.py --compare      # every project twice: blind, then with its conventions

Each project runs with its convention layers (conventions/projects.yaml). A site with role TEST is
always reported twice, blind and with conventions (spec-tribal-knowledge.md section 4.3); the database
keeps the with-conventions run. There is no test site at the moment.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.adapters.haystack import read_blind_export  # noqa: E402
from projectmodel.conventions import apply_conventions, load_layers, scopes_for  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.mapper.llm import get_provider  # noqa: E402
from projectmodel.mapper.pipeline import Mapper  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, load_ground_truth, score_project  # noqa: E402

ROLE = {"alpha": "dev"}
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


def column(r: dict) -> str:
    tag = ROLE.get(r["project"].split("/")[0], "?")
    if r.get("label"):
        tag += ", " + r["label"]
    return f"{r['project']} [{tag}]"


def print_report(results: list[dict]) -> None:
    cols = [column(r) for r in results]
    w = max(30, *(len(c) for c in cols)) + 2
    print(f"\nScore report (auto-accept at confidence >= {results[0]['accept_threshold']})\n")
    print(" " * 40 + "".join(c.rjust(w) for c in cols))
    print("conventions".ljust(40) + "".join(
        (", ".join(r["conventions"]) or "none").rjust(w) for r in results))
    for label, key, unit in ROWS:
        print(label.ljust(40) + "".join(fmt(r[key], unit).rjust(w) for r in results))
    for rel in ("hasPart", "feeds"):
        print(f"{rel} precision / recall".ljust(40) + "".join(
            f"{fmt(r[rel]['precision_pct'], '%')} / {fmt(r[rel]['recall_pct'], '%')}".rjust(w) for r in results))
    print("H2 exact, BMS names / dis fallback".ljust(40) + "".join(
        f"{fmt(r['by_name_source']['source']['exact_pct'], '%')} / {fmt(r['by_name_source']['dis']['exact_pct'], '%')}"
        .rjust(w) for r in results))
    print("\nCalibration: class exact % by confidence band (n)")
    for i, band in enumerate(results[0]["calibration"]):
        print(f"  {band['conf']}".ljust(40) + "".join(
            f"{fmt(r['calibration'][i]['exact_pct'], '%')} ({r['calibration'][i]['n']})".rjust(w) for r in results))
    if any(ROLE.get(r["project"].split("/")[0]) == "TEST" for r in results):
        print("\nTEST columns are held out: do not tune rules, templates or prompts on them.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=["alpha"])
    ap.add_argument("--variants", nargs="+", default=["names_paths", "names_only"])
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    ap.add_argument("--accept", type=float, default=DEFAULT_ACCEPT)
    ap.add_argument("--llm", default="none")
    ap.add_argument("--no-run", action="store_true", help="score the database as it is")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--compare", action="store_true", help="report every project blind and with conventions")
    args = ap.parse_args()

    km = load_knowledge_model()  # the bare model; scoring always uses it, so columns stay comparable
    store = Store(args.db)
    llm = get_provider(args.llm)
    results = []
    for site in args.sites:
        gt = load_ground_truth(site)
        for variant in args.variants:
            project = f"{site}/{variant}"
            if args.no_run:
                results.append(score_project(store, project, gt, km, args.accept))
                continue
            records = read_blind_export(ROOT / "data/blind" / site / f"{variant}.csv")
            runs = [("with conventions", apply_conventions(km, load_layers(scopes_for(project))))]
            if args.compare or ROLE.get(site) == "TEST":
                runs.insert(0, ("blind", km))
            for label, run_km in runs:
                Mapper(run_km, llm=llm).run(records, store, project)
                results.append(score_project(store, project, gt, km, args.accept)
                               | {"label": label if len(runs) > 1 else ""})
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)
