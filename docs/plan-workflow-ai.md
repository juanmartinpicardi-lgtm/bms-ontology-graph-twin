# Plan – Workflow, ontology and AI: where we are, what to build v0.1

Status: draft for agreement, 2026-11-23. Nothing here is built by this document. Once agreed, each work package in §7
is executed in its own session and branch. Vocabulary as in `CLAUDE.md` §2.

This plan replaces the readiness table of `spec-submittals-workflow.md` §5, which predates the guided setup, and
extends `spec-ai-architecture.md` (who does what) into an execution plan. It builds on the app's Ontology page
(`app/views/ontology.py`).

## 1. Goal

From a building's documents and BMS data, build a reviewed knowledge graph. That means every equipment, point, space
and control relation, typed in Brick plus our extension, each with its source. From that graph, generate what an
integrator builds by hand today: equipment and floor graphics with points bound to them, and the checks that the
building runs as designed.

The leverage: models read what rules can't (drawings, odd tables, prose). Rules and the knowledge model keep the
answers exact and repeatable. People decide. Every model answer is a proposal with a confidence, never a fact on its
own.

## 2. The workflow end to end

| # | Stage | Goes in | Comes out |
|---|---|---|---|
| 0 | Locate | Name or address | Site, address, coordinates |
| 1 | Floor plans | Plan sheets (PDF, vector or scanned) | Floors, rooms, zones; where each unit is and what it serves; the drawing as vectors |
| 2 | Equipment schedules | Schedule sheets | Equipment with type and nameplate; first `feeds` links |
| 3 | Sequences of operation | Sequence pages | Control loops, interlocks, resets, modes, intended values, per equipment type |
| 4 | Controls submittal | Submittal PDF: riser, point schedules, room schedule, RFIs | Controllers and network; points with classes; a second source for rooms |
| 5 | BMS and tool data | BMS CSV today; Haystack (dev); Niagara, CPO Studio later | Points with device, object id, units, kind |
| 6 | Point binding | Everything above | One point, bound across BMS object, submittal point, equipment, template slot and graphic anchor |
| 7 | Review | Every proposal | Confirmed, fixed or rejected facts, each next to its source page |
| 8 | Graphics creation | The confirmed graph | Equipment graphics, floor graphics, system graphics, digital twin |
| 9 | Tribal knowledge | People, review fixes | Notes, site and contractor conventions, memory and skills |
| 10 | Agent | Graph, documents, memory | Answers, diagnoses, checks, with citations |
| 11 | Export and validation | The graph | Brick Turtle, SHACL report |

To confirm (§8): "graphics creation" here means generating equipment, floor and system graphics from the graph (2D
and 3D), as a BMS integrator would draw them. "Point binding" means stage 6: tying each point to the same thing
across every source, and to its place on a graphic.

## 3. What we have today, stage by stage

Readiness: **ready** (works end to end), **partial** (works, with known gaps), **missing**.
AI today: what a model actually does now. Only three jobs are wired: `point_class`, `agent_chat`, `agent_reason`
(`ai/jobs.py`). In the guided setup only the point classification calls a model (`point_class`, below).

