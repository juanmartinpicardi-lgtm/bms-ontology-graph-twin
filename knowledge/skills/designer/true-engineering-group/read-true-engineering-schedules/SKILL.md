---
name: read-true-engineering-schedules
description: Read the equipment schedules drawn by True Engineering Group (M-4xx sheets) - fan powered and VAV terminals, chillers, pumps, mini-splits, unit heaters, air handling units - with the firm's column layouts.
version: 1
metadata:
  projectmodel:
    scope: designer/true-engineering-group
    applies_to: {step: schedules, sheet_titles: ["SCHEDULE"]}
    rules: [rules/layouts.yaml]
    status: active
    locked: false
    method: import
    approved_by: project-model-team
    evidence: ["src/projectmodel/intake/schedules.py"]
---
# Read True Engineering Group schedules

## When to use

The guided setup's schedules step, on a design set whose title block names True Engineering Group as the designer.

## Procedure

1. A schedule row is a line that starts with an equipment tag. Its schedule is the nearest "... SCHEDULE" title
   above it whose columns it sits under.
2. Choose the layout in `rules/layouts.yaml` whose title words appear in the schedule's title, and read the cells
   after the tag in that column order. "-" is an empty cell.
3. The class comes from the tag, refined by the row: a VAVE with heater kW is electric reheat.
4. Check: tags on the plans with no schedule row, rows with no tag on the plans, values that contradict each other.
5. A row in a schedule with no layout keeps its raw values and is asked about.

## Pitfalls

- Two-word makes (BELL & GOSSETT, AMERICAN WHEATLEY) shift every column after them if read as one word.
- The air handling schedule spans supply, exhaust, preheat, cooling and humidifier groups in one row.

## Verification

Troop D's schedule rows and values score as before against the answer key (`intake/score.py`).
