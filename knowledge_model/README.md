# Knowledge model v0

The definitions that are the same for every project. Loaded and validated by
`src/projectmodel/knowledge_model.py`; check with `.venv/bin/python scripts/validate_km.py`.

| File | What it holds |
|---|---|
| `brick_subset.yaml` | The Brick 1.4.4 classes and relations the mapper may assign, grouped. Parents come from Brick. |
| `ba_extension.ttl` | Building-automation classes Brick lacks (controllers, field networks, unit heater, software/diagnostic/cost points, schedules, trend logs, alarm definitions) and 10 relations (3 hardware links, 6 control relations, `serves`). |
| `templates/*.yaml` | Equipment templates (AHU, VAV, FCU, chiller, boiler, pump): point slots, name patterns, expected feeds. See `templates/README.md`. |
| `name_rules/abbreviations.yaml` | Tokenizer settings, phrase rules, controlled vocabulary, abbreviations (with alternatives for ambiguous ones), worked examples. |
| `units.yaml` | Engineering units as sources spell them (°F, cfm, in.wc...) → QUDT unit ids (`unit:DEG_F`), the units Brick uses; what each measures, checked against the point's class. Read by `src/projectmodel/units.py`. |
| `shapes/*.ttl` | SHACL building rules (W2): a point on exactly one equipment, `hasLocation` to a location, `isHostedBy` to one controller, `feeds` between equipment, a VAV with a zone temperature sensor, and more, each with a label and a comment. Run with Brick 1.4.4's own shapes on every export by `scripts/export_brick.py` (`src/projectmodel/export/`); the report is `reports/shacl/<project>.json`. |

Validation fails the load if: a class is missing or deprecated in Brick 1.4.4, an equipment/point class
is listed under the wrong kind, an extension class clashes with Brick or has an unknown parent, a
template references an unknown class/template/relation or has a bad regex, a tag prefix proposes a class that is not an equipment class of the model, a relation the app writes (`WRITTEN_RELATIONS` in the loader: the six control relations, `serves`, and the riser's `isHostedBy`, `isOnNetwork`, `controls`) is declared nowhere, an extension relation has no label and comment or a parent relation Brick lacks, an abbreviation expands to a
word outside the vocabulary or can never be produced by the tokenizer, or a worked example parses differently.

Tuning rule: change these files based on the Alpha dev set only, never a test set.

## Modelling decisions

- **Containment is `hasPart`, not `feeds`** (decided 2026-11-08). A plant or loop contains its chillers,
  boilers, pumps and heat exchangers, and an AHU contains its fans: the graph records these as `hasPart`
  only. `feeds` is kept for a medium actually flowing to other equipment (AHU → VAV air, hot water plant
  → reheat VAV). Haystack's refs (`chilledWaterRef`, `hotWaterRef`, `airRef`) also express containment,
  so the ground truth converted from them has `feeds` links we deliberately don't produce: on Alpha 23 of
  270 (plant → its members 17, AHU → its own fans 6), which caps feeds recall there at 91.5%.

### Terms the app writes (W1, decided 2026-11-24)

Rule: every class and relation the readers write is declared here, so the Ontology page lists nothing as
off-standard and export can map each term. The loader fails if one is not (`WRITTEN_RELATIONS`, tag prefix classes,
template slots), and `tests/test_intake.py` checks the terms a published Troop D setup really holds.

- **Control relations** `drives`, `feedback`, `requires`, `resets`, `requests`, `switches` → `ba:` object
  properties. Brick 1.4 has nothing for control logic (no relation says "setpoint drives output"). Each has domain
  `brick:Point` and a range (`resets` → `Setpoint`, `requests` → `Equipment`, the rest → `Point`). The list lives in
  the loader (`CONTROL_RELATIONS`); `sequences.CONTROL` reads it from there.
- **`serves`** → `ba:serves`, `rdfs:subPropertyOf brick:feeds`. Brick expresses "a VAV serves a space" as
  `feeds` to an HVAC zone, and "is in a place" as `hasLocation`. The floor plans give a third fact: the unit's
  thermostat is in this room. That is not a zone the unit feeds, so it keeps its own term, and a reader of plain
  Brick still sees `feeds` through the sub-property. Equipment that only sits in a room uses `hasLocation`.
  Its range is `rec:Space`, the parent of `brick:Location` and of every `rec:` location, so a reasoner never types
  a served room as the deprecated `brick:Location`.
- **Locations** `Floor`, `Room`, `HVAC_Zone`, `Building`, `Site` → Brick classes, kept in a `locations:` section of
  `brick_subset.yaml`. Brick 1.4 deprecated all of them in favour of RealEstateCore (`rec:Level`, `rec:Room`,
  `rec:HVACZone`, `rec:Building`, `rec:Site`), and the Troop D answer key already names the `rec:` classes. The
  loader still rejects a deprecated class anywhere else. Here it accepts it only while Brick's own `isReplacedBy`
  matches the `rec:` class written in the file, and records it as `replaced_by`. Export (W2) writes the `rec:`
  class, and writes `hasLocation` / `isLocationOf` as `rec:locatedIn` / `rec:isLocationOf`, which Brick 1.4.4
  declares equivalent: its generic `brick:hasLocation` shape still asks for the deprecated `brick:Location`.
- **Networks** (`ba:Field_Network`, a `brick:Collection`): the store keeps one edge per controller,
  `isOnNetwork`. The export also writes the other direction, `<network> rec:includes <controller>`, because
  Brick's Collection shape wants a collection's members listed that way.
- **`RVAV`** is a real Brick 1.4.4 class (under `VAV`), not deprecated: added to the subset as it is.
- **`Unit_Heater`** is not in Brick. Brick has `Space_Heater` ("a heater used to warm the air in an enclosed
  area"): `ba:Unit_Heater` is a subclass of it, so the name the readers and the answer key already use stays.
- **`Schedule`, `Trend_Log`, `Alarm_Definition`** sit under `brick:Entity`. They describe or attach to points; they
  are not points. Under `brick:Point` they would become candidates every time a point is classified.
- **Point classes** from the Troop D answer key that the subset lacked (16, all real Brick 1.4.4 classes), and the
  part and tank classes it and the schedule reader use, were added. Brick parents are implicit: the loader reads
  them from Brick.

### Nodes from what we already read (W4, 2026-11-24)

- **Controllers and networks** from a controls riser (and the BMS export's device columns): `ba:Field_Controller`,
  one node per BACnet device instance (`ctrl:3104`; a gateway serving three mini-splits is one controller), on its
  trunk `ba:Field_Network` (`net:<supervisor>/FC-1`). The supervisory controller the point references start with
  (`TROOPD-NAE01/FC-1...`) is a `ba:Supervisory_Controller` on each trunk. Relations: controller `ba:isOnNetwork`
  trunk, controller `ba:controls` unit (only where the riser or the same tag says which unit), point `ba:isHostedBy`
  controller. In the store they are node kinds `controller` and `network`, not `equipment`, so equipment counts,
  the tree and the twin are unchanged.
- **Units** stay as the source wrote them (`units`) with the QUDT id (`unit`) where the spelling names one unit
  (`units.yaml`). An ambiguous spelling ("F") gets none.
- **Site and building** come from the project record (`rec:Site`, `rec:Building`); floors are `hasPart` of the
  building. **HVAC zones** only where a source states one (a zone fact, or a schedule's `zone` column): none is
  inferred.
