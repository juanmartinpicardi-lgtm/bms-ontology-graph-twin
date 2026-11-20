# Spec – Memory and skills v0.1

Status: draft, 2026-11-20. Builds on Phase 0, the guided setup (`spec-submittals-workflow.md`) and tribal knowledge
(`spec-tribal-knowledge.md`, T1 notes and T2 conventions are built; T3 is replaced by this spec). Models and providers
as in `spec-ai-architecture.md`. Vocabulary as in `CLAUDE.md` §2.

## 1. What this is

A layer that keeps **how our engineers work**: their principles, what they know about a design firm, a controls
contractor, a customer or a site, and the procedures they follow. It is written to automatically while people work,
is used by every reader, the mapper and the agent, and is always visible and editable in the app.

Today that knowledge is scattered and mostly lost:

| Where it is today | What it holds | Problem |
|---|---|---|
| `knowledge_model/` | Classes, templates, name rules for every project | Changed by hand only |
| `conventions/` | Naming rules per contractor, customer, site (T2) | Written by hand; nobody proposes them |
| `notes` table (T1) and setup notes | Tribal knowledge per project | Context only; teaches the next project nothing |
| Review fixes (`method=human`) | One corrected point at a time | The same fix is made again on the next building |
| Setup answers (`intake/knowledge.py`) | Tag prefixes and phrases learned in one setup | Exported as YAML by hand, if at all |
| Hard-coded layouts (`intake/schedules.py`) | One engineer's schedule habits | Code change per new engineer |

The design follows Nous Research's Hermes Agent, adapted to a product where wrong knowledge changes engineering
output:

| Hermes Agent | Here |
|---|---|
| `MEMORY.md` (2,200 chars) and `USER.md` (1,375 chars), bounded, loaded at session start | **Memory** per scope, bounded per scope, loaded for the scopes a task touches |
| Skills: `SKILL.md` with YAML frontmatter, loaded on demand (index → full body → reference file) | **Skills**: same format (agentskills.io compatible), plus a `rules/` folder the readers execute |
| Background review after a session creates or patches skills | **Curator** after a trigger (review batch, setup published, agent session) proposes changes |
| `skills.write_approval` off by default | **Approval is on** for anything that changes outputs, with a regression score before approval |
| FTS5 search over past sessions | **Journal** of episodes (reviews, setup answers, agent sessions), FTS5 in the same SQLite |
| User profile (Honcho) | **People**: one short profile per person (role, how they review) |

