"""Sequence of operations -> one sequence per equipment type, with its sections, setpoints and the units it applies
to; plus the gaps a reader can see.

Rules:
1. A system starts at an all-capitals heading ending in a colon (AIR HANDLING UNIT:, VAV TERMINAL UNITS:).
   Sections are "A. General:", "B. Occupancy ...". Missing letters are reported (A, B, C, E skips D).
2. The system names a family of equipment through its words (SYSTEM_WORDS). When the families' schedules show
   that one sequence covers more than one tag prefix (VAV and VAVE share the VAV schedule), the reader asks.
3. Setpoints are numbers with a unit in a sentence ("maintain a mixed air temperature of 55 degrees (adj.)").
4. A section that needs a device the units do not have is a conflict: a heating section that speaks of reheat for
   boxes with no heater in the schedule.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import pdfdoc, tags

SYSTEM = re.compile(r"^([A-Z][A-Z \-/&]{3,}):$")
SECTION = re.compile(r"^([A-Z])\.\s+(.+?):")
SYSTEM_WORDS = [  # heading words -> family, most specific first
    ("FVAV", "fvav"), ("FAN POWERED", "fvav"), ("VAV", "vav"), ("AIR HANDLING", "ahu"), ("AIR HANDLER", "ahu"),
    ("CHILLED WATER", "chiller"), ("CHILLER", "chiller"), ("EXHAUST FAN", "ef"), ("FAN COIL", "fcu"),
    ("BOILER", "boiler"), ("HOT WATER", "boiler"),
]
SETPOINT = re.compile(
    r"(?P<v>[-+]?\d+(?:\.\d+)?)\s*(?:(?P<u>degrees?|deg(?:ree)?s?\s*F|def F|°F|%\s*RH|%|”\s*wc|\"\s*wc|” \(adj\)|gpm|cfm|minutes?|min)\b|(?P<u2>%|”))",
    re.I)
UNIT = [("deg", "°F"), ("def", "°F"), ("°", "°F"), ("rh", "%RH"), ("%", "%"), ("wc", "in.wc"), ("”", "in.wc"),
        ("\"", "in.wc"), ("gpm", "gpm"), ("cfm", "cfm"), ("min", "min")]


def read(paths: list[tuple[Path, str]], equipment: list[dict], log) -> list[dict]:
    facts = []
    for path, name in paths:
        for page in range(pdfdoc.page_count(path)):
            ws = pdfdoc.words(path, page)
            sheet = pdfdoc.sheet_number(ws)
            cols = _columns(ws)
            systems = _systems(cols)
            if not systems:
                log(f"Page {page + 1} · {sheet}: no sequence headings found")
                continue
            log(f"Page {page + 1} · {sheet}: {len(systems)} systems — {', '.join(s['title'].title() for s in systems)}")
            for s in systems:
                facts += _system_facts(s, equipment, {"file": name, "page": page, "sheet": sheet}, log)
    return facts


def _columns(ws):
    """Sequence sheets are set in columns: text lines in reading order, column by column. A column starts where a
    heading's left edge is, and runs down the page."""
    body = max(set(w.size for w in ws), key=lambda s: sum(1 for w in ws if w.size == s))  # the body text size
    lines = pdfdoc.lines([w for w in ws if abs(w.size - body) < 1.5], gap=40)
    heads = [l for l in lines if SYSTEM.match(l.text) or SECTION.match(l.text)]
    if not heads:
        return []
    edges = sorted({round(l.bbox[0] / 40) * 40 for l in heads})
    merged = []
    for e in edges:
        if not merged or e - merged[-1] > 200:
            merged.append(e)
    out = []
    for i, x in enumerate(merged):
        x_end = merged[i + 1] - 20 if i + 1 < len(merged) else 1e9
        col = sorted((l for l in lines if x - 30 <= l.bbox[0] < x_end), key=lambda l: l.bbox[1])
        out += col
    return out


def _systems(lines):
    systems, cur, sec = [], None, None
    for l in lines:
        t = l.text.strip()
        m = SYSTEM.match(t)
        if m and not SECTION.match(t):
            cur = {"title": m.group(1).strip(), "bbox": l.bbox, "sections": [], "lines": [l]}
            systems.append(cur)
            sec = None
            continue
        if cur is None:
            continue
        cur["lines"].append(l)
        m = SECTION.match(t)
        if m:
            sec = {"letter": m.group(1), "title": m.group(2).strip(), "text": t[m.end():].strip(), "bbox": l.bbox}
            cur["sections"].append(sec)
        elif sec is not None:
            sec["text"] += " " + t
            sec["bbox"] = [min(sec["bbox"][0], l.bbox[0]), sec["bbox"][1], max(sec["bbox"][2], l.bbox[2]), l.bbox[3]]
    systems = [s for s in systems if s["sections"]]  # title-block labels (REVISION:, DATE:) have no sections
    for s in systems:
        b = [l.bbox for l in s["lines"] if l.bbox[1] <= s["sections"][-1]["bbox"][3]]
        s["bbox"] = [min(x[0] for x in b), min(x[1] for x in b), max(x[2] for x in b), max(x[3] for x in b)]
    return systems


