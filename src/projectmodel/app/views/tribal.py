"""Tribal knowledge: what is captured so far (conventions, notes, review decisions) and what is still to come.
Spec: docs/spec-tribal-knowledge.md."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import notes  # noqa: E402
from projectmodel.app.shell import box, get_store  # noqa: E402
from projectmodel.conventions import layer_entries, load_layers, scopes_for  # noqa: E402
from projectmodel.projects import label, summaries  # noqa: E402

store = get_store()

st.write("What engineers know about a building or a contractor that is written down nowhere. "
         "Captured, it makes the next mapping better and gives agents the context people have.")
st.info("Live: notes and site conventions. Still to come: adding conventions from the app, and conventions "
        "proposed from repeated review fixes. See docs/spec-tribal-knowledge.md.", icon=":material/construction:")

where = box("tk_where", "Where it lives", "groups")
where.dataframe({
    "Kind": ["Contractor / customer conventions", "Site conventions", "Notes", "Learned from corrections"],
    "Example": ["\"This integrator writes CC for chiller condenser\"",
                "\"On Alpha, ZN means zone\"",
                "\"AHU-3 replaced in 2022; its RF VFD points are unused\"",
                "Reviewers fixed the same name 3 times → proposed convention"],
    "Scope": ["Shared across projects", "One project", "One project", "Proposed per project, promoted upward"],
    "Changes the mapping?": ["Yes", "Yes", "No, context only", "Once accepted"],
}, hide_index=True)

c = where.columns(3)
c[0].page_link("views/notes.py", label="Notes (add them in the project's Tree)", icon=":material/sticky_note_2:")
c[1].button("Add convention", icon=":material/rule:", disabled=True, width="stretch")
c[2].button("Review proposed conventions", icon=":material/inbox:", disabled=True, width="stretch")

captured = box("tk_captured", "Captured so far", "inventory_2")
captured.write("Every review decision is already tribal knowledge for that one point. The coming features turn "
         "repeated decisions into rules.")
rows = [(label(p), s.get("human", 0), len(notes.notes_by_project(store, p)), " <- ".join(scopes_for(p)) or "none")
        for p, s in sorted(summaries(store).items())]
captured.dataframe({"Project": [r[0] for r in rows], "Human decisions": [r[1] for r in rows],
              "Active notes": [r[2] for r in rows], "Conventions": [r[3] for r in rows]}, hide_index=True)

conv = box("tk_conv", "Conventions in use", "rule")
conv.caption("Files under conventions/, layered knowledge model <- contractor <- customer <- site "
           "(conventions/projects.yaml says which apply where).")
entries = layer_entries(load_layers(sorted({s for p in summaries(store) for s in scopes_for(p)})))
if entries:
    conv.dataframe(entries, hide_index=True)
else:
    conv.caption("None yet.")
