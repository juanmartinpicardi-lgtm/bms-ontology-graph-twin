# Real document sets for the guided setup

Package W0 of `docs/plan-workflow-ai.md` asks for "3 more real document sets, one held out", so the guided setup's
readers (rules today, the AI readers of W6 and W8 later) are measured on buildings the rules have never seen. Troop D
stays the worked example. These three are the yardstick.

Files, sources and sha256: `data/raw/SOURCES.md`. Run: `scripts/run_real_sets.py` (results in
`reports/real_sets.json`). Collected 23 Nov 2026.

| Set | Building | Owner (public record) | Designer | Region | Role |
|---|---|---|---|---|---|
| `msu_mbb` | Molecular Bioscience Building, lab and office renovation, phase 2 | Montana State University | Bechtle Architects; SE Engineers (mech.) | Mountain West (Bozeman, MT) | **dev** |
| `itd_d1_lab` | District 1 Testing Laboratory, new building | Idaho Transportation Department | Miller Stauffer Architects; Musgrove Engineering (mech.) | Inland Northwest (Coeur d'Alene, ID) | **dev** |
| `liberty_boe` | Board of Education building, HVAC replacement | Liberty County School System | Method Engineering Group (mech.) | Southeast (Hinesville, GA) | **held out** |

## Held-out set: `liberty_boe`

The Liberty County set is the held-out test set (also written in `CLAUDE.md` §5).

- Never tune rules, prompts, conventions or page-sorting on it.
- When choosing fixes, never look at its results in detail: no questions, issues or facts. `run_real_sets.py` writes
  only headline counts for it, and the table below shows only those.
- Run it to report a number: before and after a reader change, or when a W6/W8 reader is scored.
- If it ever leaks into tuning, say so in this file. Then pick a new held-out set; don't keep calling this one held out.

Why this one: it is the most "ordinary" building (RTUs, VAV boxes, ductless splits, three office floors), so it
measures what the readers should handle routinely. It is also from a different region, firm and drawing style than
both dev sets. The two dev sets carry the unusual layouts (floor-dotted tags, two-line hexagon tags, Title Case
rooms, a lab exhaust system) that the readers have to learn from.

## What none of the sets has

- **No contractor controls submittal and no BMS export.** None was found as public record for any of the three. Bid
  sets are published before a controls contractor exists, and submittals and point exports are not posted afterwards.
  Each set has a **design points list on the drawings** instead (MSU M.502, ITD M6.2–M6.3, Liberty M301). The runs
  give those sheets to the submittal step as the closest stand-in. They are not a submittal: no riser, no addresses,
  no object instances. The BMS step gets nothing.
- **No scanned sheet set.** All three are vector PDFs with a text layer. Troop D's "scanned" stress scenario remains
  the only scan test.
- **No answer key.** The counts under "What a person would expect" are approximate hand counts. I read the sheets
  with a regex pass over the text layer, then checked against the rendered sheets. They are not a ground truth.

## Candidates seen but not used

- Vermillion County Jail addition and renovation, Indiana (2021). A good mechanical set with alphanumeric rooms
  (`C106`), floor tags `VAV-1-1` and point lists M901–M906. It was not used because it is hosted on a construction
  manager's free bid site, not on the public owner's own site, and it is another justice building like Troop D. It is
  the first choice for a fourth set:
  `https://www.hannigbidding.com/download.php?pid=75&type=Drawings&name=Mechanical_Vermillion_County-Bid_Set_Construction_Documents_Drawings-3.pdf`.
- Delaware OMB / school district sets on `bidcondocs.delaware.gov`. The site rejects automated downloads.
- Other Missouri OA sets. Same agency and procurement format as Troop D, so less variety.

---

## Profile: `msu_mbb` (dev)

Montana State University, Molecular Bioscience Building renovations and maintenance, phase 2 (PPA 22-0045). Bid set
dated 12/12/25, bid 10 Sep 2026. A partial renovation of an occupied lab building. Most HVAC equipment is existing
`(E)`; new fan coils, a new chiller and boilers, and new pumps are added.

**Files.** `22-0045 Plans.pdf` (78 sheets, all disciplines), the project manual (603 pages), and addenda 1–3. Page
numbers below are pages of `22-0045 Plans.pdf`.

| Role | Pages | Sheets |
|---|---|---|
| Floor plans (HVAC) | 22, 23, 24 | M.201 Level 1, M.202 Level 2, M.203 Level 3 & roof |
| Demolition plans | 17, 18, 19 | M001–M003 |
| Schedules | 20, 21 | M.101 legend, notes and fan coil schedule; M.102 schedules |
| Piping / flow diagrams | 25–28, 29 | M.301–M.304 piping plans; M.401 flow diagrams |
| Controls | 30 | M.501 controls (diagrams) |
| Sequences + points list | 31 | M.502 control legend, sequence of operations, control system points list |
| Spec | project manual | Division 23 from page 244. **No 23 09 xx section** (23 09 93 is only referenced). |

**What differs from Troop D**

- *Titles.* The title block is vertical on the right edge. The project name is rotated. The sheet title is very
  small ("LEVEL 2 - HVAC PLANS"). The view title is mixed case ("Level 2 - HVAC PLAN"). The sheet index says
  `M.201`; the title block says `M202`.
- *Rooms.* Three digits, with the number below the name (`OFFICE` / `222`). The names are drawn in light grey
  (background architecture). Only the renovated wings are labelled, not whole floors.
- *Tags.* Floor-dotted numbers: `FC-1.16`, `FC-2.14`, `CHWP-1.1`, `GWP-1.2`. Many tags carry an `(E)` prefix for
  existing equipment, and keynote hexagons sit next to them.
- *Schedules.* The key column is `PLAN CODE`, not `TAG`/`MARK`. Fan coils appear twice: in the M.101 fan coil
  schedule and in an "Existing ERV unit balancing schedule" grouped by `(E) ERV-3` / `(E) ERV-2`. That second
  schedule gives each fan coil's room served, which is a schedule-to-room link Troop D does not have.
  The split system is a transposed schedule (rows are attributes, columns are units).
- *Sequences.* One drawing sheet. It covers plant only: `1.1 CHILLED WATER PLANT CONTROL SEQUENCE`,
  `1.2 HEATING HOT WATER PLANT CONTROL SEQUENCE`, with lettered parts (`C. BOILER SEQUENCE:`). There is no fan coil,
  ERV or DOAS sequence anywhere in the set.
- *Points list.* A matrix on M.502 (point name × DI/AI/BO/AO/…). Fan coils are a typical: "FAN COIL UNITS (15 NEW
  UNITS)".

