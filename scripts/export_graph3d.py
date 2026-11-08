"""Write a standalone 3D viewer page for one project: reports/graph3d/<site>_<variant>.html.

Usage: .venv/bin/python scripts/export_graph3d.py alpha/names_paths [--db data/kg.sqlite]
The page embeds the graph data; it loads the 3D library from jsdelivr, so it needs a network connection.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.viz import graph_payload, render_html  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="e.g. alpha/names_paths")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    args = ap.parse_args()
    payload = graph_payload(Store(args.db), args.project, load_knowledge_model())
    if not payload["nodes"]:
        sys.exit(f"project {args.project!r} has no nodes; run the mapper first")
    out = ROOT / "reports/graph3d" / (args.project.replace("/", "_") + ".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(payload))
    print(f"{out.relative_to(ROOT)}  ({out.stat().st_size / 1e6:.1f} MB, {payload['counts']})")


if __name__ == "__main__":
    main()
