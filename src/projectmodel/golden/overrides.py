"""Human override rules that resolve brickschema ties in the ground truth.

A rule fires when an entity of kind `applies_to` comes back `ambiguous` with exactly the
candidate set `when_candidates`. It then gets `choose`, with method=human and the rule id.

Validation (fails the build):
  - `choose` must be a non-deprecated Brick class of the right kind (point or equipment);
  - if `choose` is not one of the candidates, the rule must say `"outside_candidates": true`.
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
    when_candidates: frozenset[str]
    choose: str
    rationale: str
    outside_candidates: bool = False


def load_overrides(path: Path, conv: BrickConverter) -> list[Override]:
    rules = [
        Override(
            id=r["id"], applies_to=r["applies_to"], when_candidates=frozenset(r["when_candidates"]),
            choose=r["choose"], rationale=r["rationale"], outside_candidates=r.get("outside_candidates", False),
        )
        for r in json.loads(Path(path).read_text())["rules"]
    ]
    seen = set()
    for o in rules:
        key = (o.applies_to, o.when_candidates)
        if key in seen:
            raise ValueError(f"{o.id}: duplicate rule for {sorted(o.when_candidates)}")
        seen.add(key)
        is_kind = {"point": conv._is_point, "equip": conv._is_equip}[o.applies_to]
        if not is_kind(o.choose):
            raise ValueError(f"{o.id}: {o.choose} is not a Brick {o.applies_to} class")
        deprecated = conv.sess.g.query(f"ASK {{ brick:{o.choose} owl:deprecated true }}").askAnswer
        if deprecated:
            raise ValueError(f"{o.id}: {o.choose} is deprecated in Brick")
        if o.choose not in o.when_candidates and not o.outside_candidates:
            raise ValueError(f"{o.id}: {o.choose} is not a candidate; set outside_candidates to allow it")
    return rules


def apply_overrides(kind: str, m: BrickMatch, rules: list[Override]) -> tuple[BrickMatch, str, str]:
    """Return (match, method, override_id)."""
    if m.status != AMBIGUOUS:
        return m, AUTO, ""
    cands = frozenset(m.candidates)
    for o in rules:
        if o.applies_to == kind and o.when_candidates == cands:
            status = GENERIC if o.choose in GENERIC_CLASSES else MAPPED
            return BrickMatch(status, o.choose, m.candidates, m.tags_used, m.leftover), HUMAN, o.id
    return m, AUTO, ""
