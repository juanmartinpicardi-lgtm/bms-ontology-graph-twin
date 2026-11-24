"""SHACL on an export: Brick 1.4.4's own shapes, and our building rules from knowledge_model/shapes/*.ttl.

    report = validate(export, km)    # a dict, written as reports/shacl/<project>.json by scripts/export_brick.py

The data graph is the export's facts plus the knowledge model's ontology (Brick 1.4.4 + BA extension), the way
brickschema validates a model: Brick's shapes travel inside Brick, and sh:class follows rdfs:subClassOf. The engine
is brickschema's (shifty when installed, else pyshacl). Never a model: validation is rules only (plan §6.2, stage 11).

The report, per rule (one node shape of ours, or one Brick shape that fired):
    targets  how many of the project's nodes the rule applies to
    failed   how many of them fail it (a node failing two constraints of one rule counts once)
    passed   targets - failed
    failing  the first failing nodes: id, label, class, and the engine's message
Results about nodes outside the project (the ontology itself) are counted apart, never mixed in.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path

import rdflib
from brickschema import shacl as brick_shacl
from rdflib.graph import ReadOnlyGraphAggregate
from rdflib.namespace import OWL, RDF, RDFS, SH

from ..knowledge_model import KnowledgeModel
from ..units import load as load_units
from .brick import PM, UNIT, Export, base

ROOT = Path(__file__).resolve().parents[3]
SHAPES_DIR = ROOT / "knowledge_model" / "shapes"
OURS = "urn:projectmodel:shapes#"
FIRST_FAILING = 25  # failing nodes kept per rule in the report
QUDT = rdflib.Namespace("http://qudt.org/schema/qudt/")
BSH = rdflib.Namespace("https://brickschema.org/schema/BrickShape#")
KG_IRI = re.compile(r"<(urn:projectmodel:kg:[^>]+)>")
ANY_IRI = re.compile(r"<([a-z]+:[^>\s]+)>")
BNODE = re.compile(r"_:[A-Za-z0-9]+")
SEVERITY = {SH.Violation: "violation", SH.Warning: "warning", SH.Info: "info"}


NAMED = "urn:projectmodel:shape-node:"
_NAMED: dict[int, rdflib.Graph] = {}


def _name_shapes(g: rdflib.Graph) -> rdflib.Graph:
    """A copy of `g` where every blank-node shape (a property shape, an anonymous node shape) gets an IRI.

    An engine may hand results back with fresh blank-node labels (shifty does), and a property shape is usually a
    blank node: named, every result's sh:sourceShape still finds the rule it belongs to. Only shapes are renamed;
    paths and lists stay blank nodes, so `[ sh:inversePath … ]` keeps its meaning."""
    shapes = {s for s in g.subjects(SH.path, None) if isinstance(s, rdflib.BNode)}
    shapes |= {s for t in (SH.NodeShape, SH.PropertyShape) for s in g.subjects(RDF.type, t)
               if isinstance(s, rdflib.BNode)}
    names = {b: rdflib.URIRef(f"{NAMED}{b}") for b in shapes}
    out = rdflib.Graph()
    for prefix, ns in g.namespaces():
        out.bind(prefix, ns)
    for s_, p_, o_ in g:
        out.add((names.get(s_, s_), p_, names.get(o_, o_)))
    return out


def _ontology(km: KnowledgeModel) -> rdflib.Graph:
    """The knowledge model's ontology (Brick + BA, with Brick's shapes) with its shapes named, made once per model.
    Read only: callers never add to it.

    QUDT itself is not loaded with Brick, so a unit the export writes (unit:DEG_F) would fail Brick's hasUnit shape
    (sh:class qudt:Unit) for lack of a type. The units of knowledge_model/units.yaml are declared qudt:Unit here, as
    QUDT declares them; a unit outside that file still fails."""
    if id(km.graph) not in _NAMED:
        _NAMED.clear()
        g = _name_shapes(km.graph)
        for uid in load_units()["quantity"]:
            g.add((UNIT[uid.split(":", 1)[1]], RDF.type, QUDT.Unit))
        _NAMED[id(km.graph)] = g
    return _NAMED[id(km.graph)]


def load_shapes(shapes_dir: Path = SHAPES_DIR) -> rdflib.Graph:
    g = rdflib.Graph()
    for path in sorted(Path(shapes_dir).glob("*.ttl")):
        g.parse(path, format="turtle")
    return g


def _instances(g: rdflib.Graph, cls) -> set:
    classes = set(g.transitive_subjects(RDFS.subClassOf, cls))
    return {s for c in classes for s in g.subjects(RDF.type, c)}


def _targets(shapes: rdflib.Graph, data: rdflib.Graph, shape) -> set:
    """The focus nodes of a node shape (SHACL §2.1.3 targets), on the data graph."""
    out = set(shapes.objects(shape, SH.targetNode))
    for cls in shapes.objects(shape, SH.targetClass):
        out |= _instances(data, cls)
    if (shape, RDF.type, RDFS.Class) in shapes or (shape, RDF.type, OWL.Class) in shapes:
        out |= _instances(data, shape)  # implicit class target: Brick's class shapes
    for p in shapes.objects(shape, SH.targetSubjectsOf):
        out |= set(data.subjects(p, None))
    for p in shapes.objects(shape, SH.targetObjectsOf):
        out |= {o for o in data.objects(None, p) if not isinstance(o, rdflib.Literal)}
    return out


def _node_shape(shapes: rdflib.Graph, shape):
    """A result's source shape is often a property shape (a blank node): report it under its node shape."""
    seen = set()
    while shape not in seen:
        seen.add(shape)
        parent = next(iter(shapes.subjects(SH.property, shape)), None)
        if parent is None:
            parent = next((p for p in shapes.subjects(SH.node, shape)), None)
        if parent is None:
            return shape
        shape = parent
    return shape


