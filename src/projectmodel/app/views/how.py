"""How it works: the pipeline step by step, the two layers (shared vs per project), and what every fact carries.
A scroll-synced story (app/story.py); every number on it is read from the knowledge model or the graph."""

import json
import sys
from collections import Counter
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import get_store, knowledge_model  # noqa: E402
from projectmodel.app.story import (Go, Section, bars, chips, features, glossary, hero, icon, p, record,  # noqa: E402
                                   stats, story, tiles)
from projectmodel.projects import DEFAULT, label, list_projects, summaries  # noqa: E402
from projectmodel.tree import provenance  # noqa: E402

km = knowledge_model()
store = get_store()
projects = list_projects(store)
project = (DEFAULT if DEFAULT in projects else projects[0]) if projects else None
info = summaries(store).get(project, {}) if project else {}
points = list(store.nodes(project, "point")) if project else []
example = next((n for n in points if n["label"] == "Clg_Valve_Cmd"), None) or next(iter(points), None)
NOT_MAPPED = '<p class="cap">Map a project to see this on real data</p>'

# 1 · Connect: the sources, and one real record as the adapter hands it over.
sources = ('<div class="srcs rise" style="--i:0"><span class="src">Project Haystack<small>now</small></span>'
           '<span class="src later">Niagara<small>next</small></span>'
           '<span class="src later">CPO Studio<small>next</small></span></div><div class="arrow"></div>')
if example:
    attrs = json.loads(example["attrs"] or "{}")
    connect = record(f'{icon("description")}<b>One record per point</b>', [
        ("name", example["label"]), ("folder", attrs.get("path") or "none"),
        ("source", f"{Path(example['source_file']).name} · row {example['source_ref']}")],
        "The same shape whatever the tool. Nothing is written back.")
else:
    connect = NOT_MAPPED

# 2 · Understand: which method decided each point's class, counted on the graph.
METHODS = [("parsed", "Structure", "Read straight from the export"),
           ("rule", "Naming rules", "Abbreviations and patterns in the name"),
           ("template", "Equipment templates", "The group of points looks like an AHU, a VAV..."),
           ("llm", "LLM", "Only for what is left, from a short list of candidate classes"),
           ("human", "Human review", "Corrections a person saved")]
by_method = Counter(n["method"] for n in points)
understand = (f'<div class="stack"><span class="cap">How {escape(label(project))} got its classes</span>'
              + bars([(name, note, by_method[m]) for m, name, note in METHODS if by_method[m] or m != "parsed"],
                     "points") + "</div>") if points else NOT_MAPPED

# 3 · Build the graph: its size, and the kinds of link it holds.
links = info.get("links", {})
if info:
    kinds = "".join(f'<span class="chip rise" style="--i:{i + 3}"><b>{n:,}</b> {escape(k)}</span>'
                    for i, (k, n) in enumerate(sorted(links.items(), key=lambda kv: -kv[1])))
    graph = ('<div class="stack">' + stats([(f"{info['nodes'].get('equipment', 0):,}", "equipment"),
                                            (f"{info['nodes'].get('point', 0):,}", "points"),
                                            (f"{sum(links.values()):,}", "links")])
             + f'<span class="cap">Kinds of link</span><div class="chips">{kinds}</div></div>')
else:
    graph = NOT_MAPPED

# 4 · Use: the views the graph powers; each tile opens its page.
views = [("account_tree", "Tree", "Equipment, parts and points.", "tree_app.py"),
         ("bubble_chart", "Graph 3D", "The whole graph in space.", "views/graph_3d.py"),
         ("view_in_ar", "Equipment 3D", "One machine, its points live.", "views/equipment_3d.py"),
         ("sync_alt", "Sequences", "How the equipment is controlled.", "views/sequences.py"),
         ("table", "Data tables", "Points, equipment, links.", "views/data_tables.py"),
         ("domain", "Digital twin", "The building, floor by floor.", "views/digital_twin.py")]
use = tiles([v[:3] for v in views], [Go(v[1], v[3]) for v in views])

