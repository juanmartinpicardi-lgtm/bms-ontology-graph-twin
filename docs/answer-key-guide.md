# Answer key guide: write the answers the AI readers are judged by

For the engineer who has 1 to 2 hours. No coding.

## Why this matters

The app has two AI readers: one reads floor plans (which tag sits in, or serves, which room), the other reads the
sequences of operation (which point controls which). To say how good they are, someone writes the right answers first,
and the reader is scored against them.

Today the AI agent that built each reader also wrote its answers. That makes the scores promising, but not proven.
**You write the answers instead, on a fixed sample.** The scores then report both: against your answers, and against the
agent's, and how often the two agree.

## What you need

- About **1 hour 40 minutes** in all. You can stop and resume at any time. The page keeps what you saved.
- **Online, nothing to install:** open https://bms-ontology-graph-twin.streamlit.app/answer-keys. The online copy
  forgets saved answers whenever it restarts (every update to the app restarts it), so:
  - at the end of each sitting, open **Your key file** and press **Download the key file**;
  - to carry on, upload that file in the same box: your answers come back, and where an item was saved in both
    places, the later save wins.
- **Or on your own computer**, where saves stay on disk. The drawings are not in git: the page fetches the public bid
  set when you press **Get the drawings** (or run `.venv/bin/python scripts/run_real_sets.py --fetch`). `troop_d`'s
  sequences come with the repo. Start the app:

  ```bash
  .venv/bin/python -m streamlit run src/projectmodel/app/main.py --server.port 8521
  ```

  Open **Overview → Answer keys**.

## The sample (fixed, so everyone does the same items)

| Set | Job | Items | About |
|---|---|---|---|
| `msu_mbb` (Montana State University lab renovation) | Plan sheets M201–M203 | 17 of 44 (sheet, tag) pairs | 25 min |
| `itd_d1_lab` (Idaho DOT testing laboratory) | Plan sheets M1.0–M2.0 | 21 of 89 (sheet, tag) pairs | 31 min |
| `troop_d` (Troop D, sheet M-304) | Sequences | 17 of 30 sections | 45 min |

The items were picked by a fixed seed from what the documents contain, not from any answer key, so they are not the ones
the agent found easy. The page shows a progress bar and a time left. After four items, the estimate follows your own pace.
Do the sets in any order. If you only have an hour, do `troop_d` and one plan set.

`liberty_boe` is not offered, and must not be used. It is held out for the final test.

## How the page works

1. Pick the **job** and the **set**. Type your name (it is saved in the file).
2. The page opens the first item that is not done. Pick any other from the **Item** list: ⬜ not started, ✏️ draft,
   ✅ done.
3. Answer from the **source** shown beside the form. For plans, it's the sheet image with the tag outlined in red;
   use *Wider* or *Whole sheet* to see the rest. For sequences, it's the section text; open *Show the section on
   the drawing* if the text is unclear.
4. **Save draft** keeps it for later. **Mark done** keeps it and counts it. **Next item** moves on.
5. Save often, since only saved time is counted. An hour away counts as ten minutes.

**Blind.** The page never shows the AI's answer or the agent's key while you work. After an item is *done* you may press
**Show the reader's answer** to compare. That is recorded in the file (`revealed: true`), and the item is locked, so your
answer stays your own. Use it sparingly: the more items you answer blind, the more the key is worth. If you change an
answer after looking, tick *Change my answer anyway*; it is marked *edited after reveal*.

Your answers are written to new files, and the agent's keys are never touched:

- `data/ground_truth/<set>/plans.human.yaml`
- `data/ground_truth/<set>/sequences.human.yaml`

When you finish, commit them, or download them from **Your key file** and send them back (the only way online).

## Plan sheets: what to mark

For each (sheet, tag), answer *What is it on this sheet?*

