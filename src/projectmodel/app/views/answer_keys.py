"""Answer keys: an engineer writes the answers the plan reader and the sequence reader are scored against.

Until now an AI agent wrote both keys (data/ground_truth/<set>/plans.yaml, sequences.yaml). This page is where a person
does it, on a fixed, seeded sample of each set that fits 1 to 2 hours (answer_keys.py, data/ground_truth/
answer_key_sample.yaml): plan sheets (which tag is in or serves which room) and sequences (which control relations each
section states). Blind: the reader's answer and the agent key are never shown while an item is open. After an item is
marked done the engineer may reveal the reader's answer; that is recorded. The key is saved to new files
(plans.human.yaml, sequences.human.yaml); scripts/eval.py then reports the readers against both keys.

Makes no model call. Guide: docs/answer-key-guide.md. The held-out set (liberty_boe) is never offered.
"""

import io
import re
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import answer_keys as ak  # noqa: E402
from projectmodel.app.shell import box  # noqa: E402

SET_TEXT = {
    "msu_mbb": "msu_mbb · Montana State University, lab and office renovation (plan sheets M201–M203)",
    "itd_d1_lab": "itd_d1_lab · Idaho DOT testing laboratory (plan sheets M1.0–M2.0)",
    "troop_d": "troop_d · Troop D, sheet M-304 (sequences of operation)",
}
FLOORS = ["L1", "L2", "L3", "L4", "B1", "RF"]
RELS = ["drives", "feedback", "requires", "requests", "resets", "switches"]
REL_HELP = {
    "drives": "a setpoint drives an output (loop)", "feedback": "a measurement feeds back to an output (loop)",
    "requires": "the first is a condition the second needs (interlock, enable, safety)",
    "requests": "a point asks equipment to run (ends on a unit: row)",
    "resets": "the first moves the second's setpoint", "switches": "a mode or schedule changes the second's operation",
}
REL_KIND = {"drives": "loop", "feedback": "loop", "requires": "interlock", "requests": "interlock",
            "resets": "reset", "switches": "mode"}
ICON = {"done": "✅", "draft": "✏️", "todo": "⬜"}


# the documents -----------------------------------------------------------------------------------------------------

@st.cache_data(show_spinner="Reading the sheet's text…")
def sheet_cands(site: str, page: int) -> dict:
    """The tags and room labels on one keyed sheet, as the plan reader's candidates find them in the PDF's text."""
    from projectmodel.intake import pdfdoc, plan_ai
    pdf = ak.plan_file(site)
    ws = pdfdoc.words(pdf, page - 1)
    pc = plan_ai.candidates(ws, page - 1, pdfdoc.page_size(pdf, page - 1))
    rooms: dict[str, str] = {}
    for c in pc.rooms.values():
        name = ak.room_hint(c)
        if name and c["text"] not in rooms:
            rooms[c["text"]] = name
    return {"rooms": rooms, "tags": {t["text"]: [o["bbox"] for o in t["occ"]] for t in pc.tags.values()},
            "titles": pc.titles, "size": pc.size}


@st.cache_data(show_spinner="Drawing the sheet…", max_entries=48)
def sheet_png(site: str, page: int, region: tuple | None, boxes: tuple, width: int) -> bytes:
    """The sheet (or `region` of it, in PDF points from the top left), `width` pixels wide, with `boxes` outlined."""
    import pypdfium2 as pdfium

    pg = pdfium.PdfDocument(ak.plan_file(site))[page - 1]
    return render_png(pg, region, boxes, width)


def render_png(pg, region: tuple | None, boxes: tuple, width: int) -> bytes:
    from PIL import ImageDraw

    w, h = pg.get_size()
    x0, y0, x1, y1 = region or (0, 0, w, h)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    scale = width / (x1 - x0)
    img = pg.render(scale=scale, crop=(x0, h - y1, w - x1, y0)).to_pil().convert("RGB")
    draw = ImageDraw.Draw(img)
    for b in boxes:
        r = [(b[0] - x0) * scale - 4, (b[1] - y0) * scale - 4, (b[2] - x0) * scale + 4, (b[3] - y0) * scale + 4]
        draw.rectangle(r, outline=(220, 40, 40), width=3)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


