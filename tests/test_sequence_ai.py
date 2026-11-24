"""Sequences with AI (W8): the candidate ids a sequence's logic may use, the rules' own reading, the sequence_read
job's checks, the merge, gaps and conflicts as issues, publishing as the setup's own source, and the score against
the hand-built Troop D key. Every model here is scripted: nothing leaves the machine. Offline, nothing changes."""
import copy
import json
import shutil

import pytest

from projectmodel.ai import Router, Scripted, jobs, set_default_router
from projectmodel.ai.config import AIConfig
from projectmodel.ai.prompts import load_prompt
from projectmodel.db.store import Store
from projectmodel.intake import model, publish, sequence_ai, sequence_links, steps
from projectmodel.intake.state import Intake
from projectmodel.knowledge_model import CONTROL_RELATIONS
from projectmodel.scoring import sequences as sq

READY = AIConfig(project="test-project")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not steps.TEST_PACKAGE.exists():
        pytest.skip("test package missing")
    root = tmp_path_factory.mktemp("seq_ai")
    it = Intake.create("Troop D seq", root=root)
    for s in steps.STEPS[:-1]:
        f = steps.TEST_PACKAGE / s.test_file
        it.add_file(s.id, f.name, f.read_bytes())
        steps.run(it, s.id, lambda m: None)
    return it


@pytest.fixture
def intake(built, tmp_path):
    """A fresh copy of the built Troop D setup, for tests that change it."""
    shutil.copytree(built.dir, tmp_path / built.slug)
    return Intake(built.slug, root=tmp_path)


@pytest.fixture(scope="module")
def qs(built):
    return {q.seq["id"]: q for q in sequence_ai.questions(model.building(built))}


def test_relations_are_the_declared_ones():
    assert sequence_ai.RELATIONS == CONTROL_RELATIONS


def test_type_of():
    assert [sequence_links.type_of(t) for t in ("AHU01", "CH01a", "VAVE-07", "EF-LAB-1", "EF-RR", "CHW-PLANT")] == \
        ["AHU", "CH", "VAVE", "EF-LAB", "EF-RR", "CHW-PLANT"]


def test_candidates(qs):
    assert len(qs) == 5
    vav = qs["seq:vav-terminal-units"].cands
    assert vav["types"] == ["VAV"]  # VAV and VAVE boxes are one type of terminal unit
    htg = vav["points"]["VAV.HTG-O"]
    assert (len(htg["units"]), htg["of"]) == (19, 38)  # only the VAVE boxes have electric heat
    assert "AHU.OCC-SCHEDULE" in vav["points"] and not vav["points"]["AHU.OCC-SCHEDULE"]["own"]  # fed by AHU01
    chw = qs["seq:chilled-water-system"].cands
    assert {"CHW-PLANT.CW-F", "CH.LCHWT-SP", "CWP.C"} <= set(chw["points"])  # the plant controller no unit owns
    assert {"unit:CH", "unit:CWP", "unit:AHU"} <= set(chw["units"])
    ahu = qs["seq:air-handling-unit"].cands
    assert "unit:CWP" in ahu["units"]  # "the chilled water pump shall be enabled" ties the pumps in
    assert ahu["points"]["AHU.DA-T"]["own"] and ahu["roles"]
    kinds = qs["seq:air-handling-unit"].values["candidate_kinds"]
    assert kinds["AHU.DA-SP"] == "setpoint" and kinds["AHU.DA-T"] == "point" and kinds["unit:CWP"] == "unit"


def test_prompt_renders_every_placeholder(qs):
    req, prompt = jobs.job_request("sequence_read", qs["seq:air-handling-unit"].values)
    user = req.messages[0]["content"]
    assert prompt.ref == load_prompt("sequence_read").ref and "$" not in user
    assert "L. Safety Control" in user and "AHU.LT-A" in user and "unit:CWP" in user
    job = jobs.get_job("sequence_read")
    assert job.status == "built" and job.contender[0] == "hydrogen" and job.schema is sequence_ai.SCHEMA


def test_rules_alone(qs):
    rels = {(r["from"], r["rel"], r["to"]) for q in qs.values() for r in q.rules}
    assert ("AHU.HSP-A", "requires", "AHU.SF-C") in rels  # a safety
    assert ("AHU.DA-P", "feedback", "AHU.SF-O") in rels  # a loop
    assert ("AHU.SF1-S", "requires", "EF-RR.C") in rels  # "interlocked with AHU01"


