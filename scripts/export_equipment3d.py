"""Write standalone 3D equipment pages: reports/equipment3d/<site>_<variant>__<equipment>.html.

Usage:
  .venv/bin/python scripts/export_equipment3d.py alpha/names_paths --equip "eq:Airside AHU-2"
  .venv/bin/python scripts/export_equipment3d.py alpha/names_paths --all-ahus
The page embeds the data and follows the system theme; it loads three.js from jsdelivr, so it needs a network
connection.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.db.store import Store  # noqa: E402
from projectmodel.equipment_view import equipment_payload, load_anchors, render_html  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="e.g. alpha/names_paths")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--equip", help='equipment id, e.g. "eq:Airside AHU-2"')
    g.add_argument("--all-ahus", action="store_true")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    args = ap.parse_args()
    store, km, anchors = Store(args.db), load_knowledge_model(), load_anchors()
    ids = [args.equip] if args.equip else sorted(
        r["id"] for r in store.nodes(args.project, "equipment") if '"template": "ahu"' in r["attrs"])
    if not ids:
        sys.exit(f"project {args.project!r} has no AHUs; run the mapper first")
    out_dir = ROOT / "reports/equipment3d"
    out_dir.mkdir(parents=True, exist_ok=True)
    for eid in ids:
        payload = equipment_payload(store, args.project, eid, km, anchors)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", payload["equipment"]["label"]).strip("-")
        out = out_dir / f"{args.project.replace('/', '_')}__{slug}.html"
        out.write_text(render_html(payload))
        placed = sum(1 for p in payload["points"].values() if p["role"])
        print(f"{out.relative_to(ROOT)}  ({placed} placed, {len(payload['unplaced'])} unplaced)")


if __name__ == "__main__":
    main()
