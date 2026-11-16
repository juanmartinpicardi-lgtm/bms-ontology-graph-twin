"""The building as it is being built, in 3D: each floor plan page becomes a floor plate, stacked in its level order,
with the rooms read from it and every unit placed where the documents put it. Colour says what kind of unit; the
ring says how sure: green confirmed, blue proposed, amber and pulsing waiting for you.

The floors are drawn from the PDF's own line work (intake/vectors.py), not from a picture of the page, so they stay
sharp at any zoom. The viewer (app/intake_twin.html, three.js) switches between the 3D stack and a 2D plan of one
floor; a click on a unit or room is sent back to the app, which opens its place in the document.
"""
from __future__ import annotations

from pathlib import Path

FAMILY_COLOR = {"ahu": "#E8833A", "vav": "#4DA3E8", "fvav": "#8E7CF0", "fcu": "#4DA3E8", "chiller": "#2BB3A3",
                "pump": "#3C8DBC", "ef": "#A0A6AD", "split": "#D96BA6", "uh": "#E0B33A", "specialty": "#8A8F96",
                "boiler": "#D9534F", "other": "#8A8F96"}
FAMILY_NAME = {"ahu": "Air handler", "vav": "VAV box", "fvav": "Fan-powered box", "chiller": "Chiller", "pump": "Pump",
               "ef": "Exhaust fan", "split": "Mini-split", "uh": "Unit heater", "specialty": "Hydronic specialty",
               "fcu": "Fan coil", "boiler": "Boiler", "other": "Other"}


TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "intake_twin.html"


def payload(b: dict, plans: dict[str, dict], selected: str | None, needs_you: set[str], theme: str = "dark") -> dict:
    """What the viewer draws. `plans` is vectors.plan() per floor id, each with a `key` that changes with the file."""
    floors = []
    anchors = {r["number"]: (r["floor"], r["anchor"]) for r in b["rooms"]}
    placed = set()
    for f in b["floors"]:
        crop = f["crop"]
        if not crop or f["id"] not in plans:
            continue
        w, h = crop[2] - crop[0], crop[3] - crop[1]
        norm = lambda xy: [round((xy[0] - crop[0]) / w, 4), round((xy[1] - crop[1]) / h, 4)]  # noqa: E731
        rooms = [{"n": r["number"], "name": r["name"], "xy": norm(r["anchor"]),
                  "s": "ask" if r["fact"] in needs_you else r["status"], "units": r["units"], "id": r["fact"]}
                 for r in b["rooms"] if r["floor"] == f["id"]]
        units = []
        for e in b["equip"].values():
            xy = e["xy"] if e["floor"] == f["id"] else None
            if not xy and e["room"] in anchors and anchors[e["room"]][0] == f["id"] and (e["floor"] in (None, f["id"])):
                xy = anchors[e["room"]][1]  # no label on a plan: stand it at its room's number
            if not xy or e["normal"] in placed:
                continue
            placed.add(e["normal"])
            ask = [i for i in e["facts"] if i in needs_you]
            units.append({"tag": e["tag"], "fam": e["family"], "cls": e["class"], "xy": norm(xy),
                          "s": "ask" if ask else e["status"] if e["room_status"] in (None, "confirmed") else "proposed",
                          "room": e["room"], "rs": e.get("room_source"), "rel": e["rel"], "pts": e["points"],
                          "ctrl": (e["controller"] or {}).get("device"), "seq": e["sequence"], "bms": e["bms"],
                          "id": (ask or e["facts"])[0], "ids": e["facts"]})
        floors.append({"id": f["id"], "name": f["name"], "sheet": f["sheet"], "geo": plans[f["id"]],
                       "aspect": round(h / w, 4), "rooms": rooms, "units": units})
    legend = sorted({u["fam"] for f in floors for u in f["units"]})
    return {"floors": floors, "selected": selected, "theme": theme, "unplaced": len(b["equip"]) - len(placed),
            "legend": [{"fam": k, "name": FAMILY_NAME.get(k, k), "color": FAMILY_COLOR.get(k, "#888")} for k in legend],
            "colors": FAMILY_COLOR}


def page() -> str:
    """The viewer page. It holds no data: the app posts the payload to it (app/bridge.py)."""
    controls = (TEMPLATE.parent / "viewer_controls.js").read_text()
    return TEMPLATE.read_text().replace("/*__CONTROLS__*/", controls)
