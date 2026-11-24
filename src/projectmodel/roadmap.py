"""The roadmap in data: the workflow stages with who does what (rules, a model, a person) today and next, the
principles for using AI, and the work packages of docs/plan-workflow-ai.md with their status.

The Roadmap page (app/views/roadmap.py) draws from here, and progress.py points each missing fact of a project at
the package that builds it. Update a package's status and parts here when its work lands.
"""
from __future__ import annotations

# Per stage: what rules do, what a model does (today, then next), what a person does.
# ai: "now" = a model runs in this stage today | "next" = planned | "never" = rules only, by design.
STAGES = [
    {"n": 1, "name": "Floor plans", "icon": "map", "ai": "next",
     "rules": "Floor from the sheet title, rooms from labels, tags by pattern",
     "model": "Read the drawing: room outlines, which room a tag sits in, symbols, zones, scanned sheets",
     "people": "Answer the asks on the plan"},
    {"n": 2, "name": "Schedules", "icon": "table_rows", "ai": "next",
     "rules": "Rows by tag, known table layouts, cross-checks",
     "model": "Learn a new firm's table layout once; rules read it after that",
     "people": "Approve the layout"},
    {"n": 3, "name": "Sequences", "icon": "sync_alt", "ai": "next",
     "rules": "Headings, setpoints with units, phrases that name points",
     "model": "Turn prose into loops, interlocks, resets and modes",
     "people": "Confirm the logic"},
    {"n": 4, "name": "Submittal and riser", "icon": "lan", "ai": "next",
     "rules": "Controller rows, point references, typicals",
     "model": "Read riser diagrams drawn as pictures, and odd point tables",
     "people": "Answer the asks"},
    {"n": 5, "name": "BMS points", "icon": "sensors", "ai": "now",
     "rules": "Columns by name, naming rules, equipment templates",
     "model": "Classify the points rules can't (built: point_class)",
     "people": "Review what is below the threshold"},
    {"n": 6, "name": "Point binding", "icon": "link", "ai": "next",
     "rules": "Same reference, same tag, same device",
     "model": "Pick the match from a short list when names don't line up",
     "people": "Confirm below the threshold"},
    {"n": 7, "name": "Review", "icon": "fact_check", "ai": "next",
     "rules": "Calibrated thresholds, agreement between two sources (built)",
     "model": "Order the queue, explain each proposal in one line",
     "people": "Decide"},
    {"n": 8, "name": "Graphics", "icon": "view_in_ar", "ai": "next",
     "rules": "Renderers draw from the graph; points sit on template anchors",
     "model": "Write new equipment builders as code; check each graphic against the graph",
     "people": "Approve new builders"},
    {"n": 9, "name": "Tribal knowledge", "icon": "groups", "ai": "next",
     "rules": "Conventions, setup rules, notes",
     "model": "Turn repeated fixes into proposed conventions; interview the site team",
     "people": "Approve"},
    {"n": 10, "name": "Agent", "icon": "smart_toy", "ai": "now",
     "rules": "Graph tools",
     "model": "Answer, diagnose and check, citing sources (built)",
     "people": "Confirm any change"},
    {"n": 11, "name": "Export and validation", "icon": "verified", "ai": "never",
     "rules": "Brick export and SHACL rules on every import",
     "model": "None: validation stays exact",
     "people": "Read the report"},
]

PRINCIPLES = [
    ("checklist", "Candidates in, ids out",
     "A model picks from our list (rooms, tags, points, classes). It never invents a name, a class or a position."),
    ("school", "Read once per firm, then rules",
     "A model learns a new firm's style once; a person approves it; rules do the work from then on."),
    ("rule", "Rules check every answer",
     "The middle of the pipeline stays exact. A model's answer is a proposal, with a confidence, never a fact."),
    ("person_check", "People decide",
     "Anything unsure becomes a question next to its source page. Nothing is confirmed silently."),
    ("speed", "Measured before it ships",
     "Every model job beats rules alone on a scorer, with honest confidence and a cost per building."),
    ("visibility", "Never a silent zero",
     "When a reader finds nothing, it says so and asks. That rule shipped first."),
]

