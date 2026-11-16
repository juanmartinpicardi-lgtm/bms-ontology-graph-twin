"""The building as the facts say it is right now: floors, rooms, equipment with its room, controller, points and
sequence; what is still missing; how far along the setup is.

A unit's room: the person's answer if there is one, else the room the submittal's room schedule and the plan agree
on, else the submittal's room, else the plan's.
"""
from __future__ import annotations

from collections import Counter

from .state import Intake
from .steps import STEPS


def building(it: Intake) -> dict:
    live = lambda kind: it.facts(kind=kind, live=True)  # noqa: E731
    floors = sorted(live("floor"), key=lambda f: _floor_order(f["data"]["floor"]))
    rooms = {r["data"]["number"]: r for r in live("room")}
    place = {p["data"]["normal"]: p for p in live("placement")}
    check = {c["data"]["normal"]: c for c in live("room_check")}
    ctrls = live("controller")
    seqs = live("sequence")
    points = live("point")
    aliases = live("alias")

    equip: dict[str, dict] = {}
    for e in live("equipment"):
        d = e["data"]
        equip[d["normal"]] = {"normal": d["normal"], "tag": d["tag"], "class": d["class"], "family": d["family"],
                              "terminal": d.get("terminal", False), "attrs": d.get("attrs", {}), "status": e["status"],
                              "conf": e["conf"], "fact": e["id"], "schedule": d.get("schedule", "")}
    for n, p in place.items():  # units seen only on plans, before the schedules are read
        if n not in equip:
            d = p["data"]
            equip[n] = {"normal": n, "tag": d["tag"], "class": d["class"], "family": d["family"],
                        "terminal": d["rel"] == "serves", "attrs": {}, "status": "proposed", "conf": 0.7,
                        "fact": p["id"], "schedule": "", "plan_only": True}
    for c in ctrls:  # controllers answered as units of their own
        if c["data"].get("equip") == "__new__":
            dev = c["data"]["device"]
            equip[dev] = {"normal": dev, "tag": dev, "class": "Equipment", "family": "other", "terminal": False,
                          "attrs": {}, "status": c["status"], "conf": c["conf"], "fact": c["id"], "schedule": ""}
            c["data"]["equip"] = dev

    for n, e in equip.items():
        p, c = place.get(n), check.get(n)
        e["floor"] = p["data"]["floor"] if p else (c["data"]["floor"] if c else None)
        e["xy"] = p["data"].get("unit_xy") if p else None
        e["at_xy"] = p["data"].get("at_xy") if p else None
        e["also_on"] = p["data"].get("also_on", []) if p else []
        if c:
            e["room"], e["room_status"], e["room_fact"] = c["data"]["room"], c["status"], c["id"]
            e["room_source"] = ("you" if c["method"] == "human" else
                                "plan + submittal agree" if c["data"].get("agree") else "submittal")
        elif p:
            e["room"], e["room_status"], e["room_fact"] = p["data"].get("room"), p["status"], p["id"]
            e["room_source"] = "you" if p["method"] == "human" else f"plan ({p['data']['by']})"
        else:
            e["room"], e["room_status"], e["room_fact"], e["room_source"] = None, None, None, None
        e["rel"] = "serves" if e["terminal"] else "located in"
        e["points"] = 0
        e["controller"] = None
        e["bms"] = None
        e["sequence"] = None

    by_device = {}
    for c in ctrls:
        n = c["data"].get("equip")
        if n in equip:
            equip[n]["controller"] = {k: c["data"][k] for k in ("device", "controller", "trunk", "address")}
            by_device[c["data"]["device"]] = n
    for p in points:
        n = by_device.get(p["data"]["device"])
        if n:
            equip[n]["points"] += 1
    for a in aliases:
        n = a["data"].get("equip")
        if n in equip:
            equip[n]["bms"] = a["data"]["device"]
    for s in seqs:
        for tag in s["data"]["applies_to"]:
            for e in equip.values():
                if e["tag"] == tag:
                    e["sequence"] = s["data"]["title"]

    served = Counter(e["room"] for e in equip.values() if e["terminal"] and e["room"])
    room_list = []
    for num, r in rooms.items():
        room_list.append({"number": num, "name": r["data"]["name"], "floor": r["data"]["floor"],
                          "anchor": r["data"]["anchor"], "status": r["status"], "fact": r["id"],
                          "units": [e["tag"] for e in equip.values() if e["room"] == num]})
    rels = live("relation")
    return {"floors": [{"id": f["data"]["floor"], "name": f["data"]["name"], "crop": f["data"]["crop"],
                        "file": f["src"]["file"], "page": f["src"]["page"], "sheet": f["src"].get("sheet"),
                        "status": f["status"]} for f in floors],
            "rooms": sorted(room_list, key=lambda r: r["number"]), "equip": equip, "relations": rels,
            "sequences": seqs, "points": points, "served": served,
            "issues": [i for i in live("issue")]}


