"""The guided setup under realistic variation (scripts/stress_intake.py): another firm's titles, room numbers, heading
style, another vendor's submittal or BMS export, a scan, the whole drawing set.

The rule: every step either reads its main kind of fact or asks the person. A step that reads nothing and says nothing
is the failure a person never sees (docs/assessment-rules-vs-ai.md). Each scenario takes about 8 seconds.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("stress_intake", ROOT / "scripts/stress_intake.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


@pytest.fixture(scope="module")
def results():
    return {}


def _run(results, name):
    if name not in results:
        results[name] = S.run(name, S.SCENARIOS[name])
    return results[name]


@pytest.mark.parametrize("name", list(S.SCENARIOS))
def test_no_step_is_silent(results, name):
    r = _run(results, name)
    crashed = {k: v for k, v in r["asks"].items() if isinstance(v, str) and v.startswith("CRASH")}
    assert not crashed, crashed
    assert r["silent"] == [], f"{name}: {r['silent']} read nothing and asked nothing"


# Partial reads nothing reports. Empty since the partial-read checks (W0); a new one fails the test.
KNOWN_QUIET: set[str] = set()


def test_partial_reads_say_so(results):
    from projectmodel.intake.coverage import stress_state
    base = _run(results, "baseline")
    quiet = {n for n in S.SCENARIOS if n != "baseline" and stress_state(_run(results, n), base)[0] == "quiet"}
    assert quiet <= KNOWN_QUIET, f"new quiet partial reads: {quiet - KNOWN_QUIET}"


def test_variations_the_rules_now_read(results):
    base = _run(results, "baseline")["read"]
    assert _run(results, "plans: titles say 'FLR' not 'LEVEL'")["read"]["rooms"] == base["rooms"] == 80
    four = _run(results, "plans + submittal: 4-digit room numbers")
    assert four["read"]["rooms"] == 80
    assert four["asks"]["plans"] <= _run(results, "baseline")["asks"]["plans"] + 2  # 1205 is on L2: not a question
    assert _run(results, "bms: Niagara export columns")["read"]["devices linked"] == base["devices linked"]
    linked, total = map(int, _run(results, "bms: devices named by instance")["read"]["devices linked"].split("/"))
    assert linked >= 60, "devices named DEV3104 should join the riser by device instance"


def test_plan_variations_another_firm_draws(results):
    """W6: plans in Title Case and room numbers drawn above their names read as the baseline does (or close)."""
    base = _run(results, "baseline")["score"]
    for name in ("plans: room names and titles in Title Case", "plans: view titles in Title Case"):
        r = _run(results, name)["score"]
        assert r["Rooms found"] == base["Rooms found"] and r["Room names right"] == base["Room names right"], name
    above = _run(results, "plans: room number above its name")["score"]
    assert above["Rooms found"][0] >= 78 and above["Room names right"][0] >= 40
