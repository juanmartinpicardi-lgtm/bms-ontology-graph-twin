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



@pytest.fixture(scope="module")
def tools():
    if not DB.exists():
        pytest.skip("run scripts/run_mapper.py first")
    return GraphTools(Store(DB), load_knowledge_model(), "alpha/names_paths")


def test_trust_levels():
    assert trust({"method": "human", "confidence": 0.2}) == "verified"
    assert trust({"method": "rule", "confirmed_by": "human", "status": "confirmed", "confidence": 0.3}) == "verified"
    assert trust({"method": "parsed", "confirmed_by": "agreement", "status": "confirmed", "confidence": 0.9}) == "agreed"
    assert trust({"method": "rule", "confirmed_by": "auto", "status": "confirmed", "confidence": 1.0}) == "accepted"
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
    assert all(p["trust"] in ("verified", "accepted", "likely", "unsure") for p in d["points"])
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


# W11: documents, sequences, checks, graphics and the "runs as designed" recipe, on Troop D --------------------------
# The Troop D graph of the agent eval (agent/projects.py): the test package read by the setup's rules, plus W8's
# sequence logic from the frozen sequence_read answers. No model is called.

AHU1, P = "unit:AHU1", "pt:TROOPD-NAE01/FC-1.AHU-1."


@pytest.fixture(scope="module")
def td(tmp_path_factory):
    from projectmodel.agent.projects import build_troop_d
    store, project, docs = build_troop_d(tmp_path_factory.mktemp("agent_td"))
    return GraphTools(store, load_knowledge_model(), project, docs)


def test_troop_d_has_w8_control_relations(td):
    rels = {(e["src"], e["rel"], e["dst"]) for e in td.control_edges}
    assert (P + "DA-SP", "drives", P + "CHWV-O") in rels and (P + "DA-T", "feedback", P + "CHWV-O") in rels
    assert all(e["status"] == "proposed" for e in td.control_edges)  # a person confirms the logic


def test_source_page_of_a_unit(td):
    s = td.source_page(AHU1)
    assert s["cite"] == "src:2_equipment_schedules.pdf#p1" and s["sheet"] == "M-401" and s["page"] == 1
    assert s["found"] and len(s["bbox"]) == 4
    assert {a["source"] for a in s["also_stated_in"]} >= {"setup:plans", "setup:submittal"}
    png = td.docs.crop_png(s["file"], s["page"], s["bbox"])
    assert png[:4] == b"\x89PNG"
    sec = td.source_page("seq:air-handling-unit/K")
    assert sec["cite"] == "src:3_sequences.pdf#p1" and "53 deg F" in sec["text"]
    with pytest.raises(KeyError):
        td.source_page("seq:air-handling-unit/Z")


def test_read_sequence(td):
    r = td.read_sequence(AHU1)
    mine = [s for s in r["sequences"] if s["applies_to_unit"]]
    assert [s["cite"] for s in mine] == ["seq:air-handling-unit"] and mine[0]["sheet"] == "M-304"
    k = next(x for x in mine[0]["sections"] if x["letter"] == "K")
    assert k["cite"] == "seq:air-handling-unit/K" and "53 °F" in k["setpoints"]
    assert any(i["kind"] == "conflict" for i in mine[0]["issues"])
    assert any(s["cite"] == "seq:chilled-water-system" for s in r["sequences"] if not s["applies_to_unit"])
    assert r["relations_read_by"] == ["hydrogen"]
    assert "text" in td.read_sequence(AHU1, section="E")["sequences"][0]["sections"][3]


def test_run_check(td):
    r = td.run_check(AHU1)
    fails = {x["cite"] for x in r["results"] if x["status"] == "fail"}
    assert f"check:class|{P}CHWV-O" in fails  # an analog output classed as a flow sensor
    assert r["summary"]["binding"] == {"pass": 1, "fail": 0}  # 54 points on the AHU's controller, all BACnet objects
    ef = td.run_check("unit:EFLAB", ["binding"])
    assert ef["summary"]["binding"]["fail"] > 5  # EF-LAB-1's points sit on no equipment
    c = td.run_check("unit:FVAV1", ["conflicts"])["results"][0]
    assert c["cite"] == "check:conflict|unit:FVAV1" and "104" in c["message"] and "108" in c["message"]
    assert c["relation"] == "rel:unit:FVAV1|serves|room:104"


def test_show_graphic(td):
    g = td.show_graphic(P + "DA-T")  # a point shows its unit's graphic
    assert g["cite"] == "graphic:unit:AHU1" and g["available"] and g["query"]["equip"] == AHU1
    assert td.resolve("graphic:unit:AHU1")["kind"] == "graphic"


