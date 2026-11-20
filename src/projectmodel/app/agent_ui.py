"""The conversation in the agent dock: history, the streaming answer with its tool steps, citations as trust badges,
cost per answer, and what the agent sees (the context packet)."""

from __future__ import annotations

import html
import json
import re
import uuid
from pathlib import Path

import streamlit as st

from projectmodel.agent.chat import Agent, Event, model_label, pick_model
from projectmodel.agent.context import Chip, context_packet
from projectmodel.agent_tools import GraphTools
from projectmodel.ai.calls import default_router
from projectmodel.ai.models import LIVE, MODELS
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

def label_of(key: str) -> str:
    return LIVE.label if key == LIVE.key else model_label(key)


def _short(key: str) -> str:
    return label_of(key).split(" (")[0].replace("Claude ", "").replace("Gemini 4 ", "").replace("Gemini ", "")


def answering_model() -> str | None:
    """The model that answers the next typed question: the picked one, else the job's routing."""
    r = default_router()
    return (picked()[0] or pick_model(r, "agent_chat")) if r.ready else None


def status_line() -> tuple[str, str, bool]:
    """(line under the dock's title, its tooltip, ready)."""
    r = default_router()
    if not r.ready:
        return "Models off", r.why_not_ready(), False
    key = answering_model()
    off = "".join(f" {label_of(k)} is not enabled in this project, so {label_of(key)} answers."
                  for k in r.not_enabled if k == "sonnet" and key != "sonnet")
    return (f"{_short(key)} · Vertex AI", f"GCP project {r.config.project}, region {r.config.region}.{off} Every call "
            "is logged with its cost.", True)


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
    bits = ([":material/mic: voice"] if turn.get("voice") else []) + (
        [label_of(turn["model"])] if turn.get("model") else [])
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
            st.markdown((":material/mic: " if turn.get("voice") else "") + (turn["text"] or "*(not understood)*"))
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


# Routing and model, the two pills under the input. Route: how hard the agent thinks (auto: by the question, briefly,
# or the reasoning model when asked to think it through). Model: auto lets the job pick (Sonnet 5.5 where it is
# enabled, else Gemini 4 Argon); a model picked here answers the whole turn.
ROUTES = {"auto": ("Auto-route", "auto_awesome", "By the question: brief, or deep when you ask to think it through"),
          "quick": ("Quick", "bolt", "Thinks briefly: answers sooner"),
          "thorough": ("Thorough", "psychology", "Thinks longer: slower, for root causes")}
ROUTE_EFFORT = {"auto": None, "quick": "low", "thorough": "high"}
PICKS = ["auto", "argon", "hydrogen", "sonnet", "opus", "haiku"]
PICK_NOTE = {"auto": "Sonnet 5.5 where enabled, else Gemini 4 Argon", "argon": "Steady: 4 to 9 s a step",
             "hydrogen": "Cheaper; speed varies a lot", "sonnet": "Best balance, where enabled",
             "opus": "Deepest reasoning, where enabled", "haiku": "Fastest and cheapest, where enabled"}


def picked() -> tuple[str | None, str | None]:
    """(model, effort) for Agent.run: None lets the job decide."""
    pick = st.session_state.get("dock_model", "auto")
    route = st.session_state.get("dock_route", "auto")
    return (None if pick == "auto" or pick not in PICKS else pick), ROUTE_EFFORT.get(route)


def _pick_caption(key: str) -> str:
    off = " · not enabled in this project" if key in default_router().not_enabled else ""
    return PICK_NOTE.get(key, "") + off


def pills() -> None:
    route = st.session_state.setdefault("dock_route", "auto")
    pick = st.session_state.setdefault("dock_model", "auto")
    name, icon, _ = ROUTES.get(route, ROUTES["auto"])
    with st.container(key="dpill_route", width="content"), st.popover(name, icon=f":material/{icon}:",
                                                                        help="How hard the agent thinks"):
        st.radio("Routing", list(ROUTES), key="dock_route", format_func=lambda k: ROUTES[k][0],
                 captions=[ROUTES[k][2] for k in ROUTES], label_visibility="collapsed")
    auto = answering_model() if pick == "auto" else None
    label = f"Auto · {_short(auto)}" if auto else ("Auto" if pick == "auto" else _short(pick))
    with st.container(key="dpill_model", width="content"), st.popover(label, icon=":material/memory:",
                                                                        help="Which model answers"):
        st.radio("Model", PICKS, key="dock_model", format_func=lambda k: "Auto" if k == "auto" else _short(k),
                 captions=[_pick_caption(k) for k in PICKS], label_visibility="collapsed")


# conversations: one at a time in the dock, all of them in the history ---------------------------------------------

def _chat_id() -> str:
    return st.session_state.setdefault("agent_chat_id", uuid.uuid4().hex[:12])


def new_chat() -> None:
    st.session_state.update(agent_log=[], agent_api=[], agent_chat_id=uuid.uuid4().hex[:12])


