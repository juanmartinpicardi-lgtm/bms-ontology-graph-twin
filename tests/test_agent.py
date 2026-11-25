"""Context engine and text agent (spec-agent §4-5, phases A1-A2), with scripted models: no network.

The agent loop is checked for what matters to a person: it calls the graph tools the model asks for, streams text,
hands over to Opus when the question or the walk is long, logs every call, stops cleanly on errors, and keeps the
conversation valid for the next question."""

import json
import sqlite3

import pytest

from projectmodel.agent.chat import HANDOVER, MAX_STEPS, SKILL_TOOL, Agent, citations
from projectmodel.agent.context import Chip, Ref, ScreenState, chips_for, context_packet, level_of, merge_chips
from projectmodel.ai import ModelResponse, ModelUnavailable, Router, Scripted
from projectmodel.ai.config import AIConfig
from projectmodel.ai.providers import ToolCall
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.memory import load_knowledge

READY = AIConfig(project="test-project")
AHU = Ref("equipment", "eq:Airside AHU-2", "Airside AHU-2")
VAV = Ref("equipment", "eq:Airside AHU-2/VAV 1-2-81", "VAV 1-2-81")


class FakeTools:
    """The two read tools the tests use, with the GraphTools result shapes."""

    def __init__(self):
        self.calls = []

    def describe(self, node_id):
        self.calls.append(("describe", node_id))
        if node_id not in (AHU.id, VAV.id):
            raise KeyError(f"no node {node_id!r}")
        return {"kind": "equipment", "name": node_id[3:], "class": "AHU" if node_id == AHU.id else "VAV",
                "trust": "likely", "points": [{}] * 3, "fed_by": [{"name": "Chiller 1"}], "feeds": [{}, {}],
                "missing_required_points": []}

    def find_nodes(self, query="", cls="", kind="", limit=20):
        self.calls.append(("find_nodes", query))
        return {"total": 1, "nodes": [{"id": VAV.id, "name": VAV.label}]}

    def upstream(self, node_id, depth=3):
        self.calls.append(("upstream", node_id))
        return {"total": 1, "nodes": [{"id": AHU.id}]}


def tool_use(*calls, text=""):
    content = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": f"tu_{i}", "name": n, "input": a} for i, (n, a) in enumerate(calls)]
    return ModelResponse(text=text, content=content, stop_reason="tool_use", input_tokens=200, output_tokens=40,
                         tool_calls=[ToolCall(f"tu_{i}", n, a) for i, (n, a) in enumerate(calls)])


def agent(*answers, tools=None, kb=None, store=None):
    scripted = Scripted(list(answers))
    a = Agent(Router(READY, providers={"claude": scripted}), tools=tools if tools is not None else FakeTools(),
              knowledge=kb, project="alpha/names_paths", store=store)
    return a, scripted


@pytest.fixture(scope="module")
def kb():
    return load_knowledge(km=load_knowledge_model())


# context engine (A1) ---------------------------------------------------------------------------------------------

def test_chips_general_to_specific_without_duplicates():
    s = ScreenState(page="tree", project="alpha/names_paths", project_label="Alpha", focus=AHU, selection=[AHU, VAV],
                    floor=Ref("floor", "fl:L3", "Level 3"))
    chips = chips_for(s)
    assert [c.label for c in chips] == ["Alpha", "Level 3", "Airside AHU-2", "VAV 1-2-81"]
    assert level_of(chips) == "equipment"
    assert level_of([]) == "general"
    assert chips_for(ScreenState(page="why-it-matters")) == []


def test_drop_and_pin():
    page = chips_for(ScreenState(project="p", project_label="P", focus=AHU))
    pinned = Chip("point", "pt:x", "ZN-T")
    out = merge_chips(page, [pinned], {f"equipment:{AHU.id}"})
    assert [c.key for c in out] == ["project:p", "point:pt:x"]
    assert merge_chips(page, [page[1]], set()) == page  # a pinned chip already on the page is not doubled


