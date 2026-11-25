"""W4: nodes from what the setup already reads. Troop D's riser becomes controller and network nodes with ba:
relations, points carry their units (QUDT where the spelling is clear) and their BACnet object, the building has a
site and a building node, zones only where a source states them; the graph standard and the cards measure it."""
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from projectmodel import units
from projectmodel.completeness import completeness
from projectmodel.db.store import SCHEMA, Edge, Node, Store
from projectmodel.graph_standard import status
from projectmodel.intake import steps
from projectmodel.intake.publish import _zones, device_object, publish
from projectmodel.intake.state import Intake
from projectmodel.knowledge_model import load_knowledge_model

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "test_packages/troop_d"
KEY = ROOT / "data/ground_truth/troop_d"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture(scope="module")
def troop_d(tmp_path_factory):
    if not PACKAGE.exists():
        pytest.skip("test package missing: run scripts/build_troop_d.py")
    it = Intake.create("Troop D test", "425 East Phelps Street, Springfield, MO",
                       root=tmp_path_factory.mktemp("intake"))
    for s in steps.STEPS[:-1]:
        f = PACKAGE / s.test_file
        it.add_file(s.id, f.name, f.read_bytes())
        steps.run(it, s.id, lambda msg: None)
    store = Store(":memory:")
    return it, store, publish(it, store)


def _key(name):
    return list(csv.DictReader((KEY / name).open()))


# --- units --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, unit", [("°F", "unit:DEG_F"), (" degF ", "unit:DEG_F"), ("cfm", "unit:FT3-PER-MIN"),
                                        ("in.wc", "unit:IN_H2O"), ("inH₂O", "unit:IN_H2O"), ("%RH", "unit:PERCENT_RH"),
                                        ("%", "unit:PERCENT"), ("psig", "unit:PSI"), ("GPM", "unit:GAL_US-PER-MIN"),
                                        ("F", None), ("MBH", None), ("", None), (None, None)])
def test_unit_spellings_map_to_qudt_only_when_clear(text, unit):
    assert units.qudt(text) == unit
    assert units.point_unit(text) == ({} if not (text or "").strip() else
                                      {"units": text.strip(), **({"unit": unit} if unit else {})})


def test_unit_against_class():
    assert units.mismatch("Zone_Air_Temperature_Sensor", "unit:IN_H2O")
    assert not units.mismatch("Zone_Air_Temperature_Sensor", "unit:DEG_F")
    assert not units.mismatch("Fan_Speed_Command", "unit:PERCENT")  # no measured quantity in the class name
    assert not units.mismatch("Zone_Air_Humidity_Sensor", "unit:PERCENT_RH")
    assert not units.mismatch(None, "unit:DEG_F") and not units.mismatch("Temperature_Sensor", None)


def test_a_spelling_for_two_units_fails_the_load(tmp_path):
    bad = tmp_path / "units.yaml"
    bad.write_text("units:\n  DEG_F: {quantity: temperature, spellings: ['F']}\n"
                   "  FARAD: {quantity: capacitance, spellings: ['f']}\n")
    with pytest.raises(ValueError, match="names both"):
        units.load(bad)


# --- Troop D: the riser as nodes ----------------------------------------------------------------------------------

