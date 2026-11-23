"""The models we may call, where they run and what they cost (spec-ai-architecture §2-3).

Prices are USD per million tokens, input / output, as reported in Nov 2026; Vertex AI bills partner models at its own
rates, so check the Vertex pricing page before trusting a cost total. Model ids can be overridden per deployment
with an environment variable `PM_MODEL_<KEY>` (e.g. `PM_MODEL_HYDROGEN=gemini-4-hydrogen-001`) when Model Garden
publishes a versioned id.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    key: str            # our short name, used in jobs and the UI
    family: str         # claude | gemini
    vertex_id: str      # the id Vertex AI expects
    label: str
    price_in: float     # USD per million input tokens
    price_out: float    # USD per million output tokens
    cache_read: float | None = None  # USD per million cached input tokens, when known

    @property
    def id(self) -> str:
        return os.environ.get(f"PM_MODEL_{self.key.upper()}", self.vertex_id)

    def cost(self, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
        """input_tokens: input billed at the full rate (not read from or written to the cache)."""
        read_price = self.cache_read if self.cache_read is not None else self.price_in * 0.1
        usd = (input_tokens * self.price_in + cache_read * read_price + cache_write * self.price_in * 1.25
               + output_tokens * self.price_out)
        return round(usd / 1e6, 6)


MODELS: dict[str, Model] = {m.key: m for m in [
    Model("fable", "claude", "claude-fable-5-2", "Claude Fable 5.2", 8.00, 40.00, 0.20),
    Model("opus", "claude", "claude-opus-5-5", "Claude Opus 5.5", 4.00, 20.00, 0.20),
    Model("sonnet", "claude", "claude-sonnet-5-5", "Claude Sonnet 5.5", 2.00, 10.00, 0.10),
    Model("haiku", "claude", "claude-haiku-5-5", "Claude Haiku 5.5", 0.10, 0.50),
    Model("hydrogen", "gemini", "gemini-4-hydrogen", "Gemini 4 Hydrogen", 1.50, 7.50),
    Model("argon", "gemini", "gemini-4-argon", "Gemini 4 Argon (price unconfirmed)", 2.50, 15.00),
]}


def get_model(key: str) -> Model:
    if key not in MODELS:
        raise KeyError(f"unknown model {key!r}; known: {sorted(MODELS)}")
    return MODELS[key]


# The voice model runs on the Live API (a WebSocket session, not generate_content), in one region: it is not in MODELS,
# so the text pickers and ai_check leave it out. Priced per million audio tokens (about 25 a second), unconfirmed.
LIVE = Model("live", "gemini-live", "gemini-3.8-live", "Gemini 3.8 Live (price unconfirmed)", 3.00, 12.00)
LIVE_REGION_DEFAULT = "us-central1"  # Live models answer there on our project (not on global, 2026-11-20)
