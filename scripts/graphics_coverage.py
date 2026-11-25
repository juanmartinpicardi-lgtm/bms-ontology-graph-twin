"""Graphics coverage of one project, per equipment type: graphic yes/no, points bound to anchors / total, QA result,
and the classes of the points that land on no anchor. Optionally runs the vision QA on one graphic per template.

Usage:
  .venv/bin/python scripts/graphics_coverage.py troop-d/documents
  .venv/bin/python scripts/graphics_coverage.py troop-d/documents --vision     (one model call per template)
  .venv/bin/python scripts/graphics_coverage.py troop-d/documents --write reports/graphics
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.db.store import Store  # noqa: E402
from projectmodel.equipment_view import equipment_payload, load_anchors  # noqa: E402
from projectmodel.graphics.coverage import by_type, equipment_coverage, orphan_points  # noqa: E402
from projectmodel.graphics.equipment2d import render  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.tree import build_tree  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--db", default=str(ROOT / "data" / "kg.sqlite"))
    ap.add_argument("--vision", action="store_true", help="vision QA on the first equipment of each template")
    ap.add_argument("--budget", type=float, default=2.0, help="stop the vision QA past this spend (USD)")
    ap.add_argument("--write", help="write each type's first graphic as SVG and PNG here")
    a = ap.parse_args()
    if "liberty_boe" in a.project:
        sys.exit("liberty_boe is held out")
    store, km, anchors = Store(a.db), load_knowledge_model(), load_anchors()
    tree = build_tree(store, a.project)
    rows = equipment_coverage(store, a.project, km, anchors, tree)
    types = by_type(rows)
    print("| Type | Units | Template | Graphic (2D + 3D) | Points bound | QA |")
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

    firsts = {}
    for r in rows:
        if r.has_2d:
            firsts.setdefault(r.template, r)
    if a.write:
        out = Path(a.write)
        out.mkdir(parents=True, exist_ok=True)
        for tid, r in firsts.items():
            g = render(equipment_payload(store, a.project, r.id, km, anchors, tree))
            (out / f"{tid}.svg").write_text(g.svg("light"))
            (out / f"{tid}.png").write_bytes(g.png("light", 1.5))
        print(f"wrote {len(firsts)} graphics to {out}")
    if a.vision:
        from projectmodel.graphics.vision import vision_check

        spend = 0.0
        for tid, r in firsts.items():
            if spend > a.budget:
                print(f"budget reached (${spend:.2f}); stopped")
                break
            p = equipment_payload(store, a.project, r.id, km, anchors, tree)
            v = vision_check(p, render(p), store=store, project=a.project)
            spend += v["cost_usd"]
            print(f"vision {tid} ({r.label}): {v['detail']} · ${v['cost_usd']:.4f} · {v['latency_s']} s")
            for i in v["issues"]:
                print(f"    {i['card']} {i['problem']}: {', '.join(i['points'])} -> {i['part']} · {i['note']}")
        print(f"vision spend: ${spend:.4f}")


if __name__ == "__main__":
    main()
