"""Sequences of operation: the document parses, every link resolves to the graph or is a deliberate finding, and the
page runs in the app. Runs on the mapped Alpha graph in data/kg.sqlite (skipped when it has not been built)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from projectmodel.db.store import SCHEMA, Edge, Node, Store
from projectmodel.graph_standard import behaviour_facts
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.sequences import behaviour, behaviour_edges, parse_text, render_html, sequences_payload

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"
P = "alpha/names_paths"
needs_db = pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")


def test_links_may_hold_parentheses():
    segs = parse_text("its [status](ch1:Status (CC)) must prove,\n   then [CH-2](ch2).")
    assert segs == [{"t": "its "}, {"t": "status", "ref": "ch1:Status (CC)"}, {"t": " must prove, then "},
                    {"t": "CH-2", "ref": "ch2"}, {"t": "."}]


@pytest.fixture(scope="module")
def payload():
    return sequences_payload(Store(DB), load_knowledge_model(), P)


@needs_db
def test_every_link_resolves_or_is_a_finding(payload):
    findings = {(s["id"], ref): x["status"] for s in payload["sequences"] for ref, x in s["refs"].items()
                if x["status"] != "ok"}
    # Each one is in the text on purpose: what the sequence needs that Alpha's graph lacks or classes differently.
    assert findings == {
        ("vav", "vav.reheat_valve"): "gap", ("vav", "vav.discharge_temp"): "gap",
        ("ahu", "ahu:Duct Static"): "conflict",
        ("chw", "chwp:CW Supply Temp"): "conflict", ("chw", "gap:Chilled water differential pressure sensor"): "gap",
        ("hw", "hwp:Steam SP"): "conflict", ("hw", "hwsys:HW Supply Temp"): "conflict",
    }
    for s in payload["sequences"]:
        assert all(v is not None for v in s["graph_links"].values()), f"{s['id']}: a step walks a link not in the graph"
        assert s["models"], f"{s['id']} shows no 3D equipment"
        for st in s["steps"]:
            if st.get("show"):
                assert st["show"] in s["bind"]


@needs_db
def test_behaviour_feeds_the_complete_graph_page(payload):
    b = behaviour(payload)
    assert b["sequences"] == 4 and b["findings"] == {"ok": 77, "gap": 3, "conflict": 4}
    facts = behaviour_facts(b)
    assert facts["loops"]["state"] == "partial"  # intent only, and two loop ends are missing
    assert facts["intent_asbuilt"]["state"] == "missing"  # no control programs yet


@needs_db
def test_behaviour_becomes_document_edges(payload):
    edges, skipped = behaviour_edges(payload)
    # Gap ends are counted, never stored: the reheat loop (no reheat valve) and the CHW pressure loop (no sensor).
    assert {(s["sequence"], s["rel"]) for s in skipped} == {("vav", "drives"), ("vav", "feedback"), ("chw", "feedback")}
    assert all(e.method == "document" and e.attrs["intent"] and e.src != e.dst for e in edges)
    assert len({(e.src, e.rel, e.dst) for e in edges}) == len(edges)  # a fact in two sequences is one edge
    assert {e.rel for e in edges} == {"drives", "feedback", "requires", "resets", "requests", "switches"}


def test_document_edges_survive_a_mapper_run(tmp_path):
    s = Store(tmp_path / "kg.sqlite")
    rev = s.start_run("p", "x.csv")
    s.replace_machine_rows("p", rev, [Node("a", "point", "A", None, "x.csv", "1", "parsed", 1.0)], [])
    s.replace_document_edges("p", "doc.yaml", rev, [Edge("a", "drives", "b", "doc.yaml", "seq 1", "document", 1.0)])
    s.replace_machine_rows("p", s.start_run("p", "x.csv"), [], [])
    assert [(e["rel"], e["method"]) for e in s.edges("p")] == [("drives", "document")]


def test_old_database_gains_the_document_method(tmp_path):
    import sqlite3
    db = tmp_path / "old.sqlite"
    old = sqlite3.connect(db)
    old.executescript(SCHEMA.replace(", 'document'", ""))
    old.execute("INSERT INTO edges (project, src, rel, dst, source_file, source_ref, method, confidence, status,"
                " revision, attrs) VALUES ('p','a','feeds','b','f','r','parsed',1,'confirmed',1,'{}')")
    old.commit()
    old.close()
    s = Store(db)
    s.replace_document_edges("p", "doc.yaml", 1, [Edge("a", "drives", "b", "doc.yaml", "seq", "document", 1.0)])
    assert sorted(e["method"] for e in s.edges("p")) == ["document", "parsed"]


@needs_db
def test_page_is_self_contained(payload):
    html = render_html(payload, "light")
    assert "/*__DATA__*/null" not in html.split("const D = ", 1)[1][:20]
    assert '<html lang="en" data-theme="light">' in html


@needs_db
def test_runs_in_the_app():
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/main.py"), default_timeout=90)
    at.switch_page("views/sequences.py").run()
    assert not at.exception
