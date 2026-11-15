"""Onboarding walk: nine steps told on Alpha, every real item counted on its graph, simulated items marked, and the
page steps through them. Runs on the mapped Alpha graph in data/kg.sqlite (skipped when absent)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.onboarding import LAYERS, steps

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"
P = "alpha/names_paths"

pytestmark = pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")


@pytest.fixture(scope="module")
def walk():
    return steps(Store(DB), load_knowledge_model(), P)


def test_nine_steps_in_workflow_order(walk):
    assert [s["id"] for s in walk] == ["locate", "drop", "read", "assets", "spaces", "connect", "sequences", "review",
                                       "use"]
    assert [s["n"] for s in walk] == list(range(9))
    for s in walk:
        assert s["status"] in ("real", "partly", "simulated") and set(s["layers"]) <= set(LAYERS)
        assert s["submitted"] and s["created"] and s["what"]


def test_status_matches_the_items(walk):
    for s in walk:
        items = s["submitted"] + s["created"]
        if s["status"] == "real":
            assert all(i["real"] for i in items), s["id"]
        if s["status"] == "simulated":
            assert not any(i["real"] for i in s["created"]), s["id"]
    by = {s["id"]: s for s in walk}
    assert by["spaces"]["status"] == "simulated" and by["use"]["status"] == "real"


def test_numbers_come_from_the_graph(walk):
    store = Store(DB)
    by = {s["id"]: s for s in walk}
    points, equip = len(store.nodes(P, "point")), len(store.nodes(P, "equipment"))
    assert by["assets"]["totals"] | {"Equipment": equip, "Points": points} == by["assets"]["totals"]
    assert sum(r["Count"] for r in by["assets"]["table"]["rows"]) == equip
    assert sum(r["Equipment"] for r in by["spaces"]["table"]["rows"]) == equip
    assert by["use"]["totals"]["Relationships"] == len(store.edges(P))
    assert by["locate"]["created"][0]["detail"].startswith("La Pièce 16, 1180 Rolle")


def test_totals_only_grow(walk):
    for a, b in zip(walk, walk[1:]):
        assert all(b["totals"][k] >= v for k, v in a["totals"].items())
    assert not any(walk[0]["totals"].values())


def test_page_steps_through():
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/views/new_project.py"), default_timeout=60).run()
    assert not at.exception
    assert any("0. Locate the building" in m.value for m in at.markdown)
    at.button(key="onb_3").click().run()
    assert not at.exception
    assert any("3. Build the assets" in m.value for m in at.markdown)
    assert at.metric[1].value == "184"
