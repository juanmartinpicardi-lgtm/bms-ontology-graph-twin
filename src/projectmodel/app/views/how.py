"""How it works: the pipeline, the two layers (shared vs per project), and what every fact carries."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store, knowledge_model  # noqa: E402
from projectmodel.projects import DEFAULT, list_projects, summaries  # noqa: E402
from projectmodel.tree import provenance  # noqa: E402

km = knowledge_model()
store = get_store()
info = summaries(store)

st.write("Exports from engineering tools go in. A complete knowledge graph of the building comes out. "
         "Data flows one way: nothing is ever written back to the source tools.")

st.header("Four steps")
steps = [
    ("cable", "1 · Connect", "Adapters read each tool's export into one common record per point: name, folder, "
                            "device, units.", "Project Haystack today. Niagara and CPO Studio next."),
    ("psychology", "2 · Understand", "The mapper groups points onto equipment and gives each a class. "
                                     "Cheapest method first: structure → naming rules → equipment templates → "
                                     "an LLM only for what's left, with a short list of candidates.",
     "Every result gets a confidence between 0 and 1."),
    ("hub", "3 · Build the graph", "Every point and equipment gets the best guess, linked into one graph: "
                                   "points on equipment, parts, and what feeds what.",
     "Each fact keeps its source, method and confidence."),
    ("explore", "4 · Use", "The graph powers the views here: tree, 3D graph, equipment, tables. "
                       "Next: agents and plain-language questions.", "One graph per building."),
]
for col, (icon, head, body, foot) in zip(st.columns(4), steps):
    with col.container(border=True, height="stretch"):
        st.markdown(f"#### :material/{icon}: {head}")
        st.write(body)
        st.caption(foot)

st.header("Two layers")
st.write("Some knowledge is true of every building. Some is true of one. They live in different places.")
left, right = st.columns(2)
with left.container(border=True, height="stretch"):
    st.markdown("#### :material/public: Shared across all projects")
    st.markdown(f"**Knowledge model**: {len(km.classes)} classes (Brick standard + our extension), "
                f"{len(km.templates)} equipment templates, {len(km.name_rules.abbreviations)} abbreviations. "
                "What kinds of things exist and how to recognise them.")
    st.markdown("**Tribal knowledge, shared part**: conventions of a contractor or a customer, e.g. "
                "*\"this integrator writes CC for chiller condenser\"*. :gray-badge[coming]")
    st.page_link("views/knowledge_model.py", label="Explore the knowledge model", icon=":material/arrow_forward:")
with right.container(border=True, height="stretch"):
    st.markdown("#### :material/apartment: Inside each project")
    st.markdown("**Building graph**: equipment, points and how they connect, with the source of every fact.")
    st.markdown("**Graphics**: 3D graph; 3D equipment :gray-badge[coming]")
    st.markdown("**Data tables**: points, equipment, links.")
    st.markdown("**Tribal knowledge, site part**: site conventions and notes, e.g. "
                "*\"AHU-3 was replaced in 2022\"*. :gray-badge[coming]")
    st.page_link("views/projects.py", label="See the projects", icon=":material/arrow_forward:")
st.caption("The loop: each project's naming habits become site conventions, good ones are promoted to contractor "
           "or customer conventions, and the best become knowledge-model rules. The next building maps better.")

st.header("Every fact can be traced")
st.write("Nothing in the graph is a black box. Here is one real point, as stored:")
example = None
projects = list_projects(store)
if projects:
    p = DEFAULT if DEFAULT in projects else projects[0]
    example = next((n for n in store.nodes(p, "point") if n["label"] == "Clg_Valve_Cmd"), None) \
        or next(iter(store.nodes(p, "point")), None)
if example:
    prov = provenance(example)
    c = st.columns([2, 3])
    with c[0].container(border=True):
        st.markdown(f"**`{example['label']}`**")
        st.markdown(f"Class: **{example['class'] or 'unknown'}**")
        st.caption(f"Project {p} · {info.get(p, {}).get('nodes', {}).get('point', 0):,} points")
    c[1].dataframe({"field": list(prov), "value": [str(v) for v in prov.values()]}, hide_index=True)
else:
    st.caption("Map a project to see an example: .venv/bin/python scripts/run_mapper.py alpha names_paths")

st.header("Words we use")
st.dataframe({
    "Term": ["Graph", "Knowledge model", "Ontology", "Knowledge graph", "Tribal knowledge", "Digital twin"],
    "Meaning": [
        "Nodes and edges. No meaning on its own.",
        "The definitions: kinds of things, how they relate, rules to recognise them. Same for every project.",
        "The classes-and-relations part of the knowledge model (Brick + our extension).",
        "One building's graph, built with the knowledge model, every fact with its provenance.",
        "What engineers know that isn't written down: conventions and notes, shared or per site.",
        "Knowledge graph + live state + views. Later phase.",
    ]}, hide_index=True)
