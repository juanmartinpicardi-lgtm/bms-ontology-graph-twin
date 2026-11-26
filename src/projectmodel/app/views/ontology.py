"""Ontology: what the graph borrows from Brick, what our extension adds, what our own layer adds on top, and where
each input of the app (floor plans, equipment schedules, sequences, controls submittal and riser, BMS points, tribal
knowledge) lands in that framework. Ends with what a complete graph still needs.

A scroll-synced story (app/story.py), like How it works. Counts are read from the knowledge model, the tag rules
and the code's own relation lists, so the page follows the model when it changes.
"""

import sys
from html import escape
from pathlib import Path

import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.app.shell import knowledge_model  # noqa: E402
from projectmodel.app.story import Go, Section, features, hero, icon, p, story  # noqa: E402
from projectmodel.sequences import CONTROL  # noqa: E402

km = knowledge_model()
KNOWN = set(km.relations) | set(km.ba_relations)
OFF_RELS = [r for r in (*CONTROL, "serves") if r not in KNOWN]  # written by the sequences and the guided setup
TAGS = yaml.safe_load((ROOT / "knowledge_model/name_rules/equipment_tags.yaml").read_text())["prefixes"]
TAG_UNCHECKED = sorted({t["class"] for t in TAGS.values() if t.get("class")} - set(km.classes))
UNCHECKED = sorted(({"Floor", "Room"} - set(km.classes)) | set(TAG_UNCHECKED))  # classes the readers use, unchecked
OFF = bool(OFF_RELS or UNCHECKED)  # the loader now refuses a model that leaves these undeclared, so normally False
brick = [c for c, i in km.classes.items() if i.source == "brick"]
ba = [c for c, i in km.classes.items() if i.source == "ba"]
count = {k: sum(1 for c in brick if km.classes[c].kind == k) for k in ("equipment", "point", "system", "location")}
LOCATIONS = sorted(c for c, i in km.classes.items() if i.kind == "location")


def home(term: str) -> str:
    """Which layer a term lives in, read from the model: brick, ba, or off (written by the app, declared nowhere)."""
    if term in km.classes:
        return km.classes[term].source
    if term in km.relations:
        return "brick"
    return "ba" if term in km.ba_relations else "off"

