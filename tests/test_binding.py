"""W7: point binding (intake/binding.py) under another integrator's naming, scored by scoring/binding.py."""
import hashlib
import json

import pytest

from projectmodel.scoring import binding as B

# The scenarios and their keys were committed before any binder ran on them (W7). A change here means a scenario was
# changed: never after seeing results.
DIGESTS = {
    "baseline": "7149a87c010d4bbc",
    "names": "3b8a86aa4e7058e3",
    "folders": "855ecd5d8355b0d6",
    "instances": "ddb22d5a8c4510a6",
    "missing": "1c13b5bfdd089820",
    "integrator": "4ecc0a24385d7725",
    "integrator_names_only": "31b75538da82803c",  # added after the first rules-only results, before any run on it
}


@pytest.mark.parametrize("scenario", list(B.SCENARIOS))
def test_scenario_is_frozen(scenario):
    digest = hashlib.sha1(json.dumps(B.key(scenario), sort_keys=True).encode()
                          + B.variant_csv(scenario)).hexdigest()[:16]
    assert digest == DIGESTS[scenario]


@pytest.mark.parametrize("scenario", list(B.SCENARIOS))
def test_keys_are_exact(scenario):
    """Every key pair names a row of the variant export that came from the same original row."""
    rows = {r["Item Reference"]: r for r in B.variant_rows(scenario)}
    assert len(rows) == len(B.variant_rows(scenario)), "references must stay unique"
    k = B.key(scenario)
    assert set(k) <= set(B.key_points())
    for sub, bms in k.items():
        if bms is not None:
            assert rows[bms][B.ORIG] == sub
    # every BMS row whose original point the submittal keeps is in the key
    kept = {r[B.ORIG] for r in rows.values()} - B.dropped_submittal(scenario)
    assert {v for v in k.values() if v} == {r["Item Reference"] for r in rows.values() if r[B.ORIG] in kept}


def test_variations_change_what_they_say():
    base = {r[B.ORIG]: r for r in B.variant_rows("baseline")}
    names = {r[B.ORIG]: r for r in B.variant_rows("names")}
    ref = "TROOPD-NAE01/FC-4.VAV-19.UNOCC-CLG-SP"
    assert names[ref]["Name"] == "COOL_UNOCC_STPT" and names[ref]["Description"] == "Unocc Clg SP"
    folders = {r[B.ORIG]: r for r in B.variant_rows("folders")}
    assert folders[ref]["Item Reference"] == "TROOPD-NAE01/FC-4.VAV_3_19.UNOCC-CLG-SP"
    inst = {r[B.ORIG]: r for r in B.variant_rows("instances")}
    assert inst[ref]["Device Instance"] != base[ref]["Device Instance"] and ".DEV1" in inst[ref]["Item Reference"]
    assert len(B.key("missing")) < len(B.key("baseline"))
    assert sum(v is None for v in B.key("missing").values()) > 30


# the binder ---------------------------------------------------------------------------------------------------------

from projectmodel.ai import Router, Scripted, jobs  # noqa: E402
from projectmodel.ai.config import AIConfig  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.intake import binding as BB  # noqa: E402

READY = AIConfig(project="test-project")


def test_devices_match_by_name_tag_instance_and_address():
    sub = {"AHU-1": {"instance": 3104, "trunk": "FC-1", "address": 4},
           "VAVE-07": {"instance": 3201, "trunk": "FC-2", "address": 7},
           "CH-1A": {"instance": 3106, "trunk": "FC-1", "address": 6},
           "CWP-1": {"instance": 3108, "trunk": "FC-1", "address": 8},
           "MS-1": {"instance": 3140, "trunk": "FC-1", "address": 40},
           "MS-2": {"instance": 3140, "trunk": "FC-1", "address": 40}}
    bms = {"AHU-1": {"instance": 9}, "VAVE_1_07": {}, "CHLR_1A": {"instance": 3106},
           "DEV100": {"instance": 100, "trunk": "FC-1", "address": 8},
           "DEV200-1": {"instance": 200, "trunk": "FC-1", "address": 40},
           "DEV200-2": {"instance": 200, "trunk": "FC-1", "address": 40}}
    m = BB.match_devices(sub, bms)
    assert m["AHU-1"] == ("AHU-1", "same name")
    assert m["VAVE_1_07"] == ("VAVE-07", "same tag")
    assert m["CHLR_1A"] == ("CH-1A", "device instance")
    assert m["DEV100"] == ("CWP-1", "trunk and address")
    assert m["DEV200-1"][0] == "MS-1" and m["DEV200-2"][0] == "MS-2"  # a gateway's units, paired by number


def _pt(dev, short, desc, io):
    return BB.Point(f"pt:NAE/FC-1.{dev}.{short}", f"NAE/FC-1.{dev}.{short}", dev, short, desc, io)


def _obj(dev, name, desc, typ):
    return BB.Obj(f"NAE/FC-1.{dev}_X.{name}", f"{dev}_X", name, desc, typ)


def _box(dev, with_desc=True):
    pts = [_pt(dev, "ZN-T", "Zone Temperature", "AI"), _pt(dev, "DPR-O", "Damper Output", "AO"),
           _pt(dev, "OCC-CLG-SP", "Occupied Cooling Setpoint", "AV"),
           _pt(dev, "UNOCC-CLG-SP", "Unoccupied Cooling Setpoint", "AV")]
    objs = [_obj(dev, "SPACE_TEMP", "Space Temp" if with_desc else "", "analog-input"),
            _obj(dev, "DMPR_OUT", "Dmpr Out" if with_desc else "", "analog-output"),
            _obj(dev, "COOL_OCC_STPT", "", "analog-value"), _obj(dev, "COOL_UNOCC_STPT", "", "analog-value")]
    return pts, objs


