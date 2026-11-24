"""Name -> Brick class, by matching canonical name words against the words of each class name.

No per-class rules: a class is a candidate because its name's words appear in the point's name.
Score = matched words - penalty for each class word the name does not mention (cheaper for
`implied_words` such as "air"). Ambiguous abbreviations are tried in every combination; the best
interpretation wins and disagreement between interpretations lowers confidence.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from ..knowledge_model import KnowledgeModel

MISSING_PENALTY = 0.5
IMPLIED_PENALTY = 0.1
IMPLIED_WORDS = {"air"}
COMPONENT_PENALTY = 1.0  # a class naming a component the name never mentions ("Building DP" is not a filter point)
ALT_PENALTY = 1.0  # per token read with a less likely abbreviation meaning
REDUNDANT_READING = 2.0  # extra, in ALT_PENALTY units, when that meaning adds no word the name doesn't already say
MAX_INTERPRETATIONS = 16
FALLBACK_CONFIDENCE = 0.1  # a generic class from the point's function only
# Words naming a kind of equipment or component (vocabulary words of the name rules).
EQUIPMENT_WORDS = {"fan", "pump", "chiller", "boiler", "cooling_tower", "heat_exchanger", "vfd", "damper",
                   "valve", "coil", "filter", "humidifier", "meter", "economizer"}


@dataclass
class ClassGuess:
    cls: str | None
    confidence: float
    words: list[str]  # the interpretation used, after synonyms and function inference
    alternatives: list[tuple[str, float]] = field(default_factory=list)  # top classes with scores
    unknown: list[str] = field(default_factory=list)
    hint: str | None = None  # origin of the convention class hint that decided the class, if any


class ClassMatcher:
    def __init__(self, km: KnowledgeModel, kind: str, also: tuple[str, ...] = ()):
        """Match against classes of `kind` (plus kinds in `also`, e.g. systems for equipment folders)."""
        self.km = km
        self.cm = km.class_matching
        self.kind = kind
        self.class_words = {c: set(ws) for k in (kind, *also) for c in km.by_kind(k) if (ws := self.cm.class_words(c))}
        self.functions = set(self.cm.functions) if kind == "point" else set()

    def tokens_without(self, name: str, equipment: str | None) -> tuple[list[str], list[str]]:
        """Name tokens with the equipment's own name removed ("B-1 Fire Rate" on B-1 -> fire rate).
        The equipment name says what the point belongs to, not what the point is. Kept if nothing remains.
        If only function words remain ("EF-2 Status" -> status), the equipment's type word comes back
        (-> fan status), since then it is the only thing saying what the status is of."""
        nr = self.km.name_rules
        tokens = nr.tokenize(name)
        drop = nr.tokenize(equipment) if equipment else []
        n = len(drop)
        for i in range(len(tokens) - n + 1) if n else ():
            if tokens[i:i + n] == drop and len(tokens) > n:
                rest = tokens[:i] + tokens[i + n:]
                words = {w for t in rest for w in (nr.expand(t) or [[t]])[0]}
                if words <= set(self.cm.functions) | set(self.cm.command_cues):
                    rest += [w for t in drop for w in (nr.expand(t) or [[]])[0] if w in EQUIPMENT_WORDS]
                return rest, drop
        return tokens, []

    def _interpretations(self, name: str, equipment: str | None = None) -> tuple[list[tuple[list[str], float]], list[str]]:
        """Every reading of the name as (words, how unlikely the abbreviation meanings used are)."""
        nr = self.km.name_rules
        options, unknown = [], []
        for t in self.tokens_without(name, equipment)[0]:
            if t.isdigit():
                continue
            alts = nr.expand(t)
            if alts is None:
                unknown.append(t)
                options.append([(0, [t])])
            else:
                options.append(list(enumerate(alts)))
        combos = list(itertools.islice(itertools.product(*options), MAX_INTERPRETATIONS)) if options else [()]
        return [([w for _, alt in combo for w in alt], self._unlikely(combo)) for combo in combos], unknown

    def _unlikely(self, combo) -> float:
        """How unlikely a reading is, in units of ALT_PENALTY: one per less likely abbreviation meaning, and
        REDUNDANT_READING more when that meaning only repeats what the rest of the name already says ("Building
        Static_SP": SP as static pressure repeats "static", which already implies pressure; SP is the setpoint)."""
        out = 0.0
        for n, (i, alt) in enumerate(combo):
            if not i:
                continue
            out += 1
            rest = {w for m, (_, other) in enumerate(combo) if m != n for w in other}
            rest |= {w for k in rest for w in self.cm.point_implies.get(k, [])} if self.kind == "point" else set()
            if set(alt) <= rest:
                out += REDUNDANT_READING
        return out

    def _with_function(self, words: list[str]) -> list[str]:
        if self.kind != "point":
            return words
        words = words + [w for k in words for w in self.cm.point_implies.get(k, []) if w not in words]
        if any(w in self.cm.functions for w in words):
            return words
        if any(w in self.cm.command_cues for w in words):
            return words + ["command"]
        if any(w in self.cm.quantities for w in words):
            return words + [self.cm.default_function]
        return words

    def _score(self, words: set[str], cls_words: set[str]) -> float:
        matched = len(words & cls_words)
        if not matched:
            return 0.0
        missing = cls_words - words
        # A class naming another function than the one the name states ("Static_SP" read as a setpoint is not a
        # sensor) is as wrong as one naming a component the name never mentions.
        said = bool(words & self.functions)
        return matched - sum(IMPLIED_PENALTY if w in IMPLIED_WORDS else COMPONENT_PENALTY if w in EQUIPMENT_WORDS
                             or (said and w in self.functions) else MISSING_PENALTY for w in missing)

    def _fallback(self, words: list[str]) -> str | None:
        """Best guess when no class name matches: the generic class of the point's function
        ("Firing Rate" -> Sensor), so every point gets a class. None for equipment."""
        if self.kind != "point":
            return None
        fn = next((w for w in words if w in self.cm.functions), self.cm.default_function)
        cls = fn.capitalize()
        return cls if cls in self.km.classes else "Point"

    def rank(self, words: list[str]) -> list[tuple[str, float]]:
        s = set(words)
        scored = [(c, self._score(s, cw)) for c, cw in self.class_words.items()]
        return sorted((x for x in scored if x[1] > 0), key=lambda x: (-x[1], len(self.class_words[x[0]]), x[0]))

    def classify(self, name: str, equipment: str | None = None) -> ClassGuess:
        """`equipment`: the name of the equipment the point sits on, left out of the point's words."""
        interpretations, unknown = self._interpretations(name, equipment)
        best: tuple[float, list[str], list[tuple[str, float]]] | None = None
        winners = set()
        for raw, non_default in interpretations:
            words = self._with_function(self.cm.name_words(raw))
            ranked = self.rank(words)
            if not ranked:
                continue
            winners.add(ranked[0][0])
            total = ranked[0][1] - ALT_PENALTY * non_default
            if best is None or total > best[0]:
                best = (total, words, ranked)
        if best is None:
            words = self._with_function(self.cm.name_words(interpretations[0][0]))
            return ClassGuess(self._fallback(words), FALLBACK_CONFIDENCE, words, [], unknown)

        _, words, ranked = best
        top_score = ranked[0][1]
        cls = ranked[0][0]
        cls_words = self.class_words[cls]
        informative = set(words)
        matched = len(informative & cls_words)
        class_cov = matched / len(cls_words)
        name_cov = matched / max(1, len(informative))
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = min(1.0, max(0.0, top_score - second))
        confidence = class_cov * (0.6 + 0.4 * name_cov) * (0.5 + 0.5 * margin)
        if len(winners) > 1:
            confidence *= 0.7
        return ClassGuess(cls, round(min(confidence, 1.0), 4), words, ranked[:5], unknown)
