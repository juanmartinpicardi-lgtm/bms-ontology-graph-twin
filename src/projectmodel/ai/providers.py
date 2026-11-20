"""One interface over the model families we call on Vertex AI.

Requests and responses use the Anthropic message shape (role + content blocks), the richest of the two; the Gemini
provider converts text, image and PDF blocks. Every provider call streams, so long answers never hit an HTTP
timeout and the agent dock can show text as it arrives (`on_text`).

  VertexClaude   Claude on Vertex AI through the Anthropic SDK's Vertex client
  VertexGemini   Gemini on Vertex AI through google-genai (vertexai=True)
  NoModel        no call at all: raises ModelUnavailable with the reason (no project, PM_AI=off, ...)
  Scripted       canned answers, for tests

Providers do not log; `ai.calls.call_model` times, prices and logs every call.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import AIConfig
from .models import Model


class ModelUnavailable(RuntimeError):
    """No model can be called (no credentials, no project, calls switched off)."""


class ModelError(RuntimeError):
    """The model was called and failed (API error, refusal, invalid output)."""


@dataclass
class ModelRequest:
    system: str
    messages: list[dict]
    max_tokens: int = 8000
    tools: list[dict] = field(default_factory=list)  # name, description, input_schema
    json_schema: dict | None = None                  # typed JSON output
    effort: str | None = None                        # low | medium | high | xhigh | max (Claude only)


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelResponse:
    text: str
    content: list[dict]           # the assistant turn's blocks, Anthropic shape, to append to the conversation
    tool_calls: list[ToolCall]
    stop_reason: str
    input_tokens: int = 0         # billed at the full input rate
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    model: str = ""
    json: Any = None              # parsed output when the request asked for JSON
    # filled by the router
    cost_usd: float = 0.0
    latency_s: float = 0.0
    provider: str = ""
    call_id: int | None = None    # row in llm_calls

    def usage(self) -> dict:
        return {"input": self.input_tokens, "output": self.output_tokens, "cache_read": self.cache_read,
                "cache_write": self.cache_write}


OnText = Callable[[str], None] | None


class Provider(Protocol):
    name: str

    def complete(self, model: Model, req: ModelRequest, on_text: OnText = None) -> ModelResponse: ...


# Claude ----------------------------------------------------------------------------------------------------------

_TOOL_KEYS = ("name", "description", "input_schema")


class VertexClaude:
    name = "vertex-claude"

    def __init__(self, config: AIConfig, client: Any = None):
        if client is None:
            from anthropic import AnthropicVertex

            client = AnthropicVertex(project_id=config.project, region=config.region_for("claude"), max_retries=2)
        self.client = client

    def complete(self, model: Model, req: ModelRequest, on_text: OnText = None) -> ModelResponse:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": model.id,
            "max_tokens": req.max_tokens,
            # The system prompt is the stable prefix (instructions, knowledge-model excerpt, memory): cache it.
            "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            "messages": req.messages,
        }
        if req.tools:
            kwargs["tools"] = [{k: t[k] for k in _TOOL_KEYS if k in t} for t in req.tools]
        output_config: dict[str, Any] = {}
        if req.effort:
            output_config["effort"] = req.effort
        if req.json_schema:
            output_config["format"] = {"type": "json_schema", "schema": req.json_schema}
        if output_config:
            kwargs["output_config"] = output_config
        try:
            with self.client.messages.stream(**kwargs) as stream:
                if on_text:
                    for text in stream.text_stream:
                        on_text(text)
                msg = stream.get_final_message()
        except anthropic.APIStatusError as e:
            raise ModelError(f"{model.label}: HTTP {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ModelError(f"{model.label}: connection failed: {e}") from e
        except Exception as e:  # google.auth refresh errors surface here when ADC is missing or expired
            if type(e).__module__.startswith("google.auth"):
                raise ModelUnavailable(f"Google credentials: {e}. Run `gcloud auth application-default login`.") from e
            raise
        content = [b.to_dict() for b in msg.content]
        text = "".join(b.text for b in msg.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, b.input if isinstance(b.input, dict) else {})
                 for b in msg.content if b.type == "tool_use"]
        u = msg.usage
        return ModelResponse(text=text, content=content, tool_calls=calls, stop_reason=msg.stop_reason or "",
                             input_tokens=u.input_tokens or 0, output_tokens=u.output_tokens or 0,
                             cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                             cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0, model=model.key)


# Gemini ----------------------------------------------------------------------------------------------------------

def _gemini_parts(content: Any) -> list:
    from google.genai import types

    if isinstance(content, str):
        return [types.Part.from_text(text=content)]
    parts = []
    for b in content:
        kind = b.get("type")
        if kind == "text":
            parts.append(types.Part.from_text(text=b["text"]))
        elif kind in ("image", "document") and b.get("source", {}).get("type") == "base64":
            src = b["source"]
            parts.append(types.Part.from_bytes(data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
        elif kind == "tool_result":
            parts.append(types.Part.from_text(text=json.dumps(b.get("content"))))
        else:
            raise ModelError(f"Gemini provider cannot send a {kind!r} block")
    return parts


class VertexGemini:
    name = "vertex-gemini"

    def __init__(self, config: AIConfig, client: Any = None):
        if client is None:
            from google import genai

            client = genai.Client(vertexai=True, project=config.project, location=config.region_for("gemini"))
        self.client = client

    def complete(self, model: Model, req: ModelRequest, on_text: OnText = None) -> ModelResponse:
        from google.genai import errors, types

        if req.tools:
            raise ModelError("tool use runs on Claude in this prototype; Gemini jobs are single-shot")
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=_gemini_parts(m["content"])) for m in req.messages]
        config = types.GenerateContentConfig(system_instruction=req.system, max_output_tokens=req.max_tokens)
        if req.json_schema:
            config.response_mime_type = "application/json"
            config.response_json_schema = req.json_schema
        chunks, usage, finish = [], None, ""
        try:
            for chunk in self.client.models.generate_content_stream(model=model.id, contents=contents, config=config):
                if chunk.text:
                    chunks.append(chunk.text)
                    if on_text:
                        on_text(chunk.text)
                usage = chunk.usage_metadata or usage
                if chunk.candidates and chunk.candidates[0].finish_reason:
                    finish = str(chunk.candidates[0].finish_reason.value).lower()
        except errors.APIError as e:
            raise ModelError(f"{model.label}: HTTP {e.code}: {e.message}") from e
        except Exception as e:
            if type(e).__module__.startswith("google.auth"):
                raise ModelUnavailable(f"Google credentials: {e}. Run `gcloud auth application-default login`.") from e
            raise
        text = "".join(chunks)
        prompt = (usage.prompt_token_count or 0) if usage else 0
        cached = (usage.cached_content_token_count or 0) if usage else 0
        out = ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0
        return ModelResponse(text=text, content=[{"type": "text", "text": text}], tool_calls=[],
                             stop_reason=finish, input_tokens=max(0, prompt - cached), output_tokens=out,
                             cache_read=cached, model=model.key)


# No model and scripted -------------------------------------------------------------------------------------------

class NoModel:
    name = "none"

    def __init__(self, reason: str = "model calls are off"):
        self.reason = reason

    def complete(self, model: Model, req: ModelRequest, on_text: OnText = None) -> ModelResponse:
        raise ModelUnavailable(self.reason)


class Scripted:
    """Answers from a list, in order, for tests. Each item is a ModelResponse, a str (a text answer; parsed as
    JSON when the request asks for JSON), or an Exception to raise."""

    name = "scripted"

    def __init__(self, answers: list):
        self.answers = list(answers)
        self.requests: list[tuple[str, ModelRequest]] = []

    def complete(self, model: Model, req: ModelRequest, on_text: OnText = None) -> ModelResponse:
        self.requests.append((model.key, req))
        if not self.answers:
            raise ModelError("scripted provider has no answer left")
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        if isinstance(a, str):
            a = ModelResponse(text=a, content=[{"type": "text", "text": a}], tool_calls=[], stop_reason="end_turn",
                              input_tokens=100, output_tokens=20, model=model.key)
        if on_text and a.text:
            on_text(a.text)
        return a
