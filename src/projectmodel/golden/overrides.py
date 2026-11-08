"""Human rules that fix brickschema's output in the ground truth. Two kinds, both in overrides.json:

  rules (GT-xxx, tie-breaks): fire when an entity of kind `applies_to` comes back `ambiguous` with
    exactly the candidate set `when_candidates`; it then gets `choose`.
  corrections (GC-xxx, single-match fixes): fire when brickschema returned exactly `when_class`
    (mapped or generic) and the entity carries every tag in `when_tags_all`; it then gets `choose`.

Either way the result has method=human and the rule id.

Validation (fails the build):
  - `choose` must be a non-deprecated Brick class of the right kind (point or equipment);
  - a tie-break choosing a class outside the candidates must say `"outside_candidates": true`;
  - a correction's `when_class` must be a Brick class (deprecated is allowed: that is often why it exists);
  - rule ids are unique.
Rules that match nothing are reported in summary.json, not silently ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .brick_convert import AMBIGUOUS, GENERIC, GENERIC_CLASSES, MAPPED, BrickConverter, BrickMatch

HUMAN, AUTO = "human", "brickschema"


@dataclass(frozen=True)
class Override:
    id: str
    applies_to: str
    choose: str
    rationale: str
    when_candidates: frozenset[str] = frozenset()  # tie-break
    outside_candidates: bool = False
    when_class: str = ""  # correction
    when_tags_all: frozenset[str] = frozenset()

    @property
    def is_correction(self) -> bool:
        return bool(self.when_class)


def load_overrides(path: Path, conv: BrickConverter) -> list[Override]:
    data = json.loads(Path(path).read_text())
    rules = [
        Override(
            id=r["id"], applies_to=r["applies_to"], choose=r["choose"], rationale=r["rationale"],
            when_candidates=frozenset(r["when_candidates"]), outside_candidates=r.get("outside_candidates", False),
        )
        for r in data["rules"]
    ] + [
        Override(
            id=r["id"], applies_to=r["applies_to"], choose=r["choose"], rationale=r["rationale"],
            when_class=r["when_class"], when_tags_all=frozenset(r.get("when_tags_all", [])),
        )
        for r in data.get("corrections", [])
    ]
    ids, seen = set(), set()
    g = conv.sess.g
    for o in rules:
        if o.id in ids:
            raise ValueError(f"{o.id}: duplicate rule id")
        ids.add(o.id)
        key = (o.applies_to, o.when_candidates, o.when_class, o.when_tags_all)
        if key in seen:
            raise ValueError(f"{o.id}: duplicate rule condition")
        seen.add(key)
        is_kind = {"point": conv._is_point, "equip": conv._is_equip}[o.applies_to]
        if not is_kind(o.choose):
            raise ValueError(f"{o.id}: {o.choose} is not a Brick {o.applies_to} class")
        if g.query(f"ASK {{ brick:{o.choose} owl:deprecated true }}").askAnswer:
            raise ValueError(f"{o.id}: {o.choose} is deprecated in Brick")
        if o.is_correction:
            if not g.query(f"ASK {{ brick:{o.when_class} a owl:Class }}").askAnswer:
                raise ValueError(f"{o.id}: when_class {o.when_class} is not a Brick class")
        elif o.choose not in o.when_candidates and not o.outside_candidates:
            raise ValueError(f"{o.id}: {o.choose} is not a candidate; set outside_candidates to allow it")
    return rules


def apply_overrides(
    kind: str, m: BrickMatch, rules: list[Override], markers: frozenset[str] = frozenset()
) -> tuple[BrickMatch, str, str]:
    """Return (match, method, override_id)."""
    for o in rules:
        if o.applies_to != kind:
            continue
        if o.is_correction:
            fires = m.status in (MAPPED, GENERIC) and m.brick_class == o.when_class and o.when_tags_all <= markers
        else:
            fires = m.status == AMBIGUOUS and frozenset(m.candidates) == o.when_candidates
        if fires:
            status = GENERIC if o.choose in GENERIC_CLASSES else MAPPED
            return BrickMatch(status, o.choose, m.candidates, m.tags_used, m.leftover), HUMAN, o.id
    return m, AUTO, ""
