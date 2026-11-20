"""The jobs models do, one entry per row of spec-ai-architecture §3: default model, contender, escalation, prompt and
output schema.

`run_job` calls the default model; output that fails the schema or the job's own check counts as a failure and goes
to the next model in the escalation list. Every attempt is logged by the router. The contender is only used when a
bake-off asks for it explicitly (`model=`).

Jobs marked `planned` have no prompt yet: they document who will do the work and fail clearly if called.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from ..db.store import Store
from .calls import Router, default_router
from .providers import ModelError, ModelRequest, ModelUnavailable
from .prompts import load_prompt

Check = Callable[[Any, dict], str | None]  # (output, values) -> problem, or None when fine


@dataclass(frozen=True)
class Job:
    id: str
    title: str
    default: str | None                    # model key in ai.models, None: rules only
    contender: tuple[str, ...] = ()
    escalate: tuple[str, ...] = ()
    prompt: str | None = None              # prompt id in ai/prompts
    schema: dict | None = None             # typed JSON output
    check: Check | None = None
    max_tokens: int = 4000
    effort: str | None = None
    status: str = "planned"                # built | planned
    people: str = ""

    @property
    def chain(self) -> list[str]:
        return [m for m in (self.default, *self.escalate) if m]


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


POINT_CLASS_SCHEMA = _obj({
    "class": {"type": ["string", "null"], "description": "One of the candidates, or null when none fits."},
    "confidence": {"type": "number", "description": "Probability the class is right, 0 to 1."},
    "why": {"type": "string"},
})


def _check_point_class(out: Any, values: dict) -> str | None:
    if out["class"] is not None and out["class"] not in values["candidate_list"]:
        return f"class {out['class']!r} is not one of the candidates"
    if not 0 <= out["confidence"] <= 1:
        return "confidence must be between 0 and 1"
    return None


JOBS: dict[str, Job] = {j.id: j for j in [
    Job("plan_meaning", "Floor plans: meaning", "hydrogen", ("sonnet",), ("opus",), people="Answer asks"),
    Job("schedule_layout", "Schedules: draft a layout per firm", "opus", ("argon",), ("fable",),
        people="Approve the layout"),
    Job("sequence_read", "Sequences", "sonnet", ("hydrogen",), ("opus",), people="Confirm the logic"),
    Job("submittal_read", "Controls submittal", "hydrogen", ("sonnet",), ("opus",), people="Answer asks"),
    Job("bms_headers", "BMS export: unknown headers", None, (), ("haiku",)),
    Job("point_class", "Point → class", "haiku", (), ("sonnet",), prompt="point_class", schema=POINT_CLASS_SCHEMA,
        check=_check_point_class, max_tokens=1000, effort="low", status="built",
        people="Review below the threshold"),
    Job("same_unit", "Same unit across documents", "haiku", people="Confirm"),
    Job("equipment_variant", "Equipment 3D: pick the variant", "haiku", ("hydrogen",)),
    Job("memory_curator", "Memory curator", "sonnet", ("hydrogen",), ("opus", "fable"), people="Approve"),
    Job("agent_chat", "Agent, text", "sonnet", ("argon",), ("opus",), prompt="agent_chat", max_tokens=16000,
        effort="medium", status="built", people="Ask, correct, confirm writes"),
    Job("agent_reason", "Agent, reasoning", "opus", ("argon",), ("fable",), prompt="agent_chat", max_tokens=32000,
        effort="high", status="built"),
    Job("name_resolve", "Name to entity, when rules are ambiguous", "haiku"),
    Job("snapshot_question", "Snapshot and photo questions", "hydrogen"),
]}


def get_job(job_id: str) -> Job:
    if job_id not in JOBS:
        raise KeyError(f"unknown job {job_id!r}; known: {sorted(JOBS)}")
    return JOBS[job_id]


@dataclass
class JobResult:
    job: str
    output: Any                 # validated JSON, or text when the job has no schema
    model: str                  # model key that produced it
    attempts: list[dict] = field(default_factory=list)  # one per model tried: model, call id, problem
    cost_usd: float = 0.0
    latency_s: float = 0.0

    @property
    def escalated(self) -> bool:
        return len(self.attempts) > 1


def run_job(job_id: str, values: dict, *, router: Router | None = None, store: Store | None = None,
            project: str = "", revision: int = 0, model: str | None = None, user_content: list | None = None
            ) -> JobResult:
    """Run a job on its default model, escalating while the output fails the checks.

    values fill the prompt's placeholders (extra keys are available to the job's check). user_content, when given,
    is sent as the user message's content blocks (images, PDFs) after the rendered user text.
    Raises ModelUnavailable when no model can be called, ModelError when every model in the chain failed."""
    job = get_job(job_id)
    if job.status != "built" or not job.prompt:
        raise ModelError(f"job {job_id!r} is planned, not built yet")
    router = router or default_router()
    prompt = load_prompt(job.prompt)
    system, user = prompt.render(**{k: v for k, v in values.items() if isinstance(v, (str, int, float))})
    content: Any = user if not user_content else [{"type": "text", "text": user}, *user_content]
    req = ModelRequest(system=system, messages=[{"role": "user", "content": content}], max_tokens=job.max_tokens,
                       json_schema=job.schema, effort=job.effort)
    result = JobResult(job_id, None, "")
    for key in ([model] if model else job.chain):
        problem = None
        try:
            resp = router.call(key, req, job=job_id, prompt=prompt.ref, store=store, project=project,
                               revision=revision)
        except ModelUnavailable:
            raise
        except ModelError as e:
            result.attempts.append({"model": key, "call": None, "problem": str(e)})
            continue
        result.cost_usd += resp.cost_usd
        result.latency_s += resp.latency_s
        out = resp.json if job.schema else resp.text
        if job.schema:
            try:
                jsonschema.validate(out, job.schema)
            except jsonschema.ValidationError as e:
                problem = f"schema: {e.message}"
        if problem is None and job.check:
            problem = job.check(out, values)
        result.attempts.append({"model": key, "call": resp.call_id, "problem": problem})
        if problem is None:
            result.output, result.model = out, key
            return result
    raise ModelError(f"{job.title}: every model failed: "
                     + "; ".join(f"{a['model']}: {a['problem']}" for a in result.attempts))