def test_packet_is_small_and_names_what_is_looked_at():
    s = ScreenState(page="Equipment_3D", title="Equipment 3D", project="alpha/names_paths", project_label="Alpha",
                    focus=AHU, view={"scenario": "normal"})
    p = context_packet(chips_for(s), s, FakeTools(), {"points": 1842})
    assert p["level"] == "equipment" and p["page"] == "Equipment 3D"
    assert p["project"] == {"id": "alpha/names_paths", "name": "Alpha", "points": 1842}
    (seen,) = p["looking_at"]
    assert seen == {"kind": "equipment", "id": AHU.id, "label": "Airside AHU-2", "class": "AHU", "trust": "likely",
                    "points": 3, "fed_by": ["Chiller 1"], "feeds": 2}
    assert p["view"] == {"scenario": "normal"}
    assert len(json.dumps(p)) < 1500


def test_packet_for_a_node_outside_the_graph():
    s = ScreenState(project="p", focus=Ref("equipment", "eq:gone", "Gone"))
    assert context_packet(chips_for(s), s, FakeTools())["looking_at"][0]["note"] == "not in this project's graph"


# the text agent (A2) ---------------------------------------------------------------------------------------------

def test_tool_loop_runs_the_tools_and_streams_the_answer(tmp_path):
    store = Store(tmp_path / "kg.sqlite")
    tools = FakeTools()
    a, scripted = agent(tool_use(("find_nodes", {"query": "1-2-81"})),
                        tool_use(("describe", {"node_id": VAV.id}), ("upstream", {"node_id": VAV.id})),
                        f"VAV 1-2-81 is fed by AHU-2 [[{AHU.id}]] *likely*.", tools=tools, store=store)
    events, history = [], []
    res = a.run(history, "What feeds VAV 1-2-81?", {"level": "project"}, emit=events.append)
    assert res.error is None
    assert tools.calls == [("find_nodes", "1-2-81"), ("describe", VAV.id), ("upstream", VAV.id)]
    assert [s["summary"] for s in res.steps] == ["1 found", "Airside AHU-2/VAV 1-2-81 · VAV · likely", "1 linked"]
    assert res.cited == [AHU.id] and res.model == "sonnet"
    assert any(e.type == "text" and "fed by" in e.data for e in events)
    # the conversation alternates user / assistant and every tool_use has its tool_result
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant", "user", "assistant"]
    assert {r["tool_use_id"] for r in history[4]["content"]} == {"tu_0", "tu_1"}
    assert "<context>" in history[0]["content"]
    # every model call is logged with its job and cost
    rows = sqlite3.connect(tmp_path / "kg.sqlite").execute("SELECT job, ok, model FROM llm_calls").fetchall()
    assert rows == [("agent_chat", 1, "claude-sonnet-5-5")] * 3 and len(res.calls) == 3
    req = scripted.requests[0][1]
    assert {t["name"] for t in req.tools} >= {"find_nodes", "describe", "upstream"}


def test_tool_errors_go_back_to_the_model():
    a, _ = agent(tool_use(("describe", {"node_id": "eq:nope"})), "Not found.")
    history = []
    res = a.run(history, "Describe eq:nope", {})
    assert res.steps[0]["error"] and history[2]["content"][0]["is_error"] is True
    assert res.text == "Not found."


def test_hands_over_to_opus_after_long_walks():
    walk = [tool_use(("find_nodes", {"query": "x"})) for _ in range(HANDOVER + 1)]
    a, scripted = agent(*walk, "Done.")
    events = []
    res = a.run([], "Where does this come from?", {}, emit=events.append)
    models = [m for m, _ in scripted.requests]
    assert models[:HANDOVER] == ["sonnet"] * HANDOVER and set(models[HANDOVER:]) == {"opus"}
    assert res.model == "opus" and [e.data["model"] for e in events if e.type == "model"] == ["sonnet", "opus"]


