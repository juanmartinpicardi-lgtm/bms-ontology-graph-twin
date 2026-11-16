"""Guided setup (src/projectmodel/intake): tag rules, each document reader, and the whole Troop D package end to end,
scored against the Troop D answer key."""
import pytest

from projectmodel.intake import model, score, steps, tags
from projectmodel.intake.state import Intake

PACKAGE = steps.TEST_PACKAGE


@pytest.mark.parametrize("text, normal", [
    ("VAVE07", "VAVE7"), ("VAVE-07", "VAVE7"), ("CH01a", "CH1A"), ("EF-LAB-1", "EFLAB1"), ("AHU-1", "AHU1"),
    ("FVAV18", "FVAV18"),
])
def test_tag_normal(text, normal):
    assert tags.normal(text) == normal


def test_tag_prefers_longer_prefix_and_ignores_words():
    assert tags.parse("FVAV-03").prefix == "FVAV"
    assert tags.normal("BOILER ROOM") is None  # one-letter prefix B only with a separator or two digits


def test_tag_classes_exist_in_brick():
    brickschema = pytest.importorskip("brickschema")
    from rdflib import OWL, RDF, Namespace
    brick = Namespace("https://brickschema.org/schema/Brick#")
    classes = set(brickschema.Graph(load_brick=True).subjects(RDF.type, OWL.Class))
    missing = {r["class"] for r in tags.rules()["prefixes"].values() if brick[r["class"]] not in classes}
    assert not missing


@pytest.fixture(scope="module")
def intake(tmp_path_factory):
    if not PACKAGE.exists():
        pytest.skip("test package missing: run scripts/build_troop_d.py")
    it = Intake.create("Troop D test", root=tmp_path_factory.mktemp("intake"))
    for s in steps.STEPS[:-1]:
        f = PACKAGE / s.test_file
        it.add_file(s.id, f.name, f.read_bytes())
        steps.run(it, s.id, lambda msg: None)
    return it


def test_every_step_reads(intake):
    for s in steps.STEPS[:-1]:
        assert intake.done(s.id) and intake.facts(s.id), s.id


def test_building(intake):
    b = model.building(intake)
    assert len(b["floors"]) == 4
    assert len(b["rooms"]) == 80
    assert len(b["points"]) == 847


def test_schedules_classes(intake):
    equip = [e for e in intake.facts("schedules", kind="equipment") if e["conf"] >= 0.9]  # read from a schedule row
    assert len(equip) >= 72


def test_known_design_issues_found(intake):
    labels = " ".join(f["label"] for f in intake.facts(kind="issue"))
    assert "FVAV15" in labels  # heating cfm below its minimum


def test_answers_survive_a_reread(intake):
    q = intake.open_questions("plans")[0]
    intake.decide(q["id"], "fixed", None, q["ask"]["field"])
    steps.run(intake, "plans", lambda msg: None)
    assert intake.fact(q["id"])["method"] == "human"
    intake.undo(q["id"])


def test_score_against_answer_key(intake):
    rows = {r["measure"]: r for r in score.score(intake, "troop_d")}
    assert rows["Rooms found"]["machine"] == rows["Rooms found"]["out of"]
    assert rows["Equipment class right"]["machine"] == rows["Equipment class right"]["out of"]
    assert rows["Points found"]["machine"] == rows["Points found"]["out of"] == 847
    assert rows["Equipment found"]["machine"] >= 72
    assert rows["Point class right or broader"]["machine"] / 847 > 0.75


def test_plan_vectors(intake):
    """The floor is drawn from the PDF's own lines: thousands of segments and the page's words, inside the plan."""
    import base64

    from projectmodel.intake import vectors
    floor = model.building(intake)["floors"][0]
    geo = vectors.plan(intake.file_by_name(floor["file"]), floor["page"], floor["crop"])
    assert geo["n"] > 5000 and not geo["image"]
    assert len(base64.b64decode(geo["seg"])) == geo["n"] * 8 and len(base64.b64decode(geo["wt"])) == geo["n"]
    assert all(0 <= x <= 1 and 0 <= y <= 1 for _, x, y, _ in geo["words"])


