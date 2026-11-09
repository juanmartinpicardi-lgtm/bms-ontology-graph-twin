"""All projects: one card per building, one row per input. Opening a project makes it active everywhere."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store, set_project  # noqa: E402
from projectmodel.projects import INPUTS, list_projects, site_of, summaries  # noqa: E402

store = get_store()
projects = list_projects(store)
info = summaries(store)

st.title("Projects")
st.write("Each project is one building with its own knowledge graph, review decisions, graphics and tables. "
         "The knowledge model and shared tribal knowledge sit above them all.")

by_site: dict[str, list[str]] = {}
for p in projects:
    by_site.setdefault(p.split("/")[0], []).append(p)

cols = st.columns(3)
for i, (site_id, plist) in enumerate(sorted(by_site.items())):
    site = site_of(plist[0])
    with cols[i % 3].container(border=True, height="stretch"):
        st.markdown(f"### {site.name}")
        st.markdown(f"{site.kind} · {site.location}")
        if site.role == "test":
            st.badge("Test set · measure only, never tune", color="orange")
        else:
            st.badge("Development set", color="blue")
        st.caption(site.source)
        for p in plist:
            s = info.get(p, {})
            n, links = s.get("nodes", {}), s.get("links", {})
            name, desc = INPUTS.get(p.split("/", 1)[1], (p, ""))
            st.divider()
            st.markdown(f"**{name}**")
            st.caption(desc)
            st.markdown(f"{n.get('point', 0):,} points · {n.get('equipment', 0)} equipment · "
                        f"{links.get('feeds', 0)} feeds links · {s.get('human', 0)} human decisions")
            st.caption(f"Mapped {(s.get('mapped_at') or '-')[:16]} · revision {s.get('revision') or '-'}")
            # Set in a callback: it runs before the header's project dropdown is drawn on the next run.
            if st.button("Open", key=f"open_{p}", icon=":material/arrow_forward:", on_click=set_project, args=(p,)):
                st.switch_page("review_app.py")

with cols[len(by_site) % 3].container(border=True, height="stretch"):
    st.markdown("### :material/add: New project")
    st.write("Add a building from a Haystack, Niagara or CPO Studio export.")
    st.page_link("views/new_project.py", label="Start", icon=":material/arrow_forward:")
