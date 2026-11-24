"""The document front end for plans (plan-workflow-ai W6): page rendering with coordinates that match the text layer,
page sorting by rules, the plan_meaning job's candidates, checks and merge, and the plans step with the model off.
Every model here is scripted: nothing leaves the machine."""
import copy
import json
from pathlib import Path

import pytest

from projectmodel.ai import Router, Scripted, jobs
from projectmodel.ai.config import AIConfig
from projectmodel.db.store import Store
from projectmodel.intake import floorplans, pages, pdfdoc, plan_ai
from projectmodel.intake.pdfdoc import Word
from projectmodel.intake.state import AUTO_ACCEPT

ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "test_packages/troop_d/1_floor_plans.pdf"
READY = AIConfig(project="test-project")
NAME = "1_floor_plans.pdf"


def W(text, x0, top, size=8.0, font="Arial", w=None):
    return Word(text, x0, top, x0 + (w or 0.55 * size * len(text)), top + size, font, size)


# ---------------------------------------------------------------- vision input

def test_page_image_maps_points_to_pixels_and_back():
    pw, ph = pdfdoc.page_size(PLANS, 0)
    full = pdfdoc.page_image(PLANS, 0, dpi=36)
    assert full.image.size == (round(pw / 2), round(ph / 2))
    crop = [100.0, 200.0, 700.0, 500.0]
    im = pdfdoc.page_image(PLANS, 0, dpi=144, crop=crop)
    assert im.image.size == (1200, 600)
    assert im.to_px(100, 200) == (0, 0) and im.to_px(400, 350) == (600, 300)
    assert im.to_pt(*im.to_px(321.5, 456.25)) == pytest.approx((321.5, 456.25))
    # the longest side is capped: the dpi drops, the mapping stays exact
    capped = pdfdoc.page_image(PLANS, 0, dpi=300, max_px=1000)
    assert max(capped.image.size) <= 1001 and capped.dpi < 300
    assert capped.to_pt(*capped.to_px(pw, ph)) == pytest.approx((pw, ph))
    block = im.block()
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"


def test_page_image_draws_ids_where_the_words_are():
    ws = pdfdoc.words(PLANS, 0)
    w = next(v for v in ws if v.text == "144")
    plain = pdfdoc.page_image(PLANS, 0, dpi=72)
    marked = pdfdoc.page_image(PLANS, 0, dpi=72, labels=[{"id": "R1", "bbox": w.bbox, "color": "#1F5FD0"}])
    x, y = (round(v) for v in marked.to_px(w.x1 + 6, w.top + 2))
    red, green, blue = marked.image.getpixel((x, y))
    assert plain.image.getpixel((x, y)) != (red, green, blue) or blue > red  # the id is drawn right of the label


def test_sheet_id_reads_any_usual_style():
    for text in ("M-101", "M201", "M.201", "M1.0", "FP-1"):
        assert pdfdoc.sheet_id([W("NOTES", 10, 10, 8), W(text, 2400, 1650, 18)]) == text
    assert pdfdoc.sheet_id([W("M201", 2400, 1650, 8)]) == ""  # small text is a reference, not the sheet number


# ---------------------------------------------------------------- page sorting

def _page(*titles, size=14):
    return [W(t, 100, 100 + 40 * i, size, w=300) for i, t in enumerate(titles)]


@pytest.mark.parametrize("titles,kind", [
    (["MECHANICAL PLAN - LEVEL 1"], "plan"),
    (["FIRST FLOOR HVAC PLAN", "ENLARGED MECHANICAL ROOM PLAN", "FAN COIL SCHEDULE"], "plan"),
    (["MECHANICAL SCHEDULES"], "schedule"),
    (["SEQUENCE OF OPERATIONS"], "sequence"),
    (["BAS NETWORK RISER"], "riser"),
    (["POINTS LIST"], "submittal"),
    (["COVER SHEET"], "other"),
])
def test_page_sorting_by_title_lines(titles, kind):
    s = pages.classify_words(_page(*titles))
    assert (s.kind, s.by) == (kind, "rule")


