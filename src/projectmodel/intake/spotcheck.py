"""Spot checks: how we measure the readers on a real building, inside the review the engineer does anyway.

Facts the rules or the AI were sure of (confidence of AUTO_ACCEPT or more, nothing asked) are confirmed without a
person. That is what makes the setup fast, and also what nobody looks at. So a small, fixed share of them is asked
again, as an ordinary question in "Needs you", without the reader's answer: the engineer answers from the document,
and only then sees what the reader said. Each answer is one honest data point on "when the machine was sure, was it
right?", on this building, from the person who knows it. Answering also confirms or fixes the fact, like any other
answer, so no work is wasted.

Which facts: per kind, PM_SPOT_CHECK of them (0.05, so 5%), at least 1 and at most PM_SPOT_MAX (5), picked by a
stable hash of the building and the fact id. The pick never depends on answers, so answering one does not draw
another; reading a step again may pick others. PM_SPOT_CHECK=0 turns spot checks off.

A spot ask is a normal ask, {"q", "field", "options"}, plus "spot": True, "expected" (the reader's value) and "said"
(the same, as its option reads), which the question screens hide until the answer is in. The decision records {"spot": {"expected", "same"}}; `report` sums
them per kind.
"""
from __future__ import annotations

import hashlib
import os
import re

KIND_NAME = {"room": "Room names", "equipment": "Unit types", "relation": "What feeds what",
             "controller": "Controller trunks", "point": "Point classes", "alias": "BMS devices",
             "bms_object": "BMS objects"}
NONE = {"value": None, "label": "None of these"}


def rate() -> float:
    try:
        return max(0.0, min(1.0, float(os.environ.get("PM_SPOT_CHECK", "0.05"))))
    except ValueError:
        return 0.05


def cap() -> int:
    try:
        return max(1, int(os.environ.get("PM_SPOT_MAX", "5")))
    except ValueError:
        return 5


def _h(slug: str, fid: str) -> str:
    return hashlib.sha256(f"{slug}|{fid}".encode()).hexdigest()


def norm(v) -> str:
    """For comparing a typed answer with the reader's: case, spaces and punctuation don't count."""
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


def same(expected, given) -> bool:
    if isinstance(expected, str) or isinstance(given, str):
        return norm(expected) == norm(given)
    return expected == given


def _pretty(cls: str | None) -> str:
    return (cls or "").replace("_", " ")


# ---------------------------------------------------------------- one blind question per kind

class _Ctx:
    """What the questions draw their options from: the building's own documents, never the reader's answer alone."""

    def __init__(self, raw: list[dict]):
        self.by_kind: dict[str, list[dict]] = {}
        for f in raw:
            self.by_kind.setdefault(f["kind"], []).append(f)
        self.tag = {f["data"].get("normal"): f["data"].get("tag") for f in self.by_kind.get("equipment", [])
                    if f["data"].get("normal")}

    def tag_of(self, normal) -> str:
        return self.tag.get(normal) or str(normal)

    def options(self, values, label=lambda v: str(v), none: bool = False) -> list[dict]:
        vals = sorted({v for v in values if v not in (None, "")}, key=lambda v: str(v))
        return [{"value": v, "label": label(v)} for v in vals] + ([NONE] if none else [])


def _room(f, c):
    d = f["data"]
    return {"q": f"What is room {d['number']} called on the plan? Type the name printed with it.", "field": "name",
            "options": [], "label": f"Spot check: room {d['number']}"}


def _equipment(f, c):
    d = f["data"]
    return {"q": f"What kind of unit is {d['tag']}? Check its schedule.", "field": "class",
            "options": c.options([e["data"].get("class") for e in c.by_kind["equipment"]], _pretty),
            "label": f"Spot check: {d['tag']}"}


def _relation(f, c):
    d = f["data"]
    if d.get("rel") != "feeds":
        return None
    srcs = [r["data"]["src"] for r in c.by_kind["relation"] if r["data"].get("rel") == "feeds"]
    return {"q": f"Which unit feeds {c.tag_of(d['dst'])}" + (f" ({d['medium']})" if d.get("medium") else "") + "?",
            "field": "src", "options": c.options(srcs, c.tag_of, none=True),
            "label": f"Spot check: what feeds {c.tag_of(d['dst'])}"}


