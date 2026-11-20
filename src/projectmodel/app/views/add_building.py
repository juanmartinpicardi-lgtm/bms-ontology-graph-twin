"""Add a building: a guided setup, one step at a time. Locate the building, upload its documents, review, then add
what people know about it (tribal knowledge). The knowledge graph and the building (its twin) are built along the
way.

Every step has the same layout, like the Location page of a project: one header line with the steps, then the step on
the left (about 40% of the width) and what has been built so far on the right (about 60%): the site, the building in
3D or 2D, the knowledge graph, the sequences linked to it, and the review. Both boxes run to the bottom of the screen.

On the left, a document step starts as a drop zone with the step's example file next to it. The document is read in
the same box, page by page, and then shown there with every fact it read outlined, with the same controls as the
viewers on the right (zoom, fit, full screen, pages). A click on a unit, a room or a graph node opens its place in the
document. What the reader is not sure about is asked, in a list or on the building itself. Answers are kept
(method = human) and survive a re-read.

The readers are rules (src/projectmodel/intake), no LLM. The example package in test_packages/troop_d/ has one file
per step.
"""

import base64
import io
import json
import sys
import time
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.bridge import frame  # noqa: E402
from projectmodel.app.shell import THEME, box, get_store, knowledge_model, secret, set_project, site_map, theme  # noqa: E402
from projectmodel.fonts import with_fonts  # noqa: E402
from projectmodel.intake.publish import delete_project, project_id, publish  # noqa: E402
from projectmodel.locate import LocateError, get_geocoder, location_dict  # noqa: E402
from projectmodel import notes as project_notes  # noqa: E402
from projectmodel.intake import graph, knowledge, pdfdoc, score, sequence_links, steps, submittal, twin, vectors  # noqa: E402
from projectmodel.viz import render_html  # noqa: E402
from projectmodel.intake.model import building, missing, progress  # noqa: E402
from projectmodel.intake.state import Intake, list_intakes  # noqa: E402
from projectmodel.intake.steps import STEPS, TEST_PACKAGE  # noqa: E402

APP = Path(__file__).resolve().parents[1]
# Semantic colours, mid-tones that read on both the white page image and the dark app
STATUS_COLOR = {"confirmed": "#4CBF45", "proposed": "#1792E5", "ask": "#F2B134", "rejected": "#FF644C"}
KIND_NAME = {"floor": "Floors", "room": "Rooms", "placement": "Where units are", "equipment": "Equipment",
             "relation": "Connections", "sequence": "Sequences", "issue": "Checks", "controller": "Controllers",
             "point": "Points", "room_check": "Room schedule check", "alias": "BMS devices", "bms_object": "BMS objects"}
PER_PAGE = 6
C = THEME[theme()]

st.html(f"""<style>
/* One header line: the steps as a stepper, what is missing, and a small manage menu at the right */
.st-key-ab_head {{ margin: -2px 0 2px; row-gap: 6px; }}
.st-key-ab_steps {{ gap: 3px !important; flex-wrap: wrap; }}
.st-key-ab_head [data-testid^="stBaseButton-"], .st-key-ab_head [data-testid="stPopoverButton"] {{
  min-height: 34px; padding: 0 10px; border-radius: 6px; }}
.st-key-ab_head [data-testid="stIconMaterial"] {{ font-size: 17px; margin-right: -2px; }}
.st-key-ab_head [data-testid^="stBaseButton-"] p, .st-key-ab_head [data-testid="stPopoverButton"] p {{
  font-size: 13px; letter-spacing: .1px; }}
.st-key-ab_steps [data-testid="stBaseButton-secondary"] {{ border-color: {C["line"]}; }}
.st-key-ab_steps [data-testid="stBaseButton-secondary"] * {{ color: {C["text2"]}; }}
.st-key-ab_steps [data-testid="stBaseButton-secondary"]:hover {{ border-color: {C["accent"]}; }}
.st-key-ab_steps [data-testid="stBaseButton-secondary"]:hover * {{ color: {C["accent"]}; }}
[class*="st-key-ab_go_done"] [data-testid="stIconMaterial"] {{ color: {C["good"]} !important; }}
[class*="st-key-ab_go_open"] [data-testid="stIconMaterial"] {{ color: {C["warn"]} !important; }}
.st-key-ab_manage [data-testid="stPopoverButton"] {{ border-color: transparent; padding: 0 8px; }}
.st-key-ab_files [data-testid="stPopoverButton"] {{ min-height: 34px; padding: 0 10px; }}
.st-key-ab_manage [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {{ font-size: 20px; }}
.ab-prog {{ display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: {C["text2"]};
  white-space: nowrap; }}
.ab-prog .bar {{ width: 48px; height: 6px; border-radius: 3px; background: {C["line"]}; overflow: hidden; }}
.ab-prog .bar i {{ display: block; height: 100%; background: {C["good"]}; border-radius: 3px; }}
/* The two boxes: tighter padding, so the viewers get the room */
[class*="st-key-box_fit_work"], [class*="st-key-box_fit_out"] {{ padding: 12px 16px !important; }}
.st-key-box_out {{ padding: 12px 16px !important; }}
.block-container {{ padding-bottom: .6rem !important; }}
/* The drop zone of an empty step: big, the first thing to do */
.st-key-ab_drop [data-testid="stFileUploaderDropzone"] {{ min-height: 190px; flex-direction: column;
  justify-content: center; align-items: center; gap: 14px; text-align: center; border-width: 2px;
  border-radius: 10px; }}
.st-key-ab_drop [data-testid="stFileUploaderDropzoneInstructions"] {{ margin: 0; }}
.st-key-ab_drop [data-testid="stFileUploaderDropzone"] button {{ min-height: 40px; }}
[class*="st-key-q_"] {{ border-left: 3px solid #F2B134 !important; border-radius: 10px !important; }}
.st-key-ab_reopen button {{ height: 168px; writing-mode: vertical-rl; border-radius: 4px; padding: 12px 6px; }}
.ab-why {{ margin: 2px 0 0; padding-left: 18px; font-size: 14px; }}
.ab-why li {{ margin: 3px 0; }}
.ab-why b {{ color: {C["text"]}; }}
</style>""")

# The flow: locate, the five documents, review, then what people know. Locate and knowledge are steps of this page;
# the document steps and review are the intake's (intake/steps.py).
FLOW = [("locate", 0, "Locate the building")] + [(s.id, s.n, s.title) for s in STEPS] + [
    ("knowledge", len(STEPS) + 1, "Add knowledge")]
FLOW_IDS = [f[0] for f in FLOW]
SHORT = {"locate": "Locate", "plans": "Floor plans", "schedules": "Schedules", "sequences": "Sequences",
         "submittal": "Submittal", "bms": "BMS export", "review": "Review", "knowledge": "Knowledge"}


# ---------------------------------------------------------------- building picker

def start_form(key: str) -> None:
    with st.form(key, border=False):
        st.caption("Give it a name and, if you have it, its address. Then locate it and upload its documents one step "
                   "at a time; each one adds to the knowledge graph and to the building.")
        name = st.text_input("Building name", placeholder="e.g. North Campus Science Building")
        address = st.text_input("Address or place (optional)", placeholder="Street, city",
                                help="Used to find the building on the map in the first step.")
        if st.form_submit_button("Start", type="primary", icon=":material/arrow_forward:"):
            if not name.strip():
                st.error("A name is needed.")
            else:
                begin(name.strip(), address.strip())
                st.rerun()


def begin(name: str, address: str = "") -> None:
    """A new, empty building: nothing read, nothing built. The graph, the twin and the review grow from here."""
    it = Intake.create(name, address)
    st.session_state.update(ab_started=True, ab_slug=it.slug, ab_step="locate", ab_sel=None, ab_work=None,
                            ab_view="site", ab_out="side", ab_loc_query=address or name, ab_loc_results=None)


