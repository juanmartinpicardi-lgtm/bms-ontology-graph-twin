# Spec – Submittals to graph: workflow and architecture readiness v0.1

Status: the 8 steps agreed 2026-11-15; step 0, the four layers and §7 still to agree. Nothing in this spec is built yet. Vocabulary as in `CLAUDE.md` §2.

## 1. Goal

A user drops a project's documents and gets, with one review pass, the same thing Alpha has today from a
BMS export, plus what Alpha lacks: spaces, nameplate data and sequences on every unit.

Documents are a source like any other: read only, never written back, every fact traceable to a file
and page.

## 2. The workflow, step by step

| # | Step | Goes in | Comes out | Example |
|---|---|---|---|---|
| 0 | **Locate the building** | A name or address typed by the user | The site: confirmed address, latitude and longitude, a map to navigate | "Hugo, CO" → full address, 39.14, -103.47 |
| 1 | **Drop documents** | Submittal package (PDF), floor plans, a BMS export if one exists | Files stored untouched, one project | `data/raw/<site>/submittal.pdf` |
| 2 | **Read and sort pages** | Every page | A type per page (equipment schedule, points list, sequence, floor plan, schematic, cut sheet, other) and its text and tables | "p. 14: VAV schedule, 138 rows" |
| 3 | **Build the assets** | Schedules and points lists | Equipment nodes (tag, type, capacity, make/model) and point nodes (name, type, unit, range), each proposed | `VAV-2-81`, 450 cfm, 11 points |
| 4 | **Place them in the building** | Floor plans, the "serves" column of schedules | Floors, rooms, zones; `hasLocation` and "serves" links | "VAV-2-81 serves room 2.14, level 2" |
| 5 | **Connect** | Air and water schematics, schedules, the BMS export | `feeds` and `hasPart` links; one node per real thing when two sources name it | "AHU-2 feeds VAV-2-81"; `VAV-2-81` (schedule) = `VAV 1-2-81` (BMS) |
| 6 | **Attach the sequences** | Sequence of operations pages | One sequence per equipment type, applied to every unit of that type: loops, interlocks, resets, setpoints as data; gaps and conflicts listed | "Airflow loop on 138 VAVs; 4 boxes have no reheat valve" |
| 7 | **Review** | Everything proposed | Confirmed, fixed or rejected facts, each shown next to its source page | Reviewer accepts 138 VAVs in one click |
| 8 | **Use** | The confirmed graph | Equipment graphics, digital twin with real floors, agent tools, checks | "Zone 2.14 is too warm" answered from the graph |

Order matters: assets (3) before spaces (4) and links (5), because a floor plan or schematic is read by
looking for tags already known. Sequences (6) come last, because they bind to points that must exist.

Steps 2 to 6 propose; only step 7 confirms. An LLM is used in steps 2, 3, 5 and 6, always with a short
list of candidates from the knowledge model and always logged (`llm_calls`).

## 3. The four layers the workflow fills

The workflow does not only produce "a graph". It fills four layers, and each has its own source and its
own page in the app.

| Layer | What it is | How we get it | Filled by steps | Seen in the app | Today |
|---|---|---|---|---|---|
| **Graph** | Nodes and edges, with no meaning yet: every tag, name, folder and page reference found in the sources | Automatically: adapters turn each row or page item into a raw record; nothing is interpreted | 0, 1, 2 | Data tables, Graph 3D | Works for one BMS export |
| **Knowledge graph** | The same nodes with a type and typed relationships (`hasPoint`, `hasPart`, `feeds`, `hasLocation`, behaviour links), each with source, method and confidence | The mapper applies the knowledge model to the graph; documents add what the BMS does not carry; review confirms | 3, 4, 5, 6, 7 | Tree, Equipment 3D, Sequences, Digital twin | Equipment and points strong; spaces missing; behaviour on 13 of 184 equipment |
| **Knowledge model** | The definitions shared by every project: Brick classes, equipment templates, name rules, validation rules | We maintain it (`/knowledge_model`). It does not come from a project. It grows when the same correction shows up on several projects, or when a submittal has an equipment type with no template | Used by 3 to 6; improved after 7 | Knowledge model | 6 templates; 28 of Alpha's 184 equipment have none |
| **Tribal knowledge** | What only the people know: naming habits of a contractor, customer or site (conventions), and facts about the building (notes) | From people: typed as notes, or proposed from repeated review fixes and accepted by a person. Later: interviews | Captured at 7, applied at 3 on the next run | Tribal knowledge, Notes | Conventions work (1 site file); notes table exists (empty); learning from fixes is specified, not built (`spec-tribal-knowledge.md` T3) |

How they relate: the knowledge model and tribal knowledge are the two inputs that turn a graph into a
knowledge graph. The knowledge model is true everywhere; tribal knowledge is true for one contractor,
customer or site. A review fix first lives in the knowledge graph (one project), may be promoted to a
convention (tribal), and then to the knowledge model.

## 4. Step 0: locate the building

The user types a building name or address, picks the right result, and confirms the pin on a map. The
site becomes the root node of the project.

| What | Google Maps Platform service | Stored on the site node |
|---|---|---|
| Search as you type | Places API (Autocomplete) | Place id |
| Address and coordinates | Geocoding API | Formatted address, address parts (street, city, region, postcode, country), latitude, longitude |
| Map to navigate | Maps JavaScript API (2D, satellite) | Nothing: display only |
| 3D view of the surroundings (the Google Earth look) | Map Tiles API, Photorealistic 3D Tiles | Nothing: display only |

