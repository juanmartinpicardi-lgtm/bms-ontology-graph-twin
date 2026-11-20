"""The conversation in the agent dock: history, the streaming answer with its tool steps, citations as trust badges,
cost per answer, and what the agent sees (the context packet)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from projectmodel.agent.chat import Agent, Event, model_label, pick_model
from projectmodel.agent.context import Chip, context_packet
from projectmodel.agent_tools import GraphTools
from projectmodel.ai.calls import default_router
from projectmodel.ai.models import MODELS
from projectmodel.app.shell import DB, knowledge_model
from projectmodel.memory import KNOWLEDGE_DIR, KnowledgeError, load_knowledge
from projectmodel.projects import site_of, summaries

TRUST_COLOR = {"verified": "green", "stated": "violet", "likely": "blue", "unsure": "orange"}
CITE = re.compile(r"\[\[([^\]]+)\]\](?:\s*\*(verified|stated|likely|unsure)\*)?")
TOOL_LABEL = {"find_nodes": "Search the graph", "describe": "Describe", "upstream": "Follow upstream",
              "downstream": "Follow downstream", "behaviour": "Read the sequences", "skill_view": "Read a skill"}


# cached resources ------------------------------------------------------------------------------------------------

def _db_stamp() -> float:
    return DB.stat().st_mtime if DB.exists() else 0.0


@st.cache_resource(show_spinner=False, max_entries=6)
def _graph_tools(project: str, stamp: float) -> GraphTools:
    from projectmodel.db.store import Store
    return GraphTools(Store(DB), knowledge_model(), project)


def graph_tools(store, project: str | None) -> GraphTools | None:
    if not project:
        return None
    try:
        return _graph_tools(project, _db_stamp())
    except Exception:  # noqa: BLE001 - a project with no graph yet: the agent works without tools
        return None


@st.cache_data(show_spinner=False, ttl=30)
def _summary(project: str, stamp: float) -> dict:
    from projectmodel.db.store import Store
    n = summaries(Store(DB)).get(project, {}).get("nodes", {})
    site = site_of(project)
    return {"points": n.get("point", 0), "equipment": n.get("equipment", 0), "kind": site.kind}


def project_summary(store, project: str | None) -> dict:
    return _summary(project, _db_stamp()) if project else {}


def _knowledge_stamp() -> float:
    return max((p.stat().st_mtime for p in KNOWLEDGE_DIR.rglob("*") if p.is_file()), default=0.0)


@st.cache_resource(show_spinner=False, max_entries=2)
def _knowledge(stamp: float):
    return load_knowledge(km=knowledge_model())


def knowledge():
    try:
        return _knowledge(_knowledge_stamp())
    except KnowledgeError as e:
        st.session_state["_knowledge_error"] = str(e)
        return None


# status ----------------------------------------------------------------------------------------------------------

def status_badge() -> None:
    r = default_router()
    if r.ready:
        key = picked()[0] or pick_model(r, "agent_chat")
        off = "".join(f" {model_label(k)} is not enabled in this project, so {model_label(key)} answers."
                      for k in r.not_enabled if k == "sonnet")
        st.badge(f"{model_label(key).split(' (')[0]} · Vertex AI", color="green", icon=":material/cloud_done:",
                 help=f"GCP project {r.config.project}, region {r.config.region}.{off} Every call is logged with its "
                      "cost.")
    else:
        st.badge("Models off", color="gray", icon=":material/cloud_off:", help=r.why_not_ready())


# rendering -------------------------------------------------------------------------------------------------------

def _label(tools: GraphTools | None, ref: str) -> str:
    if ref.startswith("m-"):
        return f"memory {ref}"
    if ref.startswith("skill:"):
        return f"skill {ref[6:]}"
    if tools is not None and (n := tools.tree.by_id.get(ref)):
        return n.label
    return ref.split(":", 1)[-1].split(" ")[-1]


def render_citations(text: str, tools: GraphTools | None) -> str:
    """[[id]] *trust* -> a badge with the node's name and its trust word, coloured."""
    def badge(m: re.Match) -> str:
        label = _label(tools, m.group(1)).replace("[", "(").replace("]", ")")
        trust = m.group(2)
        color = TRUST_COLOR.get(trust or "", "gray")
        return f":{color}-badge[{label}{' · ' + trust if trust else ''}]"
    return CITE.sub(badge, text)