def test_page_sorting_leaves_what_it_cannot_tell_to_the_model():
    assert pages.classify_words([]).kind == "unsorted"  # a scan
    assert pages.classify_words(_page("GENERAL NOTES")).kind == "unsorted"
    # a note that points to a plan is not a title
    assert pages.classify_words(_page("SEE ROOF PLAN FOR CONTINUATION", "MECHANICAL SCHEDULES")).kind == "schedule"
    tied = pages.classify_words(_page("LEVEL 1 PLAN", "EQUIPMENT SCHEDULES"))
    assert tied.kind == "unsorted" and tied.by == "none"


def test_page_sorting_on_the_troop_d_plans():
    assert [s.kind for s in pages.sort(PLANS)] == ["plan"] * 4


# ---------------------------------------------------------------- candidates

def synthetic_page():
    return [
        W("OFFICE", 100, 100), W("154", 104, 110),                      # a room label: name above the number
        W("S-1", 300, 100), W("120", 302, 110),                          # airflow under a diffuser: not a room
        W("STORAGE", 500, 100), W("155", 504, 110),
        W("FC-1.16", 140, 150),                                          # a unit label
        W("T", 200, 200, 6), W("(FC-1.16)", 210, 200),                  # its thermostat callout
        W("SAV", 400, 300, 7), W("3", 404, 308, 7),                      # a two-line hexagon
        W("(EH-1/EF-7)", 600, 300),                                      # one sensor naming two units
        W("S-1", 700, 300),                                              # a diffuser type: not equipment
    ]


def test_candidates_find_rooms_and_tags_in_their_written_forms():
    pc = plan_ai.candidates(synthetic_page(), 0, (1000, 800))
    assert sorted(c["text"] for c in pc.rooms.values()) == ["154", "155"]
    found = {t["text"]: t for t in pc.tags.values()}
    assert set(found) == {"FC-1.16", "SAV-3", "EH-1", "EF-7"}
    assert sorted(o["role"] for o in found["FC-1.16"]["occ"]) == ["sensor callout", "unit label"]
    assert found["EH-1"]["occ"][0]["role"] == "sensor callout"
    values = plan_ai.prompt_values(pc, "plans.pdf")
    assert values["room_ids"] == list(pc.rooms) and values["tag_ids"] == list(pc.tags)
    assert "OFFICE" in values["room_lines"] and "SAV-3" in values["tag_lines"]


def _ids(pc):
    return {c["text"]: rid for rid, c in pc.rooms.items()}, {t["text"]: tid for tid, t in pc.tags.items()}


def answer(views=(("L1", "LEVEL 1 PLAN"),), rooms=(), placements=(), kind="plan"):
    return {"page_kind": kind, "views": [{"floor": f, "title": t} for f, t in views],
            "rooms": [{"id": i, "name": n, "floor": f, "box": b, "confidence": c} for i, n, f, b, c in rooms],
            "placements": [{"tag": t, "room": r, "floor": f, "rel": rel, "confidence": c, "why": "on the plan"}
                           for t, r, f, rel, c in placements]}


def test_rules_check_every_answer():
    pc = plan_ai.candidates(synthetic_page(), 0, (1000, 800))
    R, T = _ids(pc)
    out = answer(rooms=[(R["154"], "Office", "L1", [80, 80, 250, 260], 0.9),
                        (R["155"], "Kitchen", "L2", None, 0.9),          # a name not printed there, a floor not shown
                        ("R99", "Lobby", "L1", None, 0.9)],              # an id we never gave
                 placements=[(T["FC-1.16"], R["154"], "L1", "serves", 0.9),
                             (T["SAV-3"], "R77", "L1", "serves", 0.8)])
    ch = plan_ai.checked({"output": out}, pc)
    rooms = {x["number"]: x for x in ch["rooms"]}
    assert set(rooms) == {"154", "155"} and ch["dropped"] == 1
    assert rooms["154"]["name"] == "Office" and rooms["154"]["raw"] == 0.9 and not rooms["154"]["checks"]
    assert rooms["155"]["name"] == "" and rooms["155"]["floor"] == "L1"
    assert rooms["155"]["raw"] == pytest.approx(0.9 * 0.8 * 0.8)
    pl = {p["tag"]: p for p in ch["placements"]}
    assert pl["FC-1.16"]["room"] == "154" and pl["FC-1.16"]["in_box"] and pl["FC-1.16"]["at"]["role"] == "sensor callout"
    assert pl["SAV-3"]["room"] is None and pl["SAV-3"]["raw"] == pytest.approx(0.8 * 0.6)
    # not a plan: nothing is read from it
    assert plan_ai.checked({"output": answer(kind="schedule", views=())}, pc)["rooms"] == []