| # | Stage | Readiness | Built today | AI today | Ontology landing |
|---|---|---|---|---|---|
| 0 | Locate | partial | Google or OpenStreetMap geocoding, a person confirms, `sites` table (`locate.py`) | none | Outside the graph: no `Site` node |
| 1 | Floor plans | partial | Rules (`intake/floorplans.py`): floor from the sheet title, rooms from labels, tags from `equipment_tags.yaml`, thermostat callouts, nearest-label placement with asks. Vectors for the twin (`intake/vectors.py`) | none. A scanned sheet yields no words, so nothing is read from it | `Floor`, `Room` (Brick, unchecked); `hasPart`, `hasLocation` (Brick); `serves` (off-standard) |
| 2 | Schedules | partial | Rules (`intake/schedules.py`): rows by tag, column layouts per engineer habit (`LAYOUTS`), class refined by row, cross-checks, `feeds` by rule | none. An unknown layout keeps raw values and asks | Brick equipment classes (`RVAV`, `Unit_Heater` unchecked); nameplate as attributes |
| 3 | Sequences | partial | Intake: headings, sections, setpoints, phrase-to-point links (`intake/sequence_text.py`, `sequence_links.py`). Projects: a hand-written YAML per site, resolved and stored as edges (`sequences.py`) | none | 6 control relations (off-standard); intended values stay in the document |
| 4 | Submittal | partial | Rules (`intake/submittal.py`): riser rows, Metasys point rows, typicals, device-to-equipment by tag, room schedule vs plans, RFIs | `point_class` for points the rules leave below 0.9 (`intake/point_ai.py`); proposals capped at 0.85 | Points in Brick classes; controllers and trunks as attributes, not `ba:` nodes |
| 5 | BMS and tools | partial | BMS CSV (`intake/bms.py`): columns by name, same-as by tag, gaps both ways. Haystack adapter plus mapper: structure, rules, templates, LLM | `point_class` on Haiku 5.5, with Argon as fallback, for what rules leave; answers capped below auto-accept | Brick points, `hasPoint`, `hasPart`, `feeds`; units and ids as attributes |
| 6 | Point binding | partial | All rules: BMS object to submittal point by reference; device to equipment by tag; point to template slot to 3D anchor (`equipment_view.py`); sequence phrase to point | none | No alias table: one id per source row |
| 7 | Review | partial | Intake: asks plus decisions kept across re-reads (`intake/state.py`, auto-accept 0.9). Mapper projects: accept, fix, reject (`review.py`) | none | Mapper rows are written `confirmed`; method and confidence still recorded |
| 8 | Graphics | partial | Equipment 3D: parametric builders for AHU, VAV, FCU, chiller, boiler, pump, plant, with simulated values (`app/equipment3d/`). Digital twin: real floors from PDF vectors for document buildings, generated floors for Haystack sites. Graph 3D, Tree | none (`equipment_variant` is planned) | Reads Brick classes and template slots |
| 9 | Tribal | partial | Conventions per contractor, customer and site (`conventions.py`, 1 site file). Setup rules (tags, terms) and notes (`intake/knowledge.py`, `notes.py`). Memory and skills files (`memory.py`, `knowledge/`) | none (`memory_curator` is planned) | Our own layer; not exported |
| 10 | Agent | ready (v1) | Text chat with 5 graph tools (`agent_tools.py`), saved history; voice on Gemini Live | `agent_chat` (Sonnet 5.5), `agent_reason` (Opus 5.5), Gemini 3.8 Live | Reads the graph |
| 11 | Export and validation | missing | Knowledge-model validation at load. Golden-set Brick export only | never a model | No project Turtle, no SHACL |

Baseline numbers (Alpha, names plus folders, `reports/score_v2.txt`):
- 100% of points grouped on the right equipment.
- 83.5% classes exact; 81.4% when above the threshold.
- Feeds recall 91.5%.
- 0 LLM calls.
- Calibration is poor: the 0.9–1.0 band is right 49% of the time, the 0.8–0.9 band 98.7%.

AI point classification in the guided setup (`intake/point_ai.py`, W0):
- After the submittal and BMS readers, points the rules leave below auto-accept (0.9) go to `point_class`. One
  question per distinct point (typicals are asked once). The candidate list comes from the knowledge model: the
  rules' class and runners-up, its subclasses, classes sharing a word, and the generic function classes. At most 15.
- The answer becomes the proposal (`method=llm`, confidence capped at 0.85, so a person reviews it). The rules'
  class stays in `data.rule_class`, and the model, reason and call ids in `data.ai`. Every attempt is logged in
  `llm_calls`. Answers are saved with the building, so a re-read asks only what changed. `PM_AI=off` or no
  credentials: rules only, unchanged.
- Troop D, 23 Nov 2026 (`scripts/score_point_ai.py`, intake scorer, machine only):

  | | Point class exact | Right or broader |
  |---|---|---|
  | Rules only | 430 / 847 (51%) | 691 / 847 (82%) |
  | Rules + `point_class` | 628 / 847 (74%) | 715 / 847 (84%) |

  679 points below 0.9 became 91 questions and 91 calls. All were answered by Argon: Haiku and Sonnet 5.5 are not
  enabled on our GCP project, and each was tried once. Cost: $0.29 ($0.34 per 1,000 points). Time: 94 s with 8 calls
  at once (111 s per 1,000 points); Argon averaged 5.6 s a call.
  The model changed 266 points and agreed with the rules on 413.
