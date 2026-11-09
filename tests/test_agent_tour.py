"""The agent tour: the walk is read from the graph (zone -> AHU -> chilled water plant -> lead chiller), every point the
agent reads resolves to a real point, and the page renders and runs in the app.
Runs on the mapped Alpha graph in data/kg.sqlite (skipped when it has not been built)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from projectmodel.agent_tour import ROLES, render_html, tour_payload
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"

pytestmark = pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")


@pytest.fixture(scope="module")
def payload():
    return tour_payload(Store(DB), load_knowledge_model())


def test_the_walk_follows_the_graph(payload):
    p = payload["path"]
    assert p == {"zone": "eq:Airside AHU-2/VAV 1-2-81", "ahu": "eq:Airside AHU-2",
                 "plant": "eq:Waterside Chilled Water Plant", "others": ["eq:Waterside Hot Water Plant"],
                 "chiller": "eq:Waterside Chilled Water Plant/CH-1"}
    assert len(payload["vavs"][p["ahu"]]) == 88  # the neighbours it checks
    assert set(payload["ahus"]) == {f"eq:Airside AHU-{i}" for i in range(2, 6)}
    assert all(payload["edges"].values()), "every hop has an edge with provenance"


def test_every_point_the_agent_reads_exists(payload):
    for key, roles in payload["roles"].items():
        t = payload["equipment"][key]["equipment"]["template"]
        assert list(roles) == ROLES[t]
        for role, pid in roles.items():
            assert pid in payload["equipment"][key]["points"], f"{key}.{role}"
    # with two points in one slot, the most confident wins: SAT, not a misread "Enthalpy"
    ahu = payload["equipment"]["ahu"]["points"]
    assert ahu[payload["roles"]["ahu"]["supply_temp"]]["label"] == "SAT"


def test_page_is_self_contained(payload):
    html = render_html(payload, "dark")
    assert "/*__DATA__*/null" not in html.split("const DATA = ", 1)[1][:20]
    assert "/*__SIM__*/" not in html and "const Sim = " in html
    assert '<html lang="en" data-theme="dark">' in html
    assert "</script>" not in html.split("const DATA = ", 1)[1].split("\n", 1)[0]  # the inlined viewer can't close it


def test_runs_in_the_app():
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/main.py"), default_timeout=60)
    at.switch_page("views/agent_tour.py").run()
    assert not at.exception
