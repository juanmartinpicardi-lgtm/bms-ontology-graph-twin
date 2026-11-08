"""Load a Project Haystack 4 JSON grid into plain Python entities.

Values are decoded to simple types:
  marker -> True, ref -> "a-0001" (id string), number -> "12.5unit" kept as raw dict,
  everything else left as-is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Standard Haystack refs on an equip that mean "<ref target> feeds <this equip>".
# An equip's own equipRef means "<this equip> is part of <ref target>".
# Non-standard refs under `custom` (e.g. secondaryLoopRef) are deliberately not used.
EQUIP_RELATION_REFS = {
    "airRef": "feeds",
    "chilledWaterRef": "feeds",
    "hotWaterRef": "feeds",
    "steamRef": "feeds",
    "condenserWaterRef": "feeds",
    "elecRef": "feeds",
}


@dataclass
class Entity:
    id: str
    row: int  # 0-based index in the grid's rows, for provenance
    tags: dict = field(default_factory=dict)  # decoded tag -> value (custom excluded)
    custom: dict = field(default_factory=dict)

    @property
    def markers(self) -> list[str]:
        return sorted(k for k, v in self.tags.items() if v is True)

    @property
    def refs(self) -> dict[str, str]:
        return {k: v for k, v in self.tags.items() if k.endswith("Ref") and isinstance(v, str)}

    def has(self, tag: str) -> bool:
        return tag in self.tags

    @property
    def kind(self) -> str:
        for k in ("point", "equip", "site", "weatherStation", "space"):
            if k in self.tags:
                return k
        return "other"


def _decode(v):
    if isinstance(v, dict) and "_kind" in v:
        k = v["_kind"]
        if k == "marker":
            return True
        if k == "ref":
            return v["val"]
        return v  # number, coord, etc. kept raw
    return v


def load_grid(path: Path) -> tuple[dict, list[Entity]]:
    grid = json.loads(Path(path).read_text())
    entities = []
    for i, row in enumerate(grid["rows"]):
        tags = {k: _decode(v) for k, v in row.items() if k != "custom"}
        custom = {k: _decode(v) for k, v in (row.get("custom") or {}).items()}
        entities.append(Entity(id=tags["id"], row=i, tags=tags, custom=custom))
    return grid.get("meta", {}), entities
