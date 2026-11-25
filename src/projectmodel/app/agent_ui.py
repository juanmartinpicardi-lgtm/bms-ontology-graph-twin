"""The conversation in the agent dock: history, the streaming answer with its tool steps, citations as trust badges,
cost per answer, and what the agent sees (the context packet).

Under each answer, its citations open: a document page (src:, seq:, issue:, a node's own source) as a crop of the page
with the box drawn; a node, a relation or a check with its trust and a link to its graphic or the tree; a graphic as a
link to its page. A cited id no tool returned is shown struck through (TurnResult.bad_cites)."""

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
from projectmodel.app.shell import DB, get_store, knowledge_model
from projectmodel.memory import KNOWLEDGE_DIR, KnowledgeError, load_knowledge
from projectmodel.projects import site_of, summaries

TRUST_COLOR = {"verified": "green", "agreed": "green", "stated": "violet", "accepted": "blue", "likely": "blue",
               "unsure": "orange"}
CITE = re.compile(r"\[\[([^\]]+)\]\](?:\s*\*(verified|agreed|stated|accepted|likely|unsure)\*)?")
KIND_ICON = {"page": "description", "sequence": "sync_alt", "section": "sync_alt", "issue": "report", "check": "rule",
             "graphic": "view_in_ar", "relation": "share", "equipment": "hvac", "point": "sensors",
             "controller": "memory", "location": "meeting_room", "network": "lan"}
# Each tool step in plain words, while it runs and once done: what the agent is looking at, not how it calls it.
STEP_WORDS = {"find_nodes": ("Searching the graph", "Searched the graph"), "describe": ("Reading", "Read"),
              "upstream": ("Following what feeds", "Followed what feeds"),
              "downstream": ("Following what is fed by", "Followed what is fed by"),
              "behaviour": ("Reading the sequences for", "Read the sequences for"),
              "read_sequence": ("Reading the sequence for", "Read the sequence for"),
              "source_page": ("Opening the source page of", "Opened the source page of"),
              "run_check": ("Running the checks on", "Ran the checks on"),
              "show_graphic": ("Opening the graphic of", "Opened the graphic of"),
              "diagnose": ("Checking the design of", "Checked the design of"),
              "skill_view": ("Reading the skill", "Read the skill")}


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

def router():
    """The app's router, told which models this GCP project could not call lately (the call log), so a fresh process
    neither offers them nor tries them first."""
    r = default_router()
    if r.ready and not r.learnt:
        try:
            r.learn(get_store())
        except Exception:  # an old database without the log's columns: learn from the calls instead
            r.learnt = True
    return r


def label_of(key: str) -> str:
    """The model's name as people read it: the catalogue's notes in brackets ("price unconfirmed") are for the cost
    log, not for the conversation."""
    return (LIVE.label if key == LIVE.key else model_label(key)).split(" (")[0]


def _short(key: str) -> str:
    return label_of(key).split(" (")[0].replace("Claude ", "").replace("Gemini 4 ", "").replace("Gemini ", "")


def answering_model() -> str | None:
    """The model that answers the next typed question: the picked one, else the job's routing."""
    r = router()
    return (picked()[0] or pick_model(r, "agent_chat")) if r.ready else None


def status_line() -> tuple[str, str, bool]:
    """(line under the dock's title, its tooltip, ready)."""
    r = router()
    if not r.ready:
        return "Models off", r.why_not_ready(), False
    key = answering_model()
    off = (f" Not enabled in this project: {', '.join(label_of(k) for k in r.not_enabled)}."
           if r.not_enabled else "")
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
    if ref.startswith("src:"):
        file, _, where = ref[4:].rpartition("#")
        return f"{file} {'p.' + where[1:] if where.startswith('p') else 'row ' + where[1:]}"
    if ref.startswith("seq:"):
        sid, _, sec = ref[4:].partition("/")
        return f"{sid.replace('-', ' ')}" + (f" §{sec}" if sec else "")
    if ref.startswith("check:"):
        kind, _, node = ref[6:].partition("|")
        return f"{kind.replace('.', ' ')} · {_label(tools, node)}"
    if ref.startswith("rel:"):
        a, rel, b = (ref[4:].split("|") + ["", ""])[:3]
        return f"{_label(tools, a)} {rel} {_label(tools, b)}"
    if ref.startswith("graphic:"):
        return f"graphic · {_label(tools, ref[8:])}"
    if ref.startswith("issue:"):
        return "gap or conflict" if "ai-" in ref else "reader's check"
    if tools is not None and ref in tools.rows:
        return tools.rows[ref]["label"]
    return ref.split(":", 1)[-1].split(" ")[-1]