**What a person would expect** (approximate hand count)

- Floors: 3 plus roof. Rooms in the renovated areas: about 12 on level 1 (150–163), about 24 on level 2 (218–241),
  and about 3 on level 3 (302 mechanical, 303–304). The rest of the building is not labelled.
- Equipment:

  | Type | Count | Tags |
  |---|---|---|
  | Fan coil units | about 55 scheduled; 21 on the HVAC plans | FC-1.1–1.26, FC-2.1–2.28, FC-3.1; points list says 15 new |
  | Chiller, air cooled | 1 | CH-1 |
  | Hot water boilers | 2 new + 1 existing | B-2, B-3 new; B-1 existing |
  | Pumps | about 10 | GWP-1.1/1.2, CHWP-1.1/1.2/2.1/2.2, BP-2/3, HWP-1/2 |
  | ERVs | 3, existing | ERV-1–3 |
  | DOAS | 1 | DOAS-1 |
  | Makeup air units | 3 | MAU-1–3 |
  | Other | | AC-1; split systems SS-1/SS-2; air separators AS-1/2; expansion tanks ET-1/2; glycol feed GF-1 |

- Sequences: 2 plant sequences (chilled water, heating hot water). None for the terminal units.

## Profile: `itd_d1_lab` (dev)

Idaho Transportation Department, District 1 Testing Laboratory (project D231130, phase 2), new single-storey materials
testing lab. Bid set 5/13/2024. Only the mechanical, plumbing and sprinkler volume is available (29 sheets). The
architectural and electrical volumes are no longer posted.

| Role | Pages | Sheets |
|---|---|---|
| Floor plans (HVAC) | 3, 4, 5, 6 | M1.0 HVAC floor plan, M1.1 exhaust, M1.2 hydronic, M2.0 roof |
| Enlarged plan | 7 | M3.0 enlarged mechanical room |
| Schedules | 12–15 | M5.0–M5.3 mechanical schedules (M5.3 = air handling unit) |
| Controls, sequences, points lists | 16–21 | M6.0–M6.5 mechanical controls |
| Other | 1, 2, 8–11, 22–29 | M0.0 cover/legend, M0.1 COMcheck, M4.x details, plumbing, sprinkler |

**What differs from Troop D**

- *Titles.* Sheet numbers are decimal (`M1.0`, `M5.2`). The title block is a right-hand strip, with the sheet title
  rotated ("HVAC FLOOR PLAN"). There is **no floor name in any title**: a one-storey building has just "HVAC PLAN".
- *Rooms.* Names are in **Title Case** ("Residency Lab", "Asphalt Lab", "Nucular Gauge Storage"). They sit above
  a three-digit number (101–135).
- *Tags.* On the plans, tags are **two-line hexagons**: the type is written over the number (`SAV` / `8`,
  `HC` / `3`, `EH` / `1`), with no dash. On the roof plan and the schedules, tags have no dash at all (`AHU1`,
  `LEF1`, `EF5`); on the schedules they appear as `SAV-1`.
