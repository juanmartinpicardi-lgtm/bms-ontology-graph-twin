"""Data for the digital twin page: one project's knowledge graph laid out as a building.

    equipment + points + feeds / hasPart (the store, rejected items left out)
        -> a type per equipment (from its family, class or template)
        -> the building's levels and rooms (the graph's Floor / Room nodes when it has them)
        -> a level per equipment, and the room it is in or serves

Two kinds of project, one page:
- with floors and rooms in the graph (a building added from its documents): the levels, rooms, room names and the
  room of every unit are real; where each room sits follows its number on the plan; room sizes, walls and geometry
  are generated.
- without (Haystack sites like Alpha): floors are inferred from the airside (zones sit on their AHU's floor), and
  rooms, geometry and every value are generated in the browser.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from .db.store import Store
from .fonts import with_fonts
from .value_model import describe

APP = Path(__file__).resolve().parent / "app"
# Inlined in this order; each may import only the ones before it (the page rewrites "./x.js" to the inlined module).
MODULES = ("data.js", "materials.js", "models.js", "building.js", "site.js", "plan.js", "viewer.js", "main.js")
ZONE_FLOORS = ("L1", "L2", "L3", "L4")  # the generated building has four office floors
ROOF = ("AHU", "Exhaust fan", "Cooling tower", "Fan VFD")
TYPES = {"AHU": "AHU", "Chiller": "Chiller", "Boiler": "Boiler", "Pump": "Pump", "Heat_Exchanger": "Heat exchanger",
         "Cooling_Tower": "Cooling tower", "Exhaust_Fan": "Exhaust fan", "Supply_Fan": "Fan VFD",
         "Return_Fan": "Fan VFD", "Unit_Heater": "Unit heater", "FCU": "Fan coil",
         "Chilled_Water_Pump": "Pump", "Hot_Water_Pump": "Pump", "Condenser_Water_Pump": "Pump",
         "Chilled_Water_Thermal_Expansion_Tank": "Hydronic specialty"}  # class -> the 3D model drawn for it
# A unit's family, as the guided setup reads it from the tag (intake/tags.py), says the most about what it is.
FAMILY_TYPES = {"vav": "VAV", "fvav": "VAV (fan powered)", "fcu": "Fan coil", "uh": "Unit heater",
                "split": "Mini-split", "specialty": "Hydronic specialty", "ef": "Exhaust fan", "ahu": "AHU",
                "chiller": "Chiller", "pump": "Pump", "boiler": "Boiler"}
AIRSIDE = ("AHU", "VAV", "VAV (dual duct)", "VAV (fan powered)", "Exhaust fan", "Fan VFD", "Fan coil", "Mini-split")
PREFIX = re.compile(r"^(Airside|Waterside|Utility Bills) ")


def natural(label: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", label)]


TEMPLATE_TYPES = {"ahu": "AHU", "chiller": "Chiller", "boiler": "Boiler", "pump": "Pump", "fcu": "Fan coil"}


def kind_of(cls: str | None, template: str | None, name: str, family: str | None = None) -> str:
    if family in FAMILY_TYPES:
        return FAMILY_TYPES[family]
    if template == "vav":
        return "VAV (dual duct)" if name.startswith("DD ") else "VAV"
    if template in TEMPLATE_TYPES:
        return TEMPLATE_TYPES[template]
    cls = cls or ""
    return TYPES.get(cls) or ("Meter" if cls.endswith("_Meter") else "System")


def system_of(kind: str, cls: str | None) -> str:
    if kind == "Meter":
        return "Metering"
    return "Airside" if kind in AIRSIDE else "Waterside"


def twin_payload(store: Store, project: str, site: str) -> dict:
    """The page's data: equipment with its points, feeds and hasPart, the levels (bottom to top) and, when the graph
    has them, the rooms of each level; a level per equipment, and its room."""
    nodes = {r["id"]: r for r in store.nodes(project) if r["status"] != "rejected"}
    live = [e for e in store.edges(project) if e["status"] != "rejected" and e["src"] in nodes and e["dst"] in nodes]
    points: dict[str, list] = {}
    parent: dict[str, str] = {}
    where: dict[str, tuple[str, str]] = {}  # unit -> (rel, location node)
    for e in live:
        if e["rel"] == "hasPoint":
            p = nodes[e["dst"]]
            spec = describe(p["class"], None)  # units are inferred from the class: blind exports carry none
            points.setdefault(e["src"], []).append({
                "n": p["label"], "c": p["class"] or "", "u": spec["unit"] or "",
                "k": "Bool" if spec["kind"] == "binary" else "Number", "s": p["status"], "m": p["method"],
                "conf": round(p["confidence"], 2)})
        elif e["rel"] == "hasPart" and nodes[e["dst"]]["kind"] == "equipment":
            parent[e["dst"]] = e["src"]
        elif e["rel"] in ("serves", "hasLocation") and nodes[e["dst"]]["kind"] == "location":
            if e["src"] not in where or nodes[e["dst"]]["class"] == "Room":  # a room says more than a floor
                where[e["src"]] = (e["rel"], e["dst"])
    levels, rooms, aspect = spaces(nodes)

    equip = []
    for i, n in nodes.items():
        if n["kind"] != "equipment":
            continue
        attrs = json.loads(n["attrs"])
        name = PREFIX.sub("", n["label"])
        kind = kind_of(n["class"], attrs.get("template"), name, attrs.get("family"))
        e = {"id": i, "name": name, "cls": n["class"] or "Unclassified", "status": n["status"],
             "method": n["method"], "conf": round(n["confidence"], 2), "parent": parent.get(i),
             "sys": system_of(kind, n["class"]), "type": kind, "file": Path(n["source_file"]).name,
             "row": n["source_ref"], "points": points.get(i, []),
             **({"floor_hint": attrs["floor"]} if attrs.get("floor") else {})}
        rel, loc = where.get(i, (None, None))
        if loc and nodes[loc]["class"] == "Room":
            room = json.loads(nodes[loc]["attrs"])
            e.update(room=loc, room_name=nodes[loc]["label"], room_rel=rel, floor_hint=room.get("floor"))
        elif loc:
            e["floor_hint"] = json.loads(nodes[loc]["attrs"]).get("level") or e.get("floor_hint")
        if levels:
            e["label"] = name  # a tag from the documents (VAV01), not a Haystack zone name
        equip.append(e)
    equip.sort(key=lambda e: natural(e["name"]))
    feeds = [{"s": e["src"], "r": "feeds", "d": e["dst"], "via": json.loads(e["attrs"]).get("medium") or e["method"]}
             for e in live if e["rel"] == "feeds" and nodes[e["src"]]["kind"] == nodes[e["dst"]]["kind"] == "equipment"]
    if levels:
        levels = place(equip, levels)
        return {"site": {"name": site, "project": project}, "equip": equip, "rels": feeds, "levels": levels,
                "rooms": rooms, "aspect": aspect, "source": "graph"}
    ahus = floors(equip, feeds)
    levels = ([{"id": "B1", "name": "Basement", "long": "Basement plant", "kind": "plant"}]
              + [{"id": f, "name": f"Level {f[1]}", "kind": "zones",
                  "long": f"Level {f[1]}" + (f" · {ahus[f]} zones" if ahus.get(f) else "")} for f in ZONE_FLOORS]
              + [{"id": "RF", "name": "Roof", "long": "Roof & penthouse", "kind": "roof"}])
    return {"site": {"name": site, "project": project}, "equip": equip, "rels": feeds, "levels": levels,
            "source": "inferred"}


def spaces(nodes: dict) -> tuple[list[dict], dict[str, list[dict]], float | None]:
    """The graph's floors (bottom to top), the rooms on each with where the plan puts them, and the plans' shape
    (depth / width). Nothing when the graph has no floors."""
    floor_rows = [n for n in nodes.values() if n["kind"] == "location" and n["class"] == "Floor"]
    if not floor_rows:
        return [], {}, None
    fl = [(json.loads(n["attrs"]), n) for n in floor_rows]
    fl.sort(key=lambda a: (a[0].get("order", 99), natural(a[0].get("level") or a[1]["id"])))
    levels = []
    for a, n in fl:
        fid = a.get("level") or n["id"].split(":", 1)[-1]
        roof = fid == "RF" or "roof" in n["label"].lower()
        levels.append({"id": fid, "name": n["label"], "long": n["label"], "kind": "roof" if roof else "zones",
                       "sheet": a.get("sheet") or n["source_ref"], "aspect": a.get("aspect")})
    levels.sort(key=lambda lv: (lv["kind"] == "roof", not lv["id"].startswith("B")))  # basements, levels, roof
    rooms: dict[str, list[dict]] = {}
    for n in nodes.values():
        if n["kind"] == "location" and n["class"] == "Room":
            a = json.loads(n["attrs"])
            rooms.setdefault(a.get("floor"), []).append(
                {"id": n["id"], "num": a.get("number", ""), "name": a.get("name", ""), "label": n["label"],
                 "xy": a.get("xy"), "status": n["status"], "file": Path(n["source_file"]).name, "ref": n["source_ref"]})
    for rs in rooms.values():
        rs.sort(key=lambda r: natural(r["num"] or r["id"]))
    shapes = [lv["aspect"] for lv in levels if lv["kind"] != "roof" and lv.get("aspect")]
    return levels, rooms, (round(statistics.median(shapes), 4) if shapes else None)


def place(equip: list[dict], levels: list[dict]) -> list[dict]:
    """A level per equipment when the graph has its own floors: the floor the documents give, else the roof for
    roof-type equipment, else the lowest occupied level. A building without a roof plan still gets its roof."""
    ids = {lv["id"] for lv in levels}
    roof = next((lv["id"] for lv in levels if lv["kind"] == "roof"), None)
    ground = next((lv["id"] for lv in levels if lv["kind"] != "roof" and not lv["id"].startswith("B")),
                  levels[0]["id"])
    for e in equip:
        hint = e.pop("floor_hint", None)
        e["floor_src"] = "plans" if hint in ids else "inferred"
        if hint in ids:
            e["floor"] = hint
        elif e["type"] in ROOF:
            e["floor"] = roof or "RF"
        else:
            e["floor"] = ground
    if not roof:
        levels = [*levels, {"id": "RF", "name": "Roof", "long": "Roof", "kind": "roof"}]
    return levels


def floors(equip: list[dict], feeds: list[dict]) -> dict[str, str]:
    """Sets each equipment's floor; returns floor -> the AHU whose zones are on it. Haystack sites carry no floor
    tags, so: AHUs in name order take L1..L4 and their zones follow them; AHUs, fans and towers sit on the roof;
    the rest is basement plant. A fifth AHU's zones share L4."""
    by_id = {e["id"]: e for e in equip}
    ahus = sorted((e for e in equip if e["type"] == "AHU"), key=lambda e: natural(e["name"]))
    floor_of_ahu = {a["id"]: ZONE_FLOORS[min(k, len(ZONE_FLOORS) - 1)] for k, a in enumerate(ahus)}
    served = {f["d"]: f["s"] for f in feeds if f["s"] in floor_of_ahu}
    known = set(ZONE_FLOORS) | {"B1", "RF"}
    for e in equip:
        hint = e.pop("floor_hint", None)
        e["floor_src"] = "inferred"
        if hint:
            e["floor"] = hint if hint in known else (f"L{min(4, int(hint[1:]))}" if hint[1:].isdigit() else "B1")
        elif e["type"].startswith("VAV"):
            ahu = served.get(e["id"]) or (e["parent"] if e["parent"] in floor_of_ahu else None)
            e["floor"] = floor_of_ahu.get(ahu, ZONE_FLOORS[0])
        elif e["type"] in ROOF or "Penthouse" in e["name"]:
            e["floor"] = "RF"
        else:
            e["floor"] = "B1"
    out: dict[str, str] = {}
    for a in ahus:
        out.setdefault(floor_of_ahu[a["id"]], by_id[a["id"]]["name"])
    return out


