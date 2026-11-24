"""Finish a guided setup: the building becomes a project like Alpha, with every project page (tree, graph, equipment,
sequences, tables, notes, tribal knowledge, digital twin) reading it from the store.

    unit  -> equipment node   (class, tag, floor, room, schedule attributes, controller, BMS device)
    point -> point node       (class, description, device)
    unit  -hasPoint-> point, unit -feeds-> unit
    floor, room -> location nodes (Floor, Room), floor -hasPart-> room, unit -serves / hasLocation-> room or floor
    notes (tribal knowledge)  -> the project's notes, with who said them
    location                  -> the site's confirmed location

Every row keeps the fact's provenance: the document and page or row it was read from, the method (rule or human),
the confidence. Floors and rooms are location nodes, so the digital twin builds the building from the graph: its
levels, its rooms where the plans put them, each unit in its room.

Each step of the setup is a source of its own (`setup:plans`, `setup:schedules`, `setup:submittal`, `setup:bms`):
    - a row belongs to the step of the fact it is built from (a unit to its schedule row, a point to the submittal);
    - the other steps that name the same thing add claims: the plan's tag and class for a unit, the riser's controller
      and the BMS device for a unit, the BMS object and the BMS device it sits on for a point, the plan's room for a
      unit the submittal places. Two steps stating the same fact confirm it; two different answers are a conflict;
    - every step gives its names for the thing as aliases: schedule_tag, submittal_ref and bacnet_device, bms_name,
      device_object (BACnet device instance:object for a point).
`publish(it, store, steps=["bms"])` re-publishes one step and leaves the others' rows, and every decision people
made in the app, as they are. Publishing everything also removes steps that no longer say anything. Statuses are the
store's (db/store.py): a person's answer in the setup is confirmed_by human; a question still open holds the row as
proposed. Nothing is written back to the setup.
"""
from __future__ import annotations

import time
from collections import defaultdict

from ..db.store import METHODS, Claim, Edge, Node, Store
from ..locate import Location, save_location
from . import knowledge, sequence_ai
from .model import building
from .state import Intake

INPUT = "documents"
FAMILY_TEMPLATE = {"vav": "vav", "fvav": "vav", "ahu": "ahu", "fcu": "fcu", "chiller": "chiller", "boiler": "boiler",
                   "pump": "pump"}
FAMILY_CLASS = {"ahu": "AHU", "chiller": "Chiller", "boiler": "Boiler", "pump": "Pump", "ef": "Exhaust_Fan"}
# Which step writes first, so it owns a row two steps state: the schedule's unit, the plan's rooms, the submittal's
# points; later steps add claims.
STEP_ORDER = ("schedules", "plans", "sequences", "submittal", "bms")
NO_FACT = "setup:guided"  # rows no single fact gives


def project_id(it: Intake) -> str:
    return f"{it.slug}/{INPUT}"


def source_of(f: dict | None) -> str:
    return f"setup:{f['step']}" if f and f.get("step") else NO_FACT


def _order(source: str) -> tuple:
    step = source.split(":", 1)[1]
    return (STEP_ORDER.index(step) if step in STEP_ORDER else len(STEP_ORDER), source)


def _prov(f: dict | None) -> tuple[str, str, str, float, str | None]:
    """source_file, source_ref, method, confidence, and the status the store is told: a person's answer, `proposed`
    while the setup still asks about it, else None (the store decides)."""
    if not f:
        return "guided setup", "", "rule", 0.7, None
    s = f["src"]
    ref = " ".join(x for x in (s.get("sheet") or "", f"page {s['page'] + 1}" if s.get("page") is not None else "",
                               f"row {s['row']}" if s.get("row") else "") if x)
    method = f["method"] if f["method"] in METHODS else "rule"
    status = f["status"] if method == "human" else "proposed" if f.get("ask") and f["status"] == "proposed" else None
    return s.get("file", "") or "guided setup", ref, method, round(float(f["conf"]), 4), status


