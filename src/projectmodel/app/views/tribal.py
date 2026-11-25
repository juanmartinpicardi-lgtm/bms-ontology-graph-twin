"""Tribal knowledge: what is captured so far (conventions, notes, review decisions), the conventions the curator
proposes from repeated review fixes (approve or reject them here), and the ones people approved.
Specs: docs/spec-tribal-knowledge.md, docs/spec-memory-skills.md; the loop: src/projectmodel/curator.py."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import curator, notes  # noqa: E402
from projectmodel.app.shell import box, get_store, knowledge_model, table  # noqa: E402
from projectmodel.conventions import ConventionError, layer_table, load_layers, scopes_for  # noqa: E402
from projectmodel.projects import label, list_projects, main_projects, summaries  # noqa: E402

store = get_store()
km = knowledge_model()

st.write("What engineers know about a building or a contractor that is written down nowhere. "
         "Captured, it makes the next mapping better and gives agents the context people have.")

where = box("tk_where", "Where it lives", "groups")
where.dataframe({
    "Kind": ["Contractor / customer conventions", "Site conventions", "Notes", "Learned from corrections"],
    "Example": ["\"This integrator writes CC for chiller condenser\"",
                "\"On Alpha, ZN means zone\"",
                "\"AHU-3 replaced in 2022; its RF VFD points are unused\"",
                "Reviewers fixed the same name twice → proposed convention"],
    "Scope": ["Shared across projects", "One project", "One project", "Proposed per site, approved by a person"],
    "Changes the mapping?": ["Yes", "Yes", "No, context only", "Once approved"],
}, hide_index=True)
where.page_link("views/notes.py", label="Notes (add them in the project's Tree)", icon=":material/sticky_note_2:")

# --- the learning loop ----------------------------------------------------------------------------------------------
every = summaries(store)
projects = list_projects(store)
inbox = box("tk_inbox", "Proposed conventions", "inbox")
inbox.caption("When people make the same fix twice in review (same class change, names sharing a word, same kind of "
              "equipment), the curator proposes a convention. Nothing changes until a named person approves it; then "
              "it is saved under knowledge/skills/ and the next run applies it, never over a person's decision.")
c = inbox.columns([2, 1, 1], vertical_alignment="bottom")
who = c[0].text_input("Your name (for approvals)", value=st.session_state.get("author", ""), key="tk_who")
if c[1].button("Look for patterns", icon=":material/manage_search:", width="stretch",
               help="Scan every project's review fixes now (rules; a model phrases them when AI is on)."):
    n = 0
    with st.spinner("Reading the review fixes…"):
        for p in projects:
            n += len(curator.propose(store, km, p))
    st.toast(f"{n} proposal{'s' if n != 1 else ''} waiting")
waiting = curator.pending(store)
c[2].metric("Waiting", len(waiting), border=True)
if not waiting:
    inbox.caption("Nothing waiting. Fix points in review; a pattern needs at least "
                  f"{curator.MIN_FIXES} fixes of the same kind.")
for p in waiting:
    pay, chk = p["payload"], p["checks"]
    with inbox.container(border=True, key=f"tk_p_{p['id']}"):
        st.markdown(f"**{pay['title']}**")
        st.caption(f"{p['id']} · {label(p['project'])} → {p['scope']} · phrased by {chk.get('phrased_by', 'rules')}")
        st.write(p["why"])
        entry = pay["entry"]
        st.code(f"{entry.get('pattern') or entry.get('phrase')}  →  {entry['class']}"
                + (f"   (on {entry['template']})" if entry.get("template") else "")
                + (f"   instead of {entry['instead_of']}" if entry.get("instead_of") else ""), language=None)
        left, right = st.columns(2)
        left.markdown(f"**Evidence: {len(p['evidence'])} fixes**")
        left.dataframe(pd.DataFrame([{"point": e["name"], "was": e["before"], "fixed to": e["after"], "by": e["by"],
                                      "equipment": e.get("equipment") or ""} for e in p["evidence"]]),
                       hide_index=True, width="stretch")
        right.markdown(f"**Would change {chk['would_change']} other points now**")
        if chk.get("examples"):
            right.caption(", ".join(f"“{x}”" for x in chk["examples"]))
        if chk.get("dropped"):
            right.caption(f"{len(chk['dropped'])} broader pattern(s) left out: they contradict a person's decision.")
        b = st.columns([1, 1, 2])
        if b[0].button("Approve", key=f"ap_{p['id']}", icon=":material/check:", type="primary", disabled=not who.strip()):
            try:
                path = curator.approve(store, km, p["id"], who.strip())
                st.toast(f"Saved to {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}. "
                         "It applies from the next run.")
                st.rerun()
            except (ValueError, ConventionError) as e:
                st.error(str(e))
        why_not = b[2].text_input("Why not? (the curator keeps it)", key=f"why_{p['id']}", label_visibility="collapsed",
                                  placeholder="Why not? (kept with the rejection)")
        if b[1].button("Reject", key=f"rj_{p['id']}", icon=":material/close:", disabled=not who.strip()):
            curator.reject(store, p["id"], who.strip(), why_not)
            st.rerun()

learned = box("tk_learned", "Learned conventions", "school")
rows = curator.learned()
if rows:
    learned.caption("Approved by people, saved under knowledge/skills/<scope>/learned-conventions-*/. Points they "
                    "decide carry the id in their provenance (method rule).")
    table(pd.DataFrame(rows), hide_index=True, width="stretch")
    mapped = [p for p in projects if p.split("/")[1] in ("names_paths", "names_only")]
    if mapped and learned.button("Re-run the mapper now", icon=":material/refresh:",
                                 help="Apply the approved conventions to the mapped projects."):
        from projectmodel.build import map_project
        with st.spinner("Mapping…"):
            for p in mapped:
                map_project(*p.split("/"), store.path)
        st.toast("Mapped again with the approved conventions")
else:
    learned.caption("None approved yet.")

# --- what is captured -----------------------------------------------------------------------------------------------
captured = box("tk_captured", "Captured so far", "inventory_2")
captured.write("Every review decision is tribal knowledge for that one point; repeated ones become proposals above.")
shown = main_projects(projects)  # one per building, as everywhere in the app (names-only is for scoring)
rows = [(label(p), every.get(p, {}).get("human", 0), len(curator.fixes(store, p)),
         len(notes.notes_by_project(store, p)), " <- ".join(scopes_for(p)) or "none") for p in shown]
captured.dataframe({"Project": [r[0] for r in rows], "Human decisions": [r[1] for r in rows],
                    "Fixes": [r[2] for r in rows], "Active notes": [r[3] for r in rows],
                    "Conventions": [r[4] for r in rows]}, hide_index=True)

conv = box("tk_conv", "Conventions in use", "rule")
conv.caption("Files under conventions/ and skills' rules under knowledge/skills/, layered knowledge model <- "
             "contractor <- customer <- site (conventions/projects.yaml says which apply where).")
entries = layer_table(load_layers(sorted({s for p in every for s in scopes_for(p)})))
if entries:
    conv.dataframe(entries, hide_index=True)
else:
    conv.caption("None yet.")