def test_rules_bind_what_the_words_settle_and_leave_the_rest():
    pts, objs = _box("VAV-1")
    bound, left = BB.bind_rules(pts, objs, {"VAV-1_X": ("VAV-1", "same tag")}, {})
    got = {p: b.obj.rsplit(".", 1)[1] for p, b in bound.items()}
    assert got["pt:NAE/FC-1.VAV-1.ZN-T"] == "SPACE_TEMP" and got["pt:NAE/FC-1.VAV-1.DPR-O"] == "DMPR_OUT"
    assert all(b.rule == "words" for b in bound.values())
    for p, cands in left.items():  # what the rules leave, with the device's free objects as candidates
        assert {c.name for c in cands} <= {"COOL_OCC_STPT", "COOL_UNOCC_STPT"}


RIGHT = {"ZN-T": "INPUT_7", "DA-T": "INPUT_9"}  # names no rule can read: only the model (here scripted) can say


def _opaque(dev):
    return ([_pt(dev, "ZN-T", "Zone Temperature", "AI"), _pt(dev, "DA-T", "Discharge Air Temperature", "AI")],
            [_obj(dev, "INPUT_7", "", "analog-input"), _obj(dev, "INPUT_9", "", "analog-input")])


def test_the_model_picks_an_id_once_per_typical_and_stays_a_proposal():
    pts, objs = [], []
    devices = {}
    for dev in ("VAV-1", "VAV-2"):
        p, o = _opaque(dev)
        pts += p
        objs += o
        devices[f"{dev}_X"] = (dev, "same tag")
    _, left = BB.bind_rules(pts, objs, devices, {})
    assert len(left) == 4
    qs = BB.questions(pts, left, devices, {}, "point_bind@1")
    assert len(qs) == 2, "typicals are asked once"
    answers = []
    for q in qs:  # pick the candidate whose name is the right one, as a model would
        i = [c.name for c in q.candidates[0]].index(RIGHT[q.points[0].short])
        answers.append(json.dumps({"pick": f"B{i + 1}", "confidence": 0.97, "why": "same point"}))
    scripted = Scripted(answers)
    router = Router(READY, providers={"claude": scripted})
    ai = BB.AI(router=router, store=Store(":memory:"), cache={}, batch=1)
    bound, summary = BB.bind(pts, objs, devices, {}, {}, ai=ai)
    assert len(scripted.requests) == 2 and summary["model_bound"] == 4
    assert all(b.obj.rsplit(".", 1)[1] == RIGHT[p.rsplit(".", 1)[1]] for p, b in bound.items())
    assert all(b.method == "llm" and b.conf <= BB.AI_CAP for b in bound.values()), \
        "no calibration yet: below auto-accept"


def test_the_check_refuses_an_id_it_was_not_given():
    values = {"candidate_list": ["B1", "B2"]}
    assert jobs.check_output("point_bind", {"pick": "B7", "confidence": 0.9, "why": ""}, values)
    assert jobs.check_output("point_bind", {"pick": None, "confidence": 0.9, "why": ""}, values) is None
    assert jobs.check_output("point_bind", {"pick": "B2", "confidence": 0.9, "why": ""}, values) is None


def test_no_model_call_when_ai_is_off():
    pts, objs = _opaque("VAV-1")
    off = Router(AIConfig(project=None, enabled=False, why_off="PM_AI=off"))
    bound, summary = BB.bind(pts, objs, {"VAV-1_X": ("VAV-1", "same tag")}, {}, {}, ai=BB.AI(router=off))
    assert summary["off"] == "PM_AI=off" and not bound and summary["left"] == 2


# Troop D ------------------------------------------------------------------------------------------------------------

def test_rules_alone_on_the_scenarios():
    """The rules' floor on every scenario (PM_AI=off): exact where names line up, precise everywhere."""
    for s in B.SCENARIOS:
        sc = B.score(s, B.pairs(B.run(s)["facts"]))
        assert sc["precision_pct"] >= 99.5, (s, sc)
        assert sc["recall_pct"] >= (98.5 if s != "integrator_names_only" else 80), (s, sc)
    assert B.score("baseline", B.pairs(B.run("baseline")["facts"]))["f1"] == 100.0


def test_riser_places_the_orphan_points():
    """W7: CHW-PLANT becomes the chilled water system (chillers and CHW pumps its parts), EF-LAB-1/2 units of their
    own: every Troop D point sits on equipment."""
    from projectmodel.intake import publish

    store = Store(":memory:")
    proj = publish.publish(B.base_intake(), store)
    pts = {r["id"] for r in store.nodes(proj, "point")}
    on = {r["dst"] for r in store.edges(proj) if r["rel"] == "hasPoint"}
    assert pts and pts <= on
    units = {r["id"]: r for r in store.nodes(proj, "equipment")}
    assert units["unit:CHWPLANT"]["class"] == "Chilled_Water_System"
    assert units["unit:EFLAB1"]["class"] == units["unit:EFLAB2"]["class"] == "Exhaust_Fan"
    parts = {r["dst"] for r in store.edges(proj) if r["rel"] == "hasPart" and r["src"] == "unit:CHWPLANT"}
    assert parts == {"unit:CH1A", "unit:CH1B", "unit:CWP1", "unit:CWP2"}