def _aliases(f: dict | None) -> list[tuple[str, str]]:
    """The names a fact gives for the unit it is about."""
    if not f:
        return []
    d = f["data"]
    if f["kind"] in ("equipment", "placement"):
        return [("schedule_tag", d.get("tag"))]
    if f["kind"] == "controller":
        return [("submittal_ref", d.get("device")), ("bacnet_device", d.get("instance"))]
    if f["kind"] == "alias":
        return [("bms_name", d.get("device"))]
    return []


def delete_project(store: Store, project: str, keep_notes: bool = False) -> None:
    """Remove the project's rows. `keep_notes`: keep notes people wrote on its pages (only the notes that came from
    the setup go)."""
    store.delete_project(project)
    with store.conn:
        if keep_notes:
            store.conn.execute("DELETE FROM notes WHERE project = ? AND source = 'interview' AND source_ref = ?",
                               (project, "guided setup"))
        else:
            store.conn.execute("DELETE FROM notes WHERE project = ?", (project,))


def publish(it: Intake, store: Store, steps: list[str] | None = None) -> str:
    """Write the building into the store as a project. Returns the project id. `steps`: re-publish only these steps
    of the setup (e.g. ["bms"]); the other steps' rows stay as they are."""
    project = project_id(it)
    knowledge.apply(it)
    out = statements(it)
    out.update(sequence_ai.statements(it, out))  # W8: the sequences' control logic, its own source
    started = time.time()
    revision = store.start_run(project, "guided setup" + (f": {', '.join(steps)}" if steps else ""))
    if steps is None:
        for gone in set(store.sources(project)) - set(out):
            store.remove_source(project, gone)
        todo = sorted(out, key=_order)
    else:
        todo = sorted({f"setup:{s}" for s in steps}, key=_order)
    written = {}
    for source in todo:
        st = out.get(source, {})
        written[source] = store.write_source(project, source, revision, st.get("nodes", []), st.get("edges", []),
                                             st.get("claims", []))
    with store.conn:
        store.conn.execute("DELETE FROM notes WHERE project = ? AND source = 'interview' AND source_ref = ?",
                           (project, "guided setup"))
    units = {r["id"] for r in store.nodes(project, "equipment")}
    _notes(it, store, project, units)
    if loc := it.location:
        fields = Location.__dataclass_fields__
        save_location(store, it.slug, Location(**{k: v for k, v in loc.items() if k in fields}),
                      loc.get("confirmed_by", "you"))
    store.finish_run(project, revision, round(time.time() - started, 2),
                     {"source": "guided setup", "steps": [s.split(":", 1)[1] for s in todo], "written": written,
                      "equipment": len(units), "points": len(store.nodes(project, "point")),
                      "links": len(store.edges(project))})
    it.s["published"] = {"project": project, "at": time.time(), "revision": revision}
    it.save()
    return project


