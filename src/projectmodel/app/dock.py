"""The agent dock (spec-agent §3): on the right of every page, with context chips, the conversation and the input.

main.py calls `open_dock()` before the page runs and `close_dock()` after it:

  open_dock    draws the dock's frame: header, the chips as they were (plain), the conversation, the input; and
               answers a message just sent, with the chips the person saw when they sent it
  close_dock   the page has published what it shows (app/screen.py): the chips are redrawn from it, each with
               pin and drop. A page that stops early (st.stop) keeps the chips drawn by open_dock.

The dock keeps its conversation across page changes (session state). Collapsed, it is one button at the bottom right.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import streamlit as st

from projectmodel.agent.context import Chip, chips_for, context_packet, merge_chips
from projectmodel.app import screen
from projectmodel.app.shell import THEME, theme

WIDTH = 400
WIDE = 600
GAP = 14  # as between the page's boxes (shell: row gap and FIT_JS GAP)


@dataclass
class Slots:
    chips: object  # st.empty for the chips row


def width() -> int:
    return WIDE if st.session_state.get("dock_wide") else WIDTH


def _css(open_: bool) -> str:
    c = THEME[theme()]
    w = width()
    # Open, the dock is a card like the page's boxes: the header runs across the whole width, and the card sits under
    # it at the right, its top level with the first box (--pm-dock-top, measured by shell.FIT_JS), GAP from the
    # screen's right and bottom edges and GAP from the boxes on its left.
    pad = (f""".block-container {{ padding-right: {w + 2 * GAP}px !important; }}
[data-testid="stLayoutWrapper"]:has(> .st-key-areabar), [data-testid="stLayoutWrapper"]:has(> .st-key-projbar) {{
  width: calc(100% + {w + GAP}px) !important; max-width: none !important; }}""" if open_ else "")
    soft = f"color-mix(in srgb, {c['accent']} 12%, transparent)"
    return f"""<style>
{pad}
[data-testid="stLayoutWrapper"]:has(> .st-key-dock), [data-testid="stLayoutWrapper"]:has(> .st-key-dock_fab),
[data-testid="stElementContainer"]:has(> .st-key-dock_fab) {{ display: contents; }}
.st-key-dock {{ position: fixed; right: {GAP}px; top: var(--pm-dock-top, 140px); bottom: {GAP}px; width: {w}px;
  z-index: 999990; background: {c["card"]}; border: 1px solid {c["card"]}; border-radius: 10px;
  box-shadow: {c["shadow"]}; padding: 12px 14px 12px; gap: 10px; overflow: hidden; transition: width .2s ease; }}
.st-key-dock .ms {{ font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal; line-height: 1; }}

/* Header: avatar, title and the model that answers, then the controls */
.st-key-dock_head {{ padding-bottom: 10px; border-bottom: 1px solid {c["line"]}; gap: 2px !important;
  flex-wrap: nowrap !important; }}
.st-key-dock_head > [data-testid="stElementContainer"]:first-child {{ min-width: 0; flex: 0 1 auto; overflow: hidden; }}
.dock-titles {{ min-width: 0; }}
.dock-sub {{ overflow: hidden; text-overflow: ellipsis; }}
/* icon-only popovers: no chevron */
.st-key-dock_hist [data-testid="stPopoverButton"] div[aria-hidden="true"],
.st-key-dock_sees [data-testid="stPopoverButton"] div[aria-hidden="true"],
.st-key-top_settings [data-testid="stPopoverButton"] div[aria-hidden="true"],
.st-key-top_me [data-testid="stPopoverButton"] div[aria-hidden="true"] {{ display: none; }}
.st-key-dock_head [data-testid="stHtml"] > div, .st-key-dock_head .stHtml {{ display: flex; align-items: center;
  gap: 10px; }}
.dock-avatar {{ position: relative; width: 38px; height: 38px; border-radius: 50%; flex: none; display: grid;
  place-items: center; background: {c["card2"]}; border: 1px solid {c["line"]}; }}