- Ceiling: 155 of the 847 answer-key classes are not in the knowledge model (`Temperature_Adjust_Sensor` 56,
  `Heating_Enable_Command` 38, `Heating_Command` 37, …), so no candidate list can reach them. That is W1.
  The rules auto-accept 168 points, 66 of them with the wrong class; those never reach the model. That is W5
  (calibration).

Test sets:
- **Alpha** (Haystack): points only.
- **Troop D**: real public drawings, schedules and sequences, plus a synthetic submittal and BMS export with an
  exact answer key (`troop_d.py`).
- No real submittal plus BMS pair yet.

## 4. The framework we rely on

| Layer | What | Where |
|---|---|---|
| Ontology | Brick 1.4.4 subset (120 classes, 8 relations), BA extension (11 classes, 3 relations) | `knowledge_model/` |
| Knowledge model, rest | 6 templates, name rules (~140 abbreviations), 15 tag prefixes, class matching | `knowledge_model/` |
| Our own layer | Provenance on every node and edge; statuses; conventions; notes; memory and skills | `db/store.py`, `conventions/`, `knowledge/` |
| Store | SQLite property graph, `llm_calls` log | `db/store.py` |
| Models | Vertex AI on our GCP project: Claude Fable 5.2, Opus 5.5, Sonnet 5.5, Haiku 5.5; Gemini 4 Hydrogen, Argon; Gemini 3.8 Live | `ai/models.py`, `ai/providers.py` |
| Model plumbing | Jobs with default, contender and escalation; schema checks; router; every call logged with cost and latency; `PM_AI=off` | `ai/jobs.py`, `ai/calls.py` |
| App | Streamlit, scroll stories, three.js viewers | `app/` |
| Scoring | H1, H2, calibration, cost; intake scorer against Troop D | `scoring/score.py`, `intake/score.py` |

## 5. What is missing to build

### 5.1 Ontology and export (from the Ontology page)

- Declare `drives`, `feedback`, `requires`, `resets`, `requests`, `switches` and `serves` in `ba_extension.ttl`, or
  map them to standard terms.
- Add `Floor`, `Room`, `HVAC_Zone`, `Building`, `Site`, `RVAV` and `Unit_Heater` to the subset.
- Give `Schedule`, `Trend_Log` and `Alarm_Definition` a Brick parent.
- Export each project graph as Brick Turtle and run SHACL on every import.

### 5.2 Data model

- **Proposed before confirmed.** Mapper rows are written `confirmed`. They should be `proposed`, and become confirmed
  by a calibrated threshold, a second source, or a person.
- **Stable ids and an alias table.** Today an id is a folder path or a row. Point binding needs one id per real thing,
  with aliases: schedule tag, BMS name, device plus object id, submittal reference.
- **Many sources per project.** Each source replaces only its own rows. Agreement and conflict are recorded.
- **Nodes for what the sources already give.** Site and building; zones; controllers and networks from the riser
  (`ba:Field_Controller`, `ba:Field_Network`, `ba:isHostedBy`, `ba:isOnNetwork`, `ba:controls`); sequences and
  documents.
- **Point properties.** Units as Brick units, BACnet and time-series references, nameplate values as Brick properties.

### 5.3 Readers that need a model

- Scanned plans; plans whose rooms or tags don't fit the rules; zone boundaries.
- Schedules with an unknown layout.
- Sequences as free prose: loops and interlocks, not only setpoints.
- Riser diagrams drawn as diagrams, not tables.
- Point binding when names and references don't line up.

### 5.4 Graphics

- 3D builders for RTU, cooling tower, heat exchanger, fans, unit heater, meters.
- 2D graphics: equipment, floor and system graphics, in the style integrators deliver.
- Points bound to graphic anchors for every template, not only the six with 3D models.

### 5.5 Learning loop

- The memory curator: repeated fixes become proposed conventions, then shared rules.
- Calibration: confidence that means what it says.

