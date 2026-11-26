"""Graphics creation (W9, plan §5.4): 2D equipment, floor and system graphics generated from the knowledge graph and
the equipment templates, point binding through template slots to anchors, and QA (rules, then an optional vision
check). The 3D builders live in app/equipment3d/; both read the same payload and the same anchors.
"""


def graphic_ref(store, project: str, equip_id: str, km) -> dict | None:
    """The agent's `show_graphic` (agent_tools.GRAPHIC_PROVIDERS): where the unit's graphic is and how it binds.
    A unit with a template opens on Equipments (its 3D model, or the 2D graphic with the QA result, one at a time); a
    system with its own points (the CHW plant) on the Graphics page, whose system graphic shows them. None when
    neither applies, so the caller falls back."""
    from ..equipment_view import equipment_payload, load_anchors, node_template
    from ..tree import build_tree
    from .equipment2d import render
    from .layouts import LAYOUTS
    from .qa import check_equipment

    tree = build_tree(store, project)
    n = tree.by_id.get(equip_id)
    if n is None:
        return None
    t = node_template(n, km)
    anchors = load_anchors()
    if t is None or t.id not in anchors or t.id not in LAYOUTS:
        info = km.classes.get(n.cls or "")
        if info is not None and info.kind == "system" and n.points:
            return {"kind": "system_graphic", "page": "graphics", "query": {"project": project},
                    "points_on_graphic": len(n.points), "points_off_graphic": 0,
                    "note": "The plant's own points are on the water-side system graphic (Graphics page, Systems "
                            "tab). Values simulated (not live)."}
        return None
    p = equipment_payload(store, project, equip_id, km, anchors, tree)
    qa = check_equipment(p, render(p))
    c = qa["counts"]
    return {"kind": "equipment_graphic", "template": t.id, "page": "Equipment_3D",
            "query": {"project": project, "equip": equip_id},
            "points_on_model": c["bound"], "points_off_model": c["unplaced"],
            "off_model": [p["points"][i]["label"] for i in p["unplaced"]][:20],
            "qa": qa["status"], "qa_problems": [x["detail"] for x in qa["checks"] if x["level"] != "ok"],
            "note": "3D model and 2D graphic of the template with the unit's points on their anchors; values "
                    "simulated (not live)."}
