"""New project: onboarding a building, step by step, from the address to a graph an agent can use.

The nine steps of docs/spec-submittals-workflow.md, walked on a building that is already built (Alpha), so each step
shows what is submitted and what it creates with real numbers from that building's knowledge graph. What a step
cannot do yet is shown as simulated and says so. Adding a building of your own from this page is not built yet.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store, knowledge_model, set_project, site_map  # noqa: E402
from projectmodel.locate import get_location  # noqa: E402
from projectmodel.onboarding import LAYERS, steps  # noqa: E402
from projectmodel.projects import DEFAULT, list_projects, site_of  # noqa: E402

STATUS = {"real": ("Works today", "green", ":material/check_circle:"),
          "partly": ("Partly built", "orange", ":material/timelapse:"),
          "simulated": ("Simulated", "gray", ":material/science:")}
LAYER_COLOR = {"graph": "gray", "kg": "blue", "km": "violet", "tribal": "orange"}


@st.cache_data(show_spinner="Reading the building's knowledge graph…")
def load_steps(project: str, revision: int) -> list[dict]:  # revision: a new mapper run refreshes the walk
    return steps(get_store(), knowledge_model(), project)


store = get_store()
projects = list_projects(store)
if not projects:
    st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
    st.stop()
project = DEFAULT if DEFAULT in projects else projects[0]
site = site_of(project)
revision = store.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM runs WHERE project = ?", (project,)).fetchone()[0]
walk = load_steps(project, revision)

st.markdown(f"#### Onboarding a building, shown on {site.name}")
st.caption("Nine steps from an address to a graph an agent can use. Numbers are counted on "
           f"{site.name}'s knowledge graph right now. Items marked *simulated* show what a step will take or "
           "produce once it is built. Adding your own building from this page is not built yet.")

n = st.session_state.setdefault("onb_step", 0)


def go(to: int) -> None:
    st.session_state["onb_step"] = max(0, min(len(walk) - 1, to))


with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    st.button("Back", icon=":material/arrow_back:", on_click=go, args=(n - 1,), disabled=n == 0)
    st.button("Next", icon=":material/arrow_forward:", type="primary", on_click=go, args=(n + 1,),
              disabled=n == len(walk) - 1)
    st.button("Restart", icon=":material/restart_alt:", on_click=go, args=(0,), disabled=n == 0)
    st.progress((n + 1) / len(walk), text=f"Step {n} of {len(walk) - 1}")

with st.container(horizontal=True, gap="small"):
    for s in walk:
        st.button(f"{s['n']} · {s['title']}", key=f"onb_{s['n']}", on_click=go, args=(s["n"],),
                  type="primary" if s["n"] == n else "tertiary" if s["n"] > n else "secondary")

step = walk[n]
label, color, icon = STATUS[step["status"]]
with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"### {step['n']}. {step['title']}", width="content")
        st.badge(label, color=color, icon=icon)
        for layer in step["layers"]:
            st.badge(LAYERS[layer], color=LAYER_COLOR[layer])
    st.write(step["what"])

    def show(items: list[dict]) -> None:
        for it in items:
            with st.container(horizontal=True, gap="small", vertical_alignment="top"):
                st.markdown(":material/check_circle:" if it["real"] else ":material/science:", width="content")
                tail = "" if it["real"] else "  \n:gray[*Simulated: not built yet.*]"
                st.markdown(f"**{it['name']}**" + (f"  \n{it['detail']}" if it["detail"] else "") + tail)

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### :material/upload: What is submitted")
        show(step["submitted"])
    with right:
        st.markdown("##### :material/auto_awesome: What is created")
        show(step["created"])

    if step["id"] == "locate" and (loc := get_location(store, project.split("/")[0])):
        site_map(loc["lat"], loc["lng"], site.name, 360)
    if step["table"]:
        st.markdown(f"**{step['table']['title']}**")
        st.dataframe(pd.DataFrame(step["table"]["rows"]), hide_index=True, width="content")
    if step["page"]:
        if st.button(f"See it on {site.name}: {step['page_label']}", icon=":material/open_in_new:",
                     on_click=set_project, args=(project,)):
            st.switch_page({"tree": "tree_app.py", "data": "views/data_tables.py"}.get(step["page"], f"views/{step['page'].lower().replace('-', '_')}.py"))

st.markdown("##### What exists after this step")
cols = st.columns(len(step["totals"]))
before = walk[n - 1]["totals"] if n else dict.fromkeys(step["totals"], 0)
for col, (name, value) in zip(cols, step["totals"].items()):
    added = value - before[name]
    col.metric(name, f"{value:,}", f"+{added:,}" if added else None, border=True)
