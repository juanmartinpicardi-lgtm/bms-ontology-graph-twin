"""Data for the 3D graph view: one project's knowledge graph, optionally joined to the knowledge model.

Instance layer: equipment and points (nodes) with hasPart / hasPoint / feeds (links).
Model layer: the knowledge-model classes those instances use, plus their ancestors in the model,
linked instance -type-> class and class -subClassOf-> parent class.
Every instance node and link carries its provenance; class nodes say where the class is defined.
Rejected links are left out (as in the tree); rejected nodes stay, marked by their status.
Instance nodes and links carry `notes` (count of active notes); the notes themselves are in
payload["notes"], keyed by node id or "src|rel|dst", for the read-only details panel.
"""

from __future__ import annotations

import json
from pathlib import Path

from .db.store import Store
from .knowledge_model import KnowledgeModel
from .notes import edge_id, notes_by_project
from .tree import provenance

TEMPLATE = Path(__file__).resolve().parent / "app" / "graph3d.html"
ATTR_KEYS = ("alternatives", "words", "unknown_tokens", "path", "template", "grouping", "evidence", "points")


def add_model_layer(nodes: list[dict], links: list[dict], km: KnowledgeModel) -> None:
    """Add the knowledge-model classes the instance nodes use, their ancestors, and the type / subClassOf links."""
    used = {n["cls"] for n in nodes if n["cls"] in km.classes}
    wanted = set()
    for c in used:
        while c and c not in wanted:
            wanted.add(c)
            c = km.classes[c].subset_parent
    for c in sorted(wanted):
        info = km.classes[c]
        nodes.append({"id": f"cls:{c}", "label": c, "kind": "class", "cls": c, "layer": "model",
                      "prov": {"source_file": "knowledge_model/" + ("ba_extension.ttl" if info.source == "ba"
                                                                   else "brick_subset.yaml"),
                               "source_ref": info.group, "method": "model", "class_kind": info.kind,
                               "defined_in": "BA extension" if info.source == "ba" else f"Brick {km.brick_version}"},
                      "attrs": {"instances": 0}})
        if info.subset_parent:
            links.append({"source": f"cls:{c}", "target": f"cls:{info.subset_parent}", "rel": "subClassOf",
                          "prov": {"method": "model", "source_file": "Brick / BA extension"}})
    count = {}
    for n in nodes:
        if n["layer"] == "instance" and n["cls"] in wanted:
            links.append({"source": n["id"], "target": f"cls:{n['cls']}", "rel": "type", "prov": n["prov"]})
            count[n["cls"]] = count.get(n["cls"], 0) + 1
    for n in nodes:
        if n["kind"] == "class":
            n["attrs"]["instances"] = count.get(n["cls"], 0)


def graph_payload(store: Store, project: str, km: KnowledgeModel | None = None) -> dict:
    nodes, links = [], []
    notes: dict[str, list[dict]] = {}
    for n in notes_by_project(store, project):
        if n["target_kind"] != "project":
            notes.setdefault(n["target_id"], []).append(
                {k: n[k] for k in ("id", "topic", "body", "author", "source", "updated_at")})
    rows = store.nodes(project)
    ids = {r["id"] for r in rows}
    for r in rows:
        attrs = json.loads(r["attrs"])
        nodes.append({"id": r["id"], "label": r["label"], "kind": r["kind"], "cls": r["class"],
                      "layer": "instance", "prov": provenance(r), "notes": len(notes.get(r["id"], [])),
                      "attrs": {k: attrs[k] for k in ATTR_KEYS if k in attrs}})
    for e in store.edges(project):
        if e["status"] == "rejected" or e["src"] not in ids or e["dst"] not in ids:
            continue
        links.append({"source": e["src"], "target": e["dst"], "rel": e["rel"], "prov": provenance(e),
                      "notes": len(notes.get(edge_id(e["src"], e["rel"], e["dst"]), []))})

    if km is not None:
        add_model_layer(nodes, links, km)

    kinds = {}
    for n in nodes:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    rels = {}
    for link in links:
        rels[link["rel"]] = rels.get(link["rel"], 0) + 1
    return {"project": project, "nodes": nodes, "links": links, "counts": {"nodes": kinds, "links": rels},
            "notes": notes}


def render_html(payload: dict, theme: str | None = None) -> str:
    """The 3D viewer page with the payload embedded. `theme` ("light" / "dark") pins the colours to the
    host app's theme; without it the page follows the system setting."""
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    controls = (TEMPLATE.parent / "viewer_controls.js").read_text()
    html = TEMPLATE.read_text().replace("/*__CONTROLS__*/", controls).replace("/*__DATA__*/null", data)
    if theme in ("light", "dark"):
        html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">', 1)
    return html
