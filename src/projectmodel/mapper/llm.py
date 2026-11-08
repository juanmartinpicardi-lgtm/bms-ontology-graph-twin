"""One LLM provider behind a small interface, used only for points the rules leave unsure.

The provider is given a short candidate list (never the full Brick list) and must pick one of
those candidates or none. Every call is logged by the caller with input, output, cost, latency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMRequest:
    name: str
    path: str | None
    equipment_class: str | None
    candidates: list[str]


@dataclass
class LLMAnswer:
    cls: str | None  # one of the candidates, or None
    confidence: float
    raw_output: str
    cost_usd: float
    latency_s: float
    model: str | None


class LLMProvider(Protocol):
    name: str

    def classify_point(self, req: LLMRequest) -> LLMAnswer | None:
        """Return None when the provider makes no call at all."""


class NoLLM:
    """Default: no calls, no cost. Leftovers go to human review as they are."""

    name = "none"

    def classify_point(self, req: LLMRequest) -> LLMAnswer | None:
        return None


def get_provider(name: str) -> LLMProvider:
    if name == "none":
        return NoLLM()
    raise ValueError(f"unknown LLM provider {name!r}; only 'none' is implemented so far")