- *Equipment kinds.* A lab exhaust system, new to the knowledge model: pressure-independent supply valves (SAV),
  general exhaust valves (GEV), snorkel exhaust valves (SEV), reheat coils (HC), canopy hoods, snorkels and a lab
  exhaust fan. The supply valves and reheat coils come in pairs per zone, not as VAV boxes.
- *Schedules.* About 21 small schedules on four sheets. One is the "Lab Equipment List" on the floor plan sheet,
  which is not HVAC.
- *Sequences.* Headings end in "SEQUENCE OF OPERATION" ("LAB EXHAUST SYSTEM SEQUENCE OF OPERATION"). They are not
  lettered sections; sub-modes end with a colon ("COOLING MODE OF OPERATION :", "UNOCCUPIED MODE:"). Points lists are
  embedded ("BOILER POINTS LIST :", "VFD POINTS LIST :").

**What a person would expect** (approximate hand count)

- Floors: 1, plus roof equipment and a mechanical room. Rooms: about 27 (101–135).
- Equipment:

  | Type | Count | Tags |
  |---|---|---|
  | Air handling unit | 1 | AHU-1 |
  | Lab exhaust fan | 1 | LEF-1 |
  | Exhaust fans | 7 | EF-1–6 in the schedule; EF-7 only in the louver schedule and controls |
  | Supply air valves | 9 | SAV-1–9 |
  | General exhaust valves | 7 | GEV-1–7 |
  | Snorkel exhaust valves | 5 | SEV-1–5 |
  | Hot water reheat coils | 9 | HC-1–9 |
  | Electric heaters | 9 | EH-1–9 |
  | Boilers | 2 | B-1, B-2 |
  | Pumps | 4 | BP-1/2, HWP-1/2 |
  | Humidifier | 1 | HUM-1 |
  | Ductless split | 1 | DFC-1 / DCU-1 |
  | Other | | furnace F-1; canopy hoods CH-1–4; snorkels SN-1–5 |

- Sequences: about 6 systems. They are the ductless split, the lab exhaust, the heating water, the AHU, lab
  ventilation with multiple hoods, and lab ventilation with general exhaust.

## Profile: `liberty_boe` (held out)

Liberty County School System, Board of Education building HVAC replacement (RFP 2026-07). Construction documents
12/05/2025. The scope is two new VAV rooftop units, new controllers on the existing VAV boxes, and ductless heat pumps
for data rooms. The set is 18 sheets. This profile describes the documents only. It does not describe how the readers
did on them.

| Role | Pages | Sheets |
|---|---|---|
| Floor plans (HVAC) | 8, 9, 10, 11 | M201–M203 levels 1–3, M204 roof |
| Demolition plans | 4–7 | M101–M104 |
| Schedules | 3 | M001 HVAC schedules |
| Controls diagram + points list | 12 | M301 |
| Sequences | 13 | M302 sequences of operations & HVAC details |
| Other | 1, 2, 14–18 | G000 cover, M000 title, electrical |

**What differs from Troop D**: there are rooms with letter suffixes (`216B`, `219A`, `000` for chases). VAV tags
have three parts, `(E)VAV1-2-5`: the rooftop unit, the floor, then the number. Schedules use `UNIT ID`, and the VAV
schedule is marked "for reference". The sequences are on a drawing, under colon-ended mode headings ("OCCUPIED:",
"UNOCCUPIED OVERRIDE:"). The title block is a right strip with large sheet titles ("LEVEL 2 HVAC PLAN").

**What a person would expect** (approximate hand count): 3 floors plus roof; about 45 rooms on level 1 and about
60 each on levels 2 and 3, closets included. Equipment: 2 RTUs (RTU-1, RTU-2), about 85 existing VAV boxes, and 5
ductless heat pumps, each an indoor DAH with an outdoor DHP. Sequences: 2, the VAV rooftop unit and the VAV terminal
unit. The ductless heat pumps have none.

---

## Results: the current readers, unchanged

Run on 23 Nov 2026 at `main` 1055ae5. The readers were not changed, the models were off (`PM_AI=off`), and no
answers were given. Full output, including every coverage issue, question and reader log for the dev sets:
`reports/real_sets.json`.

Each set was run twice:
- **sheets**: the pages a person would pick for each step, as listed in the profiles above;
- **whole set**: the entire drawing PDF uploaded at steps 1–3.

The submittal step got the design points-list sheets. Both dev sets have them, but neither is a submittal.

### Dev sets: what was read against what a person would expect

