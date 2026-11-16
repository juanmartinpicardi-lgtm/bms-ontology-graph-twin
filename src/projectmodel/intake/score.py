"""Score a guided setup against an answer key (data/ground_truth/<site>/), for test buildings only. The answer key is
never read by the readers: it is used here, after the fact, to measure them.

Each measure is given twice: as read by the machine alone, and with the person's answers applied.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from . import tags
from .model import building
from .state import Intake

GT = Path(__file__).resolve().parents[3] / "data/ground_truth"


def answer_keys() -> list[str]:
    return sorted(p.parent.name for p in GT.glob("*/spaces.csv"))


def _rows(site: str, name: str) -> list[dict]:
    return list(csv.DictReader((GT / site / name).open()))


@lru_cache
def _is_a(cls: str, ancestor: str) -> bool:
    try:
        return _km().is_a(cls, ancestor)
    except Exception:
        return False


@lru_cache
def _km():
    from projectmodel.knowledge_model import load_knowledge_model
    return load_knowledge_model()


class _MachineOnly(Intake):
    """The same intake with every answer ignored."""

    def __init__(self, it: Intake):
        self.slug, self.dir, self.s = it.slug, it.dir, dict(it.s, decisions={})


def score(it: Intake, site: str) -> list[dict]:
    with_you, machine = building(it), building(_MachineOnly(it))
    spaces = [r for r in _rows(site, "spaces.csv") if r["kind"] == "room"]
    eq_gt = {n: r for r in _rows(site, "equipment.csv") if (n := tags.normal(r["tag"]))}
    pts_gt = {r["bms_name"]: r for r in _rows(site, "points.csv")}
    rel_gt = _rows(site, "relations.csv")
    gt_ids = {r["equip_id"]: n for n, r in eq_gt.items()}
    gt_feeds = {(gt_ids[r["src"]], gt_ids[r["dst"]]) for r in rel_gt
                if r["rel"] == "feeds" and r["src"] in gt_ids and r["dst"] in gt_ids}  # unit -> unit only
    out = []

    def row(measure, what, fn):
        m, y = fn(machine), fn(with_you)
        out.append({"measure": measure, "what": what, "machine": m[0], "with you": y[0], "out of": m[1]})

    gt_rooms = {r["number"]: r for r in spaces}
    row("Rooms found", "room numbers on the plans", lambda b: (len(gt_rooms.keys() & {r["number"] for r in b["rooms"]}), len(gt_rooms)))
    row("Room names right", "same name as the answer key",
        lambda b: (sum(1 for r in b["rooms"] if r["number"] in gt_rooms and r["name"].upper() == gt_rooms[r["number"]]["name"].upper()), len(gt_rooms)))
    row("Equipment found", "units in the answer key with a tag",
        lambda b: (len(eq_gt.keys() & b["equip"].keys()), len(eq_gt)))
    row("Equipment class right", "Brick class of the units found",
        lambda b: (sum(1 for n, e in b["equip"].items() if n in eq_gt and e["class"] == eq_gt[n]["brick_class"]),
                   len(eq_gt.keys() & b["equip"].keys())))
    terminals = {n: r for n, r in eq_gt.items() if r["kind"] in ("vav", "vave", "fvav")}
    row("Box serves the right room", "terminal units, room from the answer key",
        lambda b: (sum(1 for n, r in terminals.items()
                       if n in b["equip"] and f"td-room-{b['equip'][n]['room']}" == r["space_id"]), len(terminals)))
    plan_rooms = {p["data"]["normal"]: p["data"].get("room") for p in it.facts(kind="placement")}
    plan_ok = sum(1 for n, r in terminals.items() if f"td-room-{plan_rooms.get(n)}" == r["space_id"])
    out.append({"measure": "Box room from the floor plan alone", "what": "before the submittal's room schedule",
                "machine": plan_ok, "with you": plan_ok, "out of": len(terminals)})
    row("Feeds found", "AHU → box, pump → chiller, chiller → AHU",
        lambda b: (len(gt_feeds & {(r["data"]["src"], r["data"]["dst"]) for r in b["relations"] if r["data"]["rel"] == "feeds"}),
                   len(gt_feeds)))
    row("Points found", "Metasys references in the answer key",
        lambda b: (len(pts_gt.keys() & {p["data"]["ref"] for p in b["points"]}), len(pts_gt)))

    def classes(b, broad):
        found = [(p["data"]["class"], pts_gt[p["data"]["ref"]]["brick_class"]) for p in b["points"] if p["data"]["ref"] in pts_gt]
        ok = sum(1 for c, g in found if c == g or (broad and c and _is_a(g, c)))
        return ok, len(found)
    row("Point class exact", "same Brick class", lambda b: classes(b, False))
    row("Point class right or broader", "same class, or a parent of it (Damper_Command for Damper_Position_Command)",
        lambda b: classes(b, True))
    bms_names = {r["bms_name"]: n for n, r in eq_gt.items() if r["bms_name"]}
    row("BMS device linked to its unit", "BMS name → drawing tag",
        lambda b: (sum(1 for n, e in b["equip"].items() if e.get("bms") and bms_names.get(e["bms"]) == n), len(bms_names)))
    return out