def test_gemini_takes_the_turn_when_claude_is_not_enabled():
    from projectmodel.ai import ModelNotEnabled
    from projectmodel.agent.chat import pick_model
    gemini = Scripted([tool_use(("find_nodes", {"query": "x"})), "Done."])
    claude = Scripted([ModelNotEnabled("Claude Sonnet 5.5: HTTP 404: not found")])
    r = Router(READY, providers={"claude": claude, "gemini": gemini})
    events, history = [], []
    res = Agent(r, tools=FakeTools(), project="p").run(history, "Hi", {}, emit=events.append)
    assert res.error is None and res.model == "argon" and res.text == "Done."
    assert [e.data["model"] for e in events if e.type == "model"] == ["sonnet", "argon"]
    assert [m for m, _ in gemini.requests] == ["argon", "argon"] and len(claude.requests) == 1
    assert pick_model(r, "agent_chat") == "argon"  # the next question goes straight to Gemini
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


def test_a_picked_model_answers_the_whole_turn():
    walk = [tool_use(("find_nodes", {"query": "x"})) for _ in range(HANDOVER + 1)]
    gemini = Scripted([*walk, "Done."])
    r = Router(READY, providers={"claude": Scripted([]), "gemini": gemini})
    res = Agent(r, tools=FakeTools(), project="p").run([], "Where does this come from?", {}, model="hydrogen",
                                                       effort="high")
    assert res.model == "hydrogen" and res.text == "Done."
    assert {m for m, _ in gemini.requests} == {"hydrogen"}  # no handover
    assert {req.effort for _, req in gemini.requests} == {"high"}


def test_a_picked_model_that_is_off_hands_over_and_says_so():
    from projectmodel.ai import ModelNotEnabled
    gemini = Scripted(["Done."])
    claude = Scripted([ModelNotEnabled("Claude Haiku 5.5: HTTP 404: not found"),
                       ModelNotEnabled("Claude Sonnet 5.5: HTTP 404: not found")])
    r = Router(READY, providers={"claude": claude, "gemini": gemini})
    res = Agent(r, tools=FakeTools(), project="p").run([], "Hi", {}, model="haiku")
    assert res.model == "argon" and res.error is None and res.text == "Done."
    assert "Haiku" in res.note and "Argon" in res.note and "haiku" in r.not_enabled


def test_the_router_learns_off_models_from_the_call_log(tmp_path):
    from projectmodel.agent.chat import pick_model
    store = Store(tmp_path / "kg.sqlite")
    err = "Claude Sonnet 5.5: HTTP 404: Publisher model ... was not found or your project does not have access to it."
    store.log_llm_call("p", 0, "vertex-claude", "claude-sonnet-5-5", "{}", None, 0, 1, job="agent_chat", ok=False,
                       error=err)
    store.log_llm_call("p", 0, "vertex-claude", "claude-opus-5-5", "{}", None, 0, 1, job="agent_chat", ok=False,
                       error=err.replace("Sonnet", "Opus"))
    store.log_llm_call("p", 0, "vertex-claude", "claude-opus-5-5", "{}", "[]", 0, 1, job="agent_chat")  # on since
    store.log_llm_call("p", 0, "vertex-gemini", "gemini-4-argon", "{}", None, 0, 1, job="agent_chat", ok=False,
                       error="Gemini 4 Argon: HTTP 503: overloaded")  # a passing problem, not "off"
    r = Router(READY, providers={"claude": Scripted([]), "gemini": Scripted([])})
    r.learn(store)
    assert set(r.not_enabled) == {"sonnet"} and r.learnt
    assert pick_model(r, "agent_chat") == "argon"


