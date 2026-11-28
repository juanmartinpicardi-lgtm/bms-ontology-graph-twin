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

- Real live values, trending, alarms, writing commands. The viewer is read-only: it never writes to a tool (write-back, when the user asks, is a separate package, plan-delivery D8; brief §8).
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
| **AHU** | casing, OA inlet, mixing box (OA/RA dampers), relief outlet, pre-filter, bag filter, cooling coil, heating coil, supply fan, return fan, return duct, supply riser + VAV branch manifold | no heating valve → no heating coil; no economizer damper → no mixing box; relief outlet if `relief_damper`; return fan if return-fan points or `RF` sub-equipment exist (Alpha AHU-2 has both) |
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
- **Look and motion:** see §4.4. That section is the quality bar, not a nice-to-have.
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

### 4.4 Visual target (the quality bar)

Target: [`reference/ahu-graphic-target.png`](reference/ahu-graphic-target.png), a BAS-style cut-away AHU
supplied as the bar to meet. It is a **style reference only**: we draw our own geometry in code and never ship or
trace the image (source and licence unknown). Unlike the reference, ours is **real 3D and fully interactive**:
the user can orbit, zoom and click everything, and it opens on a "hero" camera matching the reference's
three-quarter view from the front and above.

What "this level" means, item by item:

| Element | In the reference | What we build |
|---|---|---|
| **Casing** | Dark grey sheet metal, front wall removed, thickness visible at cut edges | `MeshStandardMaterial` metal/roughness, bevelled panel edges, visible wall thickness at the cut, subtle panel seams. Front wall cut away; a toggle shows it closed (translucent) |
| **Ductwork** | Return duct looping over the top, fresh-air inlet left, supply riser and branch manifold right | Same topology from the variant: OA inlet → mixing box ← return duct (over the top) → relief outlet if `relief_damper`. Supply duct → riser → branch manifold → downstream VAVs (see "Context" below) |
| **Filters** | Pleated pre-filter, bag filter with pockets | Procedural pleats (folded plane) and bag pockets (lathe geometry); canvas-generated fibre texture. Drawn always: filters are physical even when the export has no filter points (Alpha has none). A part with no point gets a muted chip "no point in source" |
| **Coils** | Finned coil with copper headers, pipe stubs with valve and actuator | Fin pack (instanced thin plates), copper headers and U-bends, supply/return stubs coloured by medium, valve body + actuator whose stem/indicator moves with `Valve_Command` |
| **Fan** | Plenum/plug fan in a housing, blades lit green when running | Housing + impeller (instanced blades) spinning at `speed%`; **status glow**: green emissive ring + bloom when `Fan_Status` = on, red when tripped, grey when off. Motor + VFD box with frequency/power readout |
| **Dampers** | Blade dampers at inlets | Opposed-blade dampers whose blades rotate to the command % (economizer, relief, VAV) |
| **Sensors** | Small transmitter heads on the duct with probe | Sensor head models on stalks per anchor: temperature, humidity, pressure (with tube), flow station (grid in the duct) |
| **Airflow** | Animated chevrons: green on fresh air, red on return, blue on supply | **Flow arrows** (chevrons scrolling along the duct, colour by air stream: outside green, return red, mixed amber, supply blue) **plus** soft particle streams inside the cut-away. Speed ∝ fan speed × damper %. Stops when the fan is off. Colour can switch to "by temperature" (blue → red ramp from the live sensor values) |
| **Water** | Pipe stubs | Particles in pipes when the valve is open, colour by medium |
| **Labels** | Title + dark pill chips with value/unit, thin leader to the sensor | Same idiom: point name in the theme's text colour, value chip (`##.#°F`, `RUN`, `NORMAL`, `AUTO`) with state colour, leader line to the anchor. CSS2D, crisp at any zoom, never overlapping (simple collision push) |
| **Panels** | Grouped tables: "SF Run Status / Trip / H-O-A / VFD Speed Cmd / FB / Enable", setpoints panel | Generated **component panels**: points grouped by part (supply fan, return fan, cooling coil, economizer…), and a **setpoints panel** listing every `*_Setpoint`. Pinned to screen corners, collapsible, click a row → highlight + fly to its anchor |
| **Context** | Supply manifold branching to 3 VAVs | Downstream VAVs from the graph's `feeds` links. AHU-2 feeds 88, so show up to 6 branches (first by name) and a "+82 more" chip that opens a searchable list; clicking a VAV opens its own 3D view. Upstream plant (chilled/hot water) as labelled pipe stubs linking to the chiller/boiler |
| **Header** | Site / equipment name, nav | Equipment name, class, template fit, value-source badge (**SIMULATED**), scenario picker, camera presets |
| **Lighting** | Studio-lit, dark backdrop | `RoomEnvironment` image-based lighting (generated, no asset file), one key light with soft shadows, ground contact shadow, ACES tone mapping, `UnrealBloomPass` for status glows. Dark theme matches the reference; light theme uses the same scene on the app's light `--bg` |

