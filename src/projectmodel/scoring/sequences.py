"""Score a reading of the sequences of operation against a hand-built key (data/ground_truth/<site>/sequences.yaml).

The unit is one relation (from, rel, to) between candidate ids, per sequence. The key's loops count as their
`setpoint drives output` and `measured feedback output` relations (a loop with no setpoint point has only the second);
interlocks, resets and modes are one relation each. A key end or relation given as a list is any-of.

    true positive    an answer relation that matches a key relation not matched yet
    duplicate        an answer relation that matches a key relation already matched (the second of two fan walls the
                     key lists as one fact): neither right nor wrong
    false positive   an answer relation that matches nothing in the key
    recall           matched required key relations / required key relations (optional ones never count against it)
    precision        true positives / (true positives + false positives)

Gaps and conflicts are fuzzy text: a key gap is found when an answer gap names the same section (or none) and shares
two content words with it (one for a short key text); a key conflict when an answer conflict names two of its sections.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "no", "not", "is", "be", "only", "point", "points",
        "setpoint", "has", "have", "units", "unit", "sequence", "section", "sections"}


def key_path(site: str) -> Path:
    return ROOT / "data/ground_truth" / site / "sequences.yaml"


def load_key(site: str) -> dict:
    return yaml.safe_load(key_path(site).read_text())


def _set(v) -> frozenset:
    if v is None:
        return frozenset()
    return frozenset(v if isinstance(v, list) else [v])


def key_relations(seq: dict) -> list[dict]:
    """The key's relations for one sequence: {from, rel, to} as sets (any-of), kind, section, optional, name."""
    out = []
    for lp in seq.get("loops", []):
        outs = _set(lp.get("output"))
        base = {"kind": "loop", "section": lp.get("section"), "optional": bool(lp.get("optional")),
                "name": lp.get("name", "")}
        if lp.get("setpoint"):
            out.append(dict(base, **{"from": _set(lp["setpoint"]), "rel": frozenset({"drives"}), "to": outs}))
        if lp.get("measured"):
            out.append(dict(base, **{"from": _set(lp["measured"]), "rel": frozenset({"feedback"}), "to": outs}))
    for kind, part in (("interlock", "interlocks"), ("reset", "resets"), ("mode", "modes")):
        for r in seq.get(part, []) or []:
            out.append({"from": _set(r["from"]), "rel": _set(r["rel"]), "to": _set(r["to"]), "kind": kind,
                        "section": r.get("section"), "optional": bool(r.get("optional")), "name": r.get("note", "")})
    return out


def _fits(r: dict, k: dict) -> bool:
    return r["from"] in k["from"] and r["rel"] in k["rel"] and r["to"] in k["to"]


def score(answer: list[dict], key: list[dict]) -> dict:
    """Match one sequence's answer relations against its key relations (greedy, required key relations first)."""
    order = sorted(range(len(key)), key=lambda i: key[i]["optional"])
    matched: dict[int, dict] = {}
    tp, fp, dup, hits, misses = 0, 0, 0, [], []
    labels: dict[tuple, str] = {}  # (from, rel, to) -> tp | dup | fp
    for r in answer:
        t = (r["from"], r["rel"], r["to"])
        if t in labels:
            continue
        free = next((i for i in order if i not in matched and _fits(r, key[i])), None)
        if free is not None:
            matched[free] = r
            tp += 1
            hits.append((r, key[free]))
            labels[t] = "tp"
        elif any(_fits(r, key[i]) for i in matched):
            dup += 1
            labels[t] = "dup"
        else:
            fp += 1
            misses.append(r)
            labels[t] = "fp"
    required = [i for i, k in enumerate(key) if not k["optional"]]
    found = [i for i in required if i in matched]
    by_kind = {}
    for kind in ("loop", "interlock", "reset", "mode"):
        req = [i for i in required if key[i]["kind"] == kind]
        by_kind[kind] = {"key": len(req), "found": sum(i in matched for i in req),
                         "answered": sum(1 for r in answer if r.get("kind") == kind)}
    return {"tp": tp, "fp": fp, "dup": dup, "required": len(required), "found": len(found),
            "missed": [key[i] for i in required if i not in matched], "false": misses, "hits": hits,
            "labels": labels, "by_kind": by_kind}


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


def gaps_found(answer: list[dict], key: list[dict]) -> list[bool]:
    """Per key gap, whether an answer gap says it."""
    out = []
    for k in key:
        kw = _words(k["text"])
        need = 2 if len(kw) > 3 else 1
        out.append(any((not g.get("section") or not k.get("section") or g["section"] == k["section"])
                       and len(kw & _words(g["text"])) >= need for g in answer))
    return out


def conflicts_found(answer: list[dict], key: list[dict]) -> list[bool]:
    return [any(len(set(k["sections"]) & set(c.get("sections", []))) >= 2 for c in answer) for k in key]


def pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


def summary(per_seq: dict[str, dict]) -> dict:
    """Precision, recall and F1 over all sequences, plus per kind."""
    tp = sum(s["tp"] for s in per_seq.values())
    fp = sum(s["fp"] for s in per_seq.values())
    req = sum(s["required"] for s in per_seq.values())
    found = sum(s["found"] for s in per_seq.values())
    p, r = pct(tp, tp + fp), pct(found, req)
    f1 = round(2 * p * r / (p + r), 1) if p and r else 0.0
    kinds = {}
    for kind in ("loop", "interlock", "reset", "mode"):
        k = sum(s["by_kind"][kind]["key"] for s in per_seq.values())
        f = sum(s["by_kind"][kind]["found"] for s in per_seq.values())
        kinds[kind] = {"key": k, "found": f, "recall_pct": pct(f, k)}
    return {"tp": tp, "fp": fp, "dup": sum(s["dup"] for s in per_seq.values()), "required": req, "found": found,
            "precision_pct": p, "recall_pct": r, "f1": f1, "by_kind": kinds}
