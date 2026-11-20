"""Shared app state. The active project is chosen once (header dropdown, Projects page or a ?project= link) and
read by every project page, so switching building switches every view at once."""

from __future__ import annotations

import html
import os
from pathlib import Path

import streamlit as st

from projectmodel.app.backdrop import graph_backdrop
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.locate import google_map_html, osm_embed_url
from projectmodel.projects import DEFAULT, list_projects, main_projects, site_of, summaries

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
    """The spot on a map: Google's satellite map and photorealistic 3D view, side by side, when a key is set; else
    OpenStreetMap's."""
    key = secret("google_maps_browser_key") or secret("google_maps_api_key")
    st.iframe(google_map_html(lat, lng, label, key, theme()) if key else osm_embed_url(lat, lng), height=height)


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
# Design language: the rail is the local navigation, near-black in both themes; the selected item is a grey tile
# with a blue bar on its left. Pages open with a page header (24px
# extra-bold title), the area's pages are underlined tabs, and every section is a grey card with a soft shadow.
THEME = {
    "dark": {"accent": "#64C3FF", "accent_hover": "#8FD3FF", "text": "#F0F0F0", "text2": "#C8C8C8",
             "mute": "#A0A0A0", "line": "#505050", "card": "#303030", "card2": "#272727", "input": "#1E1E1E",
             "input_line": "#8A8A8A", "input_hover": "#C8C8C8", "on_accent": "#1E1E1E", "tag_line": "#A0A0A0",
             "shadow": "0 4px 10px rgba(0,0,0,.25)", "bg": "#1E1E1E", "graph": "#9FD6FF", "good": "#68D560",
             "warn": "#F2B134", "bad": "#FF644C"},
    "light": {"accent": "#1792E5", "accent_hover": "#005EAC", "text": "#303030", "text2": "#505050",
              "mute": "#707070", "line": "#D0D0D0", "card": "#FFFFFF", "card2": "#F7F7F7", "input": "#FFFFFF",
              "input_line": "#909090", "input_hover": "#505050", "on_accent": "#FFFFFF", "tag_line": "#909090",
              "shadow": "0 2px 8px rgba(0,0,0,.08)", "bg": "#F0F0F0", "graph": "#005EAC", "good": "#007000",
              "warn": "#C98A12", "bad": "#EE3124"},
}
NAV = {"bg": "#090909", "fg": "#F0F0F0", "hover": "#262626", "on": "#404040", "bar": "#1792E5"}
ACCENT = THEME["dark"]["accent"]


def theme() -> str:
    return "light" if st.context.theme.type == "light" else "dark"