Performance: 60 fps on a laptop for one AHU with 6 VAV branches. Instance repeated geometry (fins, blades,
chevrons, particles). Pause rendering when the tab is hidden.

**Acceptance for the look:** a screenshot of Alpha AHU-2 at the hero camera, dark theme, put next to the
reference image. Someone outside the project should judge them as the same class of graphic. The coding session
must iterate render → screenshot → compare in the browser pane until that holds, then check light theme.

### 4.5 Template and anchor gaps this exposes

Alpha AHU-2's real points include things the AHU template has no slot for. They would land in "unplaced" and
the model would miss parts. Add these slots to `ahu.yaml` (with anchors), then **re-score Alpha to confirm no
regression** (slots also feed the mapper's template boost):

| New slot | Classes (Brick) | Alpha example |
|---|---|---|
| `return_fan_cmd` / `return_fan_speed` / `return_fan_status` | `Fan_Speed_Command`, `Fan_Status` on a return fan | `RF VFD S/S`, `RF Status` |
| `relief_damper` | `Damper_Command`, `Damper_Position_Command` | `Relief Damper Signal` |
| `vfd_frequency`, `vfd_power` (on fan sub-equipment) | `Frequency_Sensor`, `Power_Sensor` | `Supply Fan Frequency`, `Return Fan Power` |
| `building_pressure` | `Building_Air_Static_Pressure_Sensor` | `Building DP` (currently mapped as supply static: a review item) |
| `filter_status` / `filter_dp` | `Filter_Status`, `Filter_Differential_Pressure_Sensor` | none on Alpha; present on most real AHUs |
| `return_humidity`, `oa_flow` | `Return_Air_Humidity_Sensor`, `Outside_Air_Flow_Sensor` | none on Alpha; in the reference |

Supply fan vs return fan points need the name rule "SF/RF" to pick the slot; the anchor map already separates
`supply_fan` and `return_fan` parts.

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

- **New Streamlit page `views/equipment_3d.py`:** project + equipment picker (templated equipment first, grouped by
  type, search). Reads `?equip=<id>` so other views can deep-link.
- **3D graph details panel:** equipment nodes get an "Open 3D equipment" link.
- **Tree tab:** equipment rows get the same link.
- **Export:** `scripts/export_equipment3d.py <project> [--equip id | --all-ahus]` writes standalone HTML to
  `reports/equipment3d/`, following the system theme, like the graph export.

## 8. Build order and done-when

| Step | Scope | Done when |
|---|---|---|
| E1 | `equipment_view.py`: slot assignment, variant, payload; AHU template gaps (§4.5); `anchors.yaml` for AHU + VAV; validator check | Tests pass for AHU-2 and a reheat VAV on Alpha; validator fails on a slot without an anchor; Alpha re-scored with no regression; AHU-2's return fan and relief damper points are placed, not unplaced |
| E2 | Viewer shell + `parts.js` + `ahu.js` at the §4.4 quality bar: casing, filters, coils, fan, dampers, sensors, labels, component panels, VAV branches, flow arrows (static values) | Side-by-side screenshot with the reference passes §4.4 acceptance; every placed point has a label; clicking shows provenance; light and dark both seamless |
| E3 | `vav.js` with reheat / fan-powered / dual-duct variants, ghost parts | Three Alpha VAV variants render correctly; a VAV missing its flow sensor shows a ghost |
| E4 | `value_model.py` + `sim.js`, motion, SIMULATED badges, scenario dropdown | Fan, dampers, valves and particles move with values; same seed gives the same demo |
| E5 | Deep links from tree and graph, standalone export | One click from the graph opens the equipment; export works offline apart from the CDN |
| E6 (v0.2) | FCU, chiller, boiler, pump | Same checks per type |

Tests: slot assignment (first-match, stacking, rejected left out), variant rules, anchor coverage, simulator
spec per class family (units, ranges, determinism), payload shape. Visual checks in the browser for each type
in both themes, as for the graph viewer.

## 9. Effort and risk

- E1–E3 (AHU + VAV, static) is the core; the geometry is the part that needs visual iteration. At the §4.4 bar,
  E2 alone is the biggest step: expect many rounds of "render → screenshot → compare with reference → adjust",
  probably more than one session. Split E2 if needed: (a) casing, ducts, flow arrows, hero camera, lighting;
  (b) filters, coils, fan, dampers, sensors; (c) labels, panels, VAV branches.
- Labels are the main readability risk on a 20–60 point AHU. Mitigations: stacking per anchor, distance-based
  detail, a "points list" toggle that hides pins.
- Inferred units can be wrong when a class is wrong. That is acceptable for a demo and visible in review: the
  side panel shows the class the unit came from.

## 10. Open questions

1. Is 3D the right default for operators, or should a flat schematic (2D, BAS-graphic style) come next using the
   same anchors? The anchor map is designed so either can be drawn from it.
2. Demo scenarios: which story do we want to tell first (normal day vs a fault)?
3. For the Niagara phase, where would the read-only value endpoint run?
