"""The knowledge graph of a building being set up, in the shape the app's graph viewer already draws (viz.py,
app/graph3d.html): floors and rooms, units, points, and the links between them, each with its provenance.

    floor   -hasPart->      room
    unit    -serves->       room        a terminal unit feeds its room
    unit    -hasLocation->  room/floor  other units stand in a room, or on a floor
    unit    -feeds->        unit        AHU -> box, pump -> chiller, chiller -> AHU
    unit    -hasPoint->     point

Every node carries `fact`, the id of the fact it was read from, so a click in the viewer can open the document at
that place. The graph grows with each document: the source file of every node says which one added it.
"""
from __future__ import annotations

from ..knowledge_model import KnowledgeModel
from ..viz import add_model_layer
from .state import Intake


def _prov(f: dict) -> dict:
    s = f["src"]
    ref = s.get("sheet") or ""
    if s.get("page") is not None:
        ref = f"{ref} page {s['page'] + 1}".strip()
    if s.get("row"):
        ref = f"{ref} row {s['row']}".strip()
    return {"source_file": s.get("file", ""), "source_ref": ref, "method": f["method"], "confidence": f["conf"],
            "status": f["status"]}


def payload(it: Intake, b: dict, km: KnowledgeModel | None = None) -> dict:
    nodes, links = [], []
    facts = {f["id"]: f for f in it.facts(live=True)}
    floor_ids = set()
    for f in it.facts(kind="floor", live=True):
        fid = f"floor:{f['data']['floor']}"
        floor_ids.add(fid)
        nodes.append({"id": fid, "label": f["data"]["name"], "kind": "location", "cls": "Floor", "layer": "instance",
                      "prov": _prov(f), "fact": f["id"], "attrs": {}})
    room_ids = {}
    for r in b["rooms"]:
        f = facts[r["fact"]]
        rid = f"room:{r['number']}"
        room_ids[r["number"]] = rid
        nodes.append({"id": rid, "label": f"{r['number']} {r['name']}".strip(), "kind": "location", "cls": "Room",
                      "layer": "instance", "prov": _prov(f), "fact": f["id"], "attrs": {}})
        if f"floor:{r['floor']}" in floor_ids:
            links.append({"source": f"floor:{r['floor']}", "target": rid, "rel": "hasPart", "prov": _prov(f)})

    unit_ids = {}
    for n, e in b["equip"].items():
        f = facts.get(e["fact"])
        if not f:
            continue
        uid = f"unit:{n}"
        unit_ids[n] = uid
        nodes.append({"id": uid, "label": e["tag"], "kind": "equipment", "cls": e["class"], "layer": "instance",
                      "prov": _prov(f), "fact": e["facts"][0], "facts": e["facts"],
                      "attrs": {"points": e["points"], **({"template": e["schedule"].title()} if e["schedule"] else {}),
                                **({"evidence": f"room from: {e['room_source']}"} if e.get("room_source") else {})}})
        where = facts.get(e.get("room_fact") or "")
        if e["room"] in room_ids and where:
            links.append({"source": uid, "target": room_ids[e["room"]], "rel": "serves" if e["terminal"] else "hasLocation",
                          "prov": _prov(where)})
        elif e["floor"] and f"floor:{e['floor']}" in floor_ids and where:
            links.append({"source": uid, "target": f"floor:{e['floor']}", "rel": "hasLocation", "prov": _prov(where)})
    for r in b["relations"]:
        d = r["data"]
        if d["rel"] == "feeds" and d["src"] in unit_ids and d["dst"] in unit_ids:
            links.append({"source": unit_ids[d["src"]], "target": unit_ids[d["dst"]], "rel": "feeds", "prov": _prov(r)})

    by_device = {e["controller"]["device"]: n for n, e in b["equip"].items() if e["controller"]}
    bms = {o["data"].get("ref"): o for o in it.facts(kind="bms_object", live=True)}
    for p in b["points"]:
        d = p["data"]
        owner = by_device.get(d["device"])
        if owner not in unit_ids:
            continue
        pid = f"pt:{d['ref']}"
        seen = bms.get(d["ref"])
        nodes.append({"id": pid, "label": d.get("short") or d["ref"].split(".")[-1], "kind": "point", "cls": d["class"],
                      "layer": "instance", "prov": _prov(p), "fact": p["id"],
                      "attrs": {"evidence": d["description"] + (" · also in the BMS export" if seen else "")}})
        links.append({"source": unit_ids[owner], "target": pid, "rel": "hasPoint", "prov": _prov(p)})

    if km is not None:
        add_model_layer(nodes, links, km)
    kinds, rels = {}, {}
    for n in nodes:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    for link in links:
        rels[link["rel"]] = rels.get(link["rel"], 0) + 1
    return {"project": it.name, "nodes": nodes, "links": links, "counts": {"nodes": kinds, "links": rels},
            "notes": {}, "by_document": True}
