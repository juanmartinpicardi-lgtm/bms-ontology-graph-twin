"""Every model call goes through `Router.call`: pick the provider for the model, time it, price it, log it.

Each call is one row in `llm_calls` (CLAUDE.md §8: input, output, cost, latency), with the job, the prompt version,
token counts and whether it succeeded. A failed call is logged too (ok = 0, error), so a cost report never misses one.
Images and PDFs in the input are logged as a size and hash, not their bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from ..db.store import Store
from .config import AIConfig, load_config
from .models import MODELS, Model, get_model
from .providers import (ModelError, ModelNotEnabled, ModelRequest, ModelResponse, ModelUnavailable, NoModel, OnText,
                        Provider, VertexClaude, VertexGemini, not_enabled)


def _redact(value: Any) -> Any:
    """Copy of a request with base64 payloads replaced by their size and hash."""
    if isinstance(value, dict):
        if value.get("type") == "base64" and isinstance(value.get("data"), str):
            data = value["data"]
            return {**value, "data": f"<{len(data)} b64 chars sha1={hashlib.sha1(data.encode()).hexdigest()[:10]}>"}
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def request_log(req: ModelRequest) -> str:
    return json.dumps({"system": req.system, "messages": _redact(req.messages),
                       "tools": [t["name"] for t in req.tools], "json_schema": bool(req.json_schema),
                       "effort": req.effort}, default=str)


class Router:
    """Holds one provider per model family. Tests pass `providers` to replace them."""

    def __init__(self, config: AIConfig | None = None, providers: dict[str, Provider] | None = None):
        self.config = config or load_config()
        self._providers: dict[str, Provider] = dict(providers or {})
        self._given = bool(providers)  # tests hand in their providers: ready whatever the config says
        self.not_enabled: dict[str, str] = {}  # model key -> why, learnt from calls (404 / 403 from Vertex AI)
        self.learnt = False  # learn() has read the call log

    def learn(self, store: Store, days: int = 3) -> None:
        """Remember the models whose latest call in the last `days` answered "not enabled in this project", so a
        fresh process (a restart, a code reload) does not try them again first. A later successful call clears it."""
        by_id = {m.id: m.key for m in MODELS.values()}
        rows = store.conn.execute("SELECT model, ok, error FROM llm_calls WHERE created_at >= datetime('now', ?) "
                                  "ORDER BY id", (f"-{days} days",)).fetchall()
        latest = {r["model"]: r for r in rows if r["model"] in by_id}
        for model_id, r in latest.items():
            m = re.search(r"HTTP (\d{3}): (.*)", r["error"] or "", re.S)
            if not r["ok"] and m and not_enabled(m.group(1), m.group(2)):
                self.not_enabled.setdefault(by_id[model_id], r["error"])
        self.learnt = True

    def first_enabled(self, keys: list[str]) -> str:
        """The first of these models not known to be off for this project (the first one when all are)."""
        return next((k for k in keys if k not in self.not_enabled), keys[0])

    @property
    def ready(self) -> bool:
        return self._given or self.config.ready

    def why_not_ready(self) -> str:
        return "" if self.ready else (self.config.why_off or "model calls are off")

    def provider(self, family: str) -> Provider:
        if family not in self._providers:
            if not self.config.ready:
                self._providers[family] = NoModel(self.why_not_ready())
            elif family == "claude":
                self._providers[family] = VertexClaude(self.config)
            elif family == "gemini":
                self._providers[family] = VertexGemini(self.config)
            else:
                raise KeyError(f"no provider for model family {family!r}")
        return self._providers[family]

    def call(self, model: str | Model, req: ModelRequest, *, job: str, prompt: str = "", store: Store | None = None,
             project: str = "", revision: int = 0, on_text: OnText = None) -> ModelResponse:
        """Call one model once. Raises ModelUnavailable (nothing was called) or ModelError (logged as failed)."""
        m = get_model(model) if isinstance(model, str) else model
        provider = self.provider(m.family)
        t0 = time.perf_counter()
        try:
            resp = provider.complete(m, req, on_text)
            self.not_enabled.pop(m.key, None)  # enabled since (e.g. turned on in Model Garden)
        except ModelUnavailable:
            raise
        except Exception as e:
            if isinstance(e, ModelNotEnabled):
                self.not_enabled[m.key] = str(e)
            if store is not None:
                store.log_llm_call(project, revision, provider.name, m.id, request_log(req), None, 0.0,
                                   round(time.perf_counter() - t0, 3), job=job, prompt=prompt, ok=False,
                                   error=str(e)[:2000])
            raise e if isinstance(e, ModelError) else ModelError(f"{m.label}: {e}") from e
        resp.latency_s = round(time.perf_counter() - t0, 3)
        resp.cost_usd = m.cost(resp.input_tokens, resp.output_tokens, resp.cache_read, resp.cache_write)
        resp.provider = provider.name
        error = None
        if resp.stop_reason == "refusal":
            error = f"{m.label} declined the request"
        elif resp.stop_reason == "max_tokens":
            error = f"{m.label} hit max_tokens ({req.max_tokens}); the answer is cut off"
        elif req.json_schema and resp.json is None:
            try:
                resp.json = parse_json(resp.text)
            except ModelError as e:
                error = str(e)
        if store is not None:
            resp.call_id = store.log_llm_call(
                project, revision, provider.name, m.id, request_log(req), json.dumps(resp.content, default=str),
                resp.cost_usd, resp.latency_s, job=job, prompt=prompt,
                input_tokens=resp.input_tokens + resp.cache_write, output_tokens=resp.output_tokens,
                cached_tokens=resp.cache_read, ok=error is None, error=error)
        if error:
            raise ModelError(error)
        return resp


def parse_json(text: str) -> Any:
    """The JSON object in a model's text answer (tolerates a ```json fence around it)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise ModelError(f"output is not valid JSON: {e}") from e


_default: Router | None = None
_pinned = False


def default_router() -> Router:
    """The app's router, rebuilt when the config changes (e.g. secrets saved while the server runs)."""
    global _default
    if _pinned and _default is not None:
        return _default
    cfg = load_config()
    if _default is None or _default.config is not cfg:
        _default = Router(cfg)
    return _default


def set_default_router(router: Router | None) -> None:
    """Use this router everywhere (tests), or None to go back to the one built from the config."""
    global _default, _pinned
    _default, _pinned = router, router is not None
