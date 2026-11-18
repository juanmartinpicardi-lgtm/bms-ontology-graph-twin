"""Data for the digital twin page: one project's knowledge graph laid out as a building.

    equipment + points + feeds / hasPart (the store, rejected items left out)
        -> a type per equipment (from its class and template) -> a floor per equipment (inferred, see `floors`)

What is real and what is not, as the page's notes say: equipment, points, classes, relations and their provenance
come from the knowledge graph; floors are inferred from the airside (zones sit on their AHU's floor); rooms, geometry
and every value are generated in the browser.
"""

from __future__ import annotations

import json
import re
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
         "Return_Fan": "Fan VFD"}  # class -> the 3D model drawn for it; meters, systems and the rest below
PREFIX = re.compile(r"^(Airside|Waterside|Utility Bills) ")


def natural(label: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", label)]


TEMPLATE_TYPES = {"ahu": "AHU", "chiller": "Chiller", "boiler": "Boiler", "pump": "Pump"}


def kind_of(cls: str | None, template: str | None, name: str) -> str:
    if template == "vav":
        return "VAV (dual duct)" if name.startswith("DD ") else "VAV"
    if template in TEMPLATE_TYPES:
        return TEMPLATE_TYPES[template]
    cls = cls or ""
    return TYPES.get(cls) or ("Meter" if cls.endswith("_Meter") else "System")


def system_of(kind: str, cls: str | None) -> str:
    if kind == "Meter":
        return "Metering"
    return "Airside" if kind in ("AHU", "VAV", "VAV (dual duct)", "Exhaust fan", "Fan VFD") else "Waterside"


def twin_payload(store: Store, project: str, site: str) -> dict:
    """The page's data: equipment with its points, feeds and hasPart, and a floor per equipment."""
    nodes = {r["id"]: r for r in store.nodes(project) if r["status"] != "rejected"}
    live = [e for e in store.edges(project) if e["status"] != "rejected" and e["src"] in nodes and e["dst"] in nodes]
    points: dict[str, list] = {}
    parent: dict[str, str] = {}
    for e in live:
        if e["rel"] == "hasPoint":
            p = nodes[e["dst"]]
            spec = describe(p["class"], None)  # units are inferred from the class: blind exports carry none
            points.setdefault(e["src"], []).append({
                "n": p["label"], "c": p["class"] or "", "u": spec["unit"] or "",
                "k": "Bool" if spec["kind"] == "binary" else "Number", "s": p["status"], "m": p["method"],
                "conf": round(p["confidence"], 2)})
        elif e["rel"] == "hasPart":
            parent[e["dst"]] = e["src"]

    equip = []
    for i, n in nodes.items():
        if n["kind"] != "equipment":
            continue
        attrs = json.loads(n["attrs"])
        name = PREFIX.sub("", n["label"])
        kind = kind_of(n["class"], attrs.get("template"), name)
        equip.append({"id": i, "name": name, "cls": n["class"] or "Unclassified", "status": n["status"],
                      "method": n["method"], "conf": round(n["confidence"], 2), "parent": parent.get(i),
                      "sys": system_of(kind, n["class"]), "type": kind, "file": Path(n["source_file"]).name,
                      "row": n["source_ref"], "points": points.get(i, []),
                      **({"floor_hint": attrs["floor"]} if attrs.get("floor") else {})})
    equip.sort(key=lambda e: natural(e["name"]))
    feeds = [{"s": e["src"], "r": "feeds", "d": e["dst"], "via": json.loads(e["attrs"]).get("medium") or e["method"]}
             for e in live if e["rel"] == "feeds"]
    ahus = floors(equip, feeds)
    return {"site": {"name": site, "project": project}, "equip": equip, "rels": feeds,
            "floors": {f: ahus.get(f, "") for f in ZONE_FLOORS}}


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
        hint = e.pop("floor_hint", None)  # read from the floor plans (guided setup): the real floor wins
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