## 6. Using AI in each stage

### 6.1 Principles

1. **Candidates in, ids out.** A model gets our candidates: room labels, tag positions, wall loops, points,
   template slots, each with an id. It answers with ids from that list, plus a confidence and a one-line reason. It
   never invents coordinates, classes or names. A schema check rejects anything else, and the job escalates.
2. **Read once per firm, then rules.** Expensive models draft a reusable rule, such as a schedule layout, a drawing
   convention or a naming convention. A person approves it, and from then on rules do the work for that firm. The
   cost per building falls with every building.
3. **Vision on the page, text where it's text.** Send page images to vision models for drawings and diagrams. Send
   extracted text and tables to text models for schedules, sequences and point lists.
4. **Generated graphics are code and data, never pixels.** Operational graphics must be exact and bound to points.
   Models write and choose parametric builders and layouts. Renderers draw them. No image-generation model in any
   delivered graphic.
5. **Every job has a bake-off, a scorer and a budget** before it becomes the default (§6.4).
6. **Calibrate.** Each job's raw confidence is mapped to measured accuracy (isotonic, per job) before it is compared
   with auto-accept.
7. **Cheap by construction.** Cache the knowledge-model excerpt and per-building context. Use batch prediction for
   re-reads. Escalate only on a failed check. `PM_AI=off` must still give a working, rules-only app.
8. **GCP only for customer data.** All calls go through Vertex AI, unless §8 decides otherwise.

### 6.2 Per stage

Model names are our Vertex lineup (`ai/models.py`, prices as of Nov 2026). The bake-off decides the final default.

| # | Stage | Rules keep | Model job | Default, contender, escalation | People | Measured by |
|---|---|---|---|---|---|---|
| 1 | **Floor plans** | Words, vectors, sheet titles, tag patterns, room-label grid | **Page triage:** sheet type, plan area, scale, north arrow, legend. **Meaning:** pick the room polygon (from wall-loop candidates) for each label; settle a tag's room when labels are about as near; read thermostat and diffuser symbols from the legend; outline zones from shading or hatching. **Scanned sheets:** propose room boxes, at lower confidence. **Once per firm:** draft a drawing-conventions skill | Hydrogen for triage and meaning; Sonnet 5.5 as contender; Opus 5.5 to escalate; Fable 5.2 drafts the firm skill | Answer asks on the 2D plan | Rooms and placements vs the Troop D key; % asks; $ per sheet |
| 2 | Schedules | Approved layouts, cross-checks | Draft a layout once per firm from two sample pages; read rows only when no layout fits | Opus 5.5 layout; Argon contender; Fable 5.2 escalate | Approve the layout | Row and value accuracy; $ on the second building |
| 3 | **Sequences** | Headings, setpoints with units, phrase links | Turn prose into structured logic per template slot role: loops (setpoint, measured, output), interlocks, resets (trim and respond), modes, timers, limits. Flag what the units can't do | Sonnet 5.5; Hydrogen contender; Opus 5.5 escalate | Confirm the logic | Loops and links vs a hand-built key; gaps and conflicts found |
| 4 | **Submittal and riser** | Metasys references, typicals, table rows | Read riser diagrams as a topology: trunks, controllers, addresses, which unit each controller serves. Read odd point tables | Hydrogen; Sonnet 5.5 contender; Opus 5.5 escalate | Answer asks | Controllers and trunk membership vs the key |
| 5 | BMS and tools | Columns by name, adapters | Map unknown headers. Classify points rules can't (`point_class`, built) | Haiku 5.5; Argon fallback; Sonnet 5.5 escalate | Review below threshold | H2 overall and auto-accepted; calibration; $ per 1,000 points |
| 6 | **Point binding** | Exact reference, normalized tag, same device, class-compatible slot | For each unbound point, pick from at most 10 candidates (submittal point, equipment, template slot) and give a reason. Merge "same unit" across documents | Haiku 5.5 (batch); Sonnet 5.5 escalate | Confirm below threshold | Binding precision and recall vs the Troop D key; % auto-bound |
| 7 | Review | Thresholds, second-source agreement | Order the queue by impact. Explain each proposal in one line with its source snippet. Suggest bulk actions ("accept 138 VAVs") | Haiku 5.5 | Decide | Minutes per 1,000 facts; fixes per session |
| 8 | **Graphics creation** | Renderers, layout engine, template slots to anchors | **Build time:** write new parametric builders (RTU, cooling tower, fans…) and 2D symbol sets as code, reviewed and committed. **Runtime:** pick the variant from graph facts; lay out system and floor graphics; place point labels. **QA:** a vision model checks each rendered graphic against the graph (missing part, point on the wrong side) | Build time: Opus 5.5 or Fable 5.2 in Claude Code. Runtime: Haiku 5.5 picks the variant. QA: Hydrogen | Approve new builders | Builders per type; points placed / points bound; QA findings that a person confirms |
| 9 | Tribal knowledge | Conventions, rules, notes | **Curator:** turn repeated fixes into proposed conventions and skills. **Interview:** a voice agent asks site staff what the documents can't say, and files notes | Curator: Sonnet 5.5, Opus 5.5 for rules. Interview: Gemini 3.8 Live, handing to Claude for reasoning | Approve | Conventions accepted; model calls saved on the next building |
| 10 | Agent | Context engine, tools | Built. Next: tools for documents (open the page a fact came from), sequences, graphics; checks such as "does AHU-2 run as designed" | Sonnet 5.5; Opus 5.5 to reason; Fable 5.2 for long tasks | Confirm writes | Right root cause, every step cited; $ per question |
| 11 | Validation | SHACL, knowledge model | never a model | — | — | Report on every import |

