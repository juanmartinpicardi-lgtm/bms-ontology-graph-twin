"""Leak checks: the blind inputs must not carry any tag, ref, id or class that gives the answer away."""

import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITES = ["alpha", "bravo"]
VARIANTS = {"names_only.csv": ["blind_id", "name"], "names_paths.csv": ["blind_id", "name", "path"]}
HAYSTACK_ID = re.compile(r"\b[a-z]-[0-9a-f]{4}\b")
HAYSTACK_REF_TAG = re.compile(r"\b[a-z][A-Za-z]*Ref\b")  # equipRef, siteRef, airRef...


def _read(path):
    with path.open() as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def _ground_truth(site):
    gt = ROOT / "data/ground_truth" / site
    points = {r["point_id"]: r for r in _read(gt / "points.csv")[1]}
    equips = {r["equip_id"]: r for r in _read(gt / "equipment.csv")[1]}
    key = {r["blind_id"]: r for r in _read(gt / "blind_key.csv")[1]}
    return points, equips, key


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize("variant", VARIANTS)
def test_only_allowed_columns(site, variant):
    cols, _ = _read(ROOT / "data/blind" / site / variant)
    assert cols == VARIANTS[variant]


@pytest.mark.parametrize("site", SITES)
def test_blind_dir_holds_only_the_two_inputs(site):
    assert sorted(p.name for p in (ROOT / "data/blind" / site).iterdir()) == sorted(VARIANTS)


@pytest.mark.parametrize("site", SITES)
def test_key_covers_every_ground_truth_point_once(site):
    points, _, key = _ground_truth(site)
    assert sorted(r["point_id"] for r in key.values()) == sorted(points)
    for variant in VARIANTS:
        _, rows = _read(ROOT / "data/blind" / site / variant)
        assert [r["blind_id"] for r in rows] == list(key)


@pytest.mark.parametrize("site", SITES)
def test_variants_share_names(site):
    _, a = _read(ROOT / "data/blind" / site / "names_only.csv")
    _, b = _read(ROOT / "data/blind" / site / "names_paths.csv")
    assert [(r["blind_id"], r["name"]) for r in a] == [(r["blind_id"], r["name"]) for r in b]


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize("variant", VARIANTS)
def test_no_ids_refs_tags_or_classes(site, variant):
    points, equips, key = _ground_truth(site)
    # Single-word classes (VAV, AHU, Pump) are ordinary BMS vocabulary; a leak is a Brick identifier.
    brick_classes = {r["brick_class"] for r in list(points.values()) + list(equips.values()) if "_" in r["brick_class"]}
    tag_strings = {r["haystack_tags"] for r in list(points.values()) + list(equips.values())}
    site_name = site.capitalize()
    _, rows = _read(ROOT / "data/blind" / site / variant)
    for r in rows:
        for col, v in r.items():
            if col == "blind_id":
                continue
            assert not HAYSTACK_ID.search(v), (r, "haystack id")
            assert not HAYSTACK_REF_TAG.search(v), (r, "ref tag")
            assert not any(c in v for c in brick_classes), (r, "Brick class")
            assert v not in tag_strings, (r, "tag set")
            assert site_name not in v.split(), (r, "site-prefixed dis")
        p = points[key[r["blind_id"]]["point_id"]]
        if p["equip_dis"]:
            assert r["name"] != p["dis"], (r, "full dis")
            assert p["equip_dis"] not in r["name"], (r, "equipment dis in name")


def _spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=v.__getitem__)
        out = [0] * len(v)
        for rank, i in enumerate(order):
            out[i] = rank
        return out
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    return 1 - 6 * sum((a - b) ** 2 for a, b in zip(rx, ry)) / (n * (n * n - 1))


@pytest.mark.parametrize("site", SITES)
def test_row_order_does_not_follow_source_order(site):
    points, _, key = _ground_truth(site)
    source_rows = [int(points[k["point_id"]]["source_row"]) for k in key.values()]
    assert abs(_spearman(list(range(len(source_rows))), source_rows)) < 0.1


@pytest.mark.parametrize("site", SITES)
def test_paths_follow_equipment(site):
    """Variant (b) is allowed to reveal grouping: one folder per equipment, no folder shared."""
    points, _, key = _ground_truth(site)
    _, rows = _read(ROOT / "data/blind" / site / "names_paths.csv")
    folder_to_equip = {}
    for r in rows:
        equip = points[key[r["blind_id"]]["point_id"]]["equip_id"]
        assert bool(r["path"]) == bool(equip)
        if r["path"]:
            assert folder_to_equip.setdefault(r["path"], equip) == equip