def _meta(turn: dict) -> str:
    bits = [model_label(turn["model"])] if turn.get("model") else []
    if turn.get("steps"):
        bits.append(f"{len(turn['steps'])} tool call{'s' if len(turn['steps']) != 1 else ''}")
    if turn.get("cost") is not None:
        bits.append(f"${turn['cost']:.4f}")
    if turn.get("seconds"):
        bits.append(f"{turn['seconds']:.1f} s")
    return " · ".join(bits)


def _steps(turn: dict) -> None:
    if not turn.get("steps"):
        return
    with st.expander(f"{len(turn['steps'])} steps", icon=":material/route:"):
        for s in turn["steps"]:
            args = ", ".join(f"{k}={v!r}" for k, v in s["input"].items() if v not in ("", None))
            mark = ":red[✕]" if s.get("error") else ":green[✓]"
            st.markdown(f"{mark} **{TOOL_LABEL.get(s['name'], s['name'])}** `{args}` → {s['summary']}")


def _show(turn: dict, tools: GraphTools | None) -> None:
    with st.chat_message(turn["role"], avatar=":material/person:" if turn["role"] == "user" else ":material/hub:"):
        if turn["role"] == "user":
            st.markdown(turn["text"])
            if turn.get("context"):
                st.caption("About: " + " › ".join(turn["context"]))
            return
        _steps(turn)
        if turn.get("text"):
            st.markdown(render_citations(turn["text"], tools))
        if turn.get("error"):
            st.error(turn["error"], icon=":material/error:")
        if meta := _meta(turn):
            st.caption(meta)


def show_packet(store, chips: list[Chip], state) -> None:
    """Fill 'What the agent sees' with the packet for the chips as they are now (after the page ran)."""
    slot = st.session_state.pop("_dock_sees", None)
    if slot is None:
        return
    project = next((c.id for c in chips if c.kind == "project"), None)
    packet = context_packet(chips, state, graph_tools(store, project), project_summary(store, project))
    with slot.container():
        st.code(json.dumps(packet, indent=1, ensure_ascii=False), language="json", wrap_lines=True)
        if err := st.session_state.get("_knowledge_error"):
            st.warning(err)


# The model picker under the input. "auto" lets the job route: Sonnet 5.5 at low effort where it is enabled, else
# Gemini 4 Argon; Opus 5.5 to think it through. A pick "<model>" or "<model>:<effort>" pins that model for the turn.
PICKS = ["auto", "argon", "argon:high", "hydrogen", "sonnet", "opus", "haiku"]
PICK_NOTE = {"argon": "fast", "argon:high": "thorough", "hydrogen": "cheaper, uneven speed"}


def _short(key: str) -> str:
    return MODELS[key].label.split(" (")[0].replace("Claude ", "").replace("Gemini 4 ", "")


def pick_label(pick: str) -> str:
    r = default_router()
    if pick == "auto":
        return f"Auto · {_short(pick_model(r, 'agent_chat'))}" if r.ready else "Auto"
    key, _, effort = pick.partition(":")
    note = PICK_NOTE.get(pick, "")
    off = " · not enabled" if key in r.not_enabled else ""
    return f"{_short(key)}{' · ' + note if note else ''}{off}"


def picked() -> tuple[str | None, str | None]:
    """(model, effort) for Agent.run: (None, None) on auto."""
    pick = st.session_state.get("dock_model", "auto")
    if pick == "auto" or pick not in PICKS:
        return None, None
    key, _, effort = pick.partition(":")
    return key, effort or None


