"""Knowledge a person adds while setting a building up. Two kinds, both kept with the building (state.json) and
both with who added them and when:

Rules, which extend the knowledge model for this building and change how its documents are read:
    tags    a tag prefix the model does not know: {"prefix", "class", "family", "terminal"}
    terms   a phrase in a point's description that settles its class: {"phrase", "class"}
After a rule is added the steps already read are stale; reading them again applies it.

Notes, tribal knowledge that changes nothing but travels with the graph:
    notes   {"id", "target", "label", "topic", "body", "author"}; target is "building", "unit:<normal tag>" or
            "room:<number>". They show on the graph node, on the unit in the building, and in the export.

export() gives all of it as YAML, in the same shape load() takes, so what one building taught can be reviewed and
moved into the shared knowledge model (knowledge_model/name_rules/) or given to the next building.
"""
from __future__ import annotations

import time

import yaml

from ..notes import TOPICS
from . import submittal, tags
from .state import Intake

FAMILIES = ("vav", "fvav", "fcu", "ahu", "chiller", "boiler", "pump", "ef", "uh", "split", "specialty", "other")


def get(it: Intake) -> dict:
    k = it.s.setdefault("knowledge", {})
    for kind in ("tags", "terms", "notes"):
        k.setdefault(kind, [])
    return k


def apply(it: Intake) -> None:
    """Make this building's rules the ones the readers use. Called before any reading or scoring."""
    k = get(it)
    tags.use({t["prefix"]: {"class": t["class"], "family": t["family"], "terminal": t.get("terminal", False)}
              for t in k["tags"]})
    submittal.use_terms([(t["phrase"], t["class"]) for t in k["terms"]])


def _stamp(it: Intake, rule: bool) -> None:
    if rule:
        it.s["knowledge"]["rules_at"] = time.time()
    it.save()
    apply(it)


def add_tag(it: Intake, prefix: str, cls: str, family: str, terminal: bool, by: str = "you") -> None:
    prefix = prefix.strip().upper().rstrip("-")
    if not prefix.isalpha() or not 2 <= len(prefix) <= 6:
        raise ValueError("A prefix is 2 to 6 letters, without the number: FPB, RTU, CRAC.")
    if family not in FAMILIES:
        raise ValueError(f"Unknown family {family!r}.")
    k = get(it)
    k["tags"] = [t for t in k["tags"] if t["prefix"] != prefix] + [
        {"prefix": prefix, "class": cls, "family": family, "terminal": bool(terminal), "by": by, "at": time.time()}]
    _stamp(it, rule=True)


def add_term(it: Intake, phrase: str, cls: str, by: str = "you") -> None:
    phrase = " ".join(phrase.split())
    if len(phrase) < 2:
        raise ValueError("A phrase is at least two characters, as written in the point list.")
    k = get(it)
    k["terms"] = [t for t in k["terms"] if t["phrase"].lower() != phrase.lower()] + [
        {"phrase": phrase, "class": cls, "by": by, "at": time.time()}]
    _stamp(it, rule=True)


def add_note(it: Intake, target: str, label: str, topic: str, body: str, author: str) -> None:
    if topic not in TOPICS:
        raise ValueError(f"Topic must be one of {', '.join(TOPICS)}.")
    if not body.strip() or not author.strip():
        raise ValueError("A note needs a text and an author.")
    k = get(it)
    k["notes"].append({"id": max([n["id"] for n in k["notes"]], default=0) + 1, "target": target, "label": label,
                       "topic": topic, "body": body.strip(), "author": author.strip(), "at": time.time()})
    _stamp(it, rule=False)


def remove(it: Intake, kind: str, index: int) -> None:
    get(it)[kind].pop(index)
    _stamp(it, rule=kind != "notes")


def rules_at(it: Intake) -> float:
    return get(it).get("rules_at", 0)


def notes_for(it: Intake) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for n in get(it)["notes"]:
        out.setdefault(n["target"], []).append(n)
    return out


def export(it: Intake) -> str:
    k = get(it)
    clean = lambda rows, keys: [{c: r[c] for c in keys if c in r} for r in rows]  # noqa: E731
    return yaml.safe_dump({"building": it.name,
                           "tags": clean(k["tags"], ("prefix", "class", "family", "terminal", "by")),
                           "terms": clean(k["terms"], ("phrase", "class", "by")),
                           "notes": clean(k["notes"], ("target", "label", "topic", "body", "author"))},
                          sort_keys=False, allow_unicode=True)


def load(it: Intake, text: str, classes: dict[str, set[str]]) -> tuple[int, list[str]]:
    """Add what a YAML file holds (the shape export() writes). `classes` = {"equipment": {...}, "point": {...}} from
    the knowledge model: a rule naming a class the model does not have is refused, not guessed.
    Returns (number added, the problems found)."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        return 0, [f"Not valid YAML: {e}"]
    if not isinstance(data, dict):
        return 0, ["The file must hold tags, terms or notes."]
    added, problems = 0, []
    for t in data.get("tags") or []:
        try:
            if t["class"] not in classes["equipment"]:
                raise ValueError(f"{t['class']} is not an equipment class of the knowledge model")
            add_tag(it, t["prefix"], t["class"], t.get("family", "other"), t.get("terminal", False), t.get("by", "file"))
            added += 1
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            problems.append(f"tag {t!r}: {e}")
    for t in data.get("terms") or []:
        try:
            if t["class"] not in classes["point"]:
                raise ValueError(f"{t['class']} is not a point class of the knowledge model")
            add_term(it, t["phrase"], t["class"], t.get("by", "file"))
            added += 1
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            problems.append(f"term {t!r}: {e}")
    for n in data.get("notes") or []:
        try:
            add_note(it, n.get("target", "building"), n.get("label", "the building"), n.get("topic", "other"), n["body"],
                     n.get("author", "file"))
            added += 1
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            problems.append(f"note {n!r}: {e}")
    return added, problems
