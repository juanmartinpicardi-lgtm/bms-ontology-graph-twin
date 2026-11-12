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

Note for Task 2: the original BMS point name lives in `custom.description` (e.g. `Clg_Valve_Cmd`).
`dis` is a composed label that includes the equipment name, so it leaks the answer.
