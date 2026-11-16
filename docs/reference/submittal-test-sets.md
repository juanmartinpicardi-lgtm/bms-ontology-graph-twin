# Submittal test sets: public packages to run the workflow end to end

Research for `spec-submittals-workflow.md` §7 ("A test building"). Checked 2026-11-16: every file below was
downloaded and its text extracted with `pypdf`; sheet lists and tag counts come from those files, not from search snippets.

## Summary

No public building has all three of: a controls submittal, design drawings with floor plans, and a BMS
export. The two best sets cover the gap from opposite sides:

| | Kelly Walsh High School (WY) | MSHP Troop D Crime Lab (MO) |
|---|---|---|
| What it is | Contractor's **as-built controls submittal** (Johnson Controls, Metasys), from the school's public O&M manual | Engineer's **bid set**: drawings + project manual, from the State of Missouri bid site |
| Floor plans | No (floors only via network risers and the room schedule) | Yes: mechanical plans with VAV tags (M-101…104, M-201…203) |
| Equipment list | Yes: room schedule, valve, damper, air-station schedules, bill of materials | Yes: VAV schedule (M-401), AHU, chiller, pump schedules; spec sections 233616, 237313, 236423 |
| Points list | Yes: point schedule per system with BACnet object names, NAE and trunk addresses (works as a BMS export) | No points list; controls diagrams M-301…303 |
| Sequences | Yes: per system type (chiller, AHU-1/2, 3/4, 5–11, 12, 13, VAV types, snowmelt…) | Yes: sheet M-304 "BAS sequence of operations"; spec 230923 |
| "Serves" links | Yes: VAV → room number and name → AHU, with flows, K-factor, controller, address | On plans (VAV in room), not in a table |
| Size | 13 AHUs, ~150 VAVs + exhaust/fan-terminal variants, chillers, boilers, snowmelt; 233 pages | 1 AHU, 56 boxes (19 VAV, 19 VAVE electric reheat, 18 FVAV fan powered), 2 chillers; 27 sheets + 268-page spec |
| Text layer | Yes (vector PDF) | Yes (vector PDF) |
| Use | Internal testing only (see licence) | Public government record |

Recommendation: use **Kelly Walsh** as the first test building for steps 2, 3, 5, 6 and 7: it is the
closest thing to a real submittal and its point schedule doubles as an answer key. Use **Troop D** for
step 4 (floor plans) and to test the design-set path (schedules + sequences without a points list).

**Update 2026-11-16: Troop D now has a complete package.** No public package was complete, so we built the
missing parts: a synthetic controls submittal (24 pages, Metasys style), a BMS export (847 objects) and an
exact answer key, all generated from the real bid set. With these, Troop D is the default test building for
every step of the workflow. See `data/documents/troop_d/README.md`. To rebuild:
`uv run python scripts/build_troop_d.py`.

## 1. Kelly Walsh High School, Casper, WY (as-built controls submittal)

Natrona County School District posts the building's O&M manual (Oct 2015). The controls part is Johnson
Controls contract 4216-0030, transmitted to KK Mechanical on 2016-02-25.

Files (direct links work; directory listings return 403):