### 6.3 Cross-cutting AI work

- **Vision input pipeline.** Render each page at a known DPI. Give it ids that match `pdfdoc.py` coordinates. Overlay
  candidate ids on the image when that helps the model ("label R12").
- **Context caching.** Cache the knowledge-model excerpt, the building's tag list and its scheduled units across every
  call for one building.
- **Batch prediction.** Use it for re-reading a document set and for point binding at scale.
- **Calibration per job.** Isotonic regression on scored outputs, stored with the job. Recompute on every bake-off.
- **Eval harness.** One command runs a job against its key, model by model, and prints accuracy, calibration, cost
  and latency (extends `scripts/score.py` and `scripts/ai_check.py`).

### 6.4 Bake-off rule

A model job becomes a default only when, on the dev set:
- it beats rules alone on its metric;
- its calibrated confidence is within 5 points of measured accuracy in each band holding 30 or more items;
- its cost per building is under the §8 budget.

Never tune on a test set.

## 7. Work packages

In build order. Each has a done-when and its own branch. Packages marked ∥ can run in parallel sessions once their
dependencies are merged.

| # | Package | Depends on | Scope | Done when | Size |
|---|---|---|---|---|---|
| W0 | Guardrails and real test sets | — ∥ | From `assessment-rules-vs-ai.md` §6.3, §8:<br>• coverage checks in every reader (expected vs found; escalate or ask, never a silent zero)<br>• `scripts/stress_intake.py` as a test<br>• rule fixes: device instance join, BMS column synonyms, 4-digit and alphanumeric rooms<br>• `point_class` wired into the setup<br>• 3 more real document sets, one held out | Every stress scenario either reads correctly or asks; no stage ends with zero results and zero questions; 3 sets collected | M |
| W1 | Ontology fixes | — | §5.1 subset and extension changes; loader checks | Every term the readers write loads and validates; the Ontology page shows no off-standard terms | S |
| W2 | Export and SHACL | W1 | Project graph to Brick Turtle; SHACL shapes for the building rules; report in the app | One command exports Alpha and Troop D and prints a SHACL report; the Complete graph page reads it | M |
| W3 | Data model for many sources | — ∥ W1 | `proposed` by default; stable ids plus an alias table; each source replaces its own rows; agreement and conflict | Re-running one source leaves the others intact; the review queue shows only proposed facts | L |
| W4 | Nodes from what we already read | W1, W3 | Site, building, zones, controllers and networks from the riser, units and BACnet references on points | Troop D's riser is controller and network nodes with `ba:` relations; points carry units | M |
| W5 | Eval harness and calibration | — ∥ | §6.3 harness; isotonic calibration per job; fix the mapper's 0.9–1.0 band | One command per job prints accuracy, calibration, cost; Alpha's bands within 5 points | M |
| W6 | Document-understanding front end, plans first | W0, W5 ∥ | Page sorting for any upload. A model reads structure (floor, room labels, tags, table headers, sequence outline) and rules check it. Floor plans first: room polygons, tag placement, symbols, zones, scanned sheets. Layout skills per firm. Then schedules | On the new real sets (not Troop D alone): the plan scenarios in the stress suite read correctly; rooms and placements beat rules alone; cost per sheet logged | L |
| W7 | Submittal, riser and point binding with AI | W3, W4, W5 | Riser topology; the binding job; same unit across documents | Troop D binding precision and recall vs the key; % auto-bound above threshold | L |
| W8 | Sequences with AI | W1, W5 ∥ W6 | Prose to structured logic per template role; ba: relations | Troop D loops and interlocks vs a hand-built key; gaps and conflicts listed | M |
| W9 | Graphics creation | W4, W7 | New 3D builders; 2D equipment, floor and system graphics; anchors for every template; vision QA | Every Troop D equipment type has a graphic with its points bound; QA runs on each | L |
| W10 | Learning loop | W3, W5 | Memory curator; conventions from fixes; interview mode for the voice agent | A fix made twice on Troop D is proposed as a convention and, once approved, applied on the next run | M |
| W11 | Agent tools | W2, W8, W9 | Open source page, read sequence, show graphic, run a check | "Does AHU-1 run as designed?" answered with cited steps on Troop D | M |
| W12 | Tool adapters | access | Niagara (station export), CPO Studio; merge on device id | When internal access exists | L |

