from pathlib import Path

import pytest

from projectmodel import review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Edge, Node, Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.tree import UNPLACED, build_tree

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture
def store(km):
    s = Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), s, P)
    return s


def test_every_node_appears_once(store):
    tree = build_tree(store, P)
    equip = [n.id for n in tree.walk() if n.id != UNPLACED]
    points = [p.id for n in tree.walk() for p in n.points]
    assert sorted(equip) == sorted(r["id"] for r in store.nodes(P, "equipment"))
    assert sorted(points) == sorted(r["id"] for r in store.nodes(P, "point"))


def test_parts_nest_and_carry_provenance(store):
    tree = build_tree(store, P)
    ahu = tree.by_id["eq:Airside AHU-2"]
    assert "eq:Airside AHU-2/SF VFD" in [c.id for c in ahu.children]
    sf = tree.by_id["eq:Airside AHU-2/SF VFD"]
    assert [n.id for n in tree.path(sf.id)][-2:] == ["eq:Airside AHU-2", sf.id]
    assert sf.via["method"] == "parsed" and sf.via["source_file"] == "data/blind/alpha/names_paths.csv"
    pt = ahu.points[0]
    assert pt.prov["source_ref"].isdigit() and pt.prov["method"] in ("rule", "template", "parsed")
    assert ahu.total_points >= len(ahu.points) + len(sf.points)


def test_moved_point_shows_under_new_equipment_with_human_provenance(store):
    pid = store.nodes(P, "point")[0]["id"]
    target = "eq:Airside AHU-2"
    review.move_points(store, P, [pid], target, "ana")
    tree = build_tree(store, P)
    assert tree.parent[pid] == target
    assert tree.by_id[pid].via["method"] == "human" and tree.by_id[pid].via["review"]["by"] == "ana"
    assert sum(1 for n in tree.walk() for p in n.points if p.id == pid) == 1


def test_unplaced_points_and_cycles():
    s = Store(":memory:")
    rev = s.start_run("t", "x.csv")
    mk = lambda i, kind: Node(i, kind, i, None, "x.csv", "1", "parsed", 1.0)  # noqa: E731
    nodes = [mk("eq:a", "equipment"), mk("eq:b", "equipment"), mk("pt:1", "point")]
    edges = [Edge("eq:a", "hasPart", "eq:b", "x.csv", "a", "parsed", 1.0),
             Edge("eq:b", "hasPart", "eq:a", "x.csv", "b", "parsed", 1.0)]
    s.replace_machine_rows("t", rev, nodes, edges)
    tree = build_tree(s, "t")
    assert {n.id for n in tree.walk()} == {"eq:a", "eq:b", UNPLACED}
    assert [p.id for p in tree.by_id[UNPLACED].points] == ["pt:1"]
