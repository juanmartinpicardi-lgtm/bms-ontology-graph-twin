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

    def complete(self, model, req, on_text=None):
        user = req.messages[0]["content"]
        first = next(line[2:].split(":")[0] for line in user.splitlines() if line.startswith("- "))
        text = answer(first, 0.7)
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
    def __init__(self):
        self.models = self
        self.call = None

    def generate_content_stream(self, model, contents, config):
        self.call = (model, contents, config)
        usage = SimpleNamespace(prompt_token_count=200, cached_content_token_count=50, candidates_token_count=30,
                                thoughts_token_count=10)
        cand = SimpleNamespace(finish_reason=SimpleNamespace(value="STOP"))
        yield SimpleNamespace(text='{"a"', usage_metadata=None, candidates=[SimpleNamespace(finish_reason=None)])
        yield SimpleNamespace(text=": 1}", usage_metadata=usage, candidates=[cand])


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
