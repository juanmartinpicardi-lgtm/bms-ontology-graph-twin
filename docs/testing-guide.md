# Testing guide: what was built in waves 1 to 3

How to try each work package of `docs/plan-workflow-ai.md`, what you should see, and what is known to be missing.
Every number below was measured when its PR merged (#26 to #41). The commands are run from the repo root.

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

  It passed on `main` after every merge, most recently with 499 tests.

## 2. Ten minutes in the app

| Where | What to look for |
|---|---|
| **Overview → Roadmap** | Waves 1–3 marked done, with each package's parts. AI now runs in the plans, sequences, BMS points, binding, tribal knowledge and agent stages. |
| **Overview → Ontology** | No term marked off-standard (W1). |
| **Overview → Complete graph** | The new **SHACL check of the export** section: pick a project and a scope, see pass and fail per building rule, and the failing nodes (W2). |
| **All projects** | A completeness ring and the next step on each card. Alpha's overall dropped from 69% to 60% because controllers, networks and site are now measured, and a BMS export has none of them. |
| **Add a building** | The guided setup. Each step reads, or says what it missed and asks. With AI on, the plans step places tags in rooms (W6), the sequences step proposes control relations and gaps (W8), and the BMS step binds renamed points (W7). |
| **Tree** | Controllers and their network on equipment (W4). |
| **Sequences** | Troop D's control relations, proposed, with their source section (W8). |
| **Tribal knowledge** | Proposed conventions waiting for **Approve / Reject**, with their evidence and a dry run, plus a "Look for patterns" button. The project page has an interview form (W10). |
| **Agent dock** | Ask "Does AHU-1 run as designed?" on Troop D. The answer goes step by step, and every claim is a citation you can open as a page crop or a graph link (W11). |
| **Equipment 3D / Graphics** | See §4, W9. |

## 3. One command per package

All model runs reuse answers already in `llm_calls`, so a rerun costs nothing.

| Package | Command | What you should get |
|---|---|---|
| W5 calibration | `.venv/bin/python scripts/eval.py mapper` | Alpha's 0.9–1.0 band right about 99% of the time, against 50% before calibration. |
| W2 export + SHACL | `.venv/bin/python scripts/export_brick.py troop_d --include-proposed` | 1,082 nodes and 2,098 edges round-trip; 12 of 13 building rules pass. |
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
- **W1 ontology.** Every term the app writes is declared. W2's checks found two fixes still to make:
  - `ba:serves` has range `brick:Location` but rooms are `rec:Room`;
  - `ba:Field_Network` doesn't list its members with `rec:includes`.
- **W3 many sources.** Facts are proposed until one of these happens:
  - 2 sources agree;
  - a calibrated score reaches 0.9;
  - a person confirms.

  Troop D has 28 unit→room conflicts held for review.
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
  writing the prompt. On the real dev sets the rules find no candidates yet, because their headings name no equipment
  family.
- **W7 binding.** Its scenarios are synthetic renamings of Troop D, so the calibration check is weak. Two known issues:
  - 2 wrong auto-binds when the BMS drops objects;
  - `unit:CHWPLANT` is a system and fails Brick's Equipment shape.
- **W10 learning loop.** Measured on Alpha. On guided-setup projects it is unit-tested only. It runs on demand, not
  after each review batch.
- **W11 agent.** No live BMS values, so "runs as designed" in operation is always "unknown". Argon sometimes stalls past
  120 s.
- **W9 graphics.** Filled in when its PR merges.
- **W12 tool adapters.** Waits for Niagara and CPO Studio access.

## 5. Decisions waiting for you (plan §8)

1. **Budget per building (§8.4).** W6 and W8 pass accuracy and calibration, and fail only the provisional $1 per 1,000
   items. That's about $0.15–0.20 per building each. W7 passes at $0.13 per 1,000. Set `PM_BUDGET_USD_PER_1000` or
   give a per-building figure.
2. **Auto-accept on agreement (§8.5).** It's on today. `PM_AUTO_AGREE=0` turns it off.
3. **A real submittal + BMS pair (§8.2).** Every binding and point-class number rests on Troop D's synthetic submittal
   and BMS export.
4. **Second keys.** A person, rather than the agent that built the reader, should key one more building for plans and
   sequences.
5. **The two knowledge-model fixes** from W2's findings (§4, W1).
