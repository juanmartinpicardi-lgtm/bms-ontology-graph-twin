"""The learning loop (curator.py, W10): review fixes are captured with their features; a fix made twice becomes a
proposed convention; once a person approves it, it is a file under knowledge/skills/ and the next mapper run applies
it (method rule, its id in the provenance) without touching a person's decisions. Models are scripted or off."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

from projectmodel import curator, review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.ai import Router, Scripted
from projectmodel.ai.config import AIConfig
from projectmodel.ai.jobs import check_output
from projectmodel.conventions import ConventionError, Layer, apply_conventions, learned_terms, scopes_for
from projectmodel.db.store import Node, Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.memory import KNOWLEDGE_DIR, load_knowledge
from projectmodel.scoring.score import load_ground_truth, score_project

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"
WANT = "Occupancy_Command"  # the key's class for VAV "Occupied status"; the rules say Occupancy_Status


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture(scope="module")
def records():
    return read_blind_export(ROOT / "data/blind/alpha/names_paths.csv")


@pytest.fixture
def kdir(tmp_path, monkeypatch):
    """A copy of knowledge/ that approvals write to: the repo's files never change."""
    d = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, d)
    monkeypatch.setenv("PM_KNOWLEDGE_DIR", str(d))
    return d


def run(store, records):
    km = load_knowledge_model(conventions=scopes_for(P))
    Mapper(km).run(records, store, P)
    return km


@pytest.fixture
def mapped(km, records, kdir):
    store = Store(":memory:")
    run(store, records)
    return store


def occupied(store, n=None):
    ids = [r["id"] for r in store.nodes(P, "point") if r["label"] == "Occupied status"]
    return ids[:n] if n else ids


def node(store, nid):
    return store.conn.execute("SELECT * FROM nodes WHERE project = ? AND id = ?", (P, nid)).fetchone()


def test_a_fix_keeps_what_a_rule_could_key_on(mapped, km):
    pid = occupied(mapped, 1)[0]
    review.fix_class(mapped, km, P, [pid], WANT, "ana")
    rv = json.loads(node(mapped, pid)["attrs"])["review"]
    assert rv["previous"]["class"] == "Occupancy_Status" and rv["previous"]["source"].startswith("mapper:")
    f = rv["features"]
    assert f["name"] == "Occupied status" and f["words"] == ["occupied", "status"]
    assert f["template"] == "vav" and f["equipment"].startswith("eq:") and f["folder"]
    assert f["source"].startswith("mapper:") and "role" in f
    fx = curator.fixes(mapped, P)
    assert [(x.kind, x.before, x.after) for x in fx] == [("class", "Occupancy_Status", WANT)]


def test_a_move_is_captured_too(mapped):
    pid = occupied(mapped, 1)[0]
    on = next(e["src"] for e in mapped.edges(P, "hasPoint") if e["dst"] == pid)
    to = next(r["id"] for r in mapped.nodes(P, "equipment") if r["id"] != on)
    review.move_points(mapped, P, [pid], to, "ana")
    fx = [x for x in curator.fixes(mapped, P) if x.kind == "move"]
    assert len(fx) == 1 and (fx[0].before, fx[0].after) == (on, to) and fx[0].f["name"] == "Occupied status"


def test_one_fix_is_not_a_pattern_two_are(mapped, km):
    a, b = occupied(mapped, 2)
    review.fix_class(mapped, km, P, [a], WANT, "ana")
    assert curator.find(mapped, km, P) == []
    review.fix_class(mapped, km, P, [b], WANT, "ana")
    [c] = curator.find(mapped, km, P)
    assert (c.before, c.after, c.template, c.kind) == ("Occupancy_Status", WANT, "vav", "class_hints")
    o = c.option(c.chosen)
    assert len(o.would_change) == len(occupied(mapped)) - 2 and a not in o.would_change


