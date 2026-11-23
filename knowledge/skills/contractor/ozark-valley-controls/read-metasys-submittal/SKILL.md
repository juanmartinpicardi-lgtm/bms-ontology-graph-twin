---
name: read-metasys-submittal
description: Read a controls contractor's Metasys submittal - riser, point schedules with NAE/FC references, room schedule and RFIs - into controllers, points and links to scheduled equipment.
version: 1
metadata:
  projectmodel:
    scope: contractor/ozark-valley-controls
    applies_to: {step: submittal, sheet_titles: ["POINT SCHEDULE", "RISER", "ROOM SCHEDULE"]}
    status: active
    locked: false
    method: human
    approved_by: project-model-team
    evidence: ["src/projectmodel/intake/submittal.py"]
---
# Read a Metasys controls submittal

## When to use

The guided setup's submittal step, for a project whose contractor writes Metasys submittals (references of the form
NAE/FC-n.DEVICE.POINT).

## Procedure

1. **Riser.** Rows of address, device, controller, device instance and location, under an "FC-n" trunk heading.
2. **Points.** Each point row ends with a Metasys reference. A reference with FC-x is a typical: apply it to every
   device of the same tag prefix on the riser.
3. **Equipment.** Link a device to scheduled equipment when the tags are the same tag (VAVE-07 = VAVE07). A device
   that matches nothing is asked about, with the nearest candidates.
4. **Classes.** A point's class comes from its description, through the knowledge model's name rules (the same
   matcher the BMS mapper uses).
5. **Rooms.** Room schedule rows (floor, room, box, AHU, FC:address): where the floor plans placed the same box in
   the same room, the room is confirmed; where they differ, ask.
6. **RFIs.** Keep each RFI and clarification as an issue with its page.

## Pitfalls

- The contractor's device names differ from drawing tags on purpose (hyphens, case, suffix letters).
- The submittal states what is to be installed, not what is; the BMS export is the stronger evidence.

## Verification

Every riser device is linked or asked about; every typical is expanded; the room schedule agrees with the plans or
raises a question per difference.
