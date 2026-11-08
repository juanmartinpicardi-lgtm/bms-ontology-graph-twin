"""Data for the 3D equipment view (docs/spec-equipment-3d.md): which template slot each point fills, where that
slot sits on the 3D model (knowledge_model/templates/anchors.yaml), and which optional parts to draw.

    point class --(first template slot whose classes include it)--> slot role --(anchor map)--> part on the model

Sub-equipment without a template of its own (AHU-2's "SF VFD", "RF VFD") is drawn as part of its parent: its points
attach to the part the anchor map names for its class. Rejected points and rejected links are left out, as in the tree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .db.store import Store
from .knowledge_model import KM_DIR, KnowledgeModel, Slot, Template
from .tree import TreeNode, build_tree

ANCHORS = KM_DIR / "templates" / "anchors.yaml"
APP = Path(__file__).resolve().parent / "app"
MODULES = ("core.js", "parts.js", "ahu.js", "vav.js", "labels.js", "panels.js")  # inlined in this order into equipment3d.html


def load_anchors(path: Path = ANCHORS) -> dict:
    return yaml.safe_load(Path(path).read_text())


def anchor_problems(km: KnowledgeModel, anchors: dict) -> list[str]:
    """Every slot role of a drawn type has an anchor, every anchor names a real role and a declared part,
    and sub-equipment classes and parts exist."""
    problems = []
    for tid, spec in anchors.items():
        where = f"anchors.yaml: {tid}"
        if tid not in km.templates:
            problems.append(f"{where} is not a template")
            continue
        parts = set(spec.get("parts", []))
        roles = {s.role for s in km.templates[tid].slots}
        placed = spec.get("anchors", {})
        for role in sorted(roles - set(placed)):
            problems.append(f"{where}: slot {role} has no anchor")
        for role, a in placed.items():
            if role not in roles:
                problems.append(f"{where}: anchor {role} is not a slot of the template")
            if a.get("part") not in parts:
                problems.append(f"{where}: anchor {role} names part {a.get('part')!r}, which is not in parts")
            if "at" in a and not 0 <= a["at"] <= 1:
                problems.append(f"{where}: anchor {role} has at={a['at']}, must be 0-1")
        for cls, part in (spec.get("sub_equipment") or {}).items():
            if cls not in km.classes or km.classes[cls].kind != "equipment":
                problems.append(f"{where}: sub_equipment {cls} is not an equipment class in the model")
            if part not in parts:
                problems.append(f"{where}: sub_equipment {cls} -> {part!r} is not in parts")
    return problems


def slot_for(template: Template, cls: str | None, words: set[str], km: KnowledgeModel) -> Slot | None:
    """The first slot (template order) whose classes include `cls` (else one listing a parent of it). A slot with
    `words` is only taken when the name has one of them, and then wins over earlier slots without words
    ("RF Status" -> return_fan_status)."""
    if not cls or cls not in km.classes:
        return None
    fits = ([s for s in template.slots if cls in s.classes]
            or [s for s in template.slots if any(km.is_a(cls, c) for c in s.classes)])
    worded = [s for s in fits if s.words and words & set(s.words)]
    return worded[0] if worded else next((s for s in fits if not s.words), None)


def assign_slots(template: Template, points: list[dict], km: KnowledgeModel) -> tuple[dict[str, list[str]], list[str]]:
    """points: [{id, label, cls, context?}], `context` being extra name text such as a sub-equipment's label.
    Returns ({role: [point ids]}, [unplaced point ids]). A slot may hold several points (they stack)."""
    slots: dict[str, list[str]] = {}
    unplaced = []
    for p in points:
        words = set(km.name_rules.words(f"{p['label']} {p.get('context') or ''}"))
        s = slot_for(template, p["cls"], words, km)
        if s:
            slots.setdefault(s.role, []).append(p["id"])
        else:
            unplaced.append(p["id"])
    return slots, unplaced


def variant(template: Template, slots: dict[str, list[str]], name: str, sub_parts: set[str],
            km: KnowledgeModel) -> dict[str, bool]:
    """Optional parts to draw, from the slots found (and the name, for VAV box types)."""
    has = lambda *roles: any(slots.get(r) for r in roles)  # noqa: E731
    if template.id == "ahu":
        return {"heating_coil": has("heating_valve"), "mixing_box": has("economizer_damper"),
                "relief_outlet": has("relief_damper"),
                "return_fan": has("return_fan_cmd", "return_fan_speed", "return_fan_status") or "return_fan" in sub_parts}
    if template.id == "vav":
        tokens = set(km.name_rules.tokenize(name))
        return {"reheat": has("reheat_valve"), "fan_powered": has("fan_cmd") or "fpb" in tokens,
                "dual_duct": "dd" in tokens}
    return {}


DECK_PARTS = ("damper", "flow_cross")
DECK_WORDS = {"hot": {"hot", "heating"}, "cold": {"cold", "cooling", "chilled"}}


def deck(name: str, km: KnowledgeModel) -> str | None:
    """The deck of a dual-duct point from its name ("Clg Dmpr Pos" -> cold), None when it doesn't say."""
    words = set(km.name_rules.words(name))
    found = [d for d, ws in DECK_WORDS.items() if words & ws]
    return found[0] if len(found) == 1 else None