@st.cache_resource(show_spinner="Reading the sequences the way the setup does (about 10 seconds)…")
def seq_questions(site: str):
    from projectmodel.scoring import eval as ev
    return ev._cache(("seqq", site), lambda: ev.sequence_read_questions(site))


@st.cache_data(show_spinner="Drawing the section…", max_entries=32)
def section_png(file: str, page: int, bbox: tuple) -> bytes:
    import pypdfium2 as pdfium
    pg = pdfium.PdfDocument(ak.ROOT / "test_packages/troop_d" / file)[page - 1]
    pad = 12
    return render_png(pg, (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad), (), 1300)


@st.cache_resource(show_spinner="Reading the sheets with the rules (about 15 seconds)…")
def plan_readers(site: str, tag: str) -> list[str]:
    return ak.plan_reader_answers(site, tag)


# state -------------------------------------------------------------------------------------------------------------

def status_of(data: dict, item_id: str) -> str:
    return next((i.get("status", "draft") for i in data["items"] if i["id"] == item_id), "todo")


def record_of(data: dict, item_id: str) -> dict:
    return next((i for i in data["items"] if i["id"] == item_id), {})


def split_room(label: str) -> tuple[str, str]:
    """'154 · LAB' -> ('154', 'LAB'); a typed '154' or '154 lab' -> the number and what follows it."""
    m = re.match(r"^\s*([A-Za-z]?\d{2,4}[A-Za-z]?)\b[\s·:-]*(.*)$", label)
    return (m.group(1).upper(), m.group(2).strip()) if m else (label.strip(), "")


def tick(item_id: str) -> None:
    """The clock for the open item: starts when it opens in this session, and restarts after each save."""
    c = st.session_state.get("ak_clock")
    if not c or c["id"] != item_id:
        st.session_state["ak_clock"] = {"id": item_id, "since": time.time()}


def add_time(rec: dict) -> dict:
    c = st.session_state.get("ak_clock")
    if c and c["id"] == rec["id"]:
        ak.add_minutes(rec, c["since"], time.time())
        c["since"] = time.time()
    return rec


def save_item(job: str, site: str, item: dict, status: str, build) -> None:
    """Callback of Save / Mark done: build the record from the widgets, check it when done, write the key file."""
    data = ak.load(job, site)
    old = record_of(data, item["id"])
    rec, problem = build(item, old, status)
    st.session_state["ak_msg"] = (item["id"], "error" if problem else "ok", problem or
                                  ("Marked done." if status == "done" else "Draft saved."))
    if problem:
        return
    rec["status"] = status
    if old.get("revealed") and st.session_state.get(f"ak_{item['id']}_unlock"):
        rec["edited_after_reveal"] = True
    add_time(rec)
    data["engineer"] = st.session_state.get("ak_engineer", data.get("engineer", ""))
    data["file"] = data.get("file") or (ak.plan_file(site).name if job == "plans" else item.get("file", ""))
    ak.save(job, site, ak.upsert(data, rec))


def reveal_item(job: str, site: str, item_id: str) -> None:
    data = ak.load(job, site)
    rec = record_of(data, item_id)
    if rec.get("status") == "done":
        rec["revealed"] = True
        ak.save(job, site, ak.upsert(data, rec))


def go_next(job: str, site: str, ids: list[str]) -> None:
    data = ak.load(job, site)
    cur = st.session_state.get(f"ak_cur_{site}")
    order = ids[ids.index(cur) + 1:] + ids[:ids.index(cur)] if cur in ids else ids
    nxt = next((i for i in order if status_of(data, i) != "done"), None)
    if nxt:
        st.session_state[f"ak_cur_{site}"] = nxt


def add_extra_tag(site: str, sheets: dict, data_ids: list[str]) -> None:
    sheet = st.session_state.get("ak_extra_sheet")
    tag = (st.session_state.get("ak_extra_tag") or "").strip()
    if not sheet or not tag:
        return
    data = ak.load("plans", site)
    iid = ak.item_id("plans", sheet, tag)
    if iid not in data_ids:
        ak.save("plans", site, ak.upsert(data, {"id": iid, "sheet": sheet, "page": sheets[sheet], "tag": tag,
                                                "status": "draft", "extra": True, "answer": None, "minutes": 0.0}))
    st.session_state[f"ak_cur_{site}"] = iid
    st.session_state["ak_extra_tag"] = ""


