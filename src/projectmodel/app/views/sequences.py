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

from projectmodel.app.shell import active_project, get_store, knowledge_model, page_tools  # noqa: E402
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
st.iframe(html, height=900)
st.caption("Read: click a highlighted word to see that point, equipment or system on the right, in 3D where there "
           "is a model. Simulate: watch the sequence run through the graph. Solid links come from the BMS export, "
           "dashed ones from the sequence; amber and red mark what the sequence found wrong or missing in the graph.")
