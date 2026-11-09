"""3D view of one project's knowledge graph, optionally joined to the knowledge model.
Everything is clickable; the viewer runs in the browser, so navigation doesn't rerun the app.
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, get_store, knowledge_model, viewer_options  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402
from projectmodel.viz import graph_payload, render_html  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)

with st.container(horizontal=True, horizontal_alignment="right"):
    height = viewer_options("graph", 780, f"For a full-window view outside the app: "
                                          f"`.venv/bin/python scripts/export_graph3d.py {project}`")

# Labels come from source exports; the viewer escapes every string it puts into the page.
# The viewer takes the app's light/dark theme so its background matches the page around it.
st.iframe(render_html(graph_payload(store, project, knowledge_model()), st.context.theme.type), height=height)
