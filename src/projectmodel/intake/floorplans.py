"""Floor plans -> floors, rooms, and where each equipment tag sits.

Rules, in order, for each page:
1. Floor: the sheet title names it ("MECHANICAL PLAN - LEVEL 1", "ROOF PLAN"). A page without one is not a floor plan.
2. Rooms: a room label is a three-digit number with its name in the line(s) just above it, centred on it
   (CONFERENCE / 109). A number with no name is kept only if it looks like the other room numbers, and asked about.
3. Tags: every word that is an equipment tag (knowledge_model/name_rules/equipment_tags.yaml). A tag next to a
   small "T" is a thermostat callout; a bold tag labels the unit itself.
4. Where: a terminal unit serves the room its thermostat is in; other equipment is located in the room its label is
   in. "In" is approximated by the nearest room label, so confidence falls when two labels are about as near, and
   the reader asks.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from math import dist
from pathlib import Path

from . import pdfdoc, tags

LEVEL = [  # LEVEL, FLOOR and FLR: the words title blocks use for a numbered level
    (re.compile(r"PLAN\s*-\s*(?:LEVEL|FLOOR|FLR\.?)\s*(\d+)|(?:LEVEL|FLOOR|FLR\.?)\s*(\d+)\s+(?:\w+\s+)?PLAN"), None),
    (re.compile(r"(FIRST|SECOND|THIRD|FOURTH|FIFTH)\s+FLOOR\s+(?:\w+\s+)?PLAN"), None),
    (re.compile(r"\bROOF\s+PLAN\b"), "RF"),
    (re.compile(r"\bBASEMENT\b.*\bPLAN\b"), "B1"),
]
ORDINAL = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5}
ROOM_NO = re.compile(r"^[A-Z]?\d{3,4}[A-Z]?$")  # 109, 109A, 1109 (larger buildings), A109 (a wing letter)
NAME_WORD = re.compile(r"^[A-Z0-9][A-Z0-9'/&.\-]*$")
UNITS = {"CFM", "GPM", "MBH", "KW", "HP", "LBS", "SF", "X", "TONS"}


def floor_of(page_text: str) -> tuple[str, str] | None:
    for rx, fixed in LEVEL:
        m = rx.search(page_text)
        if not m:
            continue
        if fixed:
            return fixed, {"RF": "Roof", "B1": "Basement"}[fixed]
        g = next(x for x in m.groups() if x)
        n = ORDINAL.get(g, None) or int(g)
        return f"L{n}", f"Level {n}"
    return None


def read(path: Path, file_name: str, log) -> list[dict]:
    facts: list[dict] = []
    per_floor = []
    n_pages = pdfdoc.page_count(path)
    for page in range(n_pages):
        ws = pdfdoc.words(path, page)
        text = pdfdoc.text(path, page)
        sheet = pdfdoc.sheet_number(ws)
        fl = floor_of(text)
        if not fl:
            log(f"Page {page + 1} ({sheet or 'no sheet number'}): no floor named in the title, skipped")
            continue
        floor_id, floor_name = fl
        rooms = _rooms(ws, floor_id)
        seen = _tags(ws)
        crop = _extent([r["anchor"] for r in rooms] or [o["xy"] for occ in seen.values() for o in occ], ws)
        src = {"file": file_name, "page": page, "sheet": sheet}
        facts.append({"id": f"floor:{floor_id}", "kind": "floor", "label": floor_name,
                      "data": {"floor": floor_id, "name": floor_name, "crop": crop, "rooms": len(rooms)},
                      "src": src | {"bbox": None}, "method": "rule", "conf": 0.97, "step": "plans", "ask": None})
        log(f"Page {page + 1} · {sheet}: {floor_name} — {len(rooms)} rooms, {len(seen)} equipment tags")
        for r in rooms:
            facts.append(_room_fact(r, floor_id, src))
        per_floor.append((floor_id, rooms, seen, src))
    facts += _placements(per_floor)
    floors = [f for f in facts if f["kind"] == "floor"]
    if not floors:
        log("No floor plan found: the titles name no level. Is this the right file?")
    return facts


# ---------------------------------------------------------------- rooms

def _rooms(ws, floor_id: str) -> list[dict]:
    named, bare = [], []
    for w in ws:
        if not ROOM_NO.match(w.text) or w.bold:
            continue
        right = [v for v in ws if abs(v.top - w.top) < 3 and 0 < v.x0 - w.x1 < 25]
        if any(v.text.upper().strip(".") in UNITS for v in right):
            continue
        name, name_bbox = _name_above(ws, w)
        (named if name else bare).append({"number": w.text, "name": name, "word": w, "name_bbox": name_bbox})
    sizes = Counter((r["word"].font, r["word"].size) for r in named)
    usual = {k for k, n in sizes.items() if n >= max(2, len(named) * 0.1)}
    bare = [r for r in bare if (r["word"].font, r["word"].size) in usual]
    rooms: dict[str, dict] = {}
    for r in named + bare:  # a number labelled twice: keep the named one
        if r["number"] not in rooms:
            w = r["word"]
            box = w.bbox if not r["name_bbox"] else [min(w.x0, r["name_bbox"][0]), r["name_bbox"][1],
                                                     max(w.x1, r["name_bbox"][2]), w.bottom]
            rooms[r["number"]] = r | {"bbox": [round(v, 1) for v in box], "anchor": (w.cx, w.top - 6)}
    return sorted(rooms.values(), key=lambda r: r["number"])


def _name_above(ws, num) -> tuple[str, list | None]:
    cands = [v for v in ws if v.bold and NAME_WORD.match(v.text) and not tags.parse(v.text)
             and -36 <= v.top - num.top <= -3 and abs(v.cx - num.cx) < 110]
    rows = sorted(_group_rows(cands), key=lambda r: -r[0].top)  # nearest line first
    picked, last_top = [], num.top
    for row in rows:
        if last_top - row[0].top > 14:
            break
        chain = _chain(row, num.cx)
        if not chain or abs((chain[0].x0 + chain[-1].x1) / 2 - num.cx) > 60:
            break
        picked.insert(0, chain)
        last_top = row[0].top
        if len(picked) == 3:
            break
    if not picked or not any(re.search(r"[A-Z]", w.text) for row in picked for w in row):
        return "", None
    words = [w for row in picked for w in row]
    bbox = [min(w.x0 for w in words), min(w.top for w in words), max(w.x1 for w in words), max(w.bottom for w in words)]
    return " ".join(w.text for w in words), bbox


def _group_rows(ws, tol=2.5):
    rows: list[list] = []
    for w in sorted(ws, key=lambda w: w.top):
        if rows and abs(rows[-1][0].top - w.top) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def _chain(row, cx):
    """The run of words around the one nearest `cx`, with no wide gap inside."""
    row = sorted(row, key=lambda w: w.x0)
    i = min(range(len(row)), key=lambda k: abs(row[k].cx - cx))
    lo = hi = i
    while lo > 0 and row[lo].x0 - row[lo - 1].x1 < 9:
        lo -= 1
    while hi < len(row) - 1 and row[hi + 1].x0 - row[hi].x1 < 9:
        hi += 1
    return row[lo:hi + 1]


def _on_level(number: str, level: str) -> bool:
    """Room 205 or 2105 is on level 2 (a 4-digit number may lead with a building or wing digit: 1205 = wing 1, L2)."""
    digits = number.strip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return digits.startswith(level) or (len(digits) == 4 and digits[1:].startswith(level))


def _room_fact(r: dict, floor_id: str, src: dict) -> dict:
    number, name = r["number"], r["name"]
    level_digit = floor_id[1:] if floor_id.startswith("L") else None
    ask, conf, note = None, 0.95, ""
    if not name:
        conf, note = 0.6, "no name next to the number"
        ask = {"q": f"Room {number} on the plan has no name next to it. Is it a room?", "field": "name",
               "options": [{"value": "", "label": "Yes, a room without a name"}]}
    elif level_digit and not _on_level(number, level_digit):
        conf, note = 0.75, f"number does not start with the level ({level_digit})"
        ask = {"q": f"Room {number} {name.title()} is on the {floor_id} plan but its number does not start with "
                    f"{level_digit}. Keep it on this floor?", "field": None, "options": []}
    return {"id": f"room:{number}", "kind": "room", "label": f"{number} {name.title()}".strip(),
            "data": {"number": number, "name": name.title(), "floor": floor_id, "anchor": r["anchor"], "note": note},
            "src": src | {"bbox": r["bbox"]}, "method": "rule", "conf": conf, "step": "plans", "ask": ask}


# ---------------------------------------------------------------- tags

def _tags(ws) -> dict[str, list[dict]]:
    """Occurrences of each tag. A regular-weight tag beside a "T" glyph is a thermostat callout: its place is the
    T's. A bold tag labels the unit. Other regular tags are callouts (a leader line to the unit or sensor)."""
    tees = [w for w in ws if w.text == "T" and w.size <= 6.5]
    seen: dict[str, list[dict]] = defaultdict(list)
    for w in ws:
        tag = tags.parse(w.text)
        if not tag:
            continue
        near = min(tees, key=lambda s: dist((s.cx, s.cy), (w.cx, w.cy)), default=None)
        if not w.bold and near and dist((near.cx, near.cy), (w.cx, w.cy)) < 28:
            seen[tag.normal].append({"tag": tag, "word": w, "role": "thermostat", "xy": (near.cx, near.cy)})
        else:
            seen[tag.normal].append({"tag": tag, "word": w, "role": "label" if w.bold else "callout",
                                     "xy": (w.cx, w.cy)})
    return seen


