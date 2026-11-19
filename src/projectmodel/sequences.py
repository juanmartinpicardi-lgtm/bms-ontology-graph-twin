"""Sequences of operation: a project document (data/documents/<site>/sequences.yaml) linked to the knowledge graph.

The document is a source like the BMS export, but it says how the building is meant to behave (intent), not what it
has. Each [words](ref) link in its text is resolved to a node of the project's graph:
  ok        the node exists, with the class the sequence implies
  conflict  the node exists, but the graph classes it differently from what the sequence implies (`expect`)
  gap       the sequence needs it, the graph does not have it
Loops, links and values are the behaviour facts the document adds on top of the graph (control loops, interlocks,
resets, requests, modes, intended values). store_behaviour() writes the loops and links into the graph as edges
between existing nodes (method document, the document as source, attrs.intent = true): a loop becomes
setpoint -drives-> output and measured -feedback-> output. A link with a gap end is not stored, only counted.
Intended values stay in the document. Nothing is ever written back to the document.

Read by the Sequences page (app/sequences.html) and by the Complete graph page's behaviour facts.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import yaml

from .db.store import Edge, Store
from .fonts import with_fonts
from .equipment_view import DATA_SLOT, equipment_payload, load_anchors, render_template
from .knowledge_model import KnowledgeModel
from .tree import build_tree, provenance

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "data/documents"
APP = Path(__file__).resolve().parent / "app"
CONTROL = ("drives", "feedback", "requires", "resets", "requests", "switches")
GRAPH = ("feeds", "hasPart", "hasPoint")


def document_path(site: str) -> Path:
    return DOCS / site / "sequences.yaml"


def load_document(site: str) -> dict | None:
    p = document_path(site)
    return yaml.safe_load(p.read_text()) if p.exists() else None


def parse_text(text: str) -> list[dict]:
    """A paragraph as segments: {"t": text} or {"t": words, "ref": ref}. Refs may hold parentheses ("Status (CC)")."""
    out, i = [], 0
    text = re.sub(r"\s+", " ", text).strip()
    while (s := text.find("[", i)) != -1:
        e = text.find("](", s)
        if e == -1:
            break
        depth, j = 1, e + 2
        while j < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        if s > i:
            out.append({"t": text[i:s]})
        out.append({"t": text[s + 1:e], "ref": text[e + 2:j - 1].strip()})
        i = j
    if i < len(text):
        out.append({"t": text[i:]})
    return out


def _refs(seq: dict) -> list[str]:
    """Every ref a sequence uses, in first-use order."""
    refs = [g["ref"] for para in seq.get("text", []) for g in parse_text(para) if "ref" in g]
    for lp in seq.get("loops", []):
        refs += [r for r in (lp.get("setpoint"), lp.get("measured")) if r] + list(lp.get("outputs", []))
    for a, b, _ in seq.get("links", []):
        refs += [a, b]
    refs += list(seq.get("values", {}))
    for st in seq.get("steps", []):
        refs += list(st.get("lit", [])) + [r for lk in st.get("links", []) for r in lk[:2]]
        refs += [r for r in (st.get("show"), st.get("focus")) if r]
    return list(dict.fromkeys(refs))


class Resolver:
    def __init__(self, store: Store, km: KnowledgeModel, project: str, anchors: dict | None = None):
        self.store, self.km, self.project = store, km, project
        self.anchors = load_anchors() if anchors is None else anchors
        self.tree = build_tree(store, project)
        self.payloads: dict[str, dict] = {}  # equipment id -> 3D payload (templated equipment only)

    def payload(self, eid: str) -> dict | None:
        n = self.tree.by_id.get(eid)
        if eid not in self.payloads and n is not None and (n.attrs.get("template") or "") in self.anchors:
            self.payloads[eid] = equipment_payload(self.store, self.project, eid, self.km, self.anchors) | {
                "embed": True, "tools": True}  # embedded, but the view buttons stay
        return self.payloads.get(eid)

    def points_of(self, eid: str) -> dict[str, dict]:
        """Point id -> {label, cls, role, confidence}: the 3D payload's points (sub-equipment included, with slot
        roles) when the equipment has a model, else the points directly on it."""
        if p := self.payload(eid):
            return {i: {"label": x["label"], "cls": x["cls"], "role": x["role"], "confidence": x["confidence"] or 0}
                    for i, x in p["points"].items()}
        n = self.tree.by_id[eid]
        return {p.id: {"label": p.label, "cls": p.cls, "role": None, "confidence": p.prov.get("confidence") or 0}
                for p in n.points}

    def node(self, nid: str, col: str) -> dict:
        n = self.tree.by_id[nid]
        out = {"id": nid, "kind": n.kind, "label": n.label, "cls": n.cls, "col": col, "prov": n.prov,
               "path": n.attrs.get("path")}
        if n.kind == "equipment":
            info = self.km.classes.get(n.cls or "")
            out |= {"system": bool(info and info.kind == "system"), "template": n.attrs.get("template"),
                    "points": len(n.points), "model": bool(self.payload(nid))}
        return out

    def resolve(self, ref: str, bind: dict, expect: dict) -> dict:
        if ref.startswith("gap:"):
            return {"ref": ref, "status": "gap", "label": ref[4:], "col": None}
        alias, sep, rest = re.match(r"^([A-Za-z0-9_]+)([.:]?)(.*)$", ref).groups()
        if alias not in bind:
            raise KeyError(f"unknown alias {alias!r} in {ref!r}")
        eid = bind[alias]
        if eid not in self.tree.by_id:
            raise KeyError(f"{eid} is not in {self.project}")
        if not sep:
            return {"ref": ref, "status": "ok", "node": eid, "col": alias}
        pts = self.points_of(eid)
        if sep == ".":
            hits = sorted((i for i, p in pts.items() if p["role"] == rest), key=lambda i: -pts[i]["confidence"])
            missing = f"{rest.replace('_', ' ')} (expected on {self.tree.by_id[eid].label})"
        else:
            hits = sorted((i for i, p in pts.items() if p["label"] == rest), key=lambda i: -pts[i]["confidence"])
            missing = f"{rest} (no point with this name on {self.tree.by_id[eid].label})"
        if not hits:
            return {"ref": ref, "status": "gap", "label": missing, "col": alias}
        out = {"ref": ref, "status": "ok", "node": hits[0], "col": alias}
        if (want := expect.get(ref)) and not self._fits(pts[hits[0]]["cls"], want):
            out |= {"status": "conflict", "expected": want}
        return out

    def _fits(self, cls: str | None, want: str) -> bool:
        return bool(cls) and (cls == want or (cls in self.km.classes and want in self.km.classes
                                              and self.km.is_a(cls, want)))

    def edge(self, src: str, dst: str, rel: str) -> dict | None:
        for e in self.store.edges(self.project, rel):
            if e["src"] == src and e["dst"] == dst and e["status"] != "rejected":
                return provenance(e)
        return None


def sequences_payload(store: Store, km: KnowledgeModel, project: str, doc: dict | None = None,
                      anchors: dict | None = None) -> dict | None:
    """The project's sequences with every link resolved against its graph, plus the 3D payloads they show."""
    site = project.split("/")[0]
    doc = load_document(site) if doc is None else doc
    if doc is None:
        return None
    r = Resolver(store, km, project, anchors)
    nodes, sequences = {}, []
    for seq in doc["sequences"]:
        bind, expect = seq["bind"], seq.get("expect", {})
        refs = {ref: r.resolve(ref, bind, expect) for ref in _refs(seq)}
        for x in refs.values():
            if x.get("node") and x["node"] not in nodes:
                nodes[x["node"]] = r.node(x["node"], x["col"])
        # Graph relations a step walks: their provenance, or None when the graph lacks the link.
        graph_links = {}
        for st in seq.get("steps", []):
            for a, b, kind in st.get("links", []):
                if kind in GRAPH and refs[a].get("node") and refs[b].get("node"):
                    graph_links[f"{a}|{b}|{kind}"] = r.edge(refs[a]["node"], refs[b]["node"], kind)
                elif kind not in CONTROL + GRAPH:
                    raise ValueError(f"{seq['id']}: unknown link kind {kind!r}")
        for a, b, kind in seq.get("links", []):
            if kind not in CONTROL:
                raise ValueError(f"{seq['id']}: unknown control kind {kind!r}")
        for alias in bind:
            r.payload(bind[alias])
        sequences.append({
            "id": seq["id"], "title": seq["title"], "scope": seq.get("scope", ""),
            "bind": bind, "columns": list(bind),
            "paras": [parse_text(p) for p in seq.get("text", [])],
            "refs": refs, "loops": seq.get("loops", []), "links": seq.get("links", []),
            "values": seq.get("values", {}), "steps": seq.get("steps", []), "graph_links": graph_links,
            "models": {a: e for a, e in bind.items() if e in r.payloads},
        })
    return {"document": doc.get("document", ""), "status": doc.get("status", ""), "revision": doc.get("revision"),
            "source_file": str(document_path(site).relative_to(ROOT)), "project": project,
            "sequences": sequences, "nodes": nodes, "equipment": r.payloads}