def rel(a, r, z, kind="loop", sec="G", conf=0.9):
    return {"from": a, "rel": r, "to": z, "kind": kind, "loop": "", "section": sec, "confidence": conf, "why": "w"}


def test_relation_checks():
    kinds = {"A.SP": "setpoint", "A.T": "point", "A.O": "point", "unit:P": "unit", "role:A.x": "role"}
    p = sequence_ai.relation_problem
    assert p(rel("A.SP", "drives", "A.O"), kinds) is None
    assert p(rel("A.T", "feedback", "role:A.x"), kinds) is None
    assert "not a candidate" in p(rel("A.SP", "drives", "B.O"), kinds)
    assert "declared" in p(rel("A.SP", "controls", "A.O"), kinds)
    assert "equipment" in p(rel("A.O", "requests", "A.T"), kinds)
    assert "only requests" in p(rel("A.O", "requires", "unit:P"), kinds)
    assert "setpoint" in p(rel("A.T", "resets", "A.O"), kinds)
    assert p(rel("A.T", "resets", "A.SP"), kinds) is None
    ok = {"relations": [rel("A.SP", "drives", "A.O")] * 3 + [rel("X", "drives", "A.O")], "gaps": [], "conflicts": []}
    assert sequence_ai.check(ok, {"candidate_kinds": kinds}) is None  # one bad in four: dropped later, not refused
    bad = dict(ok, relations=ok["relations"][:2] + [rel("X", "drives", "A.O")] * 2)
    assert "fail the checks" in sequence_ai.check(bad, {"candidate_kinds": kinds})


def answer_for(q, extra=()):
    """A scripted answer: the first own setpoint (or sensor) drives (or feeds back to) the first own output."""
    pts = q.cands["points"].values()
    sp = next((p["id"] for p in pts if p["own"] and p["setpoint"]), None)
    pv = next(p["id"] for p in pts if p["own"] and p["io"] in ("AI", "BI"))
    out = next(p["id"] for p in pts if p["own"] and p["io"] in ("AO", "BO"))
    first = rel(sp, "drives", out, conf=0.95) if sp else rel(pv, "feedback", out, conf=0.95)
    return {"relations": [first, *extra],
            "gaps": [{"section": "G", "text": "Discharge air 90 °F has no setpoint point"}],
            "conflicts": [{"sections": ["C", "F"], "text": "C runs the fans always, F only on pressure"}]}


def test_merge_checks_caps_and_adds_the_rules_gaps(qs):
    q = copy.copy(qs["seq:vav-terminal-units"])
    a = answer_for(q, [rel("VAV.ZN-T", "feedback", "VAV.HTG-O", conf=0.97), rel("VAV.NOPE", "drives", "VAV.DPR-O")])
    q.answer = {"output": a, "model": "hydrogen", "calls": [1], "cost_usd": 0.01}
    m = sequence_ai.merge(q, calibrate=False)
    llm = [r for r in m["relations"] if r["method"] == "llm"]
    assert len(llm) == 2 and all(r["confidence"] <= sequence_ai.AI_CAP for r in llm)
    assert [d["from"] for d in m["dropped"]] == ["VAV.NOPE"]
    assert any("VAV.HTG-O is on 19 of the 38" in g["text"] and g["by"] == "rule" for g in m["gaps"])
    assert {g["by"] for g in m["gaps"]} == {"llm", "rule"} and m["conflicts"]
    issues = sequence_ai.issues(q, m)
    assert issues and all(i["kind"] == "issue" and i["ask"] and i["id"].startswith("issue:ai-") for i in issues)


def test_offline_publish_is_unchanged(intake, tmp_path, monkeypatch):
    monkeypatch.setattr(sequence_ai, "DB", tmp_path / "never.sqlite")
    before = json.dumps(intake.s, sort_keys=True, default=str)
    store = Store(tmp_path / "kg.sqlite")
    pid = publish.publish(intake, store)
    assert "setup:sequence_logic" not in store.sources(pid)
    assert not [e for e in store.edges(pid) if e["rel"] in CONTROL_RELATIONS]
    after = json.loads(json.dumps(intake.s, default=str))
    after.pop("published"), after.pop("updated")
    was = json.loads(before)
    was.pop("updated")
    assert after == was
    assert not (tmp_path / "never.sqlite").exists()


