"""Voice turns on Gemini Live (agent/voice.py), with a scripted Live session: no network."""

import json
import wave
import io
from contextlib import asynccontextmanager

from google.genai import types

from projectmodel.agent.chat import Agent
from projectmodel.agent.voice import read_wav, to_wav, voice_turn
from projectmodel.ai import Router, Scripted
from projectmodel.db.store import Store
from tests.test_agent import READY, VAV, FakeTools


def wav(seconds=1.0, rate=16000, channels=1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds) * channels)
    return buf.getvalue()


class FakeLive:
    """A Live session that plays back `turns`: one list of server messages per receive() call."""

    def __init__(self, turns):
        self.turns, self.sent, self.tool_responses, self.config = list(turns), [], [], None

    def connect(self, model, config):
        self.model, self.config = model, config

        @asynccontextmanager
        async def cm():
            yield self
        return cm()

    async def send_realtime_input(self, **kw):
        self.sent.append(kw)

    async def send_tool_response(self, function_responses):
        self.tool_responses.extend(function_responses)

    async def receive(self):
        for m in (self.turns.pop(0) if self.turns else []):
            yield m


def said(text, audio=b"\x00\x01" * 100, done=True):
    return types.LiveServerMessage(server_content=types.LiveServerContent(
        model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=audio, mime_type="audio/pcm"))]),
        output_transcription=types.Transcription(text=text), turn_complete=done))


def heard(text):
    return types.LiveServerMessage(server_content=types.LiveServerContent(
        input_transcription=types.Transcription(text=text)))


def tool_call(name, args):
    return types.LiveServerMessage(tool_call=types.LiveServerToolCall(
        function_calls=[types.FunctionCall(id="fc1", name=name, args=args)]))


def ended():
    return types.LiveServerMessage(server_content=types.LiveServerContent(turn_complete=True),
                                   usage_metadata=types.UsageMetadata(prompt_token_count=900, response_token_count=60))


def make_agent(store=None):
    return Agent(Router(READY, providers={"claude": Scripted([])}), tools=FakeTools(), project="alpha/names_paths",
                 store=store)


def test_wav_round_trip_and_stereo_fold():
    pcm, rate = read_wav(wav(0.5, 16000, channels=2))
    assert rate == 16000 and len(pcm) == 16000  # 0.5 s, mono, 2 bytes a sample
    with wave.open(io.BytesIO(to_wav(b"\x00\x00" * 24000))) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 24000


def test_a_spoken_question_runs_the_tools_and_answers(tmp_path):
    store = Store(tmp_path / "kg.sqlite")
    live = FakeLive([
        [heard("What feeds VAV 1-2-81?"), tool_call("find_nodes", {"query": "VAV 1-2-81"}), ended()],
        [said("AHU-2 feeds it."), ended()],
    ])
    res = voice_turn(make_agent(store), wav(), {"page": "tree"}, recent=[("Hi", "Hello")], connect=live.connect)
    assert res.error is None
    assert res.heard == "What feeds VAV 1-2-81?" and res.text == "AHU-2 feeds it." and res.wav.startswith(b"RIFF")
    assert res.steps == [{"name": "find_nodes", "input": {"query": "VAV 1-2-81"}, "summary": "1 found",
                          "error": False}]
    assert json.loads(live.tool_responses[0].response["output"])["nodes"][0]["id"] == VAV.id
    # push-to-talk: the utterance is framed by activity start and end, as 16 kHz PCM
    assert "activity_start" in live.sent[0] and "activity_end" in live.sent[-1]
    assert live.sent[1]["audio"].mime_type == "audio/pcm;rate=16000"
    assert "Conversation so far" in live.config.system_instruction and "find_nodes" in str(live.config.tools)
    row = store.conn.execute("SELECT job, ok, input_tokens, output_tokens, input FROM llm_calls").fetchone()
    assert row["job"] == "agent_voice" and row["ok"] == 1 and (row["input_tokens"], row["output_tokens"]) == (900, 60)
    assert "not stored" in row["input"] and res.cost_usd > 0


def test_problems_come_back_as_errors(tmp_path):
    assert "not a WAV" in voice_turn(make_agent(), b"nope", {}, connect=FakeLive([]).connect).error
    assert "empty" in voice_turn(make_agent(), wav(0.01), {}, connect=FakeLive([]).connect).error
    assert voice_turn(make_agent(), wav(), {}, connect=FakeLive([[ended()]]).connect).error == \
        "Gemini Live sent no answer"
