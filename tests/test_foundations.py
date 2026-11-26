"""What the agent knows about the app and every project (agent/foundations.py)."""

import re
from pathlib import Path

from projectmodel.agent.chat import Agent
from projectmodel.agent.foundations import PAGES, foundations_text, projects_text
from projectmodel.db.store import Store

MAIN = Path(__file__).resolve().parents[1] / "src/projectmodel/app/main.py"


def test_every_page_in_the_app_is_described():
    titles = set(re.findall(r'st\.Page\([^)]*?title="([^"]+)"', MAIN.read_text(), re.S))
    assert titles <= {p for _, p, _ in PAGES}, titles - {p for _, p, _ in PAGES}


def test_foundations_name_the_architecture_examples_and_status():
    t = foundations_text()
    for word in ("Knowledge graph", "Mapper", "Add a building", "MSU", "W11", "Vertex AI"):
        assert word in t
    assert "liberty" not in t.lower()  # held out: never shown


def test_projects_text_lists_the_store(tmp_path):
    store = Store(tmp_path / "kg.sqlite")
    assert "none mapped yet" in projects_text(store)


def test_the_agent_reads_the_app_context():
    class R:
        ready = True
    sys_prompt, _ = Agent(R(), app_context="APP-CONTEXT-MARK").system()
    assert "APP-CONTEXT-MARK" in sys_prompt and "need no citation" in sys_prompt
    assert "APP-CONTEXT-MARK" not in Agent(R()).system()[0]
