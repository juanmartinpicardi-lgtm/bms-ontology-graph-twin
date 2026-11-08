"""Tribal knowledge: placeholder until docs/spec-tribal-knowledge.md lands. Shows what is already captured."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store  # noqa: E402
from projectmodel.projects import label, summaries  # noqa: E402

store = get_store()

st.title("Tribal knowledge")
st.write("What engineers know about a building or a contractor that is written down nowhere. "
         "Captured, it makes the next mapping better and gives agents the context people have.")
st.info("Being built. See docs/spec-tribal-knowledge.md.", icon=":material/construction:")

st.header("Where it lives")
st.dataframe({
    "Kind": ["Contractor / customer conventions", "Site conventions", "Notes", "Learned from corrections"],
    "Example": ["\"This integrator writes CC for chiller condenser\"",
                "\"On Alpha, ZN means zone\"",
                "\"AHU-3 replaced in 2022; its RF VFD points are unused\"",
                "Reviewers fixed the same name 3 times → proposed convention"],
    "Scope": ["Shared across projects", "One project", "One project", "Proposed per project, promoted upward"],
    "Changes the mapping?": ["Yes", "Yes", "No, context only", "Once accepted"],
}, hide_index=True)

c = st.columns(3)
c[0].button("Add note", icon=":material/sticky_note_2:", disabled=True, width="stretch")
c[1].button("Add convention", icon=":material/rule:", disabled=True, width="stretch")
c[2].button("Review proposed conventions", icon=":material/inbox:", disabled=True, width="stretch")

st.header("Captured so far")
st.write("Every review decision is already tribal knowledge for that one point. The coming features turn "
         "repeated decisions into rules.")
rows = [(label(p), s.get("human", 0)) for p, s in sorted(summaries(store).items())]
st.dataframe({"Project": [r[0] for r in rows], "Human decisions": [r[1] for r in rows]}, hide_index=True)
