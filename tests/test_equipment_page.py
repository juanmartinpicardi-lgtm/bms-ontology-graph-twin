"""The Equipment 3D Streamlit page: deep links pick the equipment and the page keeps the address bar in sync.
Runs on the mapped Alpha graph in data/kg.sqlite (skipped when it has not been built)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src/projectmodel/app/pages/3_Equipment_3D.py"

pytestmark = pytest.mark.skipif(not (ROOT / "data/kg.sqlite").exists(), reason="run scripts/run_mapper.py first")


def run(**params) -> AppTest:
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    for k, v in params.items():
        at.query_params[k] = v
    return at.run()


def test_deep_link_opens_that_equipment():
    at = run(project="alpha/names_paths", equip="eq:Airside AHU-4/DD 1-4-1")
    assert not at.exception
    assert at.sidebar.selectbox[1].value == "eq:Airside AHU-4/DD 1-4-1"
    assert at.query_params["equip"] == "eq:Airside AHU-4/DD 1-4-1"


def test_equipment_without_a_model_falls_back_with_a_note():
    at = run(project="alpha/names_paths", equip="eq:Airside AHU-2/SF VFD")
    assert not at.exception
    assert at.sidebar.selectbox[1].value == "eq:Airside AHU-2"  # AHUs first
    assert any("has no 3D model" in i.value for i in at.sidebar.info)
