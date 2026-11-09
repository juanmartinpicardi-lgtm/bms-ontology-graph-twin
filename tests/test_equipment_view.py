import copy
from pathlib import Path

import pytest

from projectmodel import review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.equipment_view import (MODULES, anchor_problems, assign_slots, equipment_payload, load_anchors,
                                         render_html)
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"
AHU2 = "eq:Airside AHU-2"
VAV = "eq:Airside AHU-2/VAV 1-2-1"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture(scope="module")
def anchors():
    return load_anchors()


@pytest.fixture
def store(km):
    s = Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), s, P)
    return s


def _by_label(payload):
    return {p["label"]: p for p in payload["points"].values()}


# anchors -------------------------------------------------------------------------------------

def test_anchor_map_covers_every_drawn_slot(km, anchors):
    assert anchor_problems(km, anchors) == []
    assert {"ahu", "vav"} <= set(anchors)


@pytest.mark.parametrize("edit, expected", [
    (lambda a: a["ahu"]["anchors"].pop("relief_damper"), "slot relief_damper has no anchor"),
    (lambda a: a["vav"]["anchors"].update(spaceship={"part": "box"}), "anchor spaceship is not a slot"),
    (lambda a: a["vav"]["anchors"]["damper"].update(part="nowhere"), "part 'nowhere', which is not in parts"),
    (lambda a: a["ahu"]["anchors"]["supply_temp"].update(at=1.5), "must be 0-1"),
    (lambda a: a["ahu"]["sub_equipment"].update(Not_A_Fan="supply_fan"), "Not_A_Fan is not an equipment class"),
    (lambda a: a.update(spaceship={}), "spaceship is not a template"),
])
def test_anchor_problems_are_caught(km, anchors, edit, expected):
    broken = copy.deepcopy(anchors)
    edit(broken)
    assert any(expected in p for p in anchor_problems(km, broken))


def test_new_slot_without_anchor_fails(km, anchors):
    from projectmodel.knowledge_model import Slot
    km2 = copy.copy(km)
    km2.templates = dict(km.templates)
    t = copy.copy(km.templates["vav"])
    t.slots = [*t.slots, Slot("co2", ("Sensor",), False)]
    km2.templates["vav"] = t
    assert "anchors.yaml: vav: slot co2 has no anchor" in anchor_problems(km2, anchors)


# slot assignment ------------------------------------------------------------------------------

def test_first_slot_wins_and_words_pick_between_slots(km):
    t = km.templates["ahu"]
    pts = [{"id": "a", "label": "Clg_Valve_Cmd", "cls": "Valve_Command"},
           {"id": "b", "label": "Htg_Valve_Cmd", "cls": "Valve_Command"},
           {"id": "c", "label": "Valve_Cmd", "cls": "Valve_Command"},  # no words: nothing picks it
           {"id": "d", "label": "RF Status", "cls": "Fan_Status"},
           {"id": "e", "label": "Status", "cls": "Fan_Status", "context": "RF VFD"},
           {"id": "f", "label": "SF Status", "cls": "Fan_Status"},
           {"id": "g", "label": "Econ_Cmd", "cls": "Damper_Command"},
           {"id": "h", "label": "Econ_Cmd", "cls": "Damper_Command"},
           {"id": "i", "label": "Weird", "cls": None},
           {"id": "j", "label": "Fan Speed", "cls": "Fan_Speed_Command"}]
    slots, unplaced = assign_slots(t, pts, km)
    assert slots["cooling_valve"] == ["a"]
    assert slots["heating_valve"] == ["b"]
    assert slots["return_fan_status"] == ["d", "e"]
    assert slots["supply_fan_status"] == ["f"]
    assert slots["economizer_damper"] == ["g", "h"]  # stacked
    assert slots["supply_fan_speed"] == ["j"]  # exact class beats supply_fan_cmd's parent Fan_Command
    assert unplaced == ["c", "i"]


# payload: AHU-2 and a reheat VAV on Alpha --------------------------------------------------------

def test_ahu2_places_return_fan_and_relief_points(store, km, anchors):
    p = equipment_payload(store, P, AHU2, km, anchors)
    assert p["equipment"]["template"] == "ahu" and p["equipment"]["slot_fill"] == 1.0
    assert p["variant"] == {"heating_coil": True, "mixing_box": True, "relief_outlet": True, "return_fan": True}
    pts = _by_label(p)
    assert pts["RF Status"]["role"] == "return_fan_status" and pts["RF Status"]["part"] == "return_fan"
    assert pts["RF VFD S/S"]["part"].startswith("return_fan")
    assert pts["Relief Damper Signal"]["role"] == "relief_damper"
    assert pts["Relief Damper Signal"]["part"] == "relief_outlet.damper"
    # sub-equipment points go on the parent's model, on the fan they belong to
    assert pts["Return Fan Frequency"]["part"] == "return_fan.vfd"
    assert pts["Supply Fan Frequency"]["part"] == "supply_fan.vfd"
    assert pts["Return Fan Power"]["sub_equipment"] == "eq:Airside AHU-2/RF VFD"
    assert pts["Clg_Valve_Cmd"]["part"] == "cooling_coil.valve" and pts["Htg_Valve_Cmd"]["part"] == "heating_coil.valve"
    placed = {i for s in p["slots"] for i in s["points"]}
    assert placed.isdisjoint(p["unplaced"]) and placed | set(p["unplaced"]) == set(p["points"])
    assert len(p["unplaced"]) <= 3
    assert len(p["relations"]["feeds"]) == 88 and all(r["template"] == "vav" for r in p["relations"]["feeds"])
    assert [r["label"] for r in p["relations"]["feeds"][:2]] == ["VAV 1-2-1", "VAV 1-2-3"]  # natural order
    assert p["value_source"] == "simulated"
    assert pts["SAT"]["prov"]["method"] and pts["SAT"]["via"]["source_ref"]