def test_propose_approve_apply_and_score(mapped, km, records, kdir):
    gt = load_ground_truth("alpha")
    before = score_project(mapped, P, gt, km, 0.8)
    a, b = occupied(mapped, 2)
    review.fix_class(mapped, km, P, [a, b], WANT, "ana")
    [p] = curator.propose(mapped, km, P)  # PM_AI=off in the tests: the rules choose and phrase
    assert p["status"] == "pending" and p["checks"]["phrased_by"] == "rules"
    assert p["payload"]["entry"] | {} == {"pattern": p["payload"]["entry"]["pattern"], "class": WANT,
                                          "template": "vav", "instead_of": "Occupancy_Status"}
    assert curator.propose(mapped, km, P)[0]["id"] == p["id"]  # refreshed, not duplicated
    assert len(curator.pending(mapped, P)) == 1

    # Not applied before a person approves it.
    run(mapped, records)
    assert node(mapped, occupied(mapped)[5])["class"] == "Occupancy_Status"

    path = curator.approve(mapped, km, p["id"], "ben", knowledge=kdir)
    assert path == kdir / "skills/site/alpha/learned-conventions-alpha/rules/conventions.yaml"
    [hint] = yaml.safe_load(path.read_text())["class_hints"]
    assert hint["id"] == p["id"] and hint["approved_by"] == "ben"
    kb = load_knowledge(km=km)  # the skill and its rules validate like any other
    assert kb.skills["learned-conventions-alpha"].approved_by == "ben"
    assert curator.proposal(mapped, p["id"])["status"] == "approved" and curator.pending(mapped) == []
    assert scopes_for(P) == ["site/alpha"]
    assert [x["id"] for x in curator.learned()] == [p["id"]]

    km2 = run(mapped, records)
    assert "site/alpha/learned-conventions-alpha" in km2.conventions
    others = [node(mapped, x) for x in occupied(mapped) if x not in (a, b)]
    assert all(n["class"] == WANT and n["method"] == "rule" for n in others)
    assert all(f"site/alpha:{p['id']}" in json.loads(n["attrs"])["convention"] for n in others)
    assert all(node(mapped, x)["method"] == "human" for x in (a, b))
    after = score_project(mapped, P, gt, km, 0.8)
    assert after["H2_exact_pct"] > before["H2_exact_pct"]
    # Nothing outside VAV "Occupied status" points changed class.
    changed = [n for n in mapped.nodes(P, "point") if f"site/alpha:{p['id']}" in json.loads(n["attrs"]).get(
        "convention", [])]
    assert {n["label"] for n in changed} == {"Occupied status"}


def test_a_convention_never_overrides_a_person(mapped, km, records, kdir):
    a, b, c = occupied(mapped, 3)
    review.fix_class(mapped, km, P, [a, b], WANT, "ana")
    [p] = curator.propose(mapped, km, P)
    curator.approve(mapped, km, p["id"], "ben", knowledge=kdir)
    review.fix_class(mapped, km, P, [c], "Occupancy_Status", "cy")  # a person says otherwise for this one
    run(mapped, records)
    assert node(mapped, c)["class"] == "Occupancy_Status" and node(mapped, c)["method"] == "human"


def test_a_pattern_that_contradicts_a_person_is_not_proposed(mapped, km):
    a, b, c = occupied(mapped, 3)
    review.fix_class(mapped, km, P, [a, b], WANT, "ana")
    review.accept(mapped, P, [c], "cy")  # a person confirmed Occupancy_Status on the same name
    assert curator.find(mapped, km, P) == []


def test_rejected_stays_rejected(mapped, km):
    review.fix_class(mapped, km, P, occupied(mapped, 2), WANT, "ana")
    [p] = curator.propose(mapped, km, P)
    curator.reject(mapped, p["id"], "ben", "the key is wrong here")
    assert curator.propose(mapped, km, P) == []
    assert curator.proposal(mapped, p["id"])["reason"] == "the key is wrong here"
    with pytest.raises(ValueError, match="already rejected"):
        curator.approve(mapped, km, p["id"], "ben")


def test_the_model_picks_an_option_and_phrases_it(mapped, km):
    review.fix_class(mapped, km, P, occupied(mapped, 2), WANT, "ana")
    [c] = curator.find(mapped, km, P)
    oid = c.options[-1].id
    answer = {"choices": [{"candidate": "C1", "option": f"C1.{oid}", "title": "VAV occupied status is a command",
                           "why": "Two fixes; the rest of the VAVs follow."}]}
    router = Router(AIConfig(project="test"), providers={"claude": Scripted([json.dumps(answer)])})
    [p] = curator.propose(mapped, km, P, router=router)
    assert p["payload"]["chosen"] == oid and p["payload"]["title"] == "VAV occupied status is a command"
    assert p["checks"]["phrased_by"] == "sonnet" and p["payload"]["entry"]["class"] == WANT
    calls = mapped.conn.execute("SELECT job, ok FROM llm_calls").fetchall()
    assert [tuple(r) for r in calls] == [("memory_curator", 1)]


def test_the_model_cannot_name_ids_it_was_not_given():
    values = {"option_ids": {"C1": ["names", "words"]}}
    ok = {"choices": [{"candidate": "C1", "option": "C1.words", "title": "t", "why": "w"}]}
    assert check_output("memory_curator", ok, values) is None
    bad_option = {"choices": [{"candidate": "C1", "option": "C1.Occupancy_Command", "title": "t", "why": "w"}]}
    assert "not an option" in check_output("memory_curator", bad_option, values)
    bad_candidate = {"choices": [{"candidate": "C7", "option": "C7.words", "title": "t", "why": "w"}]}
    assert "not a candidate" in check_output("memory_curator", bad_candidate, values)


