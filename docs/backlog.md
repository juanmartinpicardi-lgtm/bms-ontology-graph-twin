# Backlog — captured requirements

Small requirements captured on 2026-11-26. **All 14 built on 2026-11-26** (branch `ui-backlog`, not yet committed); the status line under each item says where.

## Captured 2026-11-26

1. **Light mode everywhere.** Switching to light mode must turn the whole app light. Today the top bar and the right panel stay dark.
    - **Done.** Top bar, rail and agent panel follow the theme (`app/shell.py`, `NAV_THEME`).
2. **"Needs you" moves to the right panel.** When uploading PDFs and reviewing, the "Needs you" section should be a tab in the right panel, not in the left panel. The right panel already has a **Review** tab: if both serve the same purpose, keep only one.
    - **Done.** Questions from the document being read now sit in the right panel's **Review** tab, above the whole building's; the left box links to them (`add_building.py`).
3. **Import other files in step 7 (Knowledge).** The Knowledge step should let the user import more file types, not just the current ones.
    - **Done.** Knowledge › **From a file** takes any common file; a model proposes tag rules, terms and notes, each with a quote, and you tick the ones to add (`file_ai.propose_knowledge`, job `knowledge_extract`).
4. **Import any common file type, app-wide.** Accept at least the most common file types everywhere files are uploaded, and build the intelligence to process and interpret each type.
    - **Done.** `fileread.py` opens PDF, Word, Excel, PowerPoint, OpenDocument, images, email, CSV and text; images become PDF pages and Excel becomes CSV where a step needs it.
5. **Equipment view: 3D / 2D toggle.** Show either the 3D or the 2D view, switched with a toggle, instead of both on the same screen.
    - **Done.** Segmented toggle 3D model / 2D graphic, also as `?view=2d` (`views/equipment_3d.py`).
6. **Rename the "Equipment 3D" tab to "Equipments".**
    - **Done.** Renamed everywhere it is shown; the URL stays `Equipment_3D` so old links work.
7. **System graphics: better visuals and a short explanation.** The user likes the system graphics (Graphics page, "System graphics" box: the air-side and water-side drawings built from the graph's `feeds` edges, `src/projectmodel/graphics/system.py`). Improve how they look, and add a short note on the page that says what a system graphic is and why it is needed.
    - **Done.** Water side: plant systems side by side, the plant chain, then each source's terminal units in a grid off one header; air side: one band per air handler; natural sort, legend, zone status dots. Short what/why text on the tab (`graphics/system.py`, `views/graphics.py`).
8. **Sequences > Simulate: improve the diagram.** The visual diagram in Simulate mode (`src/projectmodel/app/sequences.html`, where the sequence runs through the graph node by node and link by link) needs better visuals.
    - **Done.** Equipment as cards holding their points as chips (role or intended value on each), links edge to edge with a pulse when a step reaches a point; fits the panel (`app/sequences.html`).
9. **New per-project "Documentation" section.** Each project gets a Documentation section listing all of its uploaded documents:
   - A clean, presentable layout, with documents grouped by category.
   - Upload more documents from here.
   - Switch between a list view and a large-icon view that shows a preview of each document.
   - Per-document actions: download, delete, replace, and similar file actions.
    - **Done.** New **Documentation** tab: categories, search, grid with previews or list, open, download, replace, recategorise, delete (setup files re-read their step), and "What is this document?" (`library.py`, `views/documentation.py`, job `document_digest`).
10. **End-to-end review of the Overview pages.** Go through every Overview page (The idea, Why it matters, How it works, Ontology, Roadmap, Complete graph, Answer keys, Agent tour; listed in `src/projectmodel/app/main.py`) and bring each one up to date with the latest requirements, current build status and any architecture changes.
    - **Done.** How it works (documents as a source, every view incl. Graphics and Documentation, agent built), Ontology (controllers and networks as nodes, Site/Building done, SHACL export done), Complete graph (document sources read now), Roadmap (any-file reading under W6). The Answer keys page had already been removed.
11. **New Overview tab: "Architecture".** A page that explains how the app works as a clean, simple architecture diagram. Give the right amount of technical detail (main components, data flow, where the knowledge model, graph, AI and review fit) without overloading the page. Note: "How it works" already exists; the new tab should stay distinct (technical architecture) or the two should be merged, decided during item 10.
    - **Done.** New **Overview › Architecture**: six steps in a line, three helpers underneath, principles, where data lives, stack. Kept distinct from How it works (that one is the story, this one the parts). Same words the agent reads (`agent/foundations.py`).
12. **Add a building: remove the "How it works" box.** Drop the right-hand "How it works" box from the Add a building page (`src/projectmodel/app/views/add_building.py:157`).
    - **Done.** Removed; the start screen is now the new-building form, buildings in progress, and the example projects.
13. **AI agent: knows all projects and the app's foundations.** Today the agent works on one building at a time and is absent from the Overview pages (`src/projectmodel/app/main.py:125`, `dock.py`). Extend it so it:
    - Sees general information about all of the user's projects (names, status, sizes, progress), not only the open one.
    - Understands the foundations of the app: everything on the Overview pages (the idea, why it matters, how it works, ontology, roadmap, architecture, etc.).
    - Can coach the user and answer questions about the app and their portfolio, including from the Overview area.
    - **Done.** The agent is on every page. Its instructions now carry the app's foundations (words, architecture, pages, setup steps, examples, roadmap status) and every project and building in progress, rebuilt from the store (`agent/foundations.py`, `Agent(app_context=…)`). On the Overview it offers app and portfolio questions.
14. **Add a building: three example projects to pick from.** Today each guided-setup step offers one example file, always from Troop D (`test_packages/troop_d/`, `add_building.py:1214`). Change it to:
    - A collapsible section, e.g. **"Example project documents"**, on the new-project screen that offers three open-source projects to start from.
    - Once one is chosen (say Project 1), every later step shows only that project's documents, never another project's. One new project must never mix documents from two example projects.
    - Make the choice easy to read: which project is selected, what building it is, and which of its documents each step uses.
    - Use the open-source sets already researched (`docs/real-document-sets.md`, files in `data/raw/`). Suggested three: **Troop D** (current worked example), **`msu_mbb`** (Montana State lab and office renovation) and **`itd_d1_lab`** (Idaho DOT testing laboratory).
    - **Do not use `liberty_boe`.** It is the held-out test set (`CLAUDE.md` §5): offering it in the app would expose its documents and results, and it would no longer count as held out. If a third non-Troop D set is wanted, the Vermillion County Jail set (first choice for a fourth set in `docs/real-document-sets.md`) is the candidate.
    - Each example project's steps need a document for each step where one exists. None of the real sets has a controls submittal or BMS export (only design points lists on the drawings), so the UI must say clearly when a step has no example document for that project.
    - **Done.** **Example project documents** (collapsible) on the start screen: Troop D, MSU Molecular Bioscience Building, ITD District 1 lab. A building remembers its example and each step offers only that project's document, or says why there is none (`intake/examples.py`). `liberty_boe` stays held out.
