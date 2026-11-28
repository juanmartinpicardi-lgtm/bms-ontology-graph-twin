"""D0 (docs/plan-delivery.md): the app's own words say write-back to a tool happens only when the user asks."""

import re
from pathlib import Path

from projectmodel import roadmap
from projectmodel.agent.foundations import PRINCIPLES, foundations_text
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.memory import load_knowledge

ROOT = Path(__file__).resolve().parents[1]
# Statements that say write-back to a tool is forbidden. Reading documents stays read-only ("never changed").
FORBIDDEN = re.compile(r"nothing (is )?(ever )?written back to (a|any|the) (source|bms|tool|station)"
                       r"|never written back( to any (tool|source))?\b|no write-back to any tool"
                       r"|data flows one way\b", re.I)


def test_no_page_memory_entry_or_doc_says_write_back_is_forbidden():
    files = [*ROOT.glob("src/projectmodel/**/*.py"), *ROOT.glob("docs/spec-*.md"), ROOT / "CLAUDE.md",
             ROOT / "knowledge/memory/global.yaml"]
    bad = [f"{f.relative_to(ROOT)}: {m.group(0)}" for f in files for m in FORBIDDEN.finditer(f.read_text())]
    assert not bad, bad


def test_the_app_describes_write_back_as_on_request():
    t = foundations_text().lower()
    assert "only when the user asks" in t or "only when you ask" in t
    assert any("when you ask" in text for _, _, text in PRINCIPLES)


def test_global_memory_carries_the_rule_and_stays_within_its_cap():
    kb = load_knowledge(km=load_knowledge_model())
    g = kb.memory["global"]
    assert g.chars <= g.cap
    entry = next(e for e in g.entries if e.id == "m-0006")
    assert "only when the user asks" in " ".join(entry.text.split())


def test_roadmap_lists_the_delivery_wave():
    want = [f"D{i}" for i in range(13)] + ["Q1", "F1"]
    assert all(i in roadmap.BY_ID for i in want)
    assert {roadmap.BY_ID[i]["wave"] for i in want} == {4}
    status = {i: roadmap.BY_ID[i]["status"] for i in want}
    assert status["D0"] == "done"
    assert all(status[i] == "doing" for i in ("F1", "Q1", "D1", "D2", "D5", "D6", "D7"))
    assert all(status[i] in ("next", "later") for i in ("D3", "D4", "D8", "D9", "D10", "D11", "D12"))
    assert all(roadmap.BY_ID[i]["plain"] for i in want)
    assert {p["wave"] for p in roadmap.PACKAGES} <= set(roadmap.WAVES)
