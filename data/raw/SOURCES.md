# Raw data sources

Files here are untouched downloads. Never edit them; derive everything else from them.

## Project Haystack example sites

Source page: https://project-haystack.org/example (license: AFL 3.0)
Downloaded: 2026-11-08 via `https://project-haystack.org/example/download/<site>.<fmt>`

| File | Site | Grid meta | sha256 |
|---|---|---|---|
| haystack/alpha.json | Alpha (central plant + VAV, Hugo CO, donated by BuildingFit) | 184 equips, 1842 points, 4 weather points | bbcf0d957c6e36e494fa8a5ebc6eaf12a3c1ab03d89d950467be5dbae010276d |
| haystack/alpha.zinc | Alpha | | 8a68a5ec65c61be94f747f2db074b5044aef42966f2dcdf4081d4238602a113c |
| haystack/alpha.ttl | Alpha | | 717f98cc6d5653b2582eda304e36640b33754dbb019009e18154361a02ec72e7 |

JSON (Haystack 4 JSON, `_kind` encoding) is the format the pipeline reads; refs are intact.
Zinc and Turtle are kept as reference copies.

## Troop D Crime Lab (State of Missouri bid set R2517-01)

Source: State of Missouri, Office of Administration, bid opportunities (public record).
Downloaded: 2026-11-16. The PDFs are not in git (see `.gitignore`); fetch them again from these URLs:

- https://oa.mo.gov/sites/default/files/bid-opportunities/_R2517-01%20Final%20Bid%20Plans.pdf
- https://oa.mo.gov/sites/default/files/bid-opportunities/_R2517-01%20Final%20Bid%20Specs.pdf

The state may archive the project and remove the URLs after award; the sha256 below identifies the right copy.

| File | Contents | sha256 |
|---|---|---|
| troop_d/R2517-01_Final_Bid_Plans.pdf | 27 sheets: floor plans M-101..M-104, piping M-301, AHU M-303, sequences M-304, schedules M-401 | 5beeabd88969dca660402c17acf8c3ae636157d7a8f622df0cdab0adc947ae8a |
| troop_d/R2517-01_Final_Bid_Specs.pdf | 268-page project manual (generic specs, incl. 23 09 00) | 714bef588c904504c20131d5f38f261fbe4933ceb55a6eaa8316fb7510a1ccab |

What is built from them: `data/documents/troop_d/README.md`.

## Real document sets for the guided setup (W0)

Three more public bid sets, collected so future readers are measured on buildings the rules have never seen. Profiles,
the held-out choice and the results of the current readers: `docs/real-document-sets.md`.
Downloaded 2026-11-23. The PDFs are not in git (see `.gitignore`); `scripts/run_real_sets.py --fetch` downloads them
again from the URLs below and checks each file against the sha256 here. Agencies remove bid files after award, so the
sha256 is what identifies the right copy.

Public-record basis: each set was published, free and without a login, by a public owner (a state agency, a state
university, a county school system) to invite public bids on a publicly funded project. No license is stated on any of
them; the title blocks keep the designers' copyright notices. Use them for internal testing only; do not republish them.

### msu_mbb: Montana State University, Molecular Bioscience Building renovations (PPA 22-0045)

Owner: Montana State University, Planning, Design & Construction (Bozeman, MT). Architect Bechtle Architects; mechanical
SE Engineers (Three Forks, MT). Bid date 10 Sep 2026; drawings dated 12/12/25.
Source page: https://www.montana.edu/pdc/bids.html (each file is at `https://www.montana.edu/pdc/projects/<file name>`,
spaces as `%20`).

| File | Contents | sha256 |
|---|---|---|
| msu_mbb/22-0045 Plans.pdf | 78 sheets, all disciplines; mechanical M001–M.601 on pages 17–32 | c08c91bcf6de63d2cc7ae960cb32a19d63eabd2b42cda09c82dc4a8fb3d055e3 |
| msu_mbb/22-0045 Molecular Bioscience Building Renovations and Maintenance Project Manual Final.pdf | 603-page project manual; Division 23 from page 244, no 23 09 xx section | 0fce2374dce80517586c43dc90a865a23da489ee1b46d0390085428b466de178 |
| msu_mbb/22-0045 Addendum 1.pdf | 131 pages | 7b18575b416d6953e3eafba5667e466ac74e4ccbeff16e514d9aa32e35193c8b |
| msu_mbb/22-0045 Addendum 2.pdf | 21 pages; answers on M002, M202, M301, M302, M501, M502 | d882e4d8af30e6b87f2660be34b802dd3f510c0c202726ec06a5c66456b362ac |
| msu_mbb/22-0045 Addendum 3 updated.pdf | 23 pages | 8834f8005c6921129858f70e86f092f58ae1586d15b935c641cd9b57bdee08f3 |

### itd_d1_lab: Idaho Transportation Department, District 1 Testing Laboratory (project D231130, phase 2)

Owner: Idaho Transportation Department (state agency), District 1, 600 W Prairie Ave, Coeur d'Alene, ID. Architect
Miller Stauffer Architects; mechanical Musgrove Engineering (Boise, ID). Bid set dated 5/13/2024.
Source: ITD facility bidding (https://itd.idaho.gov/facility-bidding/ lists the phase 2 bid tab; the drawing file is no
longer linked there but is still served at the URL below).

| File | Contents | sha256 |
|---|---|---|
| itd_d1_lab/ITD D1 Laboratory Building - Mechanical Bid Set 05-14-24.pdf | 29 sheets: M0.0–M6.5 mechanical, P1.0–P6.0 plumbing, FS1.0 | 9dafcead2eb5fe3679921f336ccd7ca4813da1524580c5fee75a87c99e1b2707 |

URL: https://apps.itd.idaho.gov/Apps/NonHwyConstructionProjects/PDFS/ITD%20D1%20Laboratory%20Building%20-%20%20Mechanical%20Bid%20Set%2005-14-24.pdf

### liberty_boe: Liberty County School System, Board of Education building HVAC replacement (RFP 2026-07) — HELD OUT

Owner: Liberty County School System (Hinesville, GA), 200 Bradwell St. Mechanical Method Engineering Group (Savannah,
GA). Construction documents dated 12/05/2025; proposals were due 6 Jan 2026.
This is the held-out test set: see `docs/real-document-sets.md` before using it.

| File | Contents | sha256 |
|---|---|---|
| liberty_boe/2026-07 Drawings.pdf | 18 sheets: G000, M000–M302, E000–E104 | a01b580c0b81796cbe62ed311ce02422168948320045b7cce387b94e6cbdff54 |

URL: https://www.libertyschools.org/ourpages/auto/2025/12/5/62988481/2026-07%20Drawings.pdf

## Notes

Note for Task 2: the original BMS point name lives in `custom.description` (e.g. `Clg_Valve_Cmd`).
`dis` is a composed label that includes the equipment name, so it leaks the answer.
