"""Knowledge model explorer: how well the reusable model covers one project, and where it is weak.

Read-only. The YAML/TTL files in /knowledge_model stay the source of truth; this only measures them
against a mapped project (and its ground truth, when there is one).

- class_coverage:   per model class, instances in the project, accuracy against ground truth, open reviews
- missing_classes:  ground-truth classes the model does not have (the mapper can never get these right)
- template_fit:     per template, how often each slot is filled on equipment of that type, and what else shows up
- unknown_tokens:   words in point names the name rules don't know, most frequent first
- relation_usage:   relations seen in the project by (source class, relation, target class), vs the templates
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from .db.store import Store
from .knowledge_model import KnowledgeModel
from .scoring.score import GroundTruth


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def hierarchy(km: KnowledgeModel) -> list[tuple[str, int]]:
    """Model classes in depth-first order with their depth, children sorted by name."""
    kids = defaultdict(list)
    for c, info in km.classes.items():
        kids[info.subset_parent].append(c)
    out = []

    def walk(c: str, depth: int):
        out.append((c, depth))
        for k in sorted(kids[c]):
            walk(k, depth + 1)

    for root in sorted(kids[None], key=lambda c: (km.classes[c].kind != "equipment", km.classes[c].kind, c)):
        walk(root, 0)
    return out


def _true_classes(store: Store, project: str, gt: GroundTruth | None) -> dict[str, str]:
    """Point node id -> ground-truth class (labelled points only)."""
    if gt is None:
        return {}
    out = {}
    for n in store.nodes(project, "point"):
        pid = gt.key[json.loads(n["attrs"])["source_id"]]["point_id"]
        if cls := gt.points[pid]["brick_class"]:
            out[n["id"]] = cls
    return out


def class_coverage(km: KnowledgeModel, store: Store, project: str, gt: GroundTruth | None = None,
                   accept: float = 0.8) -> list[dict]:
    nodes = store.nodes(project)
    true = _true_classes(store, project, gt)
    predicted = defaultdict(list)
    for n in nodes:
        if n["status"] != "rejected" and n["class"]:
            predicted[n["class"]].append(n)
    true_count = Counter(true.values())
    rows = []
    for c, depth in hierarchy(km):
        info = km.classes[c]
        inst = predicted.get(c, [])
        pts = [n for n in inst if n["kind"] == "point" and n["id"] in true]
        right = sum(1 for n in pts if true[n["id"]] == c)  # predicted c and truly c: precision and recall hits
        rows.append({
            "class": c, "depth": depth, "kind": info.kind, "defined in": "BA extension" if info.source == "ba" else "Brick",
            "group": info.group, "parent": info.subset_parent or "",
            "instances": len(inst),
            "to review": sum(1 for n in inst if n["status"] == "proposed" and n["method"] != "human"
                             and n["confidence"] < accept),
            "human decided": sum(1 for n in inst if n["method"] == "human"),
            "true points": true_count.get(c, 0),
            "precision %": _pct(right, len(pts)),
            "recall %": _pct(right, true_count.get(c, 0)),
            "used by templates": ", ".join(sorted(t.id for t in km.templates.values()
                                                  if t.brick_class == c or any(c in s.classes for s in t.slots))),
        })
    return rows


def class_detail(km: KnowledgeModel, store: Store, project: str, cls: str, gt: GroundTruth | None = None) -> dict:
    """Definition, place in the hierarchy, example instances and (with ground truth) what it gets confused with."""
    from rdflib import RDFS, SKOS
    info = km.classes[cls]
    uri = km.uri(cls)
    chain, c = [], info.subset_parent
    while c:
        chain.append(c)
        c = km.classes[c].subset_parent
    nodes = store.nodes(project)
    said = {n["id"]: n["class"] for n in nodes}
    true = _true_classes(store, project, gt)
    return {
        "definition": str(km.graph.value(uri, SKOS.definition) or km.graph.value(uri, RDFS.comment) or ""),
        "uri": str(uri),
        "ancestors": chain,
        "children": sorted(k for k, i in km.classes.items() if i.subset_parent == cls),
        "examples": sorted({n["label"] for n in nodes if n["class"] == cls})[:12],
        "truly this, mapper said": Counter(said[p] or "(none)" for p, t in true.items() if t == cls and said[p] != cls).most_common(6),
        "mapper said this, truly": Counter(t for p, t in true.items() if said[p] == cls and t != cls).most_common(6),
    }


def missing_classes(km: KnowledgeModel, store: Store, project: str, gt: GroundTruth | None) -> list[dict]:
    """Ground-truth point classes that are not in the model, with how often they occur and what we said instead."""
    true = _true_classes(store, project, gt)
    said = {n["id"]: n["class"] for n in store.nodes(project, "point")}
    names = {n["id"]: n["label"] for n in store.nodes(project, "point")}
    by_cls = defaultdict(list)
    for pid, c in true.items():
        if c not in km.classes:
            by_cls[c].append(pid)
    rows = []
    for c, pids in sorted(by_cls.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        nearest = next((a for a in _brick_ancestors(km, c) if a in km.classes), "")
        rows.append({"class": c, "points": len(pids), "nearest model class": nearest,
                     "mapper said": ", ".join(f"{k} ({v})" for k, v in Counter(said[p] or "(none)" for p in pids).most_common(3)),
                     "example names": ", ".join(sorted({names[p] for p in pids})[:3])})
    return rows


def _brick_ancestors(km: KnowledgeModel, cls: str) -> list[str]:
    """Brick superclasses of a class that may not be in the model, nearest first (by ancestor count)."""
    from rdflib import RDFS, URIRef

    from .knowledge_model import BRICK
    uri = URIRef(BRICK[cls])
    anc = [a for a in km.graph.transitive_objects(uri, RDFS.subClassOf) if a != uri and str(a).startswith(str(BRICK))]
    depth = {a: sum(1 for _ in km.graph.transitive_objects(a, RDFS.subClassOf)) for a in anc}
    return [str(a)[len(str(BRICK)):] for a in sorted(anc, key=lambda a: -depth[a])]


def template_fit(km: KnowledgeModel, store: Store, project: str) -> list[dict]:
    """Per template: instances, per-slot fill rate, required slots missing, extra point classes, size check."""
    points_of = defaultdict(list)
    cls_of = {n["id"]: n["class"] for n in store.nodes(project, "point") if n["status"] != "rejected"}
    for e in store.edges(project, "hasPoint"):
        if e["status"] != "rejected":
            points_of[e["src"]].append(cls_of.get(e["dst"]))
    equip = [n for n in store.nodes(project, "equipment") if n["status"] != "rejected"]

    def fits(c, slot):
        return bool(c) and any(km.is_a(c, sc) or km.is_a(sc, c) for sc in slot.classes)

    out = []
    for t in km.templates.values():
        inst = [n for n in equip if json.loads(n["attrs"]).get("template") == t.id or n["class"] == t.brick_class]
        slots, extra, missing_req, small, big = [], Counter(), 0, 0, 0
        filled = {s.role: 0 for s in t.slots}
        for n in inst:
            classes = points_of.get(n["id"], [])
            for s in t.slots:
                filled[s.role] += any(fits(c, s) for c in classes)
            missing_req += any(not any(fits(c, s) for c in classes) for s in t.slots if s.required)
            extra.update(c or "(no class)" for c in classes if not any(fits(c, s) for s in t.slots))
            small += len(classes) < t.point_count[0]
            big += len(classes) > t.point_count[1]
        for s in t.slots:
            slots.append({"role": s.role, "required": s.required, "filled %": _pct(filled[s.role], len(inst)),
                          "filled": filled[s.role], "classes": ", ".join(s.classes)})
        out.append({"template": t.id, "class": t.brick_class, "description": t.description,
                    "instances": len(inst), "missing a required point": missing_req,
                    "fewer points than expected": small, "more points than expected": big,
                    "expected points": f"{t.point_count[0]}–{t.point_count[1]}",
                    "slots": slots, "extra classes": extra.most_common(15),
                    "relations": [{"rel": r.rel, "target": r.target, "medium": r.medium, "required": r.required}
                                  for r in t.relations]})
    return out


def unknown_tokens(store: Store, project: str, accept: float = 0.8) -> list[dict]:
    """Words in point names the name rules don't know, with how many points they touch."""
    seen = defaultdict(list)
    for n in store.nodes(project, "point"):
        for tok in json.loads(n["attrs"]).get("unknown_tokens", []):
            seen[tok].append(n)
    rows = []
    for tok, ns in sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        rows.append({"token": tok, "points": len(ns),
                     "below accept": sum(1 for n in ns if n["confidence"] < accept),
                     "classes given": ", ".join(f"{k} ({v})" for k, v in Counter(n["class"] or "(none)" for n in ns).most_common(3)),
                     "example names": ", ".join(sorted({n["label"] for n in ns})[:4])})
    return rows


