"""The mapper's model step, used only for points the rules leave unsure.

The provider is given a short candidate list (never the full Brick list) and must pick one of those candidates or
none. Providers:

  none     no calls, no cost; leftovers go to human review as they are (the default)
  haiku    the `point_class` job in `projectmodel.ai` (Claude Haiku 5.5 on Vertex AI, escalating to Sonnet 5.5)
  sonnet   the same job, starting on Sonnet 5.5 (for the bake-off)

A provider that logs its own calls (`logs_calls = True`) is bound to the store, project and revision before the
run, so every attempt (escalations included) is one row in llm_calls; otherwise the mapper logs the answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from rdflib import URIRef
from rdflib.namespace import RDFS, SKOS


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


def class_definition(km, cls: str) -> str:
    """A one-line definition of a class from Brick (or the BA extension), for a candidate list."""
    if km is None or cls not in km.classes:
        return ""
    uri = km.uri(cls)
    for pred in (SKOS.definition, RDFS.comment):
        for o in km.graph.objects(URIRef(uri), pred):
            text = " ".join(str(o).split())
            return text[:200]
    return ""


class JobClassifier:
    """Runs the `point_class` job. Points it cannot call a model for (no credentials) stay with the rules' guess."""

    logs_calls = True

    def __init__(self, km=None, model: str | None = None, router=None):
        from ..ai.calls import default_router

        self.km, self.model = km, model
        self.router = router or default_router()
        self.name = f"vertex:{model or 'point_class'}"
        self.store, self.project, self.revision = None, "", 0
        self.unavailable: str | None = None

    def bind(self, store, project: str, revision: int) -> None:
        self.store, self.project, self.revision = store, project, revision

    def classify_point(self, req: LLMRequest) -> LLMAnswer | None:
        from ..ai.jobs import run_job
        from ..ai.providers import ModelError, ModelUnavailable

        if self.unavailable or not req.candidates:
            return None
        lines = []
        for c in req.candidates:
            d = class_definition(self.km, c)
            lines.append(f"- {c}" + (f": {d}" if d else ""))
        values = {"name": req.name, "path": req.path or "(none)", "equipment_class": req.equipment_class or "(unknown)",
                  "candidates": "\n".join(lines), "candidate_list": req.candidates}
        try:
            res = run_job("point_class", values, router=self.router, store=self.store, project=self.project,
                          revision=self.revision, model=self.model)
        except ModelUnavailable as e:
            self.unavailable = str(e)  # stop trying for the rest of the run
            return None
        except ModelError as e:
            return LLMAnswer(None, 0.0, str(e), 0.0, 0.0, self.model)
        from ..calibration import calibrate_model

        out = res.output
        # The model's own number stays in llm_calls; the mapper gets it calibrated for this job and model.
        return LLMAnswer(out["class"], calibrate_model("point_class", float(out["confidence"]), res.model),
                         json.dumps(out), res.cost_usd, res.latency_s, res.model)


def get_provider(name: str, km=None) -> LLMProvider:
    if name == "none":
        return NoLLM()
    if name in ("haiku", "vertex", "point_class"):
        return JobClassifier(km)
    if name in ("sonnet", "opus"):
        return JobClassifier(km, model=name)
    raise ValueError(f"unknown LLM provider {name!r}; use none, haiku or sonnet")
