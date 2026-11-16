"""Sequences: the project's sequences of operation, read as linked text (each link opens its point, equipment or
system on the right, in 3D where there is a model) or simulated on the graph step by step. The document lives in
data/documents/<site>/sequences.yaml; projectmodel/sequences.py resolves it against the graph; the page is
app/sequences.html.
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, box, get_store, knowledge_model, page_tools  # noqa: E402
from projectmodel.intake.state import Intake  # noqa: E402
from projectmodel.equipment_view import MODULES  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402
from projectmodel.sequences import document_path, render_html, sequences_payload  # noqa: E402

APP = ROOT / "src/projectmodel/app"


@st.cache_data(show_spinner="Linking the sequences to the graph…")
def page(project: str, theme: str | None, start: str, start_mode: str, stamp: tuple) -> str | None:
    try:
        payload = sequences_payload(get_store(), knowledge_model(), project)
    except KeyError:  # the sequences name equipment this input did not produce (names only: no equipment folders)
        return None
    return render_html(payload | {"start": start, "start_mode": start_mode}, theme) if payload else None


store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)
doc = document_path(project.split("/")[0])
setup = Intake(project.split("/")[0]) if project.endswith("/documents") else None
if setup and setup.s and not doc.exists():  # a building added from its documents: the sequences its reader found
    seqs = setup.facts(kind="sequence", live=True)
    with box("seq_read", "Sequences of operation, as read from the documents", "sync_alt", fit=True):
        if not seqs:
            st.info("No sequence of operation was read for this building.", icon=":material/info:")
        for s in seqs:
            d = s["data"]
            with st.expander(f"**{d['title']}** · applies to {len(d['applies_to'])} units · "
                             f"{len(d.get('setpoints', []))} setpoints · {s['src'].get('file', '')}"):
                st.caption(", ".join(d["applies_to"]))
                for x in d.get("sections", []):
                    st.markdown(f"**{x['letter']}. {x['title']}**: {x['text']}")
    st.stop()
if not doc.exists():
    st.info(f"No sequences of operation for this building yet. Add them in `{doc.relative_to(ROOT)}`.")
    st.stop()
with page_tools():
    st.caption("Demo sequences written for Alpha (its own are not public)")
files = [ROOT / "data/kg.sqlite", doc, APP / "sequences.html", APP / "equipment3d.html",
         *(APP / "equipment3d" / m for m in MODULES)]
html = page(project, st.context.theme.type, st.query_params.get("seq", ""), st.query_params.get("mode", "read"),
            tuple(p.stat().st_mtime for p in files))
if html is None:
    st.info("The sequences talk about equipment this input does not have (names only gives no equipment folders). "
            "Switch the input to names + paths in the project header.")
    st.stop()
with box("sequences", fit=True):
    st.iframe(html, height=860)
    st.caption("Read: click a highlighted word to see that point, equipment or system on the right, in 3D where there "
               "is a model. Simulate: watch the sequence run through the graph. Solid links come from the BMS export, "
               "dashed ones from the sequence; amber and red mark what the sequence found wrong or missing in the graph.")
