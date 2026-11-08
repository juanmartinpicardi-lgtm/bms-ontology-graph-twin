# Knowledge model v0

The definitions that are the same for every project. Loaded and validated by
`src/projectmodel/knowledge_model.py`; check with `.venv/bin/python scripts/validate_km.py`.

| File | What it holds |
|---|---|
| `brick_subset.yaml` | The Brick 1.4.4 classes and relations the mapper may assign, grouped. Parents come from Brick. |
| `ba_extension.ttl` | ~10 building-automation classes Brick lacks (controllers, field networks, software/diagnostic/cost points, schedules, trend logs, alarm definitions) and 3 relations. |
| `templates/*.yaml` | Equipment templates (AHU, VAV, FCU, chiller, boiler, pump): point slots, name patterns, expected feeds. See `templates/README.md`. |
| `name_rules/abbreviations.yaml` | Tokenizer settings, phrase rules, controlled vocabulary, abbreviations (with alternatives for ambiguous ones), worked examples. |

Validation fails the load if: a class is missing or deprecated in Brick 1.4.4, an equipment/point class
is listed under the wrong kind, an extension class clashes with Brick or has an unknown parent, a
template references an unknown class/template/relation or has a bad regex, an abbreviation expands to a
word outside the vocabulary or can never be produced by the tokenizer, or a worked example parses differently.

Tuning rule: change these files based on the Alpha dev set only, never Bravo.
