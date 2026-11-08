"""Review screen: proposed items sorted by confidence; accept / fix / reject in bulk.
Tree tab: equipment tree with points and the provenance of every node and edge, plus notes
(free-text tribal knowledge) on equipment, points, links and the whole project.

Run: .venv/bin/streamlit run src/projectmodel/app/review_app.py
Decisions are written to data/kg.sqlite with method=human and survive mapper reruns.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import notes, review  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, GT_DIR, load_ground_truth, score_project  # noqa: E402
from projectmodel.tree import UNPLACED, build_tree  # noqa: E402

DB = ROOT / "data/kg.sqlite"

st.set_page_config(page_title="Project Model review", layout="wide")


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


@st.cache_resource
def ground_truth(site: str):
    return load_ground_truth(site)


km = knowledge_model()
store = Store(DB)

# --- Sidebar: project, reviewer, live score ----------------------------------------------------
projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes ORDER BY project")]
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
with st.sidebar:
    st.header("Review")
    default = projects.index("alpha/names_paths") if "alpha/names_paths" in projects else 0
    project = st.selectbox("Project", projects, index=default)
    reviewer = st.text_input("Reviewer", value=st.session_state.get("reviewer", ""), placeholder="your name")
    st.session_state["reviewer"] = reviewer
    accept_at = st.slider("Auto-accept at confidence ≥", 0.0, 1.0, DEFAULT_ACCEPT, 0.05)

    site = project.split("/")[0]
    if (GT_DIR / site).exists():
        s = score_project(store, project, ground_truth(site), km, accept_at)
        st.subheader("Score")
        if site == "bravo":
            st.caption("Bravo is the held-out test set. Don't tune on it.")
        c1, c2 = st.columns(2)
        c1.metric("H1 grouping", f"{s['H1_grouped_right_pct']}%")
        c2.metric("H2 class exact", f"{s['H2_exact_pct']}%")
        c1.metric("Exact, auto-accepted", f"{s['H2_auto_accepted_exact_pct']}%")
        c2.metric("To review", f"{s['review_pct']}%")
        st.metric("Decided by a human", s["human_decided"])
    else:
        st.caption("No ground truth for this project, so no score.")


def need_reviewer() -> bool:
    if not reviewer.strip():
        st.error("Enter your name in the sidebar first, so every decision is attributed.")
        return True
    return False


def frame(kind: str) -> pd.DataFrame:
    rows = []
    note_count = notes.active_counts(store, project)
    hp = {e["dst"]: e["src"] for e in store.edges(project, "hasPoint") if e["status"] != "rejected"}
    for n in store.nodes(project, kind):
        a = json.loads(n["attrs"])
        alts = ", ".join(f"{c} ({s:g})" for c, s in a.get("alternatives", [])[1:4])
        rows.append({
            "select": False, "id": n["id"], "name": n["label"],
            "equipment": (hp.get(n["id"], "")[3:] if kind == "point" else a.get("template") or ""),
            "class": n["class"] or "", "confidence": n["confidence"], "method": n["method"],
            "status": n["status"], "alternatives": alts if kind == "point" else "",
            "points": a.get("points", "") if kind == "equipment" else "",
            "notes": note_count.get(("node", n["id"]), 0),
            "flag": a["ignore"]["reason"] if "ignore" in a else "",
        })
    return pd.DataFrame(rows)


def review_tab(kind: str):
    df = frame(kind)
    if df.empty:
        st.info(f"No {kind} nodes.")
        return
    f1, f2, f3, f4 = st.columns([1.2, 1, 1.4, 1.4])
    statuses = f1.multiselect("Status", ["proposed", "confirmed", "rejected"], ["proposed"], key=f"st_{kind}")
    max_conf = f2.slider("Confidence ≤", 0.0, 1.0, 1.0, 0.05, key=f"mc_{kind}")
    text = f3.text_input("Name / equipment contains", key=f"tx_{kind}")
    cls_filter = f4.selectbox("Class", ["(any)"] + sorted(c for c in df["class"].unique() if c), key=f"cl_{kind}")
    view = df[df["status"].isin(statuses) & (df["confidence"] <= max_conf)]
    if text:
        view = view[view["name"].str.contains(text, case=False) | view["equipment"].str.contains(text, case=False)]
    if cls_filter != "(any)":
        view = view[view["class"] == cls_filter]
    view = view.sort_values(["confidence", "name"]).reset_index(drop=True)

    limit = st.number_input("Rows shown", 10, 5000, 200, 50, key=f"lim_{kind}")
    st.caption(f"{len(view)} {kind} items match, lowest confidence first. Showing {min(len(view), limit)}.")
    view = view.head(int(limit))
    if st.checkbox("Select all shown", key=f"all_{kind}"):
        view["select"] = True
    cols = ["select", "name", "equipment", "class", "notes", "confidence", "method", "status"]
    cols += ["flag", "alternatives"] if kind == "point" else ["points"]
    edited = st.data_editor(
        view[cols + ["id"]], hide_index=True, width="stretch", height=420,
        disabled=[c for c in cols + ["id"] if c != "select"],
        column_config={"id": None, "confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                       "select": st.column_config.CheckboxColumn("✓", width="small"),
                       "notes": st.column_config.NumberColumn("📝", width="small", help="Active notes")},
        key=f"ed_{kind}_{project}",
    )
    chosen = edited[edited["select"]]["id"].tolist()
    st.write(f"**{len(chosen)} selected**")

    a1, a2, a3 = st.columns([1, 1, 2.5])
    if a1.button("Accept", key=f"acc_{kind}", disabled=not chosen, type="primary"):
        if not need_reviewer():
            st.session_state["flash"] = f"Accepted {review.accept(store, project, chosen, reviewer)} {kind} items."
            st.rerun()
    if a2.button("Reject", key=f"rej_{kind}", disabled=not chosen):
        if not need_reviewer():
            st.session_state["flash"] = f"Rejected {review.reject(store, project, chosen, reviewer)} {kind} items."
            st.rerun()
    with a3.form(key=f"fix_{kind}", border=False):
        options = km.by_kind("point") if kind == "point" else km.by_kind("equipment") + km.by_kind("system")
        c_sel, c_btn = st.columns([3, 1])
        new_cls = c_sel.selectbox("Fix class to", options, label_visibility="collapsed", key=f"fc_{kind}")
        why = st.text_input("Why? (optional, saved as a note on each fixed item)", key=f"why_{kind}")
        if c_btn.form_submit_button("Fix class", disabled=not chosen) and not need_reviewer():
            n = review.fix_class(store, km, project, chosen, new_cls, reviewer)
            if why.strip():
                labels = dict(zip(edited["id"], edited["name"]))
                for i in chosen:
                    notes.add_note(store, project, "node", i, labels.get(i, i), "naming", why, reviewer,
                                   source="review", source_ref=f"fix to {new_cls}")
            st.session_state["flash"] = f"Set {n} {kind} items to {new_cls}."
            st.rerun()
    if kind == "point":
        equips = sorted(n["id"] for n in store.nodes(project, "equipment"))
        with st.form(key="move", border=False):
            m1, m2 = st.columns([3, 1])
            target = m1.selectbox("Move selected points to equipment", equips, format_func=lambda e: e[3:])
            if m2.form_submit_button("Move", disabled=not chosen) and not need_reviewer():
                n = review.move_points(store, project, chosen, target, reviewer)
                st.session_state["flash"] = f"Moved {n} points to {target[3:]}."
                st.rerun()


def fact(what: str, p: dict | None) -> dict:
    """One row of a provenance table: a fact and where it came from."""
    p = p or {}
    r = p.get("review") or {}
    return {"fact": what, "method": p.get("method", ""), "confidence": p.get("confidence"),
            "status": p.get("status", ""), "ref": p.get("source_ref", ""), "revision": p.get("revision"),
            "reviewed": f"{r['action']} by {r['by']} at {r['at'][:16]}" if r else "",
            "convention": ", ".join(p.get("convention", [])), "source": p.get("source_file", "")}


def provenance_table(rows: list[dict]):
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"confidence": st.column_config.NumberColumn(format="%.2f")})


def show_notes(items: list[dict], key: str, with_target: bool = False):
    """Notes with inline edit and status buttons (no delete: resolve or supersede instead)."""
    for x in items:
        head = f"**{x['topic']}** · {x['author']} · {x['updated_at'][:16]}"
        if x["source"] != "manual":
            head += f" · {x['source']}" + (f" ({x['source_ref']})" if x["source_ref"] else "")
        if x["status"] != "active":
            head += f" · _{x['status']}_"
        if with_target:
            head = f"{x['target_label'] or 'project'} — " + head
        with st.container(border=True):
            st.markdown(head)
            st.write(x["body"])
            b1, b2, b3 = st.columns([1, 1, 3])
            if x["status"] == "active":
                if b1.button("Resolve", key=f"nres_{key}_{x['id']}"):
                    notes.set_status(store, x["id"], "resolved")
                    st.rerun()
                if b2.button("Supersede", key=f"nsup_{key}_{x['id']}"):
                    notes.set_status(store, x["id"], "superseded")
                    st.rerun()
            elif b1.button("Reopen", key=f"nre_{key}_{x['id']}"):
                notes.set_status(store, x["id"], "active")
                st.rerun()
            with b3.popover("Edit"):
                with st.form(key=f"nedf_{key}_{x['id']}", border=False):
                    body = st.text_area("Note", x["body"], key=f"ned_{key}_{x['id']}")
                    topic = st.selectbox("Topic", notes.TOPICS, index=notes.TOPICS.index(x["topic"]),
                                         key=f"netp_{key}_{x['id']}")
                    if st.form_submit_button("Save") and body.strip():
                        notes.update_note(store, x["id"], body, topic)
                        st.rerun()


def add_note_form(targets: list[tuple[str, str, str]], key: str):
    """targets: (target_kind, target_id, label) the note may be attached to; the first is the default."""
    with st.expander("Add note"):
        with st.form(key=f"nadd_{key}", clear_on_submit=True, border=False):
            if len(targets) > 1:
                t = st.selectbox("About", targets, format_func=lambda t: t[2], key=f"natg_{key}")
            else:
                t = targets[0]
            topic = st.selectbox("Topic", notes.TOPICS, key=f"natp_{key}")
            body = st.text_area("Note", key=f"nabd_{key}",
                                placeholder="What should the next engineer know? e.g. 'RF VFD removed in 2022 retrofit'")
            if st.form_submit_button("Save note") and not need_reviewer():
                if not body.strip():
                    st.error("Write something first.")
                else:
                    notes.add_note(store, project, t[0], t[1], t[2], topic, body, reviewer, source="manual")
                    st.session_state["flash"] = f"Note added to {t[2]}."
                    st.rerun()


def notes_section(targets: list[tuple[str, str, str]], key: str):
    """Notes on any of the targets (all statuses, active first), then the add form."""
    found = [x for kind, tid, _ in targets for x in notes.notes_for(store, project, kind, tid)]
    found.sort(key=lambda x: (x["status"] != "active", x["id"]))
    st.markdown(f"**Notes ({sum(x['status'] == 'active' for x in found)} active)**")
    show_notes(found, key, with_target=len(targets) > 1)
    add_note_form(targets, key)


def tree_tab():
    tree = build_tree(store, project)
    proj_notes = notes.notes_for(store, project, "project", "")
    with st.expander(f"Project notes ({sum(x['status'] == 'active' for x in proj_notes)} active)"):
        show_notes(sorted(proj_notes, key=lambda x: (x["status"] != "active", x["id"])), "proj")
        add_note_form([("project", "", f"project {project}")], "proj")
    f1, f2 = st.columns([2, 1])
    text = f1.text_input("Find equipment or point", key="tree_tx").strip().lower()
    only_open = f2.toggle("Only equipment with proposed items", key="tree_open")

    def matches(n) -> bool:
        if only_open and n.prov.get("status") != "proposed" and all(p.prov["status"] != "proposed" for p in n.points):
            return False
        return not text or text in n.label.lower() or text in (n.cls or "").lower() or \
            any(text in p.label.lower() for p in n.points)

    keep = set()
    for n in tree.walk():
        if matches(n):
            keep.update(a.id for a in tree.path(n.id))
    rows = [{"id": n.id, "equipment": " " * n.depth + ("▾ " if n.children else "• ") + n.label,
             "class": n.cls or "", "points": f"{len(n.points)} / {n.total_points}" if n.children else str(len(n.points)),
             "method": n.prov.get("method", ""), "status": n.prov.get("status", "")}
            for n in tree.walk() if n.id in keep]
    eq_count = sum(1 for n in tree.walk() if n.id != UNPLACED)
    st.caption(f"{eq_count} equipment, {len(tree.by_id) - eq_count - (UNPLACED in tree.by_id)} points. "
               f"Showing {len(rows)} equipment. Points column: own / including parts. Select a row for its provenance.")

    left, right = st.columns([1, 1.5])
    with left:
        df = pd.DataFrame(rows, columns=["id", "equipment", "class", "points", "method", "status"])
        ev = st.dataframe(df, hide_index=True, width="stretch", height=640, on_select="rerun",
                          selection_mode="single-row", key=f"tree_{project}", column_config={"id": None})
    sel = ev.selection.rows
    with right:
        if not sel or sel[0] >= len(df):
            st.info("Select equipment on the left.")
            return
        n = tree.by_id[df.iloc[sel[0]]["id"]]
        st.subheader(n.label)
        st.caption(" › ".join(a.label for a in tree.path(n.id)))
        facts = [fact(f"class = {n.cls or '(none)'}", n.prov)] if n.prov else []
        if n.via:
            facts.append(fact(f"part of {tree.by_id[tree.parent[n.id]].label}", n.via))
        facts += [fact(f"feeds {tree.by_id[d].label}", p) for d, p in tree.feeds_to(n.id)]
        facts += [fact(f"fed by {tree.by_id[s].label}", p) for s, p in tree.fed_by(n.id)]
        if facts:
            provenance_table(facts)
        if n.attrs.get("template") or n.attrs.get("evidence"):
            with st.expander("How the class was chosen"):
                st.json({"template": n.attrs.get("template"), "grouping": n.attrs.get("grouping"),
                         "evidence": n.attrs.get("evidence")}, expanded=True)
        if n.id != UNPLACED:
            targets = [("node", n.id, n.label)]
            if n.via:
                par = tree.parent[n.id]
                targets.append(("edge", notes.edge_id(par, "hasPart", n.id),
                                f"{tree.by_id[par].label} has part {n.label}"))
            targets += [("edge", notes.edge_id(n.id, "feeds", d), f"{n.label} feeds {tree.by_id[d].label}")
                        for d, _ in tree.feeds_to(n.id)]
            targets += [("edge", notes.edge_id(s_, "feeds", n.id), f"{tree.by_id[s_].label} feeds {n.label}")
                        for s_, _ in tree.fed_by(n.id)]
            notes_section(targets, f"eq_{n.id}")
            pt_notes = [x for p in n.points for x in notes.notes_for(store, project, "node", p.id, "active")]
            if pt_notes:
                with st.expander(f"Notes on this equipment's points ({len(pt_notes)})"):
                    for x in pt_notes:
                        st.markdown(f"**{x['target_label']}** · {x['topic']} · {x['author']}: {x['body']}")

        st.markdown(f"**Points ({len(n.points)})**")
        if not n.points:
            return
        pt_count = notes.active_counts(store, project)
        pts = pd.DataFrame([{"id": p.id, "name": p.label, "class": p.cls or "",
                             "notes": pt_count.get(("node", p.id), 0), "confidence": p.prov["confidence"],
                             "method": p.prov["method"], "status": p.prov["status"], "row": p.prov["source_ref"],
                             "placed by": (p.via or {}).get("method", "")} for p in n.points])
        pev = st.dataframe(pts, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                           key=f"tree_pts_{project}_{n.id}",
                           column_config={"id": None, "notes": st.column_config.NumberColumn("📝", width="small"),
                                          "confidence": st.column_config.ProgressColumn(
                                              min_value=0, max_value=1, format="%.2f")})
        if pev.selection.rows:
            p = tree.by_id[pts.iloc[pev.selection.rows[0]]["id"]]
            st.markdown(f"**{p.label}** · `{p.attrs.get('source_id', '')}`")
            provenance_table([fact(f"class = {p.cls or '(none)'}", p.prov), fact(f"on {n.label}", p.via)])
            a = p.attrs
            detail = {"name words": a.get("words"), "unknown tokens": a.get("unknown_tokens"),
                      "alternatives (class, score)": [f"{c} ({s:g})" for c, s in a.get("alternatives", [])],
                      "folder path": a.get("path")}
            if "review" in a:
                detail["before review"] = a["review"].get("previous")
            if "ignore" in a:
                detail["flagged for review"] = f"{a['ignore']['reason']} ({a['ignore']['convention']})"
            st.json({k: v for k, v in detail.items() if v}, expanded=True)
            targets = [("node", p.id, p.label)]
            if n.id != UNPLACED:
                targets.append(("edge", notes.edge_id(n.id, "hasPoint", p.id), f"{n.label} has point {p.label}"))
            notes_section(targets, f"pt_{p.id}")


st.title("Project Model review")
st.caption(f"{project} · knowledge graph in {DB.relative_to(ROOT)} · decisions are saved as method=human")
if msg := st.session_state.pop("flash", None):
    st.success(msg)
# Keyed so a save (flash + rerun) keeps the reviewer on the tab they were working in.
tab_p, tab_e, tab_t = st.tabs(["Points", "Equipment", "Tree"], key="main_tab", on_change="rerun")
with tab_p:
    review_tab("point")
with tab_e:
    review_tab("equipment")
with tab_t:
    tree_tab()
