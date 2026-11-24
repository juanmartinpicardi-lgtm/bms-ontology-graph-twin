import json
from pathlib import Path

import pytest

from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import METHODS, Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.classify import ClassMatcher
from projectmodel.mapper.llm import LLMAnswer, LLMRequest
from projectmodel.mapper.pipeline import Mapper
from projectmodel.records import RawRecord

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.mark.parametrize("name, cls", [
    ("MAT", "Mixed_Air_Temperature_Sensor"),
    ("Discharge Air Temp", "Discharge_Air_Temperature_Sensor"),
    ("Space Temperature", "Zone_Air_Temperature_Sensor"),
    ("Unoccupied Htg Sp", "Unoccupied_Heating_Zone_Air_Temperature_Setpoint"),
    ("SF VFD Signal", "Fan_Speed_Command"),
    ("Econ_Cmd", "Damper_Command"),
    ("HHWP-2 S/S", "Start_Stop_Command"),
])
def test_point_names(km, name, cls):
    assert ClassMatcher(km, "point").classify(name).cls == cls


@pytest.mark.parametrize("name, cls", [
    ("AHU-2", "AHU"), ("DD 1-4-2", "VAV"), ("EF-1", "Exhaust_Fan"), ("Gas Meter 1", "Gas_Meter"),
    ("Hot Water Plant", "Hot_Water_System"), ("Chilled Water Plant", "Chilled_Water_System"),
    ("Penthouse HW Sys", "Hot_Water_System"),
])
def test_equipment_names(km, name, cls):
    assert ClassMatcher(km, "equipment", also=("system",)).classify(name).cls == cls


@pytest.mark.parametrize("name, equipment, words", [
    ("B-1 Fire Rate", "B-1", ["fire", "rate"]),              # equipment name dropped
    ("EF-2 Status", "EF-2", ["status", "fan"]),               # only a function left: keep the type word
    ("CWP-1 ISO Valve", "CWP-1", ["iso", "valve"]),           # something else left: no type word
    ("HHWP-2", "HHWP-2", ["hhwp", "2"]),                      # nothing would remain: name kept as is
    ("Fire Rate", "B-1", ["fire", "rate"]),                   # equipment name not in the point name
])
def test_point_name_without_its_equipment(km, name, equipment, words):
    assert ClassMatcher(km, "point").tokens_without(name, equipment)[0] == words


def _rec(i, name, path):
    return RawRecord(f"p{i}", "test", "t.csv", i, name, path=path)


def test_medium_feeds_need_evidence_and_a_single_source(km):
    recs = [_rec(1, "Space Temp", "HW Plant/x"),  # gives the plant folder a point
            _rec(2, "Space Temp", "VAV-1"), _rec(3, "Airflow", "VAV-1"), _rec(4, "Damper Cmd", "VAV-1"),
            _rec(5, "Reheat Valve Cmd", "VAV-1"),
            _rec(6, "Space Temp", "VAV-2"), _rec(7, "Airflow", "VAV-2"), _rec(8, "Damper Cmd", "VAV-2")]
    store = Store(":memory:")
    Mapper(km).run([r if r.source_id != "p1" else _rec(1, "HW Supply Temp", "Hot Water Plant") for r in recs], store, "t")
    feeds = {(e["src"], e["dst"]): json.loads(e["attrs"])["medium"] for e in store.edges("t", "feeds")}
    assert feeds == {("eq:Hot Water Plant", "eq:VAV-1"): "hot_water"}  # VAV-2 has no reheat valve
    # Two separate hot water plants: no way to tell which feeds VAV-1, so nothing is inferred.
    store2 = Store(":memory:")
    Mapper(km).run(recs[1:] + [_rec(1, "HW Supply Temp", "Hot Water Plant"), _rec(9, "HW Supply Temp", "HW Plant B")],
                   store2, "t")
    assert not store2.edges("t", "feeds")


def test_unknown_name_gets_generic_class(km):
    g = ClassMatcher(km, "point").classify("Zork Blarg")
    assert g.cls == "Sensor" and g.confidence == 0.1 and g.unknown == ["zork", "blarg"]
    assert ClassMatcher(km, "point").classify("Zork Status").cls == "Status"
    assert ClassMatcher(km, "equipment").classify("Zork Blarg").cls is None


def test_equipment_ids_in_names(km):
    m = Mapper(km)
    assert m._equipment_id_in_name("EF-1 Status") == "EF-1"
    assert m._equipment_id_in_name("HHWP-2 S/S") == "HHWP-2"
    assert m._equipment_id_in_name("Damper Command") is None


def _rec(i, name, path=None):
    return RawRecord(f"p{i}", "test", "test.csv", i, name, path=path)