# 5 · Two layers: what is shared by every project, what belongs to one.
layers = (f'<div class="layers"><div class="layer top rise" style="--i:0"><h4>{icon("public")}Shared across all '
          'projects</h4>'
          + chips([f"{len(km.classes)} classes", f"{len(km.templates)} equipment templates",
                   f"{len(km.name_rules.abbreviations)} abbreviations", "Contractor and customer conventions"])
          + f'</div><div class="between"><span>{icon("south")}used to map</span>'
            f'<span>{icon("north")}good habits promoted</span></div>'
            f'<div class="layer rise" style="--i:2"><h4>{icon("apartment")}Inside each project</h4>'
          + chips(["Building graph", "Graphics", "Data tables", "Site conventions and notes"], 2) + "</div></div>")

# 6 · Traceable: one real point, as stored.
trace = record(f'<code>{escape(example["label"])}</code><span class="tag">{escape(example["class"] or "unknown")}'
               '</span>', list(provenance(example).items()), f"As stored in {label(project)}.") \
    if example else NOT_MAPPED

WORDS = glossary([
    ("Graph", "Nodes and edges. No meaning on its own."),
    ("Knowledge model", "The definitions: kinds of things, how they relate, rules to recognise them. Same for "
                        "every project."),
    ("Ontology", "The classes-and-relations part of the knowledge model (Brick + our extension)."),
    ("Knowledge graph", "One building's graph, built with the knowledge model, every fact with its provenance."),
    ("Tribal knowledge", "What engineers know that isn't written down: conventions and notes, shared or per site."),
    ("Digital twin", "Knowledge graph + live state + views. Later phase."),
])

hero("Exports go in. A knowledge graph comes out.",
     "Four steps turn engineering-tool exports into a complete graph of the building. Data flows one way: "
     "nothing is ever written back to the source tools.")

story([
    Section("Connect", "cable", "Read every tool into one common record.",
            p("Adapters read each tool's export into one record per point: name, folder, device, units.",
              "Adapters stay thin. All the intelligence lives in the mapper and the knowledge model, so the "
              "pipeline doesn't care where the data came from."),
            f'<div class="flow">{sources}{connect}</div>'),
    Section("Understand", "psychology", "Cheapest method first. An LLM only for what's left.",
            p("The mapper groups points onto equipment and gives each one a class, in order: structure, naming "
              "rules, equipment templates, then an LLM with a short list of candidates.",
              "Every result gets a confidence between 0 and 1; the low ones go to review."),
            understand, [Go("Explore the knowledge model", "views/knowledge_model.py")]),
    Section("Build the graph", "hub", "One graph per building, every fact linked.",
            p("Every point and equipment gets the best guess, linked into one graph: points on equipment, parts, "
              "and what feeds what.",
              "Each fact keeps its source, method and confidence."),
            graph, [Go("What a complete graph is", "views/complete_graph.py")]),
    Section("Use", "explore", "The graph powers every view here.",
            p("Tree, 3D graph, equipment, sequences and tables all read the same graph. Next: agents and "
              "plain-language questions."),
            use, [Go("Watch the agent tour", "views/agent_tour.py", "play_circle")]),
    Section("Two layers", "layers", "Some knowledge is true of every building. Some is true of one.",
            p("They live in different places, and feed each other.")
            + features([
                ("public", "Shared.", "The knowledge model, and the conventions of a contractor or a customer."),
                ("apartment", "Per project.", "The building's graph, graphics, tables, site conventions and notes."),
                ("autorenew", "The loop.", "Site habits become conventions, the best become knowledge-model "
                                           "rules. The next building maps better."),
            ]),
            layers, [Go("See the projects", "views/projects.py", "apartment")]),
    Section("Traceable facts", "fingerprint", "Nothing in the graph is a black box.",
            p("Every node and link stores where it came from, how it was decided, how sure the mapper was, and "
              "whether a person confirmed it.",
              "Here is one real point, as stored."),
            trace),
    Section("Words we use", "menu_book", "Six terms, used the same way everywhere.",
            p("The same vocabulary in the code, in the app and in conversation."),
            WORDS),
], key="how_story")