def statements(it: Intake) -> dict[str, dict[str, list]]:
    """Per source (setup step): the nodes and edges it writes, and the claims it makes on rows other steps write."""
    b = building(it)
    facts = {f["id"]: f for f in it.facts(live=True)}
    out: dict[str, dict[str, list]] = defaultdict(lambda: {"nodes": [], "edges": [], "claims": []})

    def put(f, what, item):
        out[source_of(f)][what].append(item)

    units = set()
    for n, e in b["equip"].items():
        if e["status"] == "rejected":
            continue
        f = facts.get(e["fact"])
        src, ref, method, conf, status = _prov(f)
        attrs = {"tag": e["tag"], "family": e["family"], "template": FAMILY_TEMPLATE.get(e["family"]),
                 "floor": e["floor"], "room": e["room"], "room_rel": e["rel"], "room_source": e.get("room_source"),
                 "schedule": e["schedule"], "controller": e["controller"], "bms_device": e["bms"],
                 "sequence": e["sequence"], "points": e["points"], **{k: v for k, v in e["attrs"].items()}}
        cls = _unit_class(e["class"], e["family"])
        uid = f"unit:{n}"
        units.add(uid)
        put(f, "nodes", Node(uid, "equipment", e["tag"], cls, src, ref, method, conf, attrs,
                             aliases=_aliases(f) or [("schedule_tag", e["tag"])], status=status))
        for fid in dict.fromkeys(e["facts"]):  # what the other steps say about this unit
            g = facts.get(fid)
            if not g or fid == e["fact"]:
                continue
            gsrc, gref, gmethod, gconf, gstatus = _prov(g)
            if g["kind"] == "placement":  # the plan's tag, and the class its tag implies (a generic one says nothing)
                plan_cls = _unit_class(g["data"].get("class"), e["family"])
                put(g, "nodes", Node(uid, "equipment", e["tag"], None if plan_cls == "Equipment" else plan_cls,
                                     gsrc, gref, gmethod, gconf, attrs, aliases=_aliases(g), status=gstatus))
            else:  # the riser's controller, the BMS device, the room schedule: they name the unit
                put(g, "claims", Claim(uid, gsrc, gref, gmethod, gconf, aliases=_aliases(g)))
    _spaces(b, facts, units, put)

    by_device = {e["controller"]["device"]: n for n, e in b["equip"].items() if e["controller"]}
    instance = {f["data"]["device"]: f["data"].get("instance") for f in facts.values() if f["kind"] == "controller"}
    points = {}
    for p in b["points"]:
        d = p["data"]
        owner = f"unit:{by_device.get(d['device'])}"
        if owner not in units or p["status"] == "rejected":
            continue
        pid = f"pt:{d['ref']}"
        points[pid] = owner
        src, ref, method, conf, status = _prov(p)
        aliases = [("submittal_ref", d["ref"])]
        if d.get("object") and instance.get(d["device"]) is not None:
            aliases.append(("device_object", f"{instance[d['device']]}:{d['object']}"))
        put(p, "nodes", Node(pid, "point", d.get("short") or d["ref"].split(".")[-1], d.get("class"), src, ref,
                             method, conf,
                             {"description": d.get("description", ""), "device": d["device"], "ref": d["ref"],
                              "path": owner.split(":", 1)[1],
                              **({"rule_class": d.get("rule_class"),  # the AI's answer and what the rules said
                                  "ai": {k: d["ai"].get(k) for k in ("model", "why", "calls")}}
                                 if d.get("ai") else {})},
                             aliases=aliases, status=status))
        put(p, "edges", Edge(owner, "hasPoint", pid, src, ref, method, conf, status=status))
    # The BMS export: each object the submittal promised names that point, and sits on the unit its device is.
    bms_unit = {f["data"]["device"]: f"unit:{f['data']['equip']}" for f in facts.values()
                if f["kind"] == "alias" and f["data"].get("equip")}
    for f in facts.values():
        if f["kind"] != "bms_object" or not f["data"].get("matched"):
            continue
        pid = f"pt:{f['data']['ref']}"
        if pid not in points:
            continue
        src, ref, method, conf, status = _prov(f)
        put(f, "claims", Claim(pid, src, ref, method, conf, aliases=[("bms_name", f["data"]["ref"])]))
        if (unit := bms_unit.get(f["data"]["device"])) in units:
            put(f, "claims", Claim(unit, src, ref, method, conf, rel="hasPoint", dst=pid))

    for r in b["relations"]:
        d = r["data"]
        s, t = f"unit:{d['src']}", f"unit:{d['dst']}"
        if d["rel"] == "feeds" and s in units and t in units:
            src, ref, method, conf, status = _prov(r)
            put(r, "edges", Edge(s, "feeds", t, src, ref, method, conf, {"medium": d.get("medium")}, status=status))
    return out


def _unit_class(cls: str | None, family: str) -> str | None:
    return cls if cls not in (None, "", "Equipment") else FAMILY_CLASS.get(family, cls)