def test_reheat_vav(store, km, anchors):
    p = equipment_payload(store, P, VAV, km, anchors)
    assert p["equipment"]["template"] == "vav" and p["equipment"]["slot_fill"] == 1.0
    assert p["variant"] == {"reheat": True, "fan_powered": False, "dual_duct": False}
    roles = {s["role"]: s for s in p["slots"]}
    assert roles["reheat_valve"]["points"] and roles["reheat_valve"]["medium"] == "hot_water"
    assert roles["zone_temp"]["anchor"]["part"] == "zone_sensor"
    assert roles["zone_temp"]["classes"] == ["Zone_Air_Temperature_Sensor"]  # the view draws a ghost from these
    assert p["unplaced"] == []
    assert AHU2 in [r["id"] for r in p["relations"]["fed_by"]]


def test_vav_variants_on_alpha(store, km, anchors):
    dd = equipment_payload(store, P, "eq:Airside AHU-4/DD 1-4-1", km, anchors)
    assert dd["variant"] == {"reheat": False, "fan_powered": False, "dual_duct": True}
    # each deck's damper and flow cross: the point names say which
    decks = {x["label"]: (x["part"], x["at"]) for x in dd["points"].values() if x["part"] in ("damper", "flow_cross")}
    assert decks == {"Airflow sensor 1 (Hot)": ("flow_cross", "hot"), "Airflow sensor 2 (Cold)": ("flow_cross", "cold"),
                     "Desired Airflow - Hot": ("flow_cross", "hot"), "Desired Airflow - Cold": ("flow_cross", "cold"),
                     "Htg Dmpr Cmnd 0-100": ("damper", "hot"), "Clg Dmpr Pos. %": ("damper", "cold")}
    fpb = equipment_payload(store, P, "eq:Airside AHU-2/VAV 1-2-89", km, anchors)
    assert fpb["variant"] == {"reheat": True, "fan_powered": True, "dual_duct": False}
    plain = equipment_payload(store, P, "eq:Airside AHU-2/VAV 1-2-52", km, anchors)
    assert not any(plain["variant"].values())
    assert all(x["at"] is None for x in plain["points"].values() if x["part"] == "damper")  # decks only on DD


def test_vav_without_flow_sensor_leaves_an_empty_required_slot(store, km, anchors):
    pts = equipment_payload(store, P, VAV, km, anchors)["points"]
    review.reject(store, P, [i for i, x in pts.items() if x["label"] == "Current Airflow"], "test")
    p = equipment_payload(store, P, VAV, km, anchors)
    airflow = next(s for s in p["slots"] if s["role"] == "airflow")
    assert airflow["required"] and airflow["points"] == []  # the view draws the flow cross as a ghost
    assert airflow["anchor"]["part"] == "flow_cross" and p["equipment"]["slot_fill"] < 1


def test_rejected_points_are_left_out(store, km, anchors):
    pts = equipment_payload(store, P, AHU2, km, anchors)["points"]
    pid = next(i for i, x in pts.items() if x["label"] == "Relief Damper Signal")
    review.reject(store, P, [pid], "test")
    p = equipment_payload(store, P, AHU2, km, anchors)
    assert pid not in p["points"]
    assert p["variant"]["relief_outlet"] is False


def test_untemplated_equipment_has_no_model(store, km, anchors):
    with pytest.raises(ValueError):
        equipment_payload(store, P, "eq:Airside AHU-2/SF VFD", km, anchors)
    with pytest.raises(KeyError):
        equipment_payload(store, P, "eq:nope", km, anchors)


# page ---------------------------------------------------------------------------------------------

def test_render_html_inlines_modules_and_data(store, km, anchors):
    p = equipment_payload(store, P, AHU2, km, anchors)
    html = render_html(p)
    assert "/*__DATA__*/" not in html and "/*__MODULES__*/" not in html
    assert '"label":"Airside AHU-2"' in html
    for const in ("const Core", "const Parts", "const Sim", "const AHU", "const VAV", "const Labels", "const Panels",
                  "const Plant", "const FCU", "const Chiller", "const Boiler", "const Pump"):
        assert const in html
    assert html.count("</script>") == 2  # import map and the one module script: nothing inlined closes it early
    assert "three@0.170.0" in html and len(MODULES) == 12
    assert '<html lang="en" data-theme="dark">' in render_html(p, theme="dark")
