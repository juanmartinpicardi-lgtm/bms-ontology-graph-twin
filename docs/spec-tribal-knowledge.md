# Spec – Tribal knowledge v0.1

Status: draft, 2026-11-08. Builds on Phase 0 (Tasks 1–8). Vocabulary as in `CLAUDE.md` §2.

## 1. What this is

**Tribal knowledge** is what engineers know about a building or a contractor that is written down nowhere:
"this integrator writes CC for chiller condenser", "AHU-3's old points are dead since the 2022 retrofit",
"zone 4 runs hot when the reheat valve sticks". Today the pipeline captures it only indirectly, as one-off
review corrections (`method=human`) that help one point and teach nothing to the next project.

This spec adds three things, in build order:

| # | Feature | What it holds | Lives in | Changes the mapper? |
|---|---|---|---|---|
| T1 | **Notes** | Free-text facts attached to equipment, points, links or the whole project | `notes` table (SQLite) | No |
| T2 | **Conventions** | Naming rules for one contractor, customer or site, layered on top of the knowledge model | `/conventions/*.yaml` | Yes |
| T3 | **Learn from corrections** | Repeated human fixes become proposed conventions a person accepts | `proposals` table → T2 files | Indirectly |

Where each kind of knowledge goes:

```
Knowledge model     reusable, all projects        "SAT = supply air temperature"
   ▲ promote (T3)
Conventions         one contractor/customer/site  "CC = chiller condenser (Acme Controls)"
   ▲ promote (T3)
Knowledge graph     one project's facts           point → class, point → equipment (+ human fixes)
Notes               one project's context         "AHU-3 replaced 2022; RF VFD points unused"
```

Rule of thumb: if the knowledge would **change how a name is read**, it is a convention. If it **describes the
building or how it behaves**, it is a note.

## 2. Non-goals (for now)

- Interviews, voice capture, document parsing (reserve fields so they can be added; see §6).
- LLM summarising or extracting notes. No LLM calls in this spec.
- Users, permissions, auth. `author` is a free-text name, as in the review screen today.
- Notes changing scores or classes. Notes are context, never graph facts.

## 3. T1 – Notes

### 3.1 Data

New table in `src/projectmodel/db/store.py` (same file, same `SCHEMA` string):

```sql
CREATE TABLE IF NOT EXISTS notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project      TEXT NOT NULL,
    target_kind  TEXT NOT NULL CHECK (target_kind IN ('node', 'edge', 'project')),
    target_id    TEXT NOT NULL,          -- node id, "src|rel|dst" for an edge, "" for project
    target_label TEXT NOT NULL,          -- label when written, so an orphaned note still reads well
    topic        TEXT NOT NULL CHECK (topic IN ('naming', 'history', 'operations', 'maintenance', 'other')),
    body         TEXT NOT NULL,
    author       TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'review', 'interview', 'document')),
    source_ref   TEXT NOT NULL DEFAULT '',   -- e.g. document + page, interview id; empty for manual
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'superseded')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

- Notes are keyed by node id. Equipment ids are path-based (`eq:Airside AHU-2`) and point ids come from the
  source, so they survive a mapper re-run. If a target disappears, the note is shown as **orphaned** (with
  `target_label`) rather than dropped.
- Editing a note updates `body`/`updated_at`; changing status never deletes. No hard delete in the UI.
- `source = interview | document` are reserved for later phases; the UI offers only `manual` and `review`.

### 3.2 Code

`src/projectmodel/notes.py`: `add_note`, `update_note`, `set_status`, `notes_for(store, project, target_kind,
target_id)`, `notes_by_project(store, project, topic=None, status="active")`, `orphaned(store, project)`.

### 3.3 UI

- **Tree tab** (review app): selected node shows its notes under the provenance table, plus an "Add note" form
  (topic, body, author). Equipment also lists its points' notes, collapsed.
- **Points / Equipment review tabs**: a note icon + count column; the fix dialog has an optional
  "Why?" box that saves a `source=review` note on the node.
- **3D graph**: `graph_payload` adds `notes: <count>` per node and link; the details panel lists them read-only
  (the viewer is an iframe; editing stays in Streamlit). Optional colour mode "has notes".
- **New page `views/notes.py`**: all notes for the project, filter by topic/status/author, orphaned notes at the top.

### 3.4 Done when

- A person can add, edit and resolve notes on equipment, points, links and the project, from the Tree tab.
- Notes appear in the 3D details panel and survive `run_mapper.py` re-runs.
- Removing a node from the source shows its note as orphaned.
- Tests: CRUD, orphan detection, re-run survival, payload counts.

## 4. T2 – Conventions

### 4.1 Files

```
conventions/
  README.md
  projects.yaml                 # which scopes apply to which project
  contractor/acme-controls.yaml
  customer/example-hospital.yaml
  site/alpha.yaml