RANK = {"thermostat": 0, "callout": 1, "label": 2}


def _placements(per_floor) -> list[dict]:
    """One placement per tag. A tag drawn on several plans (a unit on L3 with its thermostat on L2, an AHU on the
    roof plan and in the mechanical room) is placed where its best evidence is: for a terminal unit the thermostat,
    else a floor with rooms before the roof."""
    by_tag: dict[str, list] = defaultdict(list)
    for floor_id, rooms, seen, src in per_floor:
        for normal, occ in seen.items():
            by_tag[normal].append((floor_id, rooms, occ, src))
    out = []
    for normal in sorted(by_tag, key=tags_sort):
        cands = by_tag[normal]
        tag = cands[0][2][0]["tag"]

        def score(c):
            floor_id, rooms, occ, _ = c
            best = min(RANK[o["role"]] for o in occ) if tag.terminal else (0 if any(o["role"] == "label" for o in occ) else 1)
            return (best, floor_id == "RF" or not rooms)
        floor_id, rooms, occ, src = min(cands, key=score)
        out.append(_place_one(normal, tag, floor_id, rooms, occ, src, also=[c[0] for c in cands if c[0] != floor_id]))
    return out


def _place_one(normal, tag, floor_id, rooms, occ, src, also) -> dict:
    anchors = [(r["anchor"], r) for r in rooms]
    label = next((o for o in occ if o["role"] == "label"), None)
    if tag.terminal:
        where, rel = min(occ, key=lambda o: RANK[o["role"]]), "serves"
    else:
        where, rel = (label or occ[0]), "located in"
    ranked = sorted(((dist(a, where["xy"]), r) for a, r in anchors), key=lambda t: t[0])
    data = {"tag": (label or occ[0])["tag"].text, "normal": normal, "class": tag.cls, "family": tag.family,
            "floor": floor_id, "rel": rel, "unit_xy": (label or occ[0])["xy"], "at_xy": where["xy"],
            "by": {"thermostat": "thermostat", "label": "unit label", "callout": "callout"}[where["role"]],
            "also_on": also, "occurrences": [{"bbox": o["word"].bbox, "role": o["role"]} for o in occ]}
    box = where["word"].bbox
    # A plan alone never auto-accepts a room: thermostats sit on walls, between two rooms, and the nearest label is
    # only a guess. Clear cases wait for a second source (the submittal's room schedule); close calls are asked.
    if not ranked or floor_id == "RF":
        data["room"] = None
        return _place_fact(normal, data, src | {"bbox": box}, 0.85 if floor_id == "RF" else 0.6, None)
    (d1, r1), *rest = ranked
    d2 = next((d for d, r in rest if r["number"] != r1["number"]), 1e9)
    if d1 <= 90 and d2 >= 1.5 * d1:
        conf = 0.85
    elif d1 <= 170 and d2 >= 1.25 * d1:
        conf = 0.75
    else:
        conf = 0.55
    if where["role"] != "thermostat" and tag.terminal:  # no thermostat found: the unit's own label is weaker
        conf = min(conf, 0.6)
    if d1 > 260 and not tag.terminal:  # far from every label: outside the rooms (yard, roof, shaft)
        conf = 0.5
    data |= {"room": r1["number"], "distance": round(d1), "runner_up": round(d2)}
    ask = None
    if conf <= 0.6:
        options = [{"value": r["number"], "label": f"{r['number']} {r['name'].title()}"}
                   for _, r in _distinct(ranked)[:4]]
        options.append({"value": None, "label": "None of these / outside"})
        verb = "serve" if rel == "serves" else "sit in"
        ask = {"q": f"Which room does {data['tag']} {verb}? Found by its {data['by']} on {src['sheet']}.",
               "field": "room", "options": options}
    return _place_fact(normal, data, src | {"bbox": box}, conf, ask)


def _place_fact(normal, data, src, conf, ask):
    where = f"room {data['room']}" if data.get("room") else {"RF": "roof"}.get(data["floor"], data["floor"])
    return {"id": f"place:{normal}", "kind": "placement", "label": f"{data['tag']} {data['rel']} {where}",
            "data": data, "src": src, "method": "rule", "conf": conf, "step": "plans", "ask": ask}


def _distinct(ranked):
    seen, out = set(), []
    for d, r in ranked:
        if r["number"] not in seen:
            seen.add(r["number"])
            out.append((d, r))
    return out


def tags_sort(normal: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", normal)]


def _extent(points, ws, margin=90) -> list[float] | None:
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [max(0, min(xs) - margin), max(0, min(ys) - margin), max(xs) + margin, max(ys) + margin]