def render_citations(text: str, tools: GraphTools | None) -> str:
    """[[id]] *trust* -> a badge with the node's name and its trust word, coloured."""
    def badge(m: re.Match) -> str:
        label = _label(tools, m.group(1)).replace("[", "(").replace("]", ")")
        trust = m.group(2)
        color = TRUST_COLOR.get(trust or "", "gray")
        return f":{color}-badge[{label}{' · ' + trust if trust else ''}]"
    return CITE.sub(badge, text)


@st.cache_data(show_spinner=False, max_entries=64)
def _crop(project: str, file: str, page: int, boxes: tuple, stamp: float) -> bytes | None:
    from projectmodel.agent.documents import DocumentIndex
    docs = DocumentIndex.for_project(project)
    box = None
    if boxes:
        box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
        if (box[2] - box[0]) * (box[3] - box[1]) > 1_500_000:  # boxes far apart: the first one
            box = list(boxes[0])
    try:
        return docs.crop_png(file, page, box)
    except Exception:  # noqa: BLE001 - a page the file does not have
        return None


def _page_of(tools: GraphTools, cite: str) -> dict | None:
    """The page (file, page, boxes) a citation shows, asking the tools for it when the turn did not."""
    try:
        if cite.startswith("src:"):
            info = tools.resolve(cite) or {}
        elif cite.startswith(("seq:", "issue:", "rel:")) or cite in tools.rows:
            src = tools.source_page(cite)
            info = dict(tools.issued.get(src.get("cite") or "", {}), boxes=[src["bbox"]] if src.get("bbox") else [])
        else:
            return None
    except (KeyError, ValueError):
        return None
    if not info.get("file") or not info.get("page"):
        return None
    return {"file": info["file"], "page": int(info["page"]), "sheet": info.get("sheet"),
            "boxes": tuple(tuple(b) for b in info.get("boxes") or [] if b)}


def sources(turn: dict, tools: GraphTools | None) -> None:
    """The answer's citations, each a popover: the source page with its box, or the node, check or graphic it is."""
    cited = [c for c in turn.get("cited") or [] if not c.startswith(("m-", "skill:"))]
    if not cited or tools is None:
        return
    bad = set(turn.get("bad_cites") or [])
    with st.container(key=f"dsrc_{abs(hash((turn.get('text') or '')[:200]))}", horizontal=True, gap="small"):
        for i, c in enumerate(cited[:16]):
            info = tools.resolve(c) if c not in bad else None
            kind = (info or {}).get("kind") or ("page" if c.startswith("src:") else "check")
            label = _label(tools, c)
            if c in bad or info is None:
                st.caption(f":gray[~~{label}~~] (not from a tool)")
                continue
            with st.popover(label[:40], icon=f":material/{KIND_ICON.get(kind, 'link')}:"):
                _source_card(c, info, tools)


PAGE_URLS = {"views/equipment_3d.py": "Equipment_3D", "tree_app.py": "tree"}


def _link(page: str, label: str, icon: str, query: dict) -> None:
    """A link to an app page with its query; a plain link where the page is not in this app's navigation."""
    from urllib.parse import urlencode

    from streamlit.errors import StreamlitPageNotFoundError
    try:
        st.page_link(page, label=label, icon=icon, query_params=query)
    except StreamlitPageNotFoundError:
        st.markdown(f"{icon} [{label}](/{PAGE_URLS.get(page, page)}?{urlencode(query)})")


