"""The text agent (spec-agent §5, phase A2): Claude on Vertex AI with the graph's read tools, citing every fact.

    agent = Agent(router, tools=GraphTools(...), knowledge=kb, project="alpha/names_paths")
    turn = agent.run(history, "Why is zone 2-14 warm?", packet, emit=on_event)

`history` is the conversation so far in the Anthropic message shape (it grows by the turn's messages, append-only,
so thinking blocks stay valid). `emit` receives events as they happen, in the AG-UI spirit:

    Event("text", delta)                     answer text as it streams
    Event("tool", {"name", "input"})         a tool call starts
    Event("tool_result", {"name", "summary"})
    Event("model", {"model"})                the model changed (handover to Opus 5.5)

Routing: Sonnet 5.5 at low effort by default; Opus 5.5 when the person asks to think it through, or once the turn
needs more than HANDOVER tool hops (when that is another model). When the GCP project has not enabled a Claude model,
the job's contender (Gemini 4 Argon) takes over, with the same tools and history. A model picked in the dock answers
the whole turn. Every model call is logged by the router (job agent_chat or agent_reason).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..agent_tools import TOOLS, GraphTools
from ..agent_tools import call as call_tool
from ..ai.calls import Router
from ..ai.jobs import get_job
from ..ai.models import get_model
from ..ai.prompts import load_prompt
from ..ai.providers import ModelError, ModelNotEnabled, ModelRequest, ModelUnavailable

MAX_STEPS = 14       # model calls in one turn
HANDOVER = 4         # tool hops on Sonnet before Opus takes over
RESULT_CHARS = 14000
THINK = re.compile(r"(?i)\b(think (it|this) (through|over)|think about it|reason (it|this) out|step by step|"
                   r"root cause|dig deeper)\b")

SKILL_TOOL = {"name": "skill_view",
              "description": "Read one of our skills (a procedure the team wrote, listed in 'Skills' in your "
                             "instructions). Read it before following it; cite it as [[skill:name]].",
              "input_schema": {"type": "object", "properties": {
                  "name": {"type": "string"},
                  "path": {"type": "string", "description": "Optional file inside the skill, e.g. rules/layouts.yaml"}},
                  "required": ["name"]}}


@dataclass
class Event:
    type: str
    data: Any = None


@dataclass
class TurnResult:
    text: str
    model: str
    steps: list[dict] = field(default_factory=list)     # tool calls: name, input, summary, error
    cost_usd: float = 0.0
    seconds: float = 0.0
    calls: list[int] = field(default_factory=list)      # llm_calls rows
    cited: list[str] = field(default_factory=list)      # ids cited in the answer
    error: str | None = None


def citations(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\[\[([^\]]+)\]\]", text)))


def _summary(name: str, result: dict) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if name == "find_nodes":
        return f"{result.get('total', 0)} found"
    if name in ("upstream", "downstream"):
        return f"{result.get('total', 0)} linked"
    if name == "behaviour":
        return f"{len(result.get('facts', []))} sequence facts"
    if name == "describe":
        return f"{result.get('name')} · {result.get('class')} · {result.get('trust')}"
    if name == "skill_view":
        return "read"
    return "done"


class Agent:
    def __init__(self, router: Router, tools: GraphTools | None = None, knowledge=None, project: str | None = None,
                 person: str | None = None, store=None):
        self.router, self.tools, self.kb, self.project, self.person = router, tools, knowledge, project, person
        self.store = store

    # prompt ------------------------------------------------------------------------------------------------------

    def system(self) -> tuple[str, str]:
        """(system prompt, prompt ref). Stable for a project and person, so it is cached across turns."""
        p = load_prompt("agent_chat")
        parts = [p.render()[0]]
        if self.kb is not None:
            scopes = self.kb.scopes_for(self.project)
            if mem := self.kb.memory_text(scopes, self.person):
                parts.append("# Memory\nWhat the team knows, general first. Cite an entry as [[m-0001]] when it "
                             "shapes your answer.\n\n" + mem)
            if idx := self.kb.skills_index(scopes):
                parts.append("# Skills\nProcedures the team wrote. Read one with skill_view before you follow it.\n"
                             + "\n".join(f"- {s['name']} ({s['scope']}): {s['description']}" for s in idx))
        if not self.tools:
            parts.append("# No project\nNo project is open, so the graph tools are not available. Answer from the "
                         "memory and skills, and say when a question needs a project.")
        return "\n\n".join(parts), p.ref

    def tool_defs(self) -> list[dict]:
        out = list(TOOLS) if self.tools else []
        if self.kb is not None and self.kb.skills:
            out.append(SKILL_TOOL)
        return out

    def _run_tool(self, name: str, args: dict) -> dict:
        if name == "skill_view":
            if self.kb is None:
                return {"error": "no skills loaded"}
            try:
                return {"skill": args.get("name"), "text": self.kb.skill_view(args.get("name", ""), args.get("path"))}
            except KeyError as e:
                return {"error": str(e.args[0])}
        if self.tools is None:
            return {"error": "no project is open"}
        return call_tool(self.tools, name, args)

    # the turn ----------------------------------------------------------------------------------------------------

    def run(self, history: list[dict], question: str, packet: dict,
            emit: Callable[[Event], None] = lambda e: None, model: str | None = None,
            effort: str | None = None) -> TurnResult:
        """One turn. `model` (a key in ai.models) pins the model for the whole turn: no handover, no fallback.
        `effort` overrides the job's (low | medium | high)."""
        t0 = time.perf_counter()
        system, prompt_ref = self.system()
        tools = self.tool_defs()
        user = f"<context>\n{json.dumps(packet, ensure_ascii=False)}\n</context>\n\n{question}"
        history.append({"role": "user", "content": user})
        job = "agent_reason" if THINK.search(question) else "agent_chat"
        pinned = model is not None
        model = model or pick_model(self.router, job)
        res = TurnResult(text="", model=model)
        emit(Event("model", {"model": model}))
        hops = 0
        for _ in range(MAX_STEPS):
            j = get_job(job)
            req = ModelRequest(system=system, messages=history, tools=tools, max_tokens=j.max_tokens,
                               effort=effort or j.effort)
            try:
                resp = self.router.call(model, req, job=job, prompt=prompt_ref, store=self.store,
                                        project=self.project or "", on_text=lambda d: emit(Event("text", d)))
            except ModelNotEnabled as e:
                # This project cannot call that model: the job's contender takes the turn (the router remembers).
                # A model the person picked is not swapped behind their back.
                if pinned or (nxt := pick_model(self.router, job)) == model:
                    res.error = str(e)
                    break
                model = nxt
                emit(Event("model", {"model": model}))
                continue
            except (ModelError, ModelUnavailable) as e:
                res.error = str(e)
                break
            res.cost_usd += resp.cost_usd
            if resp.call_id:
                res.calls.append(resp.call_id)
            history.append({"role": "assistant", "content": resp.content})
            if resp.text:
                res.text += ("\n\n" if res.text else "") + resp.text
            if resp.stop_reason != "tool_use" or not resp.tool_calls:
                break
            results = []
            for tc in resp.tool_calls:
                emit(Event("tool", {"name": tc.name, "input": tc.input}))
                out = self._run_tool(tc.name, tc.input)
                text = json.dumps(out, ensure_ascii=False, default=str)
                if len(text) > RESULT_CHARS:
                    text = text[:RESULT_CHARS] + ' ... (cut: ask for less, e.g. describe one node)"'
                summary = _summary(tc.name, out)
                res.steps.append({"name": tc.name, "input": tc.input, "summary": summary, "error": "error" in out})
                emit(Event("tool_result", {"name": tc.name, "summary": summary}))
                results.append({"type": "tool_result", "tool_use_id": tc.id, "content": text,
                                **({"is_error": True} if "error" in out else {})})
            history.append({"role": "user", "content": results})
            hops += 1
            if job == "agent_chat" and hops >= HANDOVER and not pinned:
                # Hand over to the reasoning model. When that is the same model (no Opus in this project: Argon
                # both), stay on the chat job: thinking harder half way through costs time and adds little.
                if (nxt := pick_model(self.router, "agent_reason")) != model:
                    job, model = "agent_reason", nxt
                    emit(Event("model", {"model": model}))
        else:
            res.error = f"stopped after {MAX_STEPS} steps"
        if history[-1]["role"] == "user":
            # The turn ended without an answer (error or step limit): close it so the next question starts cleanly.
            history.append({"role": "assistant", "content": [{"type": "text", "text": res.error or "(stopped)"}]})
        res.model = model
        res.seconds = round(time.perf_counter() - t0, 2)
        res.cited = citations(res.text)
        return res


def pick_model(router: Router, job: str) -> str:
    """The job's default model, or its contender when this GCP project has not enabled the default (Sonnet 5.5 ->
    Gemini 4 Argon for agent_chat)."""
    j = get_job(job)
    return router.first_enabled([m for m in (j.default, *j.contender) if m])


def model_label(key: str) -> str:
    return get_model(key).label
