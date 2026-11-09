"""Validate the knowledge model and report its coverage of the Alpha dev set.

Usage: .venv/bin/python scripts/validate_km.py [--project alpha/names_paths]

Only Alpha is measured: Bravo is the held-out test set and must not drive changes here.
"""

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.knowledge_model import KnowledgeModelError, load_knowledge_model  # noqa: E402


def check_anchors(km) -> bool:
    """3D anchor map: every slot role of a drawn equipment type has an anchor, and every anchor a real role and part."""
    from projectmodel.equipment_view import anchor_problems, load_anchors

    anchors = load_anchors()
    problems = anchor_problems(km, anchors)
    for p in problems:
        print(f"  {p}")
    undrawn = sorted(set(km.templates) - set(anchors))
    print(f"\n3D anchors: {'OK' if not problems else f'{len(problems)} problem(s)'} for {', '.join(sorted(anchors))}"
          f"{'; no 3D model yet: ' + ', '.join(undrawn) if undrawn else ''}")
    return not problems


def check_conventions(project: str) -> int:
    """`--project <site>/<variant>`: validate the knowledge model merged with that project's convention
    layers (conventions/projects.yaml), with the same rules. Returns the exit code."""
    from projectmodel.conventions import ConventionError, layer_entries, load_layers, scopes_for

    try:
        scopes = scopes_for(project)
        km = load_knowledge_model(conventions=scopes)
    except ConventionError as e:
        print(e)
        return 1
    except KnowledgeModelError as e:
        print(e)
        return 1
    print(f"Knowledge model + conventions OK for {project}: {' <- '.join(['knowledge model'] + km.conventions)}")
    for row in layer_entries(load_layers(scopes)):
        print(f"  {row['scope']:<24} {row['kind']:<19} {row['key']} -> {row['value']}")
    return 0


if __name__ == "__main__" and "--project" in sys.argv:
    sys.exit(check_conventions(sys.argv[sys.argv.index("--project") + 1]))

if __name__ == "__main__":
    try:
        km = load_knowledge_model()
    except KnowledgeModelError as e:
        print(e)
        sys.exit(1)

    kinds = Counter((c.source, c.kind) for c in km.classes.values())
    print(f"Knowledge model OK (Brick {km.brick_version})")
    print(f"  Brick subset: {kinds[('brick', 'equipment')]} equipment + {kinds[('brick', 'point')]} point + "
          f"{kinds[('brick', 'system')]} system classes, {len(km.relations)} relations")
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

    if not check_anchors(km):
        sys.exit(1)
