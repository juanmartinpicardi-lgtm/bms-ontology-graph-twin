"""Engineering units as the sources write them -> QUDT unit ids, the units Brick uses (knowledge_model/units.yaml).

    qudt("°F")      -> "unit:DEG_F"
    qudt("in.wc")   -> "unit:IN_H2O"
    qudt("F")       -> None          (Fahrenheit or farad: not guessed)
    point_unit("cfm") -> {"units": "cfm", "unit": "unit:FT3-PER-MIN"}

A point keeps the text its source wrote (`units`) and, where the spelling names one unit, its QUDT id (`unit`).
`mismatch(cls, unit)` says when a point's class and its unit measure different things (a temperature in in.wc).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

KM_DIR = Path(__file__).resolve().parents[2] / "knowledge_model"
PREFIX = "unit:"


def _key(text: str) -> str:
    return re.sub(r"\s+", "", str(text).strip().replace("₂", "2")).lower()


@lru_cache
def load(path: Path = KM_DIR / "units.yaml") -> dict:
    """{"spelling": {key -> QUDT id}, "quantity": {QUDT id -> quantity}, "class_words": {word -> quantities}}.
    Raises ValueError when one spelling names two units."""
    d = yaml.safe_load(Path(path).read_text())
    spelling, quantity, problems = {}, {}, []
    for uid, u in d["units"].items():
        quantity[PREFIX + uid] = u["quantity"]
        for s in u["spellings"]:
            k = _key(s)
            if spelling.get(k, PREFIX + uid) != PREFIX + uid:
                problems.append(f"units.yaml: {s!r} names both {spelling[k]} and {PREFIX + uid}")
            spelling[k] = PREFIX + uid
    if problems:
        raise ValueError("; ".join(problems))
    return {"spelling": spelling, "quantity": quantity, "class_words": d.get("class_words", {})}


def qudt(text: str | None) -> str | None:
    """The QUDT unit id a source's unit text names, or None (empty, unknown or ambiguous)."""
    if not text or not str(text).strip():
        return None
    return load()["spelling"].get(_key(text))


def point_unit(text: str | None) -> dict:
    """The attrs a point gets for its unit text: {} when the source gives none."""
    if not text or not str(text).strip():
        return {}
    out = {"units": str(text).strip()}
    if u := qudt(text):
        out["unit"] = u
    return out


def mismatch(cls: str | None, unit: str | None) -> bool:
    """True when the class names a quantity (Temperature, Pressure...) and the QUDT unit measures another one."""
    if not cls or not unit:
        return False
    m = load()
    q = m["quantity"].get(unit)
    words = cls.split("_")
    for word, allowed in m["class_words"].items():
        if word in words:
            return q is not None and q not in allowed
    return False
