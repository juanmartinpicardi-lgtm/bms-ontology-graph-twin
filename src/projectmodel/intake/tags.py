"""Equipment tags: recognise them in text and compare two spellings of one tag.

Rules live in the knowledge model (knowledge_model/name_rules/equipment_tags.yaml), so a new prefix is a data change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RULES = Path(__file__).resolve().parents[3] / "knowledge_model/name_rules/equipment_tags.yaml"


@dataclass(frozen=True)
class Tag:
    text: str        # as written
    prefix: str
    number: str      # without leading zeros; "" for named units (EF-RR)
    suffix: str      # letter suffix (CH01a -> A) or name (EF-RR -> RR)
    cls: str
    family: str
    terminal: bool

    @property
    def normal(self) -> str:
        return f"{self.prefix}{self.number}{self.suffix}"


_extra: dict = {}  # prefixes a person added for the building being read (intake/knowledge.py)


def use(extra: dict | None) -> None:
    """Add prefixes to the model's own for the readings that follow; None or {} goes back to the model alone."""
    global _extra
    extra = {k.upper(): v for k, v in (extra or {}).items()}
    if extra != _extra:
        _extra = extra
        rules.cache_clear()
        _pattern.cache_clear()


@lru_cache
def rules() -> dict:
    r = yaml.safe_load(RULES.read_text())
    return dict(r, prefixes={**r["prefixes"], **_extra})


@lru_cache
def _pattern() -> re.Pattern:
    r = rules()
    prefixes = sorted(r["prefixes"], key=len, reverse=True)
    loose = "|".join(p for p in prefixes if not r["prefixes"][p].get("strict"))
    strict = "|".join(p for p in prefixes if r["prefixes"][p].get("strict"))
    named = r["named_suffix"]
    # prefix, separator, then a number with an optional letter, or a name (EF-RR), or a name with a number (EF-LAB1)
    body = rf"(?P<sep>[- ]?)(?:(?P<name>{named})(?:-?(?P<nn>\d{{1,2}}))?|(?P<num>\d{{1,3}})(?P<suf>[A-Za-z])?)"
    alts = [rf"(?P<p1>{loose}){body}"]
    if strict:
        alts.append(rf"(?P<p2>{strict})(?P<sep2>-)(?P<num2>\d{{1,3}})|(?P<p3>{strict})(?P<num3>\d{{2,3}})")
    return re.compile(rf"^(?:{'|'.join(alts)})$")


def parse(text: str) -> Tag | None:
    """The tag in `text` (the whole string), or None. VAVE07, VAVE-07, CH01a, CH-1A, EF-LAB1, EF-RR, AHU-1."""
    t = text.strip().strip(",.;:()")
    m = _pattern().match(t)
    if not m:
        return None
    g = m.groupdict()
    prefix = g["p1"] or g.get("p2") or g.get("p3")
    if g["p1"] and g["name"]:  # named unit: EF-LAB1, EF-LAB-1 -> suffix LAB1; EF-RR -> RR
        word = g["name"].upper()
        digits = g["nn"] or (re.search(r"\d+$", word) or [""])[0]
        number, suffix = "", word.rstrip("0123456789") + (str(int(digits)) if digits else "")
    elif g["p1"]:
        number, suffix = str(int(g["num"])), (g["suf"] or "").upper()
    else:
        number, suffix = str(int(g.get("num2") or g.get("num3"))), ""
    info = rules()["prefixes"][prefix]
    return Tag(t, prefix, number, suffix, info["class"], info["family"], bool(info.get("terminal")))


def normal(text: str) -> str | None:
    tag = parse(text)
    return tag.normal if tag else None


def find_all(text: str) -> list[Tag]:
    """Every tag among the words of `text`."""
    return [t for w in re.split(r"[\s,;()]+", text) if w and (t := parse(w))]