The main difference: Hermes writes skills with no approval by default. Research on self-improving agents warns that
skills learned in practice can drift into wrong or unsafe behaviour ("Practice Makes Unsafe: Skill Misevolution in
Self-Improving LLM Agents", arXiv 2608.12851). In a BMS a wrong rule misclassifies thousands of points silently, so
here anything that changes how documents are read waits for a person and must not lower the dev-set score.

## 2. Non-goals (for now)

- Auth and permissions. `author` and `approver` are free-text names, as in the review screen.
- Writing to any source tool (CLAUDE.md §8). Memory is about how we read sources, never written back to them.
- Vector databases or embeddings. SQLite FTS5 is enough at this size; revisit if recall is poor (§11).
- Google's Agent Platform Memory Bank (formerly Vertex AI Memory Bank). It is a managed conversational memory; we
  need files in git, scopes, provenance and approval. Revisit for the agent's chat memory later (§11).
- Interviews and voice capture (reserved: `source = interview`).

## 3. The three kinds of knowledge, and where each goes

| Kind | Is | Example | Changes outputs? |
|---|---|---|---|
| **Memory entry** | A short statement: a principle, a fact, a preference, a warning | "Design documents are intent; the submittal and BMS win on what is installed." | No (context for models and people) |
| **Skill** | A procedure: when to use it, steps, pitfalls, how to verify | "Read a Metasys controls submittal" | Only through its `rules/` |
| **Skill rules** | Machine-readable rules inside a skill, run by the readers and mapper without a model | Schedule column layout for one design firm; tag prefixes; abbreviations; class hints | **Yes** |
| **Profile** | How one person works with the app | "Reviews by equipment; wants plain-English labels next to Brick classes" | No |
| **Journal episode** | What happened: a review batch, setup answers, an agent session, a note | "Ana fixed 12 points `CC-*` → Condenser_Water…" | No (evidence for the curator) |

Rule of thumb, extending the one in `spec-tribal-knowledge.md`: if it **changes how a document or name is read**, it
is a skill rule. If it **says how we work or what is true about a party**, it is memory. If it **describes one
building**, it stays a note.

## 4. Scopes

Every memory entry and skill has one scope. Scopes layer from general to specific, like conventions today; the more
specific wins, and a conflict between layers is shown, never silently resolved.

```
global                     our principles and methods, every project
  designer/<firm>          the engineering firm that drew the plans and schedules
  contractor/<name>        the controls contractor (submittal, BMS naming)
  customer/<name>          the building owner's standards
    site/<slug>            one building
person/<name>              one person's profile (separate: never changes outputs)
```

`designer/` is new: plan and schedule habits belong to the firm that drew them, not to the controls contractor. A
project's scopes are listed in `conventions/projects.yaml` (extended with `designer:`); the guided setup proposes
them from the title block (designer) and the submittal cover (contractor), and the person confirms.

Size caps per scope, as Hermes does, so memory stays readable and is consolidated rather than appended:

| Scope | Memory cap | Skills |
|---|---|---|
| global | 4,000 chars | unlimited |
| designer, contractor, customer | 2,500 chars each | unlimited |
| site | 2,500 chars | unlimited |
| person | 1,200 chars | none |

A write that would exceed the cap is rejected; the curator must merge or retire entries in the same proposal.

## 5. Files and data

### 5.1 Files: the source of truth, in git

```
knowledge/
  memory/
    global.yaml
    designer/<firm>.yaml
    contractor/<name>.yaml
    customer/<name>.yaml
    site/<slug>.yaml
  people/<name>.yaml
  skills/
    <scope path>/<skill-name>/
      SKILL.md                 frontmatter + When to use / Procedure / Pitfalls / Verification
      rules/*.yaml             optional; executed by readers and mapper (schemas in §5.3)
      references/*.md          optional; loaded only when asked for
```

A memory file:

```yaml
scope: designer/example-mep-firm
cap: 2500
entries:
  - id: m-0007
    kind: fact                 # principle | fact | preference | warning
    text: "VAVE is a VAV box with electric reheat; FVAV is fan powered. Quantity markers like (9) follow the tag."
    source: {episodes: [e-0412, e-0419], facts: ["troop_d:schedules:p3:row12"]}
    method: curator            # human | curator | import
    author: ana                # who wrote or approved it
    status: active             # active | retired
    locked: false              # true: the curator may not change it
    created: 2026-11-20
    used: 0                    # times it was in context for a model call or shown to a reviewer
```

A skill's `SKILL.md` frontmatter (agentskills.io fields plus ours under `metadata.projectmodel`):

```yaml
---
name: read-example-mep-firm-schedules
description: Read equipment schedules drawn by an example MEP firm (M-4xx sheets).
version: 3
metadata:
  projectmodel:
    scope: designer/example-mep-firm
    applies_to: {step: schedules, sheet_titles: ["SCHEDULE"]}
    rules: [rules/layouts.yaml]
    status: active             # active | draft | retired
    locked: false
    method: curator
    approved_by: ana
    evidence: [e-0412]
    dev_score: {before: 0.91, after: 0.97, set: troop_d}
---
```

`conventions/*.yaml` keep working unchanged. Phase M3 moves each one into a skill's `rules/conventions.yaml` (same
shape, same loader), so there is one place for rules.

### 5.2 SQLite (runtime state, same `data/kg.sqlite`)

