import json
import shutil
import subprocess
from pathlib import Path

import pytest

from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.equipment_view import APP, equipment_payload, load_anchors
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.value_model import describe

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"


# specs per class family -----------------------------------------------------------------------------

@pytest.mark.parametrize("cls, role, part, expected", [
    ("Supply_Air_Temperature_Sensor", "supply_temp", None, {"kind": "analog", "unit": "°F", "driver": "supply_temp"}),
    ("Valve_Command", "cooling_valve", None, {"kind": "command", "unit": "%", "driver": "cooling_valve"}),
    ("Valve_Command", "reheat_valve", None, {"kind": "command", "unit": "%", "driver": "reheat_valve"}),
    ("Fan_Status", "return_fan_status", None, {"kind": "binary", "states": ["OFF", "RUN"], "fan": "return"}),
    ("Frequency_Sensor", "vfd_frequency", "return_fan.vfd", {"unit": "Hz", "driver": "fan_freq", "fan": "return"}),
    ("Frequency_Sensor", "vfd_frequency", "supply_fan.vfd", {"fan": "supply"}),
    ("Occupied_Cooling_Zone_Air_Temperature_Setpoint", "occ_cooling_sp", None,
     {"kind": "setpoint", "unit": "°F", "base": 74, "driver": "constant"}),
    ("Unoccupied_Heating_Zone_Air_Temperature_Setpoint", "unocc_heating_sp", None, {"base": 62}),
    ("Discharge_Air_Static_Pressure_Setpoint", "static_pressure_sp", None, {"unit": "inH₂O", "base": 1.5}),
    ("Discharge_Air_Flow_Sensor", "airflow", None, {"unit": "cfm", "driver": "airflow"}),
    ("Occupancy_Status", "occupancy", None, {"kind": "binary", "states": ["UNOCC", "OCC"]}),
    # no slot: class family, neutral random walk
    ("Outside_Air_Humidity_Sensor", None, None, {"unit": "%RH", "driver": "generic"}),
    ("Speed_Sensor", None, None, {"unit": "rpm", "driver": "generic"}),
    ("Fan_Status", None, None, {"kind": "binary", "fan": "exhaust"}),
    (None, None, None, {"unit": None, "driver": "generic", "generic": True}),
])
def test_spec_per_class_family(cls, role, part, expected):
    spec = describe(cls, role, part)
    assert {k: spec.get(k) for k in expected} == expected
    assert spec["unit_source"] == "inferred" and spec["from_class"] == cls
    lo, hi = spec["range"]
    assert lo <= spec["base"] <= hi


def test_describe_is_deterministic():
    assert describe("Damper_Command", "damper", "damper", "hot") == describe("Damper_Command", "damper", "damper", "hot")
    assert describe("Damper_Command", "damper", "damper", "hot")["deck"] == "hot"


# the payload carries a spec per point -------------------------------------------------------------------

@pytest.fixture(scope="module")
def payloads():
    km, s = load_knowledge_model(), Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), s, P)
    ids = ["eq:Airside AHU-2", "eq:Airside AHU-2/VAV 1-2-1", "eq:Airside AHU-4/DD 1-4-1"]
    return {i: equipment_payload(s, P, i, km, load_anchors()) for i in ids}


def test_every_point_has_a_sim_spec(payloads):
    for p in payloads.values():
        assert all(x["sim"]["unit_source"] == "inferred" for x in p["points"].values())
    ahu = {x["label"]: x["sim"] for x in payloads["eq:Airside AHU-2"]["points"].values()}
    assert ahu["Return Fan Power"]["fan"] == "return" and ahu["Discharge Fan Power-1"]["fan"] == "supply"
    dd = {x["label"]: x["sim"] for x in payloads["eq:Airside AHU-4/DD 1-4-1"]["points"].values()}
    assert dd["Htg Dmpr Cmnd 0-100"]["deck"] == "hot" and dd["Clg Dmpr Pos. %"]["deck"] == "cold"


# sim.js, run in node --------------------------------------------------------------------------------------

RUN = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const Sim = new Function(src + "; return Sim;")();
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const [id, p] of Object.entries(data)) {
  const a = Sim.create(p), b = Sim.create(p), c = Sim.create(p, { seed: "other" });
  const day = [9.5, 12, 15.25, 21].map(h => a.sample(h));
  out[id] = {
    same: [9.5, 12, 15.25, 21].every(h => JSON.stringify(a.sample(h).values) === JSON.stringify(b.sample(h).values)),
    other: JSON.stringify(a.sample(12).values) !== JSON.stringify(c.sample(12).values),
    run: day.map(s => s.ahu.run), texts: Object.values(day[1].values).map(v => v.text),
    vav: day.map(s => s.vav && Math.round(s.vav.reheat)),
  };
  const st = Sim.create(p, { scenario: "stuck" });
  out[id].stuck = st.scenarios.map(s => s.key).includes("stuck") ? [st.sample(9.5).vav.zone, st.sample(13).vav.zone, st.sample(13).vav.reheat] : null;
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_sim_is_deterministic_and_follows_the_schedule(payloads, tmp_path):
    script = tmp_path / "run.js"
    script.write_text(RUN)
    r = subprocess.run(["node", str(script), str(APP / "equipment3d" / "sim.js")], input=json.dumps(payloads),
                       capture_output=True, text=True, check=True)
    out = json.loads(r.stdout)
    for res in out.values():
        assert res["same"] and res["other"]                # same seed, same demo; another seed, another one
        assert res["run"] == [True, True, True, False]     # occupied 07-19
        assert "—" not in res["texts"] and "NaN" not in " ".join(res["texts"])
    ahu = out["eq:Airside AHU-2"]
    assert ahu["stuck"] is None                            # the stuck valve needs a reheat VAV
    z0, z1, valve = out["eq:Airside AHU-2/VAV 1-2-1"]["stuck"]
    assert valve == 100 and z1 > z0 + 2                    # valve held open, zone drifts up
