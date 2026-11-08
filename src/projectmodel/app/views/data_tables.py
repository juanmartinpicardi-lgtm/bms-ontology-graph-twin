"""Data tables: the active project's points, equipment and links, flat, searchable, downloadable."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import active_project, get_store  # noqa: E402
from projectmodel.projects import label, list_projects  # noqa: E402

store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = active_project(projects)

st.title("Data tables")
st.caption(label(project))

COLS = ["id", "label", "class", "confidence", "method", "status", "source_file", "source_ref", "revision"]
on = {e["dst"]: e["src"] for e in store.edges(project, "hasPoint") if e["status"] != "rejected"}
points = pd.DataFrame([{**{k: n[k] for k in COLS}, "equipment": on.get(n["id"], "")}
                       for n in store.nodes(project, "point")])
equipment = pd.DataFrame([{k: n[k] for k in COLS} for n in store.nodes(project, "equipment")])
links = pd.DataFrame([{k: e[k] for k in ("src", "rel", "dst", "confidence", "method", "status", "source_ref")}
                      for e in store.edges(project)])

query = st.text_input("Search", placeholder="name, class, equipment…")


def show(df: pd.DataFrame, name: str) -> None:
    if query and not df.empty:
        df = df[df.astype(str).apply(lambda col: col.str.contains(query, case=False, regex=False)).any(axis=1)]
    st.caption(f"{len(df):,} rows")
    st.dataframe(df, hide_index=True, height=560,
                 column_config={"confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
    st.download_button("Download CSV", df.to_csv(index=False), f"{project.replace('/', '_')}_{name}.csv",
                       mime="text/csv", icon=":material/download:", key=f"dl_{name}")


tabs = st.tabs([f"Points ({len(points):,})", f"Equipment ({len(equipment):,})", f"Links ({len(links):,})"])
with tabs[0]:
    show(points, "points")
with tabs[1]:
    show(equipment, "equipment")
with tabs[2]:
    show(links, "links")