def test_diagnose_ahu1(td):
    d = td.diagnose(AHU1)
    steps = {s["step"]: s for s in d["steps"]}
    assert list(steps) == ["sequence", "loops", "interlocks", "setpoints", "checks", "gaps_and_conflicts", "operation"]
    assert steps["operation"]["status"] == "unknown" and "unknown" in d["verdict"]
    k = next(lp for lp in steps["loops"]["loops"] if lp["section"] == "K")
    assert k["status"] == "problem" and any("CHWV-O" in p for p in k["problems"])
    vals = {(v["section_cite"], v.get("point")): v for v in steps["setpoints"]["values"] if v.get("point")}
    da = vals[("seq:air-handling-unit/K", P + "DA-SP")]
    assert da["status"] == "agree" and da["schedule"]["status"] == "agree"  # 53 °F; the schedule's 53.1 LAT
    assert vals[("seq:air-handling-unit/F", P + "BLDGP-SP")]["status"] == "agree"
    assert vals[("seq:air-handling-unit/G", P + "MA-SP")]["status"] == "differ"  # 60 °F economizer: no such point
    assert vals[("seq:air-handling-unit/E", P + "DAP-SP")]["status"] == "no value"  # set by the TAB engineer
    assert not any(v["status"] == "differ" and "J" in v["section_cite"] for v in vals.values())  # 40 %RH: threshold
    for cite in [*steps["sequence"]["cite"], da["cite"], *steps["operation"]["cite"]]:
        assert td.resolve(cite) is not None, cite


def test_resolve_rejects_made_up_ids(td):
    assert td.resolve("unit:NOPE") is None and td.resolve("rel:unit:AHU1|feeds|unit:NOPE") is None
    assert td.resolve("seq:nope") is None and td.resolve("src:nope.pdf#p1") is None
    assert td.resolve(f"rel:{P}DA-SP|drives|{P}CHWV-O")["kind"] == "relation"


def test_rules_evidence_covers_the_question_set(td):
    from projectmodel.scoring import agent as sa
    key = sa.load_key("troop_d")
    for q in key["questions"]:
        found, _ = sa.rules_evidence(td, q)
        missing = [f["id"] for f in q["facts"] if f.get("cite") and not f.get("optional") and not found[f["id"]]]
        assert not missing, (q["id"], missing)


def test_answer_scoring():
    from projectmodel.scoring import agent as sa
    q = {"facts": [{"id": "a", "answer": ["53"], "cite": ["check:setpoint.K|*"]},
                   {"id": "b", "answer": ["fire alarm"], "cite": ["issue:*"], "optional": True}],
         "forbid": [r"\bis running\b"]}
    s = sa.score_answer(q, "Holds 53 °F [[check:setpoint.K|pt:X]] and is running.", ["check:setpoint.K|pt:X", "u:1"],
                        ["u:1"])
    assert s["answer"] == 1.0 and s["citation"] == 1.0 and s["precision"] == 0.5 and s["forbidden"]
    assert sa.score_answer(q, "Holds 53 °F.", [], [])["citation"] == 0.0


def _dock_answer(root: str):
    """An answered turn in the dock, citing a page, a sequence section, a check, a point and a made-up id."""
    import json as _json
    from pathlib import Path as _Path

    from projectmodel.agent.documents import DocumentIndex
    from projectmodel.agent_tools import GraphTools as _GT
    from projectmodel.app import agent_ui
    from projectmodel.db.store import Store as _Store
    from projectmodel.intake.state import Intake
    from projectmodel.knowledge_model import load_knowledge_model as _km

    meta = _json.loads((_Path(root) / "build.json").read_text())
    docs = DocumentIndex(meta["project"], Intake(meta["slug"], root=_Path(root) / "intake"))
    tools = _GT(_Store(_Path(root) / "troop_d.sqlite"), _km(), meta["project"], docs)
    p = "pt:TROOPD-NAE01/FC-1.AHU-1.DA-SP"
    cited = ["src:2_equipment_schedules.pdf#p1", "seq:air-handling-unit/K", f"check:setpoint.K|{p}", p, "unit:NOPE"]
    tools.diagnose("unit:AHU1")
    agent_ui._show({"role": "assistant", "text": " ".join(f"Fact [[{c}]] *likely*." for c in cited), "cited": cited,
                    "bad_cites": ["unit:NOPE"], "steps": []}, tools)


def test_dock_shows_citations_as_pages_and_links(td, tmp_path_factory):
    from streamlit.testing.v1 import AppTest
    root = str(td.docs.intake.dir.parent.parent)
    at = AppTest.from_function(_dock_answer, args=(root,), default_timeout=60).run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    pages = [c for img in at.get("image") for c in img.proto.imgs and [img.proto.imgs[0].caption]]
    assert "2_equipment_schedules.pdf · M-401 · page 1" in pages  # the schedule page, cropped around AHU01's row
    assert any(c.startswith("3_sequences.pdf · M-304") for c in pages)  # section K, and the setpoint check's point
    assert len(at.get("popover")) == 4  # one per cited id that a tool returned
    assert "not from a tool" in text  # the made-up id is struck through
    assert "agrees with the sequence" in text  # the check's own text