def _source_card(cite: str, info: dict, tools: GraphTools) -> None:
    if info.get("trust"):
        st.markdown(f":{TRUST_COLOR.get(info['trust'], 'gray')}-badge[{info['trust']}] {info.get('label') or ''}")
    if text := info.get("text"):
        st.caption(str(text)[:600])
    if cite.startswith("graphic:"):
        _link("views/equipment_3d.py", "Open the graphic", ":material/view_in_ar:", info.get("query") or {})
        return
    node = cite if cite in tools.rows else None
    if node is None and cite.startswith("check:"):
        node = cite.partition("|")[2] or None
    if node and node in tools.rows:
        eq = tools._equipment_of(tools.tree.by_id[node]) if node in tools.tree.by_id else None
        if eq is not None and eq.attrs.get("template"):
            _link("views/equipment_3d.py", f"{eq.label} in Equipment 3D", ":material/view_in_ar:",
                  {"project": tools.project, "equip": eq.id})
        _link("tree_app.py", "Open the tree", ":material/account_tree:", {"project": tools.project})
    page = _page_of(tools, node or cite)
    if page:
        png = _crop(tools.project, page["file"], page["page"], page["boxes"], _db_stamp())
        where = " · ".join(x for x in (page["file"], page.get("sheet"), f"page {page['page']}") if x)
        if png:
            st.image(png, caption=where)
        else:
            st.caption(where + " (the file is not on this machine)")


def _meta(turn: dict) -> str:
    bits = ([":material/mic: voice"] if turn.get("voice") else []) + (
        [label_of(turn["model"])] if turn.get("model") else [])
    if turn.get("cost") is not None:  # the steps are counted on their own fold ("Thought in N steps")
        bits.append(f"${turn['cost']:.4f}")
    if turn.get("seconds"):
        bits.append(f"{turn['seconds']:.1f} s")
    return " · ".join(bits)


def step_text(name: str, args: dict, tools: GraphTools | None, done: bool = False) -> str:
    """One thinking step in plain words: "Reading AHU-2", "Searching the graph for “zone 2-14”"."""
    verb = STEP_WORDS.get(name, (name.replace("_", " ").capitalize(),) * 2)[1 if done else 0]
    args = args or {}
    if node := args.get("node_id"):
        return f"{verb} {_label(tools, str(node))}"
    if what := args.get("query") or args.get("cls") or args.get("name"):
        return f"{verb} for “{what}”" if name == "find_nodes" else f"{verb} {what}"
    return verb


def _steps(turn: dict, tools: GraphTools | None = None) -> None:
    if not turn.get("steps"):
        return
    n = len(turn["steps"])
    with st.expander(f"Thought in {n} step{'s' if n != 1 else ''}", icon=":material/neurology:"):
        for s in turn["steps"]:
            mark = ":red[✕]" if s.get("error") else ":green[✓]"
            st.markdown(f"{mark} {step_text(s['name'], s['input'], tools, done=True)}"
                        + (f" · :gray[{s['summary']}]" if s.get("summary") else ""))


def _show(turn: dict, tools: GraphTools | None) -> None:
    with st.chat_message(turn["role"], avatar=":material/person:" if turn["role"] == "user" else ":material/hub:"):
        if turn["role"] == "user":
            st.markdown((":material/mic: " if turn.get("voice") else "") + (turn["text"] or "*(not understood)*"))
            if turn.get("context"):
                st.caption("About: " + " › ".join(turn["context"]))
            return
        _steps(turn, tools)
        if turn.get("text"):
            st.markdown(render_citations(turn["text"], tools))
            sources(turn, tools)
        if turn.get("note"):
            st.caption(f":material/swap_horiz: {turn['note']}")
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
PICK_NOTE = {"argon": "Steady: 4 to 9 s a step", "hydrogen": "Cheaper; speed varies a lot",
             "sonnet": "Best balance", "opus": "Deepest reasoning", "haiku": "Fastest and cheapest"}


def picks() -> list[str]:
    """The models offered in the picker: those this project can call (as far as the call log knows)."""
    off = router().not_enabled
    return [k for k in PICKS if k not in off]


def picked() -> tuple[str | None, str | None]:
    """(model, effort) for Agent.run: None lets the job decide."""
    pick = st.session_state.get("dock_model", "auto")
    route = st.session_state.get("dock_route", "auto")
    return (None if pick == "auto" or pick not in PICKS else pick), ROUTE_EFFORT.get(route)


def _pick_caption(key: str) -> str:
    if key == "auto":
        r = router()
        return f"Now {_short(pick_model(r, 'agent_chat'))}: the best model this project can call" if r.ready else ""
    return PICK_NOTE.get(key, "")