# plan sheets -------------------------------------------------------------------------------------------------------

def build_plan(item: dict, old: dict, status: str) -> tuple[dict, str | None]:
    k = lambda n: st.session_state.get(f"ak_{item['id']}_{n}")  # noqa: E731
    ans = k("answer")
    nums, names = [], {}
    for lab in k("rooms") or []:
        num, name = split_room(lab)
        nums.append(num)
        if name:
            names[num] = name
    for num in (k("more_rooms") or "").replace(";", ",").split(","):
        if num.strip() and num.strip().upper() not in nums:
            nums.append(num.strip().upper())
    rec = {**old, "id": item["id"], "sheet": item["sheet"], "page": item["page"], "tag": item["tag"],
           "answer": ans, "floor": (k("floor") or ("RF" if ans == "roof" else "")) if ans in ("here", "roof") else "",
           "rooms": nums if ans == "here" else [], "room_names": names if ans == "here" else {},
           "rel": k("rel") or "serves", "note": (k("note") or "").strip(), "extra": bool(item.get("extra")),
           "source_page": int(k("source_page") or item["page"])}
    if status == "done":
        if not ans:
            return rec, "Pick what this tag is on this sheet."
        if ans == "here" and not rec["floor"]:
            return rec, "Pick the floor."
        if ans == "here" and not nums:
            return rec, "Pick at least one room, or choose 'a unit in no room' if it sits in none."
    return rec, None


def plan_item(site: str, item: dict, data: dict, job: str) -> None:
    rec = record_of(data, item["id"])
    sheet = sheet_cands(site, item["page"])
    iid = item["id"]
    k = lambda n: f"ak_{iid}_{n}"  # noqa: E731
    locked = bool(rec.get("revealed")) and not st.session_state.get(k("unlock"))
    left, right = st.columns([3, 2], gap="large")
    with left:
        occ = sheet["tags"].get(item["tag"], [])
        modes = ["Near the tag", "Wider", "Whole sheet"]
        c1, c2 = st.columns([3, 2])
        mode = c1.segmented_control("View", modes, default=modes[0], key="ak_view", label_visibility="collapsed")
        n = 1
        if len(occ) > 1:
            n = c2.selectbox("Where on the sheet", range(1, len(occ) + 1), key=f"ak_occ_{iid}",
                             format_func=lambda i: f"{item['tag']} drawn {len(occ)} times: #{i}")
        w, h = sheet["size"]
        if mode == "Whole sheet" or not occ:
            png = sheet_png(site, item["page"], None, tuple(map(tuple, occ)), 2600)
        else:
            x0, y0, x1, y1 = occ[n - 1]
            m = 230 if mode == "Near the tag" else 650
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            png = sheet_png(site, item["page"], (cx - m * 1.3, cy - m, cx + m * 1.3, cy + m), (tuple(occ[n - 1]),),
                            1500)
        st.image(png, width="stretch")
        st.caption(f"Sheet {item['sheet']} (PDF page {item['page']}); the tag is outlined in red. "
                   + (f"Views printed on it: {'; '.join(sheet['titles'])}. " if sheet["titles"] else "")
                   + "Hover the image for full screen.")
        if not occ:
            st.warning("This tag's position was not found in the text layer; use the whole sheet.")
    with right:
        st.subheader(f"{item['tag']} on {item['sheet']}", anchor=False)
        st.caption("Where is this unit, and which room does it serve or sit in? Use the drawing, and the schedule "
                   "sheets if the plan doesn't say.")
        old_ans = rec.get("answer")
        st.radio("What is it on this sheet?", ak.PLAN_ANSWERS, key=k("answer"), disabled=locked,
                 format_func=ak.PLAN_ANSWER_TEXT.get, index=ak.PLAN_ANSWERS.index(old_ans) if old_ans else None)
        ans = st.session_state.get(k("answer"))
        if ans in ("here", "roof"):
            st.selectbox("Floor", FLOORS, key=k("floor"), disabled=locked, accept_new_options=True,
                         index=(FLOORS.index(rec["floor"]) if rec.get("floor") in FLOORS else
                                (FLOORS.index("RF") if ans == "roof" else None)),
                         help="The floor of the view the unit is drawn in. Type one if it's not in the list.")
        if ans == "here":
            opts = [f"{num} · {name}" for num, name in sorted(sheet["rooms"].items())]
            saved = [f"{r} · {rec['room_names'][r]}" if r in (rec.get("room_names") or {}) else r
                     for r in rec.get("rooms") or []]
            opts += [s for s in saved if s not in opts]
            st.multiselect("Room(s) it serves or sits in", opts, default=saved, key=k("rooms"), disabled=locked,
                           accept_new_options=True, placeholder="Pick from the labels printed on this sheet…",
                           help="Pick every room that is right (a unit between two rooms: both). Type a number the "
                                "list doesn't have.")
            st.radio("The unit…", list(ak.REL_TEXT), key=k("rel"), disabled=locked, horizontal=False,
                     format_func=ak.REL_TEXT.get, index=list(ak.REL_TEXT).index(rec.get("rel") or "serves"))
        if ans:
            st.number_input("Source page (change it if the answer came from another sheet, say a schedule)",
                            min_value=1, value=int(rec.get("source_page") or item["page"]), key=k("source_page"),
                            disabled=locked)
            st.text_input("Note (optional)", value=rec.get("note", ""), key=k("note"), disabled=locked)
        item_buttons(job, site, item, rec, build_plan, locked, k)