def test_no_handover_to_the_same_model():
    """No Opus in the project: Argon does chat and reasoning, so a long walk stays on chat (low effort)."""
    from projectmodel.ai import ModelNotEnabled
    walk = [tool_use(("find_nodes", {"query": "x"})) for _ in range(HANDOVER + 1)]
    gemini = Scripted([*walk, "Done."])
    claude = Scripted([ModelNotEnabled("Claude Sonnet 5.5: HTTP 404")])
    r = Router(READY, providers={"claude": claude, "gemini": gemini})
    res = Agent(r, tools=FakeTools(), project="p").run([], "Where does this come from?", {})
    assert res.model == "argon" and {req.effort for _, req in gemini.requests} == {"low"}


def test_think_it_through_goes_to_opus():
    a, scripted = agent("Here is my reasoning.")
    assert a.run([], "Think it through: why is zone 2-14 warm?", {}).model == "opus"
    assert scripted.requests[0][1].effort == "high"


def test_errors_end_the_turn_and_keep_history_valid():
    a, _ = agent(tool_use(("find_nodes", {"query": "x"})), ModelUnavailable("ADC missing"))
    history = []
    res = a.run(history, "Hi", {})
    assert res.error == "ADC missing" and history[-1]["role"] == "assistant"
    a2, _ = agent(*[tool_use(("find_nodes", {"query": "x"})) for _ in range(MAX_STEPS)])
    h2 = []
    assert "stopped after" in a2.run(h2, "Loop", {}).error and h2[-1]["role"] == "assistant"


def test_memory_and_skills_in_the_prompt(kb):
    a, _ = agent("ok", kb=kb)
    system, ref = a.system()
    assert ref.startswith("agent_chat@") and "# Memory" in system and "m-0001" in system
    assert "troubleshoot-warm-zone" in system and SKILL_TOOL in a.tool_defs()
    assert "no skill" in a._run_tool("skill_view", {"name": "nope"})["error"]
    assert "#" in a._run_tool("skill_view", {"name": "troubleshoot-warm-zone"})["text"]


def test_no_project_means_no_graph_tools(kb):
    a = Agent(Router(READY, providers={"claude": Scripted(["ok"])}), tools=None, knowledge=kb)
    assert [t["name"] for t in a.tool_defs()] == ["skill_view"]
    assert "# No project" in a.system()[0]
    assert a._run_tool("describe", {"node_id": "x"}) == {"error": "no project is open"}


def test_citations_unique_in_order():
    assert citations("a [[x]] *likely* b [[m-0001]] c [[x]]") == ["x", "m-0001"]


# citations come from the tools (W11) ------------------------------------------------------------------------------

def test_a_citation_no_tool_returned_gets_one_rewrite():
    bad = "VAV 1-2-81 is fed by AHU-9 [[eq:Airside AHU-9]] *likely*."
    good = f"VAV 1-2-81 is fed by AHU-2 [[{AHU.id}]] *likely*."
    a, scripted = agent(tool_use(("upstream", {"node_id": VAV.id})), bad, good)
    events, history = [], []
    res = a.run(history, "What feeds VAV 1-2-81?", {}, emit=events.append)
    assert res.repaired and res.text == good and res.bad_cites == [] and res.cited == [AHU.id]
    assert any(e.type == "reset" for e in events)
    assert "eq:Airside AHU-9" in history[-2]["content"] and history[-1]["role"] == "assistant"
    assert len(scripted.requests) == 3


def test_a_citation_still_wrong_after_the_rewrite_is_reported():
    bad = "Fed by [[eq:Airside AHU-9]]."
    a, _ = agent(tool_use(("upstream", {"node_id": VAV.id})), bad, bad)
    res = a.run([], "What feeds VAV 1-2-81?", {})
    assert res.repaired and res.bad_cites == ["eq:Airside AHU-9"] and res.error is None


def test_check_citations_reads_every_tool_result():
    from projectmodel.agent.chat import check_citations
    history = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                             "content": json.dumps({"cite": "src:a.pdf#p1", "id": "unit:X"})}]}]
    assert check_citations("A [[src:a.pdf#p1]] B [[unit:X]] C [[unit:Y]] D [[m-0001]]", history) == ["unit:Y"]