def open_chat(store, chat_id: str) -> None:
    if c := store.chat(chat_id):
        st.session_state.update(agent_log=c["log"], agent_api=c["api"], agent_chat_id=chat_id)


def delete_chat(store, chat_id: str) -> None:
    store.delete_chat(chat_id)
    if chat_id == st.session_state.get("agent_chat_id"):
        new_chat()


def _save(store, project: str | None) -> None:
    log = st.session_state.get("agent_log", [])
    first = next((t["text"] for t in log if t["role"] == "user" and t.get("text")), "Conversation")
    store.save_chat(_chat_id(), first[:90], log, st.session_state.get("agent_api", []), project or "",
                    st.session_state.get("author") or "")


def history(store) -> None:
    """The history popover: earlier conversations, newest first; a click opens one."""
    chats = store.chats(25)
    st.markdown("**Conversations**")
    if not chats:
        st.caption("None yet. Every conversation is kept here, on this app's database, for everyone who uses it.")
    current = st.session_state.get("agent_chat_id")
    for c in chats:
        with st.container(key=f"dhist_{c['id']}", horizontal=True, vertical_alignment="center", gap="small"):
            when = c["updated_at"][5:16].replace("-", "/")
            where = c["project"].split("/")[0].title() if c["project"] else "no project"
            st.button(f"{c['title']}", key=f"dhopen_{c['id']}", type="tertiary", on_click=open_chat,
                      args=(store, c["id"]), icon=":material/chat:" if c["id"] != current else ":material/forum:",
                      help=f"{where} · {when} · {c['n'] // 2} questions" + (f" · {c['person']}" if c["person"] else ""),
                      width="stretch")
            st.button("", key=f"dhdel_{c['id']}", type="tertiary", icon=":material/delete:", on_click=delete_chat,
                      args=(store, c["id"]), help="Delete this conversation")


def header(store) -> None:
    """The dock's top: who it is and which model answers, then new chat, history, width and hide."""
    line, tip, ready = status_line()
    with st.container(key="dock_head", horizontal=True, vertical_alignment="center", gap="small"):
        st.html(f'<div class="dock-avatar{" on" if ready else ""}" title="{html.escape(tip)}">'
                '<span class="ms">auto_awesome</span><i></i></div>'
                f'<div class="dock-titles" title="{html.escape(tip)}"><p class="dock-title">Agent</p>'
                f'<p class="dock-sub">{html.escape(line)}</p></div>', width="content")
        st.space("stretch")
        st.button("", icon=":material/edit_square:", key="dock_new", type="tertiary", on_click=new_chat,
                  help="New conversation")
        with st.container(key="dock_hist", width="content"), st.popover("", icon=":material/history:",
                                                                         help="Earlier conversations"):
            history(store)
        wide = st.session_state.get("dock_wide", False)
        st.button("", icon=":material/close_fullscreen:" if wide else ":material/open_in_full:", key="dock_wide_btn",
                  type="tertiary", on_click=lambda: st.session_state.update(dock_wide=not wide),
                  help="Narrower" if wide else "Wider")
        st.button("", icon=":material/close:", key="dock_hide", type="tertiary",
                  on_click=lambda: st.session_state.update(dock_open=False), help="Hide the agent (bring it back "
                  "with the Agent button at the bottom right, or from the top bar)")


def suggestions(chips: list[Chip]) -> list[tuple[str, str, str]]:
    """(icon, title, question): what to ask about what is on the screen."""
    focus = next((c for c in reversed(chips) if c.kind not in ("project", "page")), None)
    project = next((c for c in chips if c.kind == "project"), None)
    if focus and focus.kind == "equipment":
        return [("account_tree", f"What feeds {focus.label}?", f"What feeds {focus.label}, all the way to the plant?"),
                ("checklist", f"Is {focus.label} complete?", f"Which points is {focus.label} missing, and how sure is "
                                                             "the graph about the ones it has?"),
                ("sync_alt", f"How is {focus.label} controlled?", f"What do the sequences say about {focus.label}?")]
    if focus and focus.kind == "point":
        return [("sensors", f"What is {focus.label}?", f"What is {focus.label}, and how sure is the graph about it?"),
                ("account_tree", "Where does it sit?", f"Which equipment does {focus.label} belong to, and what "
                                                       "feeds that equipment?")]
    if project:
        return [("thermostat", "Why would a zone run warm?", "Why is zone 2-14 warm? Walk the chain from the zone to "
                                                              "the plant."),
                ("help", "What is least certain?", "Which equipment in this project is the graph least sure about, "
                                                   "and why?"),
                ("hub", "How is the plant built?", "What are the main air handlers and plants, and what does each "
                                                   "feed?")]
    return [("lightbulb", "What can you do?", "What can you help me with, and where do your answers come from?")]


def _ask(question: str) -> None:
    st.session_state["dock_ask"] = question