# Colours for the five places a fact can land. Mid-tone hues, mixed with the page colours so they read in both themes.
STYLE = """<style>
.story { --c-brick: #1D9E75; --c-ba: #6E64D8; --c-off: #C98316; --c-gap: #D85A30; --c-own: var(--muted); }
.on-brick { --c: var(--c-brick); } .on-ba { --c: var(--c-ba); } .on-off { --c: var(--c-off); }
.on-gap { --c: var(--c-gap); } .on-own { --c: var(--c-own); }
.on-t { display: inline-flex; align-items: center; font-family: var(--st-code-font, ui-monospace, monospace);
  font-size: .72rem; line-height: 1.2; padding: 3px 8px; border-radius: 4px; border: 1px solid; white-space: nowrap;
  background: color-mix(in srgb, var(--c) 13%, var(--bg)); border-color: color-mix(in srgb, var(--c) 50%, transparent);
  color: color-mix(in srgb, var(--c) 72%, var(--fg)); }
.on-t.on-gap { background: transparent; border-style: dashed; }
.on-ch { display: flex; flex-wrap: wrap; gap: 5px; justify-content: flex-end; }
.on-dot { display: inline-block; width: 10px; height: 10px; border-radius: 3px; flex: none; margin-top: 4px;
  background: color-mix(in srgb, var(--c) 30%, var(--bg)); border: 1.5px solid var(--c); }
.on-dot.on-gap { background: transparent; border-style: dashed; }
.on-key { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 9px; }
.on-key li { display: flex; gap: 10px; align-items: flex-start; font-size: .88rem; line-height: 1.45; color: var(--muted);
  margin: 0; }
.on-key b { color: var(--fg); font-weight: 600; }

.on-map { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
  box-shadow: 0 10px 28px -18px rgba(0, 0, 0, .3); max-width: 460px !important; }
.on-map header { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--line);
  font-size: .9rem; }
.on-map header .ms { color: var(--acc); }
.on-map header small { margin-left: auto; font-size: .7rem; padding: 2px 8px; border-radius: 4px; background: var(--tint);
  color: var(--acc); font-weight: 600; white-space: nowrap; }
.on-map ul { list-style: none; margin: 0; padding: 4px 0; }
.on-map li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; margin: 0;
  padding: 8px 14px; border-bottom: 1px solid color-mix(in srgb, var(--fg) 6%, transparent); }
.on-map li:last-child { border-bottom: 0; }
.on-map li > span:first-child { font-size: .79rem; line-height: 1.35; color: var(--muted); }
.on-map footer { padding: 10px 14px 12px; border-top: 1px solid var(--line); display: grid; gap: 7px;
  background: color-mix(in srgb, var(--c-gap) 4%, var(--bg)); }
.on-map footer .on-ch { justify-content: flex-start; }
.on-cap { font-size: .7rem; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }

.on-lays { display: grid; gap: 8px; max-width: 460px !important; }
.on-lay { padding: 12px 14px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--c) 45%, transparent);
  background: color-mix(in srgb, var(--c) 8%, var(--bg)); display: grid; gap: 8px; }
.on-lay.on-off { border-style: dashed; }
.on-lay h4 { margin: 0; padding: 0; font-size: .86rem; font-weight: 600; display: flex; align-items: baseline;
  gap: 8px; flex-wrap: wrap; }
.on-lay h4 span { font-weight: 400; font-size: .76rem; color: var(--muted); }
.on-lay .on-ch { justify-content: flex-start; }

.on-vav text.vt { font-size: 13px; font-weight: 600; }
.on-vav text.vs { fill: var(--muted); font-size: 11px; }
.on-vav text.ve { fill: var(--muted); font-size: 11px; }
.on-vav rect.vn { fill: color-mix(in srgb, var(--c) 12%, var(--bg)); stroke: var(--c); stroke-width: 1; }
.on-vav rect.vn.dash { stroke-dasharray: 4 3; }
.on-vav .vl { stroke: var(--c); stroke-width: 1.5; fill: none; }
.on-vav .vl.dash { stroke-dasharray: 4 3; }
.on-vav marker path { fill: none; stroke: context-stroke; stroke-width: 1.5; }

.on-miss { display: grid; gap: 10px; max-width: 460px !important; }
.on-grp { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: 11px 14px; }
.on-grp h5 { margin: 0 0 6px; padding: 0; font-size: .84rem; font-weight: 600; display: flex; gap: 8px;
  align-items: center; }
.on-grp h5 .ms { font-size: 18px; color: var(--c-gap); }
.on-grp ul { margin: 0; padding-left: 18px; display: grid; gap: 3px; }
.on-grp li { font-size: .77rem; line-height: 1.4; color: var(--muted); margin: 0; }
.on-grp li code { color: var(--fg); }
</style>"""

KINDS = [
    ("brick", "Brick 1.4.", "Standard classes and relations, checked against Brick every time the model loads."),
    ("ba", "Our BA extension.", "Building-automation things Brick lacks, under our own ba: namespace, hung under "
                                "Brick parents."),
    ("own", "Our own layer.", "Not ontology: provenance, templates, naming rules, attributes, notes. Brick has no "
                              "place for these."),
    ("off", "In use, off-standard.", "Works in the app today, but isn't valid Brick and isn't declared in our "
                                     "extension yet."),
    ("gap", "Missing.", "A source could give it, or Brick has a term for it, but the graph doesn't hold it yet."),
]


def t(term: str, kind: str) -> str:
    return f'<span class="on-t on-{kind}">{escape(term)}</span>'


def key() -> str:
    return '<ul class="on-key">' + "".join(
        f'<li><span class="on-dot on-{k}"></span><span><b>{escape(h)}</b> {escape(d)}</span></li>'
        for k, h, d in KINDS if OFF or k != "off") + "</ul>"


def mapping(ic: str, name: str, when: str, rows: list[tuple[str, list[tuple[str, str]]]],
            missing: list[str]) -> str:
    """One source as a card: what is read from it, the terms it becomes, and what is still missing."""
    body = "".join(f'<li><span>{escape(read)}</span><span class="on-ch">'
                   f'{"".join(t(x, home(x) if k == "off" else k) for x, k in terms)}</span></li>'
                   for read, terms in rows)
    foot = (f'<footer><span class="on-cap">Still missing</span><div class="on-ch">'
            f'{"".join(t(m, "gap") for m in missing)}</div></footer>') if missing else ""
    return (f'<div class="on-map"><header>{icon(ic)}<b>{escape(name)}</b>'
            f'<small>{escape(when)}</small></header><ul>{body}</ul>{foot}</div>')