def _short(g: rdflib.Graph, term) -> str:
    if isinstance(term, rdflib.BNode) or str(term).startswith(NAMED):
        return "(anonymous shape)"
    try:
        return g.namespace_manager.normalizeUri(term)
    except Exception:  # noqa: BLE001 - any IRI the manager can't shorten is shown whole
        return str(term)


def _run(engine: str, data: list, shapes: list) -> tuple[bool, rdflib.Graph]:
    conforms, results, _text = brick_shacl.validate(data, shapes, engine=engine)
    return bool(conforms), results


def validate(export: Export, km: KnowledgeModel, shapes: rdflib.Graph | None = None,
             engine: str | None = None) -> dict:
    """Run our building rules and Brick's shapes on an export. Returns the report (see module docstring)."""
    ours = _name_shapes(shapes if shapes is not None else load_shapes())
    onto = _ontology(km)
    engine_used = brick_shacl.resolve(engine)
    t0 = time.perf_counter()
    # Two passes over the same data (the facts plus the ontology, so sh:class follows rdfs:subClassOf):
    #   building rules: our shapes alone, on the graph as the export wrote it. Brick's rules (sh:rule) don't run, so
    #     nothing is inferred from a relation's domain or range: a plant at the end of ba:requires stays a plant and
    #     the rule says so, instead of the plant quietly becoming a point.
    #   Brick: Brick's own shapes and rules, the way brickschema validates a model. The ontology must be passed as the
    #     shapes graph: given an extra shapes graph, shifty stops reading the shapes embedded in the data, and Brick's
    #     shapes would silently not run.
    ok_ours, res_ours = _run(engine_used, [onto, export.graph], [ours])
    ok_brick, res_brick = _run(engine_used, [onto, export.graph], [onto])
    seconds = round(time.perf_counter() - t0, 2)
    data = ReadOnlyGraphAggregate([onto, export.graph])
    all_shapes = ReadOnlyGraphAggregate([onto, ours])  # where a shape is defined: Brick's in the ontology, ours here
    kg = str(base(export.project))
    ids = {s: str(o) for s, o in export.prov.subject_objects(PM.id)}
    names = rdflib.Graph()  # prefixes for the report: the export's, plus Brick's shape namespace
    for prefix, ns in export.graph.namespaces():
        names.bind(prefix, ns, override=True)
    names.bind("bsh", BSH)

    def readable(msg: str) -> str:
        """Engine messages with store ids for the project's nodes, prefixed names for terms, no blank-node labels."""
        msg = KG_IRI.sub(lambda m: ids.get(rdflib.URIRef(m.group(1)), m.group(1)), msg)
        msg = ANY_IRI.sub(lambda m: _short(names, rdflib.URIRef(m.group(1))), msg)
        return BNODE.sub("(an anonymous shape)", msg)

    failing: dict = defaultdict(dict)  # node shape -> focus -> [messages]
    severity: dict = {}
    outside = defaultdict(int)
    for results in (res_ours, res_brick):
        for r in results.subjects(RDF.type, SH.ValidationResult):
            focus = results.value(r, SH.focusNode)
            sev = SEVERITY.get(results.value(r, SH.resultSeverity), "violation")
            if not str(focus).startswith(kg):
                outside[sev] += 1
                continue
            shape = _node_shape(all_shapes, results.value(r, SH.sourceShape))
            msg = readable(str(results.value(r, SH.resultMessage) or ""))
            path = results.value(r, SH.resultPath)
            if path is not None and not isinstance(path, rdflib.BNode):
                msg = f"{msg} [{_short(names, path)}]" if msg else _short(names, path)
            failing[shape].setdefault(focus, [])
            if msg and msg not in failing[shape][focus]:
                failing[shape][focus].append(msg)
            if severity.get(shape) != "violation":  # the worst severity seen for the shape
                severity[shape] = sev

    def node_info(focus) -> dict:
        cls = export.graph.value(focus, RDF.type)
        return {"id": ids.get(focus, str(focus)), "label": str(export.graph.value(focus, RDFS.label) or ""),
                "class": _short(names, cls) if cls is not None else None}

    rules = []
    our_shapes = sorted({s for s in ours.subjects(RDF.type, SH.NodeShape) if str(s).startswith(OURS)}, key=str)
    mine = set(our_shapes)
    for shape in our_shapes + sorted((s for s in failing if s not in mine), key=str):
        targets = {f for f in _targets(all_shapes, data, shape) if str(f).startswith(kg)}
        bad = failing.get(shape, {})
        targets |= set(bad)  # a failing node is a target, whatever our target reading says (Brick infers types)
        rules.append({
            "id": "shape:" + str(shape).split("#")[-1] if shape in mine else _short(names, shape),
            "origin": "building" if shape in mine else "brick",
            "label": str(all_shapes.value(shape, RDFS.label)) if shape in mine else
            f"Brick shape on {_short(names, shape)}",
            "comment": str(ours.value(shape, RDFS.comment) or "") if shape in mine else
            "Brick 1.4.4's own shape, run with Brick's inference rules.",
            "severity": severity.get(shape, "violation"),
            "targets": len(targets), "failed": len(bad), "passed": len(targets) - len(bad),
            "failing": [dict(node_info(f), messages=m) for f, m in
                        sorted(bad.items(), key=lambda kv: ids.get(kv[0], str(kv[0])))[:FIRST_FAILING]],
        })
    building = [r for r in rules if r["origin"] == "building"]
    brick = [r for r in rules if r["origin"] == "brick"]
    count = lambda rs, sev=None: sum(r["failed"] for r in rs if sev is None or r["severity"] == sev)  # noqa: E731
    return {
        "project": export.project, "scope": export.summary["scope"], "engine": engine_used, "seconds": seconds,
        "conforms": not any(r["failed"] and r["severity"] == "violation" for r in rules),
        "engine_conforms": {"building": ok_ours, "brick": ok_brick},
        "export": export.summary,
        "totals": {
            "building_rules": len(building), "building_rules_failing": sum(1 for r in building if r["failed"]),
            "building_failures": count(building),
            "brick_shapes_failing": len(brick), "brick_violations": count(brick, "violation"),
            "brick_warnings": count(brick, "warning") + count(brick, "info"),
            "outside_project": dict(outside),
        },
        "rules": rules,
    }
