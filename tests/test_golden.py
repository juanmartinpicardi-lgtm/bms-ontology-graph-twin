import csv
import json
from pathlib import Path

import pytest

from projectmodel.golden.load import load_grid

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"mapped", "generic", "ambiguous", "unmapped"}


def test_load_decodes_markers_and_refs():
    _, es = load_grid(ROOT / "data/raw/haystack/alpha.json")
    p = next(e for e in es if e.id == "a-0002")
    assert p.kind == "point"
    assert p.tags["equipRef"] == "a-0001"
    assert "valve" in p.markers
    assert p.custom["description"] == "Clg_Valve_Cmd"


@pytest.mark.parametrize("site", ["alpha", "bravo"])
def test_ground_truth_invariants(site):
    gt = ROOT / "data/ground_truth" / site
    summary = json.loads((gt / "summary.json").read_text())
    points = list(csv.DictReader((gt / "points.csv").open()))
    equips = {r["equip_id"]: r for r in csv.DictReader((gt / "equipment.csv").open())}

    assert len(points) == summary["grid_meta"]["numPoints"]
    assert len(equips) == summary["grid_meta"]["numEquips"]
    assert len({p["point_id"] for p in points}) == len(points)
    for p in points:
        assert p["map_status"] in STATUSES
        assert bool(p["brick_class"]) == (p["map_status"] in {"mapped", "generic"})
        assert not p["equip_id"] or p["equip_id"] in equips
    for r in points + list(equips.values()):
        assert r["method"] in {"brickschema", "human"}
        assert bool(r["override_id"]) == (r["method"] == "human")
    for r in csv.DictReader((gt / "equip_relations.csv").open()):
        assert r["src"] in equips and r["dst"] in equips


def test_every_override_rule_is_used_somewhere():
    data = json.loads((ROOT / "data/ground_truth/overrides.json").read_text())
    rules = {r["id"] for r in data["rules"] + data.get("corrections", [])}
    unused = [
        set(json.loads((ROOT / "data/ground_truth" / s / "summary.json").read_text())["overrides_unused_here"])
        for s in ("alpha", "bravo")
    ]
    assert rules and not set.intersection(*unused)
