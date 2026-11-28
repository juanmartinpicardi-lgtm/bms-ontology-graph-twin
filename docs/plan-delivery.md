# Plan – Delivery wave: from a reviewed graph to what a contractor ships

Status: agreed 2026-11-28 (§7). D0 done; the other packages run in their own sessions. Nothing here is built by this document. It follows `plan-workflow-ai.md`
(waves 1 to 3 done, W0 to W11) and the TVDA comparison (*TVDA.ai vs Project Model: analysis and recommendations*,
27 Nov 2026). Once agreed, each work package in §5 runs in its own session and branch, as before. Vocabulary as in
`CLAUDE.md` §2.

## 1. Goal

Today the app ends at understanding: a reviewed knowledge graph, views and an agent. This wave makes it end in
**outputs in the contractor's own currency**: the point schedule, the I/O plan and the controllers to order, the
system test report, the Niagara package and the graphics. Each replaces hours of work the buyer already pays for.

Three things make the app feel like a frontier product while it does that:

- **Talk to it.** Voice and text drive the screen ("show me the 3D twin", "explode the AHU") and edit the building
  ("swap the chillers for Carrier 30XV"). Edits land as proposals a person confirms.
- **It learns.** Every key edit can become a saved rule, visible on one Memory page, used to automate the next
  project.
- **It looks the part.** 3D equipment and plant views at the level of the best late-2026 tools.

What stays: rules and the knowledge model first, models propose and people decide, every fact keeps its source and
method, `liberty_boe` stays held out.

## 2. Decided on 28 Nov 2026

1. **Write-back is allowed when the user asks** (`CLAUDE.md` §1 and §8 updated). The app shows what will change,
   the user confirms, every write is logged. Generated files (CSV, `.bog`, graphics) are outputs, not write-back.
2. Build all nine TVDA recommendations, plus: voice commands for every screen option, 3D at frontier level, the
   memory layer with its own pages, the cost per building as a metric, and one place for all outputs.
3. **Accuracy.** Below 85% is not acceptable for any job; strive for 100%. Two numbers per job (§6.8): what the
   machine gets right on its own (floor 85%, aim higher), and what is right in a delivered output after review
   (100%: nothing unconfirmed ships without being marked).
4. **OEM PDFs** may be stored in our GCP bucket for reading.
5. **Niagara.** A licence can be had, but we work around it for now: we build and check the files ourselves; a
   colleague runs a short test on another machine when a package is ready (§6.7).
6. **Front end.** React with a Python (FastAPI) API now, not after wave 4 (§6.9). Decided 28 Nov 2026.
7. **Memory and tribal knowledge are both kept.** Tribal knowledge is raw knowledge gathered over time (documents,
   field experience, interviews). Memory is wider: it learns from tribal knowledge and from everything users do. Every
   user action and decision is recorded once the user has agreed to it (§6.4).