def _controller(f, c):
    d = f["data"]
    names = {x["data"].get("trunk"): x["data"].get("trunk_name") for x in c.by_kind["controller"]}
    return {"q": f"Which field trunk is the controller of {d['device']} on? Check the riser.", "field": "trunk",
            "options": c.options(names, lambda t: f"{t} · {names[t]}" if names.get(t) else str(t)),
            "label": f"Spot check: trunk of {d['device']}"}


def _point(f, c):
    d = f["data"]
    classes = [p["data"].get("class") for p in c.by_kind["point"] if p["data"].get("io") == d.get("io")]
    return {"q": f"What is {d['device']} point {d['short']}" + (f", \"{d['description']}\"" if d.get("description")
                                                                 else "") + f" ({d.get('io') or 'point'})?",
            "field": "class", "options": c.options(classes, _pretty),
            "label": f"Spot check: {d['device']}.{d['short']}"}


def _alias(f, c):
    d = f["data"]
    return {"q": f"Which unit on the drawings is the BMS device {d['device']}?", "field": "equip",
            "options": c.options(c.tag, c.tag_of, none=True), "label": f"Spot check: BMS {d['device']}"}


def _bms_object(f, c):
    d = f["data"]
    pts = {p["id"]: p["data"] for p in c.by_kind.get("point", []) if p["data"].get("device") == d.get("device")}
    if not pts:
        return None
    lab = lambda pid: f"{pts[pid]['short']} · {pts[pid].get('description') or ''}".strip(" ·")
    return {"q": f"Which submittal point is the BMS object {d['ref']} ({d.get('object_type', '')})?",
            "field": "point", "options": c.options(pts, lab, none=True), "label": "Spot check: BMS object "
                                                                             + d["ref"].split("/")[-1]}


BUILD = {"room": _room, "equipment": _equipment, "relation": _relation, "controller": _controller, "point": _point,
         "alias": _alias, "bms_object": _bms_object}


def eligible(f: dict, auto_accept: float) -> bool:
    return f["kind"] in BUILD and f["conf"] >= auto_accept and not f.get("ask")


def pick(slug: str, raw: list[dict], auto_accept: float) -> dict[str, dict]:
    """The spot asks for one building, by fact id. `raw`: every fact as read (no decisions applied)."""
    r = rate()
    if r <= 0:
        return {}
    ctx, out = _Ctx(raw), {}
    pool: dict[str, list[dict]] = {}
    for f in raw:
        if eligible(f, auto_accept):
            pool.setdefault(f["kind"], []).append(f)
    for kind, facts in pool.items():
        n = min(max(1, round(r * len(facts))), cap(), len(facts))
        for f in sorted(facts, key=lambda f: _h(slug, f["id"])):
            if n == 0:
                break
            try:
                ask = BUILD[kind](f, ctx)
            except (KeyError, TypeError):
                ask = None
            expected = f["data"].get(ask["field"]) if ask else None
            if not ask or (ask["options"] and not any(o["value"] == expected for o in ask["options"])):
                continue  # a question whose right answer is not among its options would measure nothing
            said = next((o["label"] for o in ask["options"] if o["value"] == expected), shown(expected))
            ask.update(spot=True, expected=expected, said=said)  # `said`: the reader's answer as the person reads it
            out[f["id"]] = ask
            n -= 1
    return out


def shown(v) -> str:
    return "none" if v in (None, "") else _pretty(v) if isinstance(v, str) else str(v)


def report(it) -> dict:
    """Per kind and in all: checked (answered, not skipped), the reader right, wrong, and still waiting."""
    rows: dict[str, dict] = {}
    for f in it.facts():
        if not (f.get("ask") or {}).get("spot"):
            continue
        r = rows.setdefault(f["kind"], {"kind": f["kind"], "what": KIND_NAME.get(f["kind"], f["kind"]), "asked": 0,
                                        "checked": 0, "right": 0, "wrong": 0, "waiting": 0, "skipped": 0})
        r["asked"] += 1
        d = it.s["decisions"].get(f["id"])
        res = (d or {}).get("spot")
        if not d:
            r["waiting"] += 1
        elif d["status"] == "rejected":
            r["checked"] += 1
            r["wrong"] += 1
        elif not res or res.get("skipped"):
            r["skipped"] += 1
        else:
            r["checked"] += 1
            r["right" if res["same"] else "wrong"] += 1
    total = {k: sum(r[k] for r in rows.values()) for k in ("asked", "checked", "right", "wrong", "waiting",
                                                             "skipped")}
    return {"kinds": sorted(rows.values(), key=lambda r: r["what"]), "total": total,
            "right_share": total["right"] / total["checked"] if total["checked"] else None}