def item_buttons(job: str, site: str, item: dict, rec: dict, build, locked: bool, k) -> None:
    ids = [i["id"] for i in st.session_state["ak_ids"]]
    msg = st.session_state.get("ak_msg")
    with st.container(horizontal=True, gap="small"):  # wraps on a narrow column instead of cutting the labels
        st.button("Save draft", key=k("sd"), disabled=locked, on_click=save_item,
                  args=(job, site, item, "draft", build))
        st.button("Mark done", key=k("md"), type="primary", disabled=locked, on_click=save_item,
                  args=(job, site, item, "done", build))
        st.button("Next item ›", key=k("nx"), on_click=go_next, args=(job, site, ids), help="The next item not done yet")
    if msg and msg[0] == item["id"]:
        (st.error if msg[1] == "error" else st.success)(msg[2])
    if rec.get("status") == "done":
        reveal(job, site, item, rec, k)
    elif rec.get("minutes"):
        st.caption(f"{rec['minutes']:g} min so far on this item. Save or mark done to count your time.")


def reveal(job: str, site: str, item: dict, rec: dict, k) -> None:
    st.divider()
    st.caption(f"Done in {rec.get('minutes', 0):g} min. Optional: compare with the reader. Once you look, the item is "
               "marked as revealed and locked, so the key stays independent.")
    if not rec.get("revealed"):
        st.button("Show the reader's answer", key=k("rv"), on_click=reveal_item, args=(job, site, item["id"]))
        return
    st.checkbox("Change my answer anyway (the item is then marked 'edited after reveal')", key=k("unlock"))
    try:
        lines = (plan_readers(site, item["tag"]) if job == "plans"
                 else ak.sequence_reader_answers(site, item["sequence"], item["section"]))
    except Exception as e:  # noqa: BLE001 - the reader's answer is a convenience; the key is what matters
        lines = [f"The reader's answer isn't available here ({str(e)[:160]})."]
    for line in lines:
        st.markdown(f"- {line}")


# sequences ---------------------------------------------------------------------------------------------------------

def candidates_of(q) -> tuple[list[str], dict[str, str]]:
    """The ids a relation of this sequence may use, in the order a person looks for them, and their labels."""
    c = q.cands
    own = [p for p in c["points"].values() if p["own"]]
    other = [p for p in c["points"].values() if not p["own"]]
    ids, labels = [], {}
    for p in own:
        ids.append(p["id"])
        labels[p["id"]] = f"{p['id']} · {p['description']} ({p['io'] or '?'})"
    for r in c["roles"].values():
        ids.append(r["id"])
        labels[r["id"]] = f"{r['id']} · a point the units don't have yet"
    for u in c["units"]:
        ids.append(u)
        labels[u] = f"{u} · the equipment itself"
    for p in other:
        ids.append(p["id"])
        labels[p["id"]] = f"{p['id']} · {p['description']} ({p['io'] or '?'}, a related unit's)"
    return ids, labels