# status: done | doing | next | later. parts: (what, done?) for the package in progress.
PACKAGES = [
    {"id": "W0", "name": "Guardrails and real test sets", "wave": 1, "status": "done",
     "plain": "Every reader says when it found nothing; the stress suite runs as a test; three real sets to measure "
              "on.",
     "parts": [("Coverage checks in every step", True), ("Stress suite as a test", True),
               ("Rule fixes: FLR titles, Niagara columns, device instance, 4-digit rooms", True),
               ("Partial-read checks: say so when a step reads only part", True),
               ("Numbered sequence sections", True),
               ("AI point classification in the setup: 51% → 74% exact on Troop D", True),
               ("3 real document sets, 1 held out", True)]},
    {"id": "W1", "name": "Ontology fixes", "wave": 1, "status": "done",
     "plain": "Every term the app writes is declared: no off-standard relations or unchecked classes left.",
     "parts": [("Control relations and serves declared in the BA extension", True),
               ("Floor, Room, Zone, Building, Site as RealEstateCore locations", True),
               ("RVAV, Unit_Heater and 16 missing point classes", True),
               ("Loader refuses an undeclared term", True),
               ("Troop D point class, rules alone: 51% → 61% exact", True)]},
    {"id": "W3", "name": "Data model for many sources", "wave": 1, "status": "done",
     "plain": "Every fact is proposed until two sources agree, a calibrated score clears 0.9, or a person decides.",
     "parts": [("Each source replaces only its own rows", True),
               ("Aliases: schedule tag, BMS name, device and object, submittal reference", True),
               ("Agreement and conflict between sources", True),
               ("Troop D: 828 of 828 point links confirmed by two sources", True),
               ("Review queue shows only proposed facts, conflicts first", True)]},
    {"id": "W5", "name": "Eval harness and calibration", "wave": 1, "status": "done",
     "plain": "One command scores each AI job; 90% sure now means right 9 times in 10.",
     "parts": [("scripts/eval.py for mapper, setup readers and point_class", True),
               ("Calibration per job, every band of 30+ within 5 points", True),
               ("Alpha's 0.9–1.0 band: 50% → 99% right", True),
               ("Bake-off rule as code; model calls time out and retry", True)]},
    {"id": "W2", "name": "Export and SHACL", "wave": 2, "status": "doing",
     "plain": "Each project as Brick Turtle, checked by the building rules on every import."},
    {"id": "W4", "name": "Nodes from what we already read", "wave": 2, "status": "doing",
     "plain": "Site, zones, controllers and networks as nodes; units on points."},
    {"id": "W6", "name": "AI document reader, plans first", "wave": 2, "status": "doing",
     "plain": "A model reads drawings the rules can't: room outlines, tags, scans; then schedules."},
    {"id": "W8", "name": "Sequences with AI", "wave": 2, "status": "doing",
     "plain": "Sequence prose becomes loops, interlocks, resets and modes in the graph."},
    {"id": "W7", "name": "Riser and point binding with AI", "wave": 3, "status": "later",
     "plain": "The same point tied across BMS, submittal, equipment and graphic."},
    {"id": "W9", "name": "Graphics creation", "wave": 3, "status": "later",
     "plain": "Equipment, floor and system graphics generated from the graph, points bound."},
    {"id": "W10", "name": "Learning loop", "wave": 3, "status": "later",
     "plain": "A fix made twice becomes a proposed convention for the next building."},
    {"id": "W11", "name": "Agent tools", "wave": 3, "status": "later",
     "plain": "\"Does AHU-1 run as designed?\" answered with cited steps."},
    {"id": "W12", "name": "Tool adapters", "wave": 4, "status": "later",
     "plain": "Niagara and CPO Studio exports, merged on device id, when access exists."},
]
BY_ID = {p["id"]: p for p in PACKAGES}

# The real dev sets (docs/real-document-sets.md) with a person's approximate hand counts, to show the reports'
# numbers against. The held-out set (liberty_boe) is never shown in detail.
REAL_SETS = {
    "msu_mbb": {"name": "Montana State University lab renovation", "rooms": 39, "equipment": 80, "sequences": 2},
    "itd_d1_lab": {"name": "Idaho DOT District 1 testing lab", "rooms": 27, "equipment": 70, "sequences": 6},
}
WAVES = {1: "First wave · done", 2: "Second wave · now", 3: "Third wave", 4: "When access exists"}
