"""The jobs models do, one entry per row of spec-ai-architecture §3: default model, contender, escalation, prompt and
output schema.

`run_job` calls the default model; output that fails the schema or the job's own check counts as a failure and goes
to the next model in the escalation list. Every attempt is logged by the router. The contender is used when a
bake-off asks for it explicitly (`model=`), and in place of the default and escalation models when this GCP project
has not enabled them (the router learns that from the first 404 / 403).

Jobs marked `planned` have no prompt yet: they document who will do the work and fail clearly if called.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from ..db.store import Store
from .. import file_ai as _file_ai
from ..intake import sequence_ai as _sequence_ai
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


POINT_BIND_SCHEMA = _obj({
    "pick": {"type": ["string", "null"], "description": "The id of the candidate BMS object (B1, B2...), or null."},
    "confidence": {"type": "number", "description": "Probability the answer is right, 0 to 1."},
    "why": {"type": "string"},
})


def _check_point_bind(out: Any, values: dict) -> str | None:
    """Candidates in, ids out (intake/binding.py): the pick is one of the ids given, or null."""
    if out["pick"] is not None and out["pick"] not in values["candidate_list"]:
        return f"pick {out['pick']!r} is not one of the candidates"
    if not 0 <= out["confidence"] <= 1:
        return "confidence must be between 0 and 1"
    return None


MEMORY_CURATOR_SCHEMA = _obj({"choices": {"type": "array", "items": _obj({
    "candidate": {"type": "string", "description": "A candidate id (C…)."},
    "option": {"type": "string", "description": "One of that candidate's option ids, as given (C1.names)."},
    "title": {"type": "string", "description": "The convention in one plain sentence, at most 140 characters."},
    "why": {"type": "string", "description": "Why, from the fixes and the dry run, in one or two sentences."},
})}})


def _check_memory_curator(out: Any, values: dict) -> str | None:
    """Candidates in, ids out (curator.py): the model picks one of the rules' options per candidate and phrases it.
    It never names a class or writes a pattern, so an unknown id is a failure."""
    options = values.get("option_ids", {})
    for c in out["choices"]:
        if c["candidate"] not in options:
            return f"{c['candidate']!r} is not a candidate"
        oid = c["option"].split(".", 1)[-1] if c["option"].startswith(c["candidate"] + ".") else None
        if oid not in options[c["candidate"]]:
            return f"{c['option']!r} is not an option of {c['candidate']}"
        if not c["title"].strip() or len(c["title"]) > 200:
            return "a title must be one sentence of at most 200 characters"
    return None


FLOOR_ID = r"^(L\d{1,2}|B\d|RF)$"
PLAN_MEANING_SCHEMA = _obj({
    "page_kind": {"type": "string", "enum": ["plan", "schedule", "sequence", "riser", "submittal", "other"]},
    "views": {"type": "array", "items": _obj({"floor": {"type": "string", "pattern": FLOOR_ID},
                                             "title": {"type": "string"}})},
    "rooms": {"type": "array", "items": _obj({
        "id": {"type": "string", "description": "A room label candidate id (R…)."},
        "name": {"type": "string", "description": "Copied from the words given with the candidate, or \"\"."},
        "floor": {"type": "string", "pattern": FLOOR_ID},
        "box": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
                "description": "[x0, top, x1, bottom] in PDF points, or null."},
        "confidence": {"type": "number"},
    })},
    "placements": {"type": "array", "items": _obj({
        "tag": {"type": "string", "description": "A tag candidate id (T…)."},
        "room": {"type": ["string", "null"], "description": "A room id from `rooms`, or null."},
        "floor": {"type": "string", "pattern": FLOOR_ID},
        "rel": {"type": "string", "enum": ["serves", "located_in"]},
        "confidence": {"type": "number"},
        "why": {"type": "string"},
    })},
})


def _check_plan_meaning(out: Any, values: dict) -> str | None:
    """Candidates in, ids out: an answer that names ids we never gave (beyond a stray one, which plan_ai drops and
    counts), or confidences outside 0..1, fails and escalates."""
    rooms, tags = set(values.get("room_ids", ())), set(values.get("tag_ids", ()))
    given = [r["id"] for r in out["rooms"]] + [p["tag"] for p in out["placements"]]
    unknown = [i for i in given if i not in rooms | tags]
    if given and len(unknown) > max(2, 0.1 * len(given)):
        return f"{len(unknown)} ids that are not candidates (e.g. {unknown[:3]})"
    if any(not 0 <= x["confidence"] <= 1 for x in [*out["rooms"], *out["placements"]]):
        return "confidence must be between 0 and 1"
    if out["page_kind"] == "plan" and (out["rooms"] or out["placements"]) and not out["views"]:
        return "a plan with rooms or placements needs at least one view and its floor"
    return None


JOBS: dict[str, Job] = {j.id: j for j in [
    # Gemini reads the page image with our candidates (intake/plan_ai.py). Contender: Argon stands in while Claude is
    # not enabled on the project (Sonnet, the spec's contender, answers 404 there in Nov 2026).
    Job("plan_meaning", "Floor plans: meaning", "hydrogen", ("argon", "sonnet"), ("opus",), prompt="plan_meaning",
        schema=PLAN_MEANING_SCHEMA, check=_check_plan_meaning, max_tokens=16000, effort="low", status="built",
        people="Answer asks"),
    Job("schedule_layout", "Schedules: draft a layout per firm", "opus", ("argon",), ("fable",),
        people="Approve the layout"),
    # Contenders stand in while Claude is not enabled on our project: Hydrogen (the spec's contender; best on the
    # Troop D bake-off, F1 87 vs Argon's 83, $0.03 a sequence), then Argon. Schema and check: intake/sequence_ai.py.
    Job("sequence_read", "Sequences", "sonnet", ("hydrogen", "argon"), ("opus",), prompt="sequence_read",
        schema=_sequence_ai.SCHEMA, check=_sequence_ai.check, max_tokens=32000, effort="low", status="built",
        people="Confirm the logic"),
    Job("submittal_read", "Controls submittal", "hydrogen", ("sonnet",), ("opus",), people="Answer asks"),
    Job("bms_headers", "BMS export: unknown headers", None, (), ("haiku",)),
    # Contender: the spec's (Jev, gpt-oss-20b) are not on our Vertex AI project yet; Argon stands in while Claude is
    # not enabled (live: right class on the sample point, 4.7 s, $0.0023 a point vs Hydrogen's 17 s, $0.0037).
    Job("point_class", "Point → class", "haiku", ("argon",), ("sonnet",), prompt="point_class", schema=POINT_CLASS_SCHEMA,
        check=_check_point_class, max_tokens=1000, effort="low", status="built",
        people="Review below the threshold"),
    Job("same_unit", "Same unit across documents", "haiku", people="Confirm"),
    # W7: for a submittal point the rules could not bind, pick its BMS object from the device's free objects
    # (intake/binding.py). Contenders stand in while Claude is not enabled on our project (Haiku and Sonnet 404).
    Job("point_bind", "Point binding: submittal point to BMS object", "haiku", ("argon", "hydrogen"), ("sonnet",),
        prompt="point_bind", schema=POINT_BIND_SCHEMA, check=_check_point_bind, max_tokens=1000, effort="low",
        status="built", people="Confirm below the threshold"),
    Job("equipment_variant", "Equipment 3D: pick the variant", "haiku", ("hydrogen",)),
    # The learning loop (curator.py): the rules find repeated fixes and the patterns that cover them; the model only
    # picks one of those patterns per candidate and phrases the proposal. Hydrogen stands in while Claude is off.
    Job("memory_curator", "Memory curator", "sonnet", ("hydrogen", "argon"), ("opus", "fable"),
        prompt="memory_curator", schema=MEMORY_CURATOR_SCHEMA, check=_check_memory_curator, max_tokens=4000,
        effort="low", status="built", people="Approve"),
    Job("agent_chat", "Agent, text", "sonnet", ("argon",), ("opus",), prompt="agent_chat", max_tokens=16000,
        effort="low", status="built", people="Ask, correct, confirm writes"),
    Job("agent_reason", "Agent, reasoning", "opus", ("argon",), ("fable",), prompt="agent_chat", max_tokens=32000,
        effort="high", status="built"),
    Job("name_resolve", "Name to entity, when rules are ambiguous", "haiku"),
    Job("snapshot_question", "Snapshot and photo questions", "hydrogen"),
    # Any file a person gives (fileread.py reads it): the knowledge it teaches, each item quoting the file, for the
    # person to confirm (file_ai.py); and what a project document is, for the Documentation page.
    Job("knowledge_extract", "Knowledge from any file", "hydrogen", ("argon",), ("opus",), prompt="knowledge_extract",
        schema=_file_ai.KNOWLEDGE_SCHEMA, check=_file_ai.check_knowledge, max_tokens=8000, effort="low",
        status="built", people="Confirm each rule and note"),
    Job("document_digest", "Documents: what a file is", "hydrogen", ("argon",), ("sonnet",), prompt="document_digest",
        schema=_file_ai.DIGEST_SCHEMA, check=_file_ai.check_digest, max_tokens=3000, effort="low", status="built",
        people="Change the category if wrong"),
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


def job_request(job_id: str, values: dict, user_content: list | None = None):
    """The request a job sends for these values, and its prompt (the same for every model in the chain)."""
    job = get_job(job_id)
    if job.status != "built" or not job.prompt:
        raise ModelError(f"job {job_id!r} is planned, not built yet")
    prompt = load_prompt(job.prompt)
    system, user = prompt.render(**{k: v for k, v in values.items() if isinstance(v, (str, int, float))})
    content: Any = user if not user_content else [{"type": "text", "text": user}, *user_content]
    req = ModelRequest(system=system, messages=[{"role": "user", "content": content}], max_tokens=job.max_tokens,
                       json_schema=job.schema, effort=job.effort)
    return req, prompt


def check_output(job_id: str, out: Any, values: dict) -> str | None:
    """Why this output fails the job's schema or check, or None when it passes."""
    job = get_job(job_id)
    if job.schema:
        try:
            jsonschema.validate(out, job.schema)
        except jsonschema.ValidationError as e:
            return f"schema: {e.message}"
    return job.check(out, values) if job.check else None


def run_job(job_id: str, values: dict, *, router: Router | None = None, store: Store | None = None,
            project: str = "", revision: int = 0, model: str | None = None, user_content: list | None = None
            ) -> JobResult:
    """Run a job on its default model, escalating while the output fails the checks.

    values fill the prompt's placeholders (extra keys are available to the job's check). user_content, when given,
    is sent as the user message's content blocks (images, PDFs) after the rendered user text.
    Raises ModelUnavailable when no model can be called, ModelError when every model in the chain failed."""
    job = get_job(job_id)
    router = router or default_router()
    req, prompt = job_request(job_id, values, user_content)
    result = JobResult(job_id, None, "")
    for key in ([model] if model else job.chain + list(job.contender)):
        if not model and key in router.not_enabled:
            continue
        if not model and key in job.contender and any(a["model"] not in router.not_enabled for a in result.attempts):
            break  # the contender stands in only for models this project has not enabled
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
        problem = check_output(job_id, out, values)
        result.attempts.append({"model": key, "call": resp.call_id, "problem": problem})
        if problem is None:
            result.output, result.model = out, key
            return result
    raise ModelError(f"{job.title}: every model failed: "
                     + "; ".join(f"{a['model']}: {a['problem']}" for a in result.attempts))
