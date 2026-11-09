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
