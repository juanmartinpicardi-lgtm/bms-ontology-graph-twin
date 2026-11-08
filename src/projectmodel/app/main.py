"""App entry point: navigation and the active-project layer.

Run: .venv/bin/streamlit run src/projectmodel/app/main.py

Overview          why the knowledge graph matters, how it works
Projects          every building, and adding a new one
This project      views of the active project's knowledge graph (project picker in the sidebar)
Shared knowledge  what sits above all projects: knowledge model, tribal knowledge
"""

import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP.parents[1]))

from projectmodel.app.shell import get_store, project_picker  # noqa: E402

st.set_page_config(page_title="Project Model", page_icon=":material/hub:", layout="wide")

overview = [
    st.Page(APP / "views/why.py", title="Why it matters", icon=":material/bolt:", default=True),
    st.Page(APP / "views/how.py", title="How it works", icon=":material/schema:", url_path="how-it-works"),
]
projects = [
    st.Page(APP / "views/projects.py", title="All projects", icon=":material/apartment:", url_path="projects"),
    st.Page(APP / "views/new_project.py", title="New project", icon=":material/add_business:", url_path="new-project"),
]
this_project = [
    st.Page(APP / "review_app.py", title="Review", icon=":material/fact_check:", url_path="review"),
    st.Page(APP / "pages/1_Graph_3D.py", title="Graph 3D", icon=":material/bubble_chart:", url_path="Graph_3D"),
    st.Page(APP / "views/equipment_3d.py", title="Equipment 3D", icon=":material/view_in_ar:",
            url_path="equipment-3d"),
    st.Page(APP / "views/data_tables.py", title="Data tables", icon=":material/table:", url_path="data"),
]
shared = [
    st.Page(APP / "pages/2_Knowledge_model.py", title="Knowledge model", icon=":material/account_tree:",
            url_path="Knowledge_model"),
    st.Page(APP / "views/tribal.py", title="Tribal knowledge", icon=":material/groups:", url_path="tribal-knowledge"),
]

page = st.navigation({"Overview": overview, "Projects": projects, "This project": this_project,
                      "Shared knowledge": shared}, position="top")
if page.url_path in {p.url_path for p in this_project}:
    project_picker(get_store())
page.run()