- [230900 – Building Automation System.pdf](https://kellywalsh.org/building_manual/03%20Maintenance%20Data/Division%2023-Mechanical/230900%20-%20Building%20Automation%20System.pdf): 233 pages, 11 MB: transmittal, drawings, schedules and cut sheets in one file
- The same content split in three: [Controls 1](https://kellywalsh.org/building_manual/03%20Maintenance%20Data/Division%2023-Mechanical/From%20Bob/Done/23%2009%2000%20Controls%201.pdf) (transmittal), [Controls 2](https://kellywalsh.org/building_manual/03%20Maintenance%20Data/Division%2023-Mechanical/From%20Bob/Done/23%2009%2000%20Controls%202.pdf) (82 pages: drawings and schedules), [Controls 3](https://kellywalsh.org/building_manual/03%20Maintenance%20Data/Division%2023-Mechanical/From%20Bob/Done/23%2009%2000%20Controls%203.pdf) (150 pages: catalog cut sheets)
- [233600 – Air Terminal Units.pdf](https://kellywalsh.org/building_manual/03%20Maintenance%20Data/Division%2023-Mechanical/233600%20-%20Air%20Terminal%20Units.pdf): Price SDV VAV box manual (8 pages)
- Other O&M sections (boilers, water heaters, terminal heat transfer units) sit in the same folders.

Contents of the controls submittal (from its drawing index, p. 2):

| Sheets | Content | Workflow step |
|---|---|---|
| L-1…L-3 | Legend, NAE and MS/TP installation details | 2 (page types) |
| NR-1…NR-5 | Network riser: overall, basement, lower, main, upper | 4 (controllers per floor), 5 |
| 1-1…1-4 | Chilled water: layout, point schedule, wiring, sequence | 3, 5, 6 |
| 2-1…2-4 | Hot water and domestic hot water boilers | 3, 5 |
| 3-x…7-x | AHU-1/2, 3/4, 5–11, 12, 13: flow layout, point schedule, wiring, sequence (+ return air units) | 3, 5, 6 |
| 8-1…8-22 | VAV types: standard, with exhaust (EF, EFH, EFS), fan terminal, humidifier, science prep with lab exhaust, reheat coils | 3 (templates), 6 |
| 9-x…13-1 | Snowmelt, greenhouse, elevator and boiler exhaust, unit heaters, DAC | 3 (types with no template yet) |
| RS-1…3 | Room schedule: floor, room number and name, VAV tag, AHU, box type, K-factor, inlet size, max/min/heating flows, GPM, controller model, NAE:trunk:address, template | 3, 4, 5 |
| VS-1…4, DS-1, AMSS-1 | Valve, damper and air measuring station schedules (with "serves" text such as "VAV-07-27, Commons F201A") | 3, 5 |

Sample rows, to show the shape:

- Point schedule (p. 20): `AHU1-2-FAC  DA-T  Discharge Air Temperature  FAC 2611  MS/TP 1  UI IN-1  … TE F131`
- Room schedule (p. 75): `C/Lower  C107  Men's PE Lockers  VAV-01-02  AHU-1  SDV5 Price  K 1.94  16"  2185 / 730 / 1460 cfm  6.00 gpm  MS-VMA1615-0  NAE2:T1:A54  VAV Typ`
- Sequence (p. 22): AHU-1/2 supply fan control, "typical of 2", referencing point names (`SFx-C`, `DAx-P`, `DAP-SP`).

What is missing: architectural floor plans (rooms exist only as numbers and names), and the mechanical
design drawings. The O&M site has an `08 As-Built Drawings` folder (a project manual volume is indexed),
but no drawing file was found by search or by guessing names.

Realistic flaws worth keeping as test cases: the room schedule header says "WMC West Tower, Project
3216-0033" (a template left over from another job) over Kelly Walsh data; tags appear in two forms
(`VAV-01-02` in schedules, `AHU1` in point names).

**Licence.** Every drawing carries a Johnson Controls notice forbidding reproduction or use without
written permission. The school publishes it openly, but treat it as internal test data: keep it out of
git, out of any published artifact or demo, and ask before showing it to anyone outside the team.

## 2. MSHP Troop D Crime Lab, Springfield, MO (bid set) – project R2517-01

"Update HVAC & Chiller, Crime Lab Building", 425 East Phelps Street. Designer True Engineering Group,
issued 2025-10-06. Existing Johnson Controls Metasys system kept and extended.

- [Final Bid Plans](https://oa.mo.gov/sites/default/files/bid-opportunities/_R2517-01%20Final%20Bid%20Plans.pdf): 27 sheets, 8.8 MB
- [Final Bid Specs](https://oa.mo.gov/sites/default/files/bid-opportunities/_R2517-01%20Final%20Bid%20Specs.pdf): 268 pages, 7.3 MB

| Sheets | Content |
|---|---|
| M-001…M-004 | Demolition plans with existing VAV and controller tags |
| M-101…M-104 | New work floor plans (VAV01…19, VAVE01…19, AHU01) |
| M-201…M-203 | Piping plans |
| M-301…M-303 | Controls diagrams, legend, controls responsibility matrix |
| M-304 | BAS sequence of operations (AHU, VAV, chiller) |
| M-401 | Mechanical schedules: VAV terminal unit schedule (mark, make, model, cooling/min cfm, heater kW…), AHU, chiller, pumps |
| E-001…E-201 | Electrical plans and panel schedules |

Spec sections that matter: 230923 DDC systems (17 pages), 230913 control devices, 233616 VAV units,
237313 custom air handlers, 236423 air-cooled scroll chiller, 230593 TAB.

Missing: no points list with BMS names, so no answer key for point classification. Good for steps 3, 4
and 6; scoring needs a hand-made ground truth (small enough: about 40 units).

The spec book is generic requirements, not project data: across its 268 pages the only equipment tag is
AHU-1 (in 237313, where the manufacturer's selection is pasted in). Section 230923 asks the contractor to
deliver a points list and I/O summary later, in the submittal, which is not public. All project facts are
in the drawings: schedules (M-401), sequence (M-304), and room names and numbers as text on the plans
(M-101…104, e.g. "DNA EXAM ROOM 209"). VAV-to-room links have to be read from where tags sit on the plan.

## 3. More from the same Missouri source (backups and stress tests)

The State of Missouri lists current and past bids at
[oa.mo.gov – bid listing, electronic plans](https://oa.mo.gov/facilities/bid-opportunities/bid-listing-electronic-plans),
with plans and specs as direct PDF links, no login. 25 open or recent HVAC projects were listed on
2026-11-16. Checked:

| Project | Building | Sheets | Why use it |
|---|---|---|---|
| [R2511-01](https://oa.mo.gov/sites/default/files/bid-opportunities/_R2511-01%20Final%20Bid%20Plans.pdf) | MSHP Troop B HQ, Macon (replace HVAC, boilers, pumps, controls; 2026-06-15) | 41 | Nine controls sheets (M-800 sequence, M-801…808 per system), schedules M-601…603. Parts of the sequence are drawn, not text: tests the page reader |
| [C2406-01](https://oa.mo.gov/sites/default/files/bid-opportunities/_C2406-01%20Final%20Bid%20Plans.pdf) | Fulton R&D Center, HVAC improvements | 118 (78 MB) | Scale: ~30 RTUs, exhaust fans, pumps, boilers; controls M400/M401 with points, sequences M600 |
| [R2513-01](https://oa.mo.gov/sites/default/files/bid-opportunities/_R2513-01%20Final%20Bid%20Plans.pdf) | Troop C CDL Supersite, HVAC & control system | 19 (49 MB) | Scanned: almost no text layer. OCR stress test |
| [R2518-01](https://oa.mo.gov/sites/default/files/bid-opportunities/_R2518-01%20-%20Final%20Plans.pdf) | Upgrade HVAC system (DOAS) | 19 | Small; controls diagrams and schedules |

Older links on that site can return 404 once a project is archived: download what we want to keep.

## 4. Second search: one package with submittal and floor plans (2026-11-16)

Not found. Controls submittals belong to the contractor and stay with the owner; they reach the web only
by accident, as Kelly Walsh's did through its O&M site. What was checked:

- **Kelly Walsh as-built drawings.** The turnover index ([Index.pdf](https://kellywalsh.org/building_manual/Index.pdf))
  has an "As-Built Drawings" page with no links. The `08 As-Built Drawings` folder only exposes a project
  manual volume; about 20 guessed file names return 404. The drawings exist (architect RB+B, 335,685 sf,
  general contractor Sampson Construction) but are not public.
- **Anonymised real submittals** (format references, no floor plans, no project):
  [AME sample](https://www.ame-inc.com/wp-content/uploads/2020/05/AME_Control_Submittal_Sample.pdf)
  (130 pages: riser with BACnet device instances, per-system schematic, wiring, point list, bill of
  materials, sequences; VAV, RTU, ERU, MAU, VRV, radiant, fume hood; valve and damper schedules) and a
  [Johnson Controls sample](https://innovativecontroltech.com/pdf/JohnsonControls.pdf) (34 pages, school:
  plant, RTUs, AHUs, unit ventilators, fan coils, splits).
- **Design sets with plans, no submittal**: Dover NH High School & CTC
  ([project page](https://www.dover.nh.gov/government/city-operations/public-education/high-school-project/):
  full conformed drawings and specs, large), plus the Missouri sets above.
- Design standards (Cornell, UMich, WVU, Wake County, NAVFAC Niagara) describe floor-plan sheets in
  submittals but contain no project.

Ways to get a complete set:

1. **Public records request, Missouri Troop D (R2517-01).** Bid Oct 2025, so the controls submittal
   should now exist. A Sunshine Law request to the Office of Administration, Facilities Management, for
   the approved Division 23 09 controls submittal gives design drawings and submittal for one building.
2. **Public records request, Natrona County School District #1**, for Kelly Walsh mechanical as-built
   drawings: adds floor plans to the most complete submittal we have.
3. **Build the missing half ourselves**: write a submittal for Troop D (points list, BACnet names,
   controller addresses, room schedule) in the AME / Johnson Controls format, from its drawings. Every
   answer is known, so it scores exactly, but it tests our own guesses about naming.
4. **One internal project** when access exists (`CLAUDE.md` §1): the only path to a real BMS export
   next to its submittal.

## 5. Looked at and not used

- **Delaware bid documents** (`bidcondocs.delaware.gov`): full sets with controls diagrams (for example
  OMB MC1002000830: M-400/401 controls, M-600 schedules), but the site rejects scripted downloads.
  Usable by hand from a browser if needed.
- **University BAS standards** (Texas A&M, UCF, Dartmouth, UConn, Cal Poly…): describe what a submittal
  must contain; useful as a checklist for the page classifier, not as test data.
- **Research datasets**: LBNL Building 59 (Brick model + 3 years of data, no drawings or submittal);
  Fierro et al. point-label dataset (103k point names, 92 buildings, no documents). Good for the mapper,
  not for this workflow.
- **Vendor samples** (EMC Controls VAV submittal, Price control sequences): one device each, too small.
