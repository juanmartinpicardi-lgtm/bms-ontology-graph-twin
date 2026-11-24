"""Mapper: raw records -> proposed knowledge graph (nodes + edges with provenance).

Order (CLAUDE.md section 3):
  1. structure   - folder paths give equipment groups and part-of links          (method=parsed)
                   names-only input: equipment ids inside names, e.g. "EF-1 Status" (method=rule)
  2. name rules  - parse each name and match it to a Brick class                    (method=rule)
  3. templates   - type each equipment from its name and its points; refine generic
                   point classes from the equipment's template; infer feeds           (method=template)
  4. LLM         - only for points still below `llm_below`, with a short candidate list (method=llm); its
                   confidence is capped at `llm_cap`, below the auto-accept threshold, so a person reviews it
Conventions (km.conventions, see conventions.py) take part as rules: a class hint decides a point's class
before anything else and is not refined by templates (method=rule); abbreviations and equipment patterns
feed steps 2-3; ignore rules flag points for review. Whatever a convention decided or contributed is
recorded in attrs.convention, e.g. ["site/alpha:abbreviations.cc"].
Nothing is written back to any source.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..db.store import Edge, Node, Store
from ..knowledge_model import KnowledgeModel, Template
from ..records import RawRecord
from .classify import ClassGuess, ClassMatcher
from .llm import LLMProvider, LLMRequest, NoLLM

# Words that say where in the system a point sits; if a name has any, templates don't override it.
POSITION_WORDS = {"supply", "discharge", "return", "mixed", "outside", "exhaust", "relief", "zone", "hot",
                  "cold", "deck", "entering", "leaving", "chilled", "condenser", "inlet", "outlet"}
TEMPLATE_AGREEMENT_BOOST = 0.5  # share of the remaining confidence gained when a point fits a template slot
HINT_CONFIDENCE = 0.95  # a class hint is a person's statement about this site's names
# A model's answer is a proposal for review: kept below the auto-accept threshold (scoring.DEFAULT_ACCEPT = 0.8).
# Chosen on Alpha (dev): Gemini 4 Argon said ~0.98 on the leftover points and had 3 of 23 right.
LLM_CAP = 0.75
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
    convention: list[str] = field(default_factory=list)


class Mapper:
    def __init__(self, km: KnowledgeModel, llm: LLMProvider | None = None, llm_below: float = 0.4,
                 llm_cap: float = LLM_CAP):
        self.km = km
        self.llm_cap = llm_cap
        self.points = ClassMatcher(km, "point")
        self.equipment = ClassMatcher(km, "equipment", also=("system",))  # a folder may be a plant / loop
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
        # The point's own equipment name (last folder, or an id found in the name) is not part of what it is.
        out = {}
        for r in records:
            guess = self.points.classify(r.name, r.path.split("/")[-1] if r.path else self._equipment_id_in_name(r.name))
            hint = next((h for h in self.km.class_hints if h.pattern.search(r.name)), None)
            if hint:
                guess.hint = hint.origin
                guess.cls, guess.confidence = hint.cls, HINT_CONFIDENCE
            out[f"pt:{r.source_id}"] = guess
        return out

    def point_conventions(self, r: RawRecord, guess: ClassGuess) -> list[str]:
        """Conventions that decided or contributed to a point: its class hint, convention abbreviations
        among its tokens, and an ignore rule."""
        used = [guess.hint] if guess.hint else []
        origin = self.km.abbreviation_origin
        used += sorted({origin[t] for t in self.km.name_rules.tokenize(r.name) if t in origin})
        rule = self.ignore_rule(r.name)
        return used + ([rule.origin] if rule else [])

    def ignore_rule(self, name: str):
        return next((g for g in self.km.ignore if g.pattern.search(name)), None)

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
        g.evidence = {"name_patterns": [t.id for t in by_name], "name_guess": name_guess.cls,
                      "slot_fill": {k: v[0] for k, v in fills.items() if v[0] > 0}}

        # A name that clearly says plant / system ("Hot Water Plant", "Boiler Room HW Sys") is a system,
        # even when it also mentions equipment that a template would match.
        if name_guess.cls and self.km.classes[name_guess.cls].kind == "system" and name_guess.confidence >= 0.5:
            g.cls, g.cls_conf, g.cls_method, g.template = name_guess.cls, name_guess.confidence, "rule", None
            return

        if by_name:
            t = max(by_name, key=lambda t: fills.get(t.id, (0, 0)))
            fill, _ = fills.get(t.id, (0.0, 0))
            in_range = t.point_count[0] <= n <= t.point_count[1]
            g.cls, g.template = t.brick_class, t
            g.cls_conf = 0.6 + 0.3 * fill + 0.1 * in_range if n else 0.6
            g.cls_method = "template" if n else "rule"
            own = [p for p in t.name_patterns if p.pattern not in t.pattern_origin and p.search(g.label)]
            if not own:  # recognised only through a convention's pattern: the convention decided
                g.convention = sorted({t.pattern_origin[p.pattern] for p in t.name_patterns
                                       if p.pattern in t.pattern_origin and p.search(g.label)})
                g.cls_method = "rule"
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

    def refine_points(self, g: EquipGroup, guesses: dict[str, ClassGuess]) -> dict[str, tuple[str, float, str]]:
        """Template context: make a generic point class specific, and raise confidence when a point
        fits one of the equipment's slots. Returns point_id -> (class, confidence, method)."""
        out = {}
        t = g.template
        for pid in g.points:
            guess = guesses[pid]
            # A class hint is final. A fallback guess (no class name matched, so no alternatives) says only
            # the point's function, too little to give it one of the template's slots.
            if not guess.cls or not t or guess.hint or not guess.alternatives:
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

    def infer_feeds(self, groups: dict[str, EquipGroup],
                    point_cls: dict[str, str | None] | None = None) -> list[tuple[str, str, float, str | None]]:
        """(source, target, confidence, medium) feeds links, from two rules:
        folder - a parent folder feeds a child when one of their templates says so (AHU feeds VAV);
        medium - equipment whose template is fed by a water medium, and that has a point showing it uses
                 that medium (a filled slot with that `medium`), is fed by the site's single top-level
                 system of that medium, or else by the single equipment of the producing template."""
        out, seen = [], set()

        def add(src, dst, conf, medium):
            if src != dst and (src, dst) not in seen:
                seen.add((src, dst))
                out.append((src, dst, round(conf, 4), medium))

        for g in groups.values():
            p = groups.get(g.parent) if g.parent else None
            if not p or not g.template or not p.template:
                continue
            fed_by_parent = next((r for r in g.template.relations if r.rel == "isFedBy" and r.target == p.template.id), None)
            parent_feeds = next((r for r in p.template.relations if r.rel == "feeds" and r.target == g.template.id), None)
            if fed_by_parent or parent_feeds:
                add(p.id, g.id, 0.9 * min(p.cls_conf, g.cls_conf), (fed_by_parent or parent_feeds).medium or None)

        if point_cls is None:
            return out
        is_a = self.km.is_a

        def ancestors(gid):
            while gid := (groups[gid].parent if gid in groups else None):
                yield gid

        def source_for(rel):
            if rel.system:
                systems = [g for g in groups.values() if g.cls and is_a(g.cls, rel.system)]
                top = [s for s in systems if not any(groups[a].cls and is_a(groups[a].cls, rel.system)
                                                     for a in ancestors(s.id))]
                if len(top) == 1:
                    return top[0]
                if top:
                    return None  # several plants of this medium: can't tell which one feeds what
            producers = [g for g in groups.values() if g.template and g.template.id == rel.target]
            return producers[0] if len(producers) == 1 else None

        for g in groups.values():
            if not g.template:
                continue
            classes = [point_cls.get(p) for p in g.points]
            for rel in g.template.relations:
                if rel.rel != "isFedBy" or rel.medium not in ("hot_water", "chilled_water"):
                    continue
                uses = any(c and any(is_a(c, sc) or is_a(sc, c) for sc in s.classes)
                           for s in g.template.slots if s.medium == rel.medium for c in classes)
                src = source_for(rel) if uses else None
                if src is not None:
                    add(src.id, g.id, 0.8 * min(src.cls_conf, g.cls_conf), rel.medium)
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
        logs_itself = getattr(self.llm, "logs_calls", False)
        if logs_itself:
            self.llm.bind(store, project, revision)
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
            if not logs_itself:
                store.log_llm_call(project, revision, self.llm.name, ans.model, json.dumps(req.__dict__),
                                   ans.raw_output, ans.cost_usd, ans.latency_s)
            if ans.cls in req.candidates:
                # Capped: a model's own confidence is not calibrated, so its answer goes to review, never straight
                # to auto-accept. The model's number stays in llm_calls.
                final[pid] = (ans.cls, min(ans.confidence, self.llm_cap), "llm")

        nodes, edges = [], []
        for g in groups.values():
            attrs = {"grouping": g.method, "template": g.template.id if g.template else None,
                     "evidence": g.evidence, "points": len(g.points)}
            if g.convention:
                attrs["convention"] = g.convention
            nodes.append(Node(g.id, "equipment", g.label, g.cls, source_file, g.source_ref, g.cls_method,
                              g.cls_conf, attrs, aliases=[("bms_path", g.source_ref)] if g.method == "parsed" else []))
            if g.parent:
                edges.append(Edge(g.parent, "hasPart", g.id, source_file, g.source_ref, "parsed", 1.0))
        for src, dst, conf, medium in self.infer_feeds(groups, {pid: c for pid, (c, _, _) in final.items()}):
            edges.append(Edge(src, "feeds", dst, source_file, groups[dst].source_ref, "template", conf,
                              {"medium": medium}))
        for pid, (cls, conf, method) in final.items():
            r, guess = rec_by_pid[pid], guesses[pid]
            attrs = {"source_id": r.source_id, "path": r.path, "words": guess.words,
                     "alternatives": guess.alternatives, "unknown_tokens": guess.unknown}
            if used := self.point_conventions(r, guess):
                attrs["convention"] = used
            if rule := self.ignore_rule(r.name):
                attrs["ignore"] = {"reason": rule.reason, "convention": rule.origin}
            nodes.append(Node(pid, "point", r.name, cls, source_file, str(r.source_row), method, conf, attrs,
                              aliases=_point_aliases(r)))
            if pid in member:
                g = groups[member[pid]]
                edges.append(Edge(g.id, "hasPoint", pid, source_file, str(r.source_row), g.method, g.confidence))
        # One source per input file: re-running it replaces only its own rows (db/store.py).
        store.replace_machine_rows(project, revision, nodes, edges, source=f"mapper:{Path(source_file).name}")

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
            "points_ignored": sum(1 for n in points if "ignore" in n.attrs),
            "conventions": list(self.km.conventions),
            "llm_provider": self.llm.name,
            "llm_calls": llm_calls,
            "seconds": round(seconds, 2),
            "seconds_per_1000_points": round(1000 * seconds / max(1, len(points)), 2),
        }
        store.finish_run(project, revision, seconds, summary)
        return summary


def _point_aliases(r: RawRecord) -> list[tuple[str, str]]:
    """The names other sources may use for this point: its id in the export (a Haystack id unless the export is a
    blind one), its BMS name (folder path and name, when there is a path), its BACnet device and object."""
    out = [("haystack_id" if r.source_system.startswith("haystack") and "blind" not in r.source_system
            else "export_id", r.source_id)]
    if r.path:
        out.append(("bms_name", f"{r.path}/{r.name}"))
    if r.device_id and r.object_id:
        out.append(("device_object", f"{r.device_id}:{r.object_id}"))
    return out


def _count(items) -> dict:
    d = defaultdict(int)
    for i in items:
        d[i] += 1
    return dict(sorted(d.items(), key=lambda kv: str(kv[0])))


def _bucket(c: float) -> str:
    return "0.0" if c == 0 else f"{min(int(c * 10), 9) / 10:.1f}-{min(int(c * 10), 9) / 10 + 0.1:.1f}"
