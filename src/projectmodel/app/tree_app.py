"""Tree: equipment tree with points and the provenance of every node and edge, plus notes
(free-text tribal knowledge) on equipment, points, links and the whole project.

Runs as a page of src/projectmodel/app/main.py; the project comes from the shared project picker.
Every class is the mapper's best guess (or a person's earlier decision); there is no review queue.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import notes  # noqa: E402
from projectmodel.app import screen  # noqa: E402
from projectmodel.app.shell import active_project, box  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.equipment_view import load_anchors  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, GT_DIR, load_ground_truth, score_project  # noqa: E402
from projectmodel.tree import UNPLACED, build_tree, provenance  # noqa: E402

DB = ROOT / "data/kg.sqlite"

@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


@st.cache_resource
def ground_truth(site: str):
    return load_ground_truth(site)


km = knowledge_model()
store = Store(DB)

# --- Header: live score ----------------------------------------------------------------------
projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes ORDER BY project")]
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)

site = project.split("/")[0]
with box("tree_head"), st.container(horizontal=True, gap="small", vertical_alignment="center"):
    st.caption("Every equipment and point with the mapper's best guess · select a row for where each fact came "
               "from", width=300)
    if (GT_DIR / site).exists():
        s = score_project(store, project, ground_truth(site), km, DEFAULT_ACCEPT)
        for name, value, tip in [
                ("Right equipment (H1)", f"{s['H1_grouped_right_pct']}%", "Points grouped on the right equipment"),
                ("Class exact (H2)", f"{s['H2_exact_pct']}%", "Points with exactly the right class"),
                ("Class compatible", f"{s['H2_compatible_pct']}%", "Right class, or its parent or child"),
                ("Equipment class", f"{s['equipment_class_exact_pct']}%", "Equipment with the right class")]:
            st.metric(name, value, help=tip, border=True, width="content")
    else:
        st.caption("No ground truth for this project, so no score.")


def fact(what: str, p: dict | None) -> dict:
    """One row of a provenance table: a fact and where it came from."""
    p = p or {}
    r = p.get("review") or {}
    return {"fact": what, "method": p.get("method", ""), "confidence": p.get("confidence"),
            "status": p.get("status", ""), "ref": p.get("source_ref", ""), "revision": p.get("revision"),
            "reviewed": f"{r['action']} by {r['by']} at {r['at'][:16]}" if r else "",
            "convention": ", ".join(p.get("convention", [])), "source": p.get("source_file", "")}


BEHAVIOUR = {"drives": ("drives", "driven by"), "feedback": ("feeds back to", "fed back by"),
             "requires": ("requires", "required by"), "resets": ("resets", "reset by"),
             "requests": ("requests", "requested by"), "switches": ("switches mode of", "mode switched by")}


def behaviour_facts(tree, nid: str) -> list[dict]:
    """The sequences' behaviour edges on this node (method document: intent, from the sequence of operation)."""
    out = []
    for e in store.edges(project):
        if e["method"] != "document" or e["rel"] not in BEHAVIOUR or nid not in (e["src"], e["dst"]):
            continue
        other = e["dst"] if e["src"] == nid else e["src"]
        verb = BEHAVIOUR[e["rel"]][e["src"] != nid]
        label = tree.by_id[other].label if other in tree.by_id else other
        out.append(fact(f"{verb} {label} (sequence, intent)", provenance(e)))
    return out


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
            author = st.text_input("Your name", value=st.session_state.get("author", ""), key=f"nau_{key}")
            if st.form_submit_button("Save note"):
                if not body.strip() or not author.strip():
                    st.error("Write the note and your name first.")
                else:
                    st.session_state["author"] = author
                    notes.add_note(store, project, t[0], t[1], t[2], topic, body, author, source="manual")
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
    text = st.text_input("Find equipment or point", key="tree_tx").strip().lower()

    def matches(n) -> bool:
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

    left, right = st.columns([1, 1.5], gap="medium")
    with left, box("tree_list", "Equipment", "account_tree", fit=True):
        df = pd.DataFrame(rows, columns=["id", "equipment", "class", "points", "method", "status"])
        ev = st.dataframe(df, hide_index=True, width="stretch", height=640, on_select="rerun",
                          selection_mode="single-row", key=f"tree_{project}", column_config={"id": None})
    sel = ev.selection.rows
    with right, box("tree_detail", "Provenance", "fact_check", fit=True):
        if not sel or sel[0] >= len(df):
            st.info("Select equipment on the left.")
            return
        n = tree.by_id[df.iloc[sel[0]]["id"]]
        if n.id != UNPLACED:
            screen.focus("equipment", n.id, n.label)
        st.subheader(n.label)
        st.caption(" › ".join(a.label for a in tree.path(n.id)))
        if n.attrs.get("template") in load_anchors():
            st.page_link("views/equipment_3d.py", label="Open 3D equipment",
                         query_params={"project": project, "equip": n.id})
        facts = [fact(f"class = {n.cls or '(none)'}", n.prov)] if n.prov else []
        if n.via:
            facts.append(fact(f"part of {tree.by_id[tree.parent[n.id]].label}", n.via))
        facts += [fact(f"feeds {tree.by_id[d].label}", p) for d, p in tree.feeds_to(n.id)]
        facts += [fact(f"fed by {tree.by_id[s].label}", p) for s, p in tree.fed_by(n.id)]
        facts += behaviour_facts(tree, n.id)
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
            screen.select([("point", p.id, p.label)])
            st.markdown(f"**{p.label}** · `{p.attrs.get('source_id', '')}`")
            provenance_table([fact(f"class = {p.cls or '(none)'}", p.prov), fact(f"on {n.label}", p.via)]
                             + behaviour_facts(tree, p.id))
            a = p.attrs
            detail = {"name words": a.get("words"), "unknown tokens": a.get("unknown_tokens"),
                      "alternatives (class, score)": [f"{c} ({s:g})" for c, s in a.get("alternatives", [])],
                      "folder path": a.get("path")}
            if "review" in a:
                detail["before review"] = a["review"].get("previous")
            if "ignore" in a:
                detail["flagged by convention"] = f"{a['ignore']['reason']} ({a['ignore']['convention']})"
            st.json({k: v for k, v in detail.items() if v}, expanded=True)
            targets = [("node", p.id, p.label)]
            if n.id != UNPLACED:
                targets.append(("edge", notes.edge_id(n.id, "hasPoint", p.id), f"{n.label} has point {p.label}"))
            notes_section(targets, f"pt_{p.id}")


if msg := st.session_state.pop("flash", None):
    st.success(msg)
tree_tab()