def resume(slug: str) -> None:
    st.session_state.update(ab_started=True, ab_slug=slug, ab_step=None, ab_sel=None, ab_work=None)


existing = list_intakes()
# Pickers map a choice back by its label, so two buildings with the same name get the time they were started.
_count = {}
for _s in existing:
    _count[_s["name"]] = _count.get(_s["name"], 0) + 1
names = {s["slug"]: s["name"] + (time.strftime(" · started %d %b %H:%M:%S", time.localtime(s["created"]))
                                 if _count[s["name"]] > 1 else "") for s in existing}
# Every visit starts like a real onboarding: an empty building, nothing pre-built. A building in progress opens
# only when someone picks it (here, or Continue on All projects).
if not st.session_state.get("ab_started") or st.session_state.get("ab_slug") not in {s["slug"] for s in existing}:
    left, right = st.columns([2, 3], gap="medium")
    with left, box("own", "Start a new building", "add_business", height="stretch"):
        start_form("ab_new")
    with right, box("intro", "How it works", "route", height="stretch"):
        st.markdown("##### Eight steps, from an address to a reviewed knowledge graph")
        st.markdown("**0** Locate the building · **1** Floor plans · **2** Equipment schedules · **3** Sequences of "
                    "operation · **4** Controls submittal · **5** BMS export · **6** Review · **7** What people know")
        st.write("Each document you upload is read in front of you and turned into part of the building. The site, "
                 "the building's twin, the knowledge graph and the review start empty and grow at every step, on the "
                 "right of the page. Every step has an example file ready to use if you want to try it first.")
        if existing:
            st.divider()
            st.markdown("**Buildings in progress**")
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                pick = st.selectbox("Continue", [s["slug"] for s in existing], label_visibility="collapsed",
                                    format_func=names.get, width=320)
                st.button("Continue", icon=":material/arrow_forward:", on_click=resume, args=(pick,))
    st.stop()

slugs = [s["slug"] for s in existing]
it = Intake(st.session_state["ab_slug"])
knowledge.apply(it)  # this building's own rules are the ones in force for everything below
if st.session_state.get("ab_step") not in FLOW_IDS:
    st.session_state["ab_step"] = "locate" if not it.location else "plans"
step_id = st.session_state["ab_step"]
step = steps.BY_ID.get(step_id)
st.session_state.setdefault("ab_sel", None)
st.session_state.setdefault("ab_out", "side")  # the outputs panel: side, hidden or full


def go(to: str) -> None:
    st.session_state.update(ab_step=to, ab_sel=None, ab_qpage=0, ab_work=None)
    if to == "locate":
        st.session_state["ab_view_want"] = "site"


def select(fid: str | None) -> None:
    st.session_state["ab_sel"] = fid


def out_mode(mode: str) -> None:
    st.session_state["ab_out"] = mode


def start_over() -> None:
    delete_project(get_store(), project_id(it))
    it.reset()
    st.session_state.update(ab_step="locate" if not it.location else "plans", ab_sel=None, ab_work=None,
                            ab_view="site", ab_nonce=st.session_state.get("ab_nonce", 0) + 1)
    st.toast(f"{it.name}: started over", icon=":material/restart_alt:")


def remove_building() -> None:
    delete_project(get_store(), project_id(it))
    name = it.name
    it.delete()
    st.session_state.update(ab_started=False, ab_slug=None, ab_step=None, ab_sel=None)
    st.toast(f"{name} deleted", icon=":material/delete:")


def other_buildings() -> None:
    st.session_state.update(ab_started=False, ab_step=None, ab_sel=None)


# ---------------------------------------------------------------- header: one line, the steps

prog = progress(it)
b = building(it)
gaps = missing(it, b)
kn = knowledge.get(it)
n_known = len(kn["tags"]) + len(kn["terms"]) + len(kn["notes"])
n_missing = len(gaps) + (0 if it.location else 1)
with st.container(key="ab_head", horizontal=True, vertical_alignment="center", gap="small"):
    with st.container(key="ab_steps", horizontal=True, vertical_alignment="center", width="content"):
        for sid, n, title in FLOW:
            p = prog["steps"].get(sid)
            if sid == "locate":
                state = "done" if it.location else "todo"
            elif sid == "review":
                state = "todo"
            elif sid == "knowledge":
                state = "done" if n_known else "todo"
            elif not p["read"]:
                state = "todo"
            else:
                state = "open" if p["open"] else "done"
            icon = {"done": ":material/check_circle:", "open": ":material/pending:"}.get(state)
            extra = f" ({p['open']})" if p and p["open"] else ""
            st.button(f"{n} {SHORT[sid]}{extra}", key=f"ab_go_{state}_{sid}", icon=icon, on_click=go, args=(sid,),
                      type="primary" if sid == step_id else "secondary", help=title)
    st.space("stretch")
    share = round(prog["share"] * 100)
    st.html(f'<div class="ab-prog" title="{sum(1 for s in prog["steps"].values() if s["read"])} of 5 documents read · '
            f'{sum(s["open"] for s in prog["steps"].values())} questions open"><div class="bar"><i style="width:{share}%">'
            f'</i></div>{share}% built</div>', width="content")
    with st.popover(f"Missing · {n_missing}", icon=":material/checklist:", help="What is missing"):
        if not it.location:
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(":material/location_off: The building is not located yet")
                st.button("Go to step 0", key="gap_locate", on_click=go, args=("locate",), type="tertiary")
        if not gaps and it.location:
            st.write("Nothing: the building is located, every document is read and every question answered.")
        for sid, kind, text in gaps:
            icon = {"todo": ":material/upload_file:", "ask": ":material/help:", "gap": ":material/report:"}[kind]
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(f"{icon} {text}")
                st.button(f"Go to step {steps.BY_ID[sid].n}", key=f"gap_{sid}_{kind}_{hash(text)}", on_click=go,
                          args=(sid,), type="tertiary")
    with st.container(key="ab_manage", width="content"), st.popover("", icon=":material/settings:",
                                                                     help=f"Manage {it.name}"):
        st.markdown(f"**{it.name}**")
        st.button("Other buildings", icon=":material/apartment:", on_click=other_buildings, type="tertiary",
                  help="Start a new building, or continue another one")
        st.caption("Start over keeps the name and the location, and removes every document, answer and piece "
                   "of knowledge. Delete removes the building" + (" and its project." if it.s.get("published")
                                                                   else "."))
        sure = st.checkbox("I understand this cannot be undone", key=f"ab_sure_{it.slug}")
        st.button("Start over", icon=":material/restart_alt:", disabled=not sure, on_click=start_over,
                  key="ab_reset")
        st.button("Delete this building", icon=":material/delete:", disabled=not sure, on_click=remove_building,
                  key="del_building")


# ---------------------------------------------------------------- shared pieces

@st.cache_data(show_spinner="Drawing the floor from the PDF…", max_entries=24)
def plan_geo(path: str, page: int, crop: tuple, sha: str) -> dict:  # sha: a new upload refreshes it
    return dict(vectors.plan(Path(path), page, list(crop)), key=f"{sha[:12]}:{page}:{crop}")


@st.cache_data(show_spinner=False, max_entries=48)
def page_image(path: str, page: int, boxes: str, sha: str, width: int = 1800) -> tuple[str, int, int, float]:
    """A document page as a JPEG data URL with what was read outlined; and the scale from PDF points to its pixels."""
    img = pdfdoc.render(Path(path), page, width=width, boxes=json.loads(boxes))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80, optimize=True)
    pw, _ = pdfdoc.page_size(Path(path), page)
    return ("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), img.width, img.height,
            img.width / pw)


