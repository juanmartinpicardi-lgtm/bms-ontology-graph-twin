"""The Graphics page and the 2D graphic on the Equipment 3D page, on the graph in data/kg.sqlite (skipped when it
has not been built)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "src/projectmodel/app/views"

pytestmark = pytest.mark.skipif(not (ROOT / "data/kg.sqlite").exists(), reason="run scripts/run_mapper.py first")


def test_graphics_page_shows_coverage_and_graphics():
    at = AppTest.from_file(str(VIEWS / "graphics.py"), default_timeout=180)
    at.query_params["project"] = "alpha/names_paths"
    at.run()
    assert not at.exception
    assert any("Types with a graphic" in m.label for m in at.metric)
    assert any("QA" in c.value for c in at.caption)


def test_equipment_page_shows_the_2d_graphic_and_its_qa():
    at = AppTest.from_file(str(VIEWS / "equipment_3d.py"), default_timeout=60)
    at.query_params.update(project="alpha/names_paths", equip="eq:Airside AHU-2")
    at.run()
    assert not at.exception
    assert any("2D graphic QA" in m.value for m in at.markdown)