def test_twin_payload_units_point_back_to_the_plan(intake):
    from projectmodel.intake import twin
    b = model.building(intake)
    plans = {f["id"]: {"key": f["id"], "n": 0, "seg": "", "wt": "", "words": [], "image": ""} for f in b["floors"]}
    needs = {f["id"] for f in intake.open_questions()}
    data = twin.payload(b, plans, None, {f["id"]: f for f in intake.open_questions()})
    units = [u for f in data["floors"] for u in f["units"]]
    assert len(units) >= 70 and len({u["tag"] for u in units}) == len(units)
    for u in units:
        assert u["id"] in u["ids"] and intake.fact(u["id"])
        assert (u["s"] == "ask") == any(i in needs for i in u["ids"]) == bool(u["q"])
        assert all(q["id"] in needs and q["q"] for q in u["q"])


def test_graph_payload(intake):
    from projectmodel.intake import graph
    g = graph.payload(intake, model.building(intake))
    ids = {n["id"] for n in g["nodes"]}
    assert g["counts"]["nodes"]["location"] == 85 and g["counts"]["nodes"]["point"] > 800
    assert all(link["source"] in ids and link["target"] in ids for link in g["links"])
    assert all(n["fact"] and intake.fact(n["fact"]) for n in g["nodes"] if n["id"] != "building")
    assert {"hasPart", "serves", "feeds", "hasPoint"} <= set(g["counts"]["links"])


def test_knowledge_rules_change_the_reading_and_notes_reach_the_graph(intake):
    from projectmodel.intake import graph, knowledge, twin
    try:
        assert tags.normal("CRAC-3") is None
        knowledge.add_tag(intake, "crac", "AHU", "ahu", False)
        assert tags.normal("CRAC-3") == "CRAC3" and tags.parse("CRAC-3").cls == "AHU"
        assert steps.stale(intake, "plans") == ["The rules you added"]

        knowledge.add_term(intake, "SF-C", "Fan_Command")
        steps.run(intake, "submittal", lambda msg: None)
        sf = next(p for p in intake.facts("submittal", kind="point") if p["data"]["short"] == "SF-C")
        assert sf["data"]["class"] == "Fan_Command" and sf["status"] == "confirmed"

        unit = next(iter(model.building(intake)["equip"].values()))
        knowledge.add_note(intake, f"unit:{unit['normal']}", unit["tag"], "history", "Replaced in 2022.", "Ana")
        g = graph.payload(intake, model.building(intake))
        assert g["notes"][f"unit:{unit['normal']}"][0]["body"] == "Replaced in 2022."
        b = model.building(intake)
        plans = {f["id"]: {"key": "", "n": 0, "seg": "", "wt": "", "words": [], "image": ""} for f in b["floors"]}
        data = twin.payload(b, plans, None, {}, notes=knowledge.notes_for(intake))
        assert any(u["notes"] for f in data["floors"] for u in f["units"])

        text = knowledge.export(intake)
        other = Intake.create("Other", root=intake.dir.parent)
        added, problems = knowledge.load(other, text, {"equipment": {"AHU"}, "point": set()})
        assert added == 2 and len(problems) == 1 and "Fan_Command" in problems[0]  # a class the model lacks is refused
    finally:
        intake.s["knowledge"] = {}
        intake.save()
        knowledge.apply(intake)
        steps.run(intake, "submittal", lambda msg: None)
    assert tags.normal("CRAC-3") is None


def test_scanned_plan_falls_back_to_a_picture(tmp_path):
    """A page with no vector lines (a scan) is drawn from a sharp picture of the plan area instead."""
    from PIL import Image, ImageDraw

    from projectmodel.intake import vectors
    img = Image.new("RGB", (1200, 800), "white")
    ImageDraw.Draw(img).rectangle([100, 100, 1100, 700], outline="black", width=4)
    scan = tmp_path / "scan.pdf"
    img.save(scan, "PDF", resolution=100)
    geo = vectors.plan(scan, 0, [0, 0, 864, 576])
    assert geo["n"] == 0 and geo["words"] == [] and geo["image"].startswith("data:image/png;base64,")
