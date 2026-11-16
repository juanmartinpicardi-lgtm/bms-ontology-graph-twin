"""App entry point: navigation and the active-project layer.

Run: .venv/bin/streamlit run src/projectmodel/app/main.py

An icon rail on the left picks the area; chips at the top pick the page inside it.

Overview          why the knowledge graph matters, how it works, what a complete graph is
Projects          every building, and adding one (guided setup); then one project's pages, with the building and input
                  switched in the project header
Digital twin      the active project as a building: floors, zones and equipment in 3D, with a floor plan
Shared knowledge  what sits above all projects: knowledge model, tribal knowledge
"""

import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
SRC = str(APP.parents[1])
sys.path.insert(0, SRC)


def reload_changed_package() -> None:
    """Drop the loaded projectmodel modules when any of the package's files changed since the last run, so this run
    imports the code that is on disk. Streamlit only reloads modules next to this script, and only for a browser
    session open at the moment of the change: without this, a running app keeps the store, mapper... it loaded at
    start until it is restarted, on Streamlit Cloud after every push."""
    stamp = max(p.stat().st_mtime_ns for p in Path(SRC, "projectmodel").rglob("*.py"))
    seen, sys._projectmodel_stamp = getattr(sys, "_projectmodel_stamp", None), stamp
    if seen is not None and seen != stamp:
        for name in [m for m in sys.modules if m == "projectmodel" or m.startswith("projectmodel.")]:
            del sys.modules[name]
        st.cache_resource.clear()  # cached objects (the knowledge model) were built by the old code
        st.cache_data.clear()


reload_changed_package()


def clear_test_buildings_once() -> None:
    """Once per server process: drop the buildings started from the test package. Not a cached resource, since a code
    change clears those and would remove test buildings in the middle of a session."""
    if getattr(sys, "_projectmodel_tests_cleared", False):
        return
    sys._projectmodel_tests_cleared = True
    from projectmodel.db.store import Store
    from projectmodel.intake.publish import INPUT, delete_project
    from projectmodel.intake.state import clear_test_intakes
    gone = clear_test_intakes()
    if gone and (APP.parents[2] / "data/kg.sqlite").exists():
        store = Store(APP.parents[2] / "data/kg.sqlite")
        for slug in gone:  # a test building finished in the setup is a project too: remove it with the building
            delete_project(store, f"{slug}/{INPUT}")


clear_test_buildings_once()

from projectmodel.app.shell import (active_project, area_header, ensure_database, get_store,  # noqa: E402
                                   project_header, rail)
from projectmodel.projects import list_projects  # noqa: E402

st.set_page_config(page_title="Project Model", page_icon=":material/hub:", layout="wide")

overview = [
    st.Page(APP / "views/pitch.py", title="The idea", icon=":material/auto_awesome:", default=True),
    st.Page(APP / "views/why.py", title="Why it matters", icon=":material/bolt:", url_path="why-it-matters"),
    st.Page(APP / "views/how.py", title="How it works", icon=":material/schema:", url_path="how-it-works"),
    st.Page(APP / "views/complete_graph.py", title="Complete graph", icon=":material/task_alt:",
            url_path="complete-graph"),
    st.Page(APP / "views/agent_tour.py", title="Agent tour", icon=":material/smart_toy:", url_path="agent-tour"),
]
projects = [
    st.Page(APP / "views/projects.py", title="All projects", icon=":material/apartment:", url_path="projects"),
    st.Page(APP / "views/add_building.py", title="Add a building", icon=":material/add_business:",
            url_path="add-building"),
]
this_project = [
    st.Page(APP / "views/location.py", title="Location", icon=":material/location_on:", url_path="location"),
    st.Page(APP / "tree_app.py", title="Tree", icon=":material/account_tree:", url_path="tree"),
    st.Page(APP / "views/graph_3d.py", title="Graph 3D", icon=":material/bubble_chart:", url_path="Graph_3D"),
    st.Page(APP / "views/equipment_3d.py", title="Equipment 3D", icon=":material/view_in_ar:",
            url_path="Equipment_3D"),
    st.Page(APP / "views/sequences.py", title="Sequences", icon=":material/sync_alt:", url_path="sequences"),
    st.Page(APP / "views/data_tables.py", title="Data tables", icon=":material/table:", url_path="data"),
    st.Page(APP / "views/notes.py", title="Notes", icon=":material/sticky_note_2:", url_path="Notes"),
    st.Page(APP / "views/project_tribal.py", title="Tribal knowledge", icon=":material/groups:",
            url_path="project-tribal-knowledge"),
]
twin = [st.Page(APP / "views/digital_twin.py", title="Digital twin", icon=":material/domain:", url_path="digital-twin")]
shared = [
    st.Page(APP / "views/knowledge_model.py", title="Knowledge model", icon=":material/account_tree:",
            url_path="Knowledge_model"),
    st.Page(APP / "views/tribal.py", title="Tribal knowledge", icon=":material/groups:", url_path="tribal-knowledge"),
]

page = st.navigation(overview + projects + this_project + twin + shared, position="hidden")
ensure_database()
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
    # Overview pages read like a document: one centred column, not the full width of a large screen.
    st.html("<style>.block-container { max-width: calc(1440px + 64px + 4rem); margin: 0 auto; }</style>")
    area_header("Overview", overview, page)
page.run()
