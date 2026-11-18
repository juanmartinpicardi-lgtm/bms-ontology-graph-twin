"""Agent tour: a guided simulation of an agent answering "Zone 1-2-81 is too warm. What's wrong?" by walking the
knowledge graph instead of the drawings (app/agent_tour.html).

Everything the agent touches is read from the graph here: the zone's VAV, the AHU that feeds it, the plants that feed
the AHU, the plant's chillers, every point with its class and provenance, and the neighbours it checks on the way
(the AHU's other VAVs, the plant's other AHUs). Only the script of the walk is fixed. Values come from the
"Chilled water running warm" scenario of the equipment simulator (equipment3d/sim.js), the same one the Equipment 3D
page runs, so the numbers in the tour and in the 3D viewer agree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

from .db.store import Store
from .fonts import with_fonts
from .equipment_view import DATA_SLOT, equipment_payload, load_anchors, render_template
from .knowledge_model import KnowledgeModel
from .tree import build_tree, provenance

PROJECT = "alpha/names_paths"
ZONE = "eq:Airside AHU-2/VAV 1-2-81"
APP = Path(__file__).resolve().parent / "app"
# A fixed stretch of the scenario, replayed in a loop: an hour in, the fault is fully developed, and the 150 s loop
# (14:30 to 17:00 simulated) ends before the building goes unoccupied.
SIM = {"scenario": "chw_warm", "offset": 60, "span": 150}
# The points the agent reads, by template slot role (knowledge_model/templates), in the order it reads them.
ROLES = {"vav": ["zone_temp", "occ_cooling_sp", "damper", "airflow", "airflow_sp"],
         "ahu": ["supply_temp", "supply_temp_sp", "cooling_valve", "supply_fan_speed"],
         "chiller": ["chw_leaving_temp", "chw_leaving_sp", "status", "chw_flow", "chw_entering_temp"]}


def _natural(label: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", label)]


def equipment_link(equip: str, project: str = PROJECT) -> str:
    return "/Equipment_3D?" + urlencode({"project": project, "equip": equip, "scenario": SIM["scenario"]})


def tour_payload(store: Store, km: KnowledgeModel, project: str = PROJECT, zone: str = ZONE,
                 anchors: dict | None = None) -> dict:
    """The walk from the zone's VAV up to the lead chiller of the plant that feeds its AHU, read from the graph."""
    anchors = load_anchors() if anchors is None else anchors
    tree = build_tree(store, project)
    by = tree.by_id
    tpl = lambda i: by[i].attrs.get("template")  # noqa: E731
    if zone not in by:
        raise KeyError(f"{zone} is not in {project}")

    ahu = next(s for s, _ in tree.fed_by(zone) if tpl(s) == "ahu")
    feeders = [s for s, _ in tree.fed_by(ahu)]
    parts = lambda i: [c.id for c in by[i].children]  # noqa: E731
    plant = next(p for p in feeders if any(tpl(c) == "chiller" for c in parts(p)))
    others = [p for p in feeders if p != plant]  # the hot water plant: fed in, pruned by the agent
    chillers = sorted((c for c in parts(plant) if tpl(c) == "chiller"), key=lambda c: _natural(by[c].label))
    chiller = chillers[0]  # the lead unit
    vavs = lambda a: sorted((c.id for c in by[a].children if c.attrs.get("template") == "vav"),  # noqa: E731
                            key=lambda c: _natural(by[c].label))
    ahus = sorted((d for d, _ in tree.feeds_to(plant) if tpl(d) == "ahu"), key=lambda a: _natural(by[a].label))

    def node(i: str) -> dict:
        n = by[i]
        return {"id": i, "label": n.label, "cls": n.cls, "template": n.attrs.get("template"),
                "points": len(n.points), "prov": n.prov}

    def edge(src: str, dst: str, rel: str) -> dict | None:
        for e in store.edges(project, rel):
            if e["src"] == src and e["dst"] == dst and e["status"] != "rejected":
                return provenance(e)
        return None

    equipment, roles = {}, {}
    for key, eid in (("zone", zone), ("ahu", ahu), ("chiller", chiller)):
        p = equipment_payload(store, project, eid, km, anchors)
        p |= {"sim": SIM, "embed": True}
        equipment[key] = p
        t = p["equipment"]["template"]
        # A slot can hold several points ("SAT" and a misread "Enthalpy"); the agent trusts the most confident one.
        roles[key] = {r: max((i for i, pt in p["points"].items() if pt["role"] == r),
                             key=lambda i: p["points"][i]["confidence"] or 0, default=None) for r in ROLES[t]}

    counts = {"points": len(store.nodes(project, "point")), "equipment": len(store.nodes(project, "equipment"))}
    return {
        "project": project,
        "counts": counts,
        "path": {"zone": zone, "ahu": ahu, "plant": plant, "others": others, "chiller": chiller},
        "nodes": {i: node(i) for i in {zone, ahu, plant, chiller, *others, *ahus, *parts(plant), *vavs(ahu)}
                  | {v for a in ahus for v in vavs(a)}},
        "vavs": {a: vavs(a) for a in ahus},
        "ahus": ahus,
        "chillers": chillers,
        "plant_parts": sorted(parts(plant), key=lambda c: _natural(by[c].label)),
        "edges": {"zone_ahu": edge(ahu, zone, "feeds"), "ahu_plant": edge(plant, ahu, "feeds"),
                  "plant_chiller": edge(plant, chiller, "hasPart")},
        "roles": roles,
        "equipment": equipment,
        "links": {k: equipment_link(i, project) for k, i in (("zone", zone), ("ahu", ahu), ("chiller", chiller))},
    }


def render_html(payload: dict, theme: str | None = None) -> str:
    """The tour page with its payload and the 3D viewer's page (once; the tour fills in each equipment) inlined."""
    data = dict(payload, viewer=render_template(theme), slot=DATA_SLOT)
    html = (APP / "agent_tour.html").read_text()
    # Sim is shared with the 3D viewer so both compute the same values.
    html = html.replace("/*__SIM__*/", (APP / "equipment3d" / "sim.js").read_text())
    html = html.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    if theme in ("light", "dark"):
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return with_fonts(html)