def sub_equipment_part(node: TreeNode, spec: dict, km: KnowledgeModel) -> str | None:
    """The part an untemplated child equipment is drawn as: by its class, else by its name ("SF VFD" -> supply fan)."""
    table = spec.get("sub_equipment") or {}
    if node.cls in km.classes:
        for cls, part in table.items():
            if km.is_a(node.cls, cls):
                return part
    words = set(km.name_rules.words(node.label))
    for cls, part in table.items():
        if set(km.class_matching.class_words(cls)) <= words:
            return part
    return None


def _natural(label: str) -> list:
    """Sort key that orders "VAV 1-2-2" before "VAV 1-2-10"."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", label)]


def _point(p: TreeNode) -> dict:
    return {"label": p.label, "cls": p.cls, "confidence": p.prov.get("confidence"), "status": p.prov.get("status"),
            "prov": p.prov, "via": p.via}


def equipment_payload(store: Store, project: str, equip_id: str, km: KnowledgeModel,
                      anchors: dict | None = None) -> dict:
    anchors = load_anchors() if anchors is None else anchors
    tree = build_tree(store, project)
    eq = tree.by_id.get(equip_id)
    if eq is None or eq.kind != "equipment":
        raise KeyError(f"{equip_id} is not an equipment of {project}")
    template = km.templates.get(eq.attrs.get("template") or "")
    if template is None or template.id not in anchors:
        raise ValueError(f"{eq.label} has no 3D model (template {template.id if template else None})")
    spec = anchors[template.id]
    fan_parts = set((spec.get("sub_equipment") or {}).values())

    live = lambda ps: [p for p in ps if p.prov.get("status") != "rejected"]  # noqa: E731
    points = {p.id: {**_point(p), "sub_equipment": None, "context": None} for p in live(eq.points)}
    sub_parts, sub_of = set(), {}
    for c in eq.children:
        if c.attrs.get("template"):
            continue  # equipment in its own right (a VAV under its AHU folder), not a part of this one
        part = sub_equipment_part(c, spec, km)
        if part:
            sub_parts.add(part)
        for p in live(c.points):
            points[p.id] = {**_point(p), "sub_equipment": c.id, "context": c.label}
            sub_of[p.id] = part

    slots, unplaced = assign_slots(template, [{"id": i, **p} for i, p in points.items()], km)
    # Points of unmapped sub-equipment (e.g. exhaust fans) have no part on this model.
    for role in list(slots):
        for pid in [p for p in slots[role] if points[p]["sub_equipment"] and not sub_of[p]]:
            slots[role].remove(pid)
            unplaced.append(pid)
        if not slots[role]:
            del slots[role]

    for role, pids in slots.items():
        a = spec["anchors"][role]
        for pid in pids:
            part = a["part"]
            head, _, rest = part.partition(".")
            if sub_of.get(pid) and head in fan_parts:  # supply_fan.vfd on "RF VFD" -> return_fan.vfd
                part = sub_of[pid] + ("." + rest if rest else "")
            points[pid].update(role=role, part=part, at=a.get("at"))
    for pid in unplaced:
        points[pid].update(role=None, part=None, at=None)
    var = variant(template, slots, eq.label, sub_parts, km)
    if var.get("dual_duct"):  # each deck has its own damper and flow cross: "Htg Dmpr Cmnd" -> damper@hot
        for p in points.values():
            if p["part"] in DECK_PARTS:
                p["at"] = deck(p["label"], km)
    for p in points.values():
        del p["context"]

    required = [s for s in template.slots if s.required]
    def _rel(nid):
        n = tree.by_id[nid]
        return {"id": n.id, "label": n.label, "cls": n.cls, "template": n.attrs.get("template")}
    return {
        "project": project,
        "equipment": {"id": eq.id, "label": eq.label, "cls": eq.cls, "template": template.id,
                      "slot_fill": round(sum(1 for s in required if slots.get(s.role)) / len(required), 4)
                      if required else 1.0,
                      "prov": eq.prov},
        "variant": var,
        "slots": [{"role": s.role, "classes": list(s.classes), "required": s.required, "medium": s.medium or None,
                   "anchor": spec["anchors"][s.role], "points": slots.get(s.role, [])} for s in template.slots],
        "points": points,
        "unplaced": sorted(unplaced, key=lambda i: points[i]["label"]),
        "relations": {"fed_by": sorted((_rel(s) for s, _ in tree.fed_by(eq.id)), key=lambda r: _natural(r["label"])),
                      "feeds": sorted((_rel(d) for d, _ in tree.feeds_to(eq.id)), key=lambda r: _natural(r["label"]))},
        "value_source": "simulated",
    }


def render_html(payload: dict, theme: str | None = None) -> str:
    """The 3D equipment page with the payload and the JS modules inlined, so it works in Streamlit's iframe and as a
    standalone file (three.js comes from the CDN). `theme` ("light" / "dark") pins the colours to the host app's
    theme; without it the page follows the system setting."""
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    modules = "\n".join((APP / "equipment3d" / m).read_text() for m in MODULES)
    html = (APP / "equipment3d.html").read_text().replace("/*__MODULES__*/", modules).replace("/*__DATA__*/null", data)
    if theme in ("light", "dark"):
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return html
