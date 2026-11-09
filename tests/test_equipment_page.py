"""The Equipment 3D Streamlit page: deep links pick the equipment, the browser (type, search, list, previous /
next, related equipment) switches it, and the address bar stays in sync.
Runs on the mapped Alpha graph in data/kg.sqlite (skipped when it has not been built)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src/projectmodel/app/views/equipment_3d.py"

pytestmark = pytest.mark.skipif(not (ROOT / "data/kg.sqlite").exists(), reason="run scripts/run_mapper.py first")


def run(**params) -> AppTest:
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    for k, v in params.items():
        at.query_params[k] = v
    return at.run()


def test_deep_link_opens_that_equipment():
    at = run(project="alpha/names_paths", equip="eq:Airside AHU-4/DD 1-4-1")
    assert not at.exception
    assert at.session_state["equip"] == "eq:Airside AHU-4/DD 1-4-1"
    assert at.radio(key="eq_pick").value == "eq:Airside AHU-4/DD 1-4-1"  # the list shows what is open
    assert at.query_params["equip"] == "eq:Airside AHU-4/DD 1-4-1"


def test_equipment_without_a_model_falls_back_with_a_note():
    at = run(project="alpha/names_paths", equip="eq:Airside AHU-2/SF VFD")
    assert not at.exception
    assert at.session_state["equip"] == "eq:Airside AHU-2"  # AHUs first
    assert any("has no 3D model" in t.value for t in at.toast)


def test_browse_by_search_list_next_and_related():
    at = run(project="alpha/names_paths")
    at.text_input(key="eq_q").input("1-2-8").run()  # search looks across every type
    assert "VAV 1-2-81" in at.radio(key="eq_pick").options
    vav = "eq:Airside AHU-2/VAV 1-2-81"
    at.radio(key="eq_pick").set_value(vav).run()
    assert at.session_state["equip"] == vav and at.query_params["equip"] == vav
    at.text_input(key="eq_q").input("").run()
    assert at.session_state["eq_type"] == "vav" and at.radio(key="eq_pick").value == vav
    at.button(key="eq_next").click().run()
    assert at.session_state["equip"] == "eq:Airside AHU-2/VAV 1-2-82"
    at.button(key="rel_fed by_eq:Airside AHU-2").click().run()  # up to the AHU that feeds it
    assert at.session_state["equip"] == "eq:Airside AHU-2" and at.session_state["eq_type"] == "ahu"
    assert not at.exception


def test_deep_link_through_the_app_sets_the_shared_project():
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/main.py"), default_timeout=60)
    at.query_params.update(project="alpha/names_only", equip="eq:Airside AHU-2")
    at.switch_page("views/equipment_3d.py").run()
    assert not at.exception
    assert at.session_state["project"] == "alpha/names_only"  # the header dropdown is keyed to this


def test_scenario_link_runs_app_wide_and_stays_in_the_address_bar():
    at = run(project="alpha/names_paths", equip="eq:Airside AHU-2", scenario="chw_warm")
    assert not at.exception and at.session_state["sim_scenario"] == "chw_warm"
    started = at.session_state["sim_started"]
    at.button(key="eq_next").click().run()  # the scenario and its clock carry over to the next equipment
    assert at.session_state["sim_scenario"] == "chw_warm" and at.session_state["sim_started"] == started
    assert at.query_params["scenario"] == "chw_warm"
    at.selectbox(key="sim_scenario").select("normal").run()
    assert "scenario" not in at.query_params


def test_related_jumps_walk_from_a_vav_up_to_the_chiller_and_back():
    at = run(project="alpha/names_paths", equip="eq:Airside AHU-2/VAV 1-2-81")
    rel = lambda: [b.key for b in at.button if b.key.startswith("rel_")]  # noqa: E731
    assert rel() == ["rel_fed by_eq:Airside AHU-2"]  # a VAV feeds nothing
    at.button(key="rel_fed by_eq:Airside AHU-2").click().run()
    assert "rel_fed by_eq:Waterside Chilled Water Plant/CH-1" in rel()  # the plant's lead unit stands in for it
    at.button(key="rel_fed by_eq:Waterside Chilled Water Plant/CH-1").click().run()
    assert at.session_state["equip"] == "eq:Waterside Chilled Water Plant/CH-1"
    assert "rel_feeds_eq:Airside AHU-2" in rel()  # CH-1 feeds what its plant feeds
