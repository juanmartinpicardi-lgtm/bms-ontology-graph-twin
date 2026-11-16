"""Add a building: a guided setup, one step at a time. Locate the building, upload its documents, review, then add
what people know about it (tribal knowledge). The knowledge graph and the building (its twin) are built along the
way and stay open on the right: hide them, or open them full screen.

Each document step asks for one kind of document. When it arrives the reader runs in front of you, page by page, and what it
built appears next to the document: the PDF on the left with every fact it read outlined, the building on the right
in 3D or as a 2D plan, growing step by step, and the knowledge graph next to it. A click on a unit, a room or a
graph node opens its place in the document. What the reader is not sure about is asked, in a list or on the building
itself, with the place on the page it came from. Answers are kept (method = human) and survive a re-read.

The readers are rules (src/projectmodel/intake), no LLM. The test package in test_packages/troop_d/ has one file per
step.
"""

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.bridge import frame  # noqa: E402
from projectmodel.app.shell import box, knowledge_model, secret, site_map  # noqa: E402
from projectmodel.locate import LocateError, get_geocoder, location_dict  # noqa: E402
from projectmodel import notes as project_notes  # noqa: E402
from projectmodel.intake import graph, knowledge, pdfdoc, score, steps, twin, vectors  # noqa: E402
from projectmodel.viz import render_html  # noqa: E402
from projectmodel.intake.model import building, missing, progress  # noqa: E402
from projectmodel.intake.state import Intake, list_intakes  # noqa: E402
from projectmodel.intake.steps import STEPS, TEST_PACKAGE  # noqa: E402

STATUS_COLOR = {"confirmed": "#3CB371", "proposed": "#4DA3E8", "ask": "#F0A030", "rejected": "#D9534F"}
KIND_NAME = {"floor": "Floors", "room": "Rooms", "placement": "Where units are", "equipment": "Equipment",
             "relation": "Connections", "sequence": "Sequences", "issue": "Checks", "controller": "Controllers",
             "point": "Points", "room_check": "Room schedule check", "alias": "BMS devices", "bms_object": "BMS objects"}
PER_PAGE = 6

st.html("""<style>
.st-key-ab_steps button { border-radius: 12px; }
.st-key-ab_steps button p { font-size: .86rem; }
[class*="st-key-q_"] { border-left: 3px solid #F0A030 !important; border-radius: 12px !important; }
/* The document (left) and the outputs (right) sit side by side, the same height, sized to fit the screen under the
   header and the step: no page scroll. Each scrolls inside itself when its content is taller. */
:root { --panelh: max(480px, calc(100vh - 436px)); }
[data-testid="stColumn"] .st-key-box_out, .st-key-box_work,
[data-testid="stColumn"] [data-testid="stLayoutWrapper"]:has(> .st-key-box_out),
[data-testid="stLayoutWrapper"]:has(> .st-key-box_work) {
  height: var(--panelh) !important; max-height: var(--panelh); flex: 0 0 auto !important; box-sizing: border-box; }
[data-testid="stColumn"] .st-key-box_out, .st-key-box_work { overflow-y: auto; }
.block-container { padding-bottom: 1rem !important; }
.st-key-box_work [data-testid="stImage"] img { max-height: calc(var(--panelh) - 150px); object-fit: contain; }
.st-key-box_step { padding: 12px 18px !important; }
.st-key-box_step h3 { padding: 0; margin: 0; font-size: 1.35rem; }
.st-key-ab_reopen button { height: 168px; writing-mode: vertical-rl; border-radius: 14px; padding: 12px 6px; }
</style>""")

# The flow: locate, the five documents, review, then what people know. Locate and knowledge are steps of this page;
# the document steps and review are the intake's (intake/steps.py).
FLOW = [("locate", 0, "Locate the building")] + [(s.id, s.n, s.title) for s in STEPS] + [
    ("knowledge", len(STEPS) + 1, "Add knowledge")]
FLOW_IDS = [f[0] for f in FLOW]


# ---------------------------------------------------------------- building picker

def start_form(key: str, compact: bool = False) -> None:
    with st.form(key, border=False):
        if not compact:
            st.markdown("#### Start a new building")
            st.caption("Give it a name. Then locate it, and upload its documents one step at a time; each one adds to "
                       "the knowledge graph and to the building.")
        name = st.text_input("Building name", placeholder="e.g. Troop D Crime Lab")
        address = st.text_input("Address or place (optional)", placeholder="Street, city",
                                help="Used to find the building on the map in the first step.")
        if st.form_submit_button("Start", type="primary", icon=":material/arrow_forward:"):
            if not name.strip():
                st.error("A name is needed.")
            else:
                begin(name.strip(), address.strip())
                st.rerun()


