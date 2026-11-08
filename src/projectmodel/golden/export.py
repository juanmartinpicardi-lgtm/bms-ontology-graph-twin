"""Build the ground-truth files for one Haystack site.

Outputs (in out_dir):
  points.csv           point -> equipment, point -> Brick class
  equipment.csv        equipment -> Brick class, parent equipment
  equip_relations.csv  equip -> equip (feeds | hasPart), with the Haystack tag it came from
  unmapped.csv         every point/equip that did not get a confident Brick class, with candidates
  issues.csv           structural problems (dangling refs, points without equipment)
  brick.ttl            the same facts as a Brick graph
  summary.json         counts, Brick version, source file hash
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import rdflib
from rdflib.namespace import RDF, RDFS

# rdflib's bundled BRICK namespace is an older Brick release; use the URI of the 1.4 ontology we match against.
BRICK = rdflib.Namespace("https://brickschema.org/schema/Brick#")

from .brick_convert import MAPPED, GENERIC, BrickConverter, BrickMatch
from .load import EQUIP_RELATION_REFS, Entity, load_grid


def raw_name(e: Entity) -> str:
    """The original BMS name when the site provides one, else the display name."""
    return e.custom.get("description") or e.tags.get("dis", "")


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build_site(site: str, src: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta, entities = load_grid(src)
    by_id = {e.id: e for e in entities}
    points = [e for e in entities if e.kind == "point"]
    equips = [e for e in entities if e.kind == "equip"]
    conv = BrickConverter(f"urn:{site}#")

    matches: dict[str, BrickMatch] = {e.id: conv.classify(e) for e in points + equips}
    issues: list[dict] = []
    src_name = str(src)

    def ref_target(e: Entity, tag: str, want: str) -> str:
        """Return the ref value if it resolves to an entity of kind `want`, else log and return ''."""
        target = e.tags.get(tag)
        if not target:
            return ""
        if target not in by_id or by_id[target].kind != want:
            found = by_id[target].kind if target in by_id else "missing"
            issues.append({"entity_id": e.id, "issue": f"{tag} -> {target} is {found}, expected {want}"})
            return ""
        return target

    # Points (weather-station points have no equipment; they are reported, not ground truth)
    point_rows, weather = [], 0
    for p in points:
        if "weatherStationRef" in p.tags and "equipRef" not in p.tags:
            weather += 1
            continue
        m = matches[p.id]
        equip_id = ref_target(p, "equipRef", "equip")
        if not equip_id and "equipRef" not in p.tags:
            issues.append({"entity_id": p.id, "issue": "point has no equipRef"})
        point_rows.append({
            "point_id": p.id, "source_row": p.row, "raw_name": raw_name(p), "dis": p.tags.get("dis", ""),
            "equip_id": equip_id, "equip_dis": by_id[equip_id].tags.get("dis", "") if equip_id else "",
            "haystack_tags": " ".join(p.markers), "kind": p.tags.get("kind", ""), "unit": p.tags.get("unit", ""),
            "brick_class": m.brick_class, "map_status": m.status, "candidates": " ".join(m.candidates),
            "leftover_tags": " ".join(m.leftover),
        })

    equip_rows, rel_rows = [], []
    for q in equips:
        m = matches[q.id]
        parent = ref_target(q, "equipRef", "equip")
        equip_rows.append({
            "equip_id": q.id, "source_row": q.row, "dis": q.tags.get("dis", ""), "parent_equip_id": parent,
            "haystack_tags": " ".join(q.markers), "brick_class": m.brick_class, "map_status": m.status,
            "candidates": " ".join(m.candidates), "leftover_tags": " ".join(m.leftover),
        })
        if parent:
            rel_rows.append({"src": parent, "rel": "hasPart", "dst": q.id, "source_tag": "equipRef"})
        for tag, rel in EQUIP_RELATION_REFS.items():
            upstream = ref_target(q, tag, "equip")
            if upstream:
                rel_rows.append({"src": upstream, "rel": rel, "dst": q.id, "source_tag": tag})

    unmapped_rows = [
        {"entity_id": eid, "entity_kind": by_id[eid].kind, "raw_name": raw_name(by_id[eid]),
         "haystack_tags": " ".join(by_id[eid].markers), "map_status": m.status, "candidates": " ".join(m.candidates)}
        for eid, m in matches.items()
        if m.status != MAPPED and not (eid in by_id and "weatherStationRef" in by_id[eid].tags)
    ]

    _write_csv(out_dir / "points.csv", point_rows, list(point_rows[0]))
    _write_csv(out_dir / "equipment.csv", equip_rows, list(equip_rows[0]))
    _write_csv(out_dir / "equip_relations.csv", rel_rows, ["src", "rel", "dst", "source_tag"])
    _write_csv(out_dir / "unmapped.csv", unmapped_rows,
               ["entity_id", "entity_kind", "raw_name", "haystack_tags", "map_status", "candidates"])
    _write_csv(out_dir / "issues.csv", issues, ["entity_id", "issue"])

    # Brick graph: only confident classes (mapped/generic); every relation from refs.
    g = rdflib.Graph()
    ns = rdflib.Namespace(f"urn:{site}#")
    g.bind("brick", BRICK)
    g.bind(site, ns)
    for r in equip_rows + point_rows:
        eid = r.get("equip_id") if "parent_equip_id" in r else r["point_id"]
        node = ns[eid]
        g.add((node, RDFS.label, rdflib.Literal(r.get("dis") or r.get("raw_name"))))
        if r["map_status"] in (MAPPED, GENERIC):
            g.add((node, RDF.type, BRICK[r["brick_class"]]))
    for r in point_rows:
        if r["equip_id"]:
            g.add((ns[r["equip_id"]], BRICK.hasPoint, ns[r["point_id"]]))
    for r in rel_rows:
        g.add((ns[r["src"]], BRICK[r["rel"]], ns[r["dst"]]))
    g.serialize(out_dir / "brick.ttl", format="turtle")

    summary = {
        "site": site,
        "source_file": src_name,
        "source_sha256": hashlib.sha256(Path(src).read_bytes()).hexdigest(),
        "brick_version": "1.4.4 (bundled with brickschema 0.8.0)",
        "grid_meta": {k: meta[k] for k in ("numPoints", "numEquips", "numWeathers") if k in meta},
        "points": len(point_rows),
        "weather_points_excluded": weather,
        "equipment": len(equip_rows),
        "point_map_status": dict(Counter(r["map_status"] for r in point_rows)),
        "equip_map_status": dict(Counter(r["map_status"] for r in equip_rows)),
        "relations": dict(Counter(f'{r["rel"]} ({r["source_tag"]})' for r in rel_rows)),
        "points_with_equipment": sum(1 for r in point_rows if r["equip_id"]),
        "issues": len(issues),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary
