"""All projects: one card per building, with a picture of its digital building, how complete its graph is and its
key numbers. Opening a project makes it active everywhere; a project can be deleted, a setup in progress
discarded. Each building shows its richest input (names + folders); the names-only input stays for scoring."""

import html
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.preview import building_svg  # noqa: E402
from projectmodel.app.shell import THEME, box, get_store, knowledge_model, set_project, theme  # noqa: E402
from projectmodel.progress import project_progress  # noqa: E402
from projectmodel.progress import setup as setup_progress  # noqa: E402
from projectmodel.intake.model import progress  # noqa: E402
from projectmodel.intake.state import Intake, list_intakes  # noqa: E402
from projectmodel.projects import delete_site, list_projects, main_projects, site_of, summaries  # noqa: E402
from projectmodel.twin_view import twin_payload  # noqa: E402


st.html("""<style>
.kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px 12px; margin: 2px 0 4px; }
.kpi b { display: block; font-size: 20px; line-height: 26px; font-weight: 700; }
.kpi span { font-size: 12px; line-height: 16px; opacity: .72; }
.loc { font-size: 13px; opacity: .72; margin: -4px 0 0; }
[class*="st-key-box_proj_"] [data-testid="stPopoverButton"],
[class*="st-key-box_intake_"] [data-testid="stPopoverButton"] { border-color: transparent; min-height: 32px;
  padding: 0 6px; }
[class*="st-key-box_"] [data-testid="stImage"] img { max-height: 240px; object-fit: contain; }
</style>""")

store = get_store()
projects = main_projects(list_projects(store))
info = summaries(store)
c = THEME[theme()]


@st.cache_data(show_spinner=False, max_entries=64)
def twin_levels(project: str, revision) -> tuple[list[dict], dict[str, int]]:  # revision: a re-map refreshes it
    p = twin_payload(get_store(), project, site_of(project).name)
    counts: dict[str, int] = {}
    for e in p["equip"]:
        counts[e.get("floor")] = counts.get(e.get("floor"), 0) + 1
    return p["levels"], counts


@st.cache_data(show_spinner=False, max_entries=64)
def completeness(project: str, revision) -> dict:  # revision: a re-map refreshes it
    """The share of the graph standard this project meets, and what to do next (progress.py; Roadmap page)."""
    return project_progress(get_store(), knowledge_model(), project, n_next=1)


def numbers(project: str) -> dict:
    q = store.conn.execute(  # trusted: confirmed (a person, two agreeing sources, auto-accept); to review: proposed
        "SELECT kind, COUNT(*), AVG(confidence), SUM(status = 'confirmed'), SUM(status = 'proposed')"
        " FROM nodes WHERE project = ? AND kind IN ('point', 'equipment') GROUP BY kind", (project,))
    rows = {k: (n, avg or 0, ok or 0, low or 0) for k, n, avg, ok, low in q}
    total = sum(r[0] for r in rows.values())
    return {"points": rows.get("point", (0,))[0], "equipment": rows.get("equipment", (0,))[0],
            "trusted": sum(r[2] for r in rows.values()) / total if total else 0,
            "confidence": sum(r[0] * r[1] for r in rows.values()) / total if total else 0,
            "review": sum(r[3] for r in rows.values())}


def kpi_grid(items: list[tuple[str, str]]) -> None:
    st.html('<div class="kpis">' + "".join(f'<div class="kpi"><b>{v}</b><span>{html.escape(k)}</span></div>'
                                           for k, v in items) + "</div>")


def open_project(p: str) -> None:
    set_project(p)


def remove(site_id: str, name: str, intake: bool) -> None:
    delete_site(store, site_id)
    if intake:
        Intake(site_id).delete()
    st.session_state.pop("project", None)
    st.toast(f"{name} deleted", icon=":material/delete:")


def discard(slug: str, name: str) -> None:
    Intake(slug).delete()
    if st.session_state.get("ab_slug") == slug:
        st.session_state.update(ab_started=False, ab_slug=None, ab_step=None, ab_sel=None)
    st.toast(f"{name}: setup discarded", icon=":material/delete:")


def manage(key: str, what: str, warning: str, action, args: tuple) -> None:
    """A small menu at the top right of a card, with a confirmation before anything is removed."""
    with st.popover("", icon=":material/more_vert:", help="Manage"):
        st.markdown(f"**{what}**")
        st.caption(warning)
        sure = st.checkbox("I understand this cannot be undone", key=f"sure_{key}")
        st.button(what, key=f"del_{key}", icon=":material/delete:", disabled=not sure, on_click=action, args=args,
                  width="stretch")


def card_head(name: str, menu) -> None:
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"### {name}", width="stretch")
        menu()


st.write("Each project is one building with its own knowledge graph, digital twin, notes and tables. The knowledge "
         "model and shared tribal knowledge sit above them all.")