# 1 · The framework: three layers, plus what is in use but not standard yet.
def layer(kind: str, title: str, sub: str, items: list[str], mono: bool = True) -> str:
    chips = "".join(t(i, kind) for i in items) if mono else "".join(
        f'<span class="on-t on-{kind}" style="font-family:inherit">{escape(i)}</span>' for i in items)
    return f'<div class="on-lay on-{kind}"><h4>{escape(title)}<span>{escape(sub)}</span></h4>' \
           f'<div class="on-ch">{chips}</div></div>'


framework = STYLE + '<div class="on-lays">' + "".join([
    layer("own", "Our own layer", "not ontology",
          ["Provenance on every fact", f"{len(km.templates)} equipment templates",
           f"{len(km.name_rules.abbreviations)} abbreviations", "Conventions", "Notes"], mono=False),
    *([layer("off", "In use, off-standard", f"{len(OFF_RELS)} relations, {len(UNCHECKED)} unchecked classes",
             OFF_RELS + UNCHECKED)] if OFF else []),
    layer("ba", "BA extension · ba:", f"{len(ba)} classes, {len(km.ba_relations)} relations",
          ["Field_Controller", "Field_Network", "Software_Point", "Schedule", "Trend_Log"] + km.ba_relations),
    layer("brick", "Brick 1.4.4", f"{len(brick)} classes, {len(km.relations)} relations",
          [f"{count['equipment']} equipment", f"{count['point']} points", f"{count['system']} systems",
           f"{count['location']} locations (deprecated, rec: replaces)",
           "hasPoint", "hasPart", "feeds", "hasLocation"], mono=False),
]) + "</div>"

# 2 · One VAV: every piece coloured by where it comes from.
VAV = """<svg class="on-vav" viewBox="0 0 460 280" role="img" aria-label="One VAV in the graph: an AHU feeds it, a
field controller controls it, it has a zone setpoint and a damper command, it serves a room, and a sequence edge says
the setpoint drives the damper. Each piece is coloured by where it comes from.">
<defs><marker id="on-ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6"
orient="auto-start-reverse"><path d="M2 1L8 5L2 9"/></marker></defs>
<g class="on-brick"><rect class="vn" x="1" y="10" width="128" height="50" rx="8"/>
<text class="vt" x="65" y="32" text-anchor="middle">AHU-1</text><text class="vs" x="65" y="49" text-anchor="middle">brick:AHU</text></g>
<g class="on-brick"><rect class="vn" x="166" y="10" width="128" height="50" rx="8"/>
<text class="vt" x="230" y="32" text-anchor="middle">VAV-2</text><text class="vs" x="230" y="49" text-anchor="middle">brick:VAV</text></g>
<g class="on-ba"><rect class="vn dash" x="331" y="10" width="128" height="50" rx="8"/>
<text class="vt" x="395" y="32" text-anchor="middle">FC-3</text><text class="vs" x="395" y="49" text-anchor="middle">ba:Field_Controller</text></g>
<g class="on-brick"><line class="vl" x1="131" y1="35" x2="163" y2="35" marker-end="url(#on-ar)"/></g>
<text class="ve" x="147" y="27" text-anchor="middle">feeds</text>
<g class="on-ba"><line class="vl dash" x1="329" y1="35" x2="297" y2="35" marker-end="url(#on-ar)"/></g>
<text class="ve" x="313" y="76" text-anchor="middle">controls</text>
<g class="on-brick"><path class="vl" d="M210 60 L210 104 L65 104 L65 146" marker-end="url(#on-ar)"/>
<line class="vl" x1="210" y1="104" x2="210" y2="146" marker-end="url(#on-ar)"/></g>
<text class="ve" x="137" y="97" text-anchor="middle">hasPoint</text>
<g class="on-__SERVES__"><path class="vl" d="M260 60 L260 120 L395 120 L395 146" marker-end="url(#on-ar)"/></g>
<text class="ve" x="330" y="113" text-anchor="middle">serves</text>
<g class="on-brick"><rect class="vn" x="1" y="150" width="128" height="50" rx="8"/>
<text class="vt" x="65" y="172" text-anchor="middle">Zone setpoint</text><text class="vs" x="65" y="189" text-anchor="middle">brick point class</text></g>
<g class="on-brick"><rect class="vn" x="166" y="150" width="128" height="50" rx="8"/>
<text class="vt" x="230" y="172" text-anchor="middle">Damper cmd</text><text class="vs" x="230" y="189" text-anchor="middle">brick point class</text></g>
<g class="on-__ROOM__"><rect class="vn" x="331" y="150" width="128" height="50" rx="8"/>
<text class="vt" x="395" y="172" text-anchor="middle">Room 204</text><text class="vs" x="395" y="189" text-anchor="middle">brick:Room → rec:Room</text></g>
<g class="on-__DRIVES__"><line class="vl dash" x1="131" y1="175" x2="163" y2="175" marker-end="url(#on-ar)"/></g>
<text class="ve" x="147" y="216" text-anchor="middle">drives</text>
<g class="on-own"><rect class="vn" x="1" y="232" width="458" height="38" rx="8"/></g>
<text class="vs" x="230" y="255" text-anchor="middle">Every node and edge: source · method · confidence · status · revision</text>
</svg>""".replace("__SERVES__", home("serves")).replace("__ROOM__", home("Room")).replace("__DRIVES__", home("drives"))