8. **Voice:** `gemini-3.8-live` (generally available, Google's recommended Live model) in the `us` multi-region.

## 3. Words used here

| Word | Means here |
|---|---|
| **Plant** | The central plant: chillers, boilers, cooling towers, heat exchangers, pumps, expansion tanks and their piping, usually in a plant room (basement or roof). It makes chilled and hot water for the rest of the building. It is not the air side (AHUs, RTUs) or the terminal units (VAVs, FCUs). TVDA covers only the plant today |
| **Point schedule** | Every point each unit needs, one row each: name, unit, what it measures or commands, I/O type (AI, AO, BI, BO, or network), units, source of the requirement |
| **I/O plan** | The point schedule assigned to controllers: which controller and expansion module takes each point, spare I/O, trunks (BACnet MS/TP, IP, Modbus), and from that the controllers and modules to order |
| **Equipment library** | A shared catalogue of real makes and models: for each, its documents (data sheet, installation and operation manual, BACnet PICS, Modbus register map, wiring diagram, controls manual), its protocols, its point list, its 3D variant. Plus general references (ASHRAE guidelines, standards). Project-agnostic; a project links only the models it uses |
| **Representative model** | A generic stand-in when no make or model is known. Good for controls diagrams and estimates; not for field wiring |
| **Output** | A file a contractor ships or a tool imports, regenerated from the confirmed graph |

## 4. Where each package lands in the workflow

| Stage (`plan-workflow-ai.md` §2) | New in this wave |
|---|---|
| 2 Schedules, 4 Submittal | Make and model read from schedules, specs, submittals and BACnet device properties (D2) |
| 6 Point binding | Point list templates from the library's BACnet and Modbus documents (D2) |
| 7 Review | Edits by chat and voice as proposals (D4); "save as a rule?" after key edits (D5) |
| 8 Graphics | Frontier 3D, plant view (D7) |
| 9 Tribal knowledge | Becomes Memory: one page, project and global (D5) |
| 10 Agent | Screen actions, voice commands, edit proposals (D4) |
| New: Estimate and I/O | Point schedule, I/O plan, controllers to order (D3) |
| New: Test | Full system test with reports (D6) |
| 11 Export | Outputs hub (D12), Niagara package and tag write-back (D8), change impact (D9) |

## 5. Work packages

In build order. Each has a done-when and its own branch. ∥ = can run in parallel once its dependencies are merged.
Targets marked *proposed* are to agree in §7.

| # | Package | Depends on | Scope | Done when | Size |
|---|---|---|---|---|---|
| D0 | **Write-back rule everywhere** | — | Carry the new `CLAUDE.md` §8 into the app's own words: `agent/foundations.py` (the "One way" principle), How it works, `knowledge/memory/global.yaml`, the module docstrings and specs that say "never written back". Add D0 to D12 to `roadmap.py` so the Roadmap page shows this wave | No page or memory entry says write-back is forbidden; the Roadmap page lists D0 to D12 | S |
| D1 | **Cost per building** ∥ | — | From `llm_calls`: total model cost and time per building, per step, per job, per 1,000 points. Shown on the project header, All projects, each setup step ("read 5 sheets, 41 calls, $0.31, 2 min") and the agent dock (per question). Cost is shown, never capped (`plan-workflow-ai.md` §8.4) | Troop D shows its total and per-step cost, equal to the sum in `llm_calls` | S |
| D2 | **Equipment library** ∥ | — | §6.1. A shared library page in the left menu. Entries with documents, protocols, point list templates, 3D variant. A `library_seek` job finds and reads OEM documents for a make and model, with page citations, as a proposed entry a person approves. Make and model read per unit from the project's own evidence (§6.1, order of evidence), or a representative model with a list of candidates. General references section (ASHRAE, BACnet, Brick, Haystack) | Every unit in the three dev sets with a make or model in its documents has an approved entry or a pending proposal; each Troop D unit shows its model card or "representative"; at least 3 models' BACnet or Modbus point lists feed binding | L |
| D3 | **Point schedule and I/O plan** | D2 (controller profiles), D5 (save-as-rule) | §6.2. Two modes: **estimate** (from plans, schedules and sequences, before any submittal) and **as built** (from the submittal and BMS export). The AI proposes every row with a confidence and its reason; a person edits inline; analytics on confidence; controller profiles; controllers and modules to order; CSV, Excel, PDF | On Troop D in estimate mode, the predicted point schedule is scored against the submittal's point list (recall and precision per unit type, at least 85% each, aiming for 100%) and the controller count is within ±10% of the riser's; every edit is stored `method=human` and can become a rule | L |
| D4 | **Agent actions and voice commands** ∥ | — (D4b needs D2 for swaps) | §6.3. **D4a screen actions**: `navigate`, `show_floor`, `select`, `highlight`, `focus`, `set_view` (3D/2D, explode, X-ray, labels, camera presets, play/pause simulation), `open_document`, each with a receipt and Undo (spec-agent A3). **D4b edit proposals**: add, remove, swap model, move a point, rename, add a point, each a proposed fact with a Confirm card. **Voice**: a hands-free call mode next to push-to-talk; fast UI commands on the voice model, reasoning handed to Claude; a spoken "yes" confirms | By voice: "show me the 3D digital twin", "go to floor 2", "explode the AHU", "X-ray", "add a heat exchanger on the chilled water loop", "swap the chillers for Carrier 30XV" all work; UI commands change the screen within 2 s of the end of speech (spec-agent A5); every edit waits in Review as a proposal | L |
| D5 | **Memory layer** ∥ | — | §6.4. Finish spec-memory-skills M2, M4 and M6 with a simpler face. A **Memory** page in the left menu (all projects) and a **Memory** section in each project, next to the Tribal knowledge pages, which stay. A journal of every user action and decision, once the user agrees to recording. Auto-saved preferences and facts; rules that change outputs saved on one click ("Save as a rule? This project / this contractor / everywhere / no"). Memory also learns from tribal knowledge. Short "why and how it works" box on both | Every action in review, the I/O plan and the agent is in the journal; a fix or edit made twice prompts "save as a rule?"; once saved, the next project applies it and shows "used rule X"; the dev score does not drop; every entry can be edited, paused or forgotten | M |
| Q1 | **Accuracy push** ∥ | — | §6.8. Every model job re-run in a bake-off with the strongest models (no cost limit); two model families vote and disagreements go to review; close the knowledge-model gaps; real answer keys from past projects; one accuracy page per job | Every job at or above 85% exact on the dev sets; every auto-accept band at least 98% right on spot checks; the accuracy page shows both numbers per job | M, ongoing |
| F1 | **React front end and Python API** | — | §6.9. FastAPI over the existing Python; a React shell with routing, the agent dock, a data grid and the viewers moved over unchanged; Postgres and Cloud Storage on our GCP so nothing is lost on restart; Cloud Run. Streamlit stays up until each page has moved | The guided setup, a project's views and the dock run in the new shell on Cloud Run; a voice command changes the screen with no page reload | L |
| D6 | **Full system test with reports** ∥ | — | §6.5. Scenario library per system type, built from each sequence's structured logic (W8): startup, staging, lead/lag rotation, failover, changeover, a fault per sensor, shutdown, economiser, freeze protection. Each step: expected (cited sequence text) vs observed (simulation), pass or fail. Run one, a system, or all; play it on the 3D or plant view; add a scenario by chat. Report as PDF, JSON and CSV for the commissioning package | Troop D's AHU, VAV and chilled water plant each have at least 5 scenarios; a deliberately broken sequence fails the right step; the report exports with every step cited | L |
| D7 | **Frontier 3D and plant view** ∥ | — (variants use D2) | §6.6. Visual quality bar, interaction set (explode slider, X-ray, section cut, flow animation, point pins with values, scenario playback), a plant view assembled from the graph's `feeds` edges with routed piping, headers and risers, then the air side (AHU to its VAVs). Builders written by the best coding models with a render-and-critique loop | Side-by-side with TVDA's public demos, the user rates ours equal or better on the 5 criteria in §6.6; Troop D's chilled water plant opens as a plant view with every unit's points pinned; 60 fps on a laptop | L, ongoing |
| D8 | **Niagara output and write-back** | D3, D5 | §6.7. Step 1: tags and hierarchy for an existing station (Haystack or Brick tags from our classes), as an import file, and as a write-back when the user asks. Step 2: a new station skeleton `.bog` (folders per equipment, points, histories, alarms). Step 3: wiresheet logic from the structured sequences. Step 4: HTML5 graphics from our views | Step 1 and 2 files open in Niagara Workbench without errors and carry every confirmed point and tag (needs a Workbench licence, §7); a write-back shows its diff and is logged | L |
| D9 | **Change impact on re-upload** | D3, D6, D12 | A revised document gives a diff of the graph and a list of what it changes: points, I/O plan rows, controllers to order, tests, graphics, outputs. Exportable as a change list (the evidence for a change order) | Re-uploading a Troop D sheet with one unit added lists exactly the rows, tests and outputs it touches | M |
| D10 | **Sketches, single lines and risers as input** | D4b | A drawn single line, riser or hand sketch becomes a topology proposal (W6 page reading, W7 riser). When it does not look like a working system, the agent asks: interpret, or keep as drawn? | On a set of sketches we draw, the units and links found are scored vs a key | M |
| D11 | **Operations questions over an event log** | twin state (later phase) | Import an alarm and event CSV as twin state; the agent answers "any anomalies since yesterday?" with citations | Later; not in this wave's build order | L |
| D12 | **Outputs hub** | D3 (first), then each output | One **Outputs** page per project: point schedule, I/O plan, controllers to order, test report, Niagara package, Brick export, graphics. Each shows readiness (what is still proposed), last build, download; regenerated when the graph changes | Every output above that exists downloads from one page and says how many of its facts are still unconfirmed | S, grows |

**Waves:**

- **Wave 4 (parallel):** D0 first (an hour), then F1, Q1, D1, D2, D6 and the engines of D5 and D7 in parallel
  sessions.
- **Wave 5:** D3, D4 (screen actions, edits, voice), the D5 pages, D7 in the new shell, D12.
- **Wave 6:** D8, D9, D10. D11 waits for the twin state layer.

Why this order: D3 needs controller profiles from the library and the save-as-rule prompt from memory. D8 needs a
confirmed point schedule. D6 and D7 depend on nothing new, so they start at once. F1 is agreed, so screens built in
wave 5 go straight into the React shell, so none is built twice; wave 4 builds engines and APIs, not screens.

## 6. Package detail

### 6.1 D2 Equipment library

**Shape.** One folder per entry in a new `library/` (in git, like `knowledge/`), project-agnostic:

- `entry.yaml`: manufacturer, model family, model codes, Brick class and our template, capacity range, protocols
  (native BACnet, Modbus, option card), BACnet vendor id, status (proposed, approved), who approved it.
- `documents.yaml`: each document's type (data sheet, IOM manual, controls manual, BACnet PICS, Modbus register map,
  wiring diagram, service schedule), source URL, date fetched, version, licence note.