def build_seq(item: dict, old: dict, status: str) -> tuple[dict, str | None]:
    k = lambda n: st.session_state.get(f"ak_{item['id']}_{n}")  # noqa: E731
    rels = [dict(r) for r in st.session_state.get(f"ak_{item['id']}_rels", [])]
    rec = {**old, "id": item["id"], "sequence": item["sequence"], "section": item["section"], "title": item["title"],
           "none": bool(k("none")), "relations": [] if k("none") else rels,
           "gaps": [g.strip() for g in (k("gaps") or "").splitlines() if g.strip()], "note": (k("note") or "").strip(),
           "source": {"file": item["file"], "page": item["page"], "sheet": item["sheet"],
                      "section": f"{item['sequence']} {item['section']}"}}
    if status == "done" and not rec["none"] and not rels:
        return rec, "Add at least one relation, or tick 'This section states no control relation'."
    return rec, None


def add_relation(iid: str, labels: dict) -> None:
    a, rel, z = (st.session_state.get(f"ak_{iid}_{n}") for n in ("from", "rel", "to"))
    if not (a and rel and z):
        st.session_state["ak_msg"] = (iid, "error", "Pick both points and the relation.")
        return
    if a == z:
        st.session_state["ak_msg"] = (iid, "error", "A point can't act on itself.")
        return
    r = {"from": a, "rel": rel, "to": z, "kind": REL_KIND[rel], "loop": (st.session_state.get(f"ak_{iid}_loop") or "")
         .strip()}
    rels = st.session_state.setdefault(f"ak_{iid}_rels", [])
    if not any((x["from"], x["rel"], x["to"]) == (a, rel, z) for x in rels):
        rels.append(r)
    st.session_state["ak_msg"] = None


def drop_relation(iid: str, n: int) -> None:
    st.session_state[f"ak_{iid}_rels"].pop(n)


def seq_item(site: str, item: dict, data: dict, job: str) -> None:
    q = next(q for q in seq_questions(site) if q.seq["id"] == f"seq:{item['sequence']}")
    sec = next(s for s in q.cands["sections"] if s["letter"] == item["section"])
    rec = record_of(data, item["id"])
    iid = item["id"]
    k = lambda n: f"ak_{iid}_{n}"  # noqa: E731
    locked = bool(rec.get("revealed")) and not st.session_state.get(k("unlock"))
    ids, labels = candidates_of(q)
    if k("rels") not in st.session_state:
        st.session_state[k("rels")] = [dict(r) for r in rec.get("relations") or []]
    rels = st.session_state[k("rels")]
    left, right = st.columns([2, 3], gap="large")
    with left:
        st.subheader(f"{q.cands['title']} · section {sec['letter']}. {sec['title']}", anchor=False)
        st.markdown(" ".join(sec["text"].split()))
        st.caption(f"{item['file']}, sheet {item['sheet']}, page {item['page']}. Other sections of this sequence are "
                   "below; a relation may use any point listed in the picks.")
        with st.expander("Show the section on the drawing"):
            st.image(section_png(item["file"], item["page"], tuple(sec["bbox"])), width="stretch")
        with st.expander("All sections of this sequence"):
            for s in q.cands["sections"]:
                st.markdown(f"**{s['letter']}. {s['title']}** {' '.join(s['text'].split())}")
    with right:
        st.checkbox("This section states no control relation", value=bool(rec.get("none")), key=k("none"),
                    disabled=locked, help="A heading, a definition or a list of schedules: nothing acts on anything.")
        if not st.session_state.get(k("none")):
            st.markdown("**Relations this section states**")
            for n, r in enumerate(rels):
                a, b, c, d = st.columns([6, 2, 6, 1], vertical_alignment="center")
                a.markdown(f"`{r['from']}`")
                b.markdown(f"**{r['rel']}**")
                c.markdown(f"`{r['to']}`" + (f" · loop *{r['loop']}*" if r.get("loop") else ""))
                d.button("✕", key=k(f"rm{n}"), on_click=drop_relation, args=(iid, n), disabled=locked,
                         help="Remove this relation")
            if not rels:
                st.caption("None yet. Add each one below: the point it starts at, the relation, the point it ends at.")
            with st.container(border=True):
                st.selectbox("From", ids, index=None, key=k("from"), format_func=lambda i: labels.get(i, i),
                             accept_new_options=True, disabled=locked, placeholder="The point or condition…",
                             help="Type to search. A point the list doesn't have: type its name.")
                st.selectbox("Relation", RELS, index=None, key=k("rel"), format_func=lambda r: f"{r} · {REL_HELP[r]}",
                             disabled=locked)
                st.selectbox("To", ids, index=None, key=k("to"), format_func=lambda i: labels.get(i, i),
                             accept_new_options=True, disabled=locked, placeholder="The point that acts or is acted on…")
                if st.session_state.get(k("rel")) in ("drives", "feedback"):
                    st.text_input("Loop name (optional: pair a setpoint and its measurement)", key=k("loop"),
                                  disabled=locked, placeholder="e.g. Duct static pressure")
                st.button("Add relation", key=k("add"), on_click=add_relation, args=(iid, labels), disabled=locked)
        st.text_area("Gaps: something this section needs that the points don't have (one per line, optional)",
                     value="\n".join(rec.get("gaps") or []), key=k("gaps"), disabled=locked, height=80)
        st.text_input("Note (optional)", value=rec.get("note", ""), key=k("note"), disabled=locked)
        item_buttons(job, site, item, rec, build_seq, locked, k)


