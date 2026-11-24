"""Progress per project: layers, overall and next steps from the graph standard; spaces, nameplate and agreement
measured when a building from documents has them; the Roadmap page runs."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from projectmodel import progress, roadmap
from projectmodel.db.store import Claim, Edge, Node, Store
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
    """A tiny building from documents: one floor, two rooms, an AHU feeding a VAV on the schedule, the same two units
    and their feed on the controls submittal, a VAV serving a room the plans and the submittal agree on."""
    store = Store(tmp_path / "kg.sqlite")
    P = "tiny/documents"

    def n(id, kind, label, cls, attrs=None, src="plans.pdf"):
        return Node(id, kind, label, cls, src, "p1", "rule", 0.95, attrs or {})

    def e(s, r, d, src="plans.pdf"):
        return Edge(s, r, d, src, "p1", "rule", 0.95, {"medium": "air"} if r == "feeds" else {})

    def c(s, r="", d=""):
        return Claim(s, "submittal.pdf", "p4", "parsed", 0.95, rel=r, dst=d)

    store.write_source(P, "setup:schedules", 1, [
        n("unit:AHU1", "equipment", "AHU-1", "AHU", {"schedule": "AHU SCHEDULE", "controller": {"device": "AHU-1"}},
          "schedules.pdf"),
        n("unit:VAV1", "equipment", "VAV-1", "VAV", {"schedule": "VAV SCHEDULE", "controller": {"device": "VAV-1"}},
          "schedules.pdf")], [e("unit:AHU1", "feeds", "unit:VAV1", "schedules.pdf")])
    store.write_source(P, "setup:plans", 1, [n("floor:L1", "location", "Level 1", "Floor"),
                                             n("room:101", "location", "101", "Room"),
                                             n("room:102", "location", "102", "Room")],
                       [e("floor:L1", "hasPart", "room:101"), e("floor:L1", "hasPart", "room:102"),
                        e("unit:VAV1", "serves", "room:101")])
    store.write_source(P, "setup:submittal", 1, claims=[c("unit:AHU1"), c("unit:VAV1"),
                                                        c("unit:AHU1", "feeds", "unit:VAV1"),
                                                        c("unit:VAV1", "serves", "room:101")])
    return store


def test_documents_project_measures_spaces_nameplate_and_agreement(tmp_path):
    store, km = _docs_project(tmp_path), load_knowledge_model()
    s = status(store, km, "tiny/documents")
    assert s["spaces"]["pct"] == 100.0 and "2 rooms" in s["spaces"]["note"]
    assert s["serves"]["pct"] == 100.0
    assert s["nameplate"]["pct"] == 100.0
    assert s["agreement"]["pct"] == 100.0  # 2 units, their feed and 1 terminal room, each from two sources: 4 of 4
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