def _family(title: str) -> str | None:
    return next((f for w, f in SYSTEM_WORDS if w in title.upper()), None)


def _system_facts(s, equipment, src, log) -> list[dict]:
    family = _family(s["title"])
    units = [e for e in equipment if e["data"]["family"] == family] if family else []
    if family == "chiller":
        units += [e for e in equipment if e["data"]["family"] == "pump"]
    prefixes = sorted({tags.parse(e["data"]["tag"]).prefix for e in units if tags.parse(e["data"]["tag"])})
    letters = [x["letter"] for x in s["sections"]]
    skipped = [chr(c) for c in range(ord("A"), ord(max(letters)) + 1) if chr(c) not in letters] if letters else []
    setpoints = []
    for sec in s["sections"]:
        for m in SETPOINT.finditer(sec["text"]):
            unit = _unit(m.group("u") or m.group("u2") or "")
            if not unit:
                continue
            start = sec["text"].rfind(".", 0, m.start()) + 1
            end = sec["text"].find(".", m.end())
            sentence = sec["text"][start:end if end > 0 else None].strip()
            if re.match(r"^\d+$", m.group("v")) and len(sentence) < 8:
                continue
            setpoints.append({"section": sec["letter"], "value": float(m.group("v")), "unit": unit,
                              "text": sentence[:220]})
    conf, ask = (0.92 if units else 0.6), None
    applies = sorted({e["data"]["tag"] for e in units}, key=_natural)
    if not family:
        ask = {"q": f"Which equipment does the sequence '{s['title'].title()}' control?", "field": None, "options": []}
    elif not units:
        conf = 0.6
        ask = {"q": f"'{s['title'].title()}' describes {family.upper()} units but no schedule has any. Keep it?",
               "field": None, "options": []}
    elif len(prefixes) > 1 and family in ("vav", "fvav"):
        conf = 0.7
        groups = {p: [t for t in applies if tags.parse(t).prefix == p] for p in prefixes}
        ask = {"q": f"'{s['title'].title()}' covers {' and '.join(f'{p} ({len(g)})' for p, g in groups.items())}: "
                    f"all of them share the {family.upper()} schedule. Apply this sequence to all?",
               "field": "applies_to",
               "options": [{"value": applies, "label": "Yes, all " + str(len(applies))}] +
                          [{"value": g, "label": f"Only {p}"} for p, g in groups.items()]}
    sid = re.sub(r"[^a-z0-9]+", "-", s["title"].lower()).strip("-")
    out = [{"id": f"seq:{sid}", "kind": "sequence", "label": s["title"].title(),
            "data": {"title": s["title"].title(), "family": family, "applies_to": applies,
                     "sections": [{"letter": x["letter"], "title": x["title"], "text": x["text"][:900],
                                   "bbox": x["bbox"]} for x in s["sections"]],
                     "setpoints": setpoints},
            "src": src | {"bbox": s["bbox"]}, "method": "rule", "conf": conf, "step": "sequences", "ask": ask}]
    log(f"  {s['title'].title()}: {len(s['sections'])} sections, {len(setpoints)} setpoints, applies to "
        f"{len(applies)} units")
    if skipped:
        text = f"Sequence '{s['title'].title()}': sections {', '.join(skipped)} are missing (lettering jumps)."
        out.append(_issue(f"{sid}-skips", text, src | {"bbox": s["bbox"]}))
        log(f"  Check: {text}")
    heating = next((x for x in s["sections"] if "HEAT" in x["title"].upper()), None)
    if heating and units and re.search(r"reheat|heating coil|electric heat", heating["text"], re.I):
        no_heat = [e["data"]["tag"] for e in units
                   if e["data"]["family"] in ("vav", "fvav") and not e["data"]["attrs"].get("heat_kw")]
        if no_heat:
            text = (f"Sequence '{s['title'].title()}' {heating['letter']}. {heating['title']}: it describes reheat, "
                    f"but {len(no_heat)} of its units have no heater in the schedule ({', '.join(no_heat[:4])}…).")
            out.append(_issue(f"{sid}-reheat", text, src | {"bbox": heating["bbox"]}))
            log(f"  Check: {text}")
    return out


def _unit(u: str) -> str | None:
    u = u.lower()
    return next((v for k, v in UNIT if k in u), None)


def _issue(id_, text, src):
    return {"id": f"issue:{id_}", "kind": "issue", "label": text, "data": {"text": text, "severity": "check"},
            "src": src, "method": "rule", "conf": 0.5, "step": "sequences", "ask": {"q": text, "field": None,
                                                                                    "options": []}}


def _natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]
