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

## Notes

Note for Task 2: the original BMS point name lives in `custom.description` (e.g. `Clg_Valve_Cmd`).
`dis` is a composed label that includes the equipment name, so it leaks the answer.