def test_riser_is_controllers_on_networks(troop_d):
    it, store, p = troop_d
    ctrl = {r["id"]: r for r in store.nodes(p, "controller")}
    nets = {r["id"]: r for r in store.nodes(p, "network")}
    riser = it.facts(kind="controller", live=True)
    instances = {f["data"]["instance"] for f in riser}
    assert {f"ctrl:{i}" for i in instances} <= set(ctrl) and len(instances) >= 60
    assert {r["class"] for r in ctrl.values()} == {"Field_Controller", "Supervisory_Controller"}
    assert {r["class"] for r in nets.values()} == {"Field_Network"} and len(nets) == 4
    # One gateway (one device instance) serves three mini-splits: one controller, three units.
    gw = ctrl["ctrl:3114"]
    assert json.loads(gw["attrs"])["devices"] == ["MS-1", "MS-2", "MS-3"]
    assert len([e for e in store.edges(p, "controls") if e["src"] == "ctrl:3114"]) == 3
    # Every controller is on its trunk; the riser and the BMS export agree on it.
    on = {e["src"]: e for e in store.edges(p, "isOnNetwork")}
    for f in riser:
        e = on[f"ctrl:{f['data']['instance']}"]
        assert e["dst"].endswith(f"/{f['data']['trunk']}") and _agree(e)
    assert all(_agree(r) for r in ctrl.values())  # riser + BMS device instance
    sup = ctrl["ctrl:TROOPD-NAE01"]
    assert sup["class"] == "Supervisory_Controller"
    assert {e["dst"] for e in store.edges(p, "isOnNetwork") if e["src"] == sup["id"]} == set(nets)
    assert store.resolve(p, "bacnet_device", "3104") == "ctrl:3104"


def test_controllers_control_the_units_of_the_answer_key(troop_d):
    _, store, p = troop_d
    controls = {(e["src"], e["dst"]) for e in store.edges(p, "controls")}
    key = [r for r in _key("equipment.csv") if r["device_instance"] and r["kind"] != "system"]
    found = [r for r in key if (f"ctrl:{r['device_instance']}", store.resolve(p, "schedule_tag", r["tag"])) in controls]
    assert len(found) >= 60 and len(found) >= 0.9 * len(key), (len(found), len(key))
    assert all(e["method"] in ("parsed", "human") for e in store.edges(p, "controls"))


def test_every_point_lives_in_one_controller_and_has_its_bacnet_object(troop_d):
    _, store, p = troop_d
    points = {r["id"]: json.loads(r["attrs"]) for r in store.nodes(p, "point")}
    hosted = defaultdict(set)
    for e in store.edges(p, "isHostedBy"):
        hosted[e["src"]].add(e["dst"])
    assert set(hosted) == set(points) and all(len(h) == 1 for h in hosted.values())
    agreed = sum(1 for e in store.edges(p, "isHostedBy") if _agree(e))
    assert agreed >= 800  # the submittal's reference and the BMS device instance say the same controller
    keyed = [pid for pid in points
             if any(store.resolve(p, "device_object", a["value"]) == pid
                    for a in store.aliases(p, pid) if a["scheme"] == "device_object")]
    assert len(keyed) >= 800
    # Where the submittal itself gives the object, it is the same BACnet name as the BMS export's.
    ahu = "pt:TROOPD-NAE01/FC-1.AHU-1.DA-T"
    names = {(a["source"], a["value"]) for a in store.aliases(p, ahu) if a["scheme"] == "device_object"}
    assert names == {("setup:submittal", "3104:analog-input:1"), ("setup:bms", "3104:analog-input:1")}
    assert points[ahu]["bacnet"] == {"device_instance": 3104, "object_type": "analog-input", "object_instance": 1}
    assert device_object(3104, "Analog-Input ", 1) == "3104:analog-input:1"


def test_points_carry_the_units_of_the_answer_key(troop_d):
    _, store, p = troop_d
    by_ref = {json.loads(r["attrs"])["ref"]: json.loads(r["attrs"]) for r in store.nodes(p, "point")}
    key = [r for r in _key("points.csv") if r["bms_name"] in by_ref]
    assert len(key) >= 800
    right = sum(1 for r in key if (by_ref[r["bms_name"]].get("units") or "") == r["units"])
    assert right == len(key)
    with_unit = [a for a in by_ref.values() if a.get("units")]
    assert len(with_unit) >= 600 and all(a.get("unit", "").startswith("unit:") for a in with_unit)
    assert Counter(a["unit"] for a in with_unit).most_common(1)[0][0] == "unit:DEG_F"