| Choice | Use it when |
|---|---|
| **A unit here** | The tag is a unit, drawn in a room. Pick the **floor** of the view it is drawn in, and the **room(s)** it serves or sits in. Say whether it *serves* the room (a terminal unit controlled from that room's thermostat) or *sits in* it. |
| **A unit here, in no room** | On the roof or outdoors (a rooftop unit, a condenser). The floor is RF. |
| **Not a unit on this sheet** | The tag is only a callout, a note, a reference to another sheet, or something that isn't equipment. |
| **I can't tell** | The documents don't settle it. It is left out of the scoring, which is better than a guess. |

Use the plan, and the schedules if the plan doesn't say which room a unit serves. If the answer came from a different sheet
(a schedule, an enlarged view), change **Source page**.

**Edge cases**

- **A unit between two rooms** (a fan coil serving a lab and the office next to it): pick both. Either one counts as right
  for the reader.
- **A tag on two sheets** (an air handler drawn on the plan and on the roof plan, or on two levels): mark it **A unit
  here** on the sheet where the unit itself is drawn. On the other sheets mark **Not a unit on this sheet**, and say
  where it is in the note. Don't answer "a unit here" on two sheets; the first one wins.
- **A tag drawn more than once on a sheet** (a unit label and a thermostat callout): the *Where on the sheet* list
  switches between the occurrences. The unit label is the one that counts.
- **A room with no label** (or a number the list doesn't have): type the number in the room box (it accepts new
  entries). If the room has no number at all, use the note and pick **I can't tell**.
- **A tag the list doesn't have:** use *A tag the list doesn't have*, below the form. It is scored like the others, and
  doesn't count towards the progress bar.
- **A sheet with two views** (a roof plan above a level 3 mechanical room): the floor is the one of the view the tag is
  in.

## Sequences: what to mark

Each item is one **section** (a lettered step such as "E. Supply fan control"). Read the text, then add every control
relation it **states**, one row each:

| Relation | Means | Example |
|---|---|---|
| **drives** | a setpoint drives an output (a loop) | duct static pressure setpoint → supply fan speed |
| **feedback** | a measurement feeds back to the same output | duct static pressure → supply fan speed |
| **requires** | the first is a condition the second needs (interlock, enable, lockout, safety) | freezestat → supply fan start/stop |
| **requests** | a point asks equipment to run (the end is the equipment, `unit:…`) | chilled water valve → `unit:CWP` |
| **resets** | the first moves the second's setpoint | outdoor air temperature → supply air setpoint |
| **switches** | a mode or schedule changes the second's operation | occupied schedule → supply fan start/stop |

Pick the points from the lists (type to search). They are the points of the units the sequence applies to, with their
descriptions. For a loop, add the *drives* row and the *feedback* row with the same **loop name**, so they pair up.

**Edge cases**

- **A section with no relation** (a heading, a list of schedules, a definition): tick *This section states no control
  relation*, then **Mark done**. It still counts: it tells the score the reader shouldn't have found anything there.
- **The text says something no point is there for** (a setpoint the units don't have): add what you can, and write
  the missing thing in *Gaps*, one per line.
- **Many points do the same job** (nine supply fan statuses): one relation is enough; pick one of them.
- **Stated loosely or only implied:** leave it out. Mark what the text says, not what a good design would do.
- **A point the list doesn't have:** type its name in the box (it accepts new entries). It is kept, but the reader can't
  match it, so use this only if the text clearly names something.
- **The same text in two sequences** (the VAV and the fan-powered VAV boxes): answer each as it appears. The sample
  has some sections of both.

## What it does to the scores

`scripts/eval.py plan_meaning` and `scripts/eval.py sequence_read` read your files if they exist. Nothing changes when
there are none: the output is as before.

With a key file, on the items you answered:

- **Your answers replace the agent's** in the score (the headline), so the reader is judged by you where you answered
  and by the agent's key elsewhere.
- Each row then adds a *human key* block: the reader **vs the human key**, the same answers **vs the agent key** on the
  same items, and **how often the two keys agree**. A low agreement means the agent key can't be trusted yet. That is
  worth knowing more than the reader's own score.
- Plans are scored on tag placements only (a floor and a room, or none). Room labels stay on the agent key, since you
  don't mark every room on a sheet.
- Sequences are scored on the sections you answered. A reader relation with no section can't be attributed, and is
  counted separately.

## Afterwards

Run the scores, tell the team what the agreement was, and commit the `*.human.yaml` files. The fixed sample is in
`data/ground_truth/answer_key_sample.yaml`: don't remake it, or the saved answers no longer line up (see
`scripts/answer_key_sample.py`).
