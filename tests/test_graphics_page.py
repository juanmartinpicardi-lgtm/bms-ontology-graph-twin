"""The Graphics page, the Equipments page (3D only) and the Documentation page, on the graph in data/kg.sqlite (skipped when it
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
    assert any("Types with a 3D model" in m.label for m in at.metric)
    assert any("QA" in c.value for c in at.caption)


def test_equipment_page_is_3d_only():
    """No 2D option: an old ?view=2d link still opens the 3D model."""
    at = AppTest.from_file(str(VIEWS / "equipment_3d.py"), default_timeout=60)
    at.query_params.update(project="alpha/names_paths", equip="eq:Airside AHU-2", view="2d")
    at.run()
    assert not at.exception
    assert not at.get("segmented_control")
    assert not any("2D" in m.value for m in at.markdown)


def test_documentation_page_lists_the_source_data():
    at = AppTest.from_file(str(VIEWS / "documentation.py"), default_timeout=60)
    at.query_params["project"] = "alpha/names_paths"
    at.run()
    assert not at.exception
    assert any("documents" in c.value for c in at.caption)
    at.session_state["doc_view"] = "list"
    at.run()
    assert not at.exception
    assert any("alpha.json" in m.value for m in at.markdown)
