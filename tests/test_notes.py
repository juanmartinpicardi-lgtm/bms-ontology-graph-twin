from pathlib import Path

import pytest

from projectmodel import notes
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.viz import graph_payload

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"
CSV = ROOT / "data/blind/alpha/names_paths.csv"
AHU = "eq:Airside AHU-2"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture(scope="module")
def records():
    return read_blind_export(CSV)


@pytest.fixture
def store(km, records):
    s = Store(":memory:")
    Mapper(km).run(records, s, P)
    return s


def test_crud_and_status(store):
    nid = notes.add_note(store, P, "node", AHU, "Airside AHU-2", "history", "Replaced in 2022.", "ana")
    assert [n["body"] for n in notes.notes_for(store, P, "node", AHU)] == ["Replaced in 2022."]
    notes.update_note(store, nid, "Replaced in 2022; RF VFD unused.", topic="maintenance")
    n = notes.get_note(store, nid)
    assert (n["body"], n["topic"], n["source"], n["status"]) == \
        ("Replaced in 2022; RF VFD unused.", "maintenance", "manual", "active")
    notes.set_status(store, nid, "resolved")
    assert notes.notes_by_project(store, P) == []                       # default: active only
    assert len(notes.notes_by_project(store, P, status=None)) == 1      # never deleted
    assert notes.notes_for(store, P, "node", AHU, "resolved")[0]["id"] == nid


def test_project_and_edge_targets(store):
    notes.add_note(store, P, "project", "ignored", "project alpha", "other", "Site visit 2026-10.", "bo")
    assert notes.notes_for(store, P, "project", "")[0]["target_id"] == ""
    e = store.edges(P, "hasPart")[0]
    eid = notes.edge_id(e["src"], e["rel"], e["dst"])
    notes.add_note(store, P, "edge", eid, "link", "operations", "Valve sticks.", "bo")
    assert notes.active_counts(store, P) == {("project", ""): 1, ("edge", eid): 1}
    assert notes.orphaned(store, P) == []


def test_validation(store):
    with pytest.raises(ValueError, match="topic"):
        notes.add_note(store, P, "node", AHU, "x", "gossip", "body", "ana")
    with pytest.raises(ValueError, match="body"):
        notes.add_note(store, P, "node", AHU, "x", "other", "  ", "ana")
    with pytest.raises(ValueError, match="author"):
        notes.add_note(store, P, "node", AHU, "x", "other", "body", "")
    with pytest.raises(ValueError, match="status"):
        notes.set_status(store, 1, "deleted")


def test_notes_survive_mapper_rerun(store, km, records):
    pid = store.nodes(P, "point")[0]["id"]
    notes.add_note(store, P, "node", pid, "pt", "naming", "CC means chiller condenser here.", "ana")
    notes.add_note(store, P, "node", AHU, "Airside AHU-2", "history", "Replaced 2022.", "ana")
    Mapper(km).run(records, store, P)
    assert len(notes.notes_by_project(store, P)) == 2
    assert notes.orphaned(store, P) == []


def test_removed_source_node_orphans_its_note(store, km, records):
    gone = records[0]
    nid = notes.add_note(store, P, "node", f"pt:{gone.source_id}", gone.name, "other", "Check this one.", "ana")
    assert notes.orphaned(store, P) == []
    Mapper(km).run(records[1:], store, P)
    orphans = notes.orphaned(store, P)
    assert [o["id"] for o in orphans] == [nid]
    assert orphans[0]["target_label"] == gone.name   # still reads well without its node


def test_payload_note_counts(store):
    e = store.edges(P, "hasPart")[0]
    eid = notes.edge_id(e["src"], e["rel"], e["dst"])
    notes.add_note(store, P, "node", AHU, "Airside AHU-2", "history", "One.", "ana")
    notes.add_note(store, P, "node", AHU, "Airside AHU-2", "operations", "Two.", "ana")
    gone = notes.add_note(store, P, "node", AHU, "Airside AHU-2", "other", "Three, resolved.", "ana")
    notes.set_status(store, gone, "resolved")
    notes.add_note(store, P, "edge", eid, "link", "operations", "Link note.", "ana")
    g = graph_payload(store, P)
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id[AHU]["notes"] == 2
    assert sum(n["notes"] for n in g["nodes"]) == 2
    link = next(lk for lk in g["links"] if (lk["source"], lk["rel"], lk["target"]) == (e["src"], e["rel"], e["dst"]))
    assert link["notes"] == 1
    assert [x["body"] for x in g["notes"][AHU]] == ["One.", "Two."]
    assert g["notes"][eid][0]["topic"] == "operations"
