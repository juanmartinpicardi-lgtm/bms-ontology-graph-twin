"""Progress per project: layers, overall and next steps from the graph standard; spaces, nameplate and agreement
measured when a building from documents has them; the Roadmap page runs."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from projectmodel import progress, roadmap
from projectmodel.db.store import Store
from projectmodel.graph_standard import FACTS, LAYERS, status
from projectmodel.knowledge_model import load_knowledge_model

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"
needs_db = pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")


def test_every_fact_has_a_next_step_and_packages_exist():
    assert set(progress.NEXT) == {f["id"] for f in FACTS}
    for action, page, pkg in progress.NEXT.values():
        assert action
        assert pkg is None or pkg in roadmap.BY_ID, pkg
        assert page is None or (ROOT / "src/projectmodel/app" / page).exists(), page
    assert {p["wave"] for p in roadmap.PACKAGES} <= set(roadmap.WAVES)


def _docs_project(tmp_path) -> Store:
    """A tiny building from documents: one floor, two rooms, an AHU on a schedule and the riser, a VAV serving a
    room the plans and the submittal agree on."""
    store = Store(tmp_path / "kg.sqlite")
    P = "tiny/documents"
    prov = ("plans.pdf", "p1", "rule", 0.95, "confirmed", 1)
    nodes = [("floor:L1", "location", "Level 1", "Floor", {}), ("room:101", "location", "101", "Room", {}),
             ("room:102", "location", "102", "Room", {}),
             ("unit:AHU1", "equipment", "AHU-1", "AHU", {"schedule": "AHU SCHEDULE", "controller": {"device": "AHU-1"}}),
             ("unit:VAV1", "equipment", "VAV-1", "VAV", {"schedule": "VAV SCHEDULE", "controller": {"device": "VAV-1"},
                                                         "room_source": "plan + submittal agree"})]
    edges = [("floor:L1", "hasPart", "room:101"), ("floor:L1", "hasPart", "room:102"),
             ("unit:VAV1", "serves", "room:101"), ("unit:AHU1", "feeds", "unit:VAV1")]
    with store.conn:
        store.conn.executemany(
            "INSERT INTO nodes (project, id, kind, label, class, source_file, source_ref, method, confidence, status,"
            " revision, attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(P, i, k, lab, c, *prov, json.dumps(a)) for i, k, lab, c, a in nodes])
        store.conn.executemany(
            "INSERT INTO edges (project, src, rel, dst, source_file, source_ref, method, confidence, status, revision,"
            " attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(P, s, r, d, *prov, json.dumps({"medium": "air"} if r == "feeds" else {})) for s, r, d in edges])
    return store


def test_documents_project_measures_spaces_nameplate_and_agreement(tmp_path):
    store, km = _docs_project(tmp_path), load_knowledge_model()
    s = status(store, km, "tiny/documents")
    assert s["spaces"]["pct"] == 100.0 and "2 rooms" in s["spaces"]["note"]
    assert s["serves"]["pct"] == 100.0
    assert s["nameplate"]["pct"] == 100.0
    assert s["agreement"]["pct"] == 100.0  # 2 units on schedule + riser, 1 terminal room agreed: 3 of 3
    r = progress.summarize(s, "tiny/documents")
    assert not r["demo"]
    assert [lay["id"] for lay in r["layers"]] == [lay["id"] for lay in LAYERS]
    assert next(lay for lay in r["layers"] if lay["id"] == "spaces")["pct"] == 100.0
    assert all(n["fact"] not in ("spaces", "serves", "nameplate", "agreement") for n in r["next"])


@needs_db
def test_alpha_is_the_demo_and_gets_documents_next_steps():
    r = progress.project_progress(Store(DB), load_knowledge_model(), "alpha/names_paths")
    assert r["demo"] and 0 < r["overall"] < 100
    assert r["next"] and r["next"][0]["fact"] == "spaces"  # a BMS export has no floor plans
    assert all(n["in_app"] for n in r["next"]) or not any(n["in_app"] for n in r["next"][1:])  # doable first


@needs_db
def test_roadmap_page_runs():
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/views/roadmap.py"), default_timeout=120).run()
    assert not at.exception
