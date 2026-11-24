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

from .config import AIConfig, request_timeout_s
from .models import Model


class ModelUnavailable(RuntimeError):
    """No model can be called (no credentials, no project, calls switched off)."""


class ModelError(RuntimeError):
    """The model was called and failed (API error, refusal, invalid output)."""


class ModelTimeout(ModelError):
    """The request got no answer in time (a stalled stream or a dropped connection). Nothing was billed for an answer
    we never saw, so the router tries once more."""


class ModelNotEnabled(ModelError):
    """The model exists but this GCP project cannot call it (not enabled in Model Garden, or a project setting such
    as data sharing is missing). The router remembers it so callers can move to the job's next model."""


def not_enabled(code: Any, message: str) -> bool:
    """Vertex AI's answer for a model this GCP project cannot call (403 / 404 with a 'not found / no access' text)."""
    return str(code) in ("403", "404") and any(w in message.lower() for w in (
        "not found", "access", "data sharing", "permission", "not enabled", "not allowed"))


_STALLED = ("Timeout", "ConnectError", "ConnectionError", "NetworkError", "RemoteProtocolError", "ProtocolError",
            "ReadError")


def _stalled(e: BaseException | None) -> bool:
    """A timeout or a dropped connection, from whichever HTTP stack the SDK runs on (httpx, requests, urllib3...):
    judged by the exception's type name along its cause chain, so no HTTP library has to be importable here."""
    seen = 0
    while e is not None and seen < 8:
        if isinstance(e, (TimeoutError, ConnectionError)) or any(s in type(e).__name__ for s in _STALLED):
            return True
        e, seen = e.__cause__ or e.__context__, seen + 1
    return False


def _status_error(model: Model, code: Any, message: str) -> ModelError:
    text = f"{model.label}: HTTP {code}: {message}"
    return ModelNotEnabled(text) if not_enabled(code, message) else ModelError(text)


def _clean(messages: list[dict]) -> list[dict]:
    """Messages for Claude: without our private keys (`_gemini_*`, kept so Gemini gets its thought signatures back)
    and without the empty text blocks a Gemini turn can leave (Claude refuses them)."""
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            c = [{k: v for k, v in b.items() if not k.startswith("_")} if isinstance(b, dict) else b for b in c
                 if not (isinstance(b, dict) and b.get("type") == "text" and not b.get("text"))]
            c = c or [{"type": "text", "text": "(no text)"}]
        out.append({**m, "content": c})
    return out


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

            # The SDK retries timeouts, connection errors, 429 and 5xx itself.
            client = AnthropicVertex(project_id=config.project, region=config.region_for("claude"), max_retries=2,
                                     timeout=request_timeout_s(), credentials=config.credentials)
        self.client = client

    def complete(self, model: Model, req: ModelRequest, on_text: OnText = None) -> ModelResponse:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": model.id,
            "max_tokens": req.max_tokens,
            # The system prompt is the stable prefix (instructions, knowledge-model excerpt, memory): cache it.
            "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            "messages": _clean(req.messages),
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
            raise _status_error(model, e.status_code, str(e.message)) from e
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

THINKING_LEVEL = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "XHIGH", "max": "XHIGH"}
REFUSAL = {"safety", "prohibited_content", "blocklist", "spii", "recitation", "image_safety"}


def _sig(b: dict) -> bytes | None:
    s = b.get("_gemini_sig")
    return base64.b64decode(s) if s else None


def _tool_output(content: Any) -> Any:
    """A tool_result's content as a JSON value for Gemini's function response."""
    if isinstance(content, list):  # text blocks
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


