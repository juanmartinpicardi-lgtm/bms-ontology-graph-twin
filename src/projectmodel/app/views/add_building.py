"""Add a building: a guided setup from its documents, one step at a time.

Each step asks for one kind of document. When it arrives the reader runs in front of you, page by page, and what it
built appears next to the document: the PDF on the left with every fact it read outlined, the building on the right
in 3D, growing step by step. What the reader is not sure about is asked, one question at a time, with the place on
the page it came from. Answers are kept (method = human) and survive a re-read.

The readers are rules (src/projectmodel/intake), no LLM. The test package in test_packages/troop_d/ has one file per
step.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.intake import pdfdoc, score, steps, twin  # noqa: E402
from projectmodel.intake.model import building, missing, progress  # noqa: E402
from projectmodel.intake.state import Intake, list_intakes  # noqa: E402
from projectmodel.intake.steps import STEPS, TEST_PACKAGE  # noqa: E402

STATUS_COLOR = {"confirmed": "#3CB371", "proposed": "#4DA3E8", "ask": "#F0A030", "rejected": "#D9534F"}
KIND_NAME = {"floor": "Floors", "room": "Rooms", "placement": "Where units are", "equipment": "Equipment",
             "relation": "Connections", "sequence": "Sequences", "issue": "Checks", "controller": "Controllers",
             "point": "Points", "room_check": "Room schedule check", "alias": "BMS devices", "bms_object": "BMS objects"}
PER_PAGE = 6

st.html("""<style>
.st-key-ab_steps button p { font-size: .86rem; }
[class*="st-key-q_"] { border-left: 3px solid #F0A030 !important; }
</style>""")


# ---------------------------------------------------------------- building picker

def start_form(key: str, compact: bool = False) -> None:
    with st.form(key, border=not compact):
        if not compact:
            st.markdown("#### Start a new building")
            st.caption("Give it a name. Then upload its documents one step at a time; each one adds to the building.")
        name = st.text_input("Building name", placeholder="e.g. Troop D Crime Lab")
        address = st.text_input("Address (optional)", placeholder="Street, city")
        if st.form_submit_button("Start", type="primary", icon=":material/arrow_forward:"):
            if not name.strip():
                st.error("A name is needed.")
            else:
                it = Intake.create(name.strip(), address.strip())
                st.session_state.update(ab_slug=it.slug, ab_step="plans", ab_sel=None)
                st.rerun()


existing = list_intakes()
if not existing:
    st.markdown("### Add a building from its documents")
    st.write("Six steps: floor plans, equipment schedules, sequences, controls submittal, BMS export, review. Each "
             "document you upload is read in front of you and turned into part of the building: floors and rooms, "
             "units in them, their controllers and points. You confirm what the reader is not sure about.")
    st.info(f"To try it end to end, use the test package: one file per step in `{TEST_PACKAGE.relative_to(ROOT)}/`.",
            icon=":material/science:")
    start_form("ab_new")
    st.stop()

slugs = [s["slug"] for s in existing]
if st.session_state.get("ab_slug") not in slugs:
    st.session_state["ab_slug"] = slugs[0]
names = {s["slug"]: s["name"] for s in existing}
it = Intake(st.session_state["ab_slug"])
step_id = st.session_state.setdefault("ab_step", "plans")
step = steps.BY_ID[step_id]
st.session_state.setdefault("ab_sel", None)


def go(to: str) -> None:
    st.session_state.update(ab_step=to, ab_sel=None, ab_qpage=0)


def select(fid: str | None) -> None:
    st.session_state["ab_sel"] = fid


# ---------------------------------------------------------------- header: building, progress, steps

prog = progress(it)
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    st.selectbox("Building", slugs, key="ab_slug", format_func=lambda s: names[s], label_visibility="collapsed",
                 width=260, on_change=lambda: st.session_state.update(ab_sel=None))
    with st.popover("New building", icon=":material/add:"):
        start_form("ab_new_pop", compact=True)
    st.progress(prog["share"], text=f"**{round(prog['share'] * 100)}% built** · "
                                    f"{sum(1 for s in prog['steps'].values() if s['read'])} of 5 documents read · "
                                    f"{sum(s['open'] for s in prog['steps'].values())} questions open")

with st.container(horizontal=True, gap="small", key="ab_steps"):
    for s in STEPS:
        p = prog["steps"].get(s.id)
        if s.id == "review":
            icon = ":material/fact_check:"
        elif not p["read"]:
            icon = ":material/radio_button_unchecked:"
        elif p["open"]:
            icon = ":material/pending:"
        else:
            icon = ":material/check_circle:"
        label = f"{s.n} · {s.title}" + (f" ({p['open']})" if p and p["open"] else "")
        st.button(label, key=f"ab_go_{s.id}", icon=icon, on_click=go, args=(s.id,),
                  type="primary" if s.id == step_id else "secondary")

b = building(it)
gaps = missing(it, b)
with st.expander(f"What is missing · {len(gaps)}", icon=":material/checklist:", expanded=False):
    if not gaps:
        st.write("Nothing: every document is read and every question answered.")
    for sid, kind, text in gaps:
        icon = {"todo": ":material/upload_file:", "ask": ":material/help:", "gap": ":material/report:"}[kind]
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown(f"{icon} {text}")
            st.button(f"Go to step {steps.BY_ID[sid].n}", key=f"gap_{sid}_{kind}_{hash(text)}", on_click=go,
                      args=(sid,), type="tertiary")


# ---------------------------------------------------------------- shared pieces

@st.cache_data(show_spinner=False, max_entries=24)
def plate(path: str, page: int, crop: tuple | None, sha: str) -> str:  # sha: a new upload refreshes it
    return twin.plate_image(Path(path), page, list(crop) if crop else None)


def file_sha(name: str) -> str:
    return next((f["sha256"] for fs in it.s["files"].values() for f in fs if f["name"] == name), "")


def twin_view(height: int = 620) -> None:
    images = {}
    for f in b["floors"]:
        path = it.file_by_name(f["file"])
        if path and f["crop"]:
            images[f["id"]] = plate(str(path), f["page"], tuple(f["crop"]), file_sha(f["file"]))
    needs = {f["id"] for f in it.open_questions()}
    st.iframe(twin.render(twin.payload(b, images, st.session_state["ab_sel"], needs), height), height=height)


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


def question_card(f: dict, i: int) -> None:
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
                typed = st.text_input("Room name", key=f"name_{f['id']}", placeholder="Name from the plan",
                                      label_visibility="collapsed", width=260)
                st.button("Save name", key=f"savename_{i}", disabled=not typed,
                          on_click=lambda f=f, k=f"name_{f['id']}": it.decide(f["id"], "fixed",
                                                                              st.session_state[k].title(), "name"))
        with st.container(horizontal=True, gap="small"):
            st.button("Show", key=f"show_{i}", icon=":material/visibility:", on_click=select, args=(f["id"],),
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


# ---------------------------------------------------------------- one step

def read_now(files: list[tuple[str, bytes]]) -> None:
    for name, data in files:
        it.add_file(step_id, name, data)
    with st.status(f"Reading {', '.join(n for n, _ in files) or 'the documents'}…", expanded=True) as box:
        n = steps.run(it, step_id, lambda m: box.write(m))
        box.update(label=f"Read: {n} facts", state="complete", expanded=False)
    st.session_state.update(ab_sel=None, ab_qpage=0, ab_nonce=st.session_state.get("ab_nonce", 0) + 1)
    st.toast(f"{step.title}: read", icon=":material/check_circle:")
    st.rerun()


if step_id == "review":
    st.markdown(f"### 6 · Review: {it.name}")
    live_eq = list(b["equip"].values())
    pts = b["points"]
    cols = st.columns(5)
    cols[0].metric("Floors", len(b["floors"]), border=True)
    cols[1].metric("Rooms", len(b["rooms"]), border=True)
    cols[2].metric("Equipment", len(live_eq), f"{sum(1 for e in live_eq if e['room'])} placed", border=True)
    cols[3].metric("Points", len(pts), f"{sum(1 for p in pts if p['status'] == 'confirmed')} confirmed", border=True)
    all_facts = it.facts()
    conf = sum(1 for f in all_facts if f["status"] == "confirmed")
    cols[4].metric("Facts confirmed", f"{round(100 * conf / max(1, len(all_facts)))}%",
                   f"{len(it.open_questions())} questions open", border=True, delta_color="off")
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown("##### Open questions, all steps")
        questions([s.id for s in STEPS[:-1]])
        proposed = [f for f in all_facts if f["status"] == "proposed" and not f.get("ask")]
        if proposed:
            st.markdown("##### Proposed, waiting for a second source")
            st.caption(f"{len(proposed)} facts nobody contradicted but no second document confirmed either "
                       f"({', '.join(sorted({KIND_NAME.get(f['kind'], f['kind']) for f in proposed}))}).")
            if st.button(f"Confirm these {len(proposed)}", icon=":material/done_all:"):
                for f in proposed:
                    it.s["decisions"][f["id"]] = {"status": "confirmed", "value": None, "field": None, "at": 0}
                it.save()
                st.rerun()
    with right:
        st.markdown("##### The building")
        twin_view(560)
        keys = score.answer_keys()
        if keys:
            st.markdown("##### Score against an answer key")
            default = next((k for k in keys if k.split("_")[0] in it.slug), None)
            key = st.selectbox("Answer key", ["(none)"] + keys, index=(keys.index(default) + 1) if default else 0,
                               help="Test buildings only. The readers never see the answer key; it is used here to "
                                    "measure them, before and after your answers.")
            if key != "(none)":
                rows = score.score(it, key)
                df = pd.DataFrame(rows)
                df["machine %"] = (df["machine"] / df["out of"].clip(lower=1) * 100).round(0)
                df["with you %"] = (df["with you"] / df["out of"].clip(lower=1) * 100).round(0)
                st.dataframe(df[["measure", "machine", "with you", "out of", "machine %", "with you %", "what"]],
                             hide_index=True)
        graph = {"building": it.name, "facts": all_facts}
        st.download_button("Download the knowledge graph (JSON, with provenance)", json.dumps(graph, indent=1),
                           file_name=f"{it.slug}_graph.json", icon=":material/download:")
    st.stop()

st.markdown(f"### Step {step.n} · {step.ask}")
st.caption(f"**Builds:** {step.builds}  \n**Looks for:** {step.looks_for}")

files = it.files(step_id)
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    up = st.file_uploader(step.ask, type=list(step.types), accept_multiple_files=True,
                          key=f"up_{step_id}_{st.session_state.get('ab_nonce', 0)}", label_visibility="collapsed")
    test = TEST_PACKAGE / step.test_file
    use_test = (test.exists() and not any(f["name"] == step.test_file for f in files)
                and st.button(f"Use the test file ({step.test_file})", icon=":material/science:", type="tertiary"))
reread = False
if files:
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        for f in files:
            st.badge(f"{f['name']} · {f['size'] / 1e6:.1f} MB", icon=":material/description:", color="gray")
        reread = st.button("Read again", icon=":material/refresh:", type="tertiary",
                           help="Reads the files again with what the earlier steps know now. Your answers are kept.")
        with st.popover("Remove a file", icon=":material/delete:"):
            for f in files:
                if st.button(f"Remove {f['name']}", key=f"rm_{f['sha256'][:8]}"):
                    it.remove_file(step_id, f["name"])
                    steps.run(it, step_id, lambda m: None)
                    st.rerun()
# Reading runs here, below the upload row, so its live log has the page width.
if up:
    read_now([(u.name, u.getvalue()) for u in up])
elif use_test:
    read_now([(test.name, test.read_bytes())])
elif reread:
    read_now([])
if files:
    if stale := steps.stale(it, step_id):
        st.warning(f"{', '.join(stale)} changed since this step was read. **Read again** to use the latest.",
                   icon=":material/sync_problem:")

if not it.done(step_id):
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.info("Nothing read yet for this step. Upload the document above"
                + (" or use the test file." if (TEST_PACKAGE / step.test_file).exists() else "."),
                icon=":material/upload_file:")
        if needs := [steps.BY_ID[n] for n in step.needs if not it.done(n)]:
            st.caption("Works best after: " + ", ".join(f"step {n.n} ({n.title.lower()})" for n in needs) + ".")
    with right:
        st.markdown("##### The building so far")
        twin_view()
else:
    names_here = [f["name"] for f in files]
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        viewer(names_here)
    with right:
        nq = len(it.open_questions(step_id))
        views = {"twin": "Building", "ask": f"Needs you ({nq})", "built": "What was read", "log": "Reading log"}
        view = st.segmented_control("View", list(views), format_func=views.get, key="ab_view", default="twin",
                                    label_visibility="collapsed") or "twin"
        if view == "twin":
            twin_view()
        elif view == "ask":
            questions([step_id])
        elif view == "built":
            built_tables([step_id])
        else:
            for line in it.log(step_id):
                st.markdown(("- " if not line.startswith("  ") else "    - ") + line.strip())

st.divider()
with st.container(horizontal=True, gap="small"):
    i = [s.id for s in STEPS].index(step_id)
    if i > 0:
        st.button(f"Back: {STEPS[i - 1].title}", icon=":material/arrow_back:", on_click=go, args=(STEPS[i - 1].id,))
    st.space("stretch")
    nxt = STEPS[i + 1]
    st.button(f"Next: {nxt.ask.lower() if nxt.id != 'review' else 'review'}", icon=":material/arrow_forward:",
              type="primary", on_click=go, args=(nxt.id,))