def test_scoped_hints_are_checked_like_any_convention(km, tmp_path):
    def layer(**h):
        return Layer("site/x", tmp_path / "x.yaml", {"scope": "site/x", "class_hints": [{"pattern": "x", **h}]})
    with pytest.raises(ConventionError, match="template 'nope'"):
        apply_conventions(km, [layer(**{"class": "Occupancy_Status", "template": "nope"})])
    with pytest.raises(ConventionError, match="instead_of"):
        apply_conventions(km, [layer(**{"class": "Occupancy_Status", "instead_of": "Nope"})])
    with pytest.raises(ConventionError, match="optionally"):
        apply_conventions(km, [layer(**{"class": "Occupancy_Status", "colour": "red"})])
    m = apply_conventions(km, [layer(**{"class": "Occupancy_Status", "template": "vav", "id": "lc-000001"})])
    assert m.class_hints[0].origin == "site/x:lc-000001" and m.class_hints[0].scoped


def test_setup_fixes_become_terms_the_setup_reads(km, kdir, tmp_path):
    from projectmodel.intake import knowledge, submittal
    from projectmodel.intake.state import Intake

    proj = "bldg/documents"
    store = Store(":memory:")
    rev = store.start_run(proj, "setup")
    nodes = [Node(f"pt:FC-{i}.OCC", "point", "OCC-S", "Occupancy_Status", "sub.pdf", f"p{i}", "rule", 0.7,
                  {"description": "Occupied Status", "device": f"VAV-{i}"}) for i in range(4)]
    store.write_source(proj, "setup:submittal", rev, nodes)
    review.fix_class(store, km, proj, ["pt:FC-0.OCC", "pt:FC-1.OCC"], WANT, "ana")
    [p] = curator.propose(store, km, proj)
    assert p["payload"]["kind"] == "terms" and p["payload"]["entry"] == {"phrase": "OCC-S", "class": WANT}
    assert p["checks"]["would_change"] == 2
    path = curator.approve(store, km, p["id"], "ben", knowledge=kdir)
    assert path.name == "terms.yaml" and learned_terms(proj) == [("OCC-S", WANT)]
    load_knowledge(km=km)

    it = Intake.create("bldg", root=tmp_path / "intake")
    try:
        knowledge.apply(it)  # the setup's hook: the building's own terms plus the learned ones
        assert submittal.by_term("Occupied Status", "OCC-S") == WANT
    finally:
        submittal.use_terms([])


def test_the_simulation_measures_on_points_that_were_not_fixed():
    from projectmodel.scoring import learning

    r = learning.simulate(P, fixes=2, max_patterns=2, also=[], log=lambda *a: None)
    assert r["fixed_points"] == 4 and len(r["conventions"]) == 2
    for c in r["conventions"]:
        assert c["touched"] > 0 and c["wrong_after"] < c["wrong_before"]
    for p in r["patterns"]:
        assert p["held_out"] > 0 and len(p["fixed"]) == 2
    o = r["overall"]
    assert o["before"]["n"] == o["after"]["n"] and o["after"]["exact"] > o["before"]["exact"]
    assert not (KNOWLEDGE_DIR / "skills/site/alpha").exists()  # the repo's knowledge/ is untouched


@pytest.mark.skipif(not (ROOT / "data/kg.sqlite").exists(), reason="run scripts/run_mapper.py first")
@pytest.mark.parametrize("page", ["tribal.py", "project_tribal.py"])
def test_tribal_pages_run(page, kdir, monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest

    from streamlit.delta_generator import DeltaGenerator

    # Page links resolve only under the app's navigation (app/main.py), not in a page run on its own.
    monkeypatch.setattr(streamlit, "page_link", lambda *a, **k: None)
    monkeypatch.setattr(DeltaGenerator, "page_link", lambda *a, **k: None)

    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/views" / page), default_timeout=120).run()
    assert not at.exception


def test_a_person_approves_in_the_tribal_page(km, records, kdir, tmp_path, monkeypatch):
    import streamlit
    from streamlit.delta_generator import DeltaGenerator
    from streamlit.testing.v1 import AppTest

    from projectmodel.app import shell

    store = Store(tmp_path / "kg.sqlite")
    run(store, records)
    review.fix_class(store, km, P, occupied(store, 2), WANT, "ana")
    [p] = curator.propose(store, km, P)
    monkeypatch.setattr(shell, "DB", tmp_path / "kg.sqlite")
    monkeypatch.setattr(streamlit, "page_link", lambda *a, **k: None)
    monkeypatch.setattr(DeltaGenerator, "page_link", lambda *a, **k: None)
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/views/tribal.py"), default_timeout=120).run()
    assert not at.exception and at.button(key=f"ap_{p['id']}").disabled  # no approver named yet
    at.text_input(key="tk_who").input("ben").run()
    at.button(key=f"ap_{p['id']}").click().run()
    assert not at.exception
    assert curator.proposal(Store(tmp_path / "kg.sqlite"), p["id"])["decided_by"] == "ben"
    assert (kdir / "skills/site/alpha/learned-conventions-alpha/rules/conventions.yaml").exists()