def chrome_css() -> str:
    """The app's chrome for the current light/dark theme: the rail, the tabs, the page header and the cards every
    section sits in (a container keyed box_<name> is a card). Content uses the full width of the screen."""
    t = theme()
    c = THEME[t]
    return f"""<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {{
  display: none !important; }}
[data-testid="stApp"] {{ background: {c["bg"]}; }}
/* A faint knowledge graph far behind the page, strongest top right and fading out towards the content */
[data-testid="stApp"]::before {{ content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background: {graph_backdrop(c["graph"])} center / cover no-repeat;
  -webkit-mask-image: radial-gradient(ellipse 75% 85% at 85% 10%, #000 0%, rgba(0,0,0,.35) 55%, transparent 100%);
  mask-image: radial-gradient(ellipse 75% 85% at 85% 10%, #000 0%, rgba(0,0,0,.35) 55%, transparent 100%); }}
[data-testid="stAppViewContainer"] {{ position: relative; z-index: 1; background: transparent; }}
[data-testid="stMain"], [data-testid="stBottomBlockContainer"] {{ background: transparent; }}
.block-container {{ padding-top: 1rem; padding-left: calc(64px + 26px); padding-right: 24px; max-width: none; }}
[data-testid="stHeader"], [data-testid="stHeader"] * {{ background: transparent; pointer-events: none; }}
[data-testid="stHeader"] button, [data-testid="stHeader"] button * {{ pointer-events: auto; }}
[data-testid="stAppDeployButton"] {{ display: none; }}

/* Local navigation */
.st-key-rail {{ position: fixed; left: 0; top: 0; bottom: 0; width: 64px; z-index: 999995; background: {NAV["bg"]};
  padding: 23px 0 14px; align-items: stretch; gap: 0; }}
.st-key-rail > div {{ width: 64px !important; }}
.st-key-rail [data-testid="stPageLink"] {{ width: 64px; }}
.st-key-rail [data-testid="stPageLink-NavLink"] {{ position: relative; width: 64px; height: 48px; margin: 0;
  justify-content: center; padding: 0; border-radius: 5px; color: {NAV["fg"]}; background: transparent; }}
.st-key-rail [data-testid="stPageLink-NavLink"] [data-testid="stMarkdownContainer"] {{ display: none; }}
.st-key-rail [data-testid="stPageLink-NavLink"] span {{ margin: 0; font-size: 24px; color: inherit !important; }}
.st-key-rail [data-testid="stPageLink-NavLink"]:hover {{ background: {NAV["hover"]}; }}
.st-key-rail_on [data-testid="stPageLink-NavLink"] {{ background: {NAV["on"]}; }}
.st-key-rail_on [data-testid="stPageLink-NavLink"]::before {{ content: ""; position: absolute; left: 0; top: 0;
  bottom: 0; width: 4px; border-radius: 1px; background: {NAV["bar"]}; }}
.rail-logo {{ width: 36px; height: 36px; border-radius: 9px; background: #FFFFFF; display: flex;
  align-items: center; justify-content: center; margin: 0 auto 27px;
  box-shadow: 0 0 0 3px rgba(238,49,36,.18); }}

/* Page header and tabs */
.st-key-areabar, .st-key-projbar {{ border-bottom: 1px solid {c["line"]}; padding-bottom: 0; margin-bottom: 10px; }}
.page-title {{ font-size: 24px; line-height: 32px; font-weight: 800; color: {c["text"]}; margin: 0; }}
/* The title row is 40px on every page (with or without the project picker), so the tabs sit at the same height
   everywhere; its right end stays clear of the fixed toolbar (theme switch and the menu) in the top right corner */
.st-key-titlebar {{ min-height: 40px; padding-right: 72px; }}
.st-key-titlebar [data-testid="stCaptionContainer"] {{ margin-top: 6px; }}
/* Top right: project, then the agent panel, settings and you, as in an app bar */
.st-key-projpick [data-baseweb="select"] > div {{ min-height: 36px; border-radius: 6px; min-width: 200px; }}
.st-key-toptools {{ gap: 8px !important; }}
.st-key-toptools [data-testid^="stBaseButton-"], .st-key-top_settings [data-testid="stPopoverButton"] {{
  width: 36px; min-height: 36px; height: 36px; padding: 0; justify-content: center; border-radius: 6px;
  background: {c["card2"]}; border: 1px solid {c["line"]}; }}
.st-key-toptools [data-testid^="stBaseButton-"]:hover, .st-key-top_settings [data-testid="stPopoverButton"]:hover {{
  border-color: {c["tag_line"]}; background: {c["card2"]}; text-decoration: none; }}
.st-key-toptools [data-testid="stIconMaterial"] {{ font-size: 19px; color: {c["text2"]} !important; }}
.st-key-top_settings [data-testid="stPopoverButton"] svg, .st-key-top_me [data-testid="stPopoverButton"] svg {{
  display: none; }}
.st-key-top_me [data-testid="stPopoverButton"] {{ width: 36px; min-height: 36px; height: 36px; padding: 0;
  border-radius: 50%; justify-content: center; background: {c["mute"]}; border: 0; }}
.st-key-top_me [data-testid="stPopoverButton"] p {{ color: {c["bg"]} !important; font-size: 13px; font-weight: 800;
  letter-spacing: .3px; }}

/* The theme switch, next to the menu: one click between light and dark */
#pm-theme {{ display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px;
  margin-right: 2px; padding: 0; border: 0; border-radius: 6px; background: transparent; cursor: pointer;
  color: {c["mute"]}; transition: color .12s ease, background .12s ease; }}
#pm-theme:hover {{ color: {c["text"]}; background: color-mix(in srgb, {c["text"]} 8%, transparent); }}
#pm-theme:focus-visible {{ outline: 2px solid {c["accent"]}; outline-offset: 1px; }}
#pm-theme span {{ font-family: 'Material Symbols Rounded'; font-size: 18px; line-height: 1; }}
/* While the switch drives Streamlit's menu, the menu is not shown */
body.pm-theming [data-testid="stMainMenuPopover"] {{ opacity: 0 !important; pointer-events: none !important; }}
[class*="st-key-chip"] [data-testid="stPageLink-NavLink"] {{ border: 0; border-radius: 0; padding: 6px 4px 10px;
  margin: 0 10px 0 0; min-height: 40px; background: transparent; border-bottom: 3px solid transparent; }}
[class*="st-key-chip"] [data-testid="stPageLink-NavLink"] p {{ font-weight: 700; color: {c["text2"]}; }}
[class*="st-key-chip"] [data-testid="stPageLink-NavLink"] span {{ color: {c["text2"]} !important; }}
[class*="st-key-chip"] [data-testid="stPageLink-NavLink"]:hover {{ background: transparent; }}
[class*="st-key-chip"] [data-testid="stPageLink-NavLink"]:hover p {{ color: {c["accent"]}; }}
.st-key-chip_on [data-testid="stPageLink-NavLink"] {{ border-bottom-color: {c["accent"]}; }}
.st-key-chip_on [data-testid="stPageLink-NavLink"] p {{ color: {c["text"]}; font-weight: 800; }}
.st-key-chip_on [data-testid="stPageLink-NavLink"] span {{ color: {c["accent"]} !important; }}

/* Cards */
[class*="st-key-box_"] {{ border: 1px solid {c["card"]} !important; border-radius: 10px !important;
  background: {c["card"]}; box-shadow: {c["shadow"]}; padding: 16px 24px !important; }}
[class*="st-key-box_"] [class*="st-key-box_"] {{ background: {c["card2"]}; border-color: {c["card2"]} !important;
  box-shadow: none; padding: 14px 16px !important; }}

/* Buttons: 40px tall, 4px corners, letter-spaced labels. Primary is filled in the accent with dark text; secondary
   (and popovers) are outlined in the accent on a transparent ground; tertiary is an accent text link. */
[data-testid^="stBaseButton-"], [data-testid="stPopoverButton"] {{ min-height: 40px; border-radius: 4px;
  padding: 0 20px; font-size: 15px; font-weight: 600; letter-spacing: .4px; box-shadow: none;
  transition: background .12s ease, border-color .12s ease, color .12s ease; }}
[data-testid^="stBaseButton-"] p, [data-testid="stPopoverButton"] p {{ font-size: 15px; font-weight: 600;
  letter-spacing: .4px; }}
[data-testid="stBaseButton-primary"] {{ background: {c["accent"]}; border: 1px solid {c["accent"]};
  color: {c["on_accent"]}; }}
[data-testid="stBaseButton-primary"] * {{ color: {c["on_accent"]} !important; }}
[data-testid="stBaseButton-primary"]:hover {{ background: {c["accent_hover"]}; border-color: {c["accent_hover"]}; }}
[data-testid="stBaseButton-secondary"], [data-testid="stPopoverButton"] {{ background: transparent;
  border: 1px solid {c["accent"]}; color: {c["accent"]}; }}
[data-testid="stBaseButton-secondary"] *, [data-testid="stPopoverButton"] * {{ color: {c["accent"]}; }}
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stPopoverButton"]:hover {{
  background: color-mix(in srgb, {c["accent"]} 12%, transparent); border-color: {c["accent_hover"]}; }}
[data-testid="stBaseButton-tertiary"] {{ padding: 0 6px; min-height: 32px; color: {c["accent"]}; }}
[data-testid="stBaseButton-tertiary"] * {{ color: {c["accent"]}; }}
[data-testid="stBaseButton-tertiary"]:hover {{ text-decoration: underline; text-underline-offset: 3px; }}
[data-testid^="stBaseButton-"]:disabled {{ opacity: .45; }}
[data-testid^="stBaseButton-"]:focus-visible, [data-testid="stPopoverButton"]:focus-visible {{
  outline: 2px solid {c["accent"]}; outline-offset: 2px; }}
/* A destructive action (a button keyed del_...) is outlined in red */
[class*="st-key-del_"] [data-testid^="stBaseButton-"] {{ border-color: {c["bad"]}; color: {c["bad"]};
  background: transparent; }}
[class*="st-key-del_"] [data-testid^="stBaseButton-"] * {{ color: {c["bad"]} !important; }}
[class*="st-key-del_"] [data-testid^="stBaseButton-"]:hover {{
  background: color-mix(in srgb, {c["bad"]} 12%, transparent); }}

/* Fields: 40px, dark fill inside the grey card, 1px grey outline, 4px corners; the accent on focus */
[data-testid="stWidgetLabel"] p {{ font-size: 14px; font-weight: 500; color: {c["text"]}; }}
[data-testid="stSelectbox"] [data-baseweb="select"] > div, [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
[data-testid="stTextInputRootElement"], [data-testid="stNumberInputContainer"], [data-testid="stDateInput"] > div > div,
[data-testid="stTextArea"] [data-baseweb="textarea"] {{
  background: {c["input"]} !important; border: 1px solid {c["input_line"]} !important; border-radius: 4px !important;
  min-height: 40px; transition: border-color .12s ease; }}
[data-testid="stSelectbox"] [data-baseweb="select"] > div:hover, [data-testid="stMultiSelect"] [data-baseweb="select"] > div:hover,
[data-testid="stTextInputRootElement"]:hover, [data-testid="stNumberInputContainer"]:hover,
[data-testid="stTextArea"] [data-baseweb="textarea"]:hover {{ border-color: {c["input_hover"]} !important; }}
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div:focus-within,
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stTextArea"] [data-baseweb="textarea"]:focus-within {{ border-color: {c["accent"]} !important;
  box-shadow: 0 0 0 1px {c["accent"]}; }}
[data-testid="stTextInputRootElement"] input, [data-testid="stNumberInputContainer"] input,
[data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] [data-baseweb="select"] div,
[data-testid="stMultiSelect"] [data-baseweb="select"] div {{ background: transparent; font-size: 15px; }}
[data-testid="stTextInputRootElement"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {{
  font-style: italic; color: {c["mute"]}; }}
/* Drop zones are dashed, like a place to put something */
[data-testid="stFileUploaderDropzone"] {{ background: transparent; border: 1px dashed {c["input_line"]};
  border-radius: 6px; }}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color: {c["accent"]}; }}
/* Tags (badges) are small outlined labels */
[data-testid="stBadge"] > span, .stBadge span {{ border-radius: 4px; font-weight: 600; letter-spacing: .2px; }}
/* Expanders and popovers share the card language */
[data-testid="stExpander"] details {{ border-radius: 6px; border-color: {c["line"]}; }}
[data-testid="stPopoverBody"] {{ border-radius: 8px; border: 1px solid {c["line"]}; box-shadow: {c["shadow"]}; }}
[data-testid="stProgress"] [role="progressbar"] > div > div {{ border-radius: 4px; }}

/* Section titles inside cards: small caps, letter-spaced, like a form heading */
.box-title {{ display: flex; align-items: center; gap: 8px; margin: 0 0 2px; font-size: 13px; font-weight: 700;
  letter-spacing: 1.6px; text-transform: uppercase; color: {c["text"]}; }}
.box-title .ms {{ font-family: 'Material Symbols Rounded'; font-size: 18px; letter-spacing: 0; text-transform: none;
  color: {c["accent"]}; font-weight: 400; }}

/* The project picker sits top right of a project page */
.st-key-projpick [data-testid="stSelectbox"] [data-baseweb="select"] > div {{ min-width: 220px; }}
</style>"""


