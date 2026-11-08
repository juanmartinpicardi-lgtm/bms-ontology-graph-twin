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
ALT_PENALTY = 1.0  # per token read with a less likely abbreviation meaning
MAX_INTERPRETATIONS = 16


@dataclass
class ClassGuess:
    cls: str | None
    confidence: float
    words: list[str]  # the interpretation used, after synonyms and function inference
    alternatives: list[tuple[str, float]] = field(default_factory=list)  # top classes with scores
    unknown: list[str] = field(default_factory=list)


class ClassMatcher:
    def __init__(self, km: KnowledgeModel, kind: str):
        self.km = km
        self.cm = km.class_matching
        self.kind = kind
        self.class_words = {c: set(ws) for c in km.by_kind(kind) if (ws := self.cm.class_words(c))}

    def _interpretations(self, name: str) -> tuple[list[tuple[list[str], int]], list[str]]:
        """Every reading of the name as (words, number of non-default abbreviation meanings used)."""
        nr = self.km.name_rules
        options, unknown = [], []
        for t in nr.tokenize(name):
            if t.isdigit():
                continue
            alts = nr.expand(t)
            if alts is None:
                unknown.append(t)
                options.append([(0, [t])])
            else:
                options.append(list(enumerate(alts)))
        combos = list(itertools.islice(itertools.product(*options), MAX_INTERPRETATIONS)) if options else [()]
        return [([w for _, alt in combo for w in alt], sum(1 for i, _ in combo if i)) for combo in combos], unknown

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
        return matched - sum(IMPLIED_PENALTY if w in IMPLIED_WORDS else MISSING_PENALTY for w in missing)

    def rank(self, words: list[str]) -> list[tuple[str, float]]:
        s = set(words)
        scored = [(c, self._score(s, cw)) for c, cw in self.class_words.items()]
        return sorted((x for x in scored if x[1] > 0), key=lambda x: (-x[1], len(self.class_words[x[0]]), x[0]))

    def classify(self, name: str) -> ClassGuess:
        interpretations, unknown = self._interpretations(name)
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
            return ClassGuess(None, 0.0, words, [], unknown)

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