| Step | `msu_mbb` (sheets) | `itd_d1_lab` (sheets) |
|---|---|---|
| 1 Floor plans | **0 rooms** of ~39. Levels 1 and 2 skipped: "no floor named in the title". M.203 read as Roof only. 1 coverage issue (Roof: no room labels). | **28 rooms** of ~27, all placed on floor "RF" (roof). 25 questions "Room 101 … has no name next to it": the Title Case names above the number are not taken as names. 1 equipment tag of ~60 (the two-line hexagon tags are not read). |
| 2 Schedules | **4 units** of ~80: CH-1, B-1 to B-3. All 55 fan coils, the pumps, ERVs, DOAS and MAUs are missed (`PLAN CODE` column). 3 questions. No coverage issue. | **16 units** of ~70: AHU-1, B-1/2, HWP-1/2, EF-1 to 7, and **CH-1 to 4 classified as chillers (they are canopy hoods)**. Then "chilled water from 2 pumps through 4 chillers to the AHU coil" is proposed: the building has no chilled water. SAV, GEV, SEV, HC, EH and HUM are missed. 16 questions. |
| 3 Sequences | **1 "sequence" named 'Note'** (8 sections, 10 setpoints, applies to 0 units). The two real plant sequences (`1.1 …`, `1.2 …`) are not found. No coverage issue. | **0 sequences** of ~6. A coverage issue was raised correctly: "no system heading like 'AIR HANDLING UNIT:' with sections A., B., C." |
| 4 Submittal (points-list sheets) | 0 points, 2 coverage issues (no point rows, no riser). | 0 points, 2 coverage issues. |
| 5 BMS | not run (no export) | not run (no export) |
| Headline | 1 floor, 0 rooms, 4 equipment, 1 sequence, 0 points; 3 coverage issues, 7 questions | 1 floor, 28 rooms, 16 equipment, 0 sequences, 0 points; 3 coverage issues, 44 questions |

The whole drawing set uploaded at steps 1–3:

| | `msu_mbb` (78 sheets) | `itd_d1_lab` (29 sheets) |
|---|---|---|
| Plans | Floors L1, L2, RF taken from other disciplines' sheets. 1 room, and it is wrong: "001 E". | Same 28 rooms; 1 more coverage issue |
| Schedules | 6 units. Adds **CH-21 and CH-23, read as chillers**, from non-mechanical sheets. | Same 16 |
| Sequences | Same 'Note' | 2 false sequences, 'Note' and 'Typical Insulation Thickness Required To Meet These Requirements', with missing-section warnings; no coverage issue now |
| Time | **1,088 s** (18 min) | 49 s |

### Held-out set: headline counts only

| `liberty_boe` | floors | rooms | equipment | sequences | points | coverage issues | questions |
|---|---|---|---|---|---|---|---|
| sheets | 3 | 185 | 2 | 0 | 0 | 3 | 26 |
| whole set | 3 | 186 | 3 | 0 | 0 | 4 | 29 |

Expected (hand count, approximate): 3 floors, about 165 rooms, about 92 equipment, 2 sequences.

### What this says about the rules (dev sets only)

1. **No step was silent in the strict sense.** Every step either read something or asked something
   (`silent_steps` is empty everywhere). The W0 guardrail holds as written.
2. **But partial reads are quiet, and they are the common failure on real sets.** No coverage issue is raised when:
   - 2 of 3 plan pages are skipped (MSU);
   - 4 of ~80 scheduled units are read (MSU);
   - the only "sequence" found is a note block (MSU).

   A coverage check that compares against what the document itself announces would catch all three: the sheet
   index lists HVAC plans for 3 levels, the schedule titles list 12 schedules, the sheet title says "SEQUENCE OF
   OPERATIONS".
3. **Wrong facts, not only missing ones.** These matter more than the misses, because they look like answers:
   - canopy hoods `CH-n` typed as chillers, which then produce an invented chilled-water chain to the AHU (ITD);
   - `CH-21` and `CH-23` found on other disciplines' sheets (MSU, whole set);
   - all ITD rooms placed on the roof;
   - "sequences" built from note blocks.

   The tag prefix → class table needs context: what the schedule title says ("CANOPY HOOD SCHEDULE").
4. **Layout gaps, by step:**
   - plans: floor names that are only in mixed-case view titles; a one-storey building with no floor name; Title
     Case room names; two-line hexagon tags;
   - schedules: the `PLAN CODE` key column, transposed schedules, and many small schedules on one sheet;
   - sequences: numbered headings (`1.1 … CONTROL SEQUENCE`) and "… SEQUENCE OF OPERATION" titles with
     colon-ended modes;
   - points: design point matrices.

   These are the W6/W8 targets. They are the same kinds of variation the Troop D stress suite simulates, now seen
   in real sheets.
5. **Whole-set upload is slow and noisy.** 18 minutes for MSU's 78 sheets, and it added false facts without adding
   true ones. Page sorting (W6) should come before any reader sees a whole set.

Next: fixes chosen from the two dev sets only. Then re-run `scripts/run_real_sets.py` and compare the held-out
headline row with the one above.
