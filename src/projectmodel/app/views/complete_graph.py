"""Complete graph: what a complete, reliable building graph is for this use case, layer by layer, where each fact
comes from, and how far Alpha (names + folders) is today. The definition lives in projectmodel/graph_standard.py;
the page is graph_standard.html.
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store, knowledge_model  # noqa: E402
from projectmodel.graph_standard import PROJECT, definition, render_html, status  # noqa: E402
from projectmodel.projects import label, list_projects  # noqa: E402
from projectmodel.sequences import behaviour, document_path, sequences_payload  # noqa: E402
from projectmodel.scoring.score import DEFAULT_ACCEPT, GT_DIR, load_ground_truth, score_project  # noqa: E402

APP = ROOT / "src/projectmodel/app"
SOURCES = [ROOT / "data/kg.sqlite", APP / "graph_standard.html", ROOT / "src/projectmodel/graph_standard.py",
           document_path(PROJECT.split("/")[0])]


@st.cache_data(show_spinner="Measuring the graph…")
def page(theme: str | None, stamp: tuple) -> str:
    store, km = get_store(), knowledge_model()
    mapped = PROJECT in list_projects(store)
    site = PROJECT.split("/")[0]
    score = score_project(store, PROJECT, load_ground_truth(site), km, DEFAULT_ACCEPT) \
        if mapped and (GT_DIR / site).exists() else None
    seqs = behaviour(sequences_payload(store, km, PROJECT)) if mapped else None
    st_ = status(store, km, PROJECT, score, seqs) if mapped else \
        {f["id"]: {"pct": None, "state": "missing", "note": "Project not mapped yet."} for f in definition()["facts"]}
    return render_html(dict(definition(), status=st_, project_label=label(PROJECT)), theme)


st.title("What a complete graph is")
st.write("For agents to monitor, diagnose and act on a building, the graph must hold everything the building has "
         "(**complete**) and every fact in it must be trustworthy (**reliable**). This page defines both, fact by "
         "fact, and names the source of each one.")
st.iframe(page(st.context.theme.type, tuple(p.stat().st_mtime for p in SOURCES if p.exists())), height="content")
st.caption(f"Today's status is measured live on {label(PROJECT)}. Sources marked “next” arrive with the Niagara and "
           "CPO Studio adapters; “later” with project documents and live data.")