def box(name: str, title: str = "", icon: str = "", fit: bool = False, **kw):
    """A section of a page: a soft rounded panel with an optional small title. Use as a context manager.
    `fit`: the box runs from where it starts to the bottom of the screen, and its main viewer (its tallest frame)
    grows or shrinks to fill it, wherever the header above ends (FIT_JS). Boxes side by side get the same height."""
    c = st.container(key=f"box_fit_{name}" if fit else f"box_{name}", **kw)
    if title:
        ms = f'<span class="ms" aria-hidden="true">{icon}</span>' if icon else ""
        c.html(f'<div class="box-title">{ms}<span>{html.escape(title)}</span></div>')
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
    // The agent dock's top: level with the first box under the page header, wherever the header ends.
    const hd = document.querySelector('.st-key-projbar, .st-key-areabar');
    if (hd) {
      const top = Math.round(hd.getBoundingClientRect().bottom + scrolled
                             + (parseFloat(getComputedStyle(hd).marginBottom) || 0) + GAP) + "px";
      if (document.documentElement.style.getPropertyValue("--pm-dock-top") !== top)
        document.documentElement.style.setProperty("--pm-dock-top", top);
    }
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
      const fr = frames(box).filter(f => !f.closest('[data-nofit]')).sort((a, b) => b.offsetHeight - a.offsetHeight)[0];
      const kids = [...box.children].filter(k => k.offsetHeight);
      if (!fr || !kids.length) continue;
      // The frame's tight wrappers: every element between the frame and the box that holds nothing else (Streamlit's
      // element container, a component's host and its shadow root's div). The outermost one is the space the frame
      // takes in the box, whatever height the frame itself has at the moment.
      const holds = (k, n) => { for (; n; n = n.parentNode || n.host) if (n === k) return true; return false; };
      const tight = [];
      for (let el = fr.parentNode; el && el !== box; el = el.parentNode || el.host) {
        if (el.nodeType !== 1) continue;  // a shadow root: go on to its host
        const inner = [...(el.shadowRoot ? el.shadowRoot.children : el.children)]
          .filter(k => !/^(STYLE|SCRIPT|LINK)$/.test(k.tagName) && (k.offsetHeight || holds(k, fr)));
        if (inner.length !== 1) break;
        tight.push(el);
      }
      // Some wrappers have no box of their own (display: contents): the space is the outermost one that has.
      const outer = [...tight].reverse().find(el => el.offsetHeight) || fr;
      const pad = parseFloat(getComputedStyle(box).paddingBottom) || 0;
      const used = kids[kids.length - 1].getBoundingClientRect().bottom - box.getBoundingClientRect().top
                   + box.scrollTop;
      const want = Math.max(MIN_FRAME, Math.round(outer.offsetHeight + (h - pad - used)));
      if (Math.abs(want - fr.offsetHeight) <= 2 && tight.every(el => Math.abs(el.offsetHeight - want) <= 2)) continue;
      // Grow or shrink the frame and its wrappers together, so what sits below the frame moves with it and nothing
      // overlaps or leaves a gap.
      for (const el of tight) { el.style.height = want + "px"; el.style.flex = "0 0 auto"; }
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