- `points.yaml`: the point list template, each row with its BACnet object or Modbus register, our Brick class, units,
  and the page it was read from.
- `variant.yaml`: what the 3D builder needs (shape, number of fans, compressors, coils).

A **References** section holds general documents: ASHRAE Guideline 36 (high-performance sequences), Standard 135
(BACnet), Guideline 13 (specifying DDC systems), Guideline 0 and 1.1 (commissioning), Standard 223P, Brick, Project
Haystack, and open implementations such as LBNL's Guideline 36 sequences in the Modelica Buildings Library. ASHRAE
documents are paid: we store the reference and our own short notes, never the text.

**Where to find documents.** Manufacturers' public product pages and document libraries (data sheets, IOM manuals,
BACnet and Modbus integration guides), BACnet International's BTL product listings (with PICS), and the documents
already in a project (submittal data sheets are often in the controls or mechanical submittal). A `library_seek` job,
given a make and model: searches the manufacturer's site, fetches the documents, sorts them by type, reads the
protocols and the point list with page citations, and files a proposed entry. A person approves it once; every
later project reuses it at no model cost.

**How the make and model is chosen for a unit**, strongest evidence first:

1. The equipment schedule's manufacturer and model columns, or "basis of design" notes.
2. The specification's basis of design and its list of acceptable manufacturers (Division 23).
3. The controls or mechanical submittal: data sheets and device models.
4. The BMS export: the BACnet device object's vendor id and model name, and naming patterns typical of a vendor.
5. A nameplate photo, read by a vision model (later, on site).
6. None of the above: a **representative model**, with the specification's acceptable manufacturers as candidates
   for the user to pick. The view says "representative" and the I/O plan says field wiring diagrams are not available.