def test_site_building_and_no_invented_zones(troop_d):
    it, store, p = troop_d
    loc = {r["id"]: r for r in store.nodes(p, "location")}
    site, bldg = loc["site"], loc["building"]
    assert (site["class"], bldg["class"]) == ("Site", "Building") and bldg["label"] == it.name
    assert site["label"].startswith("425 East Phelps") and site["method"] == "human" and site["status"] == "confirmed"
    part = {(e["src"], e["dst"]) for e in store.edges(p, "hasPart")}
    assert ("site", "building") in part
    floors = {i for i, r in loc.items() if r["class"] == "Floor"}
    assert floors and {("building", f) for f in floors} <= part
    assert not [r for r in loc.values() if r["class"] == "HVAC_Zone"]  # no source states a zone


def test_republishing_the_bms_keeps_the_riser(troop_d):
    it, store, p = troop_d
    before = {r["id"] for r in store.nodes(p, "controller")}
    store.remove_source(p, "setup:bms")
    assert {r["id"] for r in store.nodes(p, "controller")} == before  # the riser still states them
    assert not any(_agree(e) for e in store.edges(p, "isHostedBy"))
    publish(it, store, steps=["bms"])
    assert sum(1 for e in store.edges(p, "isHostedBy") if _agree(e)) >= 800


def test_graph_standard_and_cards_measure_the_new_layers(troop_d, km):
    _, store, p = troop_d
    s = status(store, km, p)
    assert s["site"]["state"] == "done"
    assert s["controllers"]["pct"] >= 95 and s["networks"]["state"] == "done"
    assert s["point"]["pct"] >= 95 and s["point_props"]["pct"] >= 90
    assert "No source states HVAC zones" in s["spaces"]["note"]
    cards = {c.key: c for c in completeness(store, p)}
    assert cards["controlled"].share == 1.0 and "4 networks" in cards["controlled"].sub
    assert cards["units"].share >= 0.9 and cards["site"].share == 1.0


# --- zones, only where stated ---------------------------------------------------------------------------------------

def test_zones_come_only_from_a_source_that_states_them():
    out = defaultdict(lambda: defaultdict(list))

    def put(f, what, item):
        out[f["step"] if f else "none"][what].append(item)
    src = {"file": "plans.pdf", "page": 0, "sheet": "M-101"}
    zone = {"zone": "Z1", "name": "Zone 1", "rooms": ["101", "999"]}  # room 999 is not in the graph: no link
    facts = {"zone:Z1": {"id": "zone:Z1", "kind": "zone", "data": zone,
                         "src": src, "method": "parsed", "conf": 0.9, "status": "proposed", "step": "plans"},
             "eq:VAV1": {"id": "eq:VAV1", "kind": "equipment", "data": {}, "src": src, "method": "parsed", "conf": 0.95,
                         "status": "confirmed", "step": "schedules"},
             "eq:VAV2": {"id": "eq:VAV2", "kind": "equipment", "data": {}, "src": src, "method": "parsed", "conf": 0.95,
                         "status": "confirmed", "step": "schedules"}}
    b = {"equip": {"VAV1": {"fact": "eq:VAV1", "status": "confirmed", "attrs": {"zone": "Z2"}},
                   "VAV2": {"fact": "eq:VAV2", "status": "confirmed", "attrs": {}}}}
    _zones(b, facts, {"unit:VAV1", "unit:VAV2"}, {"room:101"}, put)
    assert [(n.id, n.cls) for n in out["plans"]["nodes"]] == [("zone:Z1", "HVAC_Zone")]
    assert [(e.src, e.rel, e.dst) for e in out["plans"]["edges"]] == [("zone:Z1", "hasPart", "room:101")]
    assert [(n.id, n.cls) for n in out["schedules"]["nodes"]] == [("zone:Z2", "HVAC_Zone")]
    assert [(e.src, e.rel, e.dst, e.attrs) for e in out["schedules"]["edges"]] == [
        ("unit:VAV1", "feeds", "zone:Z2", {"medium": "air"})]


# --- a project with none of it: measured as missing ----------------------------------------------------------------