def test_job_check_refuses_answers_made_of_invented_ids():
    values = {"room_ids": ["R1", "R2"], "tag_ids": ["T1"]}
    ok = answer(rooms=[("R1", "", "L1", None, 0.8)], placements=[("T1", "R1", "L1", "serves", 0.7)])
    assert jobs.check_output("plan_meaning", ok, values) is None
    bad = answer(rooms=[(f"R{n}", "", "L1", None, 0.8) for n in range(5, 10)])
    assert "not candidates" in jobs.check_output("plan_meaning", bad, values)
    assert "view" in jobs.check_output("plan_meaning", answer(views=(), rooms=[("R1", "", "L1", None, .8)]), values)
    assert jobs.check_output("plan_meaning", {"page_kind": "plan"}, values).startswith("schema")


# ---------------------------------------------------------------- merging with the rules

def rules_facts():
    return floorplans.read(PLANS, NAME, lambda m: None)


def test_merge_keeps_the_rules_answer_and_stays_below_auto_accept():
    facts = rules_facts()
    ws = pdfdoc.words(PLANS, 0)
    pc = plan_ai.candidates(ws, 0, pdfdoc.page_size(PLANS, 0))
    R, T = _ids(pc)
    by = {f["id"]: f for f in facts}
    assert by["place:CWP1"]["data"]["room"] == "144"
    other = next(n for n in R if n != "144" and n.startswith("1"))
    out = answer(views=[("L1", "MECHANICAL PLAN - LEVEL 1")],
                 rooms=[(R["144"], "MECHANICAL ROOM", "L1", None, 0.97), (R[other], "", "L1", None, 0.9)],
                 placements=[(T["CWP-01"], R[other], "L1", "located_in", 0.95)])
    res = [{"page": 0, "cands": pc, "answer": {"output": out, "model": "hydrogen", "calls": [7]},
            "checked": plan_ai.checked({"output": out}, pc)}]
    s = plan_ai.merge(facts, res, NAME, lambda m: None)
    assert s["rooms_agreed"] == 2 and s["placements_changed"] == 1
    f = by["place:CWP1"]
    assert f["method"] == "llm" and f["data"]["room"] == other and f["conf"] <= plan_ai.AI_CAP < AUTO_ACCEPT
    assert f["data"]["rule_room"] == "144" and f["data"]["rule_floor"] == "L1"  # the rules' answer is kept
    assert f["data"]["ai"]["calls"] == [7] and f["data"]["ai"]["job"] == "plan_meaning"
    assert by["room:144"]["method"] == "rule" and by["room:144"]["conf"] >= 0.95  # agreement keeps the rules' fact


def test_merge_adds_what_only_the_model_found_as_a_proposal():
    facts = [f for f in rules_facts() if f["id"] not in ("room:144", "place:CWP1")]
    pc = plan_ai.candidates(pdfdoc.words(PLANS, 0), 0, pdfdoc.page_size(PLANS, 0))
    R, T = _ids(pc)
    out = answer(views=[("L1", "MECHANICAL PLAN - LEVEL 1")], rooms=[(R["144"], "MECHANICAL ROOM", "L1", None, 0.97)],
                 placements=[(T["CWP-01"], R["144"], "L1", "located_in", 0.95)])
    res = [{"page": 0, "cands": pc, "answer": {"output": out, "model": "hydrogen", "calls": []},
            "checked": plan_ai.checked({"output": out}, pc)}]
    s = plan_ai.merge(facts, res, NAME, lambda m: None)
    assert s["rooms_added"] == 1 and s["placements_added"] == 1
    by = {f["id"]: f for f in facts}
    assert by["room:144"]["method"] == "llm" and by["room:144"]["data"]["name"] == "Mechanical Room"
    assert by["place:CWP1"]["method"] == "llm" and by["place:CWP1"]["data"]["room"] == "144"
    assert all(f["conf"] <= plan_ai.AI_CAP for f in facts if f["method"] == "llm")
    assert by["place:CWP1"]["src"]["file"] == NAME and by["place:CWP1"]["src"]["bbox"]