TEST_NAME, TEST_PLACE = "Troop D Crime Lab", "Missouri State Highway Patrol Troop D, Springfield, Missouri"


def begin(name: str, address: str = "", test: bool = False) -> None:
    """A new, empty building: nothing read, nothing built. The graph, the twin and the review grow from here.
    A test building is removed when the server restarts."""
    it = Intake.create(name, address, test=test)
    st.session_state.update(ab_started=True, ab_slug=it.slug, ab_step="locate", ab_sel=None, ab_work=None,
                            ab_view="twin", ab_out="side", ab_loc_query=address or name, ab_loc_results=None)


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
    with box("intro", "Add a building", "add_business"):
        st.markdown("### Add a building, step by step")
        st.write("Eight steps: locate the building, then floor plans, equipment schedules, sequences, controls "
                 "submittal, BMS export, review, and finally what people know about it. Each document you upload is "
                 "read in front of you and turned into part of the building. The knowledge graph, the building's "
                 "twin and the review start empty and grow at every step, on the right of the page.")
    left, right = st.columns(2, gap="medium")
    with left, box("try", "Try it with the test building", "science", height="stretch"):
        st.markdown(f"#### {TEST_NAME}")
        st.write("A real public bid set (plans, schedules, sequences) plus a synthetic controls submittal and BMS "
                 "export. You start from an empty building: each step has a **Use the test file** button that loads "
                 "that step's document, and you watch it being read.")
        st.caption(f"Files: `{TEST_PACKAGE.relative_to(ROOT)}/`")
        st.button("Start with the test building", type="primary", icon=":material/play_arrow:", on_click=begin,
                  args=(TEST_NAME, TEST_PLACE, True))
        st.caption("Test buildings are cleared when the app restarts.")
    with right, box("own", "Your own building", "add_business", height="stretch"):
        start_form("ab_new")
    if existing:
        with box("resume", "Buildings in progress", "history"):
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                pick = st.selectbox("Continue", [s["slug"] for s in existing], label_visibility="collapsed",
                                    format_func=names.get,
                                    width=320)
                st.button("Continue", icon=":material/arrow_forward:", on_click=resume, args=(pick,))
    st.stop()

slugs = [s["slug"] for s in existing]
if st.session_state.get("ab_slug") not in slugs:
    st.session_state["ab_slug"] = slugs[0]
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


def select(fid: str | None) -> None:
    st.session_state["ab_sel"] = fid


def out_mode(mode: str) -> None:
    st.session_state["ab_out"] = mode


# ---------------------------------------------------------------- header: building, progress, steps

prog = progress(it)
b = building(it)
gaps = missing(it, b)
kn = knowledge.get(it)
n_known = len(kn["tags"]) + len(kn["terms"]) + len(kn["notes"])
with box("head"):
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.selectbox("Building", slugs, key="ab_slug", format_func=lambda s: names[s], label_visibility="collapsed",
                     width=260, on_change=lambda: st.session_state.update(ab_sel=None, ab_step=None))
        with st.popover("New building", icon=":material/add:"):
            st.button(f"Start {TEST_NAME} again (test files)", icon=":material/science:", on_click=begin,
                      args=(TEST_NAME, TEST_PLACE, True), type="tertiary")
            start_form("ab_new_pop", compact=True)
        st.progress(prog["share"], text=f"**{round(prog['share'] * 100)}% built** · "
                                        f"{sum(1 for s in prog['steps'].values() if s['read'])} of 5 documents read · "
                                        f"{sum(s['open'] for s in prog['steps'].values())} questions open")
        if st.session_state["ab_out"] == "hidden":
            st.button("Show graph & twin", icon=":material/right_panel_open:", on_click=out_mode, args=("side",))
        with st.popover(f"What is missing · {len(gaps) + (0 if it.location else 1)}", icon=":material/checklist:"):
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

    with st.container(horizontal=True, gap="small", key="ab_steps"):
        for sid, n, title in FLOW:
            p = prog["steps"].get(sid)
            if sid == "locate":
                icon = ":material/check_circle:" if it.location else ":material/location_on:"
            elif sid == "review":
                icon = ":material/fact_check:"
            elif sid == "knowledge":
                icon = ":material/check_circle:" if n_known else ":material/psychology:"
            elif not p["read"]:
                icon = ":material/radio_button_unchecked:"
            elif p["open"]:
                icon = ":material/pending:"
            else:
                icon = ":material/check_circle:"
            extra = f" ({p['open']})" if p and p["open"] else f" ({n_known})" if sid == "knowledge" and n_known else ""
            st.button(f"{n} · {title}{extra}", key=f"ab_go_{sid}", icon=icon, on_click=go, args=(sid,),
                      type="primary" if sid == step_id else "secondary")



