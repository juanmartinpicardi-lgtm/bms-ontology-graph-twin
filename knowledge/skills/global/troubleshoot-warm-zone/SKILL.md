---
name: troubleshoot-warm-zone
description: Find why a zone is too warm (or too cold) by walking the chain that serves it - zone, terminal unit, air handler, chilled or hot water plant, machines - and say which link to check first on site.
version: 1
metadata:
  projectmodel:
    scope: global
    applies_to: {agent: true, levels: [room, equipment, point]}
    status: active
    locked: false
    method: human
    approved_by: project-model-team
    evidence: ["src/projectmodel/agent_tour.py"]
---
# Troubleshoot a warm zone

## When to use

A person asks why a space, zone or terminal unit is too warm or too cold, or cannot reach its setpoint, or a
simulated scenario pushes a zone out of range.

## Procedure

1. **Zone.** Find the zone's temperature sensor and setpoints (`find_nodes`, then `describe` on the terminal unit).
   Note the cooling and heating setpoints and whether an occupied/unoccupied mode applies.
2. **Terminal unit.** `describe` the VAV (or FCU): damper command and position, airflow and its setpoints, reheat
   valve or electric heat. Missing required points are themselves a finding.
3. **Air handler.** `upstream` from the terminal unit with medium `air`: the AHU that feeds it. `describe` it:
   discharge air temperature and setpoint, cooling valve, supply fan status and speed, static pressure.
4. **Plant.** `upstream` from the AHU with medium `chilled_water` (or `hot_water` for a cold zone): the plant, then
   its chillers or boilers and pumps. Check supply water temperature against its setpoint and the plant's enable.
5. **Sequences.** `behaviour` on each link: the control loops, resets and requests the sequences of operation
   state. A zone request that should reset the AHU discharge air setpoint, or a trim-and-respond on the plant,
   explains a lot of "warm everywhere" cases.
6. **Answer.** Lead with the most likely link, then the chain as a short list, each step cited with its trust word.
   End with what to check on site, cheapest first (setpoint and override, sensor, damper, valve, plant).

## Pitfalls

- The graph says how things are connected and what the sequences intend; it does not hold live values. Never say a
  damper *is* closed; say what to check.
- A `feeds` link the mapper inferred (trust *likely* or *unsure*) may be wrong: say so when the answer rests on it.
- One warm zone points at the zone or its box; every zone on an AHU warm points at the AHU or the plant.
- Design documents state intent (*stated*); the submittal and BMS state what is installed.

## Verification

Every step of the chain is cited to a node id from a tool result, and the missing links (no AHU found, no plant
found, no sequence) are named rather than guessed.
