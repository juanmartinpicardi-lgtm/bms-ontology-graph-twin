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
