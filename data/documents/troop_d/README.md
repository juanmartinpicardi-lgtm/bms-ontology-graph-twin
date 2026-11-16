# Troop D Crime Lab: synthetic submittal test set

A complete test package for the submittals workflow (`docs/spec-submittals-workflow.md`). Use it for every
step, from dropping the documents in to reviewing the graph.

No public project comes with the controls contractor's submittal and the BMS database
(see `docs/reference/submittal-test-sets.md`). This set takes a real public design set and adds those two
documents. They are written the way a controls contractor would write them, and the answer key is generated
in the same run, so every fact is known exactly.

## What is real and what is invented

| Item | Real (public bid set R2517-01) | Invented here |
|---|---|---|
| Building, floors, rooms (87 spaces) | Plans M-101 to M-104 | |
| Equipment and capacities (AHU01, 2 chillers, 2 pumps, 56 VAV boxes, exhaust fans, mini-splits, unit heaters) | Schedules M-401, AHU detail M-303 | |
| Sequences of operation | M-304 | Restated with point names in the submittal |
| Which room each box serves | Thermostat location on the plans; 12 placed with medium confidence | |
| Design conflicts (DI-1 to DI-4) | Found in the set | Raised as RFIs in the submittal |
| Contractor, controllers, MS/TP network, addresses, device instances | | All |
| Point lists, Metasys names, BACnet objects | | All |
| BMS names differing from drawing tags (VAVE07 vs VAVE-07, CH01a vs CH-1A) | | On purpose, to test the merge step |

The contractor "Ozark Valley Controls" is fictitious. Every page of the submittal says it is a synthetic test document.

## Files

| File | What it is | Workflow input? |
|---|---|---|
| `../../raw/troop_d/R2517-01_Final_Bid_Plans.pdf` | Design drawings (27 sheets) | yes |
| `../../raw/troop_d/R2517-01_Final_Bid_Specs.pdf` | Project manual | yes |
| `submittal_230900_controls.pdf` | Controls submittal, 24 pages: riser, point schedules, sequences, BOM, room, valve and damper schedules, RFIs | yes |
| `bms_export.csv` | Metasys-style object export, 847 objects | yes |
| `building.yaml` | Source of truth, with a sheet cited for each fact | no: the generator's input |
| `../../ground_truth/troop_d/*.csv` | Answer key: spaces, equipment, points, relations, issues | no: scoring only |

Never give `building.yaml` or the answer key to the pipeline.

## Rebuild

```bash
uv run python scripts/build_troop_d.py
```

The output is deterministic. Change `building.yaml` or `src/projectmodel/troop_d.py`, then rebuild.