# ---------------------------------------------------------------- shared pieces

@st.cache_data(show_spinner="Drawing the floor from the PDF…", max_entries=24)
def plan_geo(path: str, page: int, crop: tuple, sha: str) -> dict:  # sha: a new upload refreshes it
    return dict(vectors.plan(Path(path), page, list(crop)), key=f"{sha[:12]}:{page}:{crop}")


def file_sha(name: str) -> str:
    return next((f["sha256"] for fs in it.s["files"].values() for f in fs if f["name"] == name), "")


def picked(ev: dict | None) -> None:
    """What the building or the graph sent back. A click selects that fact, so the document opens at its place.
    An answer given on the building is checked against the question as it stands here, then saved like any other."""
    if not ev or not ev.get("id"):
        return
    if ev.get("name") == "pick" and ev["id"] != st.session_state["ab_sel"]:
        st.session_state.update(ab_sel=ev["id"], ab_work_want="doc")  # the step's work area shows the document
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
    data = twin.payload(b, plans, st.session_state["ab_sel"], needs, st.context.theme.type or "dark",
                        knowledge.notes_for(it))
    data["only_ask"] = only_ask
    picked(frame(twin.page(), data, height, key=key, title="The building"))
    if panel:
        selection_panel()


def graph_view(height: int | str = 720) -> None:
    g = graph.payload(it, b, knowledge_model())
    if not g["nodes"]:
        st.info("The graph is empty until the first document is read. Every document then adds to it: floors and "
                "rooms, units, their links, their points.", icon=":material/hub:")
        return
    n = g["counts"]["nodes"]
    st.caption(f"{n.get('location', 0)} floors and rooms · {n.get('equipment', 0)} units · {n.get('point', 0)} points · "
               f"{len(g['links'])} links. Click a node: its source opens in the document. **Colour by** kind, class, "
               "confidence, method, review status or source document.")
    picked(frame(render_html(g, st.context.theme.type), {"select": st.session_state["ab_sel"]}, height,
                 key="ab_graph", title="Knowledge graph"))
    selection_panel()


