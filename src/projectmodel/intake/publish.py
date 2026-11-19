"""Finish a guided setup: the building becomes a project like Alpha, with every project page (tree, graph, equipment,
sequences, tables, notes, tribal knowledge, digital twin) reading it from the store.

    unit  -> equipment node   (class, tag, floor, room, schedule attributes, controller, BMS device)
    point -> point node       (class, description, device)
    unit  -hasPoint-> point, unit -feeds-> unit
    floor, room -> location nodes (Floor, Room), floor -hasPart-> room, unit -serves / hasLocation-> room or floor
    notes (tribal knowledge)  -> the project's notes, with who said them
    location                  -> the site's confirmed location

Every row keeps the fact's provenance: the document and page or row it was read from, the method (rule or human),
the confidence, and whether it is confirmed. Floors and rooms are location nodes, so the digital twin builds the
building from the graph: its levels, its rooms where the plans put them, each unit in its room. Publishing again replaces the project's rows; nothing is written back to the setup.
"""
from __future__ import annotations

import json
import time

from ..db.store import METHODS, Store
from ..locate import Location, save_location
from . import knowledge
from .model import building
from .state import Intake

INPUT = "documents"
FAMILY_TEMPLATE = {"vav": "vav", "fvav": "vav", "ahu": "ahu", "fcu": "fcu", "chiller": "chiller", "boiler": "boiler",
                   "pump": "pump"}
FAMILY_CLASS = {"ahu": "AHU", "chiller": "Chiller", "boiler": "Boiler", "pump": "Pump", "ef": "Exhaust_Fan"}


def project_id(it: Intake) -> str:
    return f"{it.slug}/{INPUT}"


def _prov(f: dict | None) -> tuple[str, str, str, float, str]:
    if not f:
        return "guided setup", "", "rule", 0.7, "proposed"
    s = f["src"]
    ref = " ".join(x for x in (s.get("sheet") or "", f"page {s['page'] + 1}" if s.get("page") is not None else "",
                               f"row {s['row']}" if s.get("row") else "") if x)
    method = f["method"] if f["method"] in METHODS else "rule"
    return s.get("file", "") or "guided setup", ref, method, round(float(f["conf"]), 4), f["status"]


def delete_project(store: Store, project: str, keep_notes: bool = False) -> None:
    """Remove the project's rows. `keep_notes`: keep notes people wrote on its pages (a re-publish replaces only
    the notes that came from the setup)."""
    with store.conn:
        for table in ("nodes", "edges", "runs"):
            store.conn.execute(f"DELETE FROM {table} WHERE project = ?", (project,))
        if keep_notes:
            store.conn.execute("DELETE FROM notes WHERE project = ? AND source = 'interview' AND source_ref = ?",
                               (project, "guided setup"))
        else:
            store.conn.execute("DELETE FROM notes WHERE project = ?", (project,))


