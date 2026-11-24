"""Export a project's knowledge graph as Brick Turtle and print its SHACL report (work package W2).

    .venv/bin/python scripts/export_brick.py alpha                      # confirmed rows of alpha/names_paths
    .venv/bin/python scripts/export_brick.py troop_d --include-proposed # Troop D from its test package, all rows
    .venv/bin/python scripts/export_brick.py alpha/names_only --out /tmp/alpha.ttl

The Turtle file (default data/export/<project>.<scope>.ttl) holds the facts in Brick terms and, as reified
statements, the provenance of every node and edge. It is read back and its node and edge counts checked. SHACL runs
Brick 1.4.4's own shapes and the building rules in knowledge_model/shapes/. The report goes to
reports/shacl/<project>.json, which the Complete graph page reads. Nothing is written back to the store.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.export import run as export_run  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="alpha, troop_d, or a project id in the store (e.g. alpha/names_only)")
    ap.add_argument("--out", type=Path, help="where to write the Turtle file")
    ap.add_argument("--include-proposed", action="store_true", help="export proposed rows as well as confirmed ones")
    ap.add_argument("--store", type=Path, default=export_run.STORE, help="the SQLite store (default data/kg.sqlite)")
    ap.add_argument("--report-dir", type=Path, default=export_run.REPORT_DIR)
    ap.add_argument("--engine", choices=["shifty", "topquadrant", "pyshacl"], help="SHACL engine (default: brickschema's)")
    args = ap.parse_args()
    km = load_knowledge_model()
    report = export_run.run(args.project, km, include_proposed=args.include_proposed, out=args.out,
                            report_dir=args.report_dir, store_path=args.store, engine=args.engine)
    print(export_run.text(report))
    return 0 if report["roundtrip"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