Each choice is a fact like any other: source, method, confidence, status.

### 6.2 D3 Point schedule and I/O plan

**What it is for.** The point schedule says what has to be measured and commanded. The I/O plan packs it into
controllers. Together they give the controllers and modules to order and the point count that drives labour, so yes:
this is the core of the controls estimate.

**How the rows are proposed**, cheapest first:

1. **As built:** the submittal's point list and the BMS export (already in the graph, W4 and W7).
2. **Estimate:** the unit's template (what an AHU of that variant needs), the sequence's structured logic (W8: every
   loop needs its sensor and output), the specification's points list tables, the library's point list (D2).
3. A model fills what is left and names its reason ("the sequence's economiser mode needs an outside air damper
   command").

I/O type comes from the Brick class and the library. Controller assignment is rules: the controller profile's I/O
counts per model and expansion module, one controller per air handler, terminal units on their own controllers, spare
I/O per contractor convention, trunk length and device limits. Controller profiles live in `knowledge_model/controllers/`
(for example JACE 9000 with NIO modules, Distech, Honeywell Optimizer), each with its source documents in the library.

**The screen.** One table per unit, grouped by controller. Each row shows its confidence as a bar and its source
(submittal, BMS, template, sequence, spec, model). A side panel shows the analytics: rows by source, by confidence
band, how many a person confirmed, the measured accuracy of each band (calibration, W5). Edit any cell inline; bulk
accept a band; add or delete a row; switch controller profile and watch the controller count change. Every edit is
stored `method=human`. After an edit that looks like a pattern (the same change twice, or a change that can be
written as a condition), a quiet line asks: "Save this as a rule? This project / contractor X / everywhere / No" (D5).

**Outputs:** CSV, Excel and a PDF point schedule; controllers and modules to order with quantities; a summary for the
estimate (points by type, controllers, spare I/O).

### 6.3 D4 Agent actions and voice commands

The tool list is spec-agent §6; this wave builds its "drive the screen" and "propose" rows. Each viewer
(`equipment3d`, `digital_twin`, `graph3d`, `sequences`, the new plant view) takes commands over the existing
`app/bridge.py` message channel, so a command changes the view without reloading it. Voice: push-to-talk exists
(`agent/voice.py`); add a call mode where the browser talks to the voice model directly with a short-lived token minted
by the server, UI commands handled by the voice model, anything needing reasoning handed to Claude. The voice model is
`gemini-3.8-live`: generally available on Vertex AI and Google's recommended Live model, with function calling and
search grounding but no thinking mode, so reasoning stays with Claude (`ask_expert`). Region: the `us` multi-region
(our projects are in North America, and a multi-region fails over by itself); `us-central1` stays as the fallback,
where it already answers today (`ai/models.py`). Writes only through
`propose_*` tools, confirmed by a click or a spoken "yes" shown in the transcript (spec-agent §9).

### 6.4 D5 Memory layer

Modelled on how Claude and Hermes Agent keep memory: short, readable entries the assistant writes as it works and the
person can see, edit and delete; procedures saved as skills; a background curator that turns repeated work into
proposals. The files, scopes and curator already exist (`memory.py`, `curator.py`, `knowledge/`, W10). This package
builds the face and the triggers.

**Memory and tribal knowledge.** Both stay, and they feed each other:

- **Tribal knowledge** is raw: what was gathered over time from documents, field experience, notes and interviews.
  It is kept as it was said, with who said it.
- **Memory** is wider and is what the app acts on. It learns from tribal knowledge (a note that "the owner calls the
  plant room MER-1" becomes a naming fact) and, above all, from the users' own work.

**Every action is recorded, once the user agrees.** The first time a person uses the app, they are asked once whether
their work may be recorded. If yes, every action and decision goes into the journal: a review accept or fix, an I/O
plan edit, a swap or an add, an agent request and its answer, a rule saved or refused. The journal is the evidence
memory learns from. Each person can see their own journal, delete entries, or switch recording off.

**Two lanes:**

| Lane | What | How it is saved |
|---|---|---|
| Remembered automatically | Preferences and facts that don't change outputs: "Ana reviews by equipment", "this owner calls the plant room 'MER-1'" | Saved as the person works; shown on the Memory page; one click to forget |
| Rules | Anything that changes how documents are read or outputs are built: a naming rule, a spare-I/O allowance, a controller profile choice, a point every AHU of this contractor has | Asked inline after the edit; saved on one click with its scope; checked against the dev set before it becomes global (spec-memory-skills §1) |

**The pages.** Left menu **Memory** (all projects): sections Rules, Remembered, Skills, Pending, Activity. Project
**Memory**: what applies here, from global down to this site, and what this project taught. Each entry: the words,
scope, who or what taught it, evidence (click through), times used, Edit / Pause / Forget. A short box on both pages:
why (so the same fix is never made twice, and each building costs less than the last) and how (it learns from your
edits, asks before saving a rule, and you can see and change everything it knows).

### 6.5 D6 Full system test

Scenarios are data, per system type, in `knowledge_model/tests/`, each step written as a condition on points and
modes ("within 10 minutes of a lead chiller trip, the lag chiller runs"). The structured sequence logic (W8) fills the
setpoints and timers for this building; Guideline 36 sequences give the default pattern where the sequence is silent.
The simulator (`value_model.py`, `sim.js`) runs each scenario on the graph. Results are always labelled simulated.
The same scenarios can later run against trend data from a real building (functional testing), once twin state exists.

### 6.6 D7 Frontier 3D and plant view

**Quality bar, five criteria** for the side-by-side review: realism (materials, lighting, shadows), legibility (what
each part is, labels that don't clutter), interaction (explode, X-ray, section, camera), live meaning (points pinned
with values, flow and state shown), speed (load under 3 s, 60 fps).

**How.** three.js with the WebGPU renderer and a WebGL fallback; physically based materials, environment lighting,
ambient occlusion, soft shadows. Builders stay parametric code, so every point has an anchor and the geometry follows
the graph (`plan-workflow-ai.md` §6.1 principle 4). The best late-2026 coding models (Claude Fable 5.2 and Opus 5.5
in Claude Code) write and refine the builders in a loop: render, screenshot, a vision model compares with reference
photos and drawings of the real unit and lists what is wrong, fix, repeat. Generated meshes are allowed only for
non-functional shells (casings, fittings), never for parts that carry points.

**Plant view.** Assembled from the graph: units placed by system, piping routed between ports, headers and risers,
valves and sensors where the points are. Then the air side: an AHU with its ducts to its VAVs. Our scope is the whole
building, plant to terminal units; TVDA stops at the plant.

### 6.7 D8 Niagara output

**Why we need it.** Niagara 4 runs a large share of North American buildings, sold under many brands. Most of an
integrator's engineering hours go into the station: folders, points, tags, histories, alarms, logic, graphics. Our
graph already knows what each point is and where it belongs. Two uses:

- **Existing buildings (our main case):** read a station's points, classify and review them, then write the tags and
  hierarchy back, so the owner's station becomes searchable, analytics-ready and consistent. This is the write-back
  `CLAUDE.md` now allows.
- **New work:** generate the station skeleton from the I/O plan, so programming starts from 80% done instead of zero.

The step order (tags first, logic and graphics last) puts the most-used and least-risky output first.

**Working without a licence for now.** A `.bog` is a zip holding an XML description of the station. We build the files
from the documented format and a real station file as a reference (the Reflow demo station, `CLAUDE.md` §5, which W12
also needs). Our own checks run in the test suite: the file unzips, the XML parses, every component type is one Niagara
ships, every confirmed point and tag is present, reading the file back gives the same graph (round trip).

**What a colleague tests on a machine with Workbench**, about 30 minutes per package, from a test pack (files plus a
one-page checklist) and a form for the results:

1. The tag import and the station `.bog` open in Workbench with no errors or warnings.
2. The folder tree matches the equipment list, and point names match the point schedule.
3. Tags show on the points (Haystack or Brick dictionary); a tag search such as "all discharge air temperature
   sensors" finds the right points.
4. The point count per folder equals ours; histories and alarm extensions are where we put them.
5. Write-back: tags imported into a **copy** of an existing station change nothing else (a station diff before and
   after), and can be undone.
6. Later steps: the wiresheet logic runs in simulation; the HTML5 graphics open in a browser from the station.

Their screenshots and the station diff come back as files; we turn each failure into a test before fixing it.

### 6.8 Q1 Accuracy: at least 85%, aiming for 100%

No model gets every fact right on its own, so 100% comes from the whole system: the machine gets as much right as the
best models can, calibration sends exactly the doubtful facts to a person, and nothing unconfirmed ships unmarked.
Last measured (`reports/eval/`, `docs/testing-guide.md`):

| Job | Now | Below the floor? |
|---|---|---|
| Point classes, Alpha (mapper) | 83.5% exact | Yes |
| Point classes, Troop D setup (rules, after W1) | 61% exact, 82% right or broader | Yes |
| Tags placed in rooms (plans) | 83% | Yes |
| Sequence relations | 87% found, 88% precision | Just above |
| Point binding (renamed export) | 99.6% recall | No |
| Agent answers and citations | 100% (10 questions) | No |
| Learning loop on Alpha, points nobody fixed | 97.5% exact | No |

What raises it, in order of expected gain:

1. **Real answer keys.** Troop D's submittal and BMS export are synthetic, so no number is fully trustworthy yet. Two
   or three past projects with their full document set and as-built station or point export are the biggest single
   step. Your Niagara access may be the way to get them (W12 reads the station).
2. **The strongest models on the hard jobs.** Point classes still run on Argon because Claude was not enabled on our
   GCP project (`plan-workflow-ai.md` §8.6). Enable Claude Opus 5.5 and Fable 5.2 and re-run every bake-off with no cost
   limit.
3. **Two model families vote.** Claude and Gemini answer independently; when they agree the confidence rises, when
   they disagree the fact goes to review.
4. **More evidence per fact.** The equipment library's point lists (D2), page images and text together, and
   cross-checks between schedule, submittal and BMS export.
5. **Close the knowledge-model gaps** that no candidate list can reach (`plan-workflow-ai.md` §3).
6. **Memory.** Each saved rule removes a whole class of errors on the next building (Alpha: 85.3% → 97.5%).
7. **Calibration and spot checks** keep each auto-accept band at least 98% right and measure it on real buildings.

Some gaps cannot close from documents alone: in estimate mode, part of the submittal is the contractor's own choice
(spare points, extra sensors). D3 scores what the design documents imply and learns the rest from each contractor's
memory.

### 6.9 F1 The right technology

**Why Streamlit holds us back.** Streamlit runs the whole page script again on every click, voice command or value
change. That is why a command like "go to floor 2" needs a page rerun, why the 3D viewers need a workaround to keep
their camera (`app/bridge.py`), and why the agent dock cannot stream a live voice call. An inline-editable table at
"frictionless" level, instant screen changes by voice and a 60 fps 3D view all want the browser to keep its own state.
Streamlit Cloud also loses buildings and notes on every restart (README). It was the right tool to prove the idea; it
is the wrong one for the product described here.

**What fits what we are building:**

| Part | Choice | Why |
|---|---|---|
| Screens | React with TypeScript (Vite or Next.js) | Client-side routing and state, so voice commands and edits are instant |
| 3D | three.js with react-three-fiber, WebGPU renderer and WebGL fallback | The best web 3D stack; our viewers are already three.js |
| Editable tables | A data grid such as AG Grid | Inline edits, bulk actions and grouping for the I/O plan and review |
| Agent dock and voice | Streaming events (AG-UI pattern) to the dock; the browser talks to Gemini Live directly with a short-lived token | Spec-agent §7 and §10, without reruns |
| Intelligence | Python stays: readers, mapper, knowledge model, rdflib and brickschema, SHACL, the AI layer | All of it carries over; FastAPI puts an API in front of it |
| Long jobs | Cloud Run jobs or Cloud Tasks | Reading a document set runs in the background with progress |
| Data | Postgres (Cloud SQL) for the store and journal, Cloud Storage for documents and the library | Nothing lost on restart; still tables, not a graph database (`CLAUDE.md` §8) |
| Hosting | Cloud Run on our GCP project, next to Vertex AI | One project, customer data stays on GCP |

Moving now, not after wave 4, means every new screen in this plan is built once. Streamlit keeps running until each
page has moved.

## 7. Decisions

Decided 28 Nov 2026: accuracy floor 85% per job, aiming for 100% (§6.8); OEM PDFs stored in our GCP bucket; Niagara
tested by a colleague on another machine, files built and checked without a licence for now (§6.7); memory and tribal
knowledge both kept, every action recorded once the user agrees (§6.4); voice on `gemini-3.8-live`, `us`
multi-region (§6.3); **move to React and FastAPI, hosted on our GCP project (Cloud Run, Cloud SQL Postgres, Cloud
Storage, Identity-Aware Proxy login, Secret Manager, Cloud Build, `us-central1`)** (§6.9). `CLAUDE.md` §8 updated:
auth and deployment are asked for; still no graph database.

Still open:

1. ~~Front end~~ Decided 28 Nov 2026: React and a Python API now (§6.9).
2. **Answer keys.** Can we get two or three past projects with their document sets and as-built station or point
   export (§6.8 item 1)?
3. **Claude on our GCP project.** Who enables Claude Opus 5.5 and Fable 5.2 on Vertex AI (§6.8 item 2)?
4. ~~Deployment~~ Decided 28 Nov 2026: Cloud Run, Cloud SQL Postgres, Cloud Storage and an Identity-Aware Proxy login
   on our GCP project. `CLAUDE.md` §8 updated.
5. **D7 judge.** Who rates the 3D against the five criteria?

## 8. Out of scope for this wave

Multi-user permissions beyond the Identity-Aware Proxy login. Pipe fabrication and CNC output (TVDA's
roadmap). A project-management board. Live BMS connections (twin state, later).
