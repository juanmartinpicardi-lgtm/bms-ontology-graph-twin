import shutil
from pathlib import Path

import pytest
import yaml

from projectmodel.knowledge_model import KM_DIR, KnowledgeModelError, _load_brick, load_knowledge_model


@pytest.fixture(scope="session")
def brick():
    return _load_brick()


@pytest.fixture(scope="session")
def km(brick):
    return load_knowledge_model(brick=brick)


def test_real_knowledge_model_loads(km):
    assert km.brick_version == "1.4.4"
    assert set(km.templates) >= {"ahu", "vav", "fcu", "chiller", "boiler", "pump"}
    assert 8 <= sum(1 for c in km.classes.values() if c.source == "ba") <= 15
    assert len(km.by_kind("point")) > 50 and len(km.by_kind("equipment")) > 20


def test_class_reasoning(km):
    assert km.is_a("VAV", "Terminal_Unit")
    assert km.is_a("Discharge_Air_Temperature_Sensor", "Temperature_Sensor")
    assert km.is_a("Calculated_Point", "Point")
    assert not km.is_a("VAV", "AHU")
    assert km.classes["Supply_Fan"].subset_parent == "Fan"


def test_name_rules(km):
    nr = km.name_rules
    assert nr.tokenize("DisAirTemp") == ["dis", "air", "temp"]
    assert nr.tokenize("AHU1_SAT-sp") == ["ahu", "1", "sat", "sp"]
    assert nr.words("Clg_Valve_Cmd") == ["cooling", "valve", "command"]
    assert nr.expand("sp") == [["setpoint"], ["static", "pressure"]]
    assert nr.unknown_tokens("Zork 12 Temp") == ["zork"]


@pytest.fixture
def km_copy(tmp_path):
    dst = tmp_path / "km"
    shutil.copytree(KM_DIR, dst)
    return dst


def _edit_yaml(path: Path, fn):
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _problems(km_dir, brick):
    with pytest.raises(KnowledgeModelError) as e:
        load_knowledge_model(km_dir, brick=brick)
    return "\n".join(e.value.problems)


@pytest.mark.parametrize("edit, expected", [
    (lambda d: d["points"]["generic"].append("Not_A_Class"), "Not_A_Class is not a Brick"),
    (lambda d: d["points"]["generic"].append("Zone_Air_Temperature_Setpoint"), "deprecated"),
    (lambda d: d["equipment"]["generic"].append("Zone_Air_Temperature_Sensor"), "is not a Equipment"),
    (lambda d: d["systems"]["water"].append("Steam_Valve"), "is not a System"),
    (lambda d: d["relations"].append("controlsEverything"), "relation controlsEverything"),
])
def test_subset_errors_are_caught(km_copy, brick, edit, expected):
    _edit_yaml(km_copy / "brick_subset.yaml", edit)
    assert expected in _problems(km_copy, brick)


@pytest.mark.parametrize("edit, expected", [
    (lambda d: d["points"].append({"role": "x", "classes": ["AHU"], "required": False}), "not a point class"),
    (lambda d: d["relations"].append({"rel": "feeds", "target": "spaceship"}), "spaceship is not a template"),
    (lambda d: d["relations"].append({"rel": "isFedBy", "target": "ahu", "system": "AHU"}), "not a system class"),
    (lambda d: d.update(name_patterns=["(unclosed"]), "bad name pattern"),
    (lambda d: d.update(id="other"), "must equal the file name"),
    (lambda d: d["points"][0].update(words=["frobnication"]), "word 'frobnication' is not in the vocabulary"),
])
def test_template_errors_are_caught(km_copy, brick, edit, expected):
    _edit_yaml(km_copy / "templates" / "vav.yaml", edit)
    assert expected in _problems(km_copy, brick)


@pytest.mark.parametrize("edit, expected", [
    (lambda d: d["abbreviations"].update(zz=["frobnication"]), "not in the vocabulary"),
    (lambda d: d["abbreviations"].update({"a_b": ["air"]}), "contains a separator"),
    (lambda d: d["examples"].update({"Htg Vlv": ["cooling"]}), "example 'Htg Vlv'"),
])
def test_name_rule_errors_are_caught(km_copy, brick, edit, expected):
    _edit_yaml(km_copy / "name_rules" / "abbreviations.yaml", edit)
    assert expected in _problems(km_copy, brick)


def test_extension_clash_is_caught(km_copy, brick):
    ttl = km_copy / "ba_extension.ttl"
    ttl.write_text(ttl.read_text() + '\nba:AHU a owl:Class ; rdfs:label "x" ; skos:definition "x" .\n')
    assert "clashes with Brick" in _problems(km_copy, brick)


# --- W1: every term the app writes is a declared, valid term ------------------------------------

