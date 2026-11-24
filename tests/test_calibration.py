"""Calibration per job (calibration.py) and the eval harness (scoring/eval.py)."""
import json

import pytest

from projectmodel import calibration as cal


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("PM_CALIBRATION", "on")


def test_pav_pools_violators_into_a_non_decreasing_step():
    blocks = cal.pav([0.1, 0.5, 0.9, 1.0], [1, 0, 1, 1])
    assert blocks == [(0.1, 0.5, 0.5, 2.0), (0.9, 1.0, 1.0, 2.0)]  # 0.1 right, 0.5 wrong: pooled
    assert [b[2] for b in cal.pav([0.1, 0.5, 0.9, 1.0], [1, 0, 1, 0])] == [0.5]  # all one block


def test_curve_interpolates_between_knots_and_is_flat_outside():
    c = cal.Curve.fit([0.2, 0.2, 0.8, 0.8], [0, 0, 1, 1])
    assert c(0.0) == 0.0 and c(1.0) == 1.0
    assert c(0.5) == pytest.approx(0.5)


def test_a_stratum_needs_min_n_items_else_the_pooled_curve_answers():
    items = [{"raw": 1.0, "ok": False, "keys": ["Status"]}] * 40 + [{"raw": 1.0, "ok": True, "keys": ["Sensor"]}] * 10
    c = cal.fit("t", items, min_n=30)
    assert "Status" in c.curves and "Sensor" not in c.curves
    assert c.apply(1.0, ("Status",)) == 0.0
    assert c.apply(1.0, ("Sensor",)) == pytest.approx(10 / 50)  # pooled


def test_cross_validation_never_scores_an_item_with_a_curve_that_saw_it():
    # Every item of a group is right in group A and wrong in group B, at the same raw confidence: a curve fitted on
    # the other folds only can't know which, so the held-out value of a lone group comes from the other group.
    import hashlib

    fold = {g: int(hashlib.sha1(g.encode()).hexdigest(), 16) % 5 for g in "ABCDEFGH"}
    a, b = "A", next(g for g in "BCDEFGH" if fold[g] != fold["A"])
    items = [{"raw": 0.9, "ok": True, "group": a}] * 30 + [{"raw": 0.9, "ok": False, "group": b}] * 30
    held = cal.cross_validate("t", items, k=5)
    assert held[0] == 0.0 and held[-1] == 1.0


def test_save_bumps_the_version_only_when_the_curves_change(tmp_path, on):
    c = cal.fit("t", [{"raw": 0.5, "ok": True}] * 3)
    cal.save(c, {"sets": ["x"]}, tmp_path)
    assert cal.load("t", tmp_path).version == 1
    cal.save(cal.fit("t", [{"raw": 0.5, "ok": True}] * 3), {"sets": ["x"]}, tmp_path)
    assert cal.load("t", tmp_path).version == 1
    cal.save(cal.fit("t", [{"raw": 0.5, "ok": False}] * 3), {"sets": ["x"]}, tmp_path)
    assert cal.load("t", tmp_path).ref == "t@2"
    assert json.loads((tmp_path / "t.json").read_text())["sets"] == ["x"]


def test_off_means_raw(tmp_path, monkeypatch):
    cal.save(cal.fit("t", [{"raw": 0.5, "ok": False}] * 3), {}, tmp_path)
    monkeypatch.setenv("PM_CALIBRATION", "off")
    assert not cal.load("t", tmp_path) and cal.load("t", tmp_path).apply(0.5) == 0.5
    assert not cal.load("no_such_job", tmp_path)


def test_bands_and_the_bake_off_verdict():
    conf = [0.95] * 40 + [0.85] * 40
    ok = [True] * 38 + [False] * 2 + [True] * 34 + [False] * 6
    table = cal.band_table(conf, ok)
    assert cal.worst_gap(table) == 0.0 and cal.calibrated(table)
    v = cal.verdict(metric=80, rules_metric=60, table=table, usd_per_1000=0.4, budget=1.0)
    assert v["default_ok"] and v["says"] == "may be the default"
    v = cal.verdict(metric=50, rules_metric=60, table=table, usd_per_1000=2.0, budget=None)
    assert not v["default_ok"] and "beats rules alone" in v["says"] and "budget: unknown" in v["says"]
    off = cal.band_table([0.95] * 40, [False] * 40)
    assert not cal.verdict(metric=80, rules_metric=60, table=off, usd_per_1000=0.1, budget=1.0)["default_ok"]


