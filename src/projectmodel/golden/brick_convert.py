"""Haystack tags -> Brick class, using brickschema's own tag-matching.

We call brickschema's matcher per entity instead of `infer_model` because, in brickschema 0.8.0:
  - `infer_model` only reads Haystack 3 JSON markers ("m:"), so Haystack 4 JSON yields nothing;
  - `infer_entity` picks `candidates[0]` from an unordered set when classes tie (non-deterministic);
  - `infer_entity` skips equipment classification whenever the entity has an equipRef
    (i.e. every sub-equipment such as a VAV under an AHU).

Here we keep every candidate and never pick among ties. The only reduction applied is
subsumption: a candidate that is a superclass of another candidate is dropped (AHU beats
HVAC_Equipment). After that: one candidate -> mapped, several -> ambiguous, none -> unmapped.
Nothing is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from brickschema.inference import HaystackInferenceSession

from .load import Entity

# Classes that are technically a match but carry almost no meaning.
GENERIC_CLASSES = {
    "Point", "Sensor", "Command", "Setpoint", "Status", "Alarm", "Parameter",
    "Equipment", "HVAC_Equipment",
}

MAPPED, GENERIC, AMBIGUOUS, UNMAPPED = "mapped", "generic", "ambiguous", "unmapped"


@dataclass
class BrickMatch:
    status: str
    brick_class: str  # empty unless status is mapped/generic
    candidates: list[str]
    tags_used: list[str]  # translated tags fed to the matcher
    leftover: list[str]  # tags the winning tagset did not use


class BrickConverter:
    def __init__(self, namespace: str = "urn:project#"):
        self.sess = HaystackInferenceSession(namespace)

    @lru_cache(maxsize=None)
    def _is_point(self, cls: str) -> bool:
        return self.sess._is_point(cls)

    @lru_cache(maxsize=None)
    def _is_equip(self, cls: str) -> bool:
        return self.sess._is_equip(cls)

    @lru_cache(maxsize=None)
    def _is_subclass(self, sub: str, sup: str) -> bool:
        q = f"ASK {{ brick:{sub} rdfs:subClassOf+ brick:{sup} }}"
        return bool(self.sess.g.query(q).askAnswer)

    def _most_specific(self, classes: list[str]) -> list[str]:
        return [c for c in classes if not any(o != c and self._is_subclass(o, c) for o in classes)]

    def _tagset(self, e: Entity) -> set[str]:
        tags = set(e.markers)
        for f in self.sess._filters:
            tags = set(filter(f, tags))
        return set(self.sess._translate_tags(tags))

    def classify(self, e: Entity) -> BrickMatch:
        tags = self._tagset(e)
        if e.kind == "point":
            tags.discard("equip")
            keep = self._is_point
        elif e.kind == "equip":
            tags = tags.difference(self.sess._point_tags) | {"equip"}
            keep = self._is_equip
        else:
            raise ValueError(f"classify() only handles points and equips, got {e.kind}")

        classes, leftover = self.sess.most_likely_tagsets(tags)
        candidates = sorted(self._most_specific([c for c in classes if keep(c)]))
        if not candidates:
            status, cls = UNMAPPED, ""
        elif len(candidates) > 1:
            status, cls = AMBIGUOUS, ""
        else:
            cls = candidates[0]
            status = GENERIC if cls in GENERIC_CLASSES else MAPPED
        # brickschema computes `leftover` against an arbitrary tied candidate, so only report it
        # when there is a single winner.
        leftover = sorted(leftover) if len(candidates) == 1 else []
        return BrickMatch(status, cls, candidates, sorted(tags), leftover)
