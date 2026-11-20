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
GAP = 14  # as between the page's boxes (shell: row gap and FIT_JS GAP)


@dataclass
class Slots:
    chips: object  # st.empty for the chips row


def _css(open_: bool) -> str:
    c = THEME[theme()]
    # Open, the dock is a card like the page's boxes: the header runs across the whole width, and the card sits under
    # it at the right, its top level with the first box (--pm-dock-top, measured by shell.FIT_JS), GAP from the
    # screen's right and bottom edges and GAP from the boxes on its left.
    pad = (f""".block-container {{ padding-right: {WIDTH + 2 * GAP}px !important; }}
[data-testid="stLayoutWrapper"]:has(> .st-key-areabar), [data-testid="stLayoutWrapper"]:has(> .st-key-projbar) {{
  width: calc(100% + {WIDTH + GAP}px) !important; max-width: none !important; }}""" if open_ else "")
    return f"""<style>
{pad}
[data-testid="stLayoutWrapper"]:has(> .st-key-dock), [data-testid="stLayoutWrapper"]:has(> .st-key-dock_fab) {{
  display: contents; }}
.st-key-dock {{ position: fixed; right: {GAP}px; top: var(--pm-dock-top, 140px); bottom: {GAP}px; width: {WIDTH}px;
  z-index: 999990; background: {c["card"]}; border: 1px solid {c["card"]}; border-radius: 10px;
  box-shadow: {c["shadow"]}; padding: 14px 16px 12px; gap: 10px; overflow: hidden; }}
.st-key-dock_head {{ padding-bottom: 10px; border-bottom: 1px solid {c["line"]}; }}
.st-key-dock_head p.dock-title {{ margin: 0; font-size: 13px; font-weight: 700; letter-spacing: 1.6px;
  text-transform: uppercase; color: {c["text"]}; }}
[data-testid="stLayoutWrapper"]:has(> .st-key-dock_conv) {{ flex: 1 1 0; min-height: 0; }}
.st-key-dock_conv {{ height: 100%; overflow-y: auto; padding-right: 4px; }}
.st-key-dock_chips {{ gap: 6px !important; flex-wrap: wrap; }}
.dock-chip {{ display: inline-flex; align-items: center; gap: 5px; max-width: 100%; padding: 3px 9px;
  border-radius: 14px; border: 1px solid {c["tag_line"]}; font-size: 13px; color: {c["text"]};
  background: {c["card2"]}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.dock-chip.pinned {{ border-color: {c["accent"]}; }}
.dock-chip .ms {{ font-family: 'Material Symbols Rounded'; font-size: 16px; color: {c["accent"]}; }}
.dock-crumb {{ font-size: 12px; color: {c["mute"]}; margin: 0; }}
[class*="st-key-dchip_"] {{ border: 1px solid {c["tag_line"]}; border-radius: 14px; padding: 0 2px 0 8px !important;
  background: {c["card2"]}; gap: 0 !important; min-height: 28px; }}
[class*="st-key-dchip_"].pinned, [class*="st-key-dchip_pin_"] {{ border-color: {c["accent"]}; }}
[class*="st-key-dchip_"] [data-testid="stMarkdownContainer"] p {{ font-size: 13px; margin: 0; white-space: nowrap; }}
[class*="st-key-dchip_"] [data-testid^="stBaseButton-"] {{ min-height: 24px; height: 24px; padding: 0 3px;
  border: 0; }}
[class*="st-key-dchip_"] [data-testid^="stBaseButton-"] span {{ font-size: 16px; }}
/* The composer: the input, and under it (inside the same frame) the model pill and the clear button */
.st-key-dock_compose {{ border: 1px solid {c["line"]}; border-radius: 8px; background: {c["input"]};
  padding: 4px 6px 6px !important; gap: 2px !important; }}
.st-key-dock_compose:focus-within {{ border-color: {c["accent"]}; }}
.st-key-dock_compose [data-testid="stChatInput"], .st-key-dock_compose [data-testid="stChatInput"] > div {{
  border: 0 !important; background: transparent !important; box-shadow: none !important; }}
.st-key-dock_compose [data-testid="stChatInputTextArea"] {{ background: transparent !important; }}
.st-key-dock_pills {{ gap: 6px !important; padding: 0 4px; }}
.st-key-dock_pills [data-testid="stSelectbox"] > div > div {{ min-height: 28px; height: 28px; border-radius: 14px;
  font-size: 13px; background: {c["card2"]}; border-color: {c["tag_line"]}; }}
.st-key-dock_pills [data-baseweb="select"] > div {{ min-height: 28px; padding-top: 0; padding-bottom: 0; }}
.st-key-dock_pills [data-testid^="stBaseButton-"] {{ min-height: 28px; height: 28px; }}
.dock-speed {{ font-size: 12px; color: {c["mute"]}; margin: 0; white-space: nowrap; }}
.st-key-dock_fab {{ position: fixed; right: {GAP + 4}px; bottom: {GAP + 4}px; z-index: 999990; }}
.st-key-dock_fab [data-testid^="stBaseButton-"] {{ border-radius: 24px; min-height: 48px;
  box-shadow: 0 4px 14px rgba(0,0,0,.25); }}
</style>"""