```sql
CREATE TABLE IF NOT EXISTS episodes (          -- the journal
    id TEXT PRIMARY KEY, kind TEXT NOT NULL,    -- review | setup_answer | setup_published | note | agent | teach
    project TEXT, scopes TEXT NOT NULL,         -- JSON list of scopes the episode touches
    author TEXT, summary TEXT NOT NULL, detail TEXT NOT NULL,   -- detail: JSON (before/after, fact ids, refs)
    created_at TEXT NOT NULL DEFAULT (datetime('now')), curated INTEGER NOT NULL DEFAULT 0);
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(summary, detail, content='episodes');

CREATE TABLE IF NOT EXISTS proposals (          -- what the curator wants to change
    id TEXT PRIMARY KEY, scope TEXT NOT NULL,
    op TEXT NOT NULL,                           -- memory.add | memory.patch | memory.retire | skill.create
                                                -- | skill.patch | skill.retire | rules.patch
    target TEXT,                                -- entry id or skill name
    payload TEXT NOT NULL,                      -- JSON: the new text / file contents / patch
    why TEXT NOT NULL, evidence TEXT NOT NULL,  -- plain-English reason; JSON episode and fact ids
    lane TEXT NOT NULL,                         -- auto | approve
    checks TEXT NOT NULL,                       -- JSON: validation, cap, conflicts, dev score before/after
    status TEXT NOT NULL,                       -- pending | applied | approved | rejected | reverted
    model TEXT, llm_call INTEGER,               -- which model proposed it; row in llm_calls
    decided_by TEXT, decided_at TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS knowledge_use (      -- which entries and skills each model call or view used
    llm_call INTEGER, item TEXT NOT NULL, project TEXT, at TEXT NOT NULL DEFAULT (datetime('now')));
```

Applied and approved proposals are written to the files in §5.1. The app shows a "changed since last commit" badge
and can export the changes as one YAML/Markdown bundle (later: open a pull request).

**Deployment note.** Streamlit Cloud's disk is wiped on every redeploy, so on the hosted app anything not committed is
lost. Until the app runs on GCP with durable storage (§11), the hosted app is for showing, and learning happens on
a machine whose `knowledge/` changes get committed.

### 5.3 Executable rules

Rules are data, checked against the knowledge model before they load, exactly as conventions are today
(`conventions.py` `check`). Shapes:

| File | Used by | Shape |
|---|---|---|
| `rules/conventions.yaml` | mapper | as `conventions/*.yaml` today: `abbreviations`, `equipment_patterns`, `class_hints`, `ignore` |
| `rules/tags.yaml` | all readers | as `equipment_tags.yaml`: prefix → class, family, terminal |
| `rules/layouts.yaml` | `intake/schedules.py` | per schedule title words: ordered columns with field name, unit, type |
| `rules/terms.yaml` | submittal, BMS | phrase in a point description → class (as setup `terms` today) |
| `rules/variants.yaml` | Equipment 3D | equipment class + schedule fields → builder variant (return fan, heat wheel, coils) |

`intake/schedules.py` `LAYOUTS` becomes the seed of `knowledge/skills/designer/<troop-d firm>/…/rules/layouts.yaml`;
the code keeps only the logic to apply a layout.

## 6. Write path: how it updates itself

```
work happens ──► episode in the journal ──► curator (background) ──► proposals ──► checks ──► lane
review batch      what changed, before/after   reads episodes +       typed ops,      KM validation,  auto: applied,
setup answers     fact ids, document refs      current memory +       each with why   cap, conflicts,  shown, undoable
setup published                                skills index           and evidence    dev score        approve: waits
agent session                                                                                          for a person
note added
"Teach" (person)
```

**Triggers** (each writes one episode; the curator runs when one arrives, batched to at most one run per project per
5 minutes):

1. A review batch is saved (accept / fix / reject in bulk).
2. A setup step is re-read after the person answered questions.
3. A setup is published as a project.
4. A note is added (T1) or a setup note (tribal knowledge step).
5. An agent session ends in which the person corrected the agent.
6. **Teach**: a person writes "remember: …", or uploads a standard (a customer's point-naming guide, our own
   commissioning checklist). Large documents become a skill with `references/` per topic, as Hermes `/learn` does.

