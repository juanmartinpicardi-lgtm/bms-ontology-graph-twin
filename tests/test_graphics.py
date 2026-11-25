"""W9 graphics: template resolution, anchors for every template, 2D equipment / floor / system graphics, and their
rule QA. Synthetic payloads keep most tests independent of any built graph; the page tests use data/kg.sqlite."""

from pathlib import Path

import pytest

from projectmodel.equipment_view import load_anchors, template_for
from projectmodel.graphics.drawing import Drawing
from projectmodel.graphics.equipment2d import render
from projectmodel.graphics.floor import render_floor
from projectmodel.graphics.layouts import LAYOUTS
from projectmodel.graphics.qa import bounds_check, check_drawing, check_equipment
from projectmodel.graphics.system import medium, render_air, render_water
from projectmodel.graphics.vision import cards
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.value_model import describe, sample

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture(scope="module")
def anchors():
    return load_anchors()


# The variant equipment_view derives when every slot has a point: every optional part drawn.
FULL = {"ahu": {"relief_outlet": True, "return_fan": True, "heating_coil": True},
        "chiller": {"water_cooled": True}, "fcu": {"heating_coil": True},
        "vav": {"fan_powered": True, "reheat": True}, "rvav": {"fan_powered": True, "reheat": True}}


def payload(tid: str, km, anchors, fill: bool = True, extra: dict | None = None) -> dict:
    """An equipment payload like equipment_view's: one point per slot (its first class) when `fill`."""
    t = km.templates[tid]
    points, slots = {}, []
    for k, s in enumerate(t.slots):
        a = anchors[tid]["anchors"][s.role]
        pids = []
        if fill:
            pid = f"p{k}"
            cls = s.classes[0]
            points[pid] = {"label": f"{s.role.upper()}-{k}", "cls": cls, "role": s.role, "part": a["part"],
                           "at": a.get("at"), "status": "confirmed", "sim": describe(cls, s.role, a["part"], None, tid)}
            pids.append(pid)
        slots.append({"role": s.role, "required": s.required, "anchor": a, "points": pids})
    points.update(extra or {})
    return {"equipment": {"id": f"unit:{tid}", "label": tid.upper(), "cls": t.brick_class, "template": tid,
                          "slot_fill": 1.0 if fill else 0.0},
            "variant": FULL.get(tid, {}) if fill else {}, "points": points, "slots": slots, "unplaced": list(extra or {})}


def test_every_template_has_anchors_and_a_2d_layout(km, anchors):
    for tid in km.templates:
        assert tid in anchors, tid
        assert tid in LAYOUTS, tid
        roles = {s.role for s in km.templates[tid].slots}
        assert roles <= set(anchors[tid]["anchors"]), (tid, roles - set(anchors[tid]["anchors"]))


@pytest.mark.parametrize("cls,label,expect", [
    ("RVAV", "VAVE01", "rvav"),                 # the most specific class wins (an RVAV is a VAV)
    ("VAV", "VAV01", "vav"),
    ("Exhaust_Fan", "EF-RR", "exhaust_fan"),
    ("Unit_Heater", "UH01", "unit_heater"),
    ("HVAC_Equipment", "MS01", "split_system"),  # generic class: the name decides
    ("AHU", "AHU01", "ahu"),
])
def test_template_for(km, cls, label, expect):
    t = template_for(cls, label, {}, km)
    assert t is not None and t.id == expect


def test_template_for_falls_back_to_the_node_template(km):
    assert template_for(None, "THING", {"template": "pump"}, km).id == "pump"
    assert template_for("Equipment", "HS01", {}, km) is None


@pytest.mark.parametrize("tid", sorted(LAYOUTS))
def test_each_template_renders_and_passes_rule_qa(km, anchors, tid):
    p = payload(tid, km, anchors)
    g = render(p)
    qa = check_equipment(p, g)
    assert qa["status"] == "pass", (tid, [c for c in qa["checks"] if c["level"] != "ok"])
    assert set(g.placed) == set(p["points"])                 # every point on its anchor
    assert "<svg" in g.svg("dark") and g.png(scale=0.5)[:4] == b"\x89PNG"


def test_missing_required_slot_fails_and_shows_a_ghost(km, anchors):
    p = payload("vav", km, anchors, fill=False)
    g = render(p)
    qa = check_equipment(p, g)
    assert qa["status"] == "no points"
    assert g.ghosts and all(s["role"] in g.ghosts for s in p["slots"] if s["required"])
    p["points"]["x"] = {"label": "X", "cls": "Command", "role": None, "status": "proposed"}
    p["unplaced"] = ["x"]
    qa = check_equipment(p, render(p))
    assert qa["status"] == "fail" and qa["checks"][0]["rule"] == "anchors"


def test_unplaced_points_are_listed_not_lost(km, anchors):
    extra = {"u1": {"label": "ZN-SP", "cls": "Setpoint", "role": None, "status": "proposed"}}
    p = payload("vav", km, anchors, extra=extra)
    g = render(p)
    assert [s.ref for s in g.drawing.of_kind("unplaced")] == ["u1"]
    assert check_equipment(p, g)["status"] == "pass"