def test_written_relations_and_classes_resolve(km):
    from projectmodel.knowledge_model import CONTROL_RELATIONS, WRITTEN_RELATIONS
    from projectmodel.sequences import CONTROL
    assert CONTROL is CONTROL_RELATIONS  # one list, not two that can drift
    declared = set(km.relations) | set(km.ba_relations)
    assert set(WRITTEN_RELATIONS) <= declared and "serves" in WRITTEN_RELATIONS
    tags = yaml.safe_load((KM_DIR / "name_rules" / "equipment_tags.yaml").read_text())["prefixes"]
    assert {t["class"] for t in tags.values() if t.get("class")} <= set(km.classes)
    assert {"Floor", "Room", "HVAC_Zone", "Building", "Site", "RVAV", "Unit_Heater"} <= set(km.classes)


def test_locations_are_kept_on_purpose(km):
    assert {km.classes[c].replaced_by for c in ("Floor", "Room", "HVAC_Zone", "Building", "Site")} == {
        "rec:Level", "rec:Room", "rec:HVACZone", "rec:Building", "rec:Site"}
    assert km.classes["Room"].kind == "location" and km.is_a("Room", "Location")
    assert km.classes["Unit_Heater"].source == "ba" and km.is_a("Unit_Heater", "Space_Heater")
    assert km.is_a("Unit_Heater", "Equipment") and km.classes["Unit_Heater"].kind == "equipment"
    assert km.is_a("RVAV", "VAV")


def test_attached_objects_have_a_brick_parent(km):
    for c in ("Schedule", "Trend_Log", "Alarm_Definition"):
        assert km.is_a(c, "Entity") and km.classes[c].kind == "other"  # not points: they stay out of point candidates


def test_serves_maps_to_brick_feeds(km):
    from projectmodel.knowledge_model import BA, BRICK
    assert (BA.serves, rdflib_subproperty(), BRICK.feeds) in km.graph


def rdflib_subproperty():
    from rdflib.namespace import RDFS
    return RDFS.subPropertyOf


def test_answer_key_classes_are_in_the_model(km):
    """The Troop D answer key (a dev set) names only classes and relations the model declares."""
    import csv
    key = KM_DIR.parent / "data/ground_truth/troop_d"
    if not key.exists():
        pytest.skip("answer key missing")
    points = {r["brick_class"] for r in csv.DictReader((key / "points.csv").open()) if r["brick_class"]}
    equip = {r["brick_class"] for r in csv.DictReader((key / "equipment.csv").open()) if r["brick_class"]}
    rels = {r["rel"] for r in csv.DictReader((key / "relations.csv").open())}
    assert not points - set(km.classes)
    assert not equip - set(km.classes)
    assert not rels - (set(km.relations) | set(km.ba_relations))


@pytest.mark.parametrize("edit, expected", [
    (lambda d: d["locations"]["spaces"].update(Room="rec:Space"), "is replaced by"),
    (lambda d: d["locations"]["spaces"].update(Room="Room"), "must name the rec: class"),
    (lambda d: d["locations"]["spaces"].update(Zork="rec:Zork"), "location Zork is not a Brick"),
    (lambda d: d["locations"]["spaces"].update(Floor_Fan_Coil_Unit="rec:Level"), "is not a Location"),
    (lambda d: d["points"]["generic"].append("Room"), "deprecated"),  # deprecated classes stay out of every other group
])
def test_location_errors_are_caught(km_copy, brick, edit, expected):
    _edit_yaml(km_copy / "brick_subset.yaml", edit)
    assert expected in _problems(km_copy, brick)


@pytest.mark.parametrize("rel", ["drives", "feedback", "requires", "resets", "requests", "switches", "serves"])
def test_undeclared_written_relation_fails_loading(km_copy, brick, rel):
    import re
    ttl = km_copy / "ba_extension.ttl"
    text = ttl.read_text()
    assert re.search(rf"^ba:{rel} a owl:ObjectProperty", text, re.M)
    ttl.write_text(re.sub(rf"^ba:{rel} a owl:ObjectProperty ;.*?\.\n", "", text, flags=re.M | re.S, count=1))
    assert f"the app writes relation '{rel}'" in _problems(km_copy, brick)


def test_unknown_tag_class_fails_loading(km_copy, brick):
    _edit_yaml(km_copy / "name_rules" / "equipment_tags.yaml", lambda d: d["prefixes"]["AHU"].update({"class": "Air_Thing"}))
    problems = _problems(km_copy, brick)
    assert "prefix AHU proposes class 'Air_Thing'" in problems


def test_relation_needs_a_comment_and_a_known_parent(km_copy, brick):
    ttl = km_copy / "ba_extension.ttl"
    ttl.write_text(ttl.read_text() + '\nba:zork a owl:ObjectProperty ; rdfs:subPropertyOf brick:nothing .\n'
                   '\nba:feeds a owl:ObjectProperty ; rdfs:label "x" ; rdfs:comment "x" .\n')
    problems = _problems(km_copy, brick)
    assert "relation zork needs rdfs:label and rdfs:comment" in problems
    assert "parent relation" in problems and "ba_extension: relation feeds clashes with Brick" in problems
