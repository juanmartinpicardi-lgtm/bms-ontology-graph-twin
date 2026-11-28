# Build Brief — Project Model Prototype (for Claude Code)

Use this as the repo's `CLAUDE.md`. Companion docs: *Spec – Project Model v0.2*, *Prototype datasets – Project Model*.

## 1. Goal

Build a prototype that turns engineering-tool exports into a reviewed **knowledge graph** of a building project, using a **knowledge model**, and measure how good it is against ground truth.

Phase 0 runs on **public data only** (Project Haystack example sites). Niagara and CPO Studio adapters come later, when internal access exists. The pipeline must not care which source the data came from.

Not a goal: production quality, auth, scale. Writing back to a source tool is allowed when the user asks for it (§8).

## 2. Vocabulary (use these terms consistently in code and UI)

| Term | Meaning | In this repo |
|---|---|---|
| **Graph** | The data structure: nodes and edges. No meaning on its own | `nodes` and `edges` tables in SQLite |
| **Knowledge model** | The definitions: what kinds of things exist, how they may relate, and the rules for recognising them. Same for every project | `/knowledge_model/`: Brick subset (classes, relations), BA extension classes, equipment templates (AHU, VAV, FCU, chiller…), name-parsing rules, validation rules |
| **Ontology** | The class + relationship part of the knowledge model | Brick subset + BA extension (inside the knowledge model) |
| **Knowledge graph** | The graph for one project, built with the knowledge model: typed instances, relationships, provenance | One project's nodes/edges, each pointing to a knowledge-model class |
| **Digital twin** | Knowledge graph + state (checkout status, revision, sync) + views | Later phase |

Rule of thumb: the knowledge model is reusable IP that improves across projects; the knowledge graph is per project.

## 3. Architecture

```
Source adapters  →  Raw records  →  Mapper  →  Knowledge graph  →  Review  →  Views / Q&A
(Haystack now,      (one common     (rules →    (SQLite nodes/      (accept /
 Niagara, CPO        shape)          LLM →       edges +             fix /
 later)                              confidence)  provenance)        reject)
                         ↑
                 Knowledge model (/knowledge_model)
```

- **Raw record** (common shape for all adapters): `source_id, source_system, name, display_name, path/folder, device_id, object_id, units, kind, extra{}`.
- **Every node and edge stores:** source file + row/path, method (`parsed | rule | llm | human`), confidence (0–1), status (`proposed | confirmed | rejected`), revision.
- **Mapper order:** deterministic structure → name-parsing rules → template match (does the group of points look like a VAV?) → LLM only for what's left, given a short candidate list of classes, never the full Brick list.

## 4. Stack (prototype)

- Python 3.11, SQLite, `rdflib` + `brickschema` (Haystack → Brick conversion, SHACL validation)
- Streamlit for the review screen and tree view
- One LLM provider behind a small interface so it can be swapped
- pytest for the scoring script and parsers

## 5. Datasets

- **Dev set:** Project Haystack site **Alpha** (central plant + VAV, ~1,842 points).
- **Test set:** none for now (Bravo was removed). When one is added, never tune rules or prompts on it.
- **Later:** LBNL Building 59 (Brick), Mortar (breadth), Reflow demo station (real Niagara file).
- **Real document sets for the guided setup** (`docs/real-document-sets.md`, files in `data/raw/`):
  - Dev: `msu_mbb` (Montana State University lab and office renovation) and `itd_d1_lab` (Idaho DOT testing laboratory). Rules and prompts may be tuned on these.
  - **Held out: `liberty_boe`** (Liberty County, GA, school board office HVAC replacement). Never tune rules or prompts on it. Run it only to report headline counts (`scripts/run_real_sets.py` writes nothing else for it), and don't open its questions, issues or facts when choosing fixes.

Download from project-haystack.org/example (CSV or Zinc). Store raw downloads in `/data/raw/` untouched.

## 6. Phase 0 tasks (each with a done-when)

1. **Golden set.** Load Alpha; convert to Brick with `brickschema`; save ground truth (point → class, point → equipment, equipment → class, equip → equip feeds/parts). *Done when:* ground truth files exist and a spot-check of 20 points looks right.
2. **Blind exports.** Build two inputs per site by removing tags: **(a) names only**, **(b) names + equipment folder path** (closest to a Niagara station tree). *Done when:* the inputs contain no tag or ref that leaks the answer.
3. **Haystack adapter** → raw records. *Done when:* every point becomes one raw record.
4. **Knowledge model v0.** Brick subset (~50 HVAC classes), BA extension (~10 classes), templates for AHU, VAV, FCU, chiller, boiler, pump; name-parsing rules (abbreviations dictionary). *Done when:* files load and validate.
5. **Mapper.** Grouping (points → equipment) and classification (point → class) with confidence. *Done when:* it runs end-to-end on Alpha.
6. **Scoring script.** Report: % points grouped on the right equipment (H1), class accuracy overall and for auto-accepted items (H2), % sent to review, cost and time per 1,000 points. *Done when:* one command prints the report for dev and test sets.
7. **Review screen.** List proposed items sorted by confidence; accept / fix / reject in bulk; corrections saved with `method=human`. *Done when:* a person can review Alpha and the score updates.
8. **Tree view.** Equipment tree with points and provenance per node.

## 7. Later phases (not now)

- Niagara adapter (`.bog` / station export), CPO Studio adapter, merge on device ID.
- Documents: link equipment to spec/sequence pages; grounded Q&A with page citations.
- Revisions and diff on re-upload.
- Digital twin state layer (seeded checkout status) and equipment page.

## 8. Rules for the coding agent

- Data flows from sources into the app by default. Write back to a source tool (for example tags into a Niagara station) only when the user asks for it: show what will change first, the user confirms, and log every write with what was sent, where, when and by whom. Never write back on the app's own initiative. Files the app generates for a tool to import (CSV, `.bog`, graphics) are outputs, not write-back.
- Keep adapters thin; all intelligence lives in the mapper + knowledge model.
- Every fact must be traceable to its source and method.
- Prefer rules and templates over LLM calls; log every LLM call with input, output, cost, latency.
- Auth and deployment are asked for (28 Nov 2026, `docs/plan-delivery.md` §7): Cloud Run, Cloud SQL Postgres, Cloud Storage, Identity-Aware Proxy login, region `us-central1`. Still no graph database.
