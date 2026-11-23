"""Voice turns for the agent dock (spec-agent §4, phase A5, push-to-talk): Gemini Live on Vertex AI.

The person records a question with the microphone in the dock's input. The recording goes to the server, which opens
one Live session: the question as audio, the same graph tools as the text agent (run here, on the server), and the
spoken answer back as audio with its transcript. No token ever reaches the browser.

    res = voice_turn(agent, wav_bytes, packet, recent=[("What feeds VAV 1-2-14?", "AHU-2 does.")])
    res.heard, res.text, res.wav, res.steps

Hands-free calls (an open microphone, interruptible) need the browser to talk to Gemini Live directly; that is a
later step. Every session is logged to llm_calls (job agent_voice) with its audio tokens and cost. The audio itself
is not stored (spec-agent §9): only the transcripts are.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..ai.models import LIVE, LIVE_REGION_DEFAULT
from .chat import Agent, _summary

OUT_RATE = 24000          # Live answers in 16-bit mono PCM at 24 kHz
TIMEOUT_S = 90
MAX_TOOL_ROUNDS = 8
RESULT_CHARS = 8000


class VoiceError(RuntimeError):
    pass


@dataclass
class VoiceResult:
    heard: str = ""                                 # what the person said, as Live transcribed it
    text: str = ""                                  # what the agent said
    wav: bytes = b""                                # the spoken answer, ready to play
    steps: list[dict] = field(default_factory=list)
    model: str = LIVE.key
    cost_usd: float = 0.0
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    call_id: int | None = None
    error: str | None = None


def read_wav(data: bytes) -> tuple[bytes, int]:
    """(16-bit mono PCM, sample rate) from a WAV recording. Stereo is folded to its first channel."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            rate, ch, width, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())
    except (wave.Error, EOFError) as e:
        raise VoiceError(f"the recording is not a WAV file: {e}") from e
    if width != 2:
        raise VoiceError(f"the recording is {8 * width}-bit; 16-bit is needed")
    if ch > 1:
        frames = b"".join(frames[i:i + 2] for i in range(0, len(frames), 2 * ch))
    return frames, rate


def to_wav(pcm: bytes, rate: int = OUT_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def live_region(config) -> str:
    return os.environ.get("PM_LIVE_REGION") or config.regions.get("live") or LIVE_REGION_DEFAULT


def _connect(config):
    """The SDK's Live connect, for our project and the Live region."""
    from google import genai
    client = genai.Client(vertexai=True, project=config.project, location=live_region(config),
                          credentials=config.credentials)
    return client.aio.live.connect


def instructions(agent: Agent, packet: dict, recent: list[tuple[str, str]]) -> tuple[str, str]:
    system, ref = agent.system("agent_voice")
    parts = [system, "# Context\n" + json.dumps(packet, ensure_ascii=False)]
    if recent:
        parts.append("# Conversation so far\n" + "\n".join(f"Person: {q}\nYou: {a}" for q, a in recent[-4:]))
    return "\n\n".join(parts), ref


async def _session(agent: Agent, pcm: bytes, rate: int, system: str, connect: Callable, res: VoiceResult) -> None:
    from google.genai import types
    tools = agent.tool_defs()
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Push-to-talk: the recording is one whole utterance, so the server does not listen for the end of speech.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)),
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(name=t["name"], description=t.get("description", ""),
                                      parameters_json_schema=t.get("input_schema") or {"type": "object"})
            for t in tools])] if tools else None,
    )
    audio = bytearray()
    async with connect(model=LIVE.id, config=config) as s:
        await s.send_realtime_input(activity_start=types.ActivityStart())
        await s.send_realtime_input(audio=types.Blob(data=pcm, mime_type=f"audio/pcm;rate={rate}"))
        await s.send_realtime_input(activity_end=types.ActivityEnd())
        # A tool call can close the model's turn before it speaks: the answer comes in the turn after the tool
        # responses. So a turn that ends with tool responses sent and nothing said since is not the end.
        done, rounds, said_since_tools = False, 0, True
        while not done and rounds <= MAX_TOOL_ROUNDS:
            async for msg in s.receive():
                if u := msg.usage_metadata:
                    res.input_tokens = max(res.input_tokens, u.prompt_token_count or 0)
                    res.output_tokens = max(res.output_tokens, u.response_token_count or 0)
                if msg.tool_call and msg.tool_call.function_calls:
                    rounds += 1
                    replies = []
                    for fc in msg.tool_call.function_calls:
                        args = dict(fc.args or {})
                        out = agent._run_tool(fc.name, args)
                        text = json.dumps(out, ensure_ascii=False, default=str)[:RESULT_CHARS]
                        res.steps.append({"name": fc.name, "input": args, "summary": _summary(fc.name, out),
                                          "error": "error" in out})
                        replies.append(types.FunctionResponse(id=fc.id, name=fc.name, response={"output": text}))
                    await s.send_tool_response(function_responses=replies)
                    said_since_tools = False
                sc = msg.server_content
                if sc is None:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    res.heard += sc.input_transcription.text
                if sc.output_transcription and sc.output_transcription.text:
                    res.text += sc.output_transcription.text
                    said_since_tools = True
                if sc.model_turn:
                    for p in sc.model_turn.parts or []:
                        if p.inline_data and p.inline_data.data:
                            audio.extend(p.inline_data.data)
                            said_since_tools = True
                if sc.turn_complete:
                    if said_since_tools:
                        done = True
                    break
    res.wav = to_wav(bytes(audio)) if audio else b""
    res.heard, res.text = res.heard.strip(), res.text.strip()


