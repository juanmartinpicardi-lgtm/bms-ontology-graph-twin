"""AI point classification in the guided setup (intake/point_ai.py): offline it changes nothing; online the model's
answer is a capped proposal with method=llm, the rules' guess kept, one call per distinct point, a short candidate
list from the knowledge model. Every model here is scripted or mocked: nothing leaves the machine."""
import copy
import json
import threading

import pytest

from projectmodel.ai import JobResult, ModelError, Router, Scripted, jobs
from projectmodel.ai.config import AIConfig
from projectmodel.db.store import Store
from projectmodel.intake import point_ai, steps
from projectmodel.intake.state import AUTO_ACCEPT, Intake
from projectmodel.intake.submittal import _matcher

READY = AIConfig(project="test-project")


def router(*answers):
    return Router(READY, providers={"claude": Scripted(list(answers))})


def point(device, short, desc, conf=0.75, io="AO"):
    ref = f"NAE/FC-1.{device}.{short}"
    return {"id": f"pt:{ref}", "kind": "point", "label": f"{device}.{short}",
            "data": {"ref": ref, "device": device, "short": short, "description": desc, "io": io, "units": "%",
                     "object": "", "class": "Damper_Command", "class_conf": 0.5, "typical": None},
            "src": {"file": "4_controls_submittal.pdf", "page": 3}, "method": "rule", "conf": conf,
            "step": "submittal", "ask": None}


def controller(device, equip):
    return {"id": f"ctrl:{device}", "kind": "controller", "label": device, "method": "parsed", "conf": 0.95,
            "data": {"device": device, "equip": equip}, "src": {}, "step": "submittal", "ask": None}


EQUIPMENT = [{"data": {"normal": f"VAVE{i:02d}", "class": "VAV"}} for i in range(1, 6)]


def facts_for(n_units=2):
    out = []
    for i in range(1, n_units + 1):
        dev = f"VAVE-{i:02d}"
        out += [controller(dev, f"VAVE{i:02d}"), point(dev, "DPR-O", "Damper Output")]
    return out


def answer(cls, conf=0.99, why="DPR-O is the damper position output"):
    return json.dumps({"class": cls, "confidence": conf, "why": why})


def test_offline_changes_nothing_and_opens_no_store(tmp_path, monkeypatch):
    monkeypatch.setattr(point_ai, "DB", tmp_path / "kg.sqlite")
    facts = facts_for()
    before = copy.deepcopy(facts)
    off = Router(AIConfig(project=None, enabled=False, why_off="PM_AI=off"))
    logs = []
    s = point_ai.refine(facts, EQUIPMENT, logs.append, project="intake:t", cache={}, router=off)
    assert facts == before
    assert s["off"] == "PM_AI=off" and s["asked"] == 0 and s["calls"] == 0
    assert not (tmp_path / "kg.sqlite").exists()
    assert any("off" in m for m in logs)


def test_offline_with_saved_answers_still_rules_only():
    facts = facts_for()
    before = copy.deepcopy(facts)
    cache = {}
    point_ai.refine(copy.deepcopy(facts), EQUIPMENT, lambda m: None, project="t", cache=cache,
                    router=router(answer("Damper_Position_Command")), store=Store(":memory:"))
    assert cache  # answered once
    off = Router(AIConfig(project=None, enabled=False, why_off="PM_AI=off"))
    point_ai.refine(facts, EQUIPMENT, lambda m: None, project="t", cache=cache, router=off)
    assert facts == before