# Everything themed on the server (the chrome CSS above, every embedded viewer) reads st.context.theme.type, which
# Streamlit does not update when the user switches light/dark in its settings menu: that switch repaints Streamlit's
# own widgets but does not rerun the script, so our colours stay on the old theme. This watches the theme Streamlit
# is actually showing (the page background it sets on <body>) and reruns once when it differs from the rendered one.
THEME_WATCH_JS = """
let sent = "";
export default function (component) {
  const { data, setTriggerValue } = component;
  const live = () => {
    const m = getComputedStyle(document.body).backgroundColor.match(/\\d+(\\.\\d+)?/g);
    if (!m) return null;
    const [r, g, b] = m.map(Number);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 128 ? "light" : "dark";
  };
  const check = () => {
    const now = live();
    if (!now || now === data.theme) return;
    const pair = data.theme + ">" + now;   // one rerun per mismatch, never a loop
    if (pair === sent) return;
    sent = pair;
    setTriggerValue("changed", { theme: now, at: Date.now() });
  };
  // The theme switch next to the menu: a moon in light mode, a sun in dark mode. It picks Light or Dark in
  // Streamlit's own menu (hidden while it does), so Streamlit keeps the choice as if the user had made it there.
  const mount = () => {
    const bar = document.querySelector('[data-testid="stToolbarActions"]');
    if (!bar) return;
    let b = document.getElementById("pm-theme");
    if (!b || b.parentNode !== bar) {
      b?.remove();
      b = document.createElement("button");
      b.id = "pm-theme"; b.type = "button";
      b.innerHTML = '<span aria-hidden="true" translate="no"></span>';
      b.addEventListener("click", flip);
      bar.appendChild(b);
    }
    const dark = live() === "dark", icon = dark ? "light_mode" : "dark_mode";
    const label = dark ? "Switch to light theme" : "Switch to dark theme";
    if (b.firstChild.textContent !== icon) b.firstChild.textContent = icon;
    if (b.title !== label) { b.title = label; b.setAttribute("aria-label", label); }
  };
  const wait = ms => new Promise(r => setTimeout(r, ms));
  async function flip() {
    const want = live() === "dark" ? "Light" : "Dark", sel = `[data-testid="stMainMenuItem-theme-${want}"]`;
    document.body.classList.add("pm-theming");
    try {
      let item = document.querySelector(sel);
      if (!item) {
        document.querySelector('[data-testid="stMainMenuButton"]')?.click();
        for (let i = 0; i < 40 && !(item = document.querySelector(sel)); i++) await wait(25);
      }
      if (!item) return;
      item.click();
      item.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true }));
      // Streamlit keeps the theme per page path: keep every page on the same one
      try {
        for (const k of Object.keys(localStorage)) if (k.startsWith("stActiveTheme-")) localStorage.setItem(k, JSON.stringify(want));
      } catch (e) {}
    } finally {
      await wait(150);
      document.body.classList.remove("pm-theming");
      mount();
    }
  }
  clearInterval(globalThis.__pmThemeWatch);
  globalThis.__pmThemeWatch = setInterval(() => { check(); mount(); }, 300);
  check();
  mount();
}
"""
_theme_watch = st.components.v2.component("projectmodel.theme_watch", js=THEME_WATCH_JS)


