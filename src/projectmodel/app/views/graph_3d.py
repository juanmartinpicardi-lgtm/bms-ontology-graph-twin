"""3D view of one project's knowledge graph, optionally joined to the knowledge model.
On the left, what the graph holds and how it was built; on the right, the graph, down to the bottom of the screen.
Everything is clickable; the viewer runs in the browser, so navigation doesn't rerun the app.
"""

import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app import screen  # noqa: E402
from projectmodel.app.bridge import frame  # noqa: E402
from projectmodel.app.shell import active_project, box, get_store, knowledge_model  # noqa: E402
from projectmodel.projects import label, list_projects  # noqa: E402
from projectmodel.viz import graph_payload, render_html  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)
payload = graph_payload(store, project, knowledge_model())
inst = [n for n in payload["nodes"] if n.get("layer") == "instance"]
kinds, rels = payload["counts"]["nodes"], payload["counts"]["links"]

info, graph = st.columns([1, 3.2], gap="medium")
with info, box("graph_info", "This graph", "hub", fit=True):
    st.markdown(f"#### {label(project)}")
    c = st.columns(2)
    c[0].metric("Equipment", f"{kinds.get('equipment', 0):,}", border=True)
    c[1].metric("Points", f"{kinds.get('point', 0):,}", border=True)
    c = st.columns(2)
    c[0].metric("Links", f"{sum(v for k, v in rels.items() if k != 'isA'):,}", border=True)
    c[1].metric("Classes used", f"{kinds.get('class', 0):,}", border=True)
    st.caption("**Links by kind**")
    st.dataframe(pd.DataFrame(sorted(((k, v) for k, v in rels.items()), key=lambda kv: -kv[1]),
                              columns=["link", "count"]), hide_index=True, width="stretch")
    methods = Counter(n.get("prov", {}).get("method", "") for n in inst)
    st.caption("**How each node was decided**")
    st.dataframe(pd.DataFrame(methods.most_common(), columns=["method", "nodes"]), hide_index=True, width="stretch")
    confident = sum(1 for n in inst if (n.get("prov", {}).get("confidence") or 0) >= 0.9)
    st.caption(f"{confident:,} of {len(inst):,} nodes at 90% confidence or more. Every node and link carries its "
               "source, method and confidence: hover one in the graph.")
    with st.expander("How to read it", icon=":material/help:"):
        st.markdown("- **Drag** to turn, **scroll** to zoom, **click** a node for its provenance and notes.\n"
                    "- **Colour by** kind, class, confidence, method, status or source in the viewer's panel.\n"
                    "- The **model layer** shows the knowledge-model classes the instances use.\n"
                    f"- Full window: `.venv/bin/python scripts/export_graph3d.py {project}`")

# Labels come from source exports; the viewer escapes every string it puts into the page.
# The viewer takes the app's light/dark theme so its background matches the page around it.
with graph, box("graph_view", fit=True):
    # A click on a node says what is selected: kept for the agent's context chips.
    ev = frame(render_html(payload, st.context.theme.type), None, 760, key=f"graph_{project}", title="Graph 3D")
if ev and ev.get("name") == "select":
    screen.remember("graph", ev)
if (picked := screen.recall("graph")) and picked.get("kind") in ("equipment", "point", "location"):
    screen.focus(picked["kind"], picked["id"], picked.get("label") or picked["id"])
