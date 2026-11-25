"""Write standalone 3D equipment pages: reports/equipment3d/<site>_<variant>__<equipment>.html.

Usage:
  .venv/bin/python scripts/export_equipment3d.py alpha/names_paths --equip "eq:Airside AHU-2"
  .venv/bin/python scripts/export_equipment3d.py alpha/names_paths --all-ahus
  .venv/bin/python scripts/export_equipment3d.py alpha/names_paths --all      (every equipment with a 3D model)
  .venv/bin/python scripts/export_equipment3d.py troop-d/documents --one-per-type
The page embeds the data and follows the system theme; it loads three.js from jsdelivr, so it needs a network
connection.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.db.store import Store  # noqa: E402
from projectmodel.equipment_view import equipment_payload, load_anchors, node_template, render_html  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.tree import build_tree  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="e.g. alpha/names_paths")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--equip", help='equipment id, e.g. "eq:Airside AHU-2"')
    g.add_argument("--all-ahus", action="store_true")
    g.add_argument("--all", action="store_true", help="every equipment with a 3D model (every template in anchors.yaml)")
    g.add_argument("--one-per-type", action="store_true", help="the first equipment of each template (and variant)")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    args = ap.parse_args()
    store, km, anchors = Store(args.db), load_knowledge_model(), load_anchors()
    tree = build_tree(store, args.project)
    models = {n.id: getattr(node_template(n, km), "id", None) for n in tree.by_id.values() if n.kind == "equipment"}
    models = {i: t for i, t in models.items() if t in anchors}
    if args.one_per_type:  # first of each template, and of each family within it (VAV vs FVAV)
        firsts = {}
        for i in sorted(models):
            firsts.setdefault((models[i], tree.by_id[i].attrs.get("family")), i)
        ids = sorted(firsts.values())
    else:
        ids = [args.equip] if args.equip else sorted(i for i, t in models.items() if args.all or t == "ahu")
    if not ids:
        sys.exit(f"project {args.project!r} has no equipment with a 3D model; run the mapper first")
    out_dir = ROOT / "reports/equipment3d"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Pages link to each other by file name (from the id, which is unique: "eq:Airside AHU-2/VAV 1-2-1"), for the
    # pages written now and those already in the folder.
    name = lambda i: f"{args.project.replace('/', '_')}__{re.sub(r'[^A-Za-z0-9]+', '-', i.removeprefix('eq:')).strip('-')}.html"  # noqa: E731
    links = {i: name(i) for i in models if i in ids or (out_dir / name(i)).exists()}
    for eid in ids:
        payload = equipment_payload(store, args.project, eid, km, anchors, tree)
        payload["links"] = {k: v for k, v in links.items() if k != eid}
        out = out_dir / name(eid)
        out.write_text(render_html(payload))
        placed = sum(1 for p in payload["points"].values() if p["role"])
        print(f"{out.relative_to(ROOT)}  ({placed} placed, {len(payload['unplaced'])} unplaced)")


if __name__ == "__main__":
    main()
