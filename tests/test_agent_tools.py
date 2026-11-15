"""Agent tools: an agent can find a zone, read its points with roles and trust, walk to what feeds it, and read the
behaviour the sequences state, all as JSON. Runs on the mapped Alpha graph in data/kg.sqlite (skipped when absent)."""

import json
from pathlib import Path

import pytest

from projectmodel.agent_tools import TOOLS, GraphTools, call, trust
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"
VAV, AHU = "eq:Airside AHU-2/VAV 1-2-81", "eq:Airside AHU-2"

pytestmark = pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")


@pytest.fixture(scope="module")
def tools():
    return GraphTools(Store(DB), load_knowledge_model(), "alpha/names_paths")


def test_trust_levels():
    assert trust({"method": "human", "confidence": 0.2}) == "verified"
    assert trust({"method": "document", "confidence": 1.0}) == "stated"
    assert trust({"method": "template", "confidence": 0.85}) == "likely"
    assert trust({"method": "rule", "confidence": 0.5}) == "unsure"


def test_find_by_name_and_class(tools):
    hit = tools.find_nodes("vav 1-2-81", kind="equipment")
    assert hit["total"] == 1 and hit["nodes"][0]["id"] == VAV
    assert tools.find_nodes(cls="VAV", kind="equipment")["total"] == 138
    temps = tools.find_nodes("1-2-81", cls="Temperature_Sensor")  # a parent class finds its subclasses
    assert any(n["class"] == "Zone_Air_Temperature_Sensor" and n["equipment"]["id"] == VAV for n in temps["nodes"])


def test_describe_equipment(tools):
    d = tools.describe(VAV)
    assert d["class"] == "VAV" and d["template"] == "vav" and d["part_of"]["id"] == AHU
    assert {"zone_temp", "airflow", "damper"} <= {p["role"] for p in d["points"]}
    assert all(p["trust"] in ("verified", "likely", "unsure") for p in d["points"])
    assert any(f["id"] == AHU and f["medium"] == "air" for f in d["fed_by"])
    assert d["missing_required_points"] == []
    assert len(tools.describe(AHU)["feeds"]) == 88


def test_describe_point(tools):
    pid = next(p["id"] for p in tools.describe(VAV)["points"] if p["role"] == "damper")
    d = tools.describe(pid)
    assert d["role"] == "damper" and d["equipment"]["id"] == VAV and d["source"]["source_ref"]
    assert any(f["loop"] == "Airflow" for f in d["behaviour"])


def test_walks(tools):
    up = {n["id"]: n for n in tools.upstream(VAV)["nodes"]}
    assert up[AHU]["steps"] == 1
    assert up["eq:Waterside Chilled Water Plant"] == up["eq:Waterside Chilled Water Plant"] | {"steps": 2, "via": AHU}
    assert {n["id"] for n in tools.upstream(VAV, medium="air")["nodes"]} == {AHU}
    assert tools.downstream(AHU, medium="air")["total"] == 88


def test_behaviour(tools):
    b = tools.behaviour(VAV)
    assert {f["relation"] for f in b["facts"]} >= {"drives", "feedback"}
    assert all(f["trust"] == "stated" and f["sequences"] for f in b["facts"])
    other = tools.behaviour("eq:Airside AHU-3/VAV 1-3-1")  # the demo sequences bind one VAV only
    assert other["facts"] == [] and other["note"]


def test_call_is_json_and_reports_errors(tools):
    for t in TOOLS:
        assert t["input_schema"]["type"] == "object"
    json.dumps(call(tools, "describe", {"node_id": AHU}))
    assert "error" in call(tools, "describe", {"node_id": "eq:nope"})
    assert "error" in call(tools, "delete_everything")
    assert "error" in call(tools, "describe", {"wrong": 1})
