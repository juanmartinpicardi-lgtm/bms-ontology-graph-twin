from pathlib import Path

import pytest

from projectmodel import km_explorer as kx
from projectmodel import review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.scoring.score import load_ground_truth

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


def mapped(km, site):
    s, p = Store(":memory:"), f"{site}/names_paths"
    Mapper(km).run(read_blind_export(ROOT / f"data/blind/{site}/names_paths.csv"), s, p)
    return s, p


@pytest.fixture(scope="module")
def alpha(km):
    return mapped(km, "alpha")


def test_hierarchy_lists_every_class_once_under_its_parent(km):
    h = kx.hierarchy(km)
    assert sorted(c for c, _ in h) == sorted(km.classes)
    pos = {c: i for i, (c, _) in enumerate(h)}
    depth = dict(h)
    for c, info in km.classes.items():
        if info.subset_parent:
            assert pos[info.subset_parent] < pos[c] and depth[c] == depth[info.subset_parent] + 1


def test_class_coverage_counts_and_accuracy(km, alpha):
    store, p = alpha
    rows = {r["class"]: r for r in kx.class_coverage(km, store, p, load_ground_truth("alpha"))}
    assert rows["VAV"]["instances"] == 138 and "vav" in rows["VAV"]["used by templates"]
    assert sum(r["instances"] for r in rows.values() if r["kind"] == "point") <= 1842
    z = rows["Zone_Air_Temperature_Sensor"]
    assert z["precision %"] is not None and 0 <= z["recall %"] <= 100
    # Without ground truth the accuracy columns are empty, not zero.
    assert kx.class_coverage(km, store, p)[0]["precision %"] is None


def test_human_decisions_show_in_coverage(km, alpha):
    store, p = mapped(km, "alpha")
    pid = store.nodes(p, "point")[0]["id"]
    review.fix_class(store, km, p, [pid], "Zone_Air_Temperature_Sensor", "ana")
    rows = {r["class"]: r for r in kx.class_coverage(km, store, p)}
    assert rows["Zone_Air_Temperature_Sensor"]["human decided"] == 1


def test_missing_classes_are_outside_the_model(km):
    store, p = mapped(km, "alpha")
    gt = load_ground_truth("alpha")
    assert kx.missing_classes(km, store, p, gt) == []  # Alpha's classes are all in the model
    pid = next(i for i, r in gt.points.items() if r["brick_class"] == "Zone_Air_Temperature_Sensor")
    gt.points[pid] = gt.points[pid] | {"brick_class": "CO2_Sensor"}
    rows = kx.missing_classes(km, store, p, gt)
    assert [r["class"] for r in rows] == ["CO2_Sensor"] and all(r["class"] not in km.classes for r in rows)
    assert all(r["nearest model class"] in km.classes for r in rows if r["nearest model class"])


def test_template_fit_and_relations(km, alpha):
    store, p = alpha
    fit = {t["template"]: t for t in kx.template_fit(km, store, p)}
    assert set(fit) == set(km.templates)
    vav = fit["vav"]
    assert vav["instances"] == 138
    zone = next(s for s in vav["slots"] if s["role"] == "zone_temp")
    assert zone["required"] and zone["filled %"] > 90
    rel = kx.relation_usage(km, store, p)
    ahu_vav = next(r for r in rel if (r["source class"], r["relation"], r["target class"]) == ("AHU", "feeds", "VAV"))
    assert ahu_vav["links"] == 138 and ahu_vav["expected by a template"]
    assert any(r["links"] == 0 and r["expected by a template"] for r in rel)  # expected but never found


def test_class_detail_shows_place_and_confusions(km, alpha):
    store, p = alpha
    d = kx.class_detail(km, store, p, "Damper_Command", load_ground_truth("alpha"))
    assert d["ancestors"][-1] == "Point" and "Damper_Position_Command" in d["children"]
    assert d["definition"] and d["examples"]
    assert all(said != "Damper_Command" for said, _ in d["truly this, mapper said"])


def test_unknown_tokens_sorted_by_frequency(alpha):
    store, p = alpha
    rows = kx.unknown_tokens(store, p)
    assert rows and [r["points"] for r in rows] == sorted((r["points"] for r in rows), reverse=True)