def test_a_bms_only_project_is_missing_the_new_layers(km):
    store = Store(":memory:")
    store.write_source("x", "mapper:x.csv", 1, [Node("eq", "equipment", "eq", "VAV", "x.csv", "1", "rule", 0.9),
                                                 Node("pt", "point", "pt", "Temperature_Sensor", "x.csv", "2", "rule",
                                                      0.9)],
                       [Edge("eq", "hasPoint", "pt", "x.csv", "2", "rule", 0.9)])
    s = status(store, km, "x")
    assert all(s[k]["state"] == "missing" for k in ("site", "controllers", "networks", "point_props"))
    assert s["point"]["state"] == "partial" and s["point"]["pct"] is None
    cards = {c.key: c for c in completeness(store, "x")}
    assert cards["controlled"].share == cards["units"].share == cards["site"].share == 0


def test_mapper_keeps_units_when_the_export_has_them(tmp_path, km):
    from projectmodel.adapters.haystack import read_blind_export
    from projectmodel.mapper.pipeline import Mapper
    f = tmp_path / "names_paths.csv"
    f.write_text("blind_id,name,path,units\np1,ZN-T,Floor1/VAV-1,°F\np2,DPR-O,Floor1/VAV-1,\n")
    recs = read_blind_export(f)
    assert [r.units for r in recs] == ["°F", None]
    store = Store(":memory:")
    Mapper(km).run(recs, store, "t")
    a = {r["label"]: json.loads(r["attrs"]) for r in store.nodes("t", "point")}
    assert (a["ZN-T"]["units"], a["ZN-T"]["unit"]) == ("°F", "unit:DEG_F") and "units" not in a["DPR-O"]


def test_a_database_from_before_controllers_migrates(tmp_path):
    db = tmp_path / "kg.sqlite"
    c = sqlite3.connect(db)
    c.executescript(SCHEMA.replace(", 'controller', 'network')", ")"))
    c.close()
    assert "'controller'" not in sqlite3.connect(db).execute(
        "SELECT sql FROM sqlite_master WHERE name = 'nodes'").fetchone()[0]
    s = Store(db)
    s.write_source("p", "setup:submittal", 1, [Node("ctrl:1", "controller", "c", "Field_Controller", "s.pdf", "p1",
                                                    "parsed", 0.95)])
    assert s.nodes("p", "controller")[0]["id"] == "ctrl:1"


def test_tree_shows_the_controller_of_a_unit_and_a_point():
    from projectmodel.tree import build_tree
    s = Store(":memory:")
    s.write_source("t", "setup:submittal", 1, [
        Node("unit:VAV1", "equipment", "VAV-1", "VAV", "s.pdf", "p1", "parsed", 0.95),
        Node("pt:1", "point", "ZN-T", "Zone_Air_Temperature_Sensor", "s.pdf", "p2", "rule", 0.95),
        Node("ctrl:3204", "controller", "VAV-1 · VMA1930", "Field_Controller", "s.pdf", "p1", "parsed", 0.95),
        Node("net:FC-2", "network", "FC-2", "Field_Network", "s.pdf", "p1", "parsed", 0.95)], [
        Edge("unit:VAV1", "hasPoint", "pt:1", "s.pdf", "p2", "rule", 0.95),
        Edge("ctrl:3204", "controls", "unit:VAV1", "s.pdf", "p1", "parsed", 0.95),
        Edge("pt:1", "isHostedBy", "ctrl:3204", "s.pdf", "p2", "parsed", 0.95),
        Edge("ctrl:3204", "isOnNetwork", "net:FC-2", "s.pdf", "p1", "parsed", 0.95)])
    tree = build_tree(s, "t")
    assert [n.id for n in tree.walk()] == ["unit:VAV1"]  # controllers are not equipment
    assert [c.id for c, _ in tree.controlled_by("unit:VAV1")] == ["ctrl:3204"]
    assert [c.id for c, _ in tree.controlled_by("pt:1")] == ["ctrl:3204"]
    assert [n.id for n, _ in tree.network_of("ctrl:3204")] == ["net:FC-2"]


def _agree(row) -> bool:
    """Two or more sources state this fact (settle's note; agreement no longer confirms it, plan §8.5)."""
    return len(json.loads(row["attrs"] or "{}").get("agree", [])) > 1
