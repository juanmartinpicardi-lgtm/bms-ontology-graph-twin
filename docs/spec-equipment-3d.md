# Spec – 3D equipment viewer v0.1

Status: draft, 2026-11-08. Builds on Phase 0 (Tasks 1–8) and the 3D graph viewer. Vocabulary as in `CLAUDE.md` §2.

## 1. What this is

Click a piece of equipment (in the tree, the 3D graph, or a picker) and see **a 3D model of that equipment with
its points placed where they physically sit**: the supply air temperature sensor in the duct after the fan, the
cooling valve on the coil pipe, the damper in the VAV inlet. Each point shows its name, class, confidence and a
**simulated live value** that moves (fan spins at its speed, valve actuator follows its command, airflow particles
speed up when the damper opens).

It does two jobs:

1. **Demo:** makes the knowledge graph tangible to people who are not BMS experts.
2. **Review aid:** a missing required sensor shows as a ghost part; points the mapper couldn't place on the
   model are listed beside it. An oddly built AHU is a hint the mapping is wrong.

Values are **simulated** for this phase; the public datasets have no readings (Haystack Alpha marks points
`cur`/`his` but ships no values). Real values arrive with the Niagara adapter, behind the same interface (§6).

## 2. Non-goals

- Real live values, trending, alarms, writing commands. Read-only, one way (brief §8).
- Photo-realistic or vendor-specific models. One clean, generic, parametric model per equipment type.
- Imported 3D assets (glTF/FBX). Everything is drawn in code: no licences, no binary files, easy to vary.
- Storing values in the knowledge graph. Values are **digital twin state** (later phase), never graph facts.
- LLM calls at runtime.

## 3. The bridge: template slots → anchors

The equipment **templates** in `knowledge_model/templates/*.yaml` already list each type's point slots
(`role`, `classes`, `medium`, `required`). The mapper already knows each point's class. So:

```
point class ──(template slot whose classes include it)──▶ slot role ──(anchor map)──▶ place on the 3D model
```

### 3.1 Slot assignment (Python, `src/projectmodel/equipment_view.py`)

`assign_slots(template, points) -> {role: [point ids]}, unplaced: [point ids]`

- A point goes to the **first** slot (template order) whose `classes` contain its class; ties are rare and
  deterministic.
- A slot may hold several points (e.g. a damper command and a damper position). The anchor shows a stack.
- Equipment without a template (e.g. `SF VFD`, `Return_Fan`) is not drawn on its own; see §3.3.
- Rejected points and rejected `hasPoint` links are left out, as in the tree.

### 3.2 Anchor map (`knowledge_model/templates/anchors.yaml`)

The anchor map says **where on the model each slot role sits**. It is per equipment type, not per project, so it
belongs with the templates:

```yaml
ahu:
  supply_temp:        {part: supply_duct, at: 0.3, label_side: up}
  return_temp:        {part: return_duct, at: 0.5}
  mixed_temp:         {part: mixing_box,  at: 0.8}
  outside_temp:       {part: outside_air_inlet, at: 0.2}
  cooling_valve:      {part: cooling_coil.valve}
  heating_valve:      {part: heating_coil.valve}
  economizer_damper:  {part: mixing_box.oa_damper}
  supply_fan_cmd:     {part: supply_fan}
  supply_fan_speed:   {part: supply_fan.vfd}
  supply_fan_status:  {part: supply_fan}
  static_pressure:    {part: supply_duct, at: 0.8}
  ...
vav: ...
```

`part` names refer to named objects the geometry code creates; `at` is 0–1 along a duct or pipe.
`scripts/validate_km.py` checks that **every slot role in every template has an anchor** and every anchor names
a real role. Adding a slot to a template without an anchor fails validation.

### 3.3 Sub-equipment

AHU-2 has parts `SF VFD` and `RF VFD` (`hasPart`). Their points are shown on the parent's model:
`Supply_Fan`/`SF` sub-equipment points attach to `supply_fan`, `Return_Fan`/`RF` to `return_fan`. The mapping is a
small table in `anchors.yaml` (`sub_equipment: {Supply_Fan: supply_fan, Return_Fan: return_fan, ...}`).
Unknown sub-equipment points go to the unplaced list.

## 4. Geometry: parametric models per type

### 4.1 Types and variants (v0.1)