# ---------------------------------------------------------------- the plans step

def test_model_off_leaves_the_rules_reading_unchanged():
    facts = rules_facts()
    before = copy.deepcopy(facts)
    logs = []
    off = Router(AIConfig(project=None, enabled=False, why_off="PM_AI=off"))
    s = plan_ai.refine(PLANS, NAME, facts, logs.append, project="intake:t", cache={}, router=off)
    assert facts == before and s["off"] and any("AI plan reader off" in m for m in logs)


def test_refine_asks_once_per_sheet_logs_the_call_and_the_cost(tmp_path):
    facts = rules_facts()
    pc = plan_ai.candidates(pdfdoc.words(PLANS, 0), 0, pdfdoc.page_size(PLANS, 0))
    R, T = _ids(pc)
    out = answer(views=[("L1", "MECHANICAL PLAN - LEVEL 1")], rooms=[(R["144"], "MECHANICAL ROOM", "L1", None, 0.97)],
                 placements=[(T["CWP-01"], R["144"], "L1", "located_in", 0.95)])
    gemini = Scripted([json.dumps(out)])
    router = Router(READY, providers={"gemini": gemini})
    router.learnt = True
    store = Store(tmp_path / "kg.sqlite")
    cache, logs = {}, []
    s = plan_ai.refine(PLANS, NAME, facts, logs.append, project="intake:t", cache=cache, router=router, store=store,
                       max_pages=1)
    assert s["asked"] == 1 and s["calls"] == 1 and s["usd_per_sheet"] is not None
    assert any("per sheet" in m for m in logs)
    rows = store.conn.execute("SELECT job, ok, prompt FROM llm_calls").fetchall()
    assert [(r["job"], r["ok"]) for r in rows] == [("plan_meaning", 1)] and rows[0]["prompt"].startswith("plan_meaning")
    (model, req), = gemini.requests
    assert any(b.get("type") == "image" for m in req.messages for b in
               (m["content"] if isinstance(m["content"], list) else []))
    assert all(f["conf"] < AUTO_ACCEPT for f in facts if f["method"] == "llm")
    # re-reading the step: the saved answer, no new call
    again = rules_facts()
    s2 = plan_ai.refine(PLANS, NAME, again, logs.append, project="intake:t", cache=cache, router=router, store=store,
                        max_pages=1)
    assert s2["cached"] == 1 and s2["asked"] == 0 and not gemini.answers and len(gemini.requests) == 1


def test_merge_asks_when_the_model_reads_another_name():
    facts = rules_facts()
    pc = plan_ai.candidates(pdfdoc.words(PLANS, 0), 0, pdfdoc.page_size(PLANS, 0))
    R, _ = _ids(pc)
    out = answer(views=[("L1", "MECHANICAL PLAN - LEVEL 1")], rooms=[(R["144"], "MECHANICAL", "L1", None, 0.9)])
    res = [{"page": 0, "cands": pc, "answer": {"output": out, "model": "hydrogen", "calls": []},
            "checked": plan_ai.checked({"output": out}, pc)}]
    assert plan_ai.merge(facts, res, NAME, lambda m: None)["rooms_renamed"] == 1
    f = next(f for f in facts if f["id"] == "room:144")
    assert f["data"]["name"] == "Mechanical" and f["data"]["rule_name"].upper() == "MECHANICAL ROOM"
    assert f["method"] == "llm" and f["conf"] <= 0.7 and f["ask"]["field"] == "name"
