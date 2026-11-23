"""The screen state every page publishes (spec-agent §4.1), read by the agent dock.

main.py starts it for the page that is about to run; the project header adds the project; a page adds what it is
about while it runs:

    from projectmodel.app import screen
    screen.focus("equipment", node_id, label)       # the one thing the page is about
    screen.select([("point", pid, label)])          # what is selected in a viewer or table
    screen.floor("L2", "Level 2"); screen.scenario("chw_warm", "Chilled water running warm")

Values a viewer sent on an earlier rerun are kept per page with `remember` / `recall`, so the context does not
vanish when something else reruns the page (a chat message, a theme switch).
"""

from __future__ import annotations

import streamlit as st

from projectmodel.agent.context import Ref, ScreenState

KEY = "_screen"


def begin(page) -> ScreenState:
    state = ScreenState(page=page.url_path or "", title=page.title or "")
    st.session_state[KEY] = state
    return state


def current() -> ScreenState:
    state = st.session_state.get(KEY)
    if state is None:  # a page run on its own (tests)
        state = st.session_state[KEY] = ScreenState()
    return state


def project(project_id: str, label: str) -> None:
    s = current()
    s.project, s.project_label = project_id, label


def focus(kind: str, node_id: str, label: str) -> None:
    current().focus = Ref(kind, node_id, label)


def select(items: list[tuple[str, str, str]]) -> None:
    current().selection = [Ref(k, i, lab) for k, i, lab in items]


def floor(floor_id: str, label: str) -> None:
    current().floor = Ref("floor", floor_id, label)


def scenario(key: str, label: str) -> None:
    current().scenario = Ref("scenario", key, label)


def document(doc_id: str, label: str) -> None:
    current().document = Ref("document", doc_id, label)


def setup_step(step_id: str, label: str) -> None:
    current().setup_step = Ref("setup", step_id, label)


def view(**kw) -> None:
    current().view.update({k: v for k, v in kw.items() if v not in (None, "", [])})


def remember(name: str, value) -> None:
    """Keep a viewer's last event for this page and project."""
    s = current()
    st.session_state[f"_screen_mem:{s.page}:{s.project}:{name}"] = value


def recall(name: str, default=None):
    s = current()
    return st.session_state.get(f"_screen_mem:{s.page}:{s.project}:{name}", default)
