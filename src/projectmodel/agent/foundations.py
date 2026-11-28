"""What the agent knows about the app itself and about every project, so it can coach a person and answer "how does
this work", "where do I find…", "which of my projects…" on any page, the Overview included.

    foundations_text()     the app: idea, vocabulary, architecture, pages, guided setup, AI, roadmap status
    projects_text(store)   every project in the store and every building in the guided setup, with its counts

ARCHITECTURE and PAGES are also what the Overview's Architecture page draws, so the page and the agent say the same
thing. The roadmap status is read from roadmap.py, the project counts from the store: nothing here goes stale by hand.
"""
from __future__ import annotations

import time

# The architecture, left to right: what comes in, how it is read, mapped, stored, reviewed and used.
# (icon, name, what it does, where it lives in the code)
ARCHITECTURE = [
    ("input", "Inputs", "Exports and documents: Project Haystack exports now; plans, schedules, sequences, the "
                        "controls submittal and the BMS export of a building; any other file on the Documentation "
                        "tab. Niagara and CPO Studio later. Read only; a write-back only when you ask.",
     "data/raw · data/intake"),
    ("description", "Readers", "Thin adapters turn each source into one record shape (one per point); the guided "
                               "setup's readers turn each document into rooms, units, points and control logic; the "
                               "file reader opens PDF, Office, images, email and text.",
     "adapters/ · intake/ · fileread.py"),
    ("psychology", "Mapper", "Cheapest method first: structure, naming rules, equipment templates, then a model with "
                             "a short list of candidate classes. Every fact gets a confidence; calibrated thresholds "
                             "decide what goes to review.", "mapper/ · intake/point_ai.py"),
    ("hub", "Knowledge graph", "One graph per project: nodes and edges in SQLite, each with its source, method, "
                               "confidence, status and revision.", "db/store.py · data/kg.sqlite"),
    ("fact_check", "Review", "People accept, fix or reject proposals and answer the readers' questions. A correction "
                             "is saved with method human and becomes a rule for the next building.",
     "review.py · Add a building › Review"),
    ("dashboard", "Views and agent", "Every page reads the same graph: digital twin, tree, 3D graph, equipments, "
                                     "graphics, sequences, tables, documentation. The agent answers from it with "
                                     "read-only tools and cites every fact. Brick export with SHACL checks.",
     "app/ · agent/ · export/"),
]
# What runs beside the flow and feeds several steps.
SUPPORT = [
    ("account_tree", "Knowledge model", "Shared by every project: the Brick subset and our extension (classes, "
                                        "relations), equipment templates, name rules, units, validation shapes. "
                                        "Improves with every building.", "knowledge_model/"),
    ("groups", "Tribal knowledge", "Conventions, notes and the team's memory, shared or per site, proposed by a "
                                   "curator model and approved by a person.", "conventions.py · notes.py · memory.py"),
    ("smart_toy", "AI layer", "One router to Vertex AI (Claude and Gemini). Each job has a default model, a contender "
                              "and an escalation; prompts live in files; every call is logged with its input, output, "
                              "cost and time. PM_AI=off runs on rules only.", "ai/ · ai/prompts/"),
]
PRINCIPLES = [
    ("east", "One way by default", "Data flows from the sources into the app. The app writes back to a source tool "
                                   "only when you ask: it shows what will change, you confirm, and every write is "
                                   "logged. Files it makes for a tool to import are outputs, not write-back."),
    ("fingerprint", "Traceable", "Every node and link stores its source, method, confidence and status."),
    ("rule", "Rules first", "Rules and templates before a model; a model only gets a short list of candidates."),
    ("person_check", "People decide", "Low-confidence facts go to review; nothing a model says is final until a "
                                       "person or a rule confirms it."),
]
STACK = ["Python 3.11", "SQLite", "rdflib + brickschema (Brick, SHACL)", "Streamlit", "three.js (3D views)",
         "Vertex AI: Claude and Gemini", "pytest"]

# (area, page, what it is for)
PAGES = [
    ("Overview", "The idea", "The pitch: exports in, a knowledge graph of the building out."),
    ("Overview", "Why it matters", "The problem it solves for controls contractors and owners."),
    ("Overview", "How it works", "The pipeline step by step, the two layers, what every fact carries, the words used."),
    ("Overview", "Architecture", "The components and how data moves between them."),
    ("Overview", "Ontology", "The Brick classes and relations used, and our extension."),
    ("Overview", "Roadmap", "Each workflow stage: what rules, models and people do today and next; work packages."),
    ("Overview", "Complete graph", "What a complete graph of a building must hold, and how each project scores."),
    ("Overview", "Agent tour", "Recorded agent walks on Alpha: root cause, functional test, impact, tribal knowledge."),
    ("Projects", "All projects", "Every building with its counts; open one."),
    ("Projects", "Add a building", "The guided setup: start from your own documents or one of three example "
                                   "projects, then read plans, schedules, sequences, submittal, BMS export, review."),
    ("Project", "Digital twin", "The building floor by floor, units in their rooms, simulated values."),
    ("Project", "Location", "Where the building is, on a map."),
    ("Project", "Tree", "Equipment, parts and points, with the provenance of every node."),
    ("Project", "Graph 3D", "The whole graph in space."),
    ("Project", "Equipments", "One unit at a time as its 3D model, points pinned on it, simulated values."),
    ("Project", "Graphics", "Coverage per equipment type (3D model, points on anchors), floor graphics and system "
                            "graphics (water and air side)."),
    ("Project", "Sequences", "Sequences of operation linked to the graph: Read, or Simulate a step-by-step walk."),
    ("Project", "Data tables", "Points, equipment and links as tables."),
    ("Project", "Documentation", "Every document of the project by category: preview, download, replace, delete, add "
                                 "more; a model can say what a document is."),
    ("Project", "Notes", "Notes on the building and its equipment."),
    ("Project", "Tribal knowledge", "This site's conventions and habits."),
    ("Shared knowledge", "Knowledge model", "The classes, templates and rules shared by every project."),
    ("Shared knowledge", "Tribal knowledge", "Conventions shared across projects, and the curator's proposals."),
]

