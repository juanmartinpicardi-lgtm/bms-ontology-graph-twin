"""Shared app state. The active project is chosen once (sidebar or Projects page) and read by every
project page, so switching building switches every view at once."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.projects import DEFAULT, INPUTS, SITES, list_projects, site_of, summaries

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data/kg.sqlite"


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


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


def project_picker(store: Store) -> None:
    """Sidebar block: building, then input. Shown on every project page."""
    projects = list_projects(store)
    if not projects:
        st.sidebar.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
        return
    current = active_project(projects)
    sites = sorted({p.split("/")[0] for p in projects})
    with st.sidebar:
        st.caption("PROJECT")
        site = st.selectbox("Building", sites, index=sites.index(current.split("/")[0]),
                            format_func=lambda s: f"{SITES[s].name} · {SITES[s].kind}" if s in SITES else s)
        inputs = [p.split("/", 1)[1] for p in projects if p.startswith(site + "/")]
        cur_input = current.split("/", 1)[1]
        inp = st.radio("Input", inputs, index=inputs.index(cur_input) if cur_input in inputs else 0,
                       format_func=lambda i: INPUTS.get(i, (i,))[0], horizontal=True)
        project = f"{site}/{inp}"
        set_project(project)
        s = summaries(store).get(project, {})
        if site_of(project).role == "test":
            st.badge("Test set · measure only, never tune", color="orange")
        n = s.get("nodes", {})
        st.caption(f"{n.get('point', 0):,} points · {n.get('equipment', 0)} equipment · "
                   f"mapped {(s.get('mapped_at') or '-')[:16]}")
        st.divider()
