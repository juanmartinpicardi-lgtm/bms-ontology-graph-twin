import json
from pathlib import Path

import pytest

from projectmodel import review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.scoring.score import load_ground_truth, score_project

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture
def mapped(km):
    store = Store(":memory:")
    recs = read_blind_export(ROOT / "data/blind/alpha/names_paths.csv")
    Mapper(km).run(recs, store, P)
    return store, recs


def _node(store, nid):
    return store.conn.execute("SELECT * FROM nodes WHERE project = ? AND id = ?", (P, nid)).fetchone()


def _wrong_points(store, gt, n=None):
    """Point ids whose class disagrees with ground truth, and the true class of each."""
    out = []
    for r in store.nodes(P, "point"):
        sid = json.loads(r["attrs"])["source_id"]
        true = gt.points[gt.key[sid]["point_id"]]["brick_class"]
        if true and r["class"] != true:
            out.append((r["id"], true))
    return out[:n] if n else out


def test_fix_accept_reject_record_human_provenance(mapped, km):
    store, _ = mapped
    ids = [r["id"] for r in store.nodes(P, "point")][:3]
    review.fix_class(store, km, P, [ids[0]], "Zone_Air_Temperature_Sensor", "ana")
    review.accept(store, P, [ids[1]], "ana")
    review.reject(store, P, [ids[2]], "ana")
    fixed, acc, rej = (_node(store, i) for i in ids)
    assert (fixed["class"], fixed["method"], fixed["status"], fixed["confidence"]) == \
        ("Zone_Air_Temperature_Sensor", "human", "confirmed", 1.0)
    assert acc["method"] == "human" and acc["status"] == "confirmed"
    assert rej["method"] == "human" and rej["status"] == "rejected"
    a = json.loads(fixed["attrs"])["review"]
    assert a["by"] == "ana" and a["action"] == "fix" and a["previous"]["method"] in ("rule", "template")


def test_fix_refuses_unknown_or_wrong_kind_class(mapped, km):
    store, _ = mapped
    pid = store.nodes(P, "point")[0]["id"]
    with pytest.raises(ValueError, match="not a class"):
        review.fix_class(store, km, P, [pid], "Not_A_Class", "ana")
    with pytest.raises(ValueError, match="equipment class"):
        review.fix_class(store, km, P, [pid], "AHU", "ana")


def test_score_updates_after_review(mapped, km):
    store, _ = mapped
    gt = load_ground_truth("alpha")
    before = score_project(store, P, gt, km, 0.8)
    wrong = _wrong_points(store, gt, 50)
    for pid, true in wrong:
        review.fix_class(store, km, P, [pid], true, "ana")
    after = score_project(store, P, gt, km, 0.8)
    assert after["H2_exact_pct"] > before["H2_exact_pct"]
    assert after["human_decided"] == before["human_decided"] + len(wrong)
    assert after["review_pct"] <= before["review_pct"]


def test_review_survives_mapper_rerun(mapped, km):
    store, recs = mapped
    points = store.nodes(P, "point")
    pid, other = points[0]["id"], points[1]["id"]
    review.fix_class(store, km, P, [pid], "Zone_Air_Temperature_Sensor", "ana")
    target = next(n["id"] for n in store.nodes(P, "equipment") if n["label"].startswith("VAV"))
    review.move_points(store, P, [other], target, "ana")
    Mapper(km).run(recs, store, P)  # rerun
    assert _node(store, pid)["class"] == "Zone_Air_Temperature_Sensor"
    placed = [e for e in store.edges(P, "hasPoint") if e["dst"] == other and e["status"] != "rejected"]
    assert [e["src"] for e in placed] == [target]
    assert len(store.nodes(P, "point")) == len(recs)


def test_move_rejects_old_edge(mapped):
    store, _ = mapped
    pid = store.nodes(P, "point")[0]["id"]
    old = next(e["src"] for e in store.edges(P, "hasPoint") if e["dst"] == pid)
    target = next(n["id"] for n in store.nodes(P, "equipment") if n["id"] != old)
    review.move_points(store, P, [pid], target, "ana")
    edges = {(e["src"], e["status"]) for e in store.edges(P, "hasPoint") if e["dst"] == pid}
    assert edges == {(old, "rejected"), (target, "confirmed")}
    with pytest.raises(ValueError):
        review.move_points(store, P, [pid], "eq:does-not-exist", "ana")