# 3-8 · The sources, in the order a building is set up, then the BMS points and the people.
plans = mapping("map", "Floor plans", "PDF · guided setup", [
    ("Sheet title (“MECHANICAL PLAN – LEVEL 1”)", [("Floor", "off")]),
    ("Room label (CONFERENCE / 109)", [("Room", "off")]),
    ("Floor holds its rooms", [("hasPart", "brick")]),
    ("Equipment tag on the plan (VAV-07, AHU-1)", [("Brick class from tag", "brick")]),
    ("Terminal's thermostat is in a room", [("serves", "off")]),
    ("Other unit drawn in a room", [("hasLocation", "brick")]),
    ("Plan line work, room positions", [("attributes", "own")]),
], ["HVAC_Zone", "room → zone"])

schedules = mapping("table_rows", "Equipment schedules", "PDF · guided setup", [
    ("Row that starts with a tag", [("equipment node", "brick")]),
    ("Columns refine the class (heater kW → reheat)", [("RVAV", "off"), ("VAV", "brick")]),
    ("Capacity, make, model, kW", [("attributes", "own")]),
    ("One AHU → every terminal unit", [("feeds", "brick")]),
    ("Chiller → AHU coil, pump → chiller", [("feeds", "brick")]),
], ["nameplate as Brick properties", "units on nameplate values"])

sequences = mapping("sync_alt", "Sequences of operation", "PDF or YAML · now", [
    ("Setpoint drives an output (control loop)", [("drives", "off")]),
    ("Measured value closes the loop", [("feedback", "off")]),
    ("Proofs and start-up order", [("requires", "off")]),
    ("Trim-and-respond, plant requests", [("resets", "off"), ("requests", "off")]),
    ("Occupied, unoccupied, economizer", [("switches", "off")]),
    ("Intended values (55 °F adj.)", [("kept in the document", "own")]),
    ("Each phrase checked: ok, conflict, gap", [("findings", "own")]),
], ["as-built programs", "ba:Schedule"])

submittal = mapping("lan", "Controls submittal and riser", "PDF · guided setup", [
    ("Point row with its Metasys reference", [("point node", "brick"), ("Brick point class", "brick")]),
    ("Point on its device", [("hasPoint", "brick")]),
    ("Riser: one controller per device instance", [("Field_Controller", "off"), ("controls", "off")]),
    ("Riser: MS/TP trunk (FC-1, FC-2…)", [("Field_Network", "off"), ("isOnNetwork", "off")]),
    ("Point on its controller", [("isHostedBy", "off")]),
    ("Room schedule vs the floor plans", [("second source", "own")]),
    ("Contractor's RFIs", [("questions", "own")]),
], ["BACnet object references"])

