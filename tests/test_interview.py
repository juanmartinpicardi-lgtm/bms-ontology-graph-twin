"""Interview mode (interview.py, W10): answers become notes; naming rules said in the asked shape become proposed
conventions that change nothing until a person approves them. Rules only."""
import json
import shutil
from pathlib import Path

import pytest

from projectmodel import curator, interview, notes, review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.agent import voice
from projectmodel.conventions import scopes_for
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.memory import KNOWLEDGE_DIR

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture
def mapped(km, tmp_path, monkeypatch):
    shutil.copytree(KNOWLEDGE_DIR, tmp_path / "knowledge")
    monkeypatch.setenv("PM_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    store = Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), store, P)
    return store


def test_answers_become_notes_and_proposals(mapped, km):
    res = interview.capture(mapped, km, P, {
        "contractor": "Acme Controls; they put the equipment tag first.",
        "abbreviations": "CC means chiller condenser. ZZ means flux capacitor",
        "classes": "Occupied status points are Occupancy_Command. Cost points are money",
        "history": "AHU-3 was replaced in 2022.",
        "operations": "",
    }, "sam")
    assert len(res["notes"]) == 4  # the empty answer files nothing
    ns = notes.notes_by_project(mapped, P)
    assert {n["source"] for n in ns} == {"interview"} and all(n["source_ref"].startswith(res["interview"]) for n in ns)
    assert {n["topic"] for n in ns} == {"naming", "history"}
    props = [curator.proposal(mapped, p) for p in res["proposals"]]
    assert sorted(p["payload"]["kind"] for p in props) == ["abbreviations", "class_hints"]
    abbr = next(p for p in props if p["payload"]["kind"] == "abbreviations")
    assert abbr["payload"]["entry"] == {"token": "cc", "words": ["chiller", "condenser"]}
    hint = next(p for p in props if p["payload"]["kind"] == "class_hints")
    assert hint["payload"]["entry"]["class"] == "Occupancy_Command" and hint["checks"]["would_change"] > 100
    assert [u["answer"] for u in res["unread"]] == ["ZZ means flux capacitor", "Cost points are money"]
    # The same answer again refreshes the pending proposal; it is not duplicated.
    again = interview.capture(mapped, km, P, {"classes": "Occupied status points are Occupancy_Command"}, "sam")
    assert again["proposals"] == [hint["id"]] and len(curator.pending(mapped, P)) == 2


def test_an_approved_interview_rule_applies_on_the_next_run(mapped, km):
    res = interview.capture(mapped, km, P, {"classes": "Occupied status points are Occupancy_Command"}, "sam")
    curator.approve(mapped, km, res["proposals"][0], "ben")
    km2 = load_knowledge_model(conventions=scopes_for(P))
    Mapper(km2).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), mapped, P)
    occ = [n for n in mapped.nodes(P, "point") if n["label"] == "Occupied status"]
    assert all(n["class"] == "Occupancy_Command" and n["method"] == "rule" for n in occ)
    assert all(f"site/alpha:{res['proposals'][0]}" in json.loads(n["attrs"])["convention"] for n in occ)
    assert [x["kind"] for x in curator.learned()] == ["class hint"]


def test_a_rule_that_contradicts_a_person_stays_a_note(mapped, km):
    pid = next(n["id"] for n in mapped.nodes(P, "point") if n["label"] == "Occupied status")
    review.accept(mapped, P, [pid], "cy")  # a person confirmed Occupancy_Status
    res = interview.capture(mapped, km, P, {"classes": "Occupied status points are Occupancy_Command"}, "sam")
    assert res["proposals"] == [] and "contradicts 1" in res["unread"][0]["why"] and len(res["notes"]) == 1


def test_voice_transcripts_map_to_the_questions():
    qs = voice.interview_questions()
    assert [q for q, _ in qs] == [q for q, _, _ in interview.QUESTIONS]
    assert voice.interview_answers(["Acme", "", "Occupied status points are Occupancy_Command"]) == {
        "contractor": "Acme", "classes": "Occupied status points are Occupancy_Command"}
    with pytest.raises(ValueError, match="person"):
        interview.capture(Store(":memory:"), None, P, {}, " ")