def _chip_html(c: Chip, pinned: bool) -> str:
    return (f'<span class="dock-chip{" pinned" if pinned else ""}" title="{html.escape(c.kind)}: {html.escape(c.id)}">'
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
        with st.container(key="dock_fab"):
            st.button("Agent", icon=":material/forum:", key="dock_show", on_click=_toggle, args=(True,),
                      type="primary", help="Open the agent")
        return None
    with st.container(key="dock"):
        with st.container(key="dock_head", horizontal=True, vertical_alignment="center", gap="small"):
            st.html('<p class="dock-title">Agent</p>', width="content")
            from projectmodel.app import agent_ui
            agent_ui.status_badge()
            st.space("stretch")
            st.button("", icon=":material/right_panel_close:", key="dock_hide", type="tertiary",
                      on_click=_toggle, args=(False,), help="Hide the agent")
        chips = st.empty()
        pinned = st.session_state.get("dock_pinned", [])
        with chips.container():
            st.html("".join(_chip_html(c, c in pinned) for c in active_chips()) or
                    '<p class="dock-crumb">Nothing selected: the agent sees the page only.</p>')
        from projectmodel.app import agent_ui
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
    with slots.chips.container(key="dock_chips", horizontal=True, gap="small"):
        if not chips:
            st.html('<p class="dock-crumb">Nothing selected: the agent sees the page only.</p>')
        for i, c in enumerate(chips):
            on = c in pinned
            with st.container(key=f"dchip_{'pin_' if on else ''}{i}", horizontal=True, vertical_alignment="center",
                              width="content"):
                st.markdown(f":material/{c.icon}: {c.label}")
                st.button("", icon=":material/keep:" if not on else ":material/keep_off:", key=f"dpin_{i}",
                          type="tertiary", on_click=_pin, args=(c,),
                          help="Unpin" if on else "Pin: keep this in the agent's context on every page")
                st.button("", icon=":material/close:", key=f"ddrop_{i}", type="tertiary", on_click=_drop,
                          args=(c.key,), help="Leave this out of the agent's context")
        if st.session_state.get("dock_dropped"):
            st.button("Restore", key="dock_restore", type="tertiary", on_click=_restore,
                      help="Bring back the chips you left out")
    from projectmodel.app import agent_ui
    agent_ui.show_packet(store, chips, state)


def packet_for(store, chips: list[Chip], state) -> dict:
    """The context packet for these chips (used by the agent and shown under 'What the agent sees')."""
    from projectmodel.app import agent_ui
    return context_packet(chips, state, agent_ui.graph_tools(store, _project_of(chips)), agent_ui.project_summary(
        store, _project_of(chips)))


def _project_of(chips: list[Chip]) -> str | None:
    return next((c.id for c in chips if c.kind == "project"), None)
