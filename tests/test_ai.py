"""Provider layer: prompts, routing, logging, escalation, typed JSON and the provider adapters, with no network."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from projectmodel.ai import ModelError, ModelRequest, ModelResponse, ModelUnavailable, Router, Scripted, run_job
from projectmodel.ai.config import AIConfig, load_config
from projectmodel.ai.jobs import JOBS
from projectmodel.ai.models import MODELS, get_model
from projectmodel.ai.prompts import all_prompts, load_prompt
from projectmodel.ai.providers import VertexClaude, VertexGemini
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.llm import JobClassifier, class_definition, get_provider
from projectmodel.mapper.pipeline import Mapper
from projectmodel.records import RawRecord

READY = AIConfig(project="test-project")


def router(*answers, family="claude"):
    return Router(READY, providers={family: Scripted(list(answers))})


def point_values(candidates=("Zone_Air_Temperature_Sensor", "Discharge_Air_Temperature_Sensor")):
    return {"name": "ZN-T", "path": "Floor 2/VAV-2-14", "equipment_class": "VAV",
            "candidates": "\n".join(f"- {c}" for c in candidates), "candidate_list": list(candidates)}


def answer(cls, conf=0.9):
    return json.dumps({"class": cls, "confidence": conf, "why": "ZN-T is a zone temperature"})


# models, config, prompts -----------------------------------------------------------------------------------------

def test_cost_counts_cache_reads_and_writes_at_their_rates():
    sonnet = get_model("sonnet")
    assert sonnet.cost(1_000_000, 0) == 2.0
    assert sonnet.cost(0, 1_000_000) == 10.0
    assert sonnet.cost(0, 0, cache_read=1_000_000) == 0.1
    assert sonnet.cost(0, 0, cache_write=1_000_000) == 2.5


def test_model_id_can_be_overridden(monkeypatch):
    monkeypatch.setenv("PM_MODEL_HYDROGEN", "gemini-4-hydrogen-001")
    assert MODELS["hydrogen"].id == "gemini-4-hydrogen-001"


def test_calls_off(monkeypatch):
    monkeypatch.setenv("PM_AI", "off")
    load_config.cache_clear()
    try:
        cfg = load_config()
        assert not cfg.ready and "PM_AI" in cfg.why_off
    finally:
        load_config.cache_clear()


def test_project_from_environment(monkeypatch):
    monkeypatch.delenv("PM_AI", raising=False)
    monkeypatch.setenv("PM_GCP_PROJECT", "my-proj")
    monkeypatch.setenv("PM_VERTEX_REGION", "us-east5")
    load_config.cache_clear()
    try:
        cfg = load_config()
        assert cfg.ready and cfg.project == "my-proj" and cfg.region_for("claude") == "us-east5"
    finally:
        load_config.cache_clear()


def test_every_prompt_loads_and_every_built_job_has_one():
    ids = {p.id for p in all_prompts()}
    assert {"point_class", "agent_chat"} <= ids
    for job in JOBS.values():
        assert job.default is None or job.default in MODELS
        assert all(m in MODELS for m in (*job.contender, *job.escalate))
        if job.status == "built":
            assert job.prompt in ids


def test_prompt_render_fills_placeholders_and_refuses_gaps():
    p = load_prompt("point_class")
    system, user = p.render(**point_values())
    assert "ZN-T" in user and "$" not in user and p.ref == "point_class@1"
    with pytest.raises(KeyError):
        p.render(name="x")


# router and logging ----------------------------------------------------------------------------------------------

def test_every_call_is_logged_with_job_prompt_tokens_and_cost():
    store = Store(":memory:")
    r = router("hello")
    resp = r.call("sonnet", ModelRequest("sys", [{"role": "user", "content": "hi"}]), job="agent_chat",
                  prompt="agent_chat@1", store=store, project="alpha/names_paths")
    assert resp.text == "hello" and resp.cost_usd > 0 and resp.call_id
    row = store.conn.execute("SELECT * FROM llm_calls").fetchone()
    assert row["job"] == "agent_chat" and row["prompt"] == "agent_chat@1" and row["ok"] == 1
    assert row["model"] == "claude-sonnet-5-5" and row["input_tokens"] == 100 and row["output_tokens"] == 20
    assert row["cost_usd"] == pytest.approx(resp.cost_usd)


def test_a_failed_call_is_logged_as_failed():
    store = Store(":memory:")
    with pytest.raises(ModelError):
        router(ModelError("HTTP 500")).call("haiku", ModelRequest("s", [{"role": "user", "content": "x"}]),
                                            job="point_class", store=store)
    row = store.conn.execute("SELECT ok, error FROM llm_calls").fetchone()
    assert row["ok"] == 0 and "500" in row["error"]


def test_no_model_raises_unavailable_and_logs_nothing():
    store = Store(":memory:")
    r = Router(AIConfig(project=None, enabled=False, why_off="no GCP project"))
    with pytest.raises(ModelUnavailable, match="no GCP project"):
        r.call("haiku", ModelRequest("s", [{"role": "user", "content": "x"}]), job="point_class", store=store)
    assert store.conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0


def test_images_are_logged_as_size_and_hash():
    store = Store(":memory:")
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 5000}}
    router("ok").call("sonnet", ModelRequest("s", [{"role": "user", "content": [img]}]), job="snapshot_question",
                      store=store)
    logged = store.conn.execute("SELECT input FROM llm_calls").fetchone()[0]
    assert "A" * 100 not in logged and "5000 b64 chars" in logged


def test_old_llm_calls_table_gets_the_new_columns(tmp_path):
    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE llm_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL, revision "
                "INTEGER NOT NULL, provider TEXT NOT NULL, model TEXT, input TEXT NOT NULL, output TEXT, cost_usd REAL "
                "NOT NULL DEFAULT 0, latency_s REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    con.execute("INSERT INTO llm_calls (project, revision, provider, input) VALUES ('p', 1, 'x', '{}')")
    con.commit()
    con.close()
    store = Store(db)
    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(llm_calls)")}
    assert {"job", "prompt", "input_tokens", "ok", "error"} <= cols
    assert store.conn.execute("SELECT ok FROM llm_calls").fetchone()[0] == 1


# jobs ------------------------------------------------------------------------------------------------------------

def test_job_returns_typed_json_from_the_default_model():
    store = Store(":memory:")
    res = run_job("point_class", point_values(), router=router(answer("Zone_Air_Temperature_Sensor")), store=store)
    assert res.output["class"] == "Zone_Air_Temperature_Sensor" and res.model == "haiku" and not res.escalated
    assert store.conn.execute("SELECT prompt FROM llm_calls").fetchone()[0] == "point_class@1"


def test_an_answer_outside_the_candidates_escalates():
    store = Store(":memory:")
    scripted = Scripted([answer("Made_Up_Class"), answer("Zone_Air_Temperature_Sensor")])
    r = Router(READY, providers={"claude": scripted})
    res = run_job("point_class", point_values(), router=r, store=store)
    assert [a["model"] for a in res.attempts] == ["haiku", "sonnet"] and res.escalated
    assert "not one of the candidates" in res.attempts[0]["problem"]
    assert res.output["class"] == "Zone_Air_Temperature_Sensor"
    assert store.conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 2


def test_invalid_json_escalates_then_fails_when_every_model_fails():
    store = Store(":memory:")
    with pytest.raises(ModelError, match="every model failed"):
        run_job("point_class", point_values(), router=router("not json", '{"class": 3}'), store=store)
    rows = store.conn.execute("SELECT ok FROM llm_calls").fetchall()
    assert [r[0] for r in rows] == [0, 1]  # the first call's output was not JSON; the second failed the schema


def test_planned_jobs_fail_clearly():
    with pytest.raises(ModelError, match="planned"):
        run_job("plan_meaning", {}, router=router())


# mapper ----------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


def test_candidate_definitions_come_from_brick(km):
    assert "temperature" in class_definition(km, "Zone_Air_Temperature_Sensor").lower()


def test_mapper_uses_the_point_class_job_for_leftovers_only(km):
    store = Store(":memory:")
    recs = [RawRecord("p1", "test", "t.csv", 1, "MAT", path="AHU-1"),
            RawRecord("p2", "test", "t.csv", 2, "Sply Tmp Alt", path="AHU-1")]
    clf = JobClassifier(km, router=Router(READY, providers={"claude": _PickFirst()}))
    summary = Mapper(km, llm=clf, llm_below=0.99).run(recs, store, "t")
    rows = store.conn.execute("SELECT job, project, revision FROM llm_calls").fetchall()
    assert summary["llm_calls"] == len(rows) >= 1
    assert all(r["job"] == "point_class" and r["project"] == "t" and r["revision"] == 1 for r in rows)
    assert any(n["method"] == "llm" for n in store.nodes("t", "point"))


def test_a_sure_model_still_goes_to_review(km):
    from projectmodel.mapper.pipeline import LLM_CAP
    from projectmodel.scoring.score import DEFAULT_ACCEPT
    store = Store(":memory:")
    recs = [RawRecord("p1", "test", "t.csv", 1, "Sply Tmp Alt", path="AHU-1")]
    clf = JobClassifier(km, router=Router(READY, providers={"claude": _PickFirst(0.99)}))
    Mapper(km, llm=clf, llm_below=0.99).run(recs, store, "t")
    (n,) = [n for n in store.nodes("t", "point") if n["method"] == "llm"]
    assert n["confidence"] == LLM_CAP < DEFAULT_ACCEPT
    logged = json.loads(store.conn.execute("SELECT output FROM llm_calls").fetchone()[0])[0]["text"]
    assert json.loads(logged)["confidence"] == 0.99  # the model's own number is kept in the log


def test_mapper_without_credentials_keeps_the_rules_answer(km):
    store = Store(":memory:")
    clf = JobClassifier(km, router=Router(AIConfig(project=None, enabled=False, why_off="off")))
    recs = [RawRecord("p1", "test", "t.csv", 1, "Sply Tmp Alt", path="AHU-1")]
    Mapper(km, llm=clf, llm_below=0.99).run(recs, store, "t")
    assert clf.unavailable and store.conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0


def test_provider_names():
    assert get_provider("none").name == "none"
    assert get_provider("haiku").name.startswith("vertex")
    with pytest.raises(ValueError):
        get_provider("gpt")


class _PickFirst:
    """Answers point_class with the first candidate, like a cautious model."""
    name = "pick-first"

    def __init__(self, confidence=0.7):
        self.confidence = confidence

    def complete(self, model, req, on_text=None):
        user = req.messages[0]["content"]
        first = next(line[2:].split(":")[0] for line in user.splitlines() if line.startswith("- "))
        text = answer(first, self.confidence)
        return ModelResponse(text, [{"type": "text", "text": text}], [], "end_turn", 50, 10, model=model.key)


# provider adapters against fake SDK clients ----------------------------------------------------------------------

class _Block(SimpleNamespace):
    def to_dict(self):
        return dict(self.__dict__)


class _FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter(["Hel", "lo"])

    def get_final_message(self):
        return self.msg


class _FakeAnthropic:
    def __init__(self):
        self.kwargs = None
        self.messages = self

    def stream(self, **kwargs):
        self.kwargs = kwargs
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=1000,
                                cache_creation_input_tokens=0)
        msg = SimpleNamespace(content=[_Block(type="text", text="Hello"),
                                       _Block(type="tool_use", id="tu1", name="describe", input={"node_id": "eq:x"})],
                              stop_reason="tool_use", usage=usage)
        return _FakeStream(msg)


def test_vertex_claude_request_shape_and_response():
    fake = _FakeAnthropic()
    seen = []
    tools = [{"name": "describe", "description": "d", "input_schema": {"type": "object"}, "runs": "server"}]
    resp = VertexClaude(READY, client=fake).complete(
        get_model("sonnet"), ModelRequest("sys", [{"role": "user", "content": "hi"}], tools=tools,
                                          json_schema={"type": "object"}, effort="low"), seen.append)
    k = fake.kwargs
    assert k["model"] == "claude-sonnet-5-5" and k["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert k["tools"] == [{"name": "describe", "description": "d", "input_schema": {"type": "object"}}]
    assert k["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert "thinking" not in k and "temperature" not in k
    assert seen == ["Hel", "lo"] and resp.text == "Hello" and resp.cache_read == 1000
    assert resp.tool_calls[0].name == "describe" and resp.tool_calls[0].input == {"node_id": "eq:x"}


class _FakeGenai:
    """generate_content_stream answering with scripted chunks: each a list of google.genai Parts, the last one with
    the finish reason and usage."""

    def __init__(self, *turns, finish="STOP"):
        from google.genai import types
        self.models = self
        self.call = None
        self.calls = []
        self.turns = list(turns) or [[[types.Part(text='{"a"')], [types.Part(text=": 1}")]]]
        self.finish = finish

    def generate_content_stream(self, model, contents, config):
        from google.genai import types
        self.call = (model, contents, config)
        self.calls.append(self.call)
        chunks = self.turns.pop(0)
        usage = SimpleNamespace(prompt_token_count=200, cached_content_token_count=50, candidates_token_count=30,
                                thoughts_token_count=10)
        for i, parts in enumerate(chunks):
            last = i == len(chunks) - 1
            cand = SimpleNamespace(content=types.Content(role="model", parts=parts),
                                   finish_reason=SimpleNamespace(value=self.finish) if last else None)
            yield SimpleNamespace(usage_metadata=usage if last else None, candidates=[cand])


def test_vertex_gemini_tool_round_trip_keeps_signatures():
    from google.genai import types
    sig = b"\x01sig"
    fake = _FakeGenai(
        [[types.Part(text="thinking", thought=True), types.Part(text="Let me look. ")],
         [types.Part(function_call=types.FunctionCall(name="describe", args={"node_id": "eq:x"}),
                     thought_signature=sig)]],
        [[types.Part(text="It is a VAV [[eq:x]] *likely*.")]])
    g = VertexGemini(READY, client=fake)
    tools = [{"name": "describe", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    msgs = [{"role": "user", "content": "what is eq:x?"}]
    seen = []
    r1 = g.complete(get_model("argon"), ModelRequest("sys", msgs, tools=tools, effort="medium"), seen.append)
    assert seen == ["Let me look. "] and r1.stop_reason == "tool_use"
    (tc,) = r1.tool_calls
    assert tc.name == "describe" and tc.input == {"node_id": "eq:x"}
    assert r1.content[1]["_gemini_sig"] and r1.content[1]["_gemini_id"] is None
    _, _, config = fake.call
    assert config.tools[0].function_declarations[0].name == "describe"
    assert config.thinking_config.thinking_level.value == "MEDIUM"
    msgs += [{"role": "assistant", "content": r1.content},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tc.id, "content": '{"class": "VAV"}'}]}]
    r2 = g.complete(get_model("argon"), ModelRequest("sys", msgs, tools=tools))
    assert r2.stop_reason == "end_turn" and r2.text.startswith("It is a VAV")
    _, contents, _ = fake.call
    call_part = contents[1].parts[1]
    assert call_part.function_call.name == "describe" and call_part.thought_signature == sig
    assert call_part.function_call.id is None
    resp_part = contents[2].parts[0].function_response
    assert resp_part.name == "describe" and resp_part.response == {"output": {"class": "VAV"}} and resp_part.id is None


def test_claude_gets_clean_messages_after_gemini_turns():
    from projectmodel.ai.providers import _clean
    msgs = [{"role": "assistant", "content": [{"type": "text", "text": ""},
                                              {"type": "tool_use", "id": "gm_0_describe", "name": "describe",
                                               "input": {}, "_gemini_sig": "AQ==", "_gemini_id": None}]}]
    assert _clean(msgs)[0]["content"] == [{"type": "tool_use", "id": "gm_0_describe", "name": "describe", "input": {}}]
    assert msgs[0]["content"][1]["_gemini_sig"] == "AQ=="  # the conversation itself keeps them


def test_not_enabled_models_fall_back_to_the_contender(tmp_path):
    from projectmodel.ai import ModelNotEnabled
    store = Store(tmp_path / "kg.sqlite")
    off = [ModelNotEnabled("Claude Haiku 5.5: HTTP 404: not found"), ModelNotEnabled("Sonnet: HTTP 404: not found")]
    answer_ = '{"class": "Zone_Air_Temperature_Sensor", "confidence": 0.9, "why": "ZN-T"}'
    claude, gemini = Scripted(off), Scripted([answer_, answer_])
    r = Router(READY, providers={"claude": claude, "gemini": gemini})
    assert JOBS["point_class"].contender == ("argon",)
    assert run_job("point_class", point_values(), router=r, store=store).model == "argon"
    assert set(r.not_enabled) == {"haiku", "sonnet"}
    assert run_job("point_class", point_values(), router=r, store=store).model == "argon"
    assert [m for m, _ in claude.requests] == ["haiku", "sonnet"]  # learnt once: the second run goes straight to argon
    oks = sqlite3.connect(tmp_path / "kg.sqlite").execute("SELECT model, ok FROM llm_calls ORDER BY id").fetchall()
    assert oks == [("claude-haiku-5-5", 0), ("claude-sonnet-5-5", 0), ("gemini-4-argon", 1), ("gemini-4-argon", 1)]


def test_a_job_that_fails_its_checks_does_not_fall_to_the_contender():
    gemini = Scripted([])
    r = Router(READY, providers={"claude": Scripted(['{"class": "Made_Up", "confidence": 0.9, "why": "x"}'] * 2),
                                 "gemini": gemini})
    with pytest.raises(ModelError, match="every model failed"):
        run_job("point_class", point_values(), router=r)
    assert gemini.requests == []


def test_status_errors_name_models_that_are_not_enabled():
    from projectmodel.ai import ModelNotEnabled
    from projectmodel.ai.providers import _status_error
    m = get_model("fable")
    assert isinstance(_status_error(m, 403, "requires data sharing to be enabled"), ModelNotEnabled)
    assert isinstance(_status_error(m, 404, "Publisher model ... was not found"), ModelNotEnabled)
    e = _status_error(m, 429, "quota")
    assert isinstance(e, ModelError) and not isinstance(e, ModelNotEnabled)



def test_vertex_gemini_request_shape_and_response():
    fake = _FakeGenai()
    pdf = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERg=="}}
    resp = VertexGemini(READY, client=fake).complete(
        get_model("hydrogen"), ModelRequest("sys", [{"role": "user", "content": [pdf, {"type": "text", "text": "q"}]}],
                                            json_schema={"type": "object"}))
    model, contents, config = fake.call
    assert model == "gemini-4-hydrogen" and contents[0].role == "user" and len(contents[0].parts) == 2
    assert config.system_instruction == "sys" and config.response_mime_type == "application/json"
    assert resp.text == '{"a": 1}' and resp.input_tokens == 150 and resp.cache_read == 50 and resp.output_tokens == 40
