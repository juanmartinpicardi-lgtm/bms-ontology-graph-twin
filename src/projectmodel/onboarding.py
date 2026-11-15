"""Onboarding a new building, step by step (docs/spec-submittals-workflow.md §2), told on a project that is already
built. For each of the nine steps: what is submitted, what is created, which of the four layers it fills, and
whether it works today.

Nothing here is invented about the graph: every item marked real is counted on the project's knowledge graph at
call time. An item marked simulated shows what the step will take or produce once it is built; it is worded as an
expectation and carries no measured number of its own. `status` per step: real | partly | simulated.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .agent_tools import GraphTools, trust
from .conventions import scopes_for
from .db.store import Store
from .knowledge_model import KnowledgeModel
from .locate import get_location
from .projects import site_of
from .sequences import behaviour, document_path, load_document, sequences_payload
from .tree import provenance
from .twin_view import twin_payload

ROOT = Path(__file__).resolve().parents[2]
LAYERS = {"graph": "Graph", "kg": "Knowledge graph", "km": "Knowledge model", "tribal": "Tribal knowledge"}
FLOOR_NAMES = {"B1": "Basement plant", "L1": "Level 1", "L2": "Level 2", "L3": "Level 3", "L4": "Level 4", "RF": "Roof"}


def _item(name: str, detail: str = "", real: bool = True) -> dict:
    return {"name": name, "detail": detail, "real": real}


def _rel(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return Path(path).name


def steps(store: Store, km: KnowledgeModel, project: str) -> list[dict]:
    site_id, site = project.split("/")[0], site_of(project)
    nodes = [n for n in store.nodes(project) if n["status"] != "rejected"]
    edges = [e for e in store.edges(project) if e["status"] != "rejected"]
    points = [n for n in nodes if n["kind"] == "point"]
    equip = [n for n in nodes if n["kind"] == "equipment"]
    rel = Counter(e["rel"] for e in edges)
    source = _rel(points[0]["source_file"]) if points else ""
    loc = get_location(store, site_id)

    eq_classes = Counter(n["class"] or "Unclassified" for n in equip)
    generic = {"Point", "Sensor", "Setpoint", "Command", "Status", "Alarm", "Equipment"}
    specific = sum(1 for n in points if n["class"] and n["class"] not in generic)
    with_template = sum(1 for n in equip if json.loads(n["attrs"]).get("template"))
    used_convention = sum(1 for n in nodes if json.loads(n["attrs"]).get("convention"))
    medium = Counter(json.loads(e["attrs"]).get("medium") or "other" for e in edges if e["rel"] == "feeds")

    twin = twin_payload(store, project, site.name)
    floors = Counter(e.get("floor", "") for e in twin["equip"])

    doc = load_document(site_id)
    seq_payload = sequences_payload(store, km, project) if doc else None
    beh = behaviour(seq_payload)
    doc_edges = [e for e in edges if e["method"] == "document"]
    doc_rel = Counter(e["rel"] for e in doc_edges)
    eq_of = {e["dst"]: e["src"] for e in edges if e["rel"] == "hasPoint"}
    covered = {eq_of.get(x, x) for e in doc_edges for x in (e["src"], e["dst"])}

    trusts = Counter(trust(provenance(r)) for r in nodes + edges)
    notes = store.conn.execute("SELECT COUNT(*) FROM notes WHERE project = ?", (project,)).fetchone()[0]

    vav = next((n for n in equip if json.loads(n["attrs"]).get("template") == "vav"), None)
    example = GraphTools(store, km, project).describe(vav["id"]) if vav else None

    out = [
        {"id": "locate", "title": "Locate the building", "status": "real" if loc else "partly",
         "layers": ["graph"], "page": "location", "page_label": "Location",
         "what": "A person types the address and confirms the pin. The site is the root everything else hangs from.",
         "submitted": [_item("An address", loc["query"] if loc else site.location)],
         "created": ([_item("The site", loc["address"]),
                      _item("Coordinates", f"{loc['lat']:.5f}, {loc['lng']:.5f}"),
                      _item("Confirmed by", f"{loc['confirmed_by']}, from {loc['provider']}")] if loc else
                     [_item("Nothing yet", "Search for the building on the Location page.")]),
         "table": None},

        {"id": "drop", "title": "Drop the documents", "status": "partly", "layers": ["graph"], "page": None,
         "what": "Everything the project has is handed over as files. They are stored untouched and never written to.",
         "submitted": [
             _item("BMS export", f"{source}: {len(points):,} point rows with their folders"),
             _item("Sequences of operation", f"{_rel(str(document_path(site_id)))}: {beh['sequences']} sequences "
                   "(a demo document written for this prototype)") if doc else
             _item("Sequences of operation", "None for this project.", False),
             _item("Mechanical schedules", "Every equipment tag with type, capacity, make and model.", False),
             _item("Points list", "The engineer's list of every point per equipment.", False),
             _item("Floor plans", "One per level, with rooms and equipment tags.", False),
             _item("Air and water schematics", "What supplies what.", False)],
         "created": [_item("Sources on file", f"{1 + bool(doc)} read for real today; the other document types "
                                               "are not accepted yet")],
         "table": None},

        {"id": "read", "title": "Read and sort the pages", "status": "partly", "layers": ["graph"], "page": "data",
         "page_label": "Data tables",
         "what": "Each file is read into one common shape, and each page gets a type, so the right reader handles it.",
         "submitted": [_item("The files from step 1")],
         "created": [
             _item("Raw records", f"{len(points):,}, one per row of the BMS export: a name and a folder, "
                                  "nothing interpreted"),
             _item("Page types", "Each PDF page marked as schedule, points list, sequence, floor plan, schematic or "
                                 "cut sheet.", False),
             _item("Tables and text per page", "With the page number kept, so every later fact can cite it.", False)],
         "table": None},

        {"id": "assets", "title": "Build the assets", "status": "partly", "layers": ["kg", "km", "tribal"],
         "page": "tree", "page_label": "Tree",
         "what": "Records become equipment and points, each with a type. The knowledge model says what the types are; "
                 "tribal knowledge says how this site writes its names.",
         "submitted": [
             _item("Raw records", f"{len(points):,} from the BMS export"),
             _item("Knowledge model", f"{len(km.templates)} equipment templates, "
                                      f"{len(km.by_kind('point'))} point classes, "
                                      f"{len(km.by_kind('equipment'))} equipment classes"),
             _item("Tribal knowledge", f"naming conventions {', '.join(scopes_for(project)) or 'none'}: they decided "
                                       f"or helped on {used_convention} items"),
             _item("Mechanical schedules and points list", "Would add nameplate data and confirm the BMS reading.",
                   False)],
         "created": [
             _item("Equipment", f"{len(equip)}, of {len(eq_classes)} types; {with_template} match a template"),
             _item("Points", f"{len(points):,}; {specific:,} with a specific class, {len(points) - specific} generic"),
             _item("Point on its equipment", f"{rel['hasPoint']:,} links"),
             _item("Nameplate data", "Capacity, make and model per equipment.", False)],
         "table": {"title": "Equipment created, by type",
                   "rows": [{"Type": c.replace("_", " "), "Count": n} for c, n in eq_classes.most_common()]}},

        {"id": "spaces", "title": "Place them in the building", "status": "simulated", "layers": ["kg"],
         "page": "digital-twin", "page_label": "Digital twin",
         "what": "Floors, rooms and zones, and which equipment serves which. Today floors are a guess and rooms are "
                 "drawn, not read.",
         "submitted": [_item("Floor plans", "Rooms per level and where each tag sits.", False),
                       _item("The \"serves\" column of the schedules", "Which rooms each terminal unit serves.", False)],
         "created": [
             _item("Floors", f"{len([f for f in floors if f])} levels, inferred from the air handlers: each one's "
                             "zones are put on one level. A stand-in, not a fact from a document.", False),
             _item("Rooms and zones", "One node per room, linked to the unit that serves it.", False)],
         "table": {"title": "Equipment per level (inferred stand-in)",
                   "rows": [{"Level": FLOOR_NAMES.get(f, f), "Equipment": floors[f]} for f in FLOOR_NAMES if floors[f]]}},

        {"id": "connect", "title": "Connect", "status": "partly", "layers": ["kg", "km"], "page": "Graph_3D",
         "page_label": "Graph 3D",
         "what": "What is part of what, and what feeds what. When two sources name the same thing, they become one "
                 "node.",
         "submitted": [_item("Folder structure of the BMS export", "Gives the parts of each plant and unit."),
                       _item("Knowledge model templates", "Say an air handler feeds its boxes, a plant feeds coils."),
                       _item("Schematics and schedules", "Would confirm each link.", False)],
         "created": [
             _item("Part-of links", f"{rel['hasPart']}"),
             _item("Feeds links", f"{rel['feeds']}: " + ", ".join(f"{n} {m.replace('_', ' ')}"
                                                                 for m, n in medium.most_common())),
             _item("Same thing, two names", "A schedule tag matched to its BMS name, so each unit is one node.", False)],
         "table": None},

        {"id": "sequences", "title": "Attach the sequences", "status": "partly", "layers": ["kg", "km"],
         "page": "sequences", "page_label": "Sequences",
         "what": "The sequence of operations is tied to the points it talks about: loops, interlocks, resets. What it "
                 "needs and cannot find is listed.",
         "submitted": [_item("Sequences of operation", f"{beh['sequences']} sequences") if doc else
                       _item("Sequences of operation", "None for this project.", False),
                       _item("The points from step 3", "Found through their role on the equipment template.")],
         "created": [
             _item("Behaviour links", f"{len(doc_edges)}: " + ", ".join(f"{n} {r}" for r, n in doc_rel.most_common())),
             _item("Equipment covered", f"{len(covered & {n['id'] for n in equip})} of {len(equip)}: each sequence "
                                        "is tied to one example unit"),
             _item("Findings", f"{beh['findings'].get('gap', 0)} points a sequence needs and the graph lacks, "
                               f"{beh['findings'].get('conflict', 0)} typed differently from what it implies"),
             _item("Every unit of the type", f"The same sequence applied to all {eq_classes.get('VAV', 0)} VAV boxes, "
                                             "with setpoints as data.", False)],
         "table": None},

        {"id": "review", "title": "Review", "status": "partly", "layers": ["kg", "tribal"], "page": "tree",
         "page_label": "Tree",
         "what": "A person accepts or fixes what was proposed. Their fixes and notes are the tribal knowledge the "
                 "next run uses.",
         "submitted": [_item("Everything created so far", f"{len(nodes) + len(edges):,} facts")],
         "created": [
             _item("Checked by a person", f"{trusts['verified']}"),
             _item("Stated by a document", f"{trusts['stated']}"),
             _item("Decided by the mapper", f"{trusts['likely']:,} with high confidence, {trusts['unsure']:,} unsure"),
             _item("Notes", f"{notes}"),
             _item("A review queue", "Today every mapper fact is saved as confirmed straight away; a queue of "
                                     "proposed facts, each next to its source page, is not built.", False)],
         "table": None},

        {"id": "use", "title": "Use", "status": "real", "layers": ["kg"], "page": "Equipment_3D",
         "page_label": "Equipment 3D",
         "what": "The same graph draws the graphics and the twin, and answers an agent's questions.",
         "submitted": [_item("The knowledge graph", f"{len(nodes):,} nodes, {len(edges):,} relationships")],
         "created": [
             _item("Equipment graphics", f"{with_template} units drawn from their template, with points placed"),
             _item("Digital twin", "The building in 3D; floors inferred, values simulated"),
             _item("Agent tools", "find_nodes, describe, upstream, downstream, behaviour")]
         + ([_item("Example: describe " + example["name"],
                   f"{example['class']}, {len(example['points'])} points with roles, fed by "
                   + ", ".join(f["name"] for f in example["fed_by"]))] if example else []),
         "table": None},
    ]

    # What exists once each step is done: the running totals shown under the steps.
    grown = {"read": {"Raw records": len(points)},
             "assets": {"Equipment": len(equip), "Points": len(points), "Relationships": rel["hasPoint"]},
             "connect": {"Relationships": rel["hasPoint"] + rel["hasPart"] + rel["feeds"]},
             "sequences": {"Relationships": len(edges), "Behaviour links": len(doc_edges)},
             "review": {"Checked by a person": trusts["verified"]}}
    totals = {"Raw records": 0, "Equipment": 0, "Points": 0, "Relationships": 0, "Behaviour links": 0,
              "Checked by a person": 0}
    for n, s in enumerate(out):
        totals = totals | grown.get(s["id"], {})
        s |= {"n": n, "totals": dict(totals)}
    return out
