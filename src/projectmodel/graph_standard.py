"""What a complete, reliable building graph is: the layers, the facts in each layer, where each fact comes from,
and how far a mapped project is today. Read by the Overview page "Complete graph" (graph_standard.html).

The definition is data, so the page and the tests read the same thing. `status()` measures one project against it:
a fact the input cannot carry yet (units, locations...) is "missing", never guessed.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .db.store import Store
from .knowledge_model import KnowledgeModel

APP = Path(__file__).resolve().parent / "app"
PROJECT = "alpha/names_paths"

# Where facts come from. `today`: in this prototype's input now | next: the Niagara / CPO adapters |
# later: documents and live data.
SOURCES = [
    {"id": "names", "name": "BMS point names", "today": "now", "group": "BMS export",
     "gives": "The name the integrator typed, e.g. \"VAV 1-2-81 ZN-T\". Says what a point measures or does, often "
              "which equipment and floor."},
    {"id": "tree", "name": "Station folder tree", "today": "now", "group": "BMS export",
     "gives": "The folders points sit in (Niagara station, BACnet device list). Says which equipment a point belongs "
              "to and which plant or system holds that equipment."},
    {"id": "bacnet", "name": "Object properties", "today": "next", "group": "BMS export",
     "gives": "BACnet object type (AI/AO/BI/BO/AV/MSV), units, writable or not, state texts, COV and trend setup. "
              "Separates sensor, setpoint, command and status without guessing."},
    {"id": "device", "name": "Controllers", "today": "next", "group": "BMS export",
     "gives": "Device instance, controller model and the application it runs (e.g. a VAV reheat program). One "
              "controller is usually one piece of equipment, and its program says which kind."},
    {"id": "program", "name": "Control programs", "today": "next", "group": "BMS export",
     "gives": "The logic that actually runs in each controller (Niagara wire sheets, CPO programs): loops, "
              "interlocks, resets and schedules as built."},
    {"id": "io_list", "name": "Points schedule / I/O list", "today": "later", "group": "Project documents",
     "gives": "The engineer's list of every point per equipment, with type and range. The closest thing to an "
              "answer key on a real project."},
    {"id": "mech", "name": "Mechanical schedule", "today": "later", "group": "Project documents",
     "gives": "Every equipment tag with type, capacity, make and model, and often the area or unit it serves."},
    {"id": "drawings", "name": "Drawings and BIM", "today": "later", "group": "Project documents",
     "gives": "Floor plans, air and water schematics, risers. Where equipment is, which rooms a zone covers, which "
              "AHU supplies which VAVs."},
    {"id": "soo", "name": "Sequence of operations", "today": "now", "group": "Project documents",
     "gives": "How the building is meant to behave (intent): which setpoint drives which output, interlocks, "
              "resets, modes, intended values. Written by the design engineer, refined by the controls "
              "contractor. For Alpha, a demo document written for this prototype (Alpha's own is not public)."},
    {"id": "km", "name": "Knowledge model", "today": "now", "group": "Our IP",
     "gives": "Brick classes, equipment templates and naming rules. Infers what the sources leave implicit (a VAV "
              "has a damper; an AHU feeds VAVs) and says what is missing."},
    {"id": "trends", "name": "Live and trend data", "today": "later", "group": "Operations",
     "gives": "Values over time. Confirms a link (VAV discharge air warms when its AHU supply air warms) and catches "
              "mislabels (a \"temperature\" that reads 0 or 1)."},
    {"id": "people", "name": "Site team and commissioning", "today": "later", "group": "Operations",
     "gives": "Commissioning sheets, site walks and the people who run the building. The final word, and the only "
              "source for history (\"AHU-3 replaced in 2022\")."},
]

# role of a source for a fact: primary = where the fact comes from; support = helps infer it; check = confirms it.
LAYERS = [
    {"id": "spaces", "name": "Spaces", "icon": "domain",
     "what": "Site, building, floors, zones and rooms: where things are and who they serve."},
    {"id": "systems", "name": "Systems", "icon": "water_drop",
     "what": "Plants and loops: chilled water, hot water, condenser water, each air system."},
    {"id": "equipment", "name": "Equipment", "icon": "hvac",
     "what": "Every piece of equipment, its type, its parts and what feeds what."},
    {"id": "points", "name": "Points", "icon": "sensors",
     "what": "Every sensor, setpoint, command, status and alarm, on its equipment, with its meaning."},
    {"id": "behaviour", "name": "Behaviour", "icon": "sync_alt",
     "what": "How the building is meant to run: control loops, interlocks, resets, modes and intended values. "
             "It acts on equipment and points across the graph."},
    {"id": "trust", "name": "Trust", "icon": "verified",
     "what": "What makes every fact above usable: where it came from, how sure we are, and whether it was checked."},
]

FACTS = [
    # spaces
    {"id": "spaces", "layer": "spaces", "name": "Floors, zones and rooms",
     "question": "Which rooms are on level 3?",
     "rule": "Every floor, HVAC zone and room served by the system exists once, under its building.",
     "sources": {"drawings": "primary", "mech": "support", "names": "support", "people": "check"},
     "how": "Floor plans give rooms; zone names in the BMS (\"VAV 1-3-1\" = floor 3) give a first guess."},
    {"id": "serves", "layer": "spaces", "name": "Equipment serves zone",
     "question": "Which VAV serves room 3.12, and which AHU is behind it?",
     "rule": "Every terminal unit (VAV, FCU) serves at least one zone; every zone is served.",
     "sources": {"drawings": "primary", "mech": "primary", "names": "support", "trends": "check"},
     "how": "Air schematics and the mechanical schedule; zone temperature points tie a terminal to its zone."},
    # systems
    {"id": "systems", "layer": "systems", "name": "Plants and loops",
     "question": "What is on the chilled water loop?",
     "rule": "Every plant and loop (chilled, hot and condenser water; each air system) is one node.",
     "sources": {"tree": "primary", "drawings": "primary", "km": "support", "mech": "check"},
     "how": "Plant folders in the station (\"Chilled Water Plant\"); piping schematics confirm."},
    {"id": "membership", "layer": "systems", "name": "Equipment in its system",
     "question": "Which pumps and chillers make up the chilled water plant?",
     "rule": "Every plant equipment belongs to exactly one system; parts belong to their equipment.",
     "sources": {"tree": "primary", "drawings": "primary", "mech": "support", "people": "check"},
     "how": "Folder nesting gives part-of links; schematics confirm which loop a pump sits on."},
    # equipment
    {"id": "equipment", "layer": "equipment", "name": "Every equipment, once",
     "question": "How many VAVs does this building have?",
     "rule": "Each physical unit is one node: none missing, none split or merged.",
     "sources": {"tree": "primary", "device": "primary", "mech": "check", "io_list": "check"},
     "how": "One folder or one controller per unit; the mechanical schedule is the list to reconcile against."},
    {"id": "equip_class", "layer": "equipment", "name": "Equipment type",
     "question": "Is this an AHU, a VAV, a fan coil?",
     "rule": "Every equipment has the most specific class the knowledge model allows.",
     "sources": {"km": "primary", "device": "primary", "names": "support", "mech": "check"},
     "how": "Templates match the group of points (a damper, airflow and zone temperature look like a VAV); the "
            "controller's program and the schedule confirm."},
    {"id": "feeds", "layer": "equipment", "name": "What feeds what",
     "question": "What is affected if AHU-2 stops?",
     "rule": "Every terminal has its air handler; every coil has its water loop; no cycles.",
     "sources": {"drawings": "primary", "mech": "primary", "tree": "support", "km": "support", "soo": "support",
                 "trends": "check"},
     "how": "Schematics and schedules say it; folders and templates infer it; trends prove it."},
    {"id": "nameplate", "layer": "equipment", "name": "Nameplate data",
     "question": "What capacity is chiller CH-1, and who made it?",
     "rule": "Capacity, make, model and serial for every major equipment.",
     "sources": {"mech": "primary", "people": "check"},
     "how": "Mechanical schedule and submittals; checked on site."},
    # points
    {"id": "point", "layer": "points", "name": "Every point, with a stable ID",
     "question": "Is this the same point as in last month's export?",
     "rule": "Each point exists once, keyed on device + object ID, not on its name.",
     "sources": {"bacnet": "primary", "device": "primary", "names": "support"},
     "how": "Device instance + object ID survive renames; names alone do not."},
    {"id": "point_equip", "layer": "points", "name": "Point on its equipment",
     "question": "Which points belong to VAV 1-2-81?",
     "rule": "Every point sits on exactly one equipment (or the site, for weather and utility points).",
     "sources": {"tree": "primary", "device": "primary", "names": "support", "io_list": "check"},
     "how": "Folders and controllers group points; names carry equipment IDs; the I/O list confirms."},
    {"id": "point_class", "layer": "points", "name": "Point type",
     "question": "Is \"ZN-T\" a zone temperature sensor or its setpoint?",
     "rule": "Every point has the most specific Brick class its sources support.",
     "sources": {"names": "primary", "bacnet": "primary", "km": "support", "io_list": "check", "trends": "check"},
     "how": "Naming rules read the name; object type and units decide sensor vs setpoint vs command; templates "
            "fill in what the equipment should have."},
    {"id": "point_props", "layer": "points", "name": "Units, kind and writability",
     "question": "Is this value in °C or °F? Can an agent write to it?",
     "rule": "Every point has its unit, analog/binary/multi-state kind, and whether it is writable.",
     "sources": {"bacnet": "primary", "io_list": "support"},
     "how": "Read straight from the controller's object properties."},
    {"id": "required", "layer": "points", "name": "Expected points present",
     "question": "Does every VAV have its zone temperature and airflow?",
     "rule": "Each equipment has the points its template requires, or the gap is recorded.",
     "sources": {"km": "primary", "io_list": "check", "people": "check"},
     "how": "The template lists what an AHU, VAV or pump must have; missing ones are flagged, not invented."},
    # behaviour
    {"id": "loops", "layer": "behaviour", "name": "Control loops",
     "question": "Which setpoint and sensor drive this valve command?",
     "rule": "Each loop links its setpoint, its measured value and its outputs, and every one of them exists.",
     "sources": {"soo": "primary", "program": "primary", "km": "support", "trends": "check"},
     "how": "Read from the sequence (intent) and the controller program (as built); templates give the usual "
            "pairs; trends show the output moving with the error."},
    {"id": "interlocks", "layer": "behaviour", "name": "Interlocks, resets and requests",
     "question": "What must be proven before the chiller starts? What resets AHU-2's supply air setpoint?",
     "rule": "Every dependency between points and equipment that is not a physical feed is a link.",
     "sources": {"soo": "primary", "program": "primary", "people": "check"},
     "how": "Start-up orders, proofs, trim-and-respond resets and plant requests, from the sequence and the "
            "program. They cross equipment: a VAV resets its AHU, an AHU enables the plant."},
    {"id": "modes", "layer": "behaviour", "name": "Modes and schedules",
     "question": "Should this zone be at 75 °F right now, or set back?",
     "rule": "Every mode (occupied, unoccupied, warm-up, economizer) is known, with what switches it and what "
             "it changes.",
     "sources": {"soo": "primary", "program": "primary", "trends": "check"},
     "how": "Schedules and mode logic from the sequence and the controller; trends show when they switch."},
    {"id": "intent_values", "layer": "behaviour", "name": "Intended values",
     "question": "What should the chilled water leaving temperature be?",
     "rule": "Every setpoint, limit and alarm threshold has its intended value.",
     "sources": {"soo": "primary", "program": "support", "io_list": "support", "trends": "check"},
     "how": "Written in the sequence; the live setpoint in the controller says what it is set to now."},
    # trust
    {"id": "provenance", "layer": "trust", "name": "Provenance on every fact",
     "question": "Where did this come from, and who decided it?",
     "rule": "Every node and link stores source, row or path, method, confidence and revision.",
     "sources": {"km": "primary"},
     "how": "Written by the mapper on every fact, never optional."},
    {"id": "validation", "layer": "trust", "name": "Passes the building rules",
     "question": "Does anything in the graph contradict physics or the model?",
     "rule": "Unit matches class, one air handler per terminal, no feed cycles, required points present.",
     "sources": {"km": "primary", "trends": "check"},
     "how": "Rules from the knowledge model (SHACL), run on every import."},
    {"id": "agreement", "layer": "trust", "name": "Confirmed by a second source",
     "question": "Do two independent sources agree on this?",
     "rule": "Key facts (equipment, feeds, point type) are confirmed by a source other than the one they came from.",
     "sources": {"io_list": "primary", "mech": "primary", "drawings": "primary", "trends": "check", "people": "check"},
     "how": "BMS export vs points schedule vs drawings vs live data: disagreement is shown, not hidden."},
    {"id": "calibration", "layer": "trust", "name": "Confidence means what it says",
     "question": "If the graph says 90% sure, is it right 9 times in 10?",
     "rule": "Each confidence band's accuracy matches the band, measured against ground truth.",
     "sources": {"km": "primary", "people": "check"},
     "how": "Scored against ground truth on every change to rules or templates."},
    {"id": "intent_asbuilt", "layer": "trust", "name": "Intent matches what runs",
     "question": "Does the controller do what the sequence says?",
     "rule": "Each behaviour fact from the sequence (intent) is compared with the control program (as built); "
             "differences are findings, shown not hidden.",
     "sources": {"program": "primary", "soo": "primary", "trends": "check", "people": "check"},
     "how": "The sequence also checks the graph: a point it needs but the graph lacks, or classes differently, "
            "is a finding."},
]

DEFINITIONS = {
    "complete": {
        "title": "Complete",
        "line": "Nothing the building has is missing from the graph.",
        "points": ["Every layer is there: spaces, systems, equipment, points.",
                   "Every point is typed and on its equipment.",
                   "Every equipment is typed and linked to what feeds it and what it serves.",
                   "Its behaviour is there: control loops, interlocks, modes and intended values.",
                   "Every expected point is found, or recorded as missing."],
    },
    "reliable": {
        "title": "Reliable",
        "line": "Every fact can be trusted, and you can see why.",
        "points": ["Every fact says where it came from and how it was decided.",
                   "Confidence is calibrated: 90% sure means right 9 times in 10.",
                   "Key facts are confirmed by a second, independent source.",
                   "The graph passes the building's rules, and stays stable across re-imports."],
    },
}

PLANT = {"Chiller", "Boiler", "Pump", "Chilled_Water_Pump", "Hot_Water_Pump", "Condenser_Water_Pump", "Cooling_Tower",
         "Heat_Exchanger"}
GENERIC = {"Point", "Sensor", "Setpoint", "Command", "Status", "Alarm", "Equipment", "HVAC_Equipment"}
TERMINALS = {"VAV", "FCU", "Terminal_Unit"}


def definition() -> dict:
    return {"sources": SOURCES, "layers": LAYERS, "facts": FACTS, "definitions": DEFINITIONS}


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


STORED = {"loops": ("drives", "feedback"), "interlocks": ("requires", "resets", "requests"), "modes": ("switches",)}


def behaviour_facts(sequences: dict | None, stored: dict | None = None) -> dict[str, dict]:
    """The behaviour layer's facts, from the project's sequences document (sequences.behaviour). `stored`: count of
    the document edges in the graph per relation (scripts/load_sequences.py writes them)."""
    if not sequences or not sequences["sequences"]:
        none = {"pct": 0, "state": "missing", "note": "No sequence of operations for this project yet."}
        return {k: dict(none) for k in ("loops", "interlocks", "modes", "intent_values", "intent_asbuilt")}
    c, f, n = sequences["counts"], sequences["findings"], sequences["sequences"]

    stored = stored or {}

    def from_doc(key, what):
        ok, total = c[key]
        pct = _pct(ok, total)
        note = f"{ok} of {total} {what} found in the graph, from {n} sequences (intent only: no control programs " \
               "read yet)."
        if key in STORED:
            k = sum(stored.get(r, 0) for r in STORED[key])
            note += f" Stored in the graph as {k} edges ({', '.join(STORED[key])}), the document as source." if k \
                else " Not stored in the graph yet: run scripts/load_sequences.py."
        else:
            note += " Kept in the document, not stored as edges."
        # Read from the demo sequences only: intent, never confirmed by a controller program, so at most partial.
        return {"pct": pct, "state": "partial" if pct else "missing", "note": note}
    return {
        "loops": from_doc("loops", "loop ends (setpoint, measured value, outputs)"),
        "interlocks": from_doc("interlocks", "ends of interlocks, resets and requests"),
        "modes": from_doc("modes", "mode switch ends"),
        "intent_values": from_doc("values", "intended values"),
        "intent_asbuilt": {"pct": 0, "state": "missing",
                           "note": f"No control programs to compare with yet. The sequences did check the graph: "
                                   f"{f.get('gap', 0)} points they need are missing and {f.get('conflict', 0)} are "
                                   "classed differently."},
    }


def status(store: Store, km: KnowledgeModel, project: str = PROJECT, score: dict | None = None,
           sequences: dict | None = None) -> dict[str, dict]:
    """Per fact: {pct (0-100, None if not measurable), state (done | partial | missing), note}. Measured on the graph;
    nothing is inferred for facts the input does not carry. `score` (score_project's result, when the project has
    ground truth) measures calibration; `sequences` (sequences.behaviour) the behaviour layer."""
    nodes = {n["id"]: n for n in store.nodes(project) if n["status"] != "rejected"}
    edges = [e for e in store.edges(project) if e["status"] != "rejected"]
    points = [n for n in nodes.values() if n["kind"] == "point"]
    equip = [n for n in nodes.values() if n["kind"] == "equipment"]
    systems = [n for n in equip if n["class"] and km.classes.get(n["class"]) and km.classes[n["class"]].kind == "system"]
    real_equip = [n for n in equip if n not in systems]
    by_rel = defaultdict(list)
    for e in edges:
        by_rel[e["rel"]].append(e)
    on_equip = {e["dst"] for e in by_rel["hasPoint"]}
    # Air feeds only: a VAV with reheat is also fed by the hot water loop, and should be.
    fed = Counter(e["dst"] for e in by_rel["feeds"] if json.loads(e["attrs"] or "{}").get("medium") == "air")
    terminals = [n for n in real_equip if n["class"] in TERMINALS]
    attrs = {n["id"]: json.loads(n["attrs"] or "{}") for n in points}

    # Required template points: a slot counts as found when a point on the equipment has one of its classes
    # (or a subclass of one).
    pts_of = defaultdict(list)
    for e in by_rel["hasPoint"]:
        if e["dst"] in nodes:
            pts_of[e["src"]].append(nodes[e["dst"]]["class"])
    req_total = req_found = 0
    for n in real_equip:
        t = km.templates.get(json.loads(n["attrs"] or "{}").get("template") or "")
        for s in t.slots if t else ():
            if s.required:
                req_total += 1
                req_found += any(c and any(c == sc or km.is_a(c, sc) for sc in s.classes) for c in pts_of[n["id"]])

    def has_cycle() -> bool:
        nxt = defaultdict(list)
        for e in by_rel["feeds"]:
            nxt[e["src"]].append(e["dst"])
        seen, stack = set(), set()

        def visit(v):
            if v in stack:
                return True
            if v in seen:
                return False
            seen.add(v)
            stack.add(v)
            found = any(visit(w) for w in nxt[v])
            stack.discard(v)
            return found
        return any(visit(v) for v in list(nxt))

    one_feeder = sum(1 for n in terminals if fed[n["id"]] == 1)
    parent = {e["dst"]: e["src"] for e in by_rel["hasPart"]}
    system_ids = {n["id"] for n in systems}
    plant = [n for n in real_equip if n["class"] in PLANT]
    in_system = sum(1 for n in plant if parent.get(n["id"]) in system_ids)
    with_unit = sum(1 for n in points if attrs[n["id"]].get("units"))
    with_prov = sum(1 for n in nodes.values() if n["source_file"] and n["source_ref"] and n["method"])
    with_prov += sum(1 for e in edges if e["source_file"] and e["source_ref"] and e["method"])
    # Calibrated: share of labelled points in a confidence band whose accuracy reaches the band's lower edge.
    bands = [b for b in (score or {}).get("calibration", []) if b["n"]]
    calibrated = sum(b["n"] for b in bands if b["exact_pct"] >= 100 * float(b["conf"].split("-")[0]))

    def fact(pct, note, state=None):
        state = state or ("missing" if not pct else "done" if pct >= 100 else "partial")
        return {"pct": pct, "state": state, "note": note}

    specific_pts = sum(1 for n in points if n["class"] and n["class"] not in GENERIC)
    specific_eq = sum(1 for n in real_equip if n["class"] and n["class"] not in GENERIC)
    validation_checks = [len(on_equip & {n["id"] for n in points}) == len(points),
                         one_feeder == len(terminals) and bool(terminals), not has_cycle(),
                         bool(with_unit)]  # unit matches class: cannot run without units
    return {
        "spaces": fact(0, "Not in the input yet: needs drawings, or floors read from zone names."),
        "serves": fact(0, "No zones yet, so nothing to serve."),
        "systems": fact(100.0 if systems else 0, f"{len(systems)} plant and loop nodes, from plant folders. Air "
                                                 "systems are not separate nodes yet.", "partial" if systems else None),
        "membership": fact(_pct(in_system, len(plant)),
                           f"{in_system} of {len(plant)} plant equipment sit in a plant or loop. Not yet checked "
                           "against schematics."),
        "equipment": fact(100.0 if real_equip else 0,
                          f"{len(real_equip)} equipment found. Not reconciled with a mechanical schedule (none yet)."),
        "equip_class": fact(_pct(specific_eq, len(real_equip)),
                            f"{specific_eq} of {len(real_equip)} have a specific type."),
        "feeds": fact(_pct(one_feeder, len(terminals)),
                      f"{len(by_rel['feeds'])} feeds links; {one_feeder} of {len(terminals)} terminals have exactly "
                      "one air handler. Inferred from folders and templates, not confirmed by drawings."),
        "nameplate": fact(0, "Needs the mechanical schedule."),
        "point": fact(None, f"{len(points):,} points, each once, but keyed on the export row: a rename would break "
                            "the link. Needs device + object ID.", "partial" if points else "missing"),
        "point_equip": fact(_pct(len(on_equip & {n['id'] for n in points}), len(points)),
                            f"{len(on_equip & {n['id'] for n in points}):,} of {len(points):,} points on equipment."),
        "point_class": fact(_pct(specific_pts, len(points)),
                            f"{specific_pts:,} of {len(points):,} points have a specific class; the rest are "
                            "generic (Sensor, Status...)."),
        "point_props": fact(_pct(with_unit, len(points)), "Not in the input: names and folders only."),
        "required": fact(_pct(req_found, req_total),
                         f"{req_found} of {req_total} required template points found."),
        **behaviour_facts(sequences, Counter(e["rel"] for e in store.edges(project) if e["method"] == "document")),
        "provenance": fact(_pct(with_prov, len(nodes) + len(edges)),
                           "Source, method, confidence and revision on every node and link."),
        "validation": fact(_pct(sum(validation_checks), len(validation_checks)),
                           f"{sum(validation_checks)} of {len(validation_checks)} checks pass: every point placed, one "
                           "air handler per terminal, no feed cycles. Unit vs class cannot run without units."),
        "agreement": fact(0, "One source today (the BMS export), so nothing is confirmed by a second one."),
        "calibration": fact(_pct(calibrated, sum(b["n"] for b in bands)),
                            "Share of points in a confidence band that is as accurate as it claims. "
                            + next((f"The {b['conf']} band is right {b['exact_pct']:.0f}% of the time."
                                    for b in bands if b["conf"].startswith("0.9")), "")
                            if bands else "Needs ground truth to measure."),
    }


def render_html(payload: dict, theme: str | None = None) -> str:
    html = (APP / "graph_standard.html").read_text()
    html = html.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")).replace("</", "<\\/"))
    if theme in ("light", "dark"):
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return html