Status, 23 Nov 2026 (the app's Roadmap page shows it live, from `src/projectmodel/roadmap.py`):
- **W0 in progress.**
  - Done: coverage checks after every step (`intake/coverage.py`); the stress suite as a test
    (`tests/test_stress_intake.py`); rule fixes for FLR titles, Niagara export columns, the device instance join,
    4-digit rooms, and unread point rows in the submittal.
  - AI point classification in the setup (`intake/point_ai.py`): Troop D point class exact went from 51% to 74%, for
    $0.34 per 1,000 points (§3).
  - Left: partial-read checks for the scenarios still marked "quiet"; 3 real document sets.
- **Per-project completeness** (`progress.py`) measures every project against the graph standard and names the next
  step. It is shown on the Roadmap and All projects pages. Alpha stays the demo set, unchanged.

Suggested first wave (parallel): **W0**, **W1**, **W3**, **W5**. Second wave: **W2**, **W4**, **W6**, **W8**. Then
W7, W9, W10, W11.

Why W0 comes first: the stress test (`assessment-rules-vs-ai.md` §4) found 9 of 16 realistic variations dropping a
stage to zero or near zero, 7 of them silently. Guardrails and real test sets come before any model work, so the
models are measured on buildings the rules have never seen.

## 8. To agree before executing

1. **Meanings.** Is "graphics creation" generating equipment, floor and system graphics from the graph (2D and 3D)? Or
   does it also mean exporting BMS graphics, such as Niagara PX or HTML5 views? Is "point binding" stage 6 as written?
2. **Test data.** Is Troop D (real drawings, synthetic submittal and BMS) enough to start W6 to W9? Or do we first need
   a real submittal plus BMS pair? No accuracy number is trustworthy until one exists.
3. **Data policy.** Vertex AI only, or may a job call a model outside GCP?
4. **Budget per building.** A target such as $X for a 1,000-point, 10-sheet building, all stages included.
5. **Auto-accept.** May a fact that two sources agree on be confirmed without a person?
6. **Model access.** Which models are enabled on our GCP project today? Claude has been off at times: point
   classification falls back to Argon.
7. **Order.** Is the first wave above right, or should a customer-visible stage (floor plans, graphics) go first?

## 9. Out of scope for this plan

Writing back to any source tool; live values and alarms (twin state, later); auth and deployment beyond Streamlit
Cloud; a graph database.