def test_answer_is_a_capped_llm_proposal_with_the_rules_guess_kept():
    store = Store(":memory:")
    facts = facts_for(n_units=3)
    s = point_ai.refine(facts, EQUIPMENT, lambda m: None, project="intake:t", cache={},
                        router=router(answer("Damper_Position_Command", 0.99)), store=store)
    pts = [f for f in facts if f["kind"] == "point"]
    assert s["questions"] == 1 and s["asked"] == 1 and s["changed"] == 3  # one typical, asked once, on 3 units
    for f in pts:
        assert f["method"] == "llm"
        assert f["conf"] == point_ai.AI_CAP < AUTO_ACCEPT
        d = f["data"]
        assert d["class"] == "Damper_Position_Command"
        assert d["rule_class"] == "Damper_Command" and d["rule_conf"] == 0.75
        assert d["ai"]["why"].startswith("DPR-O") and d["ai"]["model"] == "haiku" and d["ai"]["calls"]
        assert "Damper_Position_Command" in d["ai"]["candidates"]
    rows = store.conn.execute("SELECT job, model, input, output, cost_usd, latency_s, ok FROM llm_calls").fetchall()
    assert len(rows) == 1 and rows[0]["job"] == "point_class" and rows[0]["ok"] == 1
    assert "DPR-O" in rows[0]["input"] and "Damper_Position_Command" in rows[0]["output"]
    assert rows[0]["cost_usd"] > 0 and rows[0]["latency_s"] >= 0
    # In the setup, the proposal waits for a person.
    it = Intake.__new__(Intake)
    it.s = {"decisions": {}}
    assert it._effective(pts[0])["status"] == "proposed"


def test_agreeing_answer_keeps_the_higher_confidence_below_auto_accept():
    facts = [point("VAVE-01", "DPR-O", "Damper Output", conf=0.88)]
    point_ai.refine(facts, [], lambda m: None, project="t", cache={},
                    router=router(answer("Damper_Command", 0.99)), store=Store(":memory:"))
    assert facts[0]["method"] == "llm" and facts[0]["conf"] == 0.88 < AUTO_ACCEPT


def test_no_fit_or_failure_keeps_the_rules_guess():
    facts = [point("VAVE-01", "DPR-O", "Damper Output"), point("VAVE-01", "X-1", "Mystery Thing", io="AV")]
    cache = {}
    r = Router(READY, providers={"claude": Scripted([json.dumps({"class": None, "confidence": 0.2, "why": "no"}),
                                                     ModelError("boom"), ModelError("boom"), ModelError("boom")])})
    s = point_ai.refine(facts, [], lambda m: None, project="t", cache=cache, router=r, store=Store(":memory:"))
    assert s["none"] == 1 and s["error"] == 1
    for f in facts:
        assert f["method"] == "rule" and f["conf"] == 0.75 and f["data"]["class"] == "Damper_Command"
        assert "ai" in f["data"]
    assert len(cache) == 1  # the failure is asked again next time, the null answer is not


def test_only_rule_points_below_auto_accept_are_asked(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "run_job", lambda *a, **k: calls.append(a) or pytest.fail("no call expected"))
    sure = point("VAVE-01", "ZN-T", "Zone Temperature", conf=AUTO_ACCEPT)
    term = dict(point("VAVE-01", "Q", "Something", conf=0.95))
    human = dict(point("VAVE-01", "R", "Other"), method="human")
    facts = [sure, term, human]
    before = copy.deepcopy(facts)
    s = point_ai.refine(facts, [], lambda m: None, project="t", cache={}, router=router(), store=Store(":memory:"))
    assert s["questions"] == 0 and facts == before and not calls


