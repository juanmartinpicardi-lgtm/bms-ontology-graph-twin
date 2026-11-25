"""Finish a guided setup: the building becomes a project like Alpha, with every project page (tree, graph, equipment,
sequences, tables, notes, tribal knowledge, digital twin) reading it from the store.

    unit  -> equipment node   (class, tag, floor, room, schedule attributes, controller, BMS device)
    point -> point node       (class, description, device, units with their QUDT id, BACnet object)
    unit  -hasPoint-> point, unit -feeds-> unit
    floor, room -> location nodes (Floor, Room), floor -hasPart-> room, unit -serves / hasLocation-> room or floor
    project record -> Site and Building nodes, site -hasPart-> building -hasPart-> floor
    zone (where a source states one) -> HVAC_Zone node, zone -hasPart-> room, unit -feeds-> zone
    riser row -> controller node (ba:Field_Controller, one per BACnet device instance) and its trunk (ba:Field_Network):
                 controller -isOnNetwork-> trunk, controller -controls-> unit, point -isHostedBy-> controller;
                 the supervisory controller the point references name (NAE/FC-1...) -isOnNetwork-> each trunk
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
    - every step gives its names for the thing as aliases: schedule_tag, submittal_ref, bms_name for a unit;
      bacnet_device (the device instance) for a controller; device_object (device instance:object type:object
      instance) for a point. The BMS export states the controllers, trunks and hosting it sees as well, so the riser
      and the BMS agree on them, or disagree in the open.
`publish(it, store, steps=["bms"])` re-publishes one step and leaves the others' rows, and every decision people
made in the app, as they are. Publishing everything also removes steps that no longer say anything. Statuses are the
store's (db/store.py): a person's answer in the setup is confirmed_by human; a question still open holds the row as
proposed. Nothing is written back to the setup.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict

from ..db.store import METHODS, Claim, Edge, Node, Store
from ..locate import Location, save_location
from ..units import point_unit
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
PROJECT = "setup:project"  # the project record: the building's name and address, as a person typed them
CONTROLLER, NETWORK, SUPERVISOR = "Field_Controller", "Field_Network", "Supervisory_Controller"
ROOM_IN_LOCATION = re.compile(r"/\s*([A-Z]?\d{3,4}[A-Z]?)\s*$")  # a riser's "Level 1 / 144": room 144


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
    if f["kind"] == "controller":  # the BACnet device instance names the controller, not the unit (controller_id)
        return [("submittal_ref", d.get("device"))]
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
    floors, rooms = _spaces(b, facts, units, put)
    _project(it, b, facts, floors, out, put)
    _zones(b, facts, units, rooms, put)
    hosts = _controllers(facts, units, rooms, put)

    by_device = {e["controller"]["device"]: n for n, e in b["equip"].items() if e["controller"]}
    instance = {f["data"]["device"]: f["data"].get("instance") for f in facts.values() if f["kind"] == "controller"}
    points = {}
    for p in b["points"]:
        d = p["data"]
        owner = f"unit:{by_device.get(d['device'])}"
        host = hosts.get(d["device"])  # the riser's controller: a point is on it even before its unit is known
        if owner not in units:
            owner = None
        if (owner is None and host is None) or p["status"] == "rejected":
            continue
        pid = f"pt:{d['ref']}"
        points[pid] = owner
        src, ref, method, conf, status = _prov(p)
        aliases = [("submittal_ref", d["ref"])]
        bacnet = {"device_instance": instance.get(d["device"]), "object_type": d.get("object") or None,
                  "object_instance": d.get("object_instance")}
        if None not in bacnet.values():
            aliases.append(("device_object", device_object(**bacnet)))
        put(p, "nodes", Node(pid, "point", d.get("short") or d["ref"].split(".")[-1], d.get("class"), src, ref,
                             method, conf,
                             {"description": d.get("description", ""), "device": d["device"], "ref": d["ref"],
                              "path": owner.split(":", 1)[1] if owner else d["device"],
                              **({"io": d["io"]} if d.get("io") else {}), **point_unit(d.get("units")),
                              **({"bacnet": {k: v for k, v in bacnet.items() if v is not None}}
                                 if any(v is not None for v in bacnet.values()) else {}),
                              **({"rule_class": d.get("rule_class"),  # the AI's answer and what the rules said
                                  "ai": {k: d["ai"].get(k) for k in ("model", "why", "calls")}}
                                 if d.get("ai") else {})},
                             aliases=aliases, status=status))
        if owner:
            put(p, "edges", Edge(owner, "hasPoint", pid, src, ref, method, conf, status=status))
        if host:  # where the point lives: its reference names its device, the riser that device's controller
            put(p, "edges", Edge(pid, "isHostedBy", host, src, ref, "parsed", 0.95))
    # The BMS export: each object the submittal promised names that point, and sits on the unit its device is.
    bms_unit = {f["data"]["device"]: f"unit:{f['data']['equip']}" for f in facts.values()
                if f["kind"] == "alias" and f["data"].get("equip")}
    bms_hosts = _bms_controllers(facts, units, put)
    for f in facts.values():
        if f["kind"] != "bms_object" or not f["data"].get("matched"):
            continue
        d = f["data"]
        pid = d.get("point") or f"pt:{d['ref']}"  # the submittal point it is bound to (intake/binding.py)
        if pid not in points:
            continue
        src, ref, method, conf, status = _prov(f)
        aliases = [("bms_name", d["ref"])]
        if all(d.get(k) is not None for k in ("device_instance", "object_type", "object_instance")):
            aliases.append(("device_object", device_object(d["device_instance"], d["object_type"],
                                                           d["object_instance"])))
        put(f, "claims", Claim(pid, src, ref, method, conf, aliases=aliases))
        if (unit := bms_unit.get(d["device"])) in units:
            put(f, "claims", Claim(unit, src, ref, method, conf, rel="hasPoint", dst=pid))
        if host := bms_hosts.get(d["device"]):  # the BMS device the object sits on
            put(f, "edges", Edge(pid, "isHostedBy", host, src, ref, "parsed", 0.95))

    for r in b["relations"]:
        d = r["data"]
        s, t = f"unit:{d['src']}", f"unit:{d['dst']}"
        if d["rel"] == "feeds" and s in units and t in units:
            src, ref, method, conf, status = _prov(r)
            put(r, "edges", Edge(s, "feeds", t, src, ref, method, conf, {"medium": d.get("medium")}, status=status))
    return out


def _unit_class(cls: str | None, family: str) -> str | None:
    return cls if cls not in (None, "", "Equipment") else FAMILY_CLASS.get(family, cls)


def _spaces(b: dict, facts: dict, units: set[str], put) -> tuple[set[str], set[str]]:
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
    return floors, rooms


# Site, building, zones ---------------------------------------------------------------------------------------------

def _project(it: Intake, b: dict, facts: dict, floors: set[str], out: dict, put) -> None:
    """One Site and one Building per project, from the project record: the name a person gave the building and its
    address (or the location they confirmed). The building has every floor the plans give, the site the building."""
    loc = it.location or {}
    address = loc.get("address") or (it.s or {}).get("address") or ""
    record = "project record" + (f" (location confirmed by {loc['confirmed_by']})" if loc.get("confirmed_by") else "")
    site_attrs = {k: loc[k] for k in ("address", "lat", "lng", "provider") if loc.get(k) is not None}
    if address and "address" not in site_attrs:
        site_attrs["address"] = address
    out[PROJECT]["nodes"] += [
        Node("building", "location", it.name, "Building", "guided setup", "project record", "human", 1.0,
             {"name": it.name}, status="confirmed"),
        # A building stands on a site: with no address the site is still there, named after the building.
        Node("site", "location", address or f"{it.name} site", "Site", "guided setup", record,
             "human" if address else "rule", 1.0 if address else 0.9, site_attrs,
             status="confirmed" if address else None)]
    out[PROJECT]["edges"].append(Edge("site", "hasPart", "building", "guided setup", "project record", "human", 1.0,
                                   status="confirmed"))
    for f in b["floors"]:  # each floor is on this building's plans
        if f"floor:{f['id']}" not in floors:
            continue
        fact = facts.get(f"floor:{f['id']}")
        src, ref, method, conf, status = _prov(fact)
        put(fact, "edges", Edge("building", "hasPart", f"floor:{f['id']}", src, ref, method, conf, status=status))


def _zones(b: dict, facts: dict, units: set[str], rooms: set[str], put) -> None:
    """HVAC zones only where a source states one, never inferred:
      - a `zone` fact (a plan's zone label, a zone schedule): {"zone", "name", "floor", "rooms": [numbers]};
      - a schedule column that names the zone a unit serves (attribute `zone` on the unit's schedule row).
    zone -hasPart-> room for the rooms it lists; unit -feeds-> zone (air) for the units whose row names it."""
    for f in facts.values():
        if f["kind"] != "zone" or f.get("status") == "rejected":
            continue
        d = f["data"]
        zid = f"zone:{d['zone']}"
        src, ref, method, conf, status = _prov(f)
        put(f, "nodes", Node(zid, "location", d.get("name") or d["zone"], "HVAC_Zone", src, ref, method, conf,
                             {k: d[k] for k in ("zone", "floor", "rooms") if d.get(k)}, status=status))
        for r in d.get("rooms") or []:
            if f"room:{r}" in rooms:
                put(f, "edges", Edge(zid, "hasPart", f"room:{r}", src, ref, method, conf, status=status))
    for n, e in b["equip"].items():
        z = (e.get("attrs") or {}).get("zone")
        if not z or f"unit:{n}" not in units or e["status"] == "rejected":
            continue
        f = facts.get(e["fact"])
        src, ref, method, conf, status = _prov(f)
        put(f, "nodes", Node(f"zone:{z}", "location", str(z), "HVAC_Zone", src, ref, method, conf, {"zone": z},
                             status=status))
        put(f, "edges", Edge(f"unit:{n}", "feeds", f"zone:{z}", src, ref, method, conf, {"medium": "air"},
                             status=status))


# Controllers and networks ------------------------------------------------------------------------------------------

def device_object(device_instance, object_type, object_instance) -> str:
    """The BACnet name of a point, the same from every source: device instance:object type:object instance."""
    return f"{device_instance}:{str(object_type).strip().lower()}:{object_instance}"


def controller_id(device: str, instance=None) -> str:
    """A controller is one BACnet device: keyed on its device instance (several units may share one, e.g. a gateway),
    on its name when no instance is given."""
    return f"ctrl:{instance}" if instance not in (None, "") else f"ctrl:{device}"


def _supervisor(ref: str) -> tuple[str, str] | None:
    """(supervisory controller, trunk) a Metasys-style reference names: SITE-NAE01/FC-1.AHU-1.SF-C."""
    m = re.match(r"^([^/\s]+)/([^./\s]+)\.", ref or "")
    return (m.group(1), m.group(2)) if m else None


def _network_ids(refs: list[str]):
    """network id for a trunk: scoped by its supervisory controller when the references name exactly one for it (two
    supervisors may each have an FC-1), else the trunk alone."""
    sups = defaultdict(set)
    for r in refs:
        if sv := _supervisor(r):
            sups[sv[1]].add(sv[0])

    def net(trunk: str) -> str:
        s = sups.get(trunk, set())
        return f"net:{next(iter(s))}/{trunk}" if len(s) == 1 else f"net:{trunk}"
    return net


def _controllers(facts: dict, units: set[str], rooms: set[str], put) -> dict[str, str]:
    """The riser: one controller node per BACnet device (ba:Field_Controller) on its trunk (ba:Field_Network), the
    unit(s) it controls where the riser links it to one, the room it sits in where the riser names one, and the
    supervisory controller the point references name, on each trunk it serves. Returns device name -> controller id,
    for the points it hosts."""
    ctrl = [f for f in facts.values() if f["kind"] == "controller" and f.get("status") != "rejected"]
    refs = [f["data"]["ref"] for f in facts.values() if f["kind"] == "point"]
    net = _network_ids(refs)
    hosts, seen_ctrl, seen_net = {}, {}, set()
    for f in ctrl:
        d = f["data"]
        cid = controller_id(d["device"], d.get("instance"))
        hosts[d["device"]] = cid
        src, ref = _prov(f)[:2]
        # The riser row is read as written (parsed); a question about which unit it is touches only `controls`.
        if cid in seen_ctrl:
            seen_ctrl[cid].attrs["devices"].append(d["device"])
            seen_ctrl[cid].label = f"{', '.join(seen_ctrl[cid].attrs['devices'])} · {d['controller']}"
        else:
            node = Node(cid, "controller", f"{d['device']} · {d['controller']}", CONTROLLER, src, ref, "parsed", 0.95,
                        {"devices": [d["device"]], "model": d["controller"], "instance": d.get("instance"),
                         "trunk": d.get("trunk"), "address": d.get("address"), "location": d.get("location")},
                        aliases=[("bacnet_device", d.get("instance"))])
            seen_ctrl[cid] = node
            put(f, "nodes", node)
            if d.get("trunk"):
                nid = net(d["trunk"])
                if nid not in seen_net:
                    seen_net.add(nid)
                    name = d.get("trunk_name")
                    put(f, "nodes", Node(nid, "network", f"{d['trunk']} · {name}" if name else d["trunk"], NETWORK,
                                         src, ref, "parsed", 0.95, {"trunk": d["trunk"], "name": name}))
                put(f, "edges", Edge(cid, "isOnNetwork", nid, src, ref, "parsed", 0.95, {"address": d.get("address")}))
            m = ROOM_IN_LOCATION.search(d.get("location") or "")
            if m and f"room:{m.group(1)}" in rooms:
                put(f, "edges", Edge(cid, "hasLocation", f"room:{m.group(1)}", src, ref, "parsed", 0.9))
        if f"unit:{d.get('equip')}" in units:  # the riser says which unit; a person may have said it instead
            src, ref, method, conf, status = _prov(f)
            put(f, "edges", Edge(cid, "controls", f"unit:{d['equip']}", src, ref, method, conf, status=status))
    _supervisors([f for f in facts.values() if f["kind"] == "point"], lambda f: f["data"]["ref"], net, seen_net, put)
    return hosts


def _supervisors(rows: list[dict], ref_of, net, trunks: set[str], put) -> None:
    """The supervisory controller (a Metasys NAE, a Niagara JACE) each reference starts with, on every trunk of the
    graph it names. Stated by the rows (points, BMS objects) whose references say so; the first row is the source."""
    first = {}
    for f in rows:
        sv = _supervisor(ref_of(f))
        if sv and (sv, net(sv[1])) not in first:
            first[(sv, net(sv[1]))] = f
    done = set()
    for ((sup, _trunk), nid), f in first.items():
        if nid not in trunks:
            continue
        src, ref = _prov(f)[:2]
        sid = f"ctrl:{sup}"
        if sid not in done:
            done.add(sid)
            put(f, "nodes", Node(sid, "controller", sup, SUPERVISOR, src, ref, "parsed", 0.9,
                                 {"devices": [sup], "from": "the point references name it"}))
        put(f, "edges", Edge(sid, "isOnNetwork", nid, src, ref, "parsed", 0.9))


def _bms_controllers(facts: dict, units: set[str], put) -> dict[str, str]:
    """What the BMS export says about the same devices: each device with a BACnet instance is a controller, on the
    trunk its rows name; it controls the unit it is named after (the same tag; a link it took from the riser is the
    riser's, not a second opinion). Where the riser said the same, the two agree. Returns BMS device -> controller."""
    objs = [f for f in facts.values() if f["kind"] == "bms_object"]
    net = _network_ids([f["data"]["ref"] for f in objs])
    hosts, seen, trunks = {}, set(), set()
    for f in facts.values():
        d = f["data"]
        if f["kind"] != "alias" or d.get("instance") in (None, ""):
            continue
        cid = controller_id(d["device"], d["instance"])
        hosts[d["device"]] = cid
        src, ref, method, conf, status = _prov(f)
        if cid not in seen:
            seen.add(cid)
            put(f, "nodes", Node(cid, "controller", d["device"], CONTROLLER, src, ref, "parsed", 0.95,
                                 {"devices": [d["device"]], "instance": d["instance"], "trunk": d.get("trunk"),
                                  "address": d.get("address")}, aliases=[("bacnet_device", d["instance"])]))
            if d.get("trunk"):
                nid = net(d["trunk"])
                if nid not in trunks:
                    trunks.add(nid)
                    put(f, "nodes", Node(nid, "network", d["trunk"], NETWORK, src, ref, "parsed", 0.95,
                                         {"trunk": d["trunk"]}))
                put(f, "edges", Edge(cid, "isOnNetwork", nid, src, ref, "parsed", 0.95, {"address": d.get("address")}))
        if d.get("via") == "same tag" and f"unit:{d.get('equip')}" in units:
            put(f, "edges", Edge(cid, "controls", f"unit:{d['equip']}", src, ref, method, conf, status=status))
    _supervisors(objs, lambda f: f["data"]["ref"], net, trunks, put)
    return hosts


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