def welcome(chips: list[Chip], cards: bool = True) -> None:
    ready = default_router().ready
    st.html('<div class="dock-welcome"><p>Ask about this building</p><span>The agent reads the knowledge graph, cites '
            'every fact with how far to trust it, and never changes anything. Type, or hold the microphone and '
            'speak.</span></div>' if ready else
            f'<div class="dock-welcome"><p>Models are off</p><span>{html.escape(default_router().why_not_ready())}'
            '</span></div>')
    for i, (icon, title, q) in enumerate(suggestions(chips) if cards else []):
        st.button(title, key=f"dsug_{i}", icon=f":material/{icon}:", on_click=_ask, args=(q,), width="stretch",
                  disabled=not ready, help=q)


def fill_welcome(chips: list[Chip]) -> None:
    if (slot := st.session_state.pop("_dock_welcome", None)) is not None:
        with slot.container():
            welcome(chips)


def _recent(log: list[dict]) -> list[tuple[str, str]]:
    pairs, q = [], None
    for t in log:
        if t["role"] == "user":
            q = t.get("text") or ""
        elif q is not None:
            pairs.append((q, re.sub(r"\[\[[^\]]+\]\]\s*(\*\w+\*)?", "", t.get("text") or "")))
            q = None
    return pairs


def conversation(store, chips: list[Chip], state) -> None:
    log = st.session_state.setdefault("agent_log", [])
    project = next((c.id for c in chips if c.kind == "project"), None)
    tools = graph_tools(store, project)
    focus = next((c for c in reversed(chips) if c.kind not in ("project", "page")), None)
    with st.container(key="dock_conv"):
        if not log:
            # Filled after the page ran (fill_welcome), so the suggestions match what is on screen now.
            st.session_state["_dock_welcome"] = slot = st.empty()
            with slot.container():
                welcome(chips, cards=False)
        for i, turn in enumerate(log):
            _show(turn, tools)
        if (wav := st.session_state.pop("_dock_play", None)) is not None:
            st.audio(wav, format="audio/wav", autoplay=True)
        live = st.container()
    with st.container(key="dock_compose", gap=None):
        value = st.chat_input(f"Ask about {focus.label}…" if focus else "Ask me about this building…",
                              key="dock_input", accept_audio=True, audio_sample_rate=16000)
        with st.container(key="dock_pills", horizontal=True, vertical_alignment="center", gap="small"):
            pills()
    question = st.session_state.pop("dock_ask", None)
    audio = None
    if value is not None and not isinstance(value, str):
        question, audio = (value.text or "").strip() or question, value.audio
    elif value:
        question = value
    if audio is not None:
        _voice(audio, chips, state, tools, project, store, live)
    elif question:
        _answer(question, chips, state, tools, project, store, live)


def _agent(tools, project, store) -> Agent:
    return Agent(default_router(), tools=tools, knowledge=knowledge(), project=project,
                 person=st.session_state.get("author") or None, store=store)


def _voice(audio, chips: list[Chip], state, tools, project, store, live) -> None:
    """A spoken question: Gemini Live hears it, runs the tools and answers aloud; the transcripts join the log."""
    from projectmodel.agent.voice import bytes_of, voice_turn
    log, api = st.session_state["agent_log"], st.session_state.setdefault("agent_api", [])
    packet = context_packet(chips, state, tools, project_summary(store, project))
    with live, st.chat_message("assistant", avatar=":material/hub:"):
        with st.status("Gemini Live is listening and answering…", expanded=False):
            res = voice_turn(_agent(tools, project, store), bytes_of(audio), packet, recent=_recent(log))
    log.append({"role": "user", "text": res.heard, "voice": True, "context": [c.label for c in chips]})
    log.append({"role": "assistant", "text": res.text, "steps": res.steps, "model": res.model, "cost": res.cost_usd,
                "seconds": res.seconds, "error": res.error, "voice": True})
    if res.heard and res.text:  # so a typed follow-up knows what was said
        api += [{"role": "user", "content": f"(spoken) {res.heard}"},
                {"role": "assistant", "content": [{"type": "text", "text": res.text}]}]
    if res.wav:
        st.session_state["_dock_play"] = res.wav
    _save(store, project)
    st.rerun()


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
                    status.update(label=f"{label_of(ev.data['model'])} is working…")

            model, effort = picked()
            res = _agent(tools, project, store).run(api, question, packet, emit=on, model=model, effort=effort)
            status.update(label=f"{len(res.steps)} steps" if res.steps else "Answered", state="error" if res.error
                          else "complete", expanded=False)
    log.append({"role": "assistant", "text": res.text, "steps": res.steps, "model": res.model, "cost": res.cost_usd,
                "seconds": res.seconds, "error": res.error, "cited": res.cited})
    _save(store, project)
    st.rerun()  # redraw the conversation from the log, with the steps folded and the badges final
