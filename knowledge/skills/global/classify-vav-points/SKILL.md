---
name: classify-vav-points
description: Classify the points of a VAV terminal unit into Brick classes from their names and the VAV template slots, and decide which go to review.
version: 1
metadata:
  projectmodel:
    scope: global
    applies_to: {step: mapper, equipment_class: VAV}
    status: active
    locked: false
    method: human
    approved_by: project-model-team
    evidence: ["knowledge_model/templates", "src/projectmodel/mapper/pipeline.py"]
---
# Classify VAV points

## When to use

Points grouped on a VAV (or a fan-powered or reheat box) whose class the name rules left unsure, in the mapper or in
review.

## Procedure

1. Read the name as tokens with the abbreviation dictionary (ZN-T, DA-T, SA-F, DMPR, HTG, CLG, SP, CMD, POS...).
2. Get the function first: sensor, setpoint, command, status, alarm. A setpoint is never a sensor.
3. Then the quantity and medium: temperature, airflow, pressure, position; zone air, discharge air, supply air.
4. Fill the VAV template's slots: zone temperature, zone setpoints (occupied/unoccupied, heating/cooling), airflow
   and its setpoint, damper command and position, reheat valve or electric heat command, and for fan-powered boxes
   the fan command and status.
5. Pick the most specific class the name supports. When two slots compete (airflow sensor vs airflow setpoint), the
   name's function word decides; with no function word, keep the generic class and send it to review.
6. Below the auto-accept threshold, or not linked to the VAV, the point goes to review.

## Pitfalls

- "Discharge" and "supply" air are often used for the same air at a box; prefer what the template slot expects.
- A box's "SP" can be a setpoint or static pressure; static pressure belongs to the AHU, not the box.
- Do not specialise a reheat point to hot water if the box is electric (VAVE).

## Verification

H2 on the dev set does not drop; the template's required slots are filled or listed as missing.