def voice_turn(agent: Agent, recording: bytes, packet: dict, recent: list[tuple[str, str]] | None = None,
               connect: Callable | None = None) -> VoiceResult:
    """One spoken question, one spoken answer (with tool calls in between). Never raises: problems are in .error."""
    t0 = time.perf_counter()
    res = VoiceResult()
    system, ref = instructions(agent, packet, recent or [])
    try:
        pcm, rate = read_wav(recording)
        if len(pcm) < rate // 5:  # under a tenth of a second
            raise VoiceError("the recording is empty")
        if connect is None:
            if not agent.router.ready:
                raise VoiceError(agent.router.why_not_ready())
            connect = _connect(agent.router.config)
        asyncio.run(asyncio.wait_for(_session(agent, pcm, rate, system, connect, res), TIMEOUT_S))
        if not res.text and not res.wav:
            res.error = "Gemini Live sent no answer"
    except VoiceError as e:
        res.error = str(e)
    except TimeoutError:
        res.error = f"no answer within {TIMEOUT_S} s"
    except Exception as e:  # noqa: BLE001 - the SDK raises websocket and API errors of many kinds
        res.error = f"{LIVE.label}: {e}"
    res.seconds = round(time.perf_counter() - t0, 2)
    res.cost_usd = LIVE.cost(res.input_tokens, res.output_tokens)
    if agent.store is not None:
        res.call_id = agent.store.log_llm_call(
            agent.project or "", 0, "vertex-live", LIVE.id,
            json.dumps({"system": system, "audio": f"<{len(recording)} bytes WAV, not stored>",
                        "tools": [t["name"] for t in agent.tool_defs()]}),
            json.dumps({"heard": res.heard, "text": res.text, "steps": res.steps}, default=str),
            res.cost_usd, res.seconds, job="agent_voice", prompt=ref, input_tokens=res.input_tokens,
            output_tokens=res.output_tokens, ok=res.error is None, error=res.error)
    return res


def bytes_of(audio: Any) -> bytes:
    """The bytes of a Streamlit UploadedFile (or bytes)."""
    return audio if isinstance(audio, bytes | bytearray) else audio.getvalue()
