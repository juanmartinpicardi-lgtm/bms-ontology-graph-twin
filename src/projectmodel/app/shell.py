"""Shared app state. The active project is chosen once (header dropdown, Projects page or a ?project= link) and
read by every project page, so switching building switches every view at once."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.locate import google_map_html, osm_embed_url
from projectmodel.projects import DEFAULT, INPUTS, list_projects, site_of, summaries

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data/kg.sqlite"


@st.cache_resource
def knowledge_model():
    return load_knowledge_model()


def viewer_options(key: str, default: int, note: str = "") -> int:
    """A small "View" popover above a 3D viewer (its height, plus a note); returns the height. The viewers have their
    own controls inside; this only holds what the app decides."""
    with st.popover("View", icon=":material/tune:"):
        height = st.slider("Viewer height", 500, 1400, default, 20, key=f"{key}_height")
        if note:
            st.caption(note)
    return height


def secret(name: str) -> str:
    """From .streamlit/secrets.toml, else the environment (NAME in upper case). Empty when not set."""
    try:
        value = st.secrets.get(name, "")
    except Exception:  # no secrets file at all
        value = ""
    return value or os.environ.get(name.upper(), "")


def site_map(lat: float, lng: float, label: str, height: int) -> None:
    """The spot on a map: Google's (satellite, with a 3D view) when a key is set, else OpenStreetMap's."""
    key = secret("google_maps_browser_key") or secret("google_maps_api_key")
    st.iframe(google_map_html(lat, lng, label, key) if key else osm_embed_url(lat, lng), height=height)


def get_store() -> Store:
    return Store(DB)


@st.cache_resource(show_spinner="First start: mapping Alpha into the knowledge graph (about a minute)…")
def ensure_database() -> None:
    """A fresh checkout (e.g. Streamlit Cloud) has no database, since data/*.sqlite is not in git: build it once from
    the blind exports and the sequences, into a temporary file moved into place when complete."""
    if DB.exists():
        return
    from projectmodel.build import build_all
    tmp = DB.with_suffix(".building.sqlite")
    tmp.unlink(missing_ok=True)
    build_all(tmp)
    tmp.replace(DB)


def active_project(projects: list[str]) -> str:
    """A ?project= deep link wins once (each new link); after that the picker decides."""
    linked = st.query_params.get("project")
    if linked in projects and linked != st.session_state.get("_linked_project"):
        st.session_state["project"] = st.session_state["_linked_project"] = linked
    p = st.session_state.get("project")
    if p not in projects:
        p = DEFAULT if DEFAULT in projects else projects[0]
        st.session_state["project"] = p
    return p


def set_project(project: str) -> None:
    st.session_state["project"] = project


# No sidebar anywhere: a fixed icon rail picks the area (Overview, Projects, Shared knowledge), chips pick the page
# inside it, and the project header switches building and input. Page controls live on the page.
ACCENT = "#4DA3E8"
RAIL = {"dark": {"bg": "#0E0F10", "line": "#24262A", "fg": "#9AA0A6", "hover": "#1E2023", "hover_fg": "#E8E9EA",
                 "on": "#23324A", "on_fg": "#8CC5F2", "box": "rgba(255,255,255,.025)", "box_line": "rgba(255,255,255,.10)"},
        "light": {"bg": "#F4F5F7", "line": "#DDE0E4", "fg": "#5F6670", "hover": "#E6E9ED", "hover_fg": "#16181D",
                  "on": "#DCEBFA", "on_fg": "#1F6FB5", "box": "rgba(16,24,40,.018)", "box_line": "rgba(16,24,40,.12)"}}


def theme() -> str:
    return "light" if st.context.theme.type == "light" else "dark"


def chrome_css() -> str:
    """The app's chrome for the current light/dark theme: the rail, the chips, and the boxes every section sits in
    (a container keyed box_<name> is a soft rounded panel). Content uses the full width of the screen."""
    c = RAIL[theme()]
    return f"""<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {{
  display: none !important; }}
.block-container {{ padding-top: 1.4rem; padding-left: calc(64px + 2rem); padding-right: 2rem; max-width: none; }}
[data-testid="stHeader"], [data-testid="stHeader"] * {{ background: transparent; pointer-events: none; }}
[data-testid="stHeader"] button, [data-testid="stHeader"] button * {{ pointer-events: auto; }}
[data-testid="stAppDeployButton"] {{ display: none; }}
.st-key-rail {{ position: fixed; left: 0; top: 0; bottom: 0; width: 64px; z-index: 999995; background: {c["bg"]};
  border-right: 1px solid {c["line"]}; padding: 14px 0; align-items: center; gap: 6px; }}
.st-key-rail [data-testid="stPageLink-NavLink"] {{ width: 44px; height: 44px; justify-content: center; padding: 0;
  border-radius: 10px; color: {c["fg"]}; }}
.st-key-rail [data-testid="stPageLink-NavLink"] [data-testid="stMarkdownContainer"] {{ display: none; }}
.st-key-rail [data-testid="stPageLink-NavLink"] span {{ margin: 0; font-size: 22px; color: inherit !important; }}
.st-key-rail [data-testid="stPageLink-NavLink"]:hover {{ background: {c["hover"]}; color: {c["hover_fg"]}; }}
.st-key-rail_on [data-testid="stPageLink-NavLink"] {{ background: {c["on"]}; color: {c["on_fg"]}; }}
.rail-logo {{ width: 36px; height: 36px; border-radius: 10px; background: {ACCENT}; display: flex;
  align-items: center; justify-content: center; margin: 0 auto 14px; }}
[class*="st-key-chip"] [data-testid="stPageLink-NavLink"] {{ border: 1px solid rgba(128,128,128,.35);
  border-radius: 999px; padding: 2px 14px; min-height: 34px; background: transparent; }}
[class*="st-key-chip"] [data-testid="stPageLink-NavLink"]:hover {{ border-color: {ACCENT}; }}
.st-key-chip_on [data-testid="stPageLink-NavLink"] {{ background: rgba(77,163,232,.16); border-color: {ACCENT}; }}
.st-key-chip_on [data-testid="stPageLink-NavLink"] p {{ font-weight: 600; }}
.st-key-areabar, .st-key-projbar {{ border-bottom: 1px solid rgba(128,128,128,.22); padding-bottom: 14px;
  margin-bottom: 6px; }}
.st-key-projsite [data-baseweb="select"] > div {{ font-size: 1.25rem; font-weight: 600; }}
[class*="st-key-box_"] {{ border: 1px solid {c["box_line"]} !important; border-radius: 16px !important;
  background: {c["box"]}; padding: 18px 20px !important; }}
[class*="st-key-box_"] [class*="st-key-box_"] {{ padding: 14px 16px !important; }}
</style>"""


def box(name: str, title: str = "", icon: str = "", fit: bool = False, **kw):
    """A section of a page: a soft rounded panel with an optional small title. Use as a context manager.
    `fit`: the box runs from where it starts to the bottom of the screen, and its main viewer (its tallest frame)
    grows or shrinks to fill it, wherever the header above ends (FIT_JS). Boxes side by side get the same height."""
    c = st.container(key=f"box_fit_{name}" if fit else f"box_{name}", **kw)
    if title:
        c.caption(f":material/{icon}: **{title}**" if icon else f"**{title}**")
    return c


# Sizes every fit box to the screen: measured in the page, so it holds when the header wraps or the window resizes.
# A fit box's height is the screen's bottom minus its top (at least MIN); its tallest frame then takes whatever
# height is left once everything else in the box is laid out. Runs once per browser tab, on resize and changes.
FIT_JS = """
export default function () {
  if (window.__pmFit) return;
  window.__pmFit = true;
  const MIN = 460, MIN_FRAME = 300, GAP = 14;
  const frames = el => {
    const out = [...el.querySelectorAll("iframe")];
    el.querySelectorAll("*").forEach(n => { if (n.shadowRoot) out.push(...n.shadowRoot.querySelectorAll("iframe")); });
    return out;
  };
  function fit() {
    const main = document.querySelector('[data-testid="stMain"]');
    const scrolled = main ? main.scrollTop : 0;
    for (const box of document.querySelectorAll('[class*="st-key-box_fit_"]')) {
      const r = box.getBoundingClientRect();
      if (!r.width) continue;
      const h = Math.max(MIN, Math.round(innerHeight - (r.top + scrolled) - GAP));
      for (const el of [box, box.parentElement]) {
        if (Math.abs(el.getBoundingClientRect().height - h) > 1 || el.style.height !== h + "px") {
          el.style.height = h + "px"; el.style.maxHeight = h + "px"; el.style.flex = "0 0 auto";
        }
      }
      box.style.overflowY = "auto";
      box.style.setProperty("--fit", h + "px");
      const fr = frames(box).sort((a, b) => b.offsetHeight - a.offsetHeight)[0];
      const kids = [...box.children].filter(k => k.offsetHeight);
      if (!fr || !kids.length) continue;
      const pad = parseFloat(getComputedStyle(box).paddingBottom) || 0;
      const used = kids[kids.length - 1].getBoundingClientRect().bottom - box.getBoundingClientRect().top
                   + box.scrollTop;
      const slack = h - pad - used;
      const want = Math.max(MIN_FRAME, Math.round(fr.offsetHeight + slack));
      if (Math.abs(want - fr.offsetHeight) <= 2) continue;
      // The frame's wrappers (Streamlit's element container, a component's host) keep the height they were given:
      // grow or shrink each one that wraps the frame tightly, so what sits below the frame moves with it.
      for (let el = fr.parentNode; el && el !== box; el = el.parentNode || el.host) {
        if (el.nodeType === 1 && Math.abs(el.offsetHeight - fr.offsetHeight) <= 4) {
          el.style.height = want + "px"; el.style.flex = "0 0 auto";  // Streamlit sizes it by flex-basis
        }
      }
      fr.style.height = want + "px";
    }
  }
  let queued = false;
  const later = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; fit(); }); } };
  addEventListener("resize", later);
  new MutationObserver(later).observe(document.body, { childList: true, subtree: true });
  setInterval(fit, 800);
  fit();
}
"""
_fit = st.components.v2.component("projectmodel.fit", js=FIT_JS)


RAIL_LOGO = """<div class="rail-logo" title="Project Model"><span aria-hidden="true"
style="font-family: 'Material Symbols Rounded'; font-size: 22px; color: #0B1A28">hub</span></div>"""


def rail(areas: list[tuple[str, str, list]], current) -> None:
    """The fixed icon rail on the left: one icon per area, linking to the area's first page."""
    st.html(chrome_css())
    with st.container(key="rail"):
        st.html(RAIL_LOGO)
        _fit(key="fit")
        for name, icon, pages in areas:
            on = any(p.url_path == current.url_path for p in pages)
            with st.container(key="rail_on" if on else f"rail_{name}", width="content"):
                st.page_link(pages[0], label=name, icon=icon, help=name)


def chips(pages: list, current, labels: dict[str, str] | None = None) -> None:
    """The pages of one area as a row of chips; the current one is filled."""
    with st.container(horizontal=True, gap="small", width="content"):
        for i, p in enumerate(pages):
            with st.container(key="chip_on" if p.url_path == current.url_path else f"chip_{i}", width="content"):
                st.page_link(p, label=(labels or {}).get(p.title, p.title), icon=p.icon)


def area_header(title: str, pages: list, current) -> None:
    """Areas without a project (Overview, Projects, Shared knowledge): the area's name, then its pages as chips."""
    with st.container(horizontal=True, vertical_alignment="center", gap="medium", key="areabar"):
        st.markdown(f"**{title}**", width="content")
        chips(pages, current)


def _pick_project(projects: list[str]) -> None:
    """Building or input changed: open that building with the chosen input, else its richest input."""
    site, inp = st.session_state["_site"], st.session_state.get("_input")
    if inp is None:  # the input toggle was cleared: keep the current project
        return
    wanted = f"{site}/{inp}"
    set_project(wanted if wanted in projects else next(p for p in projects if p.startswith(site + "/")))


def project_header(store: Store, sections: list, current, all_projects) -> None:
    """The top of every project page: back to all projects, the building (switch it here), its role and size, the
    input it was mapped from, then the project's pages as chips. Building and input are re-derived from the active
    project on every run, so deep links, the Projects page and these controls always agree."""
    projects = list_projects(store)
    if not projects:
        st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
        return
    project = active_project(projects)
    site_id = project.split("/")[0]
    st.session_state["_site"], st.session_state["_input"] = site_id, project.split("/", 1)[1]
    site = site_of(project)
    with st.container(key="projbar", gap="small"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.page_link(all_projects, label="Projects", icon=":material/arrow_back:")
            st.selectbox("Building", list(dict.fromkeys(p.split("/")[0] for p in projects)), key="_site",
                         format_func=lambda s: site_of(f"{s}/").name,
                         label_visibility="collapsed", width=170, on_change=_pick_project, args=(projects,),
                         help="Every project page shows this building. Switch it here at any time.")
            if site.role == "test":
                st.badge("Test set · measure only, never tune", color="orange", icon=":material/science:")
            elif site.source.startswith("Guided setup"):
                st.badge("Added from its documents", color="violet", icon=":material/add_business:")
            else:
                st.badge("Dev set", color="blue")
            n = summaries(store).get(project, {}).get("nodes", {})
            st.caption(f"{site.kind} · {n.get('point', 0):,} points · {n.get('equipment', 0)} equipment",
                       width="content")
            st.space("stretch")
            st.segmented_control("Input", [p.split("/", 1)[1] for p in projects if p.startswith(site_id + "/")],
                                 key="_input", format_func=lambda i: INPUTS.get(i, (i,))[0],
                                 label_visibility="collapsed", on_change=_pick_project, args=(projects,),
                                 help="What the mapper was given: names only, or names plus equipment folders.")
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            chips(sections, current)
            st.space("stretch")
            # The right end of this row belongs to the page (page_tools): its scenario, view options, ...
            st.session_state["_page_tools"] = st.container(horizontal=True, width="content", gap="small",
                                                           vertical_alignment="center")


def page_tools():
    """The page's own tools, at the right end of the header row; in place when the page runs on its own (tests)."""
    return st.session_state.pop("_page_tools", None) or st.container(horizontal=True, horizontal_alignment="right")