RAIL_LOGO = """<div class="rail-logo" title="Project Model"><span aria-hidden="true"
style="font-family: 'Material Symbols Rounded'; font-size: 24px; color: #EE3124">hub</span></div>"""


def rail(areas: list[tuple[str, str, list]], current) -> None:
    """The fixed icon rail on the left: one icon per area, linking to the area's first page."""
    st.html(chrome_css())
    with st.container(key="rail"):
        st.html(RAIL_LOGO)
        _fit(key="fit")
        _theme_watch(data={"theme": theme()}, key="theme_watch", on_changed_change=lambda: None)
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


AREA_SUBTITLES = {
    "Overview": "Why a knowledge graph of the building matters, how it is built, and what a complete one looks like.",
    "Projects": "Every building mapped into the knowledge graph, and a guided setup to add one.",
    "Shared knowledge": "What every project reuses: the knowledge model and the team's tribal knowledge.",
}


def page_title(title: str) -> None:
    """A page header's title: 24px extra-bold."""
    st.html(f'<p class="page-title">{html.escape(title)}</p>', width="content")


def _tabs_row(pages: list, current) -> None:
    """The second header row, the same on every page: the area's pages as tabs, the page's own tools at the right
    end (page_tools)."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        chips(pages, current)
        st.space("stretch")
        st.session_state["_page_tools"] = st.container(horizontal=True, width="content", gap="small",
                                                       vertical_alignment="center")


def area_header(title: str, pages: list, current) -> None:
    """Areas without a project (Overview, Projects, Shared knowledge). Same rows as a project page's header, so the
    title and tabs sit at the same place on every page: the title with a one-line description, then the tabs."""
    with st.container(key="areabar", gap="small"):
        with st.container(key="titlebar", horizontal=True, vertical_alignment="center", gap="small"):
            page_title(title)
            if sub := AREA_SUBTITLES.get(title, ""):
                st.caption(sub, width="content")
            st.space("stretch")
            every = list_projects(get_store())
            projects = main_projects(every)
            if projects:
                # Show the active building (its main project) without changing which project is active.
                cur = active_project(every)
                st.session_state["_project_go"] = cur if cur in projects else next(
                    (p for p in projects if p.split("/")[0] == cur.split("/")[0]), projects[0])
                with st.container(key="projpick", width="content"):
                    st.selectbox("Project", projects, key="_project_go", format_func=lambda p: site_of(p).name,
                                 label_visibility="collapsed", on_change=_go_project,
                                 help="Open a building: its project pages, from the tree")
            top_tools()
        _tabs_row(pages, current)
    if st.session_state.pop("_project_open", False):
        st.switch_page("tree_app.py")


def _go_project() -> None:
    set_project(st.session_state["_project_go"])
    st.session_state["_project_open"] = True


def _initials(name: str) -> str:
    parts = [w for w in name.replace(".", " ").split() if w[:1].isalnum()]
    return ("".join(w[0] for w in parts[:2]) or "?").upper()


def _set_author() -> None:
    st.session_state["author"] = st.session_state["_author_input"].strip()


def _ai_today() -> tuple[int, float]:
    row = get_store().conn.execute("SELECT count(*), coalesce(sum(cost_usd), 0) FROM llm_calls "
                                   "WHERE created_at >= date('now')").fetchone()
    return row[0], row[1]


def top_tools() -> None:
    """The right end of every page's title row: the agent panel, settings, and who you are."""
    open_ = st.session_state.get("dock_open", True)
    with st.container(key="toptools", horizontal=True, vertical_alignment="center", gap="small", width="content"):
        st.button("", icon=":material/right_panel_close:" if open_ else ":material/right_panel_open:",
                  key="top_agent", on_click=lambda: st.session_state.update(dock_open=not open_),
                  help="Hide the agent" if open_ else "Show the agent")
        with st.container(key="top_settings", width="content"), st.popover("", icon=":material/settings:",
                                                                            help="Settings"):
            from projectmodel.ai.calls import default_router
            st.markdown("**Agent**")
            # The toggles mirror the panel's own buttons, so they are set from its state on every run.
            st.session_state.update(_top_open=open_, _top_wide=bool(st.session_state.get("dock_wide")))
            st.toggle("Show the agent panel", key="_top_open",
                      on_change=lambda: st.session_state.update(dock_open=st.session_state["_top_open"]))
            st.toggle("Wide panel", key="_top_wide",
                      on_change=lambda: st.session_state.update(dock_wide=st.session_state["_top_wide"]))
            st.divider()
            st.markdown("**Model calls**")
            r = default_router()
            if r.ready:
                n, usd = _ai_today()
                st.caption(f"Vertex AI · project {r.config.project} · region {r.config.region}  \n"
                           f"Today: {n} calls · ${usd:.2f}. Every call is logged with its input, output and cost.")
            else:
                st.caption(f"Off: {r.why_not_ready()}")
        author = st.session_state.get("author", "")
        if st.session_state.get("_author_input") != author:
            st.session_state["_author_input"] = author
        with st.container(key="top_me", width="content"), st.popover(_initials(author), help=author or "Who are you?"):
            st.text_input("Your name", key="_author_input", on_change=_set_author, placeholder="First and last name",
                          help="Recorded with your notes, answers and confirmations, and used by the agent to "
                               "remember what you told it.")
            st.caption("There are no accounts yet: the name stays with this browser tab.")


