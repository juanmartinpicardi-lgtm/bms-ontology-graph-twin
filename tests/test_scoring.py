from pathlib import Path

import pytest

from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Edge, Node, Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.scoring.score import GroundTruth, load_ground_truth, match_equipment, score_project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


def test_match_is_one_to_one_by_overlap():
    true = {"p1": "A", "p2": "A", "p3": "A", "p4": "B"}
    # g1 holds most of A, g2 the rest of A plus B's point: g2 must not also claim A
    assert match_equipment({"g1": ["p1", "p2"], "g2": ["p3", "p4"]}, true) == {"g1": "A", "g2": "B"}
    # one predicted group merging A and B gets only one of them
    assert match_equipment({"g": ["p1", "p2", "p3", "p4"]}, true) == {"g": "A"}


def _toy(store: Store, project: str, points: list[tuple[str, str | None, float, str, str]]):
    """points: (source_id, class, confidence, method, group)."""
    nodes, edges = [], []
    for g in {p[4] for p in points}:
        nodes.append(Node(g, "equipment", g, "VAV", "f", g, "parsed", 1.0))
    for sid, cls, conf, method, g in points:
        nodes.append(Node(f"pt:{sid}", "point", sid, cls, "f", "1", method, conf, {"source_id": sid}))
        edges.append(Edge(g, "hasPoint", f"pt:{sid}", "f", "1", "parsed", 1.0))
    rev = store.start_run(project, "f")
    store.replace_machine_rows(project, rev, nodes, edges)
    store.finish_run(project, rev, 0.5, {})


def test_scores_on_toy_project(km):
    gt = GroundTruth(
        points={"t1": {"equip_id": "E1", "brick_class": "Zone_Air_Temperature_Sensor"},
                "t2": {"equip_id": "E1", "brick_class": "Damper_Command"},
                "t3": {"equip_id": "E2", "brick_class": "Air_Flow_Sensor"},
                "t4": {"equip_id": "E2", "brick_class": ""}},
        equipment={"E1": {"brick_class": "VAV"}, "E2": {"brick_class": "VAV"}},
        relations=set(),
        key={f"b{i}": {"point_id": f"t{i}", "name_source": "source"} for i in range(1, 5)},
    )
    store = Store(":memory:")
    _toy(store, "toy", [
        ("b1", "Zone_Air_Temperature_Sensor", 0.95, "rule", "g1"),   # right group, right class, accepted
        ("b2", "Damper_Position_Command", 0.9, "rule", "g1"),        # child of true class: compatible only
        ("b3", "Air_Flow_Sensor", 0.3, "rule", "g1"),                # wrong group, right class, to review
        ("b4", None, 0.0, "rule", "g2"),                             # no truth class; to review
    ])
    s = score_project(store, "toy", gt, km, accept=0.8)
    assert s["H1_grouped_right_pct"] == 75.0  # g1 -> E1 (2 pts), g2 -> E2 (1 pt), b3 sits on g1
    assert s["H2_labelled_points"] == 3
    assert s["H2_exact_pct"] == round(100 * 2 / 3, 1)
    assert s["H2_compatible_pct"] == 100.0
    assert s["H2_auto_accepted_exact_pct"] == 50.0
    assert s["review_pct"] == 50.0
    assert s["seconds_per_1000_points"] == 125.0


def test_human_decisions_count_as_accepted(km):
    gt = GroundTruth({"t1": {"equip_id": "E1", "brick_class": "Damper_Command"}}, {"E1": {"brick_class": "VAV"}},
                     set(), {"b1": {"point_id": "t1", "name_source": "source"}})
    store = Store(":memory:")
    _toy(store, "toy", [("b1", "Damper_Command", 0.1, "human", "g1")])
    s = score_project(store, "toy", gt, km, accept=0.8)
    assert s["review_pct"] == 0.0 and s["H2_auto_accepted_exact_pct"] == 100.0 and s["human_decided"] == 1


def test_alpha_end_to_end_report(km):
    store = Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), store, "alpha/names_paths")
    s = score_project(store, "alpha/names_paths", load_ground_truth("alpha"), km, accept=0.8)
    assert s["H1_grouped_right_pct"] == 100.0
    assert s["hasPart"]["precision_pct"] == s["hasPart"]["recall_pct"] == 100.0
    assert 0 < s["H2_exact_pct"] <= 100 and s["cost_usd_per_1000_points"] == 0.0