def behaviour(payload: dict | None) -> dict:
    """What the document adds and what it found, for the Complete graph page: per kind of behaviour fact,
    (resolved, total) refs; plus findings."""
    out = {k: [0, 0] for k in ("loops", "interlocks", "modes", "values")}
    findings = Counter()
    for seq in (payload or {}).get("sequences", []):
        refs = seq["refs"]
        ok = lambda ref: refs[ref]["status"] != "gap"  # noqa: E731
        for lp in seq["loops"]:
            ends = [x for x in (lp.get("setpoint"), lp.get("measured")) if x] + list(lp.get("outputs", []))
            out["loops"][0] += sum(map(ok, ends))
            out["loops"][1] += len(ends)
        for a, b, kind in seq["links"]:
            key = "modes" if kind == "switches" else "interlocks"
            out[key][0] += ok(a) + ok(b)
            out[key][1] += 2
        out["values"][0] += sum(map(ok, seq["values"]))
        out["values"][1] += len(seq["values"])
        findings.update(x["status"] for x in refs.values())
    return {"counts": out, "findings": dict(findings), "sequences": len((payload or {}).get("sequences", []))}


def behaviour_edges(payload: dict) -> tuple[list[Edge], list[dict]]:
    """The loops and links of every sequence as graph edges between resolved nodes, plus the ones that could not
    be stored because an end is a gap. Confidence: 1.0 when both ends are named (equipment or point label),
    0.8 when an end was found through a template slot role. The same fact in two sequences is one edge."""
    found: dict[tuple, Edge] = {}
    skipped = []
    for seq in payload["sequences"]:
        refs = seq["refs"]
        facts = []
        for lp in seq["loops"]:
            for out in lp.get("outputs", []):
                facts += [(lp.get("setpoint"), out, "drives", f"loop {lp['name']}", lp["name"]),
                          (lp.get("measured"), out, "feedback", f"loop {lp['name']}", lp["name"])]
        facts += [(a, b, kind, f"link {i + 1}", None) for i, (a, b, kind) in enumerate(seq["links"])]
        for a, b, kind, where, loop in facts:
            if not a or not b:
                continue
            ra, rb = refs[a], refs[b]
            if ra["status"] == "gap" or rb["status"] == "gap":
                skipped.append({"sequence": seq["id"], "from": a, "to": b, "rel": kind, "where": where})
                continue
            key = (ra["node"], kind, rb["node"])
            if key in found:
                found[key].attrs["sequences"].append(seq["id"])
                continue
            attrs = {"intent": True, "sequences": [seq["id"]], "refs": [a, b]}
            if loop:
                attrs["loop"] = loop
            if conflicts := [r for r in (a, b) if refs[r]["status"] == "conflict"]:
                attrs["conflict"] = conflicts
            conf = 0.8 if any("." in r.split(":")[0] for r in (a, b)) else 1.0
            found[key] = Edge(ra["node"], kind, rb["node"], payload["source_file"],
                              f"sequence {seq['id']} · {where}", "document", conf, attrs)
    return list(found.values()), skipped


def store_behaviour(store: Store, km: KnowledgeModel, project: str, doc: dict | None = None) -> dict | None:
    """Write the project's sequences' loops and links into the graph as document edges, replacing the ones the
    same document wrote before. Runs after the mapper, on the latest revision. None when there is no document."""
    try:
        payload = sequences_payload(store, km, project, doc)  # 3D anchors give the template slot roles
    except KeyError as e:  # the document binds equipment this graph does not have (e.g. a names-only export)
        return {"stored": {}, "edges": 0, "skipped": [], "source_file": None, "unbound": str(e.args[0])}
    if payload is None:
        return None
    edges, skipped = behaviour_edges(payload)
    revision = store.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM runs WHERE project = ?",
                                  (project,)).fetchone()[0]
    store.replace_document_edges(project, payload["source_file"], revision, edges)
    return {"stored": dict(Counter(e.rel for e in edges)), "edges": len(edges), "skipped": skipped,
            "source_file": payload["source_file"]}


def render_html(payload: dict, theme: str | None = None) -> str:
    data = dict(payload, viewer=render_template(theme), slot=DATA_SLOT)
    html = (APP / "sequences.html").read_text()
    html = html.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    if theme in ("light", "dark"):
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return with_fonts(html)
