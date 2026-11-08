"""Validate the knowledge model and report its coverage of the Alpha dev set.

Usage: .venv/bin/python scripts/validate_km.py

Only Alpha is measured: Bravo is the held-out test set and must not drive changes here.
"""

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.knowledge_model import KnowledgeModelError, load_knowledge_model  # noqa: E402

if __name__ == "__main__":
    try:
        km = load_knowledge_model()
    except KnowledgeModelError as e:
        print(e)
        sys.exit(1)

    kinds = Counter((c.source, c.kind) for c in km.classes.values())
    print(f"Knowledge model OK (Brick {km.brick_version})")
    print(f"  Brick subset: {kinds[('brick', 'equipment')]} equipment + {kinds[('brick', 'point')]} point classes, "
          f"{len(km.relations)} relations")
    print(f"  BA extension: {sum(v for (s, _), v in kinds.items() if s == 'ba')} classes, {len(km.ba_relations)} relations")
    print(f"  Templates: {', '.join(sorted(km.templates))}")
    print(f"  Name rules: {len(km.name_rules.vocabulary)} words, {len(km.name_rules.abbreviations)} abbreviations, "
          f"{len(km.name_rules.examples)} examples pass")

    # Alpha coverage
    with (ROOT / "data/ground_truth/alpha/points.csv").open() as f:
        points = list(csv.DictReader(f))
    labelled = [p for p in points if p["brick_class"]]
    in_model = [p for p in labelled if p["brick_class"] in km.classes]
    missing = Counter(p["brick_class"] for p in labelled if p["brick_class"] not in km.classes)
    print(f"\nAlpha (dev) ground-truth point classes in the model: {len(in_model)}/{len(labelled)} points")
    for cls, n in missing.most_common():
        print(f"  not in model: {cls} ({n})")

    with (ROOT / "data/blind/alpha/names_only.csv").open() as f:
        names = [r["name"] for r in csv.DictReader(f)]
    tokens = [t for n in names for t in km.name_rules.tokenize(n) if not t.isdigit()]
    unknown = Counter(t for n in names for t in km.name_rules.unknown_tokens(n))
    print(f"Alpha name tokens understood: {len(tokens) - sum(unknown.values())}/{len(tokens)}")
    print("  most common unknown: " + ", ".join(f"{t} ({n})" for t, n in unknown.most_common(15)))
