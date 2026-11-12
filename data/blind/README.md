# Blind exports

Mapper inputs with every Haystack tag, ref, id and curated label removed. Built from `data/raw/` by
`scripts/build_blind.py`; checked by `tests/test_blind.py`.

| File | Columns | Closest real-world source |
|---|---|---|
| `<site>/names_only.csv` | `blind_id, name` | a flat point list |
| `<site>/names_paths.csv` | `blind_id, name, path` | a Niagara station tree (one folder per equipment) |

- `name` is the original BMS point name (`custom.description`, or `custom.sourcePointName` where a site uses it).
  Where a site has none (Alpha: 91 points) it falls back to the Haystack `dis` with the
  equipment prefix stripped. That label was written from the tags, so it is easier than a real name;
  `name_source` in the key marks these so scoring can report them separately.
- `path` is the equipment folder chain (e.g. `Airside AHU-2/VAV 1-2-21`), from equip `equipRef`s.
- Rows are shuffled with a fixed seed and renumbered, because Haystack ids are sequential per equipment.
- Same `blind_id`s in both variants. The answer key (`blind_id -> point_id, name_source`) lives in
  `data/ground_truth/<site>/blind_key.csv`. The mapper must never read `data/ground_truth/`.
- Not included: units and value kind. Real exports usually carry them; add them as a separate
  variant if wanted, so the brief's "names only" baseline stays pure.
