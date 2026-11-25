# Testing guide: what was built in waves 1 to 3

How to try each work package of `docs/plan-workflow-ai.md`, what you should see, and what is known to be missing.
Every number below was measured when its PR merged (#26 to #42). The commands are run from the repo root.

## 1. Start

```bash
.venv/bin/python -m streamlit run src/projectmodel/app/main.py --server.port 8521
```

Then open http://localhost:8521.

- **Rules only.** Without Vertex AI credentials, or with `PM_AI=off`, every page works and the AI steps say they are off.
- **With AI.** With credentials, the setup's AI steps run on Gemini Hydrogen or Argon. Claude models return 404 on our
  GCP project today.
- **Full test suite** (about 12 minutes):

  ```bash
  PM_AI=off .venv/bin/python -m pytest -q
  ```

  It passed on `main` after every merge, most recently with 532 tests.

## 2. Ten minutes in the app

| Where | What to look for |
|---|---|
| **Overview → Roadmap** | Waves 1–3 marked done, with each package's parts. AI now runs in the plans, sequences, BMS points, binding, tribal knowledge and agent stages. |
| **Overview → Ontology** | No term marked off-standard (W1). |
| **Overview → Answer keys** | The page where an engineer writes independent answer keys for the plan and sequence readers (§5, item 2). Blind; saves to `*.human.yaml`; makes no model call. |
| **Overview → Complete graph** | The new **SHACL check of the export** section: pick a project and a scope, see pass and fail per building rule, and the failing nodes (W2). |
| **All projects** | A completeness ring and the next step on each card. Alpha's overall dropped from 69% to 60% because controllers, networks and site are now measured, and a BMS export has none of them. |
| **Add a building** | The guided setup. Each step reads, or says what it missed and asks. With AI on, the plans step places tags in rooms (W6), the sequences step proposes control relations and gaps (W8), and the BMS step binds renamed points (W7). |
| **Tree** | Controllers and their network on equipment (W4). |
| **Sequences** | Troop D's control relations, proposed, with their source section (W8). |
| **Tribal knowledge** | Proposed conventions waiting for **Approve / Reject**, with their evidence and a dry run, plus a "Look for patterns" button. The project page has an interview form (W10). |
| **Agent dock** | Ask "Does AHU-1 run as designed?" on Troop D. The answer goes step by step, and every claim is a citation you can open as a page crop or a graph link (W11). |
| **Graphics** | Each Troop D equipment type with its 2D schematic, points on anchors, simulated values and a QA result. Also floor and system graphics. **Equipment 3D** has the new types (W9). |

## 3. One command per package

All model runs reuse answers already in `llm_calls`, so a rerun costs nothing.

| Package | Command | What you should get |
|---|---|---|
| W5 calibration | `.venv/bin/python scripts/eval.py mapper` | Alpha's 0.9–1.0 band right about 99% of the time, against 50% before calibration. |
| W2 export + SHACL | `.venv/bin/python scripts/export_brick.py troop_d --include-proposed` | 1,085 nodes and 2,124 edges round-trip; 12 of 13 building rules pass and Brick's own shapes report 2 violations, both on the CHW plant (a system, not equipment). |
| W9 graphics | `.venv/bin/python scripts/graphics_coverage.py troop-d/documents` | Every Troop D type with points has a graphic; 694 of 847 points on an anchor; QA passes. |
| W6 plan reader | `.venv/bin/python scripts/eval.py plan_meaning` | Keyed plan facts: 49% with rules alone, 83% with Hydrogen and rules. About $0.04 per sheet. |
| W8 sequences | `.venv/bin/python scripts/eval.py sequence_read` | Relations found: 18% with rules alone, 87% with Hydrogen and rules, at 88% precision. |
| W7 binding | `.venv/bin/python scripts/eval.py point_bind` | Renamed export, names only: recall goes from 84.5% to 99.6% with the model. $0.13 per 1,000 points. |
| W10 learning loop | `.venv/bin/python scripts/learning_loop.py` | Alpha, on points nobody fixed: 85.3% → 97.5% class exact. Runs in a temporary copy, so nothing in the repo changes. |
| W11 agent | `.venv/bin/python scripts/agent_ask.py --project troop_d "Does AHU-1 run as designed?"` | A cited, step-by-step answer in about 80 s, for about $0.06–0.09. Use `PM_AI_TIMEOUT_S=360` if Argon stalls. |
| W11 scored | `.venv/bin/python scripts/eval.py agent --models argon` | 10 questions: answers 100%, citations 100%. |
| All | `.venv/bin/python scripts/eval.py all` | Every job, with its §6.4 verdict. |

## 4. Per package: done, and known gaps

- **W0 guardrails.** No step is silent. Over 17 stress variations, 10 read and 7 ask (`tests/test_stress_intake.py`).
  - **Real sets:** `msu_mbb` and `itd_d1_lab` are dev sets.
  - **Held out:** `liberty_boe` is held out. Only its headline counts are ever reported.
- **W1 ontology.** Every term the app writes is declared. The two fixes W2's checks found are made (25 Nov 2026):
  - `ba:serves` now ends on `rec:Space`, and the export writes `hasLocation` as `rec:locatedIn`, so rooms are no
    longer typed as Brick's deprecated `brick:Location`;
  - each `ba:Field_Network` lists its controllers with `rec:includes`.

  Troop D's Brick shape results: confirmed facts 35 violations and 26 warnings → 0 and 0; with proposed facts
  31 violations and 49 warnings → 2 and 0 (the CHW plant, a system).
- **W3 many sources.** Facts are proposed until one of these happens:
  - a calibrated score reaches 0.9;
  - a person confirms.

  When two documents agree, the fact still waits for the expert, noted "documents agree" with their combined
  confidence, and can be accepted in one click (Add a building → Review → Waiting). Troop D has 28 unit→room
  conflicts held for review.
- **W4 nodes.** Troop D has 67 controllers and 4 networks, and 847 of 847 points sit on the right controller.
  - **Zones:** only where a source states them. Troop D gets none.
  - **Alpha:** has no site or building node.
- **W5 calibration.** Every band of 30 or more items is within 5 points. Caveat: Alpha repeats one VAV typical 138 times,
  so the held-out numbers are optimistic.
- **W2 export.** Not yet run on every import; it's one command. With confirmed rows only, the graph is thin, because
  point classes stay proposed.
- **W6 plans.** Not built yet:
  - room outlines, scanned sheets and zones;
  - schedules with an unknown layout.

  The model doesn't yet remove the false rooms the rules read.
- **W8 sequences.** The key has only one building (Troop D), and the agent that built the reader also wrote it, before
  writing the prompt (a person can now write an independent one: §5, item 2). On the real dev sets the rules find no
  candidates yet, because their headings name no equipment family.
- **W7 binding.** Its scenarios are synthetic renamings of Troop D, so the calibration check is weak. Two known issues:
  - 2 wrong auto-binds when the BMS drops objects;
  - `unit:CHWPLANT` is a system and fails Brick's Equipment shape.
- **W10 learning loop.** Measured on Alpha. On guided-setup projects it is unit-tested only. It runs on demand, not
  after each review batch.
- **W11 agent.** No live BMS values, so "runs as designed" in operation is always "unknown". Argon sometimes stalls past
  120 s.
- **W9 graphics.** Not every point has an anchor yet: 153 Troop D points, mostly on the AHU and chillers, are listed under their graphic. Unit heaters and two exhaust fans have no BMS points, so they show dashed "expected, not found" cards. On Alpha, 1,809 of 1,848 points are on an anchor, but QA fails on
  the 8 chilled-water meters, the 3 boilers and 2 pumps (Graphics → Coverage lists why). All values are simulated.
- **W12 tool adapters.** Waits for Niagara and CPO Studio access.

## 5. Decisions

**Decided (25 Nov 2026).** Two documents agreeing does not confirm a fact on its own: the expert decides. The fact
waits in the review, noted "documents agree" with their combined confidence (1 minus the product of each document's
doubt, as if they were independent), and the expert can accept that whole group in one click. Only a fact's own
calibrated confidence of 0.9 or more still confirms it without a person. `PM_AUTO_AGREE=2` brings the old rule back.

**Decided (25 Nov 2026).** No cost limit on AI jobs, as long as calls are billed to our GCP project. The app's model
calls all go to Vertex AI on GCP: about $6 so far across every package. The bake-off still reports cost per job, but
no longer fails a job on cost. So the plan reader (W6) and the sequence reader (W8) now pass.

**Still open, in plain words:**

1. **Real test data.** Troop D's drawings are real, but its controls submittal and BMS point list were made up by us to
   match those drawings. The point-matching and point-class numbers are only as good as that made-up data. Needed: one
   real controls submittal plus the BMS point export from the same past job, which can stay anonymised. A search of
   public sources (25 Nov 2026: bid and addenda sites in 8 states, commissioning reports, open datasets such as LBNL
   Building 59 and Mortar) found no such pair: real submittals and BMS exports are almost never posted. Nearest
   misses: a public dataset of real BMS point names from about 92 anonymised buildings (no drawings), and city permit
   archives with design-stage point lists (the same kind of data as Troop D). The way left is a public-records request
   to one building owner for the controls O&M volume and a BMS point export.
2. **Answer keys written by a person.** To score an AI reader, someone writes down the right answers first. For plans
   and sequences, the AI agent that built each reader also wrote its answer key (before building it, but still). The
   tool for fixing this now exists. It needs about 1–2 hours of an engineer, and no code:

   - **Start it:** run the app (§1), open **Overview → Answer keys**, pick a job and a set. The documents must be in
     `data/raw/` (`.venv/bin/python scripts/run_real_sets.py --fetch`). Troop D's sequences come with the repo.
   - **What it asks:** a fixed, seeded sample (about 100 minutes in all): 17 plan tags on `msu_mbb` and 21 on
     `itd_d1_lab` (which room each is in or serves), and 17 sections of Troop D's sequences (which control relations
     each states). The page shows the source, takes the answer from dropdowns built from the documents, saves any time,
     and resumes later. It is blind: the reader's answer stays hidden until an item is done, and showing it is
     recorded and locks the item.
   - **What it writes:** new files, `data/ground_truth/<set>/plans.human.yaml` and `sequences.human.yaml`. The agent
     keys are never touched.
   - **What it does to the scores:** `scripts/eval.py plan_meaning` and `sequence_read` use the person's answers on the
     items they cover, and report the reader against the human key and against the agent key on the same items, plus
     how often the two keys agree. Without a key file, the output is unchanged.
   - **Held out:** `liberty_boe` is never offered.

   The guide for the engineer is [`answer-key-guide.md`](answer-key-guide.md). Until a person has filled it in, those
   scores stay "promising, not proven".

**Done (25 Nov 2026).** The two small ontology corrections: rooms are now typed the same way in our extension and
in the export, and each network lists its controllers the way Brick expects (§4, W1).
