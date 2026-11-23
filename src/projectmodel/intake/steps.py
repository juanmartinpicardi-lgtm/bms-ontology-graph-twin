"""The guided setup: which document each step asks for, what it builds, and running its reader.

Each reader gets what earlier steps established, with the person's answers applied: the schedules are checked against
the tags on the plans, the sequences against the scheduled units, the submittal's rooms against the plan placements,
the BMS against the submittal. A step can be re-read after earlier answers change; answers are kept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import bms, coverage, floorplans, knowledge, point_ai, schedules, sequence_text, submittal
from .state import Intake

ROOT = Path(__file__).resolve().parents[3]
TEST_PACKAGE = ROOT / "test_packages/troop_d"


@dataclass(frozen=True)
class Step:
    id: str
    n: int
    title: str
    ask: str
    types: tuple[str, ...]
    builds: str
    looks_for: str
    test_file: str = ""
    needs: tuple[str, ...] = field(default=())


STEPS = [
    Step("plans", 1, "Floor plans", "Upload the floor plans", ("pdf",),
         "Floors and rooms of the building, and the room each unit sits in or serves.",
         "One sheet per level with room names and numbers, and the equipment tags (VAV-1, AHU-1…).",
         "1_floor_plans.pdf"),
    Step("schedules", 2, "Equipment schedules", "Upload the equipment schedules", ("pdf",),
         "Every unit with its make, model and capacities, its Brick class, and the first connections "
         "(which AHU feeds which box, chilled water from pumps and chillers).",
         "Schedule sheets (M-401 style), and piping or control diagrams if you have them.",
         "2_equipment_schedules.pdf", ("plans",)),
    Step("sequences", 3, "Sequences of operation", "Upload the sequence of operations", ("pdf",),
         "One sequence per equipment type, with its control sections and setpoints, applied to every unit of that "
         "type; gaps and conflicts with the schedules.",
         "The BAS sequence sheet or the sequence section of the specification.",
         "3_sequences.pdf", ("schedules",)),
    Step("submittal", 4, "Controls submittal", "Upload the controls submittal", ("pdf",),
         "Controllers and their network, every point with a Brick class, and a second opinion on which room each "
         "box serves.",
         "The temperature controls contractor's submittal: riser, point schedules, room schedule.",
         "4_controls_submittal.pdf", ("schedules",)),
    Step("bms", 5, "BMS export", "Upload the BMS export", ("csv",),
         "Which BMS device is which unit, and whether the BMS has every point the submittal promised.",
         "A point list exported from the BMS (CSV), one row per object.",
         "5_bms_export.csv", ("submittal",)),
    Step("review", 6, "Review and finish", "Check what was built", (),
         "The building as a knowledge graph: what is confirmed, what is left, and how it scores against the "
         "answer key when there is one.", ""),
]
BY_ID = {s.id: s for s in STEPS}


def run(it: Intake, step_id: str, log) -> int:
    """Read the step's files with what the earlier steps established. Returns the number of facts."""
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        log(msg)

    knowledge.apply(it)
    files = [(it.path(f), f["name"]) for f in it.files(step_id)]
    if not files:
        it.clear_step(step_id)
        return 0
    live = lambda kind: it.facts(kind=kind, live=True)  # noqa: E731
    if step_id == "plans":
        facts = []
        for path, name in files:
            say(f"Reading {name}…")
            facts += floorplans.read(path, name, say)
    elif step_id == "schedules":
        plan = {p["data"]["normal"]: p for p in live("placement")}
        facts = schedules.read(files, plan, say)
    elif step_id == "sequences":
        facts = sequence_text.read(files, [e for e in live("equipment")], say)
    elif step_id == "submittal":
        facts = submittal.read(files, live("equipment"), live("placement"), say)
    elif step_id == "bms":
        facts = []
        for path, name in files:
            facts += bms.read(path, name, live("equipment"), live("controller"), live("point"), say)
    else:
        facts = []
    if step_id in ("submittal", "bms"):  # points the rules leave unsure: the point_class job proposes a class
        point_ai.refine(facts, live("equipment"), say, project=f"intake:{it.slug}",
                        cache=it.s.setdefault("ai_point_class", {}))
    gaps = coverage.check(step_id, facts, files)  # never end with nothing found and nothing said
    for g in gaps:
        say(f"Coverage: {g['label']}")
    facts += gaps
    auto = sum(1 for f in facts if f["conf"] >= 0.9 and not f.get("ask"))
    asks = sum(1 for f in facts if f.get("ask"))
    say(f"Done: {len(facts)} facts — {auto} accepted by rule, {asks} questions for you, "
        f"{len(facts) - auto - asks} proposed and waiting for another source.")
    it.set_step(step_id, facts, lines)
    return len(facts)


def stale(it: Intake, step_id: str) -> list[str]:
    """Earlier steps changed (re-read, or answered) after this one was read: this one may need re-reading."""
    if not it.done(step_id):
        return []
    t = it.read_at(step_id)
    out = [BY_ID[n].title for n in BY_ID[step_id].needs if it.changed_since(n, t)]
    return out + (["The rules you added"] if knowledge.rules_at(it) > t else [])
