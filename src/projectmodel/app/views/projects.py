"""All projects: one card per building, one row per input. Opening a project makes it active everywhere."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store, set_project  # noqa: E402
from projectmodel.intake.model import progress  # noqa: E402
from projectmodel.intake.state import Intake, list_intakes  # noqa: E402
from projectmodel.projects import INPUTS, list_projects, site_of, summaries  # noqa: E402

store = get_store()
projects = list_projects(store)
info = summaries(store)

st.write("Each project is one building with its own knowledge graph, notes, graphics and tables. "
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
                st.switch_page("tree_app.py")

def open_intake(slug: str) -> None:
    st.session_state.update(ab_slug=slug, ab_sel=None)


k = len(by_site)
for s in list_intakes():  # buildings added from their documents, set up step by step
    it = Intake(s["slug"])
    share = progress(it)["share"]
    with cols[k % 3].container(border=True, height="stretch"):
        st.markdown(f"### {it.name}")
        loc = it.s.get("location") or {}
        st.markdown(loc.get("address") or it.s.get("address") or "Not located yet")
        st.badge("Guided setup", color="violet", icon=":material/add_business:")
        st.progress(share, text=f"{round(share * 100)}% built")
        if st.button("Continue the setup", key=f"intake_{it.slug}", icon=":material/arrow_forward:",
                     on_click=open_intake, args=(it.slug,)):
            st.switch_page("views/add_building.py")
    k += 1

with cols[k % 3].container(border=True, height="stretch"):
    st.markdown("### :material/add: Add a building")
    st.write("Locate it, upload its documents one step at a time (plans, schedules, sequences, controls submittal, "
             "BMS export), review, then add what people know. The graph and the twin grow at every step.")
    st.page_link("views/add_building.py", label="Start", icon=":material/arrow_forward:")