def _pick_project() -> None:
    """The project picker changed: open that building (its richest input) on every project page."""
    set_project(st.session_state["_project_pick"])


def project_header(store: Store, sections: list, current, all_projects) -> None:
    """The top of every project page, in the same rows as every other page: the building's name, role and size,
    with a link back to all projects and the project picker at the right; then the project's pages as tabs. The picker is re-derived from the active project on every
    run, so deep links, the Projects page and this control always agree. Each building shows its richest input
    (names + folders): the names-only input is kept for scoring, not for browsing."""
    projects = list_projects(store)
    if not projects:
        st.warning("No mapped projects yet. Run: .venv/bin/python scripts/run_mapper.py alpha names_paths")
        return
    shown = main_projects(projects)
    project = active_project(projects)
    if project not in shown:  # an old link to the names-only input: show the building's main project
        project = next(p for p in shown if p.split("/")[0] == project.split("/")[0])
        set_project(project)
    st.session_state["_project_pick"] = project
    site = site_of(project)
    from projectmodel.app import screen
    screen.project(project, site.name)
    with st.container(key="projbar", gap="small"):
        with st.container(key="titlebar", horizontal=True, vertical_alignment="center", gap="small"):
            page_title(site.name)
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
            st.page_link(all_projects, label="All projects", icon=":material/apps:")
            with st.container(key="projpick", width="content"):
                st.selectbox("Project", shown, key="_project_pick", format_func=lambda p: site_of(p).name,
                             label_visibility="collapsed", on_change=_pick_project,
                             help="Every project page shows this building. Switch it here at any time.")
            top_tools()
        _tabs_row(sections, current)


def page_tools():
    """The page's own tools, at the right end of the header row; in place when the page runs on its own (tests)."""
    return st.session_state.pop("_page_tools", None) or st.container(horizontal=True, horizontal_alignment="right")