def _spaces(b: dict, facts: dict, units: set[str], put) -> None:
    """Floors and rooms as location nodes, in the shape of the setup's own graph (intake/graph.py): floor -hasPart->
    room, terminal -serves-> room, other units -hasLocation-> room (or floor). Each floor keeps its level order and
    its plan's proportions, each room where its number sits on that plan (0..1 of the plan area), so the digital
    twin can lay the building out the way the drawings do. Where the plan and the submittal's room schedule both
    place a unit, both say so: the same room agrees, another room is a conflict."""
    crops, floors = {}, set()
    for order, f in enumerate(b["floors"]):
        if f.get("status") == "rejected":
            continue
        fact = facts.get(f"floor:{f['id']}")
        src, ref, method, conf, status = _prov(fact)
        crop = f.get("crop")
        aspect = round((crop[3] - crop[1]) / (crop[2] - crop[0]), 4) if crop and crop[2] > crop[0] else None
        crops[f["id"]] = crop
        floors.add(f"floor:{f['id']}")
        put(fact, "nodes", Node(f"floor:{f['id']}", "location", f["name"], "Floor", src, ref, method, conf,
                                {"level": f["id"], "order": order, "aspect": aspect, "sheet": f.get("sheet")},
                                status=status))
    rooms = set()
    for r in b["rooms"]:
        fact = facts.get(r["fact"])
        if r["status"] == "rejected" or f"floor:{r['floor']}" not in floors:
            continue
        crop, xy = crops.get(r["floor"]), r.get("anchor")
        at = ([round((xy[0] - crop[0]) / (crop[2] - crop[0]), 4), round((xy[1] - crop[1]) / (crop[3] - crop[1]), 4)]
              if crop and xy else None)
        rid = f"room:{r['number']}"
        rooms.add(rid)
        src, ref, method, conf, status = _prov(fact)
        put(fact, "nodes", Node(rid, "location", f"{r['number']} {r['name']}".strip(), "Room", src, ref, method, conf,
                                {"floor": r["floor"], "number": r["number"], "name": r["name"], "xy": at},
                                status=status))
        put(fact, "edges", Edge(f"floor:{r['floor']}", "hasPart", rid, src, ref, method, conf, status=status))
    for n, e in b["equip"].items():
        uid = f"unit:{n}"
        if uid not in units:
            continue
        fact = facts.get(e.get("room_fact") or "")
        src, ref, method, conf, status = _prov(fact)
        rel = "serves" if e["terminal"] else "hasLocation"
        if f"room:{e['room']}" in rooms:
            put(fact, "edges", Edge(uid, rel, f"room:{e['room']}", src, ref, method, conf, status=status))
            for g in (facts.get(x) for x in e["facts"]):  # the other step's room for this unit
                if not g or g["id"] == (fact or {}).get("id") or g["kind"] not in ("placement", "room_check"):
                    continue
                if (other := g["data"].get("room")) and f"room:{other}" in rooms:
                    gsrc, gref, gmethod, gconf, gstatus = _prov(g)
                    put(g, "claims", Claim(uid, gsrc, gref, gmethod, gconf, rel=rel, dst=f"room:{other}"))
        elif f"floor:{e['floor']}" in floors:
            put(fact, "edges", Edge(uid, "hasLocation", f"floor:{e['floor']}", src, ref, method, conf, status=status))


def _notes(it: Intake, store: Store, project: str, units: set[str]) -> None:
    """The tribal knowledge given in the setup becomes the project's notes (source: interview)."""
    from .. import notes as project_notes
    for n in knowledge.get(it)["notes"]:
        target = n["target"]
        if target in units:
            kind, tid = "node", target
        else:
            kind, tid = "project", ""
        project_notes.add_note(store, project, kind, tid, n["label"], n["topic"], n["body"], n["author"],
                               source="interview", source_ref="guided setup")