def test_template_refines_generic_airflow_only_without_position_words(km):
    recs = [_rec(1, "Current Airflow", "AHU-1/VAV 1"), _rec(2, "Airflow sensor (Hot)", "AHU-1/VAV 1"),
            _rec(3, "Space Temperature", "AHU-1/VAV 1"), _rec(4, "Damper Command", "AHU-1/VAV 1")]
    store = Store(":memory:")
    Mapper(km).run(recs, store, "t")
    cls = {r["label"]: r["class"] for r in store.nodes("t", "point")}
    assert cls["Current Airflow"] == "Discharge_Air_Flow_Sensor"
    assert cls["Airflow sensor (Hot)"] == "Air_Flow_Sensor"
    feeds = [(e["src"], e["dst"]) for e in store.edges("t", "feeds")]
    assert feeds == [("eq:AHU-1", "eq:AHU-1/VAV 1")]


@pytest.fixture(scope="module")
def alpha_run(km):
    store = Store(":memory:")
    recs = read_blind_export(ROOT / "data/blind/alpha/names_paths.csv")
    summary = Mapper(km).run(recs, store, "alpha/names_paths")
    return store, recs, summary


def test_end_to_end_alpha(alpha_run):
    store, recs, summary = alpha_run
    points = store.nodes("alpha/names_paths", "point")
    assert len(points) == len(recs) == summary["points"]
    assert len(store.edges("alpha/names_paths", "hasPoint")) == len(recs)
    for n in points + store.nodes("alpha/names_paths", "equipment"):
        assert n["method"] in METHODS and 0 <= n["confidence"] <= 1
        assert n["source_file"] and n["source_ref"] and n["revision"] == 1 and n["source"] == "mapper:names_paths.csv"
        # Proposed unless the auto-accept rule confirms it (one source: no agreement), and marked as such.
        auto = n["confidence"] >= 0.9
        assert (n["status"], n["confirmed_by"]) == (("confirmed", "auto") if auto else ("proposed", None))
    assert summary["llm_calls"] == 0


def test_rerun_keeps_human_rows(km):
    store = Store(":memory:")
    recs = [_rec(1, "MAT", "AHU-1"), _rec(2, "OAT", "AHU-1")]
    Mapper(km).run(recs, store, "t")
    store.replace_machine_rows("t", 1, [], [])  # wipe machine rows
    with store.conn:
        store.conn.execute("INSERT INTO nodes (project, id, kind, label, class, source_file, source_ref, method,"
                           " confidence, revision) VALUES ('t', 'pt:p1', 'point', 'MAT', 'Temperature_Sensor',"
                           " 'review', 'x', 'human', 1, 1)")
    Mapper(km).run(recs, store, "t")
    p1 = [n for n in store.nodes("t", "point") if n["id"] == "pt:p1"]
    assert len(p1) == 1 and p1[0]["method"] == "human" and p1[0]["class"] == "Temperature_Sensor"


class FakeLLM:
    name = "fake"

    def __init__(self):
        self.requests: list[LLMRequest] = []

    def classify_point(self, req):
        self.requests.append(req)
        pick = req.candidates[0] if req.candidates else "Not_A_Candidate"
        return LLMAnswer(pick, 0.6, f"picked {pick}", 0.001, 0.01, "fake-model")


def test_llm_only_for_leftovers_and_logged(km):
    store, fake = Store(":memory:"), FakeLLM()
    recs = [_rec(1, "MAT", "AHU-1"), _rec(2, "Zork", "AHU-1"), _rec(3, "Cost", "AHU-1")]
    summary = Mapper(km, llm=fake, llm_below=0.4).run(recs, store, "t")
    asked = [r.name for r in fake.requests]
    assert "MAT" not in asked and "Zork" in asked
    assert all(len(r.candidates) <= 5 for r in fake.requests)
    logged = store.conn.execute("SELECT COUNT(*), SUM(cost_usd) FROM llm_calls").fetchone()
    assert logged[0] == summary["llm_calls"] == len(fake.requests)
    nodes = {n["label"]: n for n in store.nodes("t", "point")}
    assert nodes["Zork"]["method"] != "llm"  # no candidates, so the answer is ignored


def test_component_word_in_the_name_beats_a_class_without_it():
    """Heating_Command and Valve_Command both match "Heating Valve Signal" on two words; the name says valve."""
    from projectmodel.knowledge_model import load_knowledge_model
    from projectmodel.mapper.classify import ClassMatcher
    g = ClassMatcher(load_knowledge_model(), "point").classify("Heating Valve Signal")
    assert g.cls == "Valve_Command"
