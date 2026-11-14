"""App entry point: navigation and the active-project layer.

Run: .venv/bin/streamlit run src/projectmodel/app/main.py

An icon rail on the left picks the area; chips at the top pick the page inside it.

Overview          why the knowledge graph matters, how it works, what a complete graph is
Projects          every building, and adding a new one; then one project's pages, with the building and input
                  switched in the project header
Digital twin      the active project as a building: floors, zones and equipment in 3D, with a floor plan
Shared knowledge  what sits above all projects: knowledge model, tribal knowledge
"""

import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP.parents[1]))

from projectmodel.app.shell import active_project, area_header, get_store, project_header, rail  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402

st.set_page_config(page_title="Project Model", page_icon=":material/hub:", layout="wide")

overview = [
    st.Page(APP / "views/why.py", title="Why it matters", icon=":material/bolt:", default=True),
    st.Page(APP / "views/how.py", title="How it works", icon=":material/schema:", url_path="how-it-works"),
    st.Page(APP / "views/complete_graph.py", title="Complete graph", icon=":material/task_alt:",
            url_path="complete-graph"),
    st.Page(APP / "views/agent_tour.py", title="Agent tour", icon=":material/smart_toy:", url_path="agent-tour"),
]
projects = [
    st.Page(APP / "views/projects.py", title="All projects", icon=":material/apartment:", url_path="projects"),
    st.Page(APP / "views/new_project.py", title="New project", icon=":material/add_business:", url_path="new-project"),
]
this_project = [
    st.Page(APP / "tree_app.py", title="Tree", icon=":material/account_tree:", url_path="tree"),
    st.Page(APP / "views/graph_3d.py", title="Graph 3D", icon=":material/bubble_chart:", url_path="Graph_3D"),
    st.Page(APP / "views/equipment_3d.py", title="Equipment 3D", icon=":material/view_in_ar:",
            url_path="Equipment_3D"),
    st.Page(APP / "views/sequences.py", title="Sequences", icon=":material/sync_alt:", url_path="sequences"),
    st.Page(APP / "views/data_tables.py", title="Data tables", icon=":material/table:", url_path="data"),
    st.Page(APP / "views/notes.py", title="Notes", icon=":material/sticky_note_2:", url_path="Notes"),
]
twin = [st.Page(APP / "views/digital_twin.py", title="Digital twin", icon=":material/domain:", url_path="digital-twin")]
shared = [
    st.Page(APP / "views/knowledge_model.py", title="Knowledge model", icon=":material/account_tree:",
            url_path="Knowledge_model"),
    st.Page(APP / "views/tribal.py", title="Tribal knowledge", icon=":material/groups:", url_path="tribal-knowledge"),
]

page = st.navigation(overview + projects + this_project + twin + shared, position="hidden")
store = get_store()
if mapped := list_projects(store):
    active_project(mapped)  # every page: a ?project= deep link opens that project app-wide
rail([("Overview", ":material/home:", overview), ("Projects", ":material/apartment:", projects + this_project),
      ("Digital twin", ":material/domain:", twin), ("Shared knowledge", ":material/account_tree:", shared)], page)
def among(pages):
    return any(p.url_path == page.url_path for p in pages)


if among(this_project + twin):  # the twin is a project page too, with its own place on the rail
    project_header(store, this_project + twin, page, projects[0])
elif among(projects):
    area_header("Projects", projects, page)
elif among(shared):
    area_header("Shared knowledge", shared, page)
else:
    area_header("Overview", overview, page)
page.run()
