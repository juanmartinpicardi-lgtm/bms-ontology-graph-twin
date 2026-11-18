"""More agent tours (app/use_cases.html), each read from Alpha's knowledge graph like the root-cause tour:

    test     "Run the functional test on VAV 1-2-81": the box, its template, its sequence -> a test script, run against
             the equipment simulator in the 3D viewer.
    impact   "I need AHU-2 off for two hours": downstream through the feeds links to every zone it serves, shown in
             the digital twin; upstream and sibling checks; the schedule picks the window.
    tribal   A technician's voice note and photo at AHU-2 become a note on the graph, linked to the equipment and the
             point it is about, after the technician confirms it.

Equipment, points, classes, template slots, links, floors and the sequence come from the graph and the project's
documents. The agents' scripts are fixed, values are simulated, and the technician's note is an example.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .agent_tour import PROJECT, ZONE, _natural
from .db.store import Store
from .fonts import with_fonts
from .equipment_view import DATA_SLOT, equipment_payload, load_anchors, render_template
from .knowledge_model import KnowledgeModel
from .tree import build_tree
from .twin_view import render_html as twin_html
from .twin_view import twin_payload

ROOT = Path(__file__).resolve().parents[2]
APP = Path(__file__).resolve().parent / "app"


def _points(eq: dict) -> list[dict]:
    return sorted(({"id": i, "label": p["label"], "role": p["role"], "cls": p.get("cls") or p.get("class"),
                    "conf": p.get("confidence")} for i, p in eq["points"].items()), key=lambda p: _natural(p["label"]))


def _template(name: str) -> dict:
    t = yaml.safe_load((ROOT / "knowledge_model/templates" / f"{name}.yaml").read_text())
    return {"required": [s["role"] for s in t.get("points", []) if s.get("required")],
            "roles": [s["role"] for s in t.get("points", [])]}


def _sequence(seq_id: str) -> dict:
    doc = yaml.safe_load((ROOT / "data/documents/alpha/sequences.yaml").read_text())
    s = next(x for x in doc["sequences"] if x["id"] == seq_id)
    role = lambda ref: ref.split(".", 1)[1] if "." in ref else ref  # noqa: E731
    return {"title": s["title"], "document": doc["document"],
            "loops": [{"name": lp["name"], "setpoint": role(lp["setpoint"]), "measured": role(lp["measured"]),
                       "outputs": [role(o) for o in lp["outputs"]]} for lp in s.get("loops", [])]}


def cases_payload(store: Store, km: KnowledgeModel, project: str = PROJECT, theme: str | None = None,
                  anchors: dict | None = None) -> dict:
    anchors = load_anchors() if anchors is None else anchors
    tree = build_tree(store, project)
    by = tree.by_id
    tpl = lambda i: by[i].attrs.get("template")  # noqa: E731
    label = lambda i: re.sub(r"^(Airside|Waterside)\s+", "", by[i].label)  # noqa: E731
    ahu = next(s for s, _ in tree.fed_by(ZONE) if tpl(s) == "ahu")
    vavs = sorted((c.id for c in by[ahu].children if c.attrs.get("template") == "vav"),
                  key=lambda c: _natural(by[c].label))
    upstream = [s for s, _ in tree.fed_by(ahu)]
    chw = next(p for p in upstream if any(tpl(c.id) == "chiller" for c in by[p].children))
    peers = sorted((d for d, _ in tree.feeds_to(chw) if tpl(d) == "ahu" and d != ahu),
                   key=lambda a: _natural(by[a].label))

    vav_eq = equipment_payload(store, project, ZONE, km, anchors) | {
        "sim": {"scenario": "hot", "offset": 40, "span": 150}, "embed": True}
    ahu_eq = equipment_payload(store, project, ahu, km, anchors)
    twin = twin_payload(store, project, "Alpha")
    floor_of = {e["id"]: e["floor"] for e in twin["equip"]}
    zone_floors = sorted({floor_of.get(v) for v in vavs if floor_of.get(v)})

    return {
        "project": project,
        "counts": {"points": len(store.nodes(project, "point")), "equipment": len(store.nodes(project, "equipment"))},
        "ahu": {"id": ahu, "label": label(ahu), "cls": by[ahu].cls, "points": _points(ahu_eq),
                "floor": floor_of.get(ahu)},
        "vavs": [{"id": v, "label": label(v), "floor": floor_of.get(v)} for v in vavs],
        "zone_floors": zone_floors,
        "upstream": [{"id": u, "label": label(u), "cls": by[u].cls} for u in upstream],
        "peers": [{"id": a, "label": label(a),
                   "vavs": sum(1 for c in by[a].children if c.attrs.get("template") == "vav")} for a in peers],
        "chw": chw,
        "test": {"vav": {"id": ZONE, "label": label(ZONE), "cls": by[ZONE].cls, "variant": vav_eq["variant"],
                         "points": _points(vav_eq)},
                 "template": _template("vav"), "sequence": _sequence("vav"), "equipment": vav_eq},
        "viewer": render_template(theme), "slot": DATA_SLOT,
        "twin": twin_html(twin, theme),
    }


def render_html(payload: dict, case: str, theme: str | None = None) -> str:
    html = (APP / "use_cases.html").read_text()
    html = html.replace("/*__SIM__*/", (APP / "equipment3d" / "sim.js").read_text())
    data = dict(payload, case=case)
    html = html.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    if theme in ("light", "dark"):
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return with_fonts(html)