def pills() -> None:
    route = st.session_state.setdefault("dock_route", "auto")
    shown = picks()
    if st.session_state.setdefault("dock_model", "auto") not in shown:
        st.session_state["dock_model"] = "auto"  # found to be off since it was picked
    pick = st.session_state["dock_model"]
    name, icon, _ = ROUTES.get(route, ROUTES["auto"])
    with st.container(key="dpill_route", width="content"), st.popover(name, icon=f":material/{icon}:",
                                                                        help="How hard the agent thinks"):
        st.radio("Routing", list(ROUTES), key="dock_route", format_func=lambda k: ROUTES[k][0],
                 captions=[ROUTES[k][2] for k in ROUTES], label_visibility="collapsed")
    auto = answering_model() if pick == "auto" else None
    label = f"Auto · {_short(auto)}" if auto else ("Auto" if pick == "auto" else _short(pick))
    with st.container(key="dpill_model", width="content"), st.popover(label, icon=":material/memory:",
                                                                        help="Which model answers"):
        st.radio("Model", shown, key="dock_model", format_func=lambda k: "Auto" if k == "auto" else _short(k),
                 captions=[_pick_caption(k) for k in shown], label_visibility="collapsed")
        if off := [k for k in PICKS if k not in shown]:
            r = router()
            st.caption(f"Not enabled in Google Cloud project {r.config.project}: "
                       f"{', '.join(_short(k) for k in off)}. Turn them on in Vertex AI Model Garden to use them.")


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
        st.html(f'<div class="dock-id"><div class="dock-avatar{" on" if ready else ""}" title="{html.escape(tip)}">'
                '<b class="wave"></b><b class="wave"></b><span class="ms" aria-hidden="true">auto_awesome</span>'
                '<i></i></div>'
                f'<div class="dock-titles" title="{html.escape(tip)}"><p class="dock-title">Agent</p>'
                f'<p class="dock-sub">{html.escape(line)}</p></div></div>', width="content")
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
                  on_click=lambda: st.session_state.update(dock_open=False), help="Hide the agent (bring it back with the round "
                  "button at the bottom right, or from the top bar)")


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
    ready = router().ready
    st.html('<div class="dock-welcome"><p>Ask about this building</p><span>The agent reads the knowledge graph, cites '
            'every fact with how far to trust it, and never changes anything. Type, or hold the microphone and '
            'speak.</span></div>' if ready else
            f'<div class="dock-welcome"><p>Models are off</p><span>{html.escape(router().why_not_ready())}'
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
    return Agent(router(), tools=tools, knowledge=knowledge(), project=project,
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
    # While it thinks: the steps it takes, in plain words, one line each, open; nothing about models or prices. The
    # dock_busy key lets the agent's avatar show it is working (dock CSS).
    with live, st.container(key="dock_busy"):
        _show(user_turn, tools)
        with st.chat_message("assistant", avatar=":material/hub:"):
            status = st.status("Thinking…", expanded=True)
            out = st.empty()
            buf: list[str] = []
            n_steps = [0]

            def on(ev: Event) -> None:
                if ev.type == "reset":  # the citation check asked for a rewrite: the new answer replaces this one
                    buf.clear()
                    status.update(label="Checking the citations…", state="running")
                    out.markdown("")
                elif ev.type == "text":
                    if not buf:
                        status.update(label="Writing the answer…", expanded=bool(n_steps[0]))
                    buf.append(ev.data)
                    out.markdown(render_citations("".join(buf), tools) + " ▌")
                elif ev.type == "tool":
                    n_steps[0] += 1
                    line = step_text(ev.data["name"], ev.data.get("input") or {}, tools)
                    status.update(label=f"{line}…", state="running", expanded=True)
                    status.markdown(f":gray[{n_steps[0]}.] {line}")
                    if buf:
                        buf.append("\n\n")

            model, effort = picked()
            res = _agent(tools, project, store).run(api, question, packet, emit=on, model=model, effort=effort)
            n = len(res.steps)
            status.update(label=f"Thought in {n} step{'s' if n != 1 else ''}" if n else "Answered",
                          state="error" if res.error else "complete", expanded=False)
    log.append({"role": "assistant", "text": res.text, "steps": res.steps, "model": res.model, "cost": res.cost_usd,
                "seconds": res.seconds, "error": res.error, "cited": res.cited, "note": res.note,
                "bad_cites": res.bad_cites})
    _save(store, project)
    st.rerun()  # redraw the conversation from the log, with the steps folded and the badges final