.dock-avatar .ms {{ font-size: 21px; background: linear-gradient(135deg, {c["accent"]}, #C77DFF); -webkit-background-clip: text;
  background-clip: text; color: transparent; }}
.dock-avatar i {{ position: absolute; top: -1px; right: -1px; width: 10px; height: 10px; border-radius: 50%;
  background: {c["mute"]}; border: 2px solid {c["card"]}; }}
.dock-avatar.on i {{ background: {c["good"]}; }}
.dock-titles p {{ margin: 0; line-height: 1.25; }}
.dock-title {{ font-size: 16px; font-weight: 700; color: {c["text"]}; }}
.dock-sub {{ font-size: 12.5px; color: {c["mute"]}; white-space: nowrap; }}
.st-key-dock_head [data-testid^="stBaseButton-"], .st-key-dock_hist [data-testid="stPopoverButton"] {{
  min-height: 32px; height: 32px; width: 32px; padding: 0; justify-content: center; border: 0 !important;
  background: transparent; border-radius: 6px; }}
.st-key-dock_head [data-testid^="stBaseButton-"]:hover, .st-key-dock_hist [data-testid="stPopoverButton"]:hover {{
  background: {c["card2"]}; text-decoration: none; }}
.st-key-dock_head [data-testid="stIconMaterial"] {{ font-size: 19px; color: {c["text2"]} !important; }}
.st-key-dock_hist [data-testid="stPopoverButton"] svg {{ display: none; }}  /* no chevron on an icon button */
[class*="st-key-dhist_"] [data-testid^="stBaseButton-"] {{ justify-content: flex-start; text-align: left; }}
[class*="st-key-dhist_"] [data-testid^="stBaseButton-"] p {{ overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; font-weight: 500; }}

/* Context: what the agent sees, as tags */
.st-key-dock_chips {{ gap: 6px !important; flex-wrap: wrap; align-items: center; }}
.dock-ctx {{ font-size: 11px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: {c["mute"]};
  margin: 0 2px 0 0; }}
.dock-chip {{ display: inline-flex; align-items: center; gap: 5px; max-width: 100%; height: 26px; padding: 0 10px;
  border-radius: 13px; border: 1px solid {c["line"]}; font-size: 12.5px; color: {c["text"]};
  background: {c["card2"]}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 0 6px 6px 0; }}
.dock-chip .ms {{ font-size: 15px; color: {c["accent"]}; }}
.dock-crumb {{ font-size: 12px; color: {c["mute"]}; margin: 0; }}
[class*="st-key-dchip_"] {{ border: 1px solid {c["line"]}; border-radius: 13px; padding: 0 3px 0 10px !important;
  background: {c["card2"]}; gap: 1px !important; height: 28px; max-width: 100%; transition: border-color .12s; }}
[class*="st-key-dchip_"]:hover {{ border-color: {c["tag_line"]}; }}
[class*="st-key-dchip_pin_"] {{ border-color: {c["accent"]}; background: {soft}; }}
[class*="st-key-dchip_"] .chip-label {{ display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px;
  color: {c["text"]}; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }}
[class*="st-key-dchip_"] .chip-label .ms {{ font-size: 15px; color: {c["accent"]}; }}
[class*="st-key-dchip_"] .chip-label small {{ color: {c["mute"]}; font-size: 11px; }}
[class*="st-key-dchip_"] [data-testid^="stBaseButton-"] {{ min-height: 20px; height: 20px; width: 20px; padding: 0;
  border: 0; border-radius: 50%; justify-content: center; }}
[class*="st-key-dchip_"] [data-testid^="stBaseButton-"]:hover {{ background: {c["line"]}; text-decoration: none; }}
[class*="st-key-dchip_"] [data-testid="stIconMaterial"] {{ font-size: 14px; color: {c["mute"]} !important; }}
/* the pin shows on hover, and stays on a pinned tag */
[class*="st-key-dchip_"]:not([class*="st-key-dchip_pin_"]) [class*="st-key-dpin_"] {{ opacity: 0;
  transition: opacity .12s; }}
[class*="st-key-dchip_"]:hover [class*="st-key-dpin_"] {{ opacity: 1; }}
[class*="st-key-dchip_pin_"] [class*="st-key-dpin_"] [data-testid="stIconMaterial"] {{ color: {c["accent"]} !important; }}
.st-key-dock_sees [data-testid="stPopoverButton"] {{ min-height: 28px; height: 28px; padding: 0 8px; border: 0;
  background: transparent; }}
.st-key-dock_sees [data-testid="stPopoverButton"] * {{ color: {c["mute"]}; font-size: 12px; }}
.st-key-dock_sees [data-testid="stPopoverButton"] svg {{ display: none; }}

/* Conversation and the welcome */
[data-testid="stLayoutWrapper"]:has(> .st-key-dock_conv) {{ flex: 1 1 0; min-height: 0; }}
.st-key-dock_conv {{ height: 100%; overflow-y: auto; padding-right: 4px; }}
.dock-welcome {{ border-left: 3px solid {c["accent"]}; padding: 2px 0 2px 12px; margin: 6px 0 6px; }}
.dock-welcome p {{ margin: 0; font-size: 19px; font-weight: 700; color: {c["text"]}; }}
.dock-welcome span {{ display: block; margin-top: 4px; font-size: 13px; color: {c["mute"]}; line-height: 1.4; }}
[class*="st-key-dsug_"] [data-testid^="stBaseButton-"] {{ justify-content: flex-start; min-height: 52px; height: auto;
  padding: 10px 14px; border-radius: 10px; border: 1px solid {c["line"]} !important; background: {c["card2"]};
  text-align: left; }}
[class*="st-key-dsug_"] [data-testid^="stBaseButton-"] > div,
[class*="st-key-dsug_"] [data-testid^="stBaseButton-"] > div > span {{ justify-content: flex-start; width: 100%; }}
[class*="st-key-dsug_"] [data-testid^="stBaseButton-"]:hover {{ border-color: {c["accent"]} !important;
  background: {soft}; text-decoration: none; }}
[class*="st-key-dsug_"] [data-testid^="stBaseButton-"] p {{ color: {c["text"]}; font-weight: 600; font-size: 14px;
  white-space: normal; text-align: left; }}
[class*="st-key-dsug_"] [data-testid="stIconMaterial"] {{ font-size: 20px; color: {c["accent"]} !important;
  margin-right: 6px; }}

/* The composer: the input with its microphone and send, and under it the routing and model pills */
.st-key-dock_compose {{ border: 1px solid {c["line"]}; border-radius: 14px; background: {c["card2"]};
  padding: 6px 8px 8px !important; gap: 4px !important; }}
.st-key-dock_compose:focus-within {{ border-color: {c["accent"]}; }}
.st-key-dock_compose [data-testid="stChatInput"], .st-key-dock_compose [data-testid="stChatInput"] > div {{
  border: 0 !important; background: transparent !important; box-shadow: none !important; }}
.st-key-dock_compose [data-testid="stChatInputTextArea"] {{ background: transparent !important; font-size: 14.5px; }}
.st-key-dock_pills {{ gap: 8px !important; padding: 0 4px; }}
.st-key-dock_pills [data-testid="stPopoverButton"] {{ min-height: 30px; height: 30px; padding: 0 10px;
  border-radius: 8px; border: 1px solid {c["line"]}; background: {c["card"]}; }}
.st-key-dock_pills [data-testid="stPopoverButton"]:hover {{ border-color: {c["tag_line"]}; background: {c["card"]}; }}
.st-key-dock_pills [data-testid="stPopoverButton"] p {{ font-size: 13px; font-weight: 500; letter-spacing: 0;
  color: {c["text"]}; }}
.st-key-dpill_route [data-testid="stIconMaterial"] {{ color: #C77DFF !important; }}
.st-key-dpill_model [data-testid="stIconMaterial"] {{ color: {c["text2"]} !important; }}
.st-key-dock_pills [data-testid="stPopoverButton"] svg {{ color: {c["mute"]}; }}

/* Hidden: one button at the bottom right brings it back */
.st-key-dock_fab {{ position: fixed !important; right: {GAP + 6}px; bottom: {GAP + 6}px; z-index: 999991;
  width: auto !important; }}
.st-key-dock_fab [data-testid^="stBaseButton-"] {{ border-radius: 24px; min-height: 48px; padding: 0 20px;
  box-shadow: 0 6px 18px rgba(0,0,0,.28); }}
</style>"""


KIND_WORD = {"project": "project", "page": "page", "equipment": "equipment", "point": "point", "location": "place",
             "sequence": "sequence", "document": "document", "floor": "floor"}


def _chip_html(c: Chip, cls: str = "dock-chip") -> str:
    return (f'<span class="{cls}" title="{html.escape(KIND_WORD.get(c.kind, c.kind))}: {html.escape(c.id)}">'
            f'<span class="ms" aria-hidden="true">{c.icon}</span>{html.escape(c.label)}</span>')


def _toggle(open_: bool) -> None:
    st.session_state["dock_open"] = open_


def _drop(key: str) -> None:
    st.session_state.setdefault("dock_dropped", set()).add(key)
    st.session_state["dock_pinned"] = [c for c in st.session_state.get("dock_pinned", []) if c.key != key]


def _pin(chip: Chip) -> None:
    pinned = st.session_state.setdefault("dock_pinned", [])
    if chip in pinned:
        pinned.remove(chip)
    else:
        pinned.append(chip)


def _restore() -> None:
    st.session_state["dock_dropped"] = set()


def active_chips() -> list[Chip]:
    """The chips the agent uses now: this run's page chips (or the last run's, before the page has run), minus the
    dropped ones, plus the pinned ones."""
    page = st.session_state.get("_dock_page_chips", [])
    return merge_chips(page, st.session_state.get("dock_pinned", []), st.session_state.get("dock_dropped", set()))


def open_dock(store) -> Slots | None:
    open_ = st.session_state.setdefault("dock_open", True)
    st.html(_css(open_))
    if not open_:
        with st.container(key="dock_fab", width="content"):
            st.button("Agent", icon=":material/auto_awesome:", key="dock_show", on_click=_toggle, args=(True,),
                      type="primary", help="Open the agent")
        return None
    from projectmodel.app import agent_ui
    with st.container(key="dock"):
        agent_ui.header(store)
        chips = st.empty()
        with chips.container(key="dock_chips_plain", horizontal=True, gap="small"):
            st.html('<span class="dock-ctx">Context</span>' + ("".join(_chip_html(c) for c in active_chips()) or
                    '<span class="dock-crumb">Nothing selected: the agent sees the page only.</span>'))
        agent_ui.conversation(store, active_chips(), screen.current())
    return Slots(chips)


def close_dock(slots: Slots | None, store) -> None:
    """After the page ran: chips from what it published, with pin and drop."""
    state = screen.current()
    page_chips = chips_for(state)
    prev = st.session_state.get("_dock_page_chips")
    st.session_state["_dock_page_chips"] = page_chips
    if prev is not None and {c.key for c in prev} != {c.key for c in page_chips}:
        # A new selection: chips dropped earlier stay dropped only while they are on screen.
        st.session_state["dock_dropped"] = {k for k in st.session_state.get("dock_dropped", set())
                                            if k in {c.key for c in page_chips}}
    if slots is None:
        return
    pinned = st.session_state.get("dock_pinned", [])
    chips = active_chips()
    with slots.chips.container(key="dock_chips", horizontal=True, gap="small", vertical_alignment="center"):
        st.html('<span class="dock-ctx">Context</span>', width="content")
        if not chips:
            st.html('<span class="dock-crumb">Nothing selected: the agent sees the page only.</span>', width="content")
        for i, c in enumerate(chips):
            on = c in pinned
            with st.container(key=f"dchip_{'pin_' if on else ''}{i}", horizontal=True, vertical_alignment="center",
                              width="content"):
                st.html(_chip_html(c, "chip-label"), width="content")
                st.button("", icon=":material/keep:" if not on else ":material/keep_off:", key=f"dpin_{i}",
                          type="tertiary", on_click=_pin, args=(c,),
                          help="Unpin" if on else "Pin: keep this in the agent's context on every page")
                st.button("", icon=":material/close:", key=f"ddrop_{i}", type="tertiary", on_click=_drop,
                          args=(c.key,), help="Leave this out of the agent's context")
        if st.session_state.get("dock_dropped"):
            st.button("Restore", key="dock_restore", type="tertiary", on_click=_restore,
                      help="Bring back the tags you left out")
        with st.container(key="dock_sees", width="content"), st.popover(
                "", icon=":material/visibility:", help="What the agent sees: the context sent with your question"):
            st.session_state["_dock_sees"] = st.empty()
    from projectmodel.app import agent_ui
    agent_ui.show_packet(store, chips, state)
    agent_ui.fill_welcome(chips)


def packet_for(store, chips: list[Chip], state) -> dict:
    """The context packet for these chips (used by the agent and shown under 'What the agent sees')."""
    from projectmodel.app import agent_ui
    return context_packet(chips, state, agent_ui.graph_tools(store, _project_of(chips)), agent_ui.project_summary(
        store, _project_of(chips)))


def _project_of(chips: list[Chip]) -> str | None:
    return next((c.id for c in chips if c.kind == "project"), None)