```

`projects.yaml`:

```yaml
alpha/names_paths: [contractor/buildingfit, site/alpha]
```

A convention file uses the same shapes as the knowledge model, so the same loader and validator apply:

```yaml
scope: site/alpha
description: Naming habits seen on site Alpha.
author: ana
abbreviations:            # same format as knowledge_model/name_rules/abbreviations.yaml
  cc: [chiller, condenser]
equipment_patterns:       # extra name_patterns per template id
  vav: ['\bZN[-_ ]?\d']
class_hints:              # whole-name regex → class, highest priority among rules
  - {pattern: '(?i)^occupied status$', class: Occupancy_Status}
ignore:                   # points known dead/unused; mapped but sent to review with a reason
  - {pattern: '^RF VFD', reason: 'Return fan removed 2022'}
```

### 4.2 Behaviour

- **Layering:** knowledge model ← contractor ← customer ← site. A later layer overrides or extends an earlier
  one. `load_knowledge_model(..., conventions=[...])` returns a model with the layers merged; the base model is
  untouched on disk.
- **Validation:** `scripts/validate_km.py --project alpha/names_paths` validates the merged model with the
  existing rules (vocabulary words exist, classes are in the subset, regexes compile, no separator in keys).
- **Provenance:** anything a convention decides is `method=rule` with `attrs.convention = "site/alpha:abbreviations.cc"`.
  The tree and 3D details panel show it. Every fact stays traceable (brief §8).
- **Explorer:** the Knowledge model page gets a scope selector showing which entries come from which layer.

### 4.3 Measuring it honestly

- Write and tune conventions on **Alpha only**.
- For a held-out **test site**, conventions may only contain what a site engineer would tell us *before* seeing
  our output (e.g. contractor abbreviations). Report it twice: blind (no conventions) and with conventions,
  labelled as such. Never tune a test-site convention on that site's score.
- The scoring report adds a line per project: `conventions: [scopes]` so a score always says what it used.

### 4.4 Done when

- `conventions/site/alpha.yaml` resolves at least the open "CC" case, re-running Alpha changes the score, and
  the report says which conventions were used.
- A broken convention file fails validation with a clear message naming the file and key.
- Tests: layer order, override vs extend, validation errors, provenance attr present.

## 5. T3 – Learn from corrections

### 5.1 How it works

After each review session (or on demand), `scripts/propose_conventions.py <project>` scans human fixes
(nodes with `method=human` and `attrs.review.action = "fix"`; the mapper's guess is in `attrs.review.previous`)
and proposes:

| Signal | Proposal |
|---|---|
| ≥3 points sharing a token that got the same class fix | `abbreviations` or `class_hints` entry |
| ≥3 equipment names matching a pattern fixed to the same class | `equipment_patterns` entry |
| A token in `unknown_tokens` across ≥5 points, fixed consistently | `abbreviations` entry |

Thresholds live in one constant block and are tuned on Alpha.

### 5.2 Data

```sql
CREATE TABLE IF NOT EXISTS proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL,
    scope       TEXT NOT NULL,           -- target file, default site/<site>
    kind        TEXT NOT NULL,           -- abbreviations | equipment_patterns | class_hints
    entry       TEXT NOT NULL,           -- JSON of the entry to add
    evidence    TEXT NOT NULL,           -- JSON list of node ids + their fixes
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'rejected')),
    decided_by  TEXT, decided_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 5.3 UI

A "Proposed conventions" tab in the review app: each proposal shows the entry, the evidence points, and
**the preview effect** (how many other points it would change, using a dry-run of the mapper). Accept writes the
entry into the chosen convention file (our own file, not a source system, so brief §8 holds) and re-runs the
mapper. A second action, **"Promote"**, moves an entry one layer up (site → customer → contractor → knowledge
model); promoting into the knowledge model only writes a patch file under `conventions/promotions/` for a model
owner to apply by hand.

### 5.4 Done when

- After fixing CC-type points on Alpha, a proposal appears with its evidence and dry-run effect; accepting it
  updates `site/alpha.yaml` and the score.
- Tests: proposal generation from synthetic fixes, dry-run count, accept writes valid YAML.

## 6. Later (placeholders only)

- **Interviews:** `notes.source = interview`, `source_ref` = interview id; a capture flow from a guided
  conversation with a site engineer.
- **Documents:** `notes.source = document`, `source_ref` = file + page; links to spec/sequence pages (brief §7).
- **Q&A:** notes are retrievable context for grounded Q&A, cited like documents.

## 7. Open questions

1. Who may edit convention files: anyone reviewing, or a named owner per scope?
2. Should `ignore` points be dropped from scoring, or scored and flagged? (Default: scored, flagged.)
3. Contractor for Alpha is unknown beyond the donor names; treat donor as contractor scope?