What the location is used for later: outdoor conditions and climate zone for the sequences, the building's
orientation for the floor plans, and placing the digital twin on the map.

To decide and to check before building:

- It needs a Google Maps Platform API key with billing, kept in Streamlit secrets, never in git.
- The address is sent to Google: the only step where project data leaves the app. Data still flows one
  way (nothing is written to a source), but this must be acceptable for customer projects.
- Google's terms limit how long geocoding results may be stored; the place id may be kept. To check
  against the current terms before storing coordinates.
- Google Earth itself has no embeddable service; Photorealistic 3D Tiles are the equivalent. Coverage
  for a given address is to be checked (Hugo, CO may not have it).

## 5. Architecture readiness

Readiness: **ready** (works today), **partial** (the foundation is there, needs extending), **missing**.

| # | Step | Readiness | What exists | What is missing |
|---|---|---|---|---|
| 0 | Locate the building | partial | Location page (`app/views/location.py`, `locate.py`): search by Google Geocoding or OpenStreetMap, a person confirms, address parts and coordinates stored per site (`sites` table); Google map with 3D view, or OpenStreetMap without a key | Search as you type (Places Autocomplete); the site as a node of the graph (comes with space nodes); the Google path has not been run with a real key yet |
| 1 | Drop documents | missing | `data/raw/` convention; a disabled placeholder page (`app/views/new_project.py`) | Upload, a `documents` table (file, hash, pages), projects created at run time (`projects.SITES` is hard-coded) |
| 2 | Read and sort | missing | The `LLMProvider` interface and the `llm_calls` log (`mapper/llm.py`, `db/store.py`) | A real provider (only `none` exists), PDF text and table extraction, a page classifier, a `pages` table |
| 3 | Build assets | partial | Raw record shape with unit, kind, device and object id fields (`records.py`); the whole mapper; templates say which points a unit must have; `method=document` rows survive mapper runs | A document adapter producing raw records; equipment rows from a schedule (nameplate in `attrs`); the mapper ignores units and kind today |
| 4 | Place in building | missing | `hasLocation` is in the Brick subset; the twin page draws floors (inferred, rooms generated: `twin_view.py`) | Node kinds for site, floor, room, zone (`nodes.kind` allows only `point`, `equipment`); floor plan reading; the twin reading real spaces |
| 5 | Connect | partial | `feeds` and `hasPart` edges with medium and provenance; inference from templates | Merge: a project is one input file, and a mapper run deletes every machine row; ids are folder paths and row numbers; no "same as" between a document tag and a BMS name |
| 6 | Sequences | partial | Resolver that binds a sequence to graph nodes and reports gaps and conflicts; behaviour edges (`drives`, `feedback`, `requires`, `resets`, `requests`, `switches`) (`sequences.py`) | Sequences per equipment type, not per unit (today bound to one VAV by id); setpoints, limits and timers as data; extraction from text; sequence and document as nodes |
| 7 | Review | partial | Accept, reject, fix class, move point, with the reviewer recorded (`review.py`); `source_ref` can hold a page | A review queue: every machine row is written `confirmed` (`store.replace_machine_rows`), so nothing is ever `proposed`; showing the source page next to a fact |
| 8 | Use | mostly ready | Equipment 3D for 6 templates, digital twin, sequences page, agent tools (`agent_tools.py`) | 3D models for fans, cooling towers, heat exchangers; live values (all simulated today) |

## 6. Changes that several steps depend on

In build order. Each is small on its own; together they are what "ready for documents" means.

1. **Proposed before confirmed.** Machine rows are written `proposed`; a rule (confidence above a
   calibrated threshold, or a second source agreeing) or a person confirms them. Needed by step 7 and by
   every agent that must tell a checked fact from a guess.
2. **Stable ids and "same as".** An id that does not depend on a folder path or a row number, plus an
   alias table (tag in the schedule, name in the BMS, device and object id). Needed by step 5.
3. **Many sources per project.** A project becomes a building, not one file. Each source replaces only its
   own rows (documents already work this way: `replace_document_edges`). When two sources state the same
   fact, it is recorded as agreement; when they differ, as a conflict for review.
4. **More node kinds.** `space` (site, floor, room, zone), `document` and `sequence`, next to `point` and
   `equipment`. Controllers and networks are already classes in the BA extension.
5. **Sequences per type.** A sequence is written against a template's slot roles (`vav.damper`), then
   applied to every unit with that template. The demo document already uses role refs; what changes is
   that `bind` names a template, not one unit.
6. **An LLM provider and a document adapter.** Behind the existing interfaces.

## 7. To agree before building

- **The first document type.** Recommended: the points list and the equipment schedule (steps 2 and 3
  only), because they are tables, they are the closest to an answer key, and they can be scored against a
  BMS export of the same building.
- **A test building.** Alpha has no real documents. Step 2 onward needs one project with a real submittal
  package and its BMS export; without it nothing can be measured.
- **Floor plans.** Reading rooms from a PDF plan is the hardest and least certain step. Option: start with
  the "serves" column of schedules and room tags in zone names, and add plan geometry later.
- **Auto-accept.** Whether a fact two sources agree on is confirmed without a person.