def publish(it: Intake, store: Store) -> str:
    """Write the building into the store as a project. Returns the project id."""
    project = project_id(it)
    knowledge.apply(it)
    b = building(it)
    facts = {f["id"]: f for f in it.facts(live=True)}
    delete_project(store, project, keep_notes=True)
    started = time.time()
    revision = store.start_run(project, "guided setup")
    nodes, edges = [], []
    for n, e in b["equip"].items():
        if e["status"] == "rejected":
            continue
        src, ref, method, conf, status = _prov(facts.get(e["fact"]))
        attrs = {"tag": e["tag"], "family": e["family"], "template": FAMILY_TEMPLATE.get(e["family"]),
                 "floor": e["floor"], "room": e["room"], "room_rel": e["rel"], "room_source": e.get("room_source"),
                 "schedule": e["schedule"], "controller": e["controller"], "bms_device": e["bms"],
                 "sequence": e["sequence"], "points": e["points"], **{k: v for k, v in e["attrs"].items()}}
        cls = e["class"] if e["class"] not in (None, "", "Equipment") else FAMILY_CLASS.get(e["family"], e["class"])
        nodes.append((project, f"unit:{n}", "equipment", e["tag"], cls, src, ref, method, conf, status, revision,
                      json.dumps(attrs, default=str)))
    units = {r[1] for r in nodes}
    _spaces(b, facts, project, revision, units, nodes, edges)
    by_device = {e["controller"]["device"]: n for n, e in b["equip"].items() if e["controller"]}
    for p in b["points"]:
        d = p["data"]
        owner = f"unit:{by_device.get(d['device'])}"
        if owner not in units or p["status"] == "rejected":
            continue
        pid = f"pt:{d['ref']}"
        src, ref, method, conf, status = _prov(p)
        nodes.append((project, pid, "point", d.get("short") or d["ref"].split(".")[-1], d.get("class"), src, ref,
                      method, conf, status, revision,
                      json.dumps({"description": d.get("description", ""), "device": d["device"], "ref": d["ref"],
                                  "path": owner.split(":", 1)[1]})))
        edges.append((project, owner, "hasPoint", pid, src, ref, method, conf, status, revision, "{}"))
    for r in b["relations"]:
        d = r["data"]
        s, t = f"unit:{d['src']}", f"unit:{d['dst']}"
        if d["rel"] == "feeds" and s in units and t in units:
            src, ref, method, conf, status = _prov(r)
            edges.append((project, s, "feeds", t, src, ref, method, conf, status, revision,
                          json.dumps({"medium": d.get("medium")})))
    with store.conn:
        store.conn.executemany(
            "INSERT OR IGNORE INTO nodes (project, id, kind, label, class, source_file, source_ref, method,"
            " confidence, status, revision, attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", nodes)
        store.conn.executemany(
            "INSERT OR IGNORE INTO edges (project, src, rel, dst, source_file, source_ref, method, confidence,"
            " status, revision, attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", edges)
    _notes(it, store, project, units)
    if loc := it.location:
        fields = Location.__dataclass_fields__
        save_location(store, it.slug, Location(**{k: v for k, v in loc.items() if k in fields}),
                      loc.get("confirmed_by", "you"))
    store.finish_run(project, revision, round(time.time() - started, 2),
                     {"source": "guided setup", "equipment": sum(1 for r in nodes if r[2] == "equipment"),
                      "points": sum(1 for r in nodes if r[2] == "point"), "links": len(edges)})
    it.s["published"] = {"project": project, "at": time.time(), "revision": revision}
    it.save()
    return project


def _spaces(b: dict, facts: dict, project: str, revision: int, units: set[str], nodes: list, edges: list) -> None:
    """Floors and rooms as location nodes, in the shape of the setup's own graph (intake/graph.py): floor -hasPart->
    room, terminal -serves-> room, other units -hasLocation-> room (or floor). Each floor keeps its level order and
    its plan's proportions, each room where its number sits on that plan (0..1 of the plan area), so the digital
    twin can lay the building out the way the drawings do."""
    crops = {}
    for order, f in enumerate(b["floors"]):
        if f.get("status") == "rejected":
            continue
        src, ref, method, conf, status = _prov(facts.get(f"floor:{f['id']}"))
        crop = f.get("crop")
        aspect = round((crop[3] - crop[1]) / (crop[2] - crop[0]), 4) if crop and crop[2] > crop[0] else None
        crops[f["id"]] = crop
        nodes.append((project, f"floor:{f['id']}", "location", f["name"], "Floor", src, ref, method, conf, status,
                      revision,
                      json.dumps({"level": f["id"], "order": order, "aspect": aspect, "sheet": f.get("sheet")})))
    floors = {r[1] for r in nodes if r[2] == "location"}
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
        nodes.append((project, rid, "location", f"{r['number']} {r['name']}".strip(), "Room", src, ref, method, conf,
                      status, revision, json.dumps({"floor": r["floor"], "number": r["number"], "name": r["name"],
                                                    "xy": at})))
        edges.append((project, f"floor:{r['floor']}", "hasPart", rid, src, ref, method, conf, status, revision, "{}"))
    for n, e in b["equip"].items():
        uid = f"unit:{n}"
        if uid not in units:
            continue
        src, ref, method, conf, status = _prov(facts.get(e.get("room_fact") or ""))
        if f"room:{e['room']}" in rooms:
            edges.append((project, uid, "serves" if e["terminal"] else "hasLocation", f"room:{e['room']}", src, ref,
                          method, conf, status, revision, "{}"))
        elif f"floor:{e['floor']}" in floors:
            edges.append((project, uid, "hasLocation", f"floor:{e['floor']}", src, ref, method, conf, status,
                          revision, "{}"))


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