def selection_panel() -> None:
    """Under the building or the graph: what is selected, its open questions, and every document that mentions it."""
    fid = st.session_state["ab_sel"]
    if not fid or not it.fact(fid):
        st.caption("Click a unit, a room or a node: its place in the document opens, and if it needs an answer the "
                   "question opens here.")
        return
    unit = next((e for e in b["equip"].values() if fid in e["facts"]), None)
    facts = [f for f in (it.fact(i) for i in dict.fromkeys(unit["facts"] if unit else [fid])) if f]
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            if unit:
                room = f" · {unit['rel']} room {unit['room']} ({unit['room_source']})" if unit["room"] else " · no room yet"
                st.markdown(f"**{unit['tag']}** · {unit['class']}{room}")
            else:
                st.markdown(f"**{facts[0]['label']}** · {KIND_NAME.get(facts[0]['kind'], facts[0]['kind'])}")
            st.space("stretch")
            st.button("Clear", key="clear_sel_panel", type="tertiary", on_click=select, args=(None,))
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.caption("In the documents:")
            for k, f in enumerate(facts):
                st.button(f"{KIND_NAME.get(f['kind'], f['kind'])} · {where(f)}", key=f"src_{k}", on_click=show_fact,
                          args=(f["id"],), type="primary" if f["id"] == fid else "secondary",
                          icon=":material/description:")
        for k, f in enumerate(f for f in facts if f["status"] == "proposed" and f.get("ask")):
            question_card(f, f"sel{k}")
        target = (f"unit:{unit['normal']}", unit["tag"]) if unit else (
            (f"room:{facts[0]['data']['number']}", f"room {facts[0]['data']['number']}") if facts[0]["kind"] == "room" else None)
        if target:
            for n in knowledge.notes_for(it).get(target[0], []):
                st.markdown(f":material/sticky_note_2: {n['body']}  \n:small[{n['topic']} · {n['author']}]")
            st.button(f"Add a note about {target[1]}", key="note_here", type="tertiary", icon=":material/add_comment:",
                      on_click=lambda: (go("knowledge"), st.session_state.update(ab_know="Note", ab_note_target=target[0])))


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
                c = st.columns([1, 2, 1.4])
                prefix = c[0].text_input("Prefix", placeholder="CRAC", max_chars=6)
                cls = c[1].selectbox("Is a (class)", km.by_kind("equipment"), index=None, placeholder="Choose a class")
                family = c[2].selectbox("Drawn and scheduled like", knowledge.FAMILIES,
                                        format_func=lambda f: twin.FAMILY_NAME.get(f, f))
                terminal = st.checkbox("Serves a room (its room comes from its thermostat on the plan)")
                if st.form_submit_button("Add the rule", icon=":material/add:") and prefix and cls:
                    knowledge.add_tag(it, prefix, cls, family, terminal)
                    st.rerun()
        elif kind == "Point term":
            st.caption("A phrase or short name in a point list that settles the point's class. Example: "
                       "**DA-T** is a discharge air temperature sensor.")
            with st.form("know_term", border=True, clear_on_submit=True):
                c = st.columns([1, 2])
                phrase = c[0].text_input("Phrase or short name", placeholder="DA-T")
                cls = c[1].selectbox("Is a (class)", km.by_kind("point"), index=None, placeholder="Choose a class")
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
                c = st.columns([2, 1, 1])
                target = c[0].selectbox("About", list(targets), format_func=targets.get, key="ab_note_target")
                if st.session_state.get("ab_note_topic") not in project_notes.TOPICS:
                    st.session_state["ab_note_topic"] = project_notes.TOPICS[0]
                topic = c[1].selectbox("Topic", project_notes.TOPICS, key="ab_note_topic")
                author = c[2].text_input("Your name", key="ab_author")
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
                with st.status("Reading again…", expanded=True) as box:
                    for s in read:
                        box.write(f"**{s.title}**")
                        steps.run(it, s.id, lambda m: None)
                        box.write(it.log(s.id)[-1])
                    box.update(label="Read again with your rules", state="complete", expanded=False)
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
    else:
        st.caption("Nothing added yet.")


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
                                      label_visibility="collapsed", width=260)
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
            if st.button("Accept every suggestion", icon=":material/done_all:", key="acc_all",
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
    """The document on the left: the selected fact's page if it has one, with what was read outlined."""
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
            st.caption(f"{csvs[0]} · {len(df)} rows")
            row = sel["src"].get("row") if sel else None
            if row:
                st.caption(f"Row {row}: the selected item")
                df = df.iloc[max(0, row - 2 - 6):row - 2 + 14]
            st.dataframe(df, hide_index=False, height=560)
        else:
            st.info("Click a unit, a room or a graph node, or **Show** on a question: the document opens here at "
                    "that place.", icon=":material/description:")
        return
    if st.session_state.get("ab_vfile") not in pdfs:
        st.session_state["ab_vfile"] = pdfs[0]
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        if len(pdfs) > 1:
            st.selectbox("File", pdfs, key="ab_vfile", label_visibility="collapsed", width=230)
        name = st.session_state["ab_vfile"]
        path = it.file_by_name(name)
        n = pdfdoc.page_count(path)
        sheets = [pdfdoc.sheet_number(pdfdoc.words(path, p)) for p in range(n)]
        pkey = f"ab_vpage_{name}"
        if st.session_state.get(pkey, 0) >= n:
            st.session_state[pkey] = 0
        st.selectbox("Page", list(range(n)), key=pkey, label_visibility="collapsed", width=170,
                     format_func=lambda p: f"Page {p + 1}" + (f" · {sheets[p]}" if sheets[p] else ""))
        zoom = st.segmented_control("Zoom", ["Page", "Selection"], default="Selection" if sel else "Page",
                                    key=f"ab_zoom_{st.session_state['ab_sel']}", label_visibility="collapsed")
    page = st.session_state[pkey]
    facts = [f for f in it.facts() if f["src"].get("file") == name and f["src"].get("page") == page and f["src"].get("bbox")]
    boxes = []
    for f in facts:
        if f["kind"] in ("floor", "sequence"):
            continue
        s = status_of(f)
        boxes.append({"bbox": f["src"]["bbox"], "color": STATUS_COLOR.get(s, "#4DA3E8"), "width": 2})
    crop = None
    if sel and sel["src"].get("file") == name and sel["src"].get("page") == page and sel["src"].get("bbox"):
        x0, y0, x1, y1 = sel["src"]["bbox"]
        boxes.append({"bbox": [x0, y0, x1, y1], "color": "#FF3B6B", "width": 5, "pad": 6})
        if zoom == "Selection":
            pw, ph = pdfdoc.page_size(path, page)
            span = max(420, (x1 - x0) * 1.6, (y1 - y0) * 2.4)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            crop = [max(0, cx - span), max(0, cy - span * .62), min(pw, cx + span), min(ph, cy + span * .62)]
    img = pdfdoc.render(path, page, width=1300, boxes=boxes, crop=crop)
    st.image(img, width="stretch")
    legend = " · ".join(f"<span style='color:{c}'>■</span> {k}" for k, c in
                        [("confirmed", STATUS_COLOR["confirmed"]), ("proposed", STATUS_COLOR["proposed"]),
                         ("needs you", STATUS_COLOR["ask"]), ("selected", "#FF3B6B")])
    st.caption(f"{len(boxes) - (1 if crop or sel else 0)} items read on this page · " + legend, unsafe_allow_html=True)
    if sel:
        with st.container(border=True):
            st.markdown(f"**{sel['label']}** · {KIND_NAME.get(sel['kind'], sel['kind'])}")
            st.caption(f"{where(sel)} · method {sel['method']} · confidence {round(sel['conf'] * 100)}% · {sel['status']}")
            if sel["kind"] == "sequence":
                for x in sel["data"]["sections"]:
                    st.markdown(f"**{x['letter']}. {x['title']}** — {x['text'][:400]}")
            elif sel["data"].get("attrs"):
                st.json(sel["data"]["attrs"], expanded=False)
            st.button("Clear selection", key="clear_sel", type="tertiary", on_click=select, args=(None,))


# ---------------------------------------------------------------- the outputs: graph and twin, on the right

FIT = "calc(var(--panelh) - 118px)"  # a viewer's height inside the side panel or the document box


def outputs_panel() -> None:
    """The two outputs the whole setup builds: the building (twin) and its knowledge graph. On the right of every
    step; it can be hidden, or opened full screen."""
    full = st.session_state["ab_out"] == "full"
    with box("out"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.caption(":material/hub: **Built so far**", width="content")
            outs = {"twin": "Building (twin)", "graph": "Knowledge graph", "review": f"Review ({len(it.open_questions())})"}
            if st.session_state.get("ab_view") not in outs:
                st.session_state["ab_view"] = "twin"
            st.segmented_control("Output", list(outs), format_func=outs.get, key="ab_view",
                                 label_visibility="collapsed")
            st.space("stretch")
            if full:
                st.button("Exit full screen", icon=":material/close_fullscreen:", on_click=out_mode, args=("side",),
                          type="tertiary")
            else:
                st.button("", icon=":material/open_in_full:", on_click=out_mode, args=("full",), type="tertiary",
                          help="Open full screen")
                st.button("", icon=":material/right_panel_close:", on_click=out_mode, args=("hidden",),
                          type="tertiary", help="Hide the graph and the twin")
        view = st.session_state.get("ab_view") or "twin"
        h = 1000 if full else FIT
        if view == "graph":
            graph_view(h)
        elif view == "review":
            review_live()
        elif not it.done("plans"):
            if it.location:
                site_map(it.location["lat"], it.location["lng"], it.name, 1000 if full else 560)
                st.caption(f"{it.location['address']}. The building rises here as soon as the floor plans are read: "
                           "each level becomes a floor, with its rooms and the units on it.")
            else:
                twin_view(h)
        else:
            twin_view(h)


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
    """The step's own column, with the outputs beside it, hidden behind a tab on the right, or full screen above."""
    mode = st.session_state["ab_out"]
    if mode == "full":
        outputs_panel()
        return st.container()
    if mode == "hidden":
        main, tab = st.columns([1, 0.035], gap="small")
        with tab, st.container(key="ab_reopen"):
            st.button("Graph & twin", icon=":material/right_panel_open:", on_click=out_mode, args=("side",),
                      help="Show the knowledge graph and the building")
        return main
    main, side = st.columns([1.2, 1], gap="medium")
    with side:
        outputs_panel()
    return main


def nav(short: bool = False) -> None:
    """Back and Next. `short`: inside the step box, at its top right, so the page needs no scroll to move on."""
    i = FLOW_IDS.index(step_id)
    with st.container(horizontal=True, gap="small", vertical_alignment="center", width="content" if short else "stretch"):
        if i > 0:
            st.button("Back" if short else f"Back: {FLOW[i - 1][2]}", icon=":material/arrow_back:", on_click=go,
                      args=(FLOW[i - 1][0],), key=f"nav_back_{short}", help=FLOW[i - 1][2])
        if not short:
            st.space("stretch")
            st.caption(f"Step {FLOW[i][1]} of {FLOW[-1][1]}")
        if i + 1 < len(FLOW):
            st.button(f"Next: {FLOW[i + 1][2]}", icon=":material/arrow_forward:", type="primary", on_click=go,
                      args=(FLOW[i + 1][0],), key=f"nav_next_{short}")


def footer() -> None:
    with box("nav"):
        nav()


# ---------------------------------------------------------------- step 0: locate

def locate_step() -> None:
    server_key = secret("google_maps_api_key")
    provider = "Google Maps" if server_key else "OpenStreetMap"
    saved = it.location
    with box("step", "Step 0 · Locate the building", "location_on"):
        st.markdown("### Where is the building?")
        st.caption("Type its name or address, pick the right result and confirm it. The building keeps the full "
                   "address, its parts and the coordinates, with who confirmed them.")
        if saved:
            st.success(f"**{saved['address']}** · {saved['lat']:.5f}, {saved['lng']:.5f} · confirmed by "
                       f"{saved['confirmed_by']} on {saved['confirmed_at']} · from {saved['provider']}",
                       icon=":material/where_to_vote:")
    left, right = st.columns([1, 1.25], gap="medium")
    with left, box("loc_form", "Find it" if not saved else "Change the location", "search"):
        st.session_state.setdefault("ab_loc_query", it.s.get("address") or it.name)
        with st.form("ab_locate", border=False):
            query = st.text_input("Building name or address", key="ab_loc_query")
            who = st.text_input("Your name", key="ab_loc_who", help="Recorded with the location you confirm.")
            search = st.form_submit_button("Search", icon=":material/search:")
        st.caption(f"The text you search for is sent to {provider}. Nothing else leaves the app.")
        if search and query.strip():
            try:
                st.session_state["ab_loc_results"] = get_geocoder(server_key).search(query.strip())
            except LocateError as e:
                st.session_state["ab_loc_results"] = []
                st.error(str(e))
        results = st.session_state.get("ab_loc_results")
        if results == []:
            st.warning("Nothing found. Try the street address with the city.")
        elif results:
            i = st.radio("Results", range(len(results)), key="ab_loc_pick",
                         format_func=lambda i: f"{results[i].address}  ({results[i].lat:.5f}, {results[i].lng:.5f})")
            if st.button("Use this location", type="primary", disabled=not who.strip(),
                         icon=":material/where_to_vote:", help=None if who.strip() else "Enter your name first."):
                it.set_location(location_dict(results[i]), who.strip())
                del st.session_state["ab_loc_results"]
                st.rerun()
    with right, box("loc_map", "Map", "map"):
        picked_ = st.session_state.get("ab_loc_results") or []
        shown = picked_[st.session_state.get("ab_loc_pick", 0) or 0] if picked_ else None
        lat, lng = (shown.lat, shown.lng) if shown else (saved["lat"], saved["lng"]) if saved else (None, None)
        if lat is None:
            st.caption("The map appears once the building is found.")
        else:
            site_map(lat, lng, it.name, 460)
        if shown:
            st.caption("Preview of the selected result. It is saved only when you press **Use this location**.")


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
    st.session_state.update(ab_know="Note", ab_note_target=target, ab_note_topic=topic, ab_note_q=question)


def knowledge_step() -> None:
    with box("step", f"Step {FLOW[-1][1]} · Add knowledge", "psychology"):
        st.markdown("### What people know that no document says")
        st.caption("Tribal knowledge from the engineers, operators and contractors: notes about the building, a unit "
                   "or a room, and rules that teach the reader this job's names. Every entry becomes part of the "
                   "knowledge graph, with who said it, and travels with it. Rules also re-read the documents.")
        c = st.columns(4)
        c[0].metric("Notes", len(kn["notes"]), border=True)
        c[1].metric("Tag rules", len(kn["tags"]), border=True)
        c[2].metric("Point terms", len(kn["terms"]), border=True)
        c[3].metric("Units with a note", sum(1 for k in knowledge.notes_for(it) if k.startswith("unit:")), border=True)
    with box("prompts", "Questions to ask the people who know it", "forum"):
        st.caption("Drawn from what the graph holds. **Answer** opens the note form below, about the right thing.")
        for k, (target, topic, q) in enumerate(prompts()):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(f":material/help: {q}")
                st.space("stretch")
                st.button("Answer", key=f"prompt_{k}", type="tertiary", icon=":material/edit_note:",
                          on_click=ask_prompt, args=(target, topic, q))
    with box("know", "Add to the graph", "add_circle"):
        knowledge_view()


# ---------------------------------------------------------------- the document steps

def read_now(files: list[tuple[str, bytes]]) -> None:
    for name, data in files:
        it.add_file(step_id, name, data)
    with st.status(f"Reading {', '.join(n for n, _ in files) or 'the documents'}…", expanded=True) as status_box:
        n = steps.run(it, step_id, lambda m: status_box.write(m))
        status_box.update(label=f"Read: {n} facts", state="complete", expanded=False)
    st.session_state.update(ab_sel=None, ab_qpage=0, ab_nonce=st.session_state.get("ab_nonce", 0) + 1)
    st.toast(f"{step.title}: read", icon=":material/check_circle:")
    st.rerun()


def work_tabs(tabs: dict[str, str], default: str) -> str:
    if want := st.session_state.pop("ab_work_want", None):
        st.session_state["ab_work"] = want
    if st.session_state.get("ab_work") not in tabs:
        st.session_state["ab_work"] = default
    return st.segmented_control("Work", list(tabs), format_func=tabs.get, key="ab_work",
                                label_visibility="collapsed") or default


def review_step() -> None:
    live_eq = list(b["equip"].values())
    pts = b["points"]
    all_facts = it.facts()
    conf = sum(1 for f in all_facts if f["status"] == "confirmed")
    with box("step"), st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"### 6 · Review: {it.name}", width="content")
        for label, value, delta in [
                ("Floors", len(b["floors"]), None), ("Rooms", len(b["rooms"]), None),
                ("Equipment", len(live_eq), f"{sum(1 for e in live_eq if e['room'])} placed"),
                ("Points", len(pts), f"{sum(1 for p in pts if p['status'] == 'confirmed')} confirmed"),
                ("Facts confirmed", f"{round(100 * conf / max(1, len(all_facts)))}%",
                 f"{len(it.open_questions())} questions open")]:
            st.metric(label, value, delta, border=True, delta_color="off" if label == "Facts confirmed" else "normal",
                      width="content")
        st.space("stretch")
        nav(short=True)
    main = layout()
    with main:
        with box("work"):
            nq = len(it.open_questions())
            if work_tabs({"ask": f"Open questions ({nq})", "doc": "Document"}, "ask") == "doc":
                viewer([f["name"] for fs in it.s["files"].values() for f in fs])
            else:
                questions([s.id for s in STEPS[:-1]])
        proposed = [f for f in all_facts if f["status"] == "proposed" and not f.get("ask")]
        if proposed:
            with box("proposed", "Proposed, waiting for a second source", "hourglass_top"):
                st.caption(f"{len(proposed)} facts nobody contradicted but no second document confirmed either "
                           f"({', '.join(sorted({KIND_NAME.get(f['kind'], f['kind']) for f in proposed}))}).")
                if st.button(f"Confirm these {len(proposed)}", icon=":material/done_all:"):
                    for f in proposed:
                        it.s["decisions"][f["id"]] = {"status": "confirmed", "value": None, "field": None, "at": 0}
                    it.save()
                    st.rerun()
        keys = score.answer_keys()
        with box("score", "Score and export", "analytics"):
            if keys:
                default = next((k for k in keys if k.split("_")[0] in it.slug), None)
                key = st.selectbox("Answer key", ["(none)"] + keys, index=(keys.index(default) + 1) if default else 0,
                                   help="Test buildings only. The readers never see the answer key; it is used here "
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


def document_step() -> None:
    files = it.files(step_id)
    with box("step"):
        head, load = st.columns([1, 1.15], gap="medium", vertical_alignment="center")
        with head:
            st.markdown(f"### {step.n} · {step.ask}")
            st.caption(f"**Builds:** {step.builds}", help=f"Looks for: {step.looks_for}")
        with load, st.container(horizontal=True, vertical_alignment="center", gap="small"):
            up = st.file_uploader(step.ask, type=list(step.types), accept_multiple_files=True,
                                  key=f"up_{step_id}_{st.session_state.get('ab_nonce', 0)}",
                                  label_visibility="collapsed")
            test = TEST_PACKAGE / step.test_file
            use_test = (test.exists() and not any(f["name"] == step.test_file for f in files)
                        and st.button(f"Use the test file ({step.test_file})", icon=":material/science:",
                                      type="tertiary"))
            nav(short=True)
        reread = False
        if files:
            with load, st.container(horizontal=True, vertical_alignment="center", gap="small"):
                for f in files:
                    st.badge(f"{f['name']} · {f['size'] / 1e6:.1f} MB", icon=":material/description:", color="gray")
                reread = st.button("Read again", icon=":material/refresh:", type="tertiary",
                                   help="Reads the files again with what the earlier steps know now. Your answers "
                                        "are kept.")
                with st.popover("Remove a file", icon=":material/delete:"):
                    for f in files:
                        if st.button(f"Remove {f['name']}", key=f"rm_{f['sha256'][:8]}"):
                            it.remove_file(step_id, f["name"])
                            steps.run(it, step_id, lambda m: None)
                            st.rerun()
        # Reading runs here, below the upload row, so its live log has the box's width.
        if up:
            read_now([(u.name, u.getvalue()) for u in up])
        elif use_test:
            read_now([(test.name, test.read_bytes())])
        elif reread:
            read_now([])
        if files and (stale := steps.stale(it, step_id)):
            st.warning(f"{', '.join(stale)} changed since this step was read. **Read again** to use the latest.",
                       icon=":material/sync_problem:")

    names_here = [f["name"] for f in files]
    main = layout()
    with main, box("work"):
        nq = len(it.open_questions(step_id))
        tabs = {"doc": "Document", "ask": f"Needs you ({nq})", "built": "What was read", "log": "Reading log"}
        work = work_tabs(tabs, "ask" if nq else "doc")
        if work == "doc":
            if it.done(step_id) or st.session_state["ab_sel"]:
                viewer(names_here)
            else:
                st.info("Nothing read yet for this step. Upload the document above"
                        + (" or use the test file." if (TEST_PACKAGE / step.test_file).exists() else "."),
                        icon=":material/upload_file:")
                if needs := [steps.BY_ID[n] for n in step.needs if not it.done(n)]:
                    st.caption("Works best after: " + ", ".join(f"step {n.n} ({n.title.lower()})" for n in needs)
                               + ".")
        elif work == "ask":
            located = {"placement", "room", "room_check"}
            on_plan = sum(1 for f in it.open_questions(step_id) if f["kind"] in located)
            how = st.segmented_control("How", ["List", "On the building"], default="List", key="ab_ask_how",
                                       label_visibility="collapsed") or "List"
            if how == "List":
                questions([step_id])
            else:
                st.caption(f"{on_plan} of this step's {nq} questions have a place on a plan: they pulse in amber. "
                           "Hover one to answer it there, or step through them with the arrows in the viewer (or "
                           "the N key). The others (controllers, checks) are in the list.")
                twin_view(FIT, only_ask=True, key="ab_twin_ask", panel=False)
        elif work == "built":
            if it.done(step_id):
                built_tables([step_id])
            else:
                st.caption("Nothing read yet for this step.")
        else:
            for line in it.log(step_id) or ["Nothing read yet for this step."]:
                st.markdown(("- " if not line.startswith("  ") else "    - ") + line.strip())


if step_id == "locate":
    main = layout()
    with main:
        locate_step()
elif step_id == "knowledge":
    main = layout()
    with main:
        knowledge_step()
elif step_id == "review":
    review_step()
else:
    document_step()
if step_id in ("locate", "knowledge"):
    footer()
