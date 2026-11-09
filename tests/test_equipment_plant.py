"""3D models for FCU, chiller, boiler and pump (spec-equipment-3d §4.1, E6): slots, variants, plant links, and the
simulated plant (staging, duty/standby) run in node. Alpha has no fan coils, so the FCU uses a small synthetic export
(tests/fixtures/fcu_demo) mapped by the same pipeline; Bravo is never used here."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.equipment_view import APP, equipment_payload, load_anchors, render_html
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper

ROOT = Path(__file__).resolve().parents[1]
P, F = "alpha/names_paths", "demo/fcu"
CHW = "eq:Waterside Chilled Water Plant"
IDS = [f"{CHW}/CH-1", f"{CHW}/CH-2", f"{CHW}/CH-3", f"{CHW}/CWP-1", f"{CHW}/CWP-2", f"{CHW}/PCHWP-1A",
       "eq:Waterside Hot Water Plant/B-1", "eq:Waterside Hot Water Plant/B-2",
       "eq:Waterside Hot Water Plant/Boiler Room HW Sys/HHWP-1"]


@pytest.fixture(scope="module")
def payloads():
    km, s = load_knowledge_model(), Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), s, P)
    Mapper(km).run(read_blind_export(ROOT / "tests/fixtures/fcu_demo/names_paths.csv"), s, F)
    out = {i: equipment_payload(s, P, i, km, load_anchors()) for i in IDS}
    out.update({i: equipment_payload(s, F, i, km, load_anchors()) for i in ("eq:Floor 3/FCU-1", "eq:Floor 3/FCU-2")})
    return out


def labels(p, role):
    return sorted(p["points"][i]["label"] for i in next(s["points"] for s in p["slots"] if s["role"] == role))


def test_chiller_slots_and_variant(payloads):
    ch2 = payloads[f"{CHW}/CH-2"]
    assert ch2["variant"] == {"water_cooled": True, "air_cooled": False}
    assert labels(ch2, "cw_entering_temp") == ["Cond Water Entering Temp"]
    # isolation valves go to their own shell by the name word, not to whichever valve slot comes first
    assert labels(ch2, "evap_iso_valve") == ["CH-2 Evap ISO Valve", "CH-2 Evap ISO Valve OPEN"]
    assert labels(ch2, "cond_iso_valve") == ["CH-2 Cond ISO Valve", "CH-2 Cond ISO Valve OPEN"]
    assert ch2["points"][ch2["slots"][0]["points"][0]]["part"] == "chw_leaving_pipe"


def test_pump_variant_from_its_name_or_system(payloads):
    assert payloads[f"{CHW}/CWP-1"]["variant"] == {"vfd": True, "medium": "condenser_water"}
    assert payloads[f"{CHW}/PCHWP-1A"]["variant"]["medium"] == "chilled_water"
    assert payloads["eq:Waterside Hot Water Plant/Boiler Room HW Sys/HHWP-1"]["variant"]["medium"] == "hot_water"
    cwp = payloads[f"{CHW}/CWP-1"]
    assert labels(cwp, "iso_valve") == ["CWP-1 ISO Valve", "CWP-1 ISO Valve OPEN"]
    assert cwp["points"][next(s["points"] for s in cwp["slots"] if s["role"] == "speed")[0]]["sim"]["unit"] == "Hz"


def test_boiler_without_leaving_temp_is_a_ghost(payloads):
    b1 = payloads["eq:Waterside Hot Water Plant/B-1"]
    slot = next(s for s in b1["slots"] if s["role"] == "hw_leaving_temp")
    assert slot["required"] and slot["points"] == [] and b1["equipment"]["slot_fill"] == 0
    assert [b1["points"][i]["label"] for i in b1["unplaced"]] == ["B-1 Fire Rate"]  # no class: a review item


def test_plant_links_to_its_plant_and_neighbours(payloads):
    rel = payloads[f"{CHW}/CH-1"]["relations"]
    assert rel["part_of"]["label"] == "Waterside Chilled Water Plant"
    assert [r["label"] for r in rel["with"]] == ["CH-2", "CH-3", "CWP-1", "CWP-2", "PCHWP-1A", "PCHWP-1B"]
    assert [r["label"] for r in payloads["eq:Waterside Hot Water Plant/Boiler Room HW Sys/HHWP-1"]["relations"]["with"]] == ["HHWP-2"]


def test_fcu_two_and_four_pipe(payloads):
    four, two = payloads["eq:Floor 3/FCU-1"], payloads["eq:Floor 3/FCU-2"]
    assert four["variant"] == {"four_pipe": True, "two_pipe": False, "cooling_coil": True, "heating_coil": True}
    assert labels(four, "heating_valve") == ["FCU-1 Htg Valve Cmd"]
    assert labels(four, "cooling_valve") == ["FCU-1 Clg Valve Cmd"]
    assert two["variant"] == {"four_pipe": False, "two_pipe": True, "cooling_coil": True, "heating_coil": False}
    assert four["unplaced"] == [] and four["equipment"]["slot_fill"] == 1.0


def test_pages_render_for_every_type(payloads):
    for p in payloads.values():
        html = render_html(p)
        assert f'"template":"{p["equipment"]["template"]}"' in html


RUN = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const Sim = new Function(src + "; return Sim;")();
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const [id, p] of Object.entries(data)) {
  const a = Sim.create(p), b = Sim.create(p), hot = Sim.create(p, { scenario: "hot" });
  const at = h => a.sample(h).plant || a.sample(h).fcu;
  out[id] = {
    same: JSON.stringify(a.sample(11).values) === JSON.stringify(b.sample(11).values),
    run: [9.5, 15, 23].map(h => at(h).run), hot: hot.sample(15).plant?.run ?? null,
    texts: [9.5, 23].flatMap(h => Object.values(a.sample(h).values).map(v => v.text)),
    values: Object.fromEntries(Object.entries(a.sample(9.5).values).map(([k, v]) => [p.points[k].label, v.text])),
  };
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_plant_sim_stages_units(payloads, tmp_path):
    script = tmp_path / "run.js"
    script.write_text(RUN)
    r = subprocess.run(["node", str(script), str(APP / "equipment3d" / "sim.js")], input=json.dumps(payloads),
                       capture_output=True, text=True, check=True)
    out = json.loads(r.stdout)
    for res in out.values():
        assert res["same"]
        assert res["run"][2] is False                       # everything off at night
        assert not any(t in ("—", "NaN") or "NaN" in t for t in res["texts"])
    assert out[f"{CHW}/CH-1"]["run"][:2] == [True, True]   # lead chiller
    assert out[f"{CHW}/CH-3"]["run"][0] is False             # third stage only on a hot afternoon
    assert out[f"{CHW}/CH-3"]["hot"] is True
    assert out[f"{CHW}/CWP-1"]["run"][0] and not out[f"{CHW}/CWP-2"]["run"][0]  # duty / standby
    ch2 = out[f"{CHW}/CH-2"]["values"]
    assert ch2["CH-2 Evap ISO Valve OPEN"] in ("OPEN", "CLOSED")
    t = float(out[f"{CHW}/CH-1"]["values"]["Chilled Water Leaving Temp"].split()[0])
    assert 42 < t < 47