def test_online_reading_publishes_proposed_ba_edges(intake, tmp_path, monkeypatch):
    monkeypatch.setattr(sequence_ai, "DB", tmp_path / "calls.sqlite")
    b = model.building(intake)
    answers = [json.dumps(answer_for(q)) for q in sequence_ai.questions(b)]
    r = Router(READY, providers={"claude": Scripted(answers)})
    calls = Store(":memory:")
    s = sequence_ai.read(intake, router=r, store=calls)
    assert s["asked"] == 5 and s["relations"] >= 5 and s["gaps"] >= 5 and s["conflicts"] == 5
    ai_issues = [f for f in intake.facts("sequences", kind="issue") if f["id"].startswith("issue:ai-")]
    assert ai_issues and all(f["status"] == "proposed" and f["ask"] for f in ai_issues)
    assert calls.conn.execute("SELECT COUNT(*) FROM llm_calls WHERE job = 'sequence_read'").fetchone()[0] == 5
    # The answers are saved with the building: publishing asks nothing again.
    set_default_router(Router(READY, providers={"claude": Scripted([])}))
    try:
        store = Store(tmp_path / "kg.sqlite")
        pid = publish.publish(intake, store)
    finally:
        set_default_router(None)
    assert "setup:sequence_logic" in store.sources(pid)
    edges = [e for e in store.edges(pid) if e["source"] == "setup:sequence_logic"]
    assert edges and {e["rel"] for e in edges} <= set(CONTROL_RELATIONS)
    assert all(e["status"] == "proposed" and e["confidence"] <= 0.85 for e in edges)
    assert {e["method"] for e in edges} == {"llm", "rule"}  # the rules' relations the model did not read otherwise
    nodes = {n["id"] for n in store.nodes(pid)}
    assert all(e["src"] in nodes and e["dst"] in nodes for e in edges)
    vav = [e for e in edges if json.loads(e["attrs"])["sequence"] == "seq:vav-terminal-units"]
    assert len(vav) >= 19  # one relation of the typical, on every box that has both points
    # Re-publishing one step leaves the sequence logic as it is (W3: each source replaces only its own rows).
    n = len(edges)
    publish.publish(intake, store, steps=["bms"])
    assert len([e for e in store.edges(pid) if e["source"] == "setup:sequence_logic"]) == n


def test_key_and_scoring():
    key = sq.load_key("troop_d")
    rels = [r for s in key["sequences"].values() for r in sq.key_relations(s)]
    assert len(key["sequences"]) == 5 and len(rels) == 86 and sum(not r["optional"] for r in rels) == 67
    k = [{"from": frozenset({"A"}), "rel": frozenset({"requires"}), "to": frozenset({"F1", "F2"}), "kind": "interlock",
          "section": "L", "optional": False, "name": ""},
         {"from": frozenset({"B"}), "rel": frozenset({"switches"}), "to": frozenset({"C"}), "kind": "mode",
          "section": "C", "optional": True, "name": ""}]
    ans = [rel("A", "requires", "F1"), rel("A", "requires", "F2"), rel("B", "switches", "C"), rel("X", "drives", "Y")]
    s = sq.score(ans, k)
    assert (s["tp"], s["dup"], s["fp"], s["found"], s["required"]) == (2, 1, 1, 1, 1)
    assert sq.gaps_found([{"section": "G", "text": "No setpoint point for the 90 °F discharge air temperature"}],
                         [{"section": "G", "text": "Reheat discharge air temperature 90 °F: no setpoint point"}]) == [True]
    assert sq.conflicts_found([{"sections": ["F", "C"], "text": "x"}], [{"sections": ["C", "F", "G"], "text": "y"}]) == \
        [True]


def test_eval_rules_row_offline():
    """scripts/eval.py sequence_read with model calls off: the rules' row against the key, the model rows skipped."""
    from projectmodel.scoring import eval as ev

    r = ev.evaluate("sequence_read", log=lambda m: None)
    rules = r["rows"][0]
    assert r["key"]["required"] == 67 and rules["kind"] == "rules"
    assert rules["precision_pct"] >= 60 and rules["recall_pct"] < 30  # rules read few loops, mostly right
    job = jobs.get_job("sequence_read")
    assert len(r["skipped"]) == len(job.chain) + len(job.contender)
    with pytest.raises(ValueError):
        ev.evaluate("sequence_read", ["liberty_boe"], log=lambda m: None)