def test_batching_and_candidate_lists(monkeypatch, tmp_path):
    seen, threads = [], set()

    def fake_run_job(job_id, values, *, router, store, project, **_):
        threads.add(threading.get_ident())
        seen.append((job_id, values, project, store))
        out = {"class": values["candidate_list"][0], "confidence": 0.6, "why": "first candidate"}
        return JobResult(job_id, out, "haiku", attempts=[{"model": "haiku", "call": len(seen), "problem": None}],
                         cost_usd=0.001, latency_s=0.1)

    monkeypatch.setattr(jobs, "run_job", fake_run_job)
    facts = []
    for i in range(1, 6):  # 5 units x 2 typical points + 1 point of its own = 11 points, 3 questions... per class
        dev = f"VAVE-{i:02d}"
        facts += [controller(dev, f"VAVE{i:02d}"), point(dev, "DPR-O", "Damper Output"),
                  point(dev, "HTG-O", "Electric Heat Output (SCR)")]
    facts += [point("AHU-1", "ECON-O", "Economizer Damper")]  # no controller: equipment unknown
    for k in range(12):  # distinct points, enough to fill several batches
        facts.append(point("AHU-1", f"P{k}", f"Pump Status {k}", io="BI"))
    store = Store(tmp_path / "kg.sqlite")
    s = point_ai.refine(facts, EQUIPMENT, lambda m: None, project="intake:b", cache={}, router=router(),
                        store=store, batch=4)
    assert s["questions"] == 3 + 12 and len(seen) == 15 and s["calls"] == 15
    assert s["points"] == 23 and s["changed"] + s["agreed"] == 23
    assert len(threads) > 1  # asked in parallel
    km, words = _matcher().km, _matcher().class_words
    for job_id, values, project, st in seen:
        assert job_id == "point_class" and project == "intake:b"
        assert st is not store and st.path == store.path  # one connection per thread, same database
        cands = values["candidate_list"]
        assert 1 <= len(cands) <= point_ai.MAX_CANDIDATES < len(km.by_kind("point"))
        assert len(set(cands)) == len(cands) and all(c in words for c in cands)
        assert {"Sensor", "Command", "Setpoint", "Status"} <= set(cands)  # the model may correct the function
        lines = values["candidates"].splitlines()
        assert [ln.split(":")[0][2:] for ln in lines] == cands and all(ln.startswith("- ") for ln in lines)
    by_name = {v["name"]: v for _, v, _, _ in seen}
    damper = by_name["DPR-O · Damper Output · AO · %"]
    assert damper["equipment_class"] == "VAV" and damper["candidate_list"][0] == "Damper_Command"
    assert "Damper_Position_Command" in damper["candidate_list"]  # more specific than the rules' class
    assert by_name["ECON-O · Economizer Damper · AO · %"]["equipment_class"] == "(unknown)"


def test_saved_answers_are_not_asked_again(monkeypatch):
    cache = {}
    point_ai.refine(facts_for(), EQUIPMENT, lambda m: None, project="t", cache=cache,
                    router=router(answer("Damper_Position_Command")), store=Store(":memory:"))
    monkeypatch.setattr(jobs, "run_job", lambda *a, **k: pytest.fail("asked again"))
    facts = facts_for()
    s = point_ai.refine(facts, EQUIPMENT, lambda m: None, project="t", cache=cache, router=router(),
                        store=Store(":memory:"))
    assert s["cached"] == 1 and s["asked"] == 0
    assert all(f["method"] == "llm" and f["data"]["ai"]["cached"] for f in facts if f["kind"] == "point")


def test_guided_setup_shows_ai_proposals(monkeypatch, tmp_path):
    """The submittal step on Troop D with the job mocked: points below auto-accept carry the model's proposal."""
    from projectmodel.ai import calls

    if not steps.TEST_PACKAGE.exists():
        pytest.skip("test package missing: run scripts/build_troop_d.py")
    monkeypatch.setattr(point_ai, "DB", tmp_path / "kg.sqlite")
    asked = []

    def fake_run_job(job_id, values, **_):
        asked.append(values["name"])
        return JobResult(job_id, {"class": values["candidate_list"][0], "confidence": 0.97, "why": "test"}, "argon",
                         attempts=[{"model": "argon", "call": 1, "problem": None}], cost_usd=0.002, latency_s=0.5)

    monkeypatch.setattr(jobs, "run_job", fake_run_job)
    calls.set_default_router(router())
    try:
        it = Intake.create("ai setup", root=tmp_path / "intake")
        log = []
        for sid in ("plans", "schedules", "submittal"):
            s = steps.BY_ID[sid]
            it.add_file(sid, s.test_file, (steps.TEST_PACKAGE / s.test_file).read_bytes())
            steps.run(it, sid, log.append)
    finally:
        calls.set_default_router(None)
    pts = it.facts("submittal", kind="point")
    ai = [p for p in pts if p["method"] == "llm"]
    assert len(pts) == 847 and ai and len(asked) < len(ai) / 3  # typicals asked once
    assert all(p["conf"] < AUTO_ACCEPT and p["status"] == "proposed" and p["data"]["ai"]["model"] == "argon"
               for p in ai)
    assert any(m.startswith("AI point classification:") for m in it.log("submittal"))
    assert it.s["ai_point_class"]  # answers saved with the building