bms = mapping("sensors", "BMS points from the tools", "Haystack now · Niagara, CPO next", [
    ("Point names (Haystack, BMS CSV)", [("Brick point class", "brick")]),
    ("Folder or device groups points", [("hasPoint", "brick")]),
    ("Plant folders hold their equipment", [("hasPart", "brick"), ("Water_System", "brick")]),
    ("Group of points looks like a VAV", [("template", "own"), ("feeds", "brick")]),
    ("Device named after a tag (VAVE07)", [("same as equipment", "own")]),
    ("Units, object type, instance", [("attributes", "own")]),
], ["hasUnit", "BACnet references", "time-series references", "stable ID: device + object"])

tribal = mapping("groups", "Tribal knowledge", "people · now", [
    ("New tag prefix taught in the setup", [("tag rule", "own")]),
    ("Phrase that settles a point's class", [("class rule", "own")]),
    ("Contractor, customer, site habits", [("conventions", "own")]),
    ("Note on a unit, room or link", [("note", "own")]),
    ("How the team works, for the agent", [("memory and skills", "own")]),
    ("Rules still pick standard classes", [("Brick class", "brick")]),
], ["notes in the export", "promote to the shared model"])


def group(ic: str, title: str, items: list[str]) -> str:
    return f'<div class="on-grp"><h5>{icon(ic)}{escape(title)}</h5><ul>' + "".join(
        f"<li>{i}</li>" for i in items) + "</ul></div>"


def codes(names: list[str]) -> str:
    return ", ".join(f"<code>{escape(n)}</code>" for n in names)


missing = '<div class="on-miss">' + "".join([
    *([group("rule", "Fix the ontology", [
        f"Declare {codes(OFF_RELS)} in the extension, or map them to standard terms",
        f"Add {codes(UNCHECKED)} to the Brick subset"])] if OFF else []),
    group("verified", "Prove it on every import", [
        "Each project already exports as Brick Turtle with " + codes(LOCATIONS) + " as their rec: classes, checked "
        "by SHACL with one command",
        "Next: run that check on every import, not only on demand"]),
    group("inventory_2", "Keep what the sources already give", [
        "BACnet and time-series references on points",
        "Nameplate data as Brick properties",
        "Zones, where a source states them"]),
    group("cable", "Connect the sources still to come", [
        "Niagara and CPO Studio adapters",
        "Control programs, to compare intent with what runs",
        "Trends and occupancy schedules"]),
]) + "</div>"

hero("Brick at the core. Our extension where Brick stops.",
     "Every input the app reads, what it adds to the graph, and where that lands: standard Brick, our "
     "building-automation extension, our own layer on top" + (", or somewhere that isn't standard yet." if OFF else "."))