# the page ----------------------------------------------------------------------------------------------------------

def get_drawing(site: str) -> bool:
    """The set's drawing PDF is not on this computer (it is not in git; on the hosted app, never): offer to fetch the
    public bid set it was keyed on. True once it is here."""
    url, _sha, mb = ak.DRAWINGS[site]
    st.info(f"The drawings for this set are not here yet. They come from the public bid set (about {mb:g} MB), checked "
            "against the copy the key was written on.", icon=":material/cloud_download:")
    if not st.button("Get the drawings", type="primary", icon=":material/download:", key=f"ak_fetch_{site}"):
        st.caption(f"Source: {url}")
        return False
    try:
        with st.spinner("Downloading the drawings…"):
            ak.fetch_drawing(site)
    except (OSError, ValueError) as e:
        st.error(f"Could not get the drawings: {e}", icon=":material/error:")
        return False
    st.rerun()
    return True


def key_file(job: str, site: str) -> None:
    """Download the key file, and carry on from one downloaded earlier. On the hosted app the disk is wiped on every
    restart, so this is how an engineer's answers survive: download at the end of each sitting, upload to resume."""
    p = ak.key_path(job, site)
    host = ak.hosted()
    if host:
        st.warning("This online copy of the app forgets saved answers when it restarts (each update restarts it). "
                   "Download your key file at the end of each sitting, and upload it here to carry on.",
                   icon=":material/cloud_off:")
    with st.expander("Your key file", expanded=host):
        c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
        if p.exists():
            c1.download_button("Download the key file", p.read_bytes(), file_name=p.name, mime="application/x-yaml",
                               icon=":material/download:", key=f"ak_dl_{job}_{site}")
            st.caption(f"`{ak.rel(p)}` is rewritten on every save. When the work is done, send the file to be "
                       "committed to the repo, so the scores use it.")
        else:
            c1.caption("Nothing saved yet for this set.")
        up = c2.file_uploader("Carry on from a key file you downloaded", type=["yaml", "yml"],
                              key=f"ak_up_{job}_{site}_{st.session_state.get('ak_up_n', 0)}")
        if up is not None:
            try:
                n = ak.import_key(job, site, up.getvalue())
            except ValueError as e:
                st.error(str(e), icon=":material/error:")
            else:
                st.session_state["ak_up_n"] = st.session_state.get("ak_up_n", 0) + 1
                st.session_state["ak_up_msg"] = (f"Loaded {n['items']} items: {n['added']} added, {n['replaced']} "
                                                 f"newer than here, {n['kept']} kept as they were.")
                st.rerun()
        if msg := st.session_state.pop("ak_up_msg", None):
            st.success(msg, icon=":material/task_alt:")