def _clear() -> None:
    st.session_state["agent_log"] = []
    st.session_state["agent_api"] = []


def conversation(store, chips: list[Chip], state) -> None:
    log = st.session_state.setdefault("agent_log", [])
    project = next((c.id for c in chips if c.kind == "project"), None)
    tools = graph_tools(store, project)
    focus = next((c for c in reversed(chips) if c.kind != "project"), None)
    with st.container(key="dock_conv"):
        if not log:
            st.caption("Ask about what is on the screen. The agent reads the knowledge graph, cites every fact with "
                       "how far to trust it, and never changes anything." if default_router().ready else
                       f"Model calls are off: {default_router().why_not_ready()}")
        for turn in log:
            _show(turn, tools)
        live = st.container()
    st.session_state["_dock_sees"] = st.expander("What the agent sees", icon=":material/visibility:").empty()
    with st.container(key="dock_compose", gap=None):
        question = st.chat_input(f"Ask about {focus.label}…" if focus else "Ask about this building…",
                                 key="dock_input")
        with st.container(key="dock_pills", horizontal=True, vertical_alignment="center", gap="small"):
            st.selectbox("Model", PICKS, key="dock_model", format_func=pick_label, label_visibility="collapsed",
                         width=240, help="Which model answers. Auto: Sonnet 5.5 where this GCP project has it, else "
                         "Gemini 4 Argon, both thinking briefly; a question that asks to think it through goes to the "
                         "reasoning model. Thorough thinks longer and answers later.")
            st.space("stretch")
            if log:
                st.button("", icon=":material/delete_sweep:", key="dock_clear", type="tertiary", on_click=_clear,
                          help="Start a new conversation")
    if question:
        _answer(question, chips, state, tools, project, store, live)


def _answer(question: str, chips: list[Chip], state, tools, project, store, live) -> None:
    log, api = st.session_state["agent_log"], st.session_state.setdefault("agent_api", [])
    packet = context_packet(chips, state, tools, project_summary(store, project))
    user_turn = {"role": "user", "text": question, "context": [c.label for c in chips]}
    log.append(user_turn)
    with live:
        _show(user_turn, tools)
        with st.chat_message("assistant", avatar=":material/hub:"):
            status = st.status("Thinking…", expanded=False)
            out = st.empty()
            buf: list[str] = []
            steps: list[str] = []

            def on(ev: Event) -> None:
                if ev.type == "text":
                    buf.append(ev.data)
                    out.markdown(render_citations("".join(buf), tools) + " ▌")
                elif ev.type == "tool":
                    args = ", ".join(f"{k}={v!r}" for k, v in ev.data["input"].items() if v not in ("", None))
                    steps.append(f"**{TOOL_LABEL.get(ev.data['name'], ev.data['name'])}** `{args}`")
                    status.update(label=f"{TOOL_LABEL.get(ev.data['name'], ev.data['name'])}…", state="running")
                    status.markdown(steps[-1])
                    buf.append("\n\n")
                elif ev.type == "model":
                    status.update(label=f"{model_label(ev.data['model'])} is working…")

            agent = Agent(default_router(), tools=tools, knowledge=knowledge(), project=project,
                          person=st.session_state.get("author") or None, store=store)
            model, effort = picked()
            res = agent.run(api, question, packet, emit=on, model=model, effort=effort)
            status.update(label=f"{len(res.steps)} steps" if res.steps else "Answered", state="error" if res.error
                          else "complete", expanded=False)
    log.append({"role": "assistant", "text": res.text, "steps": res.steps, "model": res.model, "cost": res.cost_usd,
                "seconds": res.seconds, "error": res.error, "cited": res.cited})
    st.rerun()  # redraw the conversation from the log, with the steps folded and the badges final