@st.cache_data(show_spinner=False, max_entries=12)
def thumbnail(path: str, sha: str) -> bytes:
    buf = io.BytesIO()
    pdfdoc.render(Path(path), 0, width=520).save(buf, "PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=1)
def doc_page() -> str:
    controls = (APP / "viewer_controls.js").read_text()
    return with_fonts((APP / "doc_viewer.html").read_text().replace("/*__CONTROLS__*/", controls))


@lru_cache(maxsize=1)
def sequences_page() -> str:
    return with_fonts((APP / "intake_sequences.html").read_text())


def file_sha(name: str) -> str:
    return next((f["sha256"] for fs in it.s["files"].values() for f in fs if f["name"] == name), "")


def picked(ev: dict | None) -> None:
    """What a viewer sent back. A click selects that fact, so the document opens at its place. An answer given on the
    building is checked against the question as it stands here, then saved like any other. The sequences can open
    a unit on the building or in the graph; the document viewer turns its pages."""
    if not ev:
        return
    if ev.get("name") == "page":
        key = f"ab_vpage_{ev.get('file')}"
        if st.session_state.get(key) != ev.get("page"):
            st.session_state[key] = ev["page"]
            st.rerun()
        return
    if not ev.get("id"):
        return
    if ev.get("name") == "view":
        st.session_state.update(ab_view_want=ev.get("view"), ab_sel=ev["id"])
        st.rerun()
    if ev.get("name") == "pick" and (ev["id"] != st.session_state["ab_sel"] or ev.get("doc")):
        st.session_state.update(ab_sel=ev["id"], ab_work_want="doc")  # the step's box shows the document
        st.rerun()
    if ev.get("name") == "answer":
        f = it.fact(ev["id"])
        if not f or not f.get("ask") or f["status"] != "proposed":
            return
        ask, status, value = f["ask"], ev.get("status"), ev.get("value")
        if status == "fixed" and ask.get("field") == "name" and isinstance(value, str) and value.strip():
            it.decide(f["id"], "fixed", value.strip()[:60].title(), "name")
        elif status == "fixed" and any(o["value"] == value for o in ask.get("options", [])):
            answer(f, value, ask.get("field"))
        elif status in ("confirmed", "rejected"):
            it.decide(f["id"], status)
        else:
            return
        st.toast(f"Saved: {f['label']}", icon=":material/check_circle:")
        st.rerun()


def twin_view(height: int | str = 640, only_ask: bool = False, key: str = "ab_twin", panel: bool = True) -> None:
    plans = {}
    for f in b["floors"]:
        path = it.file_by_name(f["file"])
        if path and f["crop"]:
            plans[f["id"]] = plan_geo(str(path), f["page"], tuple(f["crop"]), file_sha(f["file"]))
    needs = {f["id"]: f for f in it.open_questions()}
    data = twin.payload(b, plans, st.session_state["ab_sel"], needs, theme(), knowledge.notes_for(it))
    data["only_ask"] = only_ask
    if panel:
        selection_panel()
    picked(frame(twin.page(), data, height, key=key, title="The building"))


def graph_view(height: int | str = 720) -> None:
    g = graph.payload(it, b, knowledge_model())
    if not g["nodes"]:
        st.info("The graph is empty until the first document is read. Every document then adds to it: floors and "
                "rooms, units, their links, their points, the sequences that control them.", icon=":material/hub:")
        return
    n = g["counts"]["nodes"]
    st.caption(f"{n.get('location', 0)} floors and rooms · {n.get('equipment', 0)} units · {n.get('point', 0)} points"
               + (f" · {n['sequence']} sequences" if n.get("sequence") else "")
               + f" · {len(g['links'])} links. Click a node: its source opens in the document.")
    selection_panel()
    picked(frame(render_html(g, theme()), {"select": st.session_state["ab_sel"]}, height,
                 key="ab_graph", title="Knowledge graph"))


def sequences_view(height: int | str, key: str) -> None:
    """The sequences read so far, with every unit, group of units and point they name linked to the graph."""
    data = sequence_links.payload(b, submittal.classify)
    sel = it.fact(st.session_state["ab_sel"]) if st.session_state["ab_sel"] else None
    data.update(theme=theme(), start=sel["id"] if sel and sel["kind"] == "sequence" else
                (data["sequences"][0]["id"] if data["sequences"] else None))
    picked(frame(sequences_page(), data, height, key=key, title="Sequences"))


def selected() -> tuple[dict | None, list[dict]]:
    """The selected unit (if the selection is one of its facts) and every fact about the selection."""
    fid = st.session_state["ab_sel"]
    if not fid or not it.fact(fid):
        return None, []
    unit = next((e for e in b["equip"].values() if fid in e["facts"]), None)
    return unit, [f for f in (it.fact(i) for i in dict.fromkeys(unit["facts"] if unit else [fid])) if f]


def answer_selected(f: dict) -> None:
    """Open the selection's question in the step's box: on its own step, Needs you tab, pinned at the top."""
    to = f.get("step") if f.get("step") in FLOW_IDS else step_id
    st.session_state.update(ab_step=to, ab_work="ask", ab_qpage=0, ab_ask_how="List")


def selection_panel() -> None:
    """Above the building or the graph, one line: what is selected, the documents that mention it (a click opens the
    place), its open question (answered in the step's box), and a note about it."""
    unit, facts = selected()
    if not facts:
        return
    open_ = [f for f in facts if f["status"] == "proposed" and f.get("ask")]
    target = (f"unit:{unit['normal']}", unit["tag"]) if unit else (
        (f"room:{facts[0]['data']['number']}", f"room {facts[0]['data']['number']}") if facts[0]["kind"] == "room" else None)
    notes = knowledge.notes_for(it).get(target[0], []) if target else []
    with st.container(horizontal=True, vertical_alignment="center", gap="small", key="ab_selbar"):
        if unit:
            room = f" · {unit['rel']} room {unit['room']}" if unit["room"] else " · no room yet"
            st.markdown(f"**{unit['tag']}** · {unit['class']}{room}", width="content")
        else:
            st.markdown(f"**{facts[0]['label']}** · {KIND_NAME.get(facts[0]['kind'], facts[0]['kind'])}",
                        width="content")
        for k, f in enumerate(facts):
            st.button(where(f), key=f"src_{k}", on_click=show_fact, args=(f["id"],), type="tertiary",
                      icon=":material/description:", help=f"{KIND_NAME.get(f['kind'], f['kind'])}: open it in the document")
        if open_:
            st.button("Needs you", key="sel_answer", icon=":material/help:", on_click=answer_selected, args=(open_[0],),
                      help=open_[0]["ask"]["q"])
        if target:
            st.button(f"Notes · {len(notes)}" if notes else "Add a note", key="note_here", type="tertiary",
                      icon=":material/sticky_note_2:", help="\n\n".join(n["body"] for n in notes) or None,
                      on_click=lambda: (go("knowledge"), st.session_state.update(
                          ab_know="Note", ab_note_target=target[0], ab_work="add")))
        st.space("stretch")
        st.button("", key="clear_sel_panel", type="tertiary", on_click=select, args=(None,), icon=":material/close:",
                  help="Clear the selection")


def selected_questions() -> None:
    """At the top of Needs you: the open questions about what is selected on the building or in the graph."""
    unit, facts = selected()
    for k, f in enumerate(f for f in facts if f["status"] == "proposed" and f.get("ask")):
        if k == 0:
            st.caption(f"About **{unit['tag'] if unit else f['label']}**, selected:")
        question_card(f, f"sel{k}")


def knowledge_view() -> None:
    """Add to the knowledge model for this building (rules that change the reading), or tribal knowledge (notes)."""
    k = knowledge.get(it)
    km = knowledge_model()
    st.caption("**Rules** extend the knowledge model for this building: they change how its documents are read. "
               "**Notes** are what people know that no document says: they change nothing, and travel with the graph.")
    kinds = ["Tag rule", "Point term", "Note", "From a file"]
    if st.session_state.get("ab_know") not in kinds:
        st.session_state["ab_know"] = kinds[0]
    kind = st.segmented_control("Add", kinds, key="ab_know", label_visibility="collapsed") or kinds[0]
    try:
        if kind == "Tag rule":
            st.caption("A tag prefix the model does not know, or reads wrongly here. Example: on this job **CRAC** "
                       "is a computer-room unit.")
            with st.form("know_tag", border=True, clear_on_submit=True):
                prefix = st.text_input("Prefix", placeholder="CRAC", max_chars=6)
                cls = st.selectbox("Is a (class)", km.by_kind("equipment"), index=None, placeholder="Choose a class")
                family = st.selectbox("Drawn and scheduled like", knowledge.FAMILIES,
                                      format_func=lambda f: twin.FAMILY_NAME.get(f, f))
                terminal = st.checkbox("Serves a room (its room comes from its thermostat on the plan)")
                if st.form_submit_button("Add the rule", icon=":material/add:") and prefix and cls:
                    knowledge.add_tag(it, prefix, cls, family, terminal)
                    st.rerun()
        elif kind == "Point term":
            st.caption("A phrase or short name in a point list that settles the point's class. Example: "
                       "**DA-T** is a discharge air temperature sensor.")
            with st.form("know_term", border=True, clear_on_submit=True):
                phrase = st.text_input("Phrase or short name", placeholder="DA-T")
                cls = st.selectbox("Is a (class)", km.by_kind("point"), index=None, placeholder="Choose a class")
                if st.form_submit_button("Add the rule", icon=":material/add:") and phrase and cls:
                    knowledge.add_term(it, phrase, cls)
                    st.rerun()
        elif kind == "Note":
            targets = {"building": "the whole building"}
            targets |= {f"unit:{n}": e["tag"] for n, e in sorted(b["equip"].items())}
            targets |= {f"room:{r['number']}": f"room {r['number']} {r['name']}".strip() for r in b["rooms"]}
            if st.session_state.get("ab_note_target") not in targets:
                st.session_state["ab_note_target"] = "building"
            with st.form("know_note", border=True, clear_on_submit=True):
                target = st.selectbox("About", list(targets), format_func=targets.get, key="ab_note_target")
                c = st.columns(2)
                if st.session_state.get("ab_note_topic") not in project_notes.TOPICS:
                    st.session_state["ab_note_topic"] = project_notes.TOPICS[0]
                topic = c[0].selectbox("Topic", project_notes.TOPICS, key="ab_note_topic")
                author = c[1].text_input("Your name", key="ab_author")
                body = st.text_area(st.session_state.get("ab_note_q") or "What should people know?", height=90,
                                    placeholder="e.g. Replaced in 2022; the old return-fan points are unused.")
                if st.form_submit_button("Add the note", icon=":material/add_comment:") and body and author:
                    knowledge.add_note(it, target, targets[target], topic, body, author)
                    st.rerun()
        else:
            st.caption("A YAML file with `tags`, `terms` and `notes`, in the shape the download below gives: what "
                       "another building taught, or a list an engineer prepared.")
            up = st.file_uploader("Knowledge file", type=["yaml", "yml"], key=f"know_up_{st.session_state.get('ab_knonce', 0)}",
                                  label_visibility="collapsed")
            if up:
                classes = {"equipment": set(km.by_kind("equipment")), "point": set(km.by_kind("point"))}
                added, problems = knowledge.load(it, up.getvalue().decode("utf-8", "replace"), classes)
                st.session_state["ab_knonce"] = st.session_state.get("ab_knonce", 0) + 1
                st.session_state["ab_know_msg"] = (added, problems)
                st.rerun()
            if msg := st.session_state.pop("ab_know_msg", None):
                st.success(f"{msg[0]} added from the file.", icon=":material/check_circle:")
                for line in msg[1]:
                    st.warning(line, icon=":material/report:")
    except ValueError as e:
        st.error(str(e))

    read = [s for s in STEPS[:-1] if it.done(s.id)]
    late = [s for s in read if knowledge.rules_at(it) > it.read_at(s.id)]
    if late:
        with st.container(border=True):
            st.markdown(f":material/sync_problem: {len(late)} of the documents were read before your latest rule.")
            if st.button("Read the documents again with these rules", type="primary", icon=":material/refresh:"):
                with st.status("Reading again…", expanded=True) as box_:
                    for s in read:
                        box_.write(f"**{s.title}**")
                        steps.run(it, s.id, lambda m: None)
                        box_.write(it.log(s.id)[-1])
                    box_.update(label="Read again with your rules", state="complete", expanded=False)
                st.rerun()

    def listing(title: str, kind: str, text) -> None:
        if not k[kind]:
            return
        st.markdown(f"###### {title} · {len(k[kind])}")
        for i, row in enumerate(k[kind]):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(text(row))
                st.space("stretch")
                st.button("Remove", key=f"know_rm_{kind}_{i}", type="tertiary", on_click=knowledge.remove,
                          args=(it, kind, i))

    listing("Tag rules", "tags", lambda t: f"**{t['prefix']}** is a {t['class']} · {twin.FAMILY_NAME.get(t['family'], t['family'])}"
            + (" · serves a room" if t.get("terminal") else "") + f" :small[· {t['by']}]")
    listing("Point terms", "terms", lambda t: f"**{t['phrase']}** is a {t['class']} :small[· {t['by']}]")
    listing("Notes", "notes", lambda n: f"**{n['label']}** · {n['topic']}: {n['body']} :small[· {n['author']}]")
    if any(k[x] for x in ("tags", "terms", "notes")):
        st.download_button("Download this building's knowledge (YAML)", knowledge.export(it),
                           file_name=f"{it.slug}_knowledge.yaml", icon=":material/download:",
                           help="To review and move into the shared knowledge model, or to give to the next building.")


def show_fact(fid: str) -> None:
    st.session_state.update(ab_sel=fid, ab_work="doc")  # a callback: runs before the widgets are made


def status_of(f: dict) -> str:
    return "ask" if f["status"] == "proposed" and f.get("ask") else f["status"]


def where(f: dict) -> str:
    s = f["src"]
    page = f" p{s['page'] + 1}" if s.get("page") is not None else ""
    row = f" row {s['row']}" if s.get("row") else ""
    return f"{s.get('sheet') or s['file']}{page}{row}"


def answer(f: dict, value, field) -> None:
    if field:
        it.decide(f["id"], "fixed", value, field)
    else:
        it.decide(f["id"], "confirmed")


def question_card(f: dict, i) -> None:
    ask = f["ask"]
    with st.container(border=True, key=f"q_{i}"):
        st.markdown(ask["q"])
        proposed = f["data"].get(ask["field"]) if ask.get("field") else None
        if isinstance(proposed, list):
            proposed = f"{len(proposed)} units"
        st.caption(f"{where(f)} · {f['method']} · confidence {round(f['conf'] * 100)}%"
                   + (f" · proposed: **{proposed}**" if proposed not in (None, "") else ""))
        if ask.get("field") == "name":  # a room with no name on the plan: type it
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                typed = st.text_input("Room name", key=f"name_{i}_{f['id']}", placeholder="Name from the plan",
                                      label_visibility="collapsed", width=240)
                st.button("Save name", key=f"savename_{i}", disabled=not typed,
                          on_click=lambda f=f, k=f"name_{i}_{f['id']}": it.decide(f["id"], "fixed",
                                                                              st.session_state[k].title(), "name"))
        with st.container(horizontal=True, gap="small"):
            st.button("Show", key=f"show_{i}", icon=":material/visibility:", on_click=show_fact, args=(f["id"],),
                      type="tertiary")
            for k, o in enumerate(ask["options"]):
                st.button(o["label"], key=f"opt_{i}_{k}", on_click=answer, args=(f, o["value"], ask["field"]))
            if f["kind"] == "issue":
                st.button("Noted", key=f"ok_{i}", icon=":material/check:", type="primary",
                          on_click=lambda f=f: it.decide(f["id"], "confirmed"))
                st.button("Not an issue", key=f"no_{i}", on_click=lambda f=f: it.decide(f["id"], "rejected"))
            else:
                if not ask["options"]:
                    st.button("Yes, keep it", key=f"ok_{i}", icon=":material/check:", type="primary",
                              on_click=lambda f=f: it.decide(f["id"], "confirmed"))
                st.button("Reject", key=f"no_{i}", icon=":material/close:",
                          on_click=lambda f=f: it.decide(f["id"], "rejected"))


def questions(step_ids: list[str]) -> None:
    qs = [f for s in step_ids for f in it.open_questions(s)]
    answered = [f for s in step_ids for f in it.facts(s) if f.get("ask") and f["method"] == "human"]
    if not qs:
        st.success(f"No question left here. {len(answered)} answered.", icon=":material/task_alt:")
    else:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(f"{len(qs)} to answer · {len(answered)} answered. **Show** opens the place in the document.")
            if st.button("Accept every suggestion", icon=":material/done_all:", key="acc_all", type="tertiary",
                         help="Confirms what the reader proposed for every open question here; checks are marked noted."):
                for f in qs:
                    it.decide(f["id"], "confirmed")
                st.rerun()
        page = st.session_state.get("ab_qpage", 0)
        page = min(page, (len(qs) - 1) // PER_PAGE)
        for i, f in enumerate(qs[page * PER_PAGE:(page + 1) * PER_PAGE]):
            question_card(f, i)
        if len(qs) > PER_PAGE:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.button("Previous", key="qp", disabled=page == 0,
                          on_click=lambda: st.session_state.update(ab_qpage=page - 1))
                st.caption(f"{page * PER_PAGE + 1}–{min(len(qs), (page + 1) * PER_PAGE)} of {len(qs)}")
                st.button("Next", key="qn", disabled=(page + 1) * PER_PAGE >= len(qs),
                          on_click=lambda: st.session_state.update(ab_qpage=page + 1))
    if answered:
        with st.expander(f"Your answers · {len(answered)}"):
            for f in answered:
                with st.container(horizontal=True, vertical_alignment="center"):
                    val = f["data"].get(f["ask"]["field"]) if f["ask"].get("field") else ""
                    st.markdown(f"**{f.get('decided', '')}** {f['label']}" + (f" → {val}" if val else ""))
                    st.button("Undo", key=f"undo_{f['id']}", type="tertiary", on_click=it.undo, args=(f["id"],))


def built_tables(step_ids: list[str]) -> None:
    facts = [f for s in step_ids for f in it.facts(s)]
    kinds = list(dict.fromkeys(f["kind"] for f in facts))
    if not kinds:
        return
    kind = st.segmented_control("Show", kinds, default=kinds[0], key=f"kind_{step_id}",
                                format_func=lambda k: f"{KIND_NAME.get(k, k)} ({sum(1 for f in facts if f['kind'] == k)})")
    rows = [f for f in facts if f["kind"] == (kind or kinds[0])]
    df = pd.DataFrame([{"status": status_of(f), "what": f["label"], "confidence": f["conf"], "method": f["method"],
                        "source": where(f), **_detail(f)} for f in rows])
    ev = st.dataframe(df, hide_index=True, height=360, on_select="rerun", selection_mode="single-row",
                      key=f"tbl_{step_id}_{kind}",
                      column_config={"confidence": st.column_config.ProgressColumn("confidence", min_value=0,
                                                                                   max_value=1, format="percent")})
    if ev and ev.selection.rows:
        fid = rows[ev.selection.rows[0]]["id"]
        if fid != st.session_state["ab_sel"]:
            select(fid)
            st.rerun()


def _detail(f: dict) -> dict:
    d = f["data"]
    k = f["kind"]
    if k == "equipment":
        return {"class": d["class"], "make": d["attrs"].get("make", ""), "schedule": d["schedule"].title()}
    if k == "placement":
        return {"room": d.get("room") or "", "found by": d["by"]}
    if k == "room":
        return {"floor": d["floor"]}
    if k == "point":
        return {"class": d["class"] or "", "description": d["description"]}
    if k == "controller":
        return {"controller": d["controller"], "trunk": d["trunk"], "address": d["address"]}
    if k == "room_check":
        return {"submittal": d["room"], "plan": d.get("plan_room") or ""}
    if k == "sequence":
        return {"applies to": len(d["applies_to"]), "setpoints": len(d["setpoints"])}
    return {}


def viewer(step_files: list[str]) -> None:
    """The document: the selected fact's page if it has one, with what was read outlined, in a viewer with the same
    controls as the building and the graph (drag, zoom, fit, full screen, pages)."""
    sel = it.fact(st.session_state["ab_sel"]) if st.session_state["ab_sel"] else None
    pdfs = [n for n in step_files if n.lower().endswith(".pdf")]
    if sel and sel["src"].get("file", "").lower().endswith(".pdf") and sel["src"].get("page") is not None:
        if sel["src"]["file"] not in pdfs:
            pdfs = [sel["src"]["file"]] + pdfs
        if st.session_state.get("ab_sel_shown") != sel["id"]:  # jump once; the person may page away after
            st.session_state["ab_sel_shown"] = sel["id"]
            st.session_state["ab_vfile"] = sel["src"]["file"]
            st.session_state[f"ab_vpage_{sel['src']['file']}"] = sel["src"]["page"]
    if not pdfs:
        csvs = [n for n in step_files if n.lower().endswith(".csv")]
        if csvs:
            path = it.file_by_name(csvs[0])
            df = pd.read_csv(path)
            row = sel["src"].get("row") if sel else None
            st.caption(f"{csvs[0]} · {len(df)} rows" + (f" · row {row}: the selected item" if row else ""))
            if row:
                df = df.iloc[max(0, row - 2 - 6):row - 2 + 14]
            st.dataframe(df, hide_index=False, height=520)
        else:
            st.info("Click a unit, a room or a graph node, or **Show** on a question: the document opens here at "
                    "that place.", icon=":material/description:")
        return
    if st.session_state.get("ab_vfile") not in pdfs:
        st.session_state["ab_vfile"] = pdfs[0]
    name = st.session_state["ab_vfile"]
    path = it.file_by_name(name)
    n = pdfdoc.page_count(path)
    pkey = f"ab_vpage_{name}"
    page = st.session_state.get(pkey, 0)
    if not 0 <= page < n:
        page = 0
    st.session_state[pkey] = page
    here = sel and sel["src"].get("file") == name and sel["src"].get("page") == page and sel["src"].get("bbox")
    if len(pdfs) > 1 or sel:
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            if len(pdfs) > 1:
                st.selectbox("File", pdfs, key="ab_vfile", label_visibility="collapsed", width=220)
            if sel:
                st.caption(f"**{sel['label']}** · {KIND_NAME.get(sel['kind'], sel['kind'])} · {where(sel)} · "
                           f"{sel['method']} · {round(sel['conf'] * 100)}% · {sel['status']}")
                st.button("", key="clear_sel", type="tertiary", on_click=select, args=(None,),
                          icon=":material/close:", help="Clear the selection")
    boxes = [{"bbox": f["src"]["bbox"], "color": STATUS_COLOR.get(status_of(f), "#4DA3E8"), "width": 2}
             for f in it.facts() if f["src"].get("file") == name and f["src"].get("page") == page
             and f["src"].get("bbox") and f["kind"] not in ("floor", "sequence")]
    if here:
        boxes.append({"bbox": sel["src"]["bbox"], "color": "#FF3B6B", "width": 5, "pad": 6})
    url, w, h, s = page_image(str(path), page, json.dumps(boxes), file_sha(name))
    sheet = pdfdoc.sheet_number(pdfdoc.words(path, page))
    legend = "".join(f"<span><i style='background:{c}'></i>{k}</span>" for k, c in
                     [("confirmed", STATUS_COLOR["confirmed"]), ("proposed", STATUS_COLOR["proposed"]),
                      ("needs you", STATUS_COLOR["ask"]), ("selected", "#FF3B6B")]) if boxes else ""
    focus = [round(v * s, 1) for v in sel["src"]["bbox"]] if here else None
    picked(frame(doc_page(), {"img": url, "w": w, "h": h, "key": f"{file_sha(name)[:12]}:{page}:{hash(url)}",
                              "focus": focus, "page": page, "pages": n, "file": name, "theme": theme(),
                              "label": f"Page {page + 1} / {n}" + (f" · {sheet}" if sheet else ""),
                              "legend": legend},
                 FIT, key="ab_doc", title="The document"))


# ---------------------------------------------------------------- the two boxes: the step (left), what is built (right)

FIT = 620  # a viewer's first height inside a fit box; the page then sizes it to the screen


def outputs_panel() -> None:
    """What the whole setup builds: the site, the building (twin), its knowledge graph, the sequences linked to it and
    the review. On the right of every step; it can be hidden, or opened full screen."""
    full = st.session_state["ab_out"] == "full"
    loc = shown_location()
    seqs = len(b["sequences"])
    with box("out", fit=not full):
        outs = {}
        if loc:
            outs["site"] = "Site"
        outs |= {"twin": "Building", "graph": "Knowledge graph"}
        if seqs:
            outs["seq"] = f"Sequences ({seqs})"
        outs["review"] = f"Review ({len(it.open_questions())})"
        if want := st.session_state.pop("ab_view_want", None):
            st.session_state["ab_view"] = want
        if st.session_state.get("ab_view") not in outs:
            st.session_state["ab_view"] = "site" if loc and not it.done("plans") else "twin"
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.html('<div class="box-title"><span class="ms">deployed_code</span><span>Built so far</span></div>',
                    width="content")
            st.segmented_control("Output", list(outs), format_func=outs.get, key="ab_view",
                                 label_visibility="collapsed")
            st.space("stretch")
            if full:
                st.button("Exit full screen", icon=":material/close_fullscreen:", on_click=out_mode, args=("side",),
                          type="tertiary")
            else:
                st.button("", icon=":material/open_in_full:", on_click=out_mode, args=("full",), type="tertiary",
                          help="Open full screen", key="out_full")
                st.button("", icon=":material/right_panel_close:", on_click=out_mode, args=("hidden",),
                          type="tertiary", help="Hide what is built", key="out_hide")
        view = st.session_state.get("ab_view") or "twin"
        h = 1000 if full else FIT
        if view == "site":
            lat, lng, label, preview = loc
            if preview:
                st.caption(f"Preview of **{label}**. It is saved only when you press **Use this location**.")
            site_map(lat, lng, it.name, h)
        elif view == "graph":
            graph_view(h)
        elif view == "seq":
            sequences_view(h, key="ab_seq_out")
        elif view == "review":
            review_live()
        else:
            twin_view(h)


def shown_location() -> tuple | None:
    """(lat, lng, label, preview): the result picked in step 0 before it is confirmed, else the confirmed location."""
    results = st.session_state.get("ab_loc_results") or []
    if step_id == "locate" and results:
        r = results[min(st.session_state.get("ab_loc_pick", 0) or 0, len(results) - 1)]
        return r.lat, r.lng, r.address, True
    if it.location:
        return it.location["lat"], it.location["lng"], it.location["address"], False
    return None


def review_live() -> None:
    """The review as it stands after the steps read so far: what is confirmed, what waits for a second source,
    what needs you. It grows with every document; step 6 is where it is finished."""
    facts = it.facts()
    if not facts and not it.location:
        st.info("Nothing to review yet. Every fact the reader finds lands here, with its source and confidence, "
                "as each document is read.", icon=":material/fact_check:")
        return
    conf = sum(1 for f in facts if f["status"] == "confirmed")
    asks = it.open_questions()
    waiting = sum(1 for f in facts if f["status"] == "proposed" and not f.get("ask"))
    c = st.columns(4)
    c[0].metric("Facts read", len(facts), border=True)
    c[1].metric("Confirmed", conf, f"{round(100 * conf / max(1, len(facts)))}%", border=True, delta_color="off")
    c[2].metric("Waiting for a 2nd source", waiting, border=True)
    c[3].metric("Need you", len(asks), border=True)
    rows = [{"step": "0 · Locate", "status": "confirmed" if it.location else "to do",
             "facts": 1 if it.location else 0, "confirmed": 1 if it.location else 0, "need you": 0}]
    for s_ in STEPS[:-1]:
        fs = it.facts(s_.id)
        rows.append({"step": f"{s_.n} · {s_.title}", "status": "read" if it.done(s_.id) else "to do",
                     "facts": len(fs), "confirmed": sum(1 for f in fs if f["status"] == "confirmed"),
                     "need you": len(it.open_questions(s_.id))})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if asks:
        st.markdown("###### Latest questions")
        for i, f in enumerate(asks[-3:]):
            question_card(f, f"live{i}")
        if len(asks) > 3:
            st.button(f"See all {len(asks)} in the review", icon=":material/fact_check:", type="tertiary",
                      on_click=go, args=("review",))


def layout():
    """The step's box (left, about 40%) and what is built (right, about 60%), as on a project's Location page. The
    right one can be hidden behind a tab, or opened full screen above the step. Returns (left, right or None)."""
    mode = st.session_state["ab_out"]
    if mode == "full":
        outputs_panel()
        return st.container(), None
    if mode == "hidden":
        main, tab = st.columns([1, 0.035], gap="small")
        with tab, st.container(key="ab_reopen"):
            st.button("Built so far", icon=":material/right_panel_open:", on_click=out_mode, args=("side",),
                      help="Show the site, the building, the knowledge graph and the review")
        return main, None
    return st.columns([2, 3], gap="medium")


def step_head(title: str, icon: str) -> None:
    """The top of the step's box: its name, and Back / Next."""
    i = FLOW_IDS.index(step_id)
    with st.container(horizontal=True, vertical_alignment="center", gap="small", horizontal_alignment="distribute"):
        st.html(f'<div class="box-title" title="{title}"><span class="ms">{icon}</span>'
                f'<span>Step {FLOW[i][1]} · {SHORT[step_id]}</span></div>', width="content")
        nav = st.container(horizontal=True, vertical_alignment="center", gap="small", width="content")
    with nav:
        if i > 0:
            st.button("", icon=":material/arrow_back:", on_click=go, args=(FLOW[i - 1][0],), key="nav_back",
                      help=f"Back: {FLOW[i - 1][2]}", type="tertiary")
        if i + 1 < len(FLOW):
            st.button(f"Next · {SHORT[FLOW[i + 1][0]]}", icon=":material/arrow_forward:", type="primary",
                      on_click=go, args=(FLOW[i + 1][0],), key="nav_next", help=FLOW[i + 1][2])


def work_tabs(tabs: dict[str, str], default: str) -> str:
    if want := st.session_state.pop("ab_work_want", None):
        st.session_state["ab_work"] = want
    if st.session_state.get("ab_work") not in tabs:
        st.session_state["ab_work"] = default
    return st.segmented_control("Work", list(tabs), format_func=tabs.get, key="ab_work",
                                label_visibility="collapsed") or default


# ---------------------------------------------------------------- step 0: locate

WHY_ADDRESS = """<ul class="ab-why">
<li><b>Weather and climate.</b> Outdoor air conditions, design days and the climate zone drive setpoints,
economizer limits and every comparison of how the building runs.</li>
<li><b>Codes and utilities.</b> The energy code, the utility and its tariffs, and the local rules that apply all
follow from the exact place.</li>
<li><b>Time and schedules.</b> The time zone and local holidays set the occupancy schedules the sequences use.</li>
<li><b>Matching the records.</b> The address ties the drawings, the BMS station and the service records to one
building, so documents from different tools land on the same twin.</li>
<li><b>The real building.</b> Its footprint, orientation, sun and neighbours, seen in 2D and 3D on the right, and the
place a technician is sent to.</li></ul>"""


def locate_step() -> None:
    server_key = secret("google_maps_api_key")
    provider = "Google Maps" if server_key else "OpenStreetMap"
    saved = it.location
    step_head("Locate the building", "location_on")
    if saved:
        st.success(f"**{saved['address']}**  \n{saved['lat']:.5f}, {saved['lng']:.5f} · confirmed by "
                   f"{saved['confirmed_by']} on {saved['confirmed_at']} · from {saved['provider']}",
                   icon=":material/where_to_vote:")
    else:
        st.markdown("### Where is the building?")
    with st.expander("Why the exact address matters", expanded=not saved, icon=":material/info:"):
        st.html(WHY_ADDRESS)
    st.session_state.setdefault("ab_loc_query", it.s.get("address") or it.name)
    with st.form("ab_locate", border=False):
        query = st.text_input("Building name or address" if not saved else "Change the location",
                              key="ab_loc_query", placeholder="Street, number, city")
        who = st.text_input("Your name", key="ab_loc_who", help="Recorded with the location you confirm.")
        search = st.form_submit_button("Search", icon=":material/search:")
    if search and query.strip():
        try:
            st.session_state["ab_loc_results"] = get_geocoder(server_key).search(query.strip())
            st.session_state["ab_loc_pick"] = 0
            st.session_state["ab_view_want"] = "site"
        except LocateError as e:
            st.session_state["ab_loc_results"] = []
            st.error(str(e))
    results = st.session_state.get("ab_loc_results")
    if results == []:
        st.warning("Nothing found. Try the street address with the city.")
    elif results:
        i = st.radio("Pick the exact building", range(len(results)), key="ab_loc_pick",
                     format_func=lambda i: f"{results[i].address}  ({results[i].lat:.5f}, {results[i].lng:.5f})")
        if results[i].kind in ("locality", "political", "postal_code", "country") or results[i].kind.startswith(
                "administrative_area"):
            st.warning("This is an area, not a building. Search with the street address (number, street, city) "
                       "to get the exact building.", icon=":material/location_searching:")
        else:
            st.caption("The map on the right shows the result you pick, in 2D and in 3D. Check it is the right "
                       "building.")
        if st.button("Use this location", type="primary", disabled=not who.strip(),
                     icon=":material/where_to_vote:", help=None if who.strip() else "Enter your name first."):
            it.set_location(location_dict(results[i]), who.strip())
            del st.session_state["ab_loc_results"]
            st.session_state["ab_view_want"] = "site"
            st.rerun()
    st.caption(f"The text you search for is sent to {provider}. Nothing else leaves the app.")


# ---------------------------------------------------------------- the last step: what people know

def prompts() -> list[tuple[str, str, str]]:
    """(about, topic, question): what to ask the people who know the building, from what the graph holds."""
    out = [("building", "operations", "How is the building really run? Schedules, overrides, seasons, what the "
                                      "operators change by hand."),
           ("building", "history", "What was replaced, added or abandoned since the drawings were made?")]
    fams: dict[str, list[dict]] = {}
    for n, e in sorted(b["equip"].items()):
        fams.setdefault(e["family"], []).append((n, e))
    for fam, units in fams.items():
        n, e = units[0]
        name = twin.FAMILY_NAME.get(fam, fam)
        out.append((f"unit:{n}", "maintenance", f"{name}{'es' if name.endswith(('x', 's')) else 's'} ({len(units)}): any unit with a known fault, a quirk, or "
                                                f"points that are unused? Start with {e['tag']}."))
    if b["equip"]:
        out.append(("building", "naming", "Any names the documents and the BMS use differently (abbreviations, "
                                          "renumbered units, the contractor's own habits)?"))
    return out[:7]


def ask_prompt(target: str, topic: str, question: str) -> None:
    st.session_state.update(ab_know="Note", ab_note_target=target, ab_note_topic=topic, ab_note_q=question,
                            ab_work="add")


def knowledge_step() -> None:
    step_head("Add knowledge", "psychology")
    st.markdown("### What people know that no document says")
    st.caption(f"{len(kn['notes'])} notes · {len(kn['tags'])} tag rules · {len(kn['terms'])} point terms · "
               f"{sum(1 for k in knowledge.notes_for(it) if k.startswith('unit:'))} units with a note. Every entry "
               "becomes part of the knowledge graph, with who said it. Rules also re-read the documents.")
    work = work_tabs({"ask": "Questions to ask", "add": "Add to the graph", "finish": "Finish"}, "ask")
    if work == "ask":
        st.caption("Drawn from what the graph holds. **Answer** opens the note form, about the right thing.")
        for k, (target, topic, q) in enumerate(prompts()):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(f":material/help: {q}")
                st.space("stretch")
                st.button("Answer", key=f"prompt_{k}", type="tertiary", icon=":material/edit_note:",
                          on_click=ask_prompt, args=(target, topic, q))
    elif work == "add":
        knowledge_view()
    else:
        finish_box()


def finish() -> None:
    project = publish(it, get_store())
    set_project(project)
    st.session_state["ab_finished"] = project


def finish_box() -> None:
    """The end of the setup: the building becomes a project like every other, with all its pages."""
    done = it.s.get("published")
    read = sum(1 for s_ in STEPS[:-1] if it.done(s_.id))
    if done:
        st.success(f"**{it.name} is a project.** Its tree, graph, equipment, sequences, tables, notes, tribal "
                   "knowledge and digital twin are under Projects, and in the building list of every project "
                   "page. Finish again after a change to update it.", icon=":material/task_alt:")
    else:
        st.markdown(f"**Ready when you are.** {read} of 5 documents read, {len(it.open_questions())} questions "
                    "open. Finishing turns the building into a project with all its pages; you can come back, "
                    "answer more and finish again.")
    with st.container(horizontal=True, gap="small"):
        st.button("Finish and update the project" if done else "Finish: create the project", type="primary",
                  icon=":material/rocket_launch:", on_click=finish, disabled=not read,
                  help=None if read else "Read at least one document first.")
        if done:
            st.page_link("tree_app.py", label="Open the project", icon=":material/arrow_forward:")
    if st.session_state.pop("ab_finished", None):
        st.session_state["flash"] = (f"{it.name} is ready: every part of the project is in the chips above (location, "
                                     "tree, graph, equipment, sequences, tables, notes, tribal knowledge, digital twin).")
        st.switch_page("tree_app.py")


# ---------------------------------------------------------------- the document steps

def read_now(files: list[tuple[str, bytes]]) -> None:
    """Read the step's files here, in the step's box, with the reader's log as it goes."""
    for name, data in files:
        it.add_file(step_id, name, data)
    with st.status(f"Reading {', '.join(n for n, _ in files) or 'the documents'}…", expanded=True) as status_box:
        n = steps.run(it, step_id, lambda m: status_box.write(m))
        status_box.update(label=f"Read: {n} facts", state="complete", expanded=False)
    st.session_state.update(ab_sel=None, ab_qpage=0, ab_nonce=st.session_state.get("ab_nonce", 0) + 1,
                            ab_work=None)
    st.session_state["ab_view_want"] = {"plans": "twin", "sequences": "seq", "submittal": "graph",
                                        "bms": "graph"}.get(step_id, "twin")
    st.toast(f"{step.title}: read", icon=":material/check_circle:")
    st.rerun()


def review_step() -> None:
    live_eq = list(b["equip"].values())
    pts = b["points"]
    all_facts = it.facts()
    conf = sum(1 for f in all_facts if f["status"] == "confirmed")
    step_head("Review and finish", "fact_check")
    st.caption(f"**{it.name}** · {len(b['floors'])} floors · {len(b['rooms'])} rooms · {len(live_eq)} units "
               f"({sum(1 for e in live_eq if e['room'])} placed) · {len(pts)} points "
               f"({sum(1 for p in pts if p['status'] == 'confirmed')} confirmed) · "
               f"{round(100 * conf / max(1, len(all_facts)))}% of facts confirmed")
    proposed = [f for f in all_facts if f["status"] == "proposed" and not f.get("ask")]
    nq = len(it.open_questions())
    work = work_tabs({"ask": f"Open questions ({nq})", "wait": f"Waiting ({len(proposed)})", "doc": "Document",
                      "score": "Score and export"}, "ask")
    if work == "doc":
        viewer([f["name"] for fs in it.s["files"].values() for f in fs])
    elif work == "wait":
        if not proposed:
            st.success("Nothing waits for a second source.", icon=":material/task_alt:")
        else:
            st.caption(f"{len(proposed)} facts nobody contradicted but no second document confirmed either "
                       f"({', '.join(sorted({KIND_NAME.get(f['kind'], f['kind']) for f in proposed}))}).")
            if st.button(f"Confirm these {len(proposed)}", icon=":material/done_all:"):
                for f in proposed:
                    it.s["decisions"][f["id"]] = {"status": "confirmed", "value": None, "field": None, "at": 0}
                it.save()
                st.rerun()
    elif work == "score":
        keys = score.answer_keys()
        if keys:
            default = next((k for k in keys if k.split("_")[0] in it.slug), None)
            key = st.selectbox("Answer key", ["(none)"] + keys, index=(keys.index(default) + 1) if default else 0,
                               help="Example buildings only. The readers never see the answer key; it is used here "
                                    "to measure them, before and after your answers.")
            if key != "(none)":
                df = pd.DataFrame(score.score(it, key))
                df["machine %"] = (df["machine"] / df["out of"].clip(lower=1) * 100).round(0)
                df["with you %"] = (df["with you"] / df["out of"].clip(lower=1) * 100).round(0)
                st.dataframe(df[["measure", "machine", "with you", "out of", "machine %", "with you %", "what"]],
                             hide_index=True)
        graph_json = {"building": it.name, "location": it.location, "facts": all_facts,
                      "knowledge": knowledge.get(it)}
        st.download_button("Download the knowledge graph (JSON, with provenance)",
                           json.dumps(graph_json, indent=1), file_name=f"{it.slug}_graph.json",
                           icon=":material/download:")
    else:
        selected_questions()
        questions([s.id for s in STEPS[:-1]])


def empty_step() -> list[tuple[str, bytes]] | None:
    """A step with nothing read yet: a big drop zone for its document, and the example ready to use next to it.
    Returns the files to read now, if any."""
    st.markdown(f"### {step.ask}")
    st.caption(f"**Builds:** {step.builds}  \n**Looks for:** {step.looks_for}")
    with st.container(key="ab_drop"):
        up = st.file_uploader(f"Drop the {step.title.lower()} here, or browse ({', '.join(step.types).upper()})",
                              type=list(step.types), accept_multiple_files=True,
                              key=f"up_{step_id}_{st.session_state.get('ab_nonce', 0)}", label_visibility="collapsed")
    if up:
        return [(u.name, u.getvalue()) for u in up]
    example = TEST_PACKAGE / step.test_file if step.test_file else None
    if example and example.exists():
        with box("example", "Or try it with the example", "science"):
            with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
                if example.suffix.lower() == ".pdf":
                    st.image(thumbnail(str(example), str(example.stat().st_mtime)), width=150)
                with st.container(gap="small"):
                    pages = f" · {pdfdoc.page_count(example)} pages" if example.suffix.lower() == ".pdf" else ""
                    st.markdown(f"**{example.name}**  \n:small[{example.stat().st_size / 1e6:.1f} MB{pages} · from a "
                                "public bid set, ready to use]")
                    if st.button("Use this example", type="primary", icon=":material/play_arrow:", key="use_example"):
                        return [(example.name, example.read_bytes())]
    if needs := [steps.BY_ID[n] for n in step.needs if not it.done(n)]:
        st.caption(":material/info: Works best after " + ", ".join(f"step {n.n} ({n.title.lower()})" for n in needs)
                   + ".")
    return None


def document_step() -> None:
    files = it.files(step_id)
    step_head(step.title, {"plans": "map", "schedules": "table_view", "sequences": "sync_alt",
                           "submittal": "description", "bms": "dns"}.get(step_id, "description"))
    if not files:
        todo = empty_step()
        if todo:
            read_now(todo)  # in this box, under the drop zone
        return
    nq = len(it.open_questions(step_id))
    tabs = {"doc": "Document", "ask": f"Needs you ({nq})",
            "built": "Sequences" if step_id == "sequences" else "Results", "log": "Log"}
    todo, reread = None, False
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        work = work_tabs(tabs, "ask" if nq else ("built" if step_id == "sequences" else "doc"))
        st.space("stretch")
        with st.container(key="ab_files", width="content"), st.popover(
                "", icon=":material/folder_open:", help=f"{len(files)} file(s): add, remove, read again"):
            for f in files:
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    st.markdown(f":material/description: {f['name']} :small[· {f['size'] / 1e6:.1f} MB]")
                    st.space("stretch")
                    if st.button("", key=f"rm_{f['sha256'][:8]}", icon=":material/delete:", type="tertiary",
                                 help=f"Remove {f['name']}"):
                        it.remove_file(step_id, f["name"])
                        steps.run(it, step_id, lambda m: None)
                        st.rerun()
            more = st.file_uploader("Add a file", type=list(step.types), accept_multiple_files=True,
                                    key=f"up_{step_id}_{st.session_state.get('ab_nonce', 0)}")
            if more:
                todo = [(u.name, u.getvalue()) for u in more]
            reread = st.button("Read again", icon=":material/refresh:",
                               help="Reads the files again with what the earlier steps know now. Your answers are kept.")
    # Reading runs here, in the step's box, under its tabs.
    if todo:
        read_now(todo)
    elif reread:
        read_now([])
    if stale := steps.stale(it, step_id):
        st.warning(f"{', '.join(stale)} changed since this step was read. **Read again** (the folder button) to use the latest.",
                   icon=":material/sync_problem:")
    if work == "doc":
        viewer([f["name"] for f in files])
    elif work == "ask":
        located = {"placement", "room", "room_check"}
        on_plan = sum(1 for f in it.open_questions(step_id) if f["kind"] in located)
        if st.session_state.get("ab_ask_how") not in ("List", "On the building"):
            st.session_state["ab_ask_how"] = "List"
        how = st.segmented_control("How", ["List", "On the building"], key="ab_ask_how",
                                   label_visibility="collapsed") or "List"
        if how == "List":
            selected_questions()
            questions([step_id])
        else:
            st.caption(f"{on_plan} of this step's {nq} questions have a place on a plan: they pulse in amber. "
                       "Hover one to answer it there, or step through them with N.")
            twin_view(FIT, only_ask=True, key="ab_twin_ask", panel=False)
    elif work == "built":
        if step_id == "sequences":
            sequences_view(FIT, key="ab_seq_left")
        else:
            built_tables([step_id])
    else:
        for line in it.log(step_id) or ["Nothing read yet for this step."]:
            st.markdown(("- " if not line.startswith("  ") else "    - ") + line.strip())


left, right = layout()
with left, box("work", fit=True):
    if step_id == "locate":
        locate_step()
    elif step_id == "knowledge":
        knowledge_step()
    elif step_id == "review":
        review_step()
    else:
        document_step()
if right is not None:
    with right:
        outputs_panel()
