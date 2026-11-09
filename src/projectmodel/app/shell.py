"""Shared app state. The active project is chosen once (header dropdown, Projects page or a ?project= link) and
read by every project page, so switching building switches every view at once."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.projects import DEFAULT, label, list_projects, site_of, summaries

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data/kg.sqlite"


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


def viewer_options(key: str, default: int, note: str = "") -> int:
    """A small "View" popover above a 3D viewer (its height, plus a note); returns the height. The viewers have their
    own controls inside; this only holds what the app decides."""
    with st.popover("View", icon=":material/tune:"):
        height = st.slider("Viewer height", 500, 1400, default, 20, key=f"{key}_height")
        st.caption("Review decisions show up here after a page refresh." + (f"\n\n{note}" if note else ""))
    return height


def get_store() -> Store:
    return Store(DB)


def active_project(projects: list[str]) -> str:
    """A ?project= deep link wins once (each new link); after that the picker decides."""
    linked = st.query_params.get("project")
    if linked in projects and linked != st.session_state.get("_linked_project"):
        st.session_state["project"] = st.session_state["_linked_project"] = linked
    p = st.session_state.get("project")
    if p not in projects:
        p = DEFAULT if DEFAULT in projects else projects[0]
        st.session_state["project"] = p
    return p


def set_project(project: str) -> None:
    st.session_state["project"] = project


# No sidebar anywhere: navigation is the top bar, the project is the header dropdown, page controls live on the page.
CHROME_CSS = """<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {
  display: none !important; }
.block-container { padding-top: 3.8rem; }
</style>"""


def project_header(store: Store) -> None:
    """One row at the top of every page: which project is open, and a dropdown to switch it. The dropdown is keyed
    to the active project itself, so every page, deep link and the Projects page share one value."""
    st.html(CHROME_CSS)
    projects = list_projects(store)
    if not projects:
        st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
        return
    active_project(projects)
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        st.selectbox("Project", projects, key="project", format_func=label, label_visibility="collapsed",
                     width=280, help="Every project page shows this project. Switch it here at any time.")
        project = st.session_state["project"]
        site = site_of(project)
        if site.role == "test":
            st.badge("Test set · measure only, never tune", color="orange", icon=":material/science:")
        else:
            st.badge("Dev set", color="blue")
        n = summaries(store).get(project, {}).get("nodes", {})
        st.caption(f"{site.kind} · {n.get('point', 0):,} points · {n.get('equipment', 0)} equipment",
                   width="content")
        st.space("stretch")
        # The right end of this row belongs to the page (page_tools): its scenario, view options, ...
        st.session_state["_page_tools"] = st.container(horizontal=True, width="content", gap="small",
                                                       vertical_alignment="center")


def page_tools():
    """The page's own tools, at the right end of the header row; in place when the page runs on its own (tests)."""
    return st.session_state.pop("_page_tools", None) or st.container(horizontal=True, horizontal_alignment="right")
