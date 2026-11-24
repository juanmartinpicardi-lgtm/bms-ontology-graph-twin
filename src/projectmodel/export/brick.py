"""Project graph (SQLite nodes and edges) -> an rdflib Graph in Brick terms, with provenance.

Terms come from the knowledge model, never from the store's spelling alone:
    - a Brick class of the subset         -> brick:<Class>
    - a class of the BA extension         -> ba:<Class>
    - a location (Floor, Room, HVAC_Zone…) -> the rec: class that replaces it in Brick 1.4 (W1: rec:Level, rec:Room…)
    - a relation of the subset             -> brick:<rel>;  a relation of the extension -> ba:<rel> (serves, drives…)
    - a point's unit, where its source spelling names one QUDT unit (W4) -> brick:hasUnit unit:<QUDT id>
A class or relation the knowledge model doesn't declare is still written (every fact the store holds is exported),
under the pm-undeclared: namespace, and listed in `Export.summary["undeclared"]`, so nothing passes as Brick that
isn't.

What is exported: confirmed rows; with include_proposed, proposed rows too. Rejected rows never. An edge is written
only when both its ends are; the others are counted, per relation, in `summary["edges_left_out"]` (on Alpha most
confirmed hasPoint edges end on a point whose class is still proposed).

Provenance: reified statements, in the same Turtle file.
    Each node carries its own provenance (pm:method, pm:confidence, pm:status…) on its IRI: the node is the thing the
    row describes, so nothing needs reifying. Each edge gets one rdf:Statement (rdf:subject / rdf:predicate /
    rdf:object, the standard RDF 1.1 reification vocabulary) carrying the same annotations.
    Why reification and not a separate provenance graph: one plain Turtle file holds the facts and where each one
    comes from, so a receiver needs no TriG or named-graph support and can't get the facts without their provenance;
    the annotations sit next to an exact copy of the triple they describe; and RDF-star, the neater option, is not
    supported by rdflib's Turtle serializer or by the SHACL engines. A Brick consumer that ignores pm: and
    rdf:Statement sees plain Brick. The facts and the provenance are still kept as two in-memory graphs
    (`Export.graph`, `Export.prov`) so SHACL runs on the facts alone.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

import rdflib
from rdflib.namespace import RDF, RDFS, XSD

from ..db.store import Store
from ..knowledge_model import BA, BRICK, REC, KnowledgeModel

ROOT = Path(__file__).resolve().parents[3]
PM = rdflib.Namespace("urn:projectmodel:prov#")  # provenance vocabulary of this app
UNDECLARED = rdflib.Namespace("urn:projectmodel:undeclared#")  # terms the knowledge model doesn't declare
UNIT = rdflib.Namespace("http://qudt.org/vocab/unit/")  # QUDT units, as Brick uses them (brick:hasUnit unit:DEG_F)
PROVENANCE = ("source", "source_file", "source_ref", "method", "confidence", "status", "confirmed_by", "revision")
PM_TERM = {"source": PM.source, "source_file": PM.sourceFile, "source_ref": PM.sourceRef, "method": PM.method,
           "confidence": PM.confidence, "status": PM.status, "confirmed_by": PM.confirmedBy,
           "revision": PM.revision}


def base(project: str) -> rdflib.Namespace:
    """The namespace of one project's instances."""
    return rdflib.Namespace(f"urn:projectmodel:kg:{quote(project, safe='')}/")


def node_uri(project: str, node_id: str) -> rdflib.URIRef:
    return base(project)[quote(node_id, safe="")]


def class_uri(km: KnowledgeModel, cls: str) -> rdflib.URIRef | None:
    """The IRI the export writes for a knowledge-model class; None if the model doesn't declare it."""
    info = km.classes.get(cls)
    if info is None:
        return None
    if info.replaced_by.startswith("rec:"):
        return REC[info.replaced_by[4:]]
    return BA[cls] if info.source == "ba" else BRICK[cls]


def relation_uri(km: KnowledgeModel, rel: str) -> rdflib.URIRef | None:
    if rel in km.ba_relations:
        return BA[rel]
    if rel in km.relations:
        return BRICK[rel]
    return None


def _relative(path: str) -> str:
    """A source file under the repo as a repo-relative path (no machine paths in an export)."""
    if not Path(path).is_absolute():
        return path
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return path