def test_bounds_rule_catches_a_shape_off_the_drawing():
    d = Drawing(100, 100)
    d.rect(10, 10, 20, 20, kind="card", ref="a")
    assert bounds_check(d)["ok"]
    d.rect(90, 90, 30, 30, kind="card", ref="b")
    b = bounds_check(d)
    assert not b["ok"] and b["refs"] == ["b"]
    assert check_drawing(d)["status"] == "fail"


def test_sample_is_deterministic_and_labelled():
    spec = describe("Zone_Air_Temperature_Sensor", None)
    a, b = sample(spec, "p1"), sample(spec, "p1")
    assert a == b and a["text"].endswith(spec["unit"])
    on = sample(describe("Fan_Status", "status"), "x")
    assert on["text"] in ("RUN", "ON") and on["state"] == "ok"


def test_describe_uses_template_roles():
    fan = describe("Speed_Sensor", "fan_speed", None, None, "cooling_tower")
    assert fan["driver"] == "tower_fan"


TWIN = {
    "levels": [{"id": "L1", "name": "Level 1", "kind": "zones", "aspect": 0.5},
               {"id": "RF", "name": "Roof", "kind": "roof"}],
    "rooms": {"L1": [{"id": "room:101", "num": "101", "label": "101 Office", "xy": [0.2, 0.3]},
                     {"id": "room:102", "num": "102", "label": "102 Lab", "xy": [0.7, 0.6]}]},
    "aspect": 0.5,
    "equip": [
        {"id": "u:AHU1", "name": "AHU01", "cls": "AHU", "type": "AHU", "sys": "Airside", "floor": "RF", "points": []},
        {"id": "u:V1", "name": "VAV01", "cls": "VAV", "type": "VAV", "sys": "Airside", "floor": "L1",
         "room": "room:101", "points": [{"n": "ZN-T", "c": "Zone_Air_Temperature_Sensor"}]},
        {"id": "u:V2", "name": "VAV02", "cls": "VAV", "type": "VAV", "sys": "Airside", "floor": "L1",
         "room": "room:101", "points": []},
        {"id": "u:V3", "name": "VAV03", "cls": "VAV", "type": "VAV", "sys": "Airside", "floor": "L1", "points": []},
        {"id": "u:P1", "name": "CWP01", "cls": "Pump", "type": "Pump", "sys": "Waterside", "floor": "L1",
         "room": "room:102", "points": []},
        {"id": "u:C1", "name": "CH01", "cls": "Chiller", "type": "Chiller", "sys": "Waterside", "floor": "L1",
         "room": "room:102", "points": []},
        {"id": "u:T1", "name": "HS01", "cls": "Equipment", "type": "Hydronic specialty", "sys": "Waterside",
         "floor": "L1", "points": []},
    ],
    "rels": [{"s": "u:AHU1", "r": "feeds", "d": "u:V1", "via": "air"},
             {"s": "u:AHU1", "r": "feeds", "d": "u:V2", "via": "air"},
             {"s": "u:P1", "r": "feeds", "d": "u:C1", "via": "chilled water"},
             {"s": "u:C1", "r": "feeds", "d": "u:AHU1", "via": "chilled water"}],
}


def test_floor_places_units_in_their_rooms_and_lists_the_rest():
    g = render_floor(TWIN, "L1")
    assert g.qa["status"] == "pass"
    assert set(g.placed) == {"u:V1", "u:V2", "u:V3", "u:P1", "u:C1", "u:T1"}
    assert set(g.unplaced) == {"u:V3", "u:T1"}            # no room in the graph: in the strip, not guessed
    assert any("°F" in s.geo["text"] for s in g.drawing.of_kind("value"))


def test_water_and_air_follow_feeds():
    w = render_water(TWIN)
    assert w.qa["status"] == "pass"
    assert {s.ref for s in w.drawing.of_kind("edge")} == {"u:P1>u:C1", "u:C1>u:AHU1"}
    assert w.unplaced == ["u:T1"]                          # plant equipment with no feeds edge
    assert w.placed["u:P1"][0] < w.placed["u:C1"][0] < w.placed["u:AHU1"][0]  # columns follow the chain
    a = render_air(TWIN)
    assert a.qa["status"] == "pass"
    assert {s.ref for s in a.drawing.of_kind("unit")} == {"u:AHU1", "u:V1", "u:V2", "u:V3"}
    assert a.unplaced == ["u:V3"]
    assert medium("air") == "supply" and medium("hot water") == "hot_water"


def test_vision_cards_are_the_drawn_cards(km, anchors):
    p = payload("ahu", km, anchors)
    g = render(p)
    cs = cards(g.drawing)
    assert len(cs) == len(g.drawing.of_kind("card"))
    assert sorted(n for c in cs for n in c["points"]) == sorted(v["label"] for v in p["points"].values())


def test_graphic_qa_job_check():
    from projectmodel.ai.jobs import check_output

    vals = {"card_ids": ["C1", "C2"]}
    assert check_output("graphic_qa", {"verdict": "ok", "issues": []}, vals) is None
    bad = {"verdict": "fix", "issues": [{"card": "C9", "problem": "overlap", "note": ""}]}
    assert "not candidates" in check_output("graphic_qa", bad, vals)