def render_html(payload: dict, theme: str | None = None) -> str:
    """The twin page with the payload and its JS modules inlined, so it runs in Streamlit's iframe (three.js comes
    from the CDN). The modules travel as text and become blob-URL modules in the page, each keeping its own scope.
    `theme` ("light" / "dark") pins the colours to the host app's theme; without it the page follows the system."""
    modules = {m: (APP / "digital_twin" / m).read_text() for m in MODULES}
    safe = lambda obj: json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")  # noqa: E731
    boot = f"""<script>window.TWIN = {safe(payload)};</script>
<script type="application/json" id="twin-modules">{safe(modules)}</script>
<script type="module">
const src = JSON.parse(document.getElementById("twin-modules").textContent), urls = {{}};
for (const name of {json.dumps(list(MODULES))}) {{
  const code = src[name].replace(/from "\\.\\/([\\w-]+\\.js)"/g, (_, dep) => `from "${{urls[dep]}}"`);
  urls[name] = URL.createObjectURL(new Blob([code], {{ type: "text/javascript" }}));
}}
import(urls["main.js"]).catch(err => {{ document.getElementById("loading").textContent = "The twin failed to start: " + err.message; }});
</script>"""
    html = (APP / "digital_twin.html").read_text().replace("<!--__TWIN__-->", boot)
    if theme in ("light", "dark"):
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return with_fonts(html)
