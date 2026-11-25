"""Graphics coverage of one project: for every equipment, its template, whether it has a 3D and a 2D graphic, how
many of its points are bound to anchors, which are not (and their classes), and its QA result. Rolled up per
equipment type (the equipment's class), which is how the W9 done-when is stated: every type has a graphic with its
points bound, and QA runs on each.

Binding goes through the graph only: a point's equipment (hasPoint), its class, the template's slots
(equipment_view.assign_slots) and the anchor map. Nothing is read from a source document here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..db.store import Store
from ..equipment_view import equipment_payload, load_anchors, node_template
from ..knowledge_model import KnowledgeModel
from ..tree import UNPLACED, build_tree
from .equipment2d import render
from .layouts import LAYOUTS
from .qa import check_equipment

DRAWN_3D = {"ahu", "vav", "rvav", "fcu", "chiller", "boiler", "pump", "rtu", "exhaust_fan", "unit_heater",
            "split_system", "cooling_tower", "heat_exchanger", "meter"}  # templates with a builder in equipment3d/


@dataclass
class EquipmentCoverage:
    id: str
    label: str
    cls: str
    template: str | None
    points: int = 0
    bound: int = 0
    unplaced: list[tuple[str, str, str]] = field(default_factory=list)  # (point id, label, class)
    qa: dict | None = None
    has_3d: bool = False
    has_2d: bool = False
    system: bool = False  # a system (the CHW plant): its points are on the water-side system graphic, not a model

    @property
    def status(self) -> str:
        if self.qa:
            return self.qa["status"]
        if self.system and self.points:
            return "on the system graphic"
        return "passive, no points" if not self.points else "no graphic"


@dataclass
class TypeCoverage:
    cls: str
    templates: list[str]
    equipment: list[EquipmentCoverage]

    @property
    def count(self) -> int:
        return len(self.equipment)

    @property
    def has_graphic(self) -> bool:
        return all(e.has_2d and (e.has_3d or e.system) for e in self.equipment)

    @property
    def needs_graphic(self) -> bool:
        """A type with no template and no points anywhere (an expansion tank, an air separator) has nothing to bind."""
        return any(e.template or e.points for e in self.equipment)

    @property
    def points(self) -> int:
        return sum(e.points for e in self.equipment)

    @property
    def bound(self) -> int:
        return sum(e.bound for e in self.equipment)

    @property
    def qa(self) -> Counter:
        return Counter(e.status for e in self.equipment)

    @property
    def unplaced_classes(self) -> Counter:
        return Counter(c or "no class" for e in self.equipment for _, _, c in e.unplaced)


def equipment_coverage(store: Store, project: str, km: KnowledgeModel, anchors: dict | None = None,
                       tree=None, graphics: bool = True) -> list[EquipmentCoverage]:
    anchors = load_anchors() if anchors is None else anchors
    tree = build_tree(store, project) if tree is None else tree
    out = []
    for n in sorted((n for n in tree.by_id.values() if n.kind == "equipment" and n.id != UNPLACED), key=lambda n: n.label):
        t = node_template(n, km)
        ec = EquipmentCoverage(n.id, n.label, n.cls or "", t.id if t else None)
        if t and t.id in anchors:
            p = equipment_payload(store, project, n.id, km, anchors, tree)
            ec.points = len(p["points"])
            ec.bound = ec.points - len(p["unplaced"])
            ec.unplaced = [(i, p["points"][i]["label"], p["points"][i]["cls"] or "") for i in p["unplaced"]]
            ec.has_3d = t.id in DRAWN_3D
            if graphics and t.id in LAYOUTS:
                g = render(p)
                ec.has_2d = True
                ec.qa = check_equipment(p, g)
        else:
            live = [p for p in n.points if p.prov.get("status") != "rejected"]
            ec.points = len(live)
            info = km.classes.get(n.cls or "")
            if info is not None and info.kind == "system" and live:  # drawn as a card on the system graphic
                ec.system = ec.has_2d = True
                ec.bound = len(live)
            else:
                ec.unplaced = [(p.id, p.label, p.cls or "") for p in live]
        out.append(ec)
    return out


def by_type(rows: list[EquipmentCoverage]) -> list[TypeCoverage]:
    groups: dict[str, list[EquipmentCoverage]] = {}
    for r in rows:
        groups.setdefault(r.cls or "(no class)", []).append(r)
    return sorted((TypeCoverage(c, sorted({e.template for e in es if e.template}), es) for c, es in groups.items()),
                  key=lambda t: (-t.count, t.cls))


def orphan_points(tree) -> list[tuple[str, str, str]]:
    """Points the graph puts on no equipment (no hasPoint): they can't be on any graphic. (id, label, class)."""
    n = tree.by_id.get(UNPLACED)
    return [(p.id, p.label, p.cls or "") for p in n.points] if n else []