def relation_usage(km: KnowledgeModel, store: Store, project: str) -> list[dict]:
    """Relations in the project by (source class, relation, target class), and whether a template expects them."""
    cls = {n["id"]: n["class"] or "(none)" for n in store.nodes(project)}
    expected = set()
    for t in km.templates.values():
        for r in t.relations:
            tgt = km.templates[r.target].brick_class
            # templates say "X isFedBy Y"; the graph stores the inverse "Y feeds X"
            expected.add((tgt, "feeds", t.brick_class) if r.rel == "isFedBy" else (t.brick_class, r.rel, tgt))
    seen = Counter()
    methods = defaultdict(Counter)
    for e in store.edges(project):
        if e["status"] == "rejected" or e["rel"] == "hasPoint":
            continue
        key = (cls.get(e["src"], "?"), e["rel"], cls.get(e["dst"], "?"))
        seen[key] += 1
        methods[key][e["method"]] += 1
    rows = [{"source class": s, "relation": r, "target class": d, "links": n,
             "methods": ", ".join(f"{m} ({k})" for m, k in methods[(s, r, d)].most_common()),
             "expected by a template": (s, r, d) in expected}
            for (s, r, d), n in seen.most_common()]
    rows += [{"source class": s, "relation": r, "target class": d, "links": 0, "methods": "",
              "expected by a template": True} for (s, r, d) in sorted(expected) if (s, r, d) not in seen]
    return rows


