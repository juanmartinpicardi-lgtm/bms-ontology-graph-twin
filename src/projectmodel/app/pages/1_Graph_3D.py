"""3D view of one project's knowledge graph, optionally joined to the knowledge model.
Everything is clickable; the viewer runs in the browser, so navigation doesn't rerun the app.
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.viz import graph_payload, render_html  # noqa: E402

DB = ROOT / "data/kg.sqlite"

st.set_page_config(page_title="Knowledge graph 3D", layout="wide")


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


store = Store(DB)
projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes ORDER BY project")]
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
with st.sidebar:
    default = projects.index("alpha/names_paths") if "alpha/names_paths" in projects else 0
    project = st.selectbox("Project", projects, index=default, key="g3d_project")
    height = st.slider("Viewer height", 500, 1400, 820, 20)
    st.caption("Review decisions show up here after a page refresh. "
               "For a full-window view: `.venv/bin/python scripts/export_graph3d.py " + project + "`")

# Labels come from source exports; the viewer escapes every string it puts into the page.
st.iframe(render_html(graph_payload(store, project, knowledge_model())), height=height)
