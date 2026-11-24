"""Data tables: the active project's points, equipment and links, flat, searchable, downloadable."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, box, count, get_store, table  # noqa: E402
from projectmodel.projects import list_projects  # noqa: E402
from projectmodel.tree import rel_source  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)


COLS = ["id", "label", "class", "confidence", "method", "status", "confirmed_by", "source", "source_file", "source_ref",
        "revision"]
on = {e["dst"]: e["src"] for e in store.edges(project, "hasPoint") if e["status"] != "rejected"}


def row(n) -> dict:
    return {k: rel_source(n[k]) if k == "source_file" else n[k] for k in COLS}


points = pd.DataFrame([{**row(n), "equipment": on.get(n["id"], "")} for n in store.nodes(project, "point")])
equipment = pd.DataFrame([row(n) for n in store.nodes(project, "equipment")])
links = pd.DataFrame([{k: e[k] for k in ("src", "rel", "dst", "confidence", "method", "status", "confirmed_by",
                                         "source", "source_ref")}
                      for e in store.edges(project)])

tables = box("tables", "Points, equipment and links", "table", fit=True)


def show(df: pd.DataFrame, name: str) -> None:
    """One table panel: a search bar and the download on top, the grid, and a footer with the row count."""
    with st.container(key=f"tablepanel_{name}"):
        with st.container(key=f"tabletools_{name}", horizontal=True, vertical_alignment="center"):
            with st.container(key=f"search_{name}", width=420):
                query = st.text_input("Search", placeholder=f"Search for {name}, classes, equipment",
                                      key=f"q_{name}", label_visibility="collapsed")
            st.space("stretch")
        total = len(df)
        if query and not df.empty:
            df = df[df.astype(str).apply(lambda col: col.str.contains(query, case=False, regex=False)).any(axis=1)]
        table(df, hide_index=True, height=560,
              column_config={"confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
        with st.container(key=f"tablefoot_{name}", horizontal=True, vertical_alignment="center"):
            st.caption(f"{len(df):,} of {total:,} rows" if query else f"{total:,} rows", width="content")
            st.space("stretch")
            st.download_button("Download CSV", df.to_csv(index=False), f"{project.replace('/', '_')}_{name}.csv",
                               mime="text/csv", icon=":material/download:", key=f"dl_{name}", type="tertiary")


tabs = tables.tabs([count("Points", len(points)), count("Equipment", len(equipment)), count("Links", len(links))])
with tabs[0]:
    show(points, "points")
with tabs[1]:
    show(equipment, "equipment")
with tabs[2]:
    show(links, "links")
