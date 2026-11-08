"""Mapper: raw records -> proposed knowledge graph (nodes + edges with provenance).

Order (CLAUDE.md section 3):
  1. structure   - folder paths give equipment groups and part-of links          (method=parsed)
                   names-only input: equipment ids inside names, e.g. "EF-1 Status" (method=rule)
  2. name rules  - parse each name and match it to a Brick class                    (method=rule)
  3. templates   - type each equipment from its name and its points; refine generic
                   point classes from the equipment's template; infer feeds           (method=template)
  4. LLM         - only for points still below `llm_below`, with a short candidate list (method=llm)
Nothing is written back to any source.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from ..db.store import Edge, Node, Store
from ..knowledge_model import KnowledgeModel, Template
from ..records import RawRecord
from .classify import ClassGuess, ClassMatcher
from .llm import LLMProvider, LLMRequest, NoLLM

# Words that say where in the system a point sits; if a name has any, templates don't override it.
POSITION_WORDS = {"supply", "discharge", "return", "mixed", "outside", "exhaust", "relief", "zone", "hot",
                  "cold", "deck", "entering", "leaving", "chilled", "condenser", "inlet", "outlet"}
TEMPLATE_AGREEMENT_BOOST = 0.5  # share of the remaining confidence gained when a point fits a template slot
EQUIP_ID = re.compile(r"\b([A-Za-z]{1,6})[-_ ]?(\d{1,3}[A-Za-z]?)\b")


@dataclass
class EquipGroup:
    id: str
    label: str  # folder / equipment name used for typing
    source_ref: str
    method: str  # how the group was found
    confidence: float  # confidence that the grouping is right
    parent: str | None = None
    points: list[str] = field(default_factory=list)  # point node ids
    cls: str | None = None
    cls_conf: float = 0.0
    cls_method: str = "rule"
    template: Template | None = None
    evidence: dict = field(default_factory=dict)


class Mapper:
    def __init__(self, km: KnowledgeModel, llm: LLMProvider | None = None, llm_below: float = 0.4):
        self.km = km
        self.points = ClassMatcher(km, "point")
        self.equipment = ClassMatcher(km, "equipment")
        self.llm = llm or NoLLM()
        self.llm_below = llm_below
        self._equip_prefixes = {
            k for k, alts in km.name_rules.abbreviations.items()
            if any(w in {"fan", "pump", "chiller", "boiler", "cooling_tower", "heat_exchanger", "vfd"}
                   for a in alts for w in a)
        }

    # 1. structure ------------------------------------------------------------------------------

    def group(self, records: list[RawRecord]) -> tuple[dict[str, EquipGroup], dict[str, str]]:
        """Return equipment groups and point_id -> group id."""
        groups: dict[str, EquipGroup] = {}
        member: dict[str, str] = {}
        for r in records:
            pid = f"pt:{r.source_id}"
            if r.path:
                parts = r.path.split("/")
                for depth in range(1, len(parts) + 1):
                    gid = "eq:" + "/".join(parts[:depth])
                    if gid not in groups:
                        parent = "eq:" + "/".join(parts[:depth - 1]) if depth > 1 else None
                        groups[gid] = EquipGroup(gid, parts[depth - 1], "/".join(parts[:depth]), "parsed", 1.0, parent)
                gid = "eq:" + r.path
                groups[gid].points.append(pid)
                member[pid] = gid
            else:
                key = self._equipment_id_in_name(r.name)
                if key:
                    gid = f"eq:name:{key}"
                    groups.setdefault(gid, EquipGroup(gid, key, key, "rule", 0.7))
                    groups[gid].points.append(pid)
                    member[pid] = gid
        return groups, member

    def _equipment_id_in_name(self, name: str) -> str | None:
        for m in EQUIP_ID.finditer(name):
            prefix, num = m.group(1), m.group(2)
            text = f"{prefix.upper()}-{num.upper()}"
            if prefix.lower() in self._equip_prefixes or any(t.matches_name(text) for t in self.km.templates.values()):
                return text
        return None

    # 2. name rules -----------------------------------------------------------------------------

    def classify_points(self, records: list[RawRecord]) -> dict[str, ClassGuess]:
        return {f"pt:{r.source_id}": self.points.classify(r.name) for r in records}

    # 3. templates ------------------------------------------------------------------------------

    def _slot_fill(self, template: Template, classes: list[str | None]) -> tuple[float, int]:
        """Share of required slots filled, and how many points fit any slot."""
        fits, required_hit = 0, set()
        for c in classes:
            if not c:
                continue
            hit = False
            for s in template.slots:
                if any(self.km.is_a(c, sc) or self.km.is_a(sc, c) for sc in s.classes):
                    hit = True
                    if s.required:
                        required_hit.add(s.role)
            fits += hit
        required = [s for s in template.slots if s.required]
        return (len(required_hit) / len(required) if required else 1.0), fits

    def type_equipment(self, g: EquipGroup, guesses: dict[str, ClassGuess]) -> None:
        classes = [guesses[p].cls for p in g.points]
        n = len(g.points)
        by_name = [t for t in self.km.templates.values() if t.matches_name(g.label)]
        name_guess = self.equipment.classify(g.label)
        fills = {t.id: self._slot_fill(t, classes) for t in self.km.templates.values()} if n else {}

        if by_name:
            t = max(by_name, key=lambda t: fills.get(t.id, (0, 0)))
            fill, _ = fills.get(t.id, (0.0, 0))
            in_range = t.point_count[0] <= n <= t.point_count[1]
            g.cls, g.template = t.brick_class, t
            g.cls_conf = 0.6 + 0.3 * fill + 0.1 * in_range if n else 0.6
            g.cls_method = "template" if n else "rule"
        elif name_guess.cls:
            g.cls, g.cls_conf, g.cls_method = name_guess.cls, name_guess.confidence, "rule"
            g.template = next((t for t in self.km.templates.values() if self.km.is_a(g.cls, t.brick_class)), None)
        elif fills:
            tid, (fill, fits) = max(fills.items(), key=lambda kv: kv[1])
            t = self.km.templates[tid]
            if fill == 1.0 and t.point_count[0] <= n <= t.point_count[1]:
                g.cls, g.template, g.cls_method = t.brick_class, t, "template"
                g.cls_conf = 0.4 + 0.3 * fits / n
        if not g.cls:
            g.cls, g.cls_conf, g.cls_method = "Equipment", 0.1, "rule"
        g.evidence = {"name_patterns": [t.id for t in by_name], "name_guess": name_guess.cls,
                      "slot_fill": {k: v[0] for k, v in fills.items() if v[0] > 0}}

    def refine_points(self, g: EquipGroup, guesses: dict[str, ClassGuess]) -> dict[str, tuple[str, float, str]]:
        """Template context: make a generic point class specific, and raise confidence when a point
        fits one of the equipment's slots. Returns point_id -> (class, confidence, method)."""
        out = {}
        t = g.template
        for pid in g.points:
            guess = guesses[pid]
            if not guess.cls or not t:
                continue
            cls, conf, method = guess.cls, guess.confidence, "rule"
            slot_classes = [c for s in t.slots for c in s.classes]
            # A slot lists its preferred class first; a name that says nothing about position
            # (no supply/discharge/hot deck...) gets the preferred, more specific class.
            if not (set(guess.words) & POSITION_WORDS):
                specific = next((s.classes[0] for s in t.slots
                                 if s.classes[0] != cls and self.km.is_a(s.classes[0], cls)), None)
                if specific:
                    cls, conf, method = specific, conf * 0.9, "template"
            if cls in slot_classes:
                conf = conf + (1 - conf) * TEMPLATE_AGREEMENT_BOOST
                method = "template"
            out[pid] = (cls, round(conf, 4), method)
        return out

    def infer_feeds(self, groups: dict[str, EquipGroup]) -> list[tuple[str, str, float]]:
        """Parent folder feeds child when one of their templates says so (e.g. AHU feeds VAV)."""
        out = []
        for g in groups.values():
            p = groups.get(g.parent) if g.parent else None
            if not p or not g.template or not p.template:
                continue
            fed_by_parent = any(r.rel == "isFedBy" and r.target == p.template.id for r in g.template.relations)
            parent_feeds = any(r.rel == "feeds" and r.target == g.template.id for r in p.template.relations)
            if fed_by_parent or parent_feeds:
                out.append((p.id, g.id, round(0.9 * min(p.cls_conf, g.cls_conf), 4)))
        return out

    # run ---------------------------------------------------------------------------------------

    def run(self, records: list[RawRecord], store: Store, project: str) -> dict:
        t0 = time.perf_counter()
        source_file = records[0].source_file if records else ""
        revision = store.start_run(project, source_file)
        groups, member = self.group(records)
        guesses = self.classify_points(records)
        final: dict[str, tuple[str | None, float, str]] = {
            pid: (g.cls, g.confidence, "rule") for pid, g in guesses.items()
        }
        for g in groups.values():
            self.type_equipment(g, guesses)
            final.update(self.refine_points(g, guesses))

        rec_by_pid = {f"pt:{r.source_id}": r for r in records}
        llm_calls = 0
        for pid, (cls, conf, _) in list(final.items()):
            if conf >= self.llm_below:
                continue
            r = rec_by_pid[pid]
            eq = groups.get(member.get(pid, ""))
            req = LLMRequest(r.name, r.path, eq.cls if eq else None, [c for c, _ in guesses[pid].alternatives])
            ans = self.llm.classify_point(req)
            if ans is None:
                continue
            llm_calls += 1
            store.log_llm_call(project, revision, self.llm.name, ans.model, json.dumps(req.__dict__),
                               ans.raw_output, ans.cost_usd, ans.latency_s)
            if ans.cls in req.candidates:
                final[pid] = (ans.cls, ans.confidence, "llm")

        nodes, edges = [], []
        for g in groups.values():
            nodes.append(Node(g.id, "equipment", g.label, g.cls, source_file, g.source_ref, g.cls_method,
                              g.cls_conf, {"grouping": g.method, "template": g.template.id if g.template else None,
                                           "evidence": g.evidence, "points": len(g.points)}))
            if g.parent:
                edges.append(Edge(g.parent, "hasPart", g.id, source_file, g.source_ref, "parsed", 1.0))
        for src, dst, conf in self.infer_feeds(groups):
            edges.append(Edge(src, "feeds", dst, source_file, groups[dst].source_ref, "template", conf,
                              {"medium": "air" if self.km.is_a(groups[dst].cls or "", "Terminal_Unit") else None}))
        for pid, (cls, conf, method) in final.items():
            r, guess = rec_by_pid[pid], guesses[pid]
            nodes.append(Node(pid, "point", r.name, cls, source_file, str(r.source_row), method, conf,
                              {"source_id": r.source_id, "path": r.path, "words": guess.words,
                               "alternatives": guess.alternatives, "unknown_tokens": guess.unknown}))
            if pid in member:
                g = groups[member[pid]]
                edges.append(Edge(g.id, "hasPoint", pid, source_file, str(r.source_row), g.method, g.confidence))
        store.replace_machine_rows(project, revision, nodes, edges)

        seconds = time.perf_counter() - t0
        points = [n for n in nodes if n.kind == "point"]
        summary = {
            "revision": revision,
            "points": len(points),
            "points_classified": sum(1 for n in points if n.cls),
            "points_grouped": len(member),
            "equipment": len(groups),
            "equipment_typed": sum(1 for g in groups.values() if g.cls != "Equipment"),
            "edges": dict(_count(e.rel for e in edges)),
            "point_methods": dict(_count(n.method for n in points)),
            "point_confidence": dict(_count(_bucket(n.confidence) for n in points)),
            "llm_provider": self.llm.name,
            "llm_calls": llm_calls,
            "seconds": round(seconds, 2),
            "seconds_per_1000_points": round(1000 * seconds / max(1, len(points)), 2),
        }
        store.finish_run(project, revision, seconds, summary)
        return summary


def _count(items) -> dict:
    d = defaultdict(int)
    for i in items:
        d[i] += 1
    return dict(sorted(d.items(), key=lambda kv: str(kv[0])))


def _bucket(c: float) -> str:
    return "0.0" if c == 0 else f"{min(int(c * 10), 9) / 10:.1f}-{min(int(c * 10), 9) / 10 + 0.1:.1f}"