VOCABULARY = [
    ("Graph", "Nodes and edges. No meaning on its own."),
    ("Knowledge model", "The definitions: kinds of things, how they relate, rules to recognise them. Same for every "
                        "project."),
    ("Ontology", "The classes-and-relations part of the knowledge model (Brick subset + our extension)."),
    ("Knowledge graph", "One building's graph, built with the knowledge model, every fact with its provenance."),
    ("Tribal knowledge", "What engineers know that isn't written down: conventions and notes, shared or per site."),
    ("Digital twin", "Knowledge graph + state + views."),
]


def _roadmap() -> str:
    from ..roadmap import PACKAGES, STAGES
    pk = "\n".join(f"- {p['id']} {p['name']}: {p['status']}. {p.get('plain', '')}" for p in PACKAGES)
    st = "\n".join(f"- {s['n']}. {s['name']}: rules {s['rules']}; model {s['model']}; people {s['people']}."
                   for s in STAGES)
    return f"Work packages:\n{pk}\n\nWorkflow stages (who does what):\n{st}"


def foundations_text() -> str:
    from ..intake.examples import EXAMPLES
    from ..intake.steps import STEPS
    arch = "\n".join(f"{i + 1}. {n}: {t} ({w})" for i, (_, n, t, w) in enumerate(ARCHITECTURE))
    sup = "\n".join(f"- {n}: {t} ({w})" for _, n, t, w in SUPPORT)
    pages = "\n".join(f"- {a} › {p}: {t}" for a, p, t in PAGES)
    steps = ", ".join(f"{s.n}. {s.title}" for s in STEPS)
    ex = "\n".join(f"- {e.name} ({e.place}): {e.kind}. Documents for: "
                   + ", ".join(sorted(e.docs)) for e in EXAMPLES.values())
    words = "\n".join(f"- {w}: {d}" for w, d in VOCABULARY)
    return f"""The app ("Graph and Ontology Builder") turns a building's engineering exports and documents into a
reviewed knowledge graph, using a shared knowledge model, and measures how good it is. It is a prototype: no login
yet, no write-back to a tool built yet (it will only happen when the user asks, with a preview, a confirm and
a log), values are simulated (no live BMS connection yet).

Words:
{words}

Architecture, in the order data flows:
{arch}
Beside the flow:
{sup}
Principles: {"; ".join(f"{n}: {t}" for _, n, t in PRINCIPLES)}
Stack: {", ".join(STACK)}.

Pages (area › page):
{pages}

Guided setup (Projects › Add a building) steps: {steps}. A building can start from one of three open example
projects (only that project's documents are offered at each step):
{ex}

Status:
{_roadmap()}"""


def _day(at) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(at)) if isinstance(at, (int, float)) else str(at)[:10]


def projects_text(store) -> str:
    """Every project in the store and every building in the guided setup, one line each."""
    from ..intake.state import Intake, list_intakes
    from ..projects import label, list_projects, main_projects, site_of, summaries
    sm = summaries(store)
    lines = []
    for p in main_projects(list_projects(store)):
        s, site = sm.get(p, {}), site_of(p)
        n, links = s.get("nodes", {}), s.get("links", {})
        lines.append(f"- {label(p)} (id {p}): {site.kind or 'building'}"
                     + (f", {site.location}" if site.location else "")
                     + f"; {n.get('equipment', 0):,} equipment, {n.get('point', 0):,} points, "
                       f"{sum(links.values()):,} links; {s.get('human', 0)} human decisions"
                     + (f"; last mapped {_day(s['mapped_at'])}" if s.get("mapped_at") else ""))
    setup = []
    for row in list_intakes():
        it = Intake(row["slug"])
        if not it.s:
            continue
        done = [k for k in ("plans", "schedules", "sequences", "submittal", "bms") if it.done(k)]
        setup.append(f"- {it.name}: steps done {', '.join(done) or 'none'}"
                     + (f"; started from the example {it.example}" if it.example else ""))
    out = "Projects in the app:\n" + ("\n".join(lines) or "- none mapped yet")
    if setup:
        out += "\n\nBuildings in the guided setup:\n" + "\n".join(setup)
    return out