@dataclass
class Export:
    project: str
    include_proposed: bool
    graph: rdflib.Graph  # the facts, in Brick terms: what SHACL checks
    prov: rdflib.Graph  # provenance of every node and edge
    summary: dict = field(default_factory=dict)

    def turtle(self) -> str:
        return (self.graph + self.prov).serialize(format="turtle")

    def write(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        g = self.graph + self.prov
        for prefix, ns in self.graph.namespaces():
            g.bind(prefix, ns, override=True)
        g.serialize(destination=path, format="turtle")
        return path


def _bind(g: rdflib.Graph, project: str) -> None:
    g.bind("brick", BRICK)
    g.bind("ba", BA)
    g.bind("rec", REC)
    g.bind("pm", PM)
    g.bind("undeclared", UNDECLARED)
    g.bind("unit", UNIT)
    g.bind("kg", base(project))


def _annotate(prov: rdflib.Graph, subject, row) -> None:
    for col in PROVENANCE:
        value = row[col]
        if value is None or value == "":
            continue
        if col == "source_file":
            value = _relative(value)
        literal = rdflib.Literal(float(value), datatype=XSD.decimal) if col == "confidence" else \
            rdflib.Literal(int(value)) if col == "revision" else rdflib.Literal(value)
        prov.add((subject, PM_TERM[col], literal))


def export_project(store: Store, project: str, km: KnowledgeModel, include_proposed: bool = False) -> Export:
    """Build the Brick graph of one project from the store. Reads only."""
    statuses = ("confirmed", "proposed") if include_proposed else ("confirmed",)
    g, prov = rdflib.Graph(), rdflib.Graph()
    _bind(g, project)
    _bind(prov, project)
    undeclared: dict[str, set] = {"classes": set(), "relations": set()}
    nodes_by_status: Counter = Counter()
    nodes_by_kind: Counter = Counter()
    units: Counter = Counter()
    exported: set[str] = set()
    for row in store.nodes(project):
        if row["status"] not in statuses:
            continue
        s = node_uri(project, row["id"])
        exported.add(row["id"])
        nodes_by_status[row["status"]] += 1
        nodes_by_kind[row["kind"]] += 1
        g.add((s, RDFS.label, rdflib.Literal(row["label"])))
        if row["class"]:
            c = class_uri(km, row["class"])
            if c is None:
                undeclared["classes"].add(row["class"])
                c = UNDECLARED[row["class"]]
            g.add((s, RDF.type, c))
        attrs = json.loads(row["attrs"] or "{}")
        if str(attrs.get("unit") or "").startswith("unit:"):  # a QUDT id (W4, units.yaml); none when ambiguous
            g.add((s, BRICK.hasUnit, UNIT[attrs["unit"][5:]]))
            units[row["kind"]] += 1
        prov.add((s, PM.id, rdflib.Literal(row["id"])))
        prov.add((s, PM.kind, rdflib.Literal(row["kind"])))
        if attrs.get("units"):  # the unit as the source wrote it
            prov.add((s, PM.unitText, rdflib.Literal(str(attrs["units"]))))
        _annotate(prov, s, row)
    edges_by_rel: Counter = Counter()
    edges_by_status: Counter = Counter()
    left_out: Counter = Counter()
    for row in store.edges(project):
        if row["status"] not in statuses:
            continue
        if row["src"] not in exported or row["dst"] not in exported:
            left_out[row["rel"]] += 1
            continue
        p = relation_uri(km, row["rel"])
        if p is None:
            undeclared["relations"].add(row["rel"])
            p = UNDECLARED[row["rel"]]
        s, o = node_uri(project, row["src"]), node_uri(project, row["dst"])
        g.add((s, p, o))
        key = hashlib.sha1(f"{row['src']}\x1f{row['rel']}\x1f{row['dst']}".encode()).hexdigest()[:20]
        st = base(project)[f"fact-{key}"]
        prov.add((st, RDF.type, RDF.Statement))
        prov.add((st, RDF.subject, s))
        prov.add((st, RDF.predicate, p))
        prov.add((st, RDF.object, o))
        _annotate(prov, st, row)
        attrs = json.loads(row["attrs"] or "{}")
        if attrs.get("medium"):
            prov.add((st, PM.medium, rdflib.Literal(attrs["medium"])))
        edges_by_rel[row["rel"]] += 1
        edges_by_status[row["status"]] += 1
    summary = {
        "project": project,
        "scope": "confirmed + proposed" if include_proposed else "confirmed",
        "nodes": len(exported), "edges": sum(edges_by_rel.values()),
        "nodes_by_kind": dict(sorted(nodes_by_kind.items())), "nodes_by_status": dict(nodes_by_status),
        "edges_by_relation": dict(sorted(edges_by_rel.items())), "edges_by_status": dict(edges_by_status),
        "edges_left_out": dict(sorted(left_out.items())),
        "with_unit": dict(units),
        "undeclared": {k: sorted(v) for k, v in undeclared.items()},
        "triples": {"facts": len(g), "provenance": len(prov)},
    }
    return Export(project, include_proposed, g, prov, summary)


def load_export(path_or_turtle: Path | str) -> dict:
    """Read an export back. Returns its nodes (store id -> class IRI or None) and edges ((src id, relation IRI,
    dst id)), recovered from the provenance annotations and checked against the facts: an edge counts only if its
    triple is in the file."""
    g = rdflib.Graph()
    if isinstance(path_or_turtle, Path) or (isinstance(path_or_turtle, str) and "\n" not in path_or_turtle
                                            and Path(path_or_turtle).exists()):
        g.parse(path_or_turtle, format="turtle")
    else:
        g.parse(data=path_or_turtle, format="turtle")
    ids = {s: str(o) for s, o in g.subject_objects(PM.id)}
    nodes = {i: (str(g.value(s, RDF.type)) if g.value(s, RDF.type) else None) for s, i in ids.items()}
    edges, missing = [], 0
    for st in g.subjects(RDF.type, RDF.Statement):
        s, p, o = g.value(st, RDF.subject), g.value(st, RDF.predicate), g.value(st, RDF.object)
        if (s, p, o) in g and s in ids and o in ids:
            edges.append((ids[s], str(p), ids[o]))
        else:
            missing += 1
    by_rel: dict[str, int] = defaultdict(int)
    for _, p, _ in edges:
        by_rel[p.split("#")[-1]] += 1
    return {"nodes": nodes, "edges": edges, "statements_without_fact": missing, "edges_by_relation": dict(by_rel),
            "ids_roundtrip": all(unquote(str(s).rsplit("/", 1)[-1]) == i for s, i in ids.items())}