def main() -> None:
    st.html('<p style="margin:0">Write the answers the readers are scored against, on a fixed sample, about 1 to 2 hours '
            'in all. Blind: the reader\'s answer and the agent key stay hidden until you mark an item done.</p>')
    jobs = {ak.JOB_TITLE[j]: j for j in ak.JOBS}
    c1, c2 = st.columns([1, 2])
    job = jobs[c1.segmented_control("Job", list(jobs), default=list(jobs)[0], key="ak_job")
               or list(jobs)[0]]
    sets = ak.offered(job)
    site = c2.selectbox("Set", sets, format_func=lambda s: SET_TEXT.get(s, s), key=f"ak_set_{job}")
    st.session_state["ak_site"] = site
    ak.check_set(job, site)
    if job == "plans" and not ak.plan_file(site).exists():
        if not get_drawing(site):
            return
    sample = ak.sample_for(site)
    data = ak.load(job, site)
    items = list(sample["items"])
    extra_items = [{"id": i["id"], "sheet": i["sheet"], "page": i["page"], "tag": i["tag"], "group": i["sheet"],
                    "est_min": 0.0, "extra": True} for i in data["items"] if i.get("extra")]
    all_items = items + extra_items
    st.session_state["ak_ids"] = all_items

    pr = ak.progress(job, site, data)
    thing = "(sheet, tag) pairs" if job == "plans" else "sections"
    st.progress(pr["done"] / pr["total"] if pr["total"] else 0.0,
                text=f"{pr['done']} of {pr['total']} items done · {pr['spent_min']:g} min spent · about "
                     f"{pr['est_left_min']:.0f} min to go" + (f" (at your pace ×{pr['pace']:g})" if pr["pace"] != 1.0 else ""))
    st.caption(f"The sample is fixed: {pr['total']} of {sample['universe']} {thing}, picked from the documents by seed "
               f"`{sample['seed']}` (never from an answer key), so it fits about {pr['est_total_min']:.0f} minutes. "
               "Everyone who works this set answers the same items. "
               + (f"{pr['revealed']} revealed. " if pr["revealed"] else "")
               + f"Saved in `{ak.rel(ak.key_path(job, site))}`; the agent key is never touched.")
    st.text_input("Your name (saved in the key file)", value=data.get("engineer", ""), key="ak_engineer",
                  placeholder="Optional")
    key_file(job, site)

    curkey = f"ak_cur_{site}"
    ids = [i["id"] for i in all_items]
    if st.session_state.get(curkey) not in ids:
        st.session_state[curkey] = next((i for i in ids if status_of(data, i) != "done"), ids[0])

    def label(iid: str) -> str:
        it = next(i for i in all_items if i["id"] == iid)
        name = f"{it['sheet']} · {it['tag']}" if job == "plans" else f"{it['sequence']} · {it['section']}. {it['title']}"
        return f"{ICON[status_of(data, iid)]} {name}" + (" (added)" if it.get("extra") else "")

    s1, s2 = st.columns([4, 1], vertical_alignment="bottom")
    s1.selectbox("Item", ids, key=curkey, format_func=label)
    s2.button("Next not done ›", on_click=go_next, args=(job, site, ids), use_container_width=True, key="ak_top_next")
    item = next(i for i in all_items if i["id"] == st.session_state[curkey])
    tick(item["id"])
    st.divider()
    if job == "plans":
        plan_item(site, item, data, job)
        with st.expander("A tag the list doesn't have"):
            sheets = {s["sheet"]: s["page"] for s in ak.plan_sheets(site)}
            e1, e2, e3 = st.columns([1, 2, 1], vertical_alignment="bottom")
            e1.selectbox("Sheet", list(sheets), key="ak_extra_sheet")
            e2.text_input("Tag, as printed", key="ak_extra_tag", placeholder="e.g. FC-2.30")
            e3.button("Add it", on_click=add_extra_tag, args=(site, sheets, ids), use_container_width=True)
            st.caption("Use it for a unit you can see on the sheet that the sample doesn't list. Added items are "
                       "scored like the others, but don't count toward the progress bar.")
    else:
        seq_item(site, item, data, job)

    st.caption("Scores: `.venv/bin/python scripts/eval.py plan_meaning` or `sequence_read` report each reader against "
               "the human key and the agent key, and how often the two keys agree. Guide: docs/answer-key-guide.md")


with box("answer_keys", "Answer keys", "fact_check"):
    main()
