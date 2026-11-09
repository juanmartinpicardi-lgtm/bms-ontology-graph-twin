"""Agent tour: "Zone 1-2-81 is too warm. What's wrong?", answered by an agent walking the knowledge graph.

Left: the graph, with the agent's walk and its trace. Right: each piece of equipment it reaches, in 3D with live
(simulated) values, and the evidence it collects. Ends on the root cause and what to check. The tour always runs on
Alpha (names + folders), whatever project is open: the scenario is about Alpha's chilled water plant.
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.agent_tour import PROJECT, render_html, tour_payload  # noqa: E402
from projectmodel.app.shell import get_store, knowledge_model  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402


APP = ROOT / "src/projectmodel/app"
SOURCES = [ROOT / "data/kg.sqlite", APP / "agent_tour.html", APP / "equipment3d.html", *(APP / "equipment3d").glob("*.js")]


@st.cache_data(show_spinner="Reading the graph…")
def page(theme: str | None, stamp: tuple) -> str:
    """Built once per theme and version of the graph and page files: the same HTML on every rerun, so the tour doesn't
    restart."""
    return render_html(tour_payload(get_store(), knowledge_model()), theme)


if PROJECT not in list_projects(get_store()):
    st.warning(f"The tour runs on {PROJECT}. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()

st.iframe(page(st.context.theme.type, tuple(p.stat().st_mtime for p in SOURCES)), height=880)
st.caption("The path, points, classes and provenance come from Alpha's knowledge graph (names and folders only). "
           "Values are simulated with the \"Chilled water running warm\" scenario; the agent's script is fixed for "
           "this demo. Space plays or pauses, the arrow keys move between steps.")