**The curator** (model per `spec-ai-architecture.md`: Claude Sonnet 5.5 on Vertex AI; Claude Opus 5.5 when the
proposal includes `rules/`, Fable 5.2 if Opus's rule fails the checks twice) receives the new episodes, the memory of
the scopes they touch, the skills index (name and description only) and the full text of skills it decides to open.
It returns proposals in a fixed JSON schema. Its instructions, in order of preference (as Hermes): patch the skill
already used; patch an existing skill in the same scope; create a skill only when nothing fits. Merge before you add.
Propose nothing when nothing general was learned: one-off fixes stay as `method=human` facts.

What counts as general enough to propose:

- The same correction made 3 or more times (same token, same class, same firm or contractor): a rule.
- A person's answer during setup that names a pattern ("FVAV is fan powered"): a rule at designer or contractor scope.
- A contradiction found between two documents and how the person settled it: a principle or a warning.
- An agent step the person corrected ("check the CHW valve before the plant"): a patch to the agent's skill.

**Checks** run on every proposal before anyone sees it:

| Check | Fails when |
|---|---|
| Knowledge model | A class, relation or template id doesn't exist (same checks as `conventions.py`) |
| Cap | The scope would exceed its cap |
| Duplicate and conflict | Same or opposite statement already in this or a parent scope (Claude Haiku 5.5 compares the candidates FTS5 finds) |
| Personal data | Names, phone numbers, emails outside `author`/`approver` (people's profiles excepted) |
| Locked | It changes an entry or skill marked `locked` |
| **Dev score** | For `rules/` changes: re-run the affected step or mapper on the dev set (Alpha, Troop D) with and without the change; the score must not drop. Never the test set. |

**Lanes:**

| Lane | What | Applied |
|---|---|---|
| auto | Memory entries of kind `fact` or `preference` at site or person scope; retiring an entry nothing used in 90 days | Immediately; shown in the activity feed with Undo |
| approve | Everything that touches `rules/`, any `global`/`designer`/`contractor`/`customer` scope, any `principle` or `warning` | After a named person approves, edits, or rejects it |

Approving shows the diff, the reason, the evidence (each episode links to the review screen or the document page)
and the dev score before and after.

## 7. Read path: how it is used

| Consumer | What it gets | How |
|---|---|---|
| Readers (setup steps) | The `rules/` of active skills whose `applies_to` matches the step and whose scope is one of the project's | Loaded deterministically, no model; logged in the step's reading log |
| Model calls inside a step | Memory of the project's scopes (capped, so it fits) + the matching skill's body | Prepended to the prompt; `knowledge_use` records what was included |
| Mapper | Skills' `rules/conventions.yaml` per project scope | Same path as `apply_conventions` today |
| Agent | Global principles + project scopes' memory + person profile in the system prompt; skills index | Tools: `memory_search`, `skill_view(name, path?)`, `journal_search`, `propose` (proposes, never writes) |
| People | Everything | The Memory and skills page (§8) and panels in context |

Skills load the way Hermes skills do: the index (name, description, scope) is always available; the body only when
chosen; a reference file only when asked for. Memory is a frozen snapshot per task, so a change mid-task applies to
the next task.

## 8. UI

A new page under **Shared knowledge**: **Memory and skills**, with tabs, in the app's usual header and cards.

- **Memory**: one card per scope (global first, then the scopes of the active project), each with its cap gauge.
  Entries show kind, text, who taught it, when, the evidence (click through), uses, and Lock / Edit / Retire.
- **Skills**: a list with name, scope, version, status, uses and last change. Opening one shows the rendered
  `SKILL.md`, its rules as tables, its version history with diffs, and Revert.
- **Pending**: proposals waiting for a person, newest first, each with the reason, evidence, diff and dev score;
  Approve, Edit then approve, Reject (with a reason the curator sees next time).
- **Activity**: what was learned, applied or reverted, by whom or by which model, with Undo for auto-lane changes.
- **People**: each person's profile, editable by that person.

In context:

- Project header: "What we know here" popover with the memory of this project's scopes.
- Review screen: when a fix matches a pattern made before, "This is the 3rd time: the curator will propose a rule."
- Guided setup: after the designer and contractor are recognised, "Using: read-example-mep-firm-schedules v3".
- **Teach** button on every page: a short form ("Remember that…", scope picker) that writes a `teach` episode.

## 9. Seed content

Written by us before M5, so the layer is useful on day one and the curator learns the style.

Global principles (examples):

- Design documents state intent; the controls submittal and the BMS state what is installed. When they disagree,
  record both and ask.
- Every fact keeps its source and method. A fact with no source is not added.
- Choose the most specific class the evidence supports, never more specific than that.
- A point is not auto-accepted unless it is linked to equipment.
- Keep source units; convert only in views.

Skills to write first: `read-metasys-submittal` (contractor), `read-troop-d-designer-schedules` (designer, from
today's `LAYOUTS`), `classify-vav-points` (global), `troubleshoot-warm-zone` (global, the agent tour's walk as a
procedure: zone temperature → VAV damper and airflow → AHU discharge air → chilled water plant → chillers).

## 10. Build phases

| # | Phase | Done when |
|---|---|---|
| M1 | **Files and loader.** `knowledge/` folders, YAML schemas, loader with scopes, caps and knowledge-model checks; seed content (§9); tests | Files load and validate; a bad class or an over-cap file fails with a clear message |
| M2 | **Memory and skills page.** Browse, edit, lock, retire, history, Teach button | A person can read and edit every entry and skill, and changes land in the files |
| M3 | **Read path.** Readers and mapper load `rules/` by project scope; `LAYOUTS` and `conventions/` move into skills | Troop D and Alpha score exactly as before (parity), with rules now coming from skills |
| M4 | **Journal.** Episodes from review batches, setup answers, publishing, notes, Teach; FTS5 search | Every trigger writes an episode; search finds them by word |
| M5 | **Curator.** Background job, proposal schema, checks, lanes, Pending tab, dev-score gate | Making the same fix 3 times in review produces a proposal; once approved, the 4th case is fixed by the rule; the dev score does not drop |
| M6 | **Agent use.** Memory in the agent's context, `memory_search`, `skill_view`, `journal_search`, `propose` | The agent cites the memory entry or skill it used, and a correction in chat becomes a pending proposal |

Measures, added to the score report: corrections per 1,000 points on each new building (should fall), share of
facts read by rules rather than models (should rise), proposals approved vs rejected, entries reverted.

## 11. Open questions

1. **Durable storage on GCP.** When the app moves to GCP: `knowledge/` in Cloud Storage or committed through pull
   requests, journal and proposals in Cloud SQL? Until then learning happens locally and is committed.
2. **Who approves global and designer scope?** Proposal: any named person for site and contractor; a named lead for
   global and designer.
3. **Designer recognition.** Title blocks name the firm on most sheets; is a rule enough, or does it need the vision
   model as a fallback?
4. **Agent Platform Memory Bank** for the agent's conversational memory (per person, across chats) once the agent is
   live: worth it alongside our files, or redundant?
5. **Search quality.** FTS5 first. If the curator misses related entries, add embeddings (Vertex AI text embeddings)
   to the conflict check only.
6. **Sharing skills across organisations.** Skills are agentskills.io compatible, so a curated skill library could
   be a product in itself. Out of scope until asked.

## 12. Sources

- Hermes Agent docs, memory: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- Hermes Agent docs, skills: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- Hermes Agent repository: https://github.com/nousresearch/hermes-agent
- Inside Hermes Agent: how self-improving skills work: https://fp8.co/articles/Inside-Hermes-Agent-Self-Improving-Skill-Memory
- Practice Makes Unsafe: Skill Misevolution in Self-Improving LLM Agents: https://arxiv.org/pdf/2608.12851
- Agent Platform Memory Bank setup: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/setup