def convention_entries(km: KnowledgeModel, store: Store, project: str, layers) -> list[dict]:
    """One row per convention entry: which layer it comes from, whether it overrides the knowledge model
    or an earlier layer, and how many nodes of the project name it in their provenance."""
    from .conventions import layer_entries

    used = Counter(c for n in store.nodes(project) for c in json.loads(n["attrs"]).get("convention", []))
    seen_abbr: dict[str, str] = {}
    rows = []
    for layer, e in ((lay, x) for lay in layers for x in layer_entries([lay])):
        effect = "adds"
        if e["kind"] == "abbreviations":
            key = e["key"].lower()
            if key in seen_abbr:
                effect = f"overrides {seen_abbr[key]}"
            elif key in km.name_rules.abbreviations or key in km.name_rules.vocabulary:
                effect = "overrides knowledge model"
            seen_abbr[key] = layer.scope
            origin = f"{layer.scope}:abbreviations.{key}"
            n = used[origin]
        else:
            # entries of one kind are numbered in file order, matching the origins the mapper records
            same = [x for x in layer_entries([layer]) if x["kind"] == e["kind"]
                    and (e["kind"] != "equipment_patterns" or x["key"] == e["key"])]
            idx = same.index(e)
            origin = (f"{layer.scope}:equipment_patterns.{e['key']}[{idx}]" if e["kind"] == "equipment_patterns"
                      else f"{layer.scope}:{e['kind']}[{idx}]")
            n = used[origin]
        rows.append({"layer": layer.scope, "kind": e["kind"], "entry": e["key"], "value": str(e["value"]),
                     "effect": effect, "points here": n, "origin": origin})
    return rows
