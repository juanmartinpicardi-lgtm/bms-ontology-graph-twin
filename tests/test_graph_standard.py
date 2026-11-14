"""The complete-graph definition is consistent, its status is measured on the real graph, and the page runs.
Status tests run on the mapped Alpha graph in data/kg.sqlite (skipped when it has not been built)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from projectmodel.db.store import Store
from projectmodel.graph_standard import PROJECT, definition, render_html, status
from projectmodel.knowledge_model import load_knowledge_model

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"
needs_db = pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")


def test_definition_is_consistent():
    d = definition()
    sources, layers = {s["id"] for s in d["sources"]}, {l["id"] for l in d["layers"]}
    assert len({f["id"] for f in d["facts"]}) == len(d["facts"])
    for f in d["facts"]:
        assert f["layer"] in layers, f["id"]
        assert set(f["sources"]) <= sources, f["id"]
        assert set(f["sources"].values()) <= {"primary", "support", "check"}, f["id"]
        assert "primary" in f["sources"].values(), f"{f['id']} has no primary source"
    assert {s["today"] for s in d["sources"]} == {"now", "next", "later"}
    assert all(any(f["layer"] == l for f in d["facts"]) for l in layers), "every layer has facts"


@needs_db
def test_status_measures_every_fact_without_guessing():
    s = status(Store(DB), load_knowledge_model(), PROJECT)
    assert set(s) == {f["id"] for f in definition()["facts"]}
    assert all(v["state"] in ("done", "partial", "missing") for v in s.values())
    assert s["point_equip"]["state"] == "done"
    assert s["feeds"]["pct"] == 100.0  # every VAV has exactly one air handler (reheat water feeds don't count)
    # not in a names + folders input, so not claimed
    assert s["point_props"]["state"] == s["spaces"]["state"] == s["agreement"]["state"] == "missing"


def test_page_is_self_contained():
    d = dict(definition(), status={f["id"]: {"pct": None, "state": "missing", "note": ""} for f in definition()["facts"]},
             project_label="x")
    html = render_html(d, "dark")
    assert "/*__DATA__*/null" not in html and '<html lang="en" data-theme="dark">' in html


@needs_db
def test_runs_in_the_app():
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/main.py"), default_timeout=60)
    at.switch_page("views/complete_graph.py").run()
    assert not at.exception
