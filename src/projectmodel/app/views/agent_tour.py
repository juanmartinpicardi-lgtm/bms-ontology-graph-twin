"""Agent tours: an agent answering a real question by walking Alpha's knowledge graph. Chips switch the use case:

    Root cause         "Zone 1-2-81 is too warm. What's wrong?" (app/agent_tour.html)
    Functional test    a VAV's test written from its template and sequence, run in the equipment simulator
    Impact             what a shutdown of AHU-2 takes out, walked downstream and shown in the digital twin
    Tribal knowledge   a technician's voice note and photo become a confirmed note on the graph

Every tour has the same frame: the question on top, the graph and the agent's trace on the left, the equipment side
on the right. The tours always run on Alpha (names + folders), whatever project is open.
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import use_cases  # noqa: E402
from projectmodel.agent_tour import PROJECT, render_html, tour_payload  # noqa: E402
from projectmodel.app.shell import box, get_store, knowledge_model  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402

APP = ROOT / "src/projectmodel/app"
SOURCES = [ROOT / "data/kg.sqlite", APP / "agent_tour.html", APP / "use_cases.html", APP / "equipment3d.html",
           *(APP / "equipment3d").glob("*.js"), *(APP / "digital_twin").glob("*.js"), APP / "digital_twin.html",
           ROOT / "data/documents/alpha/sequences.yaml"]
CASES = {  # chip label -> (case, icon, caption)
    "Root cause": ("root", ":material/troubleshoot:",
                   "Values are simulated with the \"Chilled water running warm\" scenario; the agent's script is "
                   "fixed. Space plays or pauses, the arrow keys move between steps."),
    "Functional test": ("test", ":material/fact_check:",
                        "Points, template slots and the sequence come from Alpha's graph and project documents; values "
                        "come from the equipment simulator (hot afternoon)."),
    "Impact before maintenance": ("impact", ":material/build_circle:",
                                  "Units, feeds links and zones come from Alpha's graph; floors are inferred and the "
                                  "schedule is simulated."),
    "Tribal knowledge": ("tribal", ":material/record_voice_over:",
                         "AHU-2 and its points come from Alpha's graph; the technician, the voice note and the photo "
                         "are an example."),
}


@st.cache_data(show_spinner="Reading the graph…")
def page(case: str, theme: str | None, stamp: tuple) -> str:
    """Built once per use case, theme and version of the graph and page files: the same HTML on every rerun, so the
    tour doesn't restart."""
    if case == "root":
        return render_html(tour_payload(get_store(), knowledge_model()), theme)
    return use_cases.render_html(use_cases.cases_payload(get_store(), knowledge_model(), theme=theme), case, theme)


if PROJECT not in list_projects(get_store()):
    st.warning(f"The tours run on {PROJECT}. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()

with box("tour", fit=True):
    pick = st.segmented_control("Use case", list(CASES), default="Root cause", key="tour_case",
                                format_func=lambda c: f"{CASES[c][1]} {c}",
                                label_visibility="collapsed") or "Root cause"
    case, _, caption = CASES[pick]
    st.iframe(page(case, st.context.theme.type, tuple(p.stat().st_mtime for p in SOURCES if p.exists())), height=820)
    st.caption(f"Scripted agent over the knowledge graph of Project Haystack site Alpha (names and folders only). "
               f"{caption}")
