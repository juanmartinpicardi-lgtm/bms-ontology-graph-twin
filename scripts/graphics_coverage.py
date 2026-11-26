"""Graphics coverage of one project, per equipment type: 3D model yes/no, points bound to anchors / total, binding QA
result, and the classes of the points that land on no anchor.

Usage:
  .venv/bin/python scripts/graphics_coverage.py troop-d/documents
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.db.store import Store  # noqa: E402
from projectmodel.equipment_view import load_anchors  # noqa: E402
from projectmodel.graphics.coverage import by_type, equipment_coverage, orphan_points  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.tree import build_tree  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--db", default=str(ROOT / "data" / "kg.sqlite"))
    a = ap.parse_args()
    if "liberty_boe" in a.project:
        sys.exit("liberty_boe is held out")
    store, km, anchors = Store(a.db), load_knowledge_model(), load_anchors()
    tree = build_tree(store, a.project)
    rows = equipment_coverage(store, a.project, km, anchors, tree)
    types = by_type(rows)
    print("| Type | Units | Template | 3D model | Points bound | QA |")
    print("|---|---|---|---|---|---|")
    for t in types:
        qa = ", ".join(f"{k} {v}" for k, v in sorted(t.qa.items()))
        graphic = "yes" if t.has_graphic else "no" if t.needs_graphic else "not needed"
        print(f"| {t.cls} | {t.count} | {', '.join(t.templates) or '—'} | {graphic} "
              f"| {t.bound}/{t.points} | {qa} |")
    print("\nPoints on no anchor, by class (per type):")
    for t in types:
        if t.unplaced_classes:
            print(f"- {t.cls}: " + ", ".join(f"{c} ×{n}" for c, n in t.unplaced_classes.most_common()))
    total, bound = sum(t.points for t in types), sum(t.bound for t in types)
    print(f"\nAll types: {bound}/{total} points bound ({100 * bound / max(1, total):.1f}%)")
    orphans = orphan_points(tree)
    if orphans:
        print(f"Points on no equipment in the graph (no hasPoint, so on no graphic): {len(orphans)}: "
              + ", ".join(lb for _, lb, _ in orphans))


if __name__ == "__main__":
    main()