story([
    Section("Framework", "layers", "Three layers, plus a few things still waiting for a home." if OFF
            else "Three layers. Every term the app writes has a home in one of them.",
            p(f"The ontology is Brick {escape(km.brick_version)} plus a small extension of our own. Around it sits a "
              "layer Brick has no place for: where each fact came from, the rules that recognise things, and what "
              "people know.",
              "Every term on this page is coloured by which of these it belongs to.") + key(),
            framework, [Go("Explore the knowledge model", "views/knowledge_model.py")]),
    Section("One VAV", "hvac", "One VAV, coloured by where each piece comes from.",
            p("Equipment, points and the physical links are Brick. The controller is our extension. The room and "
              "the sequence edge are declared too" + (", but not standard yet." if OFF else
                                                    ": the room as a Brick location, the edge in our extension."),
              "Under all of it, every node and edge carries its provenance: our own layer."),
            VAV, [Go("Open the graph in 3D", "views/graph_3d.py", "bubble_chart")]),
    Section("Floor plans", "map", "Floor plans give the building its spaces.",
            p("The reader finds the floor from the sheet title, rooms from their labels, and every equipment tag "
              "on the page. A terminal unit serves the room its thermostat is in; other units sit in the room "
              "they're drawn in.",
              "Floors and rooms are in our subset and checked at load. Brick 1.4 deprecated them for RealEstateCore "
              "(<code>rec:Level</code>, <code>rec:Room</code>), which is what export will write. Brick links "
              "equipment to zones, not rooms, and has no <code>serves</code>: ours is a sub-property of "
              "<code>feeds</code>.")
            + features([("check_circle", "Brick.", "Tags become Brick equipment classes; hasPart, hasLocation."),
                        ("help", "Asked.", "When two room labels are about as near, the reader asks you.")]),
            plans, [Go("Add a building", "views/add_building.py", "add_business"),
                    Go("Digital twin", "views/digital_twin.py", "domain")]),
    Section("Schedules", "table_rows", "Equipment schedules give each unit its type and nameplate.",
            p("Each schedule row becomes one piece of equipment. Its class starts from the tag and is refined by "
              "the row: a VAVE with heater kW is a reheat VAV.",
              "Capacity, make and model are kept as attributes, not Brick properties. The first feeds links come "
              "from rules: with one AHU, it feeds every terminal unit.")
            + features([("warning", "Unchecked.", f"Tags can propose {', '.join(TAG_UNCHECKED)}: Brick classes "
                                                   "outside our subset.")] if TAG_UNCHECKED else []),
            schedules, [Go("Data tables", "views/data_tables.py", "table")]),
    Section("Sequences", "sync_alt", "Sequences of operation add behaviour. Brick has no words for it.",
            p("The sequence says how the building is meant to run: which setpoint drives which output, what must be "
              "proven before a start, what resets what. These become edges between existing points and "
              "equipment, with the document as their source.",
              f"Brick has no control-logic relations, so {', '.join(CONTROL)} are declared in our extension "
              "(checked at load). Intended values stay in the document. Every phrase the sequence names is checked against the "
              "graph: ok, conflict, or gap.")
            + features([("fact_check", "Intent, not as-built.", "No control program has been read to confirm "
                                                                "what actually runs.")]),
            sequences, [Go("Sequences", "views/sequences.py", "sync_alt")]),
    Section("Submittal and riser", "lan", "The controls submittal gives points and the controller network.",
            p("Point rows carry the contractor's reference, and their description gives each point a Brick class "
              "through the same naming rules the BMS mapper uses. The riser diagram lists every controller: "
              "address, device instance, location and the MS/TP trunk it sits on.",
              "Each controller becomes a node of our extension's field controller class, on its trunk "
              "(<code>isOnNetwork</code>); it <code>controls</code> its unit and hosts its points "
              "(<code>isHostedBy</code>).")
            + features([("compare_arrows", "Second source.", "The contractor's room schedule is checked against "
                                                             "where the floor plans put each box.")]),
            submittal, [Go("Add a building", "views/add_building.py", "add_business")]),
    Section("BMS points", "sensors", "BMS points from the tools fill the points layer.",
            p("Haystack exports (names and folders) go through the mapper: structure, naming rules, equipment "
              "templates, then an LLM for what's left. A BMS CSV in the guided setup matches devices to "
              "equipment by tag and objects to submittal points.",
              "Units, object type and device instance are read but kept as attributes. Brick has terms for units "
              "and for BACnet and time-series references; we don't use them yet.")
            + features([("schedule", "Next.", "Niagara and CPO Studio adapters, into the same raw record.")]),
            bms, [Go("Tree", "tree_app.py", "account_tree"), Go("How it works", "views/how.py", "schema")]),
    Section("Tribal knowledge", "groups", "Tribal knowledge shapes how the graph is read, not what it says.",
            p("What people teach during setup becomes rules for that building: a tag prefix the model didn't "
              "know, a phrase that settles a point's class. Contractor, customer and site habits are layered on "
              "top of the knowledge model as conventions.",
              "Notes travel with the graph, attached to a unit, room or link, but never change a class or a score. "
              "None of it is ontology: the rules still point at standard classes.")
            + features([("autorenew", "The loop.", "Site habits become conventions; the best become shared "
                                                   "knowledge-model rules.")]),
            tribal, [Go("Shared tribal knowledge", "views/tribal.py", "groups")]),
    Section("Still missing", "flag", "What a complete graph still needs.",
            p(("First the plumbing: give every term in use a home in the ontology, then export" if OFF else
               "First the plumbing: every term in use now has a home in the ontology, so export") +
              " each project graph as Brick and validate it (both done; next on every import). Then keep what the "
              "sources already hand us instead of storing it as attributes.",
              "Last, the sources that haven't arrived yet: Niagara, CPO Studio, control programs and live data.")
            + features([("task_alt", "Measured.", "The Complete graph page scores each of these facts on a "
                                                  "real project.")]),
            missing, [Go("What a complete graph is", "views/complete_graph.py", "task_alt")]),
], key="ontology_story")