| Type | Built from | Variants chosen from the slots found |
|---|---|---|
| **AHU** | casing, mixing box (OA/RA dampers), filter, cooling coil, heating coil, supply fan, return fan, ducts | no heating valve → no heating coil; no economizer damper → no mixing box; return fan only if return-fan points or sub-equipment exist |
| **VAV** | inlet duct, damper, flow sensor cross, box, optional reheat coil, optional fan, discharge duct, zone sensor on a wall stub | reheat if `reheat_valve`; fan-powered if `fan_cmd` or name says FPB; dual-duct if name says DD (two inlets) |
| FCU | casing, fan, coil(s), filter | 2- or 4-pipe from valves found |
| Chiller | shell-and-tube evaporator + condenser, compressor, pipe stubs | water-cooled vs air-cooled from condenser points |
| Boiler | casing, burner, flue, pipe stubs | — |
| Pump | motor, volute, pipe stubs, VFD box | VFD if speed points |

**v0.1 builds AHU and VAV** (Alpha's mapped graph has 4 AHUs and 138 VAVs). FCU, chiller, boiler and pump follow the same
pattern in v0.2.

### 4.2 Code

```
src/projectmodel/app/equipment3d.html        page shell: layout, panels, theme tokens (same tokens as graph3d.html)
src/projectmodel/app/equipment3d/
  core.js        scene, camera, lights, orbit controls, label pins, theme, animation loop
  parts.js       shared parts: duct(len, w, h), pipe(path, medium), coil(), damper(), valve(), fan(), vfd(), sensor()
  ahu.js         build(spec) -> {group, parts: {name: Object3D}}
  vav.js         build(spec) -> ...
  sim.js         simulated values (§6)
```

- **three.js**, pinned exact version from cdn.jsdelivr.net (e.g. `three@0.170.0`, ES modules via an import map),
  plus `OrbitControls` and `CSS2DRenderer` for labels from the same version.
- The Python side inlines the JS modules into one HTML string (as `render_html` does today) so Streamlit's
  `st.iframe` and a standalone export both work with no server.
- **Look:** clean product-render style. Brushed-metal casing with a cut-away front panel so the inside shows;
  ducts in light grey; pipes coloured by medium (chilled water blue, hot water red, condenser water green,
  matching the graph viewer's palette); soft studio lighting; ground shadow; background = the app's theme
  `--bg` so it sits seamlessly in light and dark mode.
- **Motion:** fan blades spin at `speed%`; damper blades and valve stems rotate to their command %; airflow
  particles move along ducts at a rate tied to fan speed and damper position; water particles in pipes when the
  valve is open. A pause button stops all motion.
- **Missing required slot:** the part is drawn as a translucent **ghost** with a "expected, not found" pin.

### 4.3 Labels and interaction

- One **pin** per anchor: a small dot on the part, a leader line, and a label card with short name, live value +
  unit, and a status dot (proposed / confirmed / rejected colours). Several points at one anchor stack in one card.
- Label density: names only when zoomed out; value + class when close or hovered.
- Click a pin → **side panel**: point name, class, slot role, confidence, method, source file + row, notes
  (from the tribal-knowledge spec, if built), and a link "Review this point" (opens the review app filtered to it).
- **Unplaced list** under the panel: points on this equipment with no slot, with class and confidence.
- Header: equipment name, class, template, fit (`slot_fill`), fed by / feeds (clickable → opens that equipment).
- Camera presets: Front, Top, Cut-away; "Fit" button. Mouse: rotate, zoom, pan, as in the graph viewer.

## 5. Payload (`equipment_payload(store, project, equip_id, km)`)

```json
{
  "project": "alpha/names_paths",
  "equipment": {"id": "eq:Airside AHU-2", "label": "Airside AHU-2", "cls": "AHU", "template": "ahu",
                "slot_fill": 1.0, "prov": {...}},
  "variant": {"heating_coil": true, "mixing_box": true, "return_fan": true},
  "slots": [{"role": "supply_temp", "required": true, "medium": null, "anchor": {"part": "supply_duct", "at": 0.3},
             "points": ["pt-00123"]}],
  "points": {"pt-00123": {"label": "SAT", "cls": "Supply_Air_Temperature_Sensor", "role": "supply_temp",
                          "confidence": 0.92, "status": "proposed", "prov": {...},
                          "sim": {"kind": "analog", "unit": "°F", "base": 55, "range": [50, 65], "driver": "cooling"}}},
  "unplaced": ["pt-00456"],
  "relations": {"fed_by": [...], "feeds": [...]},
  "value_source": "simulated"
}
```

`variant` is computed in Python from the slots found (so it is testable); the JS only draws what it is told.

## 6. Values

### 6.1 Interface

Values come through one interface so the simulator can be swapped for real data later:

```
ValueSource.describe(point) -> sim/value spec      (Python, at payload time)
JS: source.start(points, onUpdate)                 (in the page)
```

- `simulated` (this phase): the page runs `sim.js` locally. No server round-trip, smooth animation.
- `niagara` (later): the page polls or subscribes to a small read-only endpoint. Streamlit's iframe cannot
  receive server pushes, so this needs a tiny HTTP/WebSocket service, which is a deployment question for later
  (brief §8: don't add deployment until asked).

### 6.2 Simulator (`value_model.py` + `sim.js`)

- **Units are inferred from the class**, not read from the source: blind exports carry no units, and the answer
  key's units would leak (Task 2). The unit shown is marked "inferred". If a later export variant includes units
  (real Niagara exports do), the source unit wins.
- Per class family, a spec: kind (`analog | binary | setpoint | command`), unit, typical range, and a **driver**:

| Class family | Kind | Unit | Behaviour |
|---|---|---|---|
| `*_Setpoint` | setpoint | °F / cfm / inH₂O | constant, typical value (e.g. SAT sp 55 °F, zone occ cooling 74 °F) |
| Temperature sensors | analog | °F | follow their setpoint ± noise; supply temp drops as cooling valve opens |
| Valve / damper commands | command | % | driven by the equipment's load signal |
| Fan speed | command | % | follows load, 30–100 % |
| Fan / run status | binary | on/off | on when command > 0 or schedule occupied |
| Air flow sensors | analog | cfm | proportional to damper % × design flow |
| Occupancy | binary | occ/unocc | follows the schedule |
| Anything else | analog | — | slow random walk in a neutral range, labelled "generic" |

- **One load signal per equipment** drives correlated values: a sped-up day (1 real minute = 1 simulated hour)
  with an occupancy schedule and a sinusoidal outdoor temperature. AHU load feeds its VAVs' loads so a building
  "breathes" together.
- Deterministic: seeded by point id, so a demo looks the same every time.
- Every value carries a **SIMULATED** badge in the UI and the page header says "Simulated values".

### 6.3 Demo scenario (optional)

A "scenario" dropdown: `Normal day`, `Hot afternoon`, `Stuck reheat valve` (one VAV's valve stays 100 %, its
zone temp drifts up). Useful for telling a story; uses the same simulator with an override.

## 7. Where it shows up

- **New Streamlit page `3_Equipment_3D.py`:** project + equipment picker (templated equipment first, grouped by
  type, search). Reads `?equip=<id>` so other views can deep-link.
- **3D graph details panel:** equipment nodes get an "Open 3D equipment" link.
- **Tree tab:** equipment rows get the same link.
- **Export:** `scripts/export_equipment3d.py <project> [--equip id | --all-ahus]` writes standalone HTML to
  `reports/equipment3d/`, following the system theme, like the graph export.

## 8. Build order and done-when

| Step | Scope | Done when |
|---|---|---|
| E1 | `equipment_view.py`: slot assignment, variant, payload; `anchors.yaml` for AHU + VAV; validator check | Tests pass for AHU-2 and a reheat VAV on Alpha; validator fails on a slot without an anchor |
| E2 | Viewer shell + `parts.js` + `ahu.js`, static (no values), pins, side panel, unplaced list | AHU-2 renders in Streamlit in light and dark, every placed point has a pin, clicking shows provenance |
| E3 | `vav.js` with reheat / fan-powered / dual-duct variants, ghost parts | Three Alpha VAV variants render correctly; a VAV missing its flow sensor shows a ghost |
| E4 | `value_model.py` + `sim.js`, motion, SIMULATED badges, scenario dropdown | Fan, dampers, valves and particles move with values; same seed gives the same demo |
| E5 | Deep links from tree and graph, standalone export | One click from the graph opens the equipment; export works offline apart from the CDN |
| E6 (v0.2) | FCU, chiller, boiler, pump | Same checks per type |

Tests: slot assignment (first-match, stacking, rejected left out), variant rules, anchor coverage, simulator
spec per class family (units, ranges, determinism), payload shape. Visual checks in the browser for each type
in both themes, as for the graph viewer.

## 9. Effort and risk

- E1–E3 (AHU + VAV, static) is the core; the geometry is the part that needs visual iteration. Expect a few
  rounds of "render → screenshot → adjust" per type.
- Labels are the main readability risk on a 20–60 point AHU. Mitigations: stacking per anchor, distance-based
  detail, a "points list" toggle that hides pins.
- Inferred units can be wrong when a class is wrong. That is acceptable for a demo and visible in review: the
  side panel shows the class the unit came from.

## 10. Open questions

1. Is 3D the right default for operators, or should a flat schematic (2D, BAS-graphic style) come next using the
   same anchors? The anchor map is designed so either can be drawn from it.
2. Demo scenarios: which story do we want to tell first (normal day vs a fault)?
3. For the Niagara phase, where would the read-only value endpoint run?