def _floor_order(f: str) -> int:
    return {"B1": 0, "RF": 99}.get(f, int(f[1:]) if f[1:].isdigit() else 50)


def missing(it: Intake, b: dict) -> list[tuple[str, str, str]]:
    """(step, severity, text): what is not there yet. severity: todo (a document to upload), ask (questions),
    gap (something the documents do not say)."""
    out = []
    eq = b["equip"]
    for s in STEPS[:-1]:
        if not it.files(s.id):
            out.append((s.id, "todo", f"{s.ask}: {s.builds[0].lower() + s.builds[1:]}"))
        elif (q := len(it.open_questions(s.id))):
            out.append((s.id, "ask", f"{q} question{'s' if q > 1 else ''} to answer on {s.title.lower()}"))
    if it.done("plans"):
        no_room = [e["tag"] for e in eq.values() if e["terminal"] and not e["room"]]
        if no_room:
            out.append(("plans", "gap", f"{len(no_room)} terminal units serve no room yet ({', '.join(no_room[:5])})"))
        likely = [e for e in eq.values() if e["room"] and e["room_status"] == "proposed"]
        if likely:
            out.append(("plans", "gap", f"{len(likely)} rooms come from the plan alone and wait for a second source "
                                        "(the submittal's room schedule) or for you"))
    if it.done("schedules"):
        plan_only = [e["tag"] for e in eq.values() if not e["schedule"] and e["family"] not in ("other",)]
        if plan_only:
            out.append(("schedules", "gap", f"{len(plan_only)} units have no schedule row: no make, model or "
                                            f"capacity ({', '.join(plan_only[:6])})"))
    if it.done("sequences"):
        fams = {e["family"] for e in eq.values() if e["sequence"]}
        none = sorted({e["family"] for e in eq.values() if not e["sequence"] and e["family"] not in fams
                       and e["family"] not in ("specialty", "uh", "other")})
        if none:
            out.append(("sequences", "gap", f"No sequence for: {', '.join(f.upper() for f in none)}"))
    if it.done("submittal"):
        no_ctrl = [e["tag"] for e in eq.values() if not e["controller"] and e["family"] not in ("specialty", "uh")]
        if no_ctrl:
            out.append(("submittal", "gap", f"{len(no_ctrl)} units have no controller in the submittal "
                                            f"({', '.join(no_ctrl[:6])})"))
    if it.done("bms"):
        no_bms = [e["tag"] for e in eq.values() if e["controller"] and not e["bms"]]
        if no_bms:
            out.append(("bms", "gap", f"{len(no_bms)} controlled units are not in the BMS export ({', '.join(no_bms[:6])})"))
    return out


def progress(it: Intake) -> dict:
    """Per step: uploaded, read, questions open/answered; overall share done."""
    per, total = {}, 0.0
    for s in STEPS[:-1]:
        facts = it.facts(s.id)
        asked = [f for f in facts if f.get("ask")]
        answered = sum(1 for f in asked if f["method"] == "human")
        share = (0.6 + 0.4 * (answered / len(asked) if asked else 1)) if it.done(s.id) else 0
        per[s.id] = {"uploaded": bool(it.files(s.id)), "read": it.done(s.id), "asked": len(asked),
                     "answered": answered, "open": len(asked) - answered, "facts": len(facts), "share": share}
        total += share
    return {"steps": per, "share": total / (len(STEPS) - 1)}