def test_function_of_a_point_class():
    assert [cal.function_of(c) for c in ("Zone_Air_Temperature_Sensor", "Occupancy_Status", "Command", None,
                                          "Utility_Cost_Point")] == ["Sensor", "Status", "Command", "none", "other"]


def test_redundant_abbreviation_reading_is_unlikely():
    """"Building Static_SP": SP as static pressure only repeats "static"; it is the setpoint."""
    from projectmodel.knowledge_model import load_knowledge_model
    from projectmodel.mapper.classify import ClassMatcher

    g = ClassMatcher(load_knowledge_model(), "point").classify("Building Static_SP", "AHU-5")
    assert cal.function_of(g.cls) == "Setpoint"
    assert ClassMatcher(load_knowledge_model(), "point").classify("Duct SP").cls.endswith("Static_Pressure_Sensor")


def test_alpha_bands_are_within_5_points_on_held_out_folds():
    """The W5 done-when: every band of 30+ points within 5 points of its measured accuracy, held out."""
    from projectmodel.scoring import eval as ev

    r = ev.evaluate("mapper", log=lambda *_: None)
    for row in r["rows"]:
        assert row["raw_worst_gap"] > 30  # raw rule confidences are not probabilities
        assert row["calibrated_worst_gap"] <= cal.TOLERANCE, row["label"]
        assert sum(b["n"] for b in row["calibrated"]) == row["n"]


def test_the_mapper_writes_calibrated_confidences(on):
    from projectmodel.scoring import eval as ev

    stored = cal.load("mapper")
    assert stored, "knowledge_model/calibration/mapper.json is missing: run scripts/eval.py mapper --fit"
    items, _ = ev.mapper_items("alpha/names_paths")
    run = ev.mapper_run("alpha/names_paths")  # raw (calibration off inside)
    final = {i["id"]: (i["cls"], i["raw"], i["method"]) for i in items}
    out = cal.calibrate_points(final, run["guesses"], run["records"])
    for i in items:
        want = i["raw"] if i["fixed"] else stored.apply(i["raw"], tuple(i["keys"]))
        assert out[i["id"]][1] == want
    # and the pipeline uses the hook
    from projectmodel.db.store import Store
    from projectmodel.mapper.pipeline import Mapper

    store = Store(":memory:")
    Mapper(run["mapper"].km).run(run["records"], store, "alpha/names_paths")
    got = {n["id"]: n["confidence"] for n in store.nodes("alpha/names_paths", "point")}
    assert all(got[pid] == c for pid, (_, c, _) in out.items())


def test_point_ai_calibrates_the_model_then_caps_below_auto_accept(tmp_path, monkeypatch, on):
    from projectmodel.intake import point_ai
    from projectmodel.intake.state import AUTO_ACCEPT

    cal.save(cal.fit("point_class", [{"raw": 0.99, "ok": True, "keys": ["argon"]}] * 20
                     + [{"raw": 0.99, "ok": False, "keys": ["argon"]}] * 20), {}, tmp_path)
    monkeypatch.setattr(cal, "CAL_DIR", tmp_path)
    q = point_ai.Question("k", {}, ["Damper_Command"], answer={"class": "Damper_Command", "confidence": 0.99,
                                                                "model": "argon", "why": "x"})
    f = {"kind": "point", "method": "rule", "conf": 0.4, "data": {"class": "Sensor"}}
    assert point_ai._apply(f, q, cached=False) == "changed"
    assert f["data"]["ai"]["calibrated"] == 0.5 and f["conf"] == 0.5 < AUTO_ACCEPT
    q.answer["confidence"], f2 = 0.99, {"kind": "point", "method": "rule", "conf": 0.4, "data": {"class": "Sensor"}}
    monkeypatch.setattr(cal, "CAL_DIR", tmp_path / "none")  # no calibration: the model's number, capped
    point_ai._apply(f2, q, cached=False)
    assert f2["conf"] == point_ai.AI_CAP


def test_held_out_sets_are_refused():
    from projectmodel.scoring import eval as ev

    with pytest.raises(ValueError):
        ev.evaluate("intake", ["liberty_boe"])


def test_point_class_rows_are_skipped_without_models():
    from projectmodel.ai.calls import Router
    from projectmodel.scoring import eval as ev

    r = ev.evaluate("point_class", router=Router(), log=lambda *_: None)  # PM_AI=off in the test suite
    assert not r["rows"] and r["skipped"] and all(s["why"] for s in r["skipped"])
