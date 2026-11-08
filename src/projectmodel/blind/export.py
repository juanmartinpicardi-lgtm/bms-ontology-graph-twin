"""Blind exports: what a mapper sees, with every tag and ref that could leak the answer removed.

Per site, two inputs (same points, same blind ids, same row order):
  data/blind/<site>/names_only.csv   blind_id, name
  data/blind/<site>/names_paths.csv  blind_id, name, path   (equipment folder chain, like a Niagara station tree)

The join back to ground truth lives outside data/blind, in data/ground_truth/<site>/blind_key.csv:
  blind_id, point_id, name_source

Name choice per point (name_source):
  source  - the original BMS name (Alpha: custom.description, Bravo: custom.sourcePointName)
  dis     - no BMS name; the Haystack dis with the equipment's dis prefix stripped. This label was
            written by the dataset curator from the tags, so it is easier than a real BMS name;
            score these points separately.
Rows are shuffled and get fresh sequential ids: Haystack ids are sequential per equipment, so
keeping them (or their order) would leak the grouping.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from ..golden.load import Entity, load_grid

SOURCE_NAME_KEYS = ("description", "sourcePointName")


def _strip_prefix(text: str, prefix: str) -> str:
    if prefix and text.startswith(prefix + " "):
        return text[len(prefix) + 1:]
    return text


def _strip_common_words(text: str, parent: str) -> str:
    """Drop the leading words `text` shares with `parent` ("Alpha Airside VAV 1-3-1" under
    "Alpha Airside AHU-3" -> "VAV 1-3-1"); keep the full text if nothing would remain."""
    words, pwords = text.split(" "), parent.split(" ")
    n = 0
    while n < min(len(words), len(pwords)) and words[n] == pwords[n]:
        n += 1
    return " ".join(words[n:]) or text


def point_name(p: Entity, equip: Entity | None, site: Entity) -> tuple[str, str]:
    for k in SOURCE_NAME_KEYS:
        if p.custom.get(k):
            return str(p.custom[k]).strip(), "source"
    dis = p.tags.get("dis", "")
    prefix = equip.tags.get("dis", "") if equip else site.tags.get("dis", "")
    return _strip_prefix(dis, prefix), "dis"


def equip_path(q: Entity, by_id: dict[str, Entity], site: Entity) -> str:
    """Folder chain from the top-level equipment down to q, each folder named by the words of its
    dis that differ from its parent's (the site for top-level equipment)."""
    chain = [q]
    while chain[-1].tags.get("equipRef") in by_id and len(chain) < 20:
        chain.append(by_id[chain[-1].tags["equipRef"]])
    chain.reverse()
    parts, parent_dis = [], site.tags.get("dis", "")
    for e in chain:
        dis = e.tags.get("dis", "")
        parts.append(_strip_common_words(dis, parent_dis))
        parent_dis = dis
    return "/".join(parts)


def build_blind(site: str, src: Path, blind_dir: Path, key_path: Path, seed: int = 20261108) -> dict:
    _, entities = load_grid(src)
    by_id = {e.id: e for e in entities}
    site_e = next(e for e in entities if e.kind == "site")
    # Same population as the ground truth: weather-station points are excluded there too.
    points = [
        e for e in entities
        if e.kind == "point" and not ("weatherStationRef" in e.tags and "equipRef" not in e.tags)
    ]
    random.Random(seed).shuffle(points)

    rows = []
    for i, p in enumerate(points, 1):
        equip = by_id.get(p.tags.get("equipRef", ""))
        name, name_source = point_name(p, equip, site_e)
        path = equip_path(equip, by_id, site_e) if equip else ""
        rows.append({"blind_id": f"pt-{i:05d}", "point_id": p.id, "name": name, "path": path, "name_source": name_source})

    blind_dir.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    for fname, cols in (("names_only.csv", ["blind_id", "name"]), ("names_paths.csv", ["blind_id", "name", "path"])):
        with (blind_dir / fname).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    with key_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["blind_id", "point_id", "name_source"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    return {
        "site": site,
        "points": len(rows),
        "name_source": {s: sum(r["name_source"] == s for r in rows) for s in ("source", "dis")},
        "distinct_names": len({r["name"] for r in rows}),
        "distinct_paths": len({r["path"] for r in rows if r["path"]}),
        "points_without_path": sum(not r["path"] for r in rows),
        "seed": seed,
    }