def _gemini_parts(content: Any, names: dict[str, str] | None = None) -> list:
    """Anthropic-shape blocks -> Gemini parts. `names` maps tool_use ids to tool names (a function response needs
    the name; it is filled as tool_use blocks go by)."""
    from google.genai import types

    names = {} if names is None else names
    if isinstance(content, str):
        return [types.Part.from_text(text=content)]
    parts = []
    for b in content:
        kind = b.get("type")
        if kind == "text":
            if b["text"] or _sig(b):
                parts.append(types.Part(text=b["text"], thought_signature=_sig(b)))
        elif kind in ("image", "document") and b.get("source", {}).get("type") == "base64":
            src = b["source"]
            parts.append(types.Part.from_bytes(data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
        elif kind == "tool_use":
            names[b["id"]] = b["name"]
            gid = b["id"] if "_gemini_id" not in b else b["_gemini_id"]
            parts.append(types.Part(function_call=types.FunctionCall(id=gid, name=b["name"], args=b.get("input") or {}),
                                    thought_signature=_sig(b)))
        elif kind == "tool_result":
            tid = b.get("tool_use_id", "")
            out = _tool_output(b.get("content"))
            response = {"error": out} if b.get("is_error") else {"output": out}
            gid = tid if not tid.startswith("gm_") else None  # our own id for a call Gemini sent without one
            parts.append(types.Part(function_response=types.FunctionResponse(id=gid, name=names.get(tid, "tool"),
                                                                             response=response)))
        elif kind in ("thinking", "redacted_thinking"):
            continue  # Claude's own reasoning: only Claude can read it back
        else:
            raise ModelError(f"Gemini provider cannot send a {kind!r} block")
    return parts


class VertexGemini:
    name = "vertex-gemini"

    def __init__(self, config: AIConfig, client: Any = None):
        if client is None:
            from google import genai
            from google.genai import types

            # google-genai has no timeout by default: a stalled stream would wait forever. HttpOptions takes ms.
            client = genai.Client(vertexai=True, project=config.project, location=config.region_for("gemini"),
                                  credentials=config.credentials,
                                  http_options=types.HttpOptions(timeout=int(request_timeout_s() * 1000)))
        self.client = client

    def complete(self, model: Model, req: ModelRequest, on_text: OnText = None) -> ModelResponse:
        """One model turn. With tools, Gemini's function calls come back as Anthropic tool_use blocks (and tool_result
        blocks go to Gemini as function responses), so the agent loop is the same for both families. Gemini's thought
        signatures ride along on the blocks as `_gemini_sig` and go back with the next request, as Gemini requires."""
        from google.genai import errors, types

        names: dict[str, str] = {}
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=_gemini_parts(m["content"], names)) for m in req.messages]
        config = types.GenerateContentConfig(system_instruction=req.system, max_output_tokens=req.max_tokens)
        if req.json_schema:
            config.response_mime_type = "application/json"
            config.response_json_schema = req.json_schema
        if req.tools:
            config.tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t.get("description", ""),
                                          parameters_json_schema=t.get("input_schema") or {"type": "object"})
                for t in req.tools])]
            config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        if req.effort in THINKING_LEVEL:
            config.thinking_config = types.ThinkingConfig(thinking_level=THINKING_LEVEL[req.effort])
        blocks: list[dict] = []
        usage, finish = None, ""
        try:
            for chunk in self.client.models.generate_content_stream(model=model.id, contents=contents, config=config):
                usage = chunk.usage_metadata or usage
                if not chunk.candidates:
                    continue
                cand = chunk.candidates[0]
                for p in (cand.content.parts if cand.content and cand.content.parts else []):
                    _add_part(blocks, p, on_text)
                if cand.finish_reason:
                    finish = str(cand.finish_reason.value).lower()
        except errors.APIError as e:
            raise _status_error(model, e.code, str(e.message)) from e
        except Exception as e:
            if _stalled(e):
                raise ModelTimeout(f"{model.label}: no answer in time: {type(e).__name__}: {e}") from e
            if type(e).__module__.startswith("google.auth"):
                raise ModelUnavailable(f"Google credentials: {e}. Run `gcloud auth application-default login`.") from e
            raise
        if finish == "malformed_function_call":
            raise ModelError(f"{model.label} sent a malformed function call")
        calls = [ToolCall(b["id"], b["name"], b["input"]) for b in blocks if b["type"] == "tool_use"]
        stop = ("tool_use" if calls else "max_tokens" if finish == "max_tokens" else
                "refusal" if finish in REFUSAL else "end_turn")
        text = "".join(b["text"] for b in blocks if b["type"] == "text")
        if not blocks:
            blocks = [{"type": "text", "text": ""}]
        prompt = (usage.prompt_token_count or 0) if usage else 0
        cached = (usage.cached_content_token_count or 0) if usage else 0
        out = ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0
        return ModelResponse(text=text, content=blocks, tool_calls=calls, stop_reason=stop,
                             input_tokens=max(0, prompt - cached), output_tokens=out, cache_read=cached,
                             model=model.key)


def _add_part(blocks: list[dict], p: Any, on_text: OnText) -> None:
    """Fold one streamed Gemini part into Anthropic-shape blocks: text joins the text block before it, a function
    call is a tool_use block. Thoughts are skipped; a signature sits on the block it came with."""
    sig = base64.b64encode(p.thought_signature).decode() if getattr(p, "thought_signature", None) else None
    if getattr(p, "thought", False):
        return
    if p.function_call:
        fc = p.function_call
        n = sum(b["type"] == "tool_use" for b in blocks)
        block = {"type": "tool_use", "id": fc.id or f"gm_{n}_{fc.name}", "name": fc.name, "input": dict(fc.args or {})}
        if not fc.id:
            block["_gemini_id"] = None
        if sig:
            block["_gemini_sig"] = sig
        blocks.append(block)
        return
    if p.text is None and not sig:
        return
    if blocks and blocks[-1]["type"] == "text" and not blocks[-1].get("_gemini_sig"):
        blocks[-1]["text"] += p.text or ""
    else:
        blocks.append({"type": "text", "text": p.text or ""})
    if sig:
        blocks[-1]["_gemini_sig"] = sig
    if p.text and on_text:
        on_text(p.text)


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