intakes = {s["slug"]: s for s in list_intakes()}
cols = st.columns(3, gap="medium")
k = 0
for p in projects:
    site_id = p.split("/")[0]
    site = site_of(p)
    s = info.get(p, {})
    num = numbers(p)
    from_docs = site_id in intakes
    with cols[k % 3], box(f"proj_{site_id}", height="stretch"):
        card_head(site.name, lambda: manage(
            site_id, "Delete project",
            "Removes the building's knowledge graph, review decisions and notes" +
            (", and its guided setup." if from_docs else ". The source files stay; the mapper can rebuild it."),
            remove, (site_id, site.name, from_docs)))
        st.html(f'<p class="loc">{html.escape(site.kind)} · {html.escape(site.location or "No address")}</p>')
        with st.container(horizontal=True, gap="small"):
            if site.role == "test":
                st.badge("Test set", color="orange", icon=":material/science:")
            elif from_docs:
                st.badge("From documents", color="violet", icon=":material/add_business:")
            else:
                st.badge("Dev set", color="blue")
            st.badge(f"Revision {s.get('revision') or '-'}", color="gray")
        levels, counts = twin_levels(p, s.get("revision"))
        st.image(building_svg(levels, counts, c), width="stretch")
        if from_docs:
            share, label = progress(Intake(site_id))["share"], "built from its documents"
        else:
            share, label = num["trusted"], ("of the graph confirmed (by a person, two sources, or confidence ≥ "
                                            f"{store.auto.threshold:g})" if store.auto.threshold is not None else
                                            "of the graph confirmed (by a person or two sources)")
        st.progress(share, text=f"**{round(share * 100)}%** {label}")
        done = completeness(p, s.get("revision"))
        st.progress(done["overall"] / 100, text=f"**{done['overall']:.0f}%** of a complete graph · "
                                                 f"{done['done']} of {done['facts']} facts done")
        if done["next"]:
            n = done["next"][0]
            st.caption(("Demo set, kept as is. A building from documents adds: " if done["demo"] else "Next: ")
                       + n["action"])
        kpi_grid([("Points", f"{num['points']:,}"), ("Equipment", f"{num['equipment']:,}"),
                  ("Relationships", f"{sum(v for r, v in s.get('links', {}).items() if r != 'hasPoint'):,}"),
                  ("Levels", str(len(levels))), ("Avg. confidence", f"{num['confidence']:.0%}"),
                  ("To review", f"{num['review']:,}")])
        with st.container(horizontal=True, gap="small"):
            if st.button("Open project", key=f"open_{p}", type="primary", on_click=open_project, args=(p,),
                         help="Opens on its digital twin; the tree, graph and tables are in the project's tabs"):
                st.switch_page("views/digital_twin.py")
            if st.button("Tree", key=f"tree_{p}", icon=":material/account_tree:", on_click=open_project, args=(p,)):
                st.switch_page("tree_app.py")
    k += 1


def open_intake(slug: str) -> None:
    st.session_state.update(ab_started=True, ab_slug=slug, ab_sel=None, ab_step=None, ab_work=None)


built = {p.split("/")[0] for p in projects}
for slug in intakes:  # buildings still being set up (a finished one is a project above)
    if slug in built:
        continue
    it = Intake(slug)
    prog = progress(it)
    with cols[k % 3], box(f"intake_{slug}", height="stretch"):
        card_head(it.name, lambda: manage(
            slug, "Discard setup", "Removes the building being set up, with every document, answer and note.",
            discard, (slug, it.name)))
        loc = it.s.get("location") or {}
        st.html(f'<p class="loc">{html.escape(loc.get("address") or it.s.get("address") or "Not located yet")}</p>')
        st.badge("Setup in progress", color="violet", icon=":material/add_business:")
        st.image(building_svg([], {}, c, ghost=True), width="stretch")
        st.progress(prog["share"], text=f"**{round(prog['share'] * 100)}%** built from its documents")
        st.caption("Next: " + setup_progress(slug)["next"])
        kpi_grid([("Documents read", f"{sum(1 for x in prog['steps'].values() if x['read'])} of 5"),
                  ("Questions open", f"{sum(x['open'] for x in prog['steps'].values())}"),
                  ("Located", "Yes" if it.location else "No")])
        if st.button("Continue the setup", key=f"intake_{slug}", type="primary", icon=":material/arrow_forward:",
                     on_click=open_intake, args=(slug,)):
            st.switch_page("views/add_building.py")
    k += 1

with cols[k % 3], box("proj_add", height="stretch"):
    st.markdown("### :material/add: Add a building")
    st.write("Locate it, upload its documents one step at a time (plans, schedules, sequences, controls submittal, "
             "BMS export), review, then add what people know. The graph and the twin grow at every step.")
    if st.button("Start", key="proj_add_start", icon=":material/arrow_forward:"):
        st.switch_page("views/add_building.py")
