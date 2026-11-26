"""Spot checks: a fixed share of the facts the readers were sure of comes back as a blind question, and the answers
measure the readers."""
import pytest

from projectmodel.intake import spotcheck, twin
from projectmodel.intake.state import Intake


def _f(fid, kind, data, conf=0.95, ask=None, step="schedules"):
    return {"id": fid, "kind": kind, "label": fid, "data": data, "src": {"file": "x.pdf", "page": 0},
            "method": "rule", "conf": conf, "step": step, "ask": ask}


def _building(tmp_path, n_rooms=40):
    it = Intake.create("Spot test", root=tmp_path)
    rooms = [_f(f"room:{100 + i}", "room", {"number": str(100 + i), "name": f"Office {i}", "floor": "L1"},
                step="plans") for i in range(n_rooms)]
    rooms.append(_f("room:999", "room", {"number": "999", "name": "", "floor": "L1"}, step="plans",
                    ask={"q": "Is it a room?", "field": "name", "options": []}))  # the reader asked: not a spot check
    rooms.append(_f("room:998", "room", {"number": "998", "name": "Store", "floor": "L1"}, conf=0.6, step="plans"))
    it.set_step("plans", rooms, [])
    eq = [_f(f"equip:VAV{i}", "equipment", {"tag": f"VAV{i:02d}", "normal": f"VAV{i}", "class": "VAV"})
          for i in range(1, 11)] + [_f("equip:AHU1", "equipment", {"tag": "AHU01", "normal": "AHU1", "class": "AHU"})]
    rel = [_f(f"rel:AHU1:feeds:VAV{i}", "relation", {"src": "AHU1", "rel": "feeds", "dst": f"VAV{i}",
                                                       "medium": "air"}) for i in range(1, 11)]
    it.set_step("schedules", eq + rel, [])
    return it


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("PM_SPOT_CHECK", "0.05")
    monkeypatch.setenv("PM_SPOT_MAX", "5")


def test_off_by_default_in_tests(tmp_path):
    it = _building(tmp_path)
    assert it.spot_asks() == {}
    assert len(it.open_questions()) == 1


def test_picks_a_share_of_the_sure_facts_per_kind(tmp_path, on):
    it = _building(tmp_path)
    asks = it.spot_asks()
    kinds = {fid.split(":")[0] for fid in asks}
    assert kinds == {"room", "equip", "rel"}
    assert sum(1 for i in asks if i.startswith("room:")) == 2  # 5% of 40
    assert sum(1 for i in asks if i.startswith("equip:")) == 1  # at least one
    assert "room:999" not in asks and "room:998" not in asks  # asked already / not sure: never spot-checked
    assert asks == Intake(it.slug, tmp_path).spot_asks()  # stable: the same building picks the same facts


def test_a_spot_check_is_blind(tmp_path, on):
    it = _building(tmp_path)
    fid = next(i for i in it.spot_asks() if i.startswith("rel:"))
    f = it.fact(fid)
    assert f["status"] == "proposed" and f["ask"]["spot"] and f in it.open_questions()
    assert "AHU" not in f["label"]  # the reader's answer is not in the label
    assert f not in it.open_questions(spot=False)
    q = twin._question(f)
    assert q["proposed"] is None and q["conf"] is None and q["spot"]
    assert any(o["value"] == "AHU1" for o in f["ask"]["options"])  # the right answer is offered, unmarked


def test_answers_confirm_or_fix_and_are_scored(tmp_path, on):
    it = _building(tmp_path)
    asks = it.spot_asks()
    room_a, room_b = [i for i in asks if i.startswith("room:")]
    rel = next(i for i in asks if i.startswith("rel:"))
    eq = next(i for i in asks if i.startswith("equip:"))
    expected = asks[room_a]["expected"]
    assert it.answer_spot(room_a, "  " + expected.upper() + " ") is True  # case and spaces don't count
    assert it.answer_spot(room_b, "Kitchen") is False
    assert it.answer_spot(rel, None, "rejected") is None
    it.decide(eq, "confirmed", spot={"skipped": True})

    a, b = it.fact(room_a), it.fact(room_b)
    assert a["status"] == "confirmed" and a["method"] == "human" and a["data"]["name"] == expected
    assert b["status"] == "confirmed" and b["data"]["name"] == "Kitchen" and b["method"] == "human"
    assert it.fact(rel)["status"] == "rejected"
    e = it.fact(eq)
    assert e["status"] == "confirmed" and e["method"] == "rule"  # "can't tell": stays the reader's
    assert it.spot_asks() == asks  # answering never draws new checks
    assert it.open_questions() == [it.fact("room:999")]

    rep = spotcheck.report(it)
    assert rep["total"] == {"asked": 4, "checked": 3, "right": 1, "wrong": 2, "waiting": 0, "skipped": 1}
    assert rep["right_share"] == pytest.approx(1 / 3)


def test_off_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_SPOT_CHECK", "0")
    assert _building(tmp_path).spot_asks() == {}


def test_every_kind_has_a_question_whose_answer_is_offered(monkeypatch):
    monkeypatch.setenv("PM_SPOT_CHECK", "1")  # every eligible fact
    raw = [
        _f("equip:AHU1", "equipment", {"tag": "AHU01", "normal": "AHU1", "class": "AHU"}),
        _f("equip:VAV1", "equipment", {"tag": "VAV01", "normal": "VAV1", "class": "VAV"}),
        _f("ctrl:AHU-1", "controller", {"device": "AHU-1", "trunk": "FC-1", "trunk_name": "Plant", "equip": "AHU1"}),
        _f("ctrl:VAV-1", "controller", {"device": "VAV-1", "trunk": "FC-2", "trunk_name": "", "equip": "VAV1"}),
        _f("pt:a", "point", {"device": "AHU-1", "short": "SF-S", "description": "Supply fan status", "io": "BI",
                             "class": "Fan_Status"}),
        _f("pt:b", "point", {"device": "AHU-1", "short": "SAT", "description": "", "io": "AI",
                             "class": "Supply_Air_Temperature_Sensor"}),
        _f("alias:AHU-1", "alias", {"device": "AHU-1", "equip": "AHU1"}),
        _f("obj:a", "bms_object", {"ref": "N/FC-1.AHU-1.SF-S", "device": "AHU-1", "point": "pt:a",
                                   "object_type": "binary-input"}),
    ]
    asks = spotcheck.pick("x", raw, 0.9)
    assert {a.split(":")[0] for a in asks} == {"equip", "ctrl", "pt", "alias", "obj"}
    for fid, a in asks.items():
        assert any(o["value"] == a["expected"] for o in a["options"]), fid
    # a point's choices are the classes of points with the same I/O type
    assert [o["value"] for o in asks["pt:a"]["options"]] == ["Fan_Status"]
