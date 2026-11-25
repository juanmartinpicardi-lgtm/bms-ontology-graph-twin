"""Controls submittal -> controllers and their network, points (with a Brick class each), the contractor's room
schedule checked against the floor plans, and the contractor's RFIs.

Rules:
1. Riser rows: address, device, controller, device instance, location, under a "FC-n" trunk heading (the heading's
   text names the trunk: "FC-1 - Plant, AHU, exhaust, gateways").
2. Point rows end with a Metasys reference NAE/FC-n.DEVICE.POINT. A reference with "FC-x" is a typical: it is
   applied to every device of the same tag prefix on the riser. A row's units, BACnet object type and instance are
   kept as written (a typical row often gives no object: the BMS export does).
3. A device is linked to scheduled equipment when their tags are the same tag (VAVE-07 = VAVE07). A device that
   matches nothing is asked about, with the nearest candidates.
4. A point's class comes from its description through the knowledge model's name rules (the same matcher the BMS
   mapper uses).
5. Room schedule rows (floor, room, box ... FC:addr): where the floor plans placed the same box in the same room,
   two sources agree and the room is confirmed; where they differ, the reader asks.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import pdfdoc, tags

TRUNK = re.compile(r"^(FC-\d+)\s+-\s+(.*)$")
RISER = re.compile(r"^(?P<addr>\d{1,3}) (?P<dev>[A-Z][A-Z0-9-]+) (?P<ctrl>.+?) (?P<inst>\d{4,7}) (?P<loc>.+)$")
IO = r"AI|AO|BI|BO|AV|BV|MV|BN"
POINT = re.compile(rf"^(?P<pt>\S+) (?P<desc>.+?) (?P<io>{IO})(?: (?P<units>\S+))? (?P<term>(?:UI|AO|BI|BO)\d+|software|BACnet)"
                   rf"(?: (?P<obj>[a-z]+(?:-[a-z]+)+) (?P<inst>\d+))? (?P<ref>[A-Z0-9-]+/FC-[\dx]+\.[A-Z0-9-]+\.\S+)$")
ROOM_ROW = re.compile(r"^(?P<floor>L\d|RF|B\d) (?P<room>[A-Z]?\d{3,4}[A-Z]?)(?P<name>.+?) (?P<box>\S+) (?P<ahu>AHU\S*) .* "
                      r"(?P<trunk>FC-\d+):(?P<addr>\d+)$")
RFI = re.compile(r"^((?:RFI|CL)-\d+) (.+)$")
# A line ending in something shaped like an object reference (NAE/TRUNK.DEVICE.POINT) that no pattern read: another
# vendor's point row. Counted so a step that read a few points out of hundreds says so.
REF_LIKE = re.compile(r"(?:\S+/\S+\.\S+\.\S+|/\S+/points/\S+)$")  # Metasys-like, or a Niagara ord path


@lru_cache
def _matcher():
    from projectmodel.knowledge_model import load_knowledge_model
    from projectmodel.mapper.classify import ClassMatcher
    return ClassMatcher(load_knowledge_model(), "point")


_terms: list[tuple[str, str]] = []  # (phrase, class) a person added for the building being read


def use_terms(terms: list[tuple[str, str]]) -> None:
    global _terms
    _terms = sorted(terms, key=lambda t: -len(t[0]))  # the longest phrase wins


def by_term(description: str, short: str) -> str | None:
    """The class a person's term for this building gives the point, if one matches."""
    for phrase, cls in _terms:
        if short.lower() == phrase.lower() or re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", description, re.I):
            return cls
    return None


def classify(description: str, short: str) -> tuple[str | None, float]:
    if cls := by_term(description, short):
        return cls, 0.95
    g = _matcher().classify(re.sub(r"\(.*?\)", "", description))
    return g.cls, round(g.confidence, 2)


def point_conf(cls: str | None, c: float, *, step: str, base: float, cap: float, term: bool) -> float:
    """A reader's confidence in a point's class, from the matcher's: `base + 0.4 c`, then calibrated to the accuracy
    measured on the dev answer key (job `intake`, calibration.py). A person's term is a statement, not a guess: it
    keeps its confidence."""
    from projectmodel import calibration

    raw = round(min(cap, base + 0.4 * c), 2) if cls else 0.4
    return raw if term else round(calibration.load("intake").apply(raw, calibration.intake_keys(cls, step)), 2)


def read(paths: list[tuple[Path, str]], equipment: list[dict], placements: list[dict], log) -> list[dict]:
    riser, points, typicals, rooms, rfis, unread = [], [], [], [], [], []
    for path, name in paths:
        trunk, trunk_sheet = None, None  # a riser table may run onto the next page of the same sheet
        trunk_name = None
        for page in range(pdfdoc.page_count(path)):
            ws = pdfdoc.words(path, page)
            src = {"file": name, "page": page, "sheet": _sheet(ws)}
            if src["sheet"] != trunk_sheet:
                trunk = None
            n_before = (len(riser), len(points), len(typicals), len(rooms), len(rfis))
            for l in pdfdoc.lines(ws, gap=1e9):
                t = l.text.strip()
                if m := TRUNK.match(t):
                    trunk, trunk_sheet, trunk_name = m.group(1), src["sheet"], m.group(2).strip()
                elif (m := POINT.match(t)):
                    row = m.groupdict() | {"src": src | {"bbox": l.bbox}}
                    (typicals if ".FC-x." in row["ref"] or "/FC-x." in row["ref"] else points).append(row)
                elif (m := ROOM_ROW.match(t)):
                    rooms.append(m.groupdict() | {"src": src | {"bbox": l.bbox}})
                elif trunk and (m := RISER.match(t)):
                    riser.append(m.groupdict() | {"trunk": trunk, "trunk_name": trunk_name,
                                                  "src": src | {"bbox": l.bbox}})
                elif (m := RFI.match(t)):
                    rfis.append({"id": m.group(1), "text": m.group(2), "src": src | {"bbox": l.bbox}})
                elif REF_LIKE.search(t):
                    unread.append({"text": t, "src": src | {"bbox": l.bbox}})
            got = [a - b for a, b in zip((len(riser), len(points), len(typicals), len(rooms), len(rfis)), n_before)]
            if any(got):
                parts = [f"{n} {w}" for n, w in zip(got, ["devices", "points", "typical points", "room rows", "RFIs"]) if n]
                log(f"Page {page + 1} · {src['sheet']}: {', '.join(parts)}")
    facts = _devices(riser, equipment, log)
    pts = _points(points, typicals, riser, log)
    facts += pts
    applied = {f["data"]["typical"] for f in pts if f["data"].get("typical")}
    for example in sorted({t["ref"].split(".")[1] for t in typicals} - applied):
        rows = [t for t in typicals if t["ref"].split(".")[1] == example]
        text = (f"Typical point list {example} ({len(rows)} points) matched no controller on the riser, so none of "
                "its points were created. The riser may name these units another way than the typical.")
        log(f"Coverage: {text}")
        facts.append({"id": f"issue:coverage-submittal-typical-{example}", "kind": "issue", "label": text,
                      "data": {"text": text, "severity": "coverage"}, "src": rows[0]["src"], "method": "rule",
                      "conf": 0.5, "step": "submittal", "ask": {"q": text, "field": None, "options": []}})
    facts += _room_check(rooms, placements, log)
    for r in rfis:
        text = f"{r['id']} from the contractor: {r['text']}"
        facts.append({"id": f"issue:{r['id']}", "kind": "issue", "label": text, "data": {"text": text, "severity": "rfi"},
                      "src": r["src"], "method": "parsed", "conf": 0.5, "step": "submittal",
                      "ask": {"q": text, "field": None, "options": []}})
    if rfis:
        log(f"{len(rfis)} RFIs and clarifications from the contractor, to read")
    if len(unread) > 0.1 * (len(points) + len(typicals)) and len(unread) >= 5:
        text = (f"{len(unread)} rows end with a point reference but were not read as points (e.g. "
                f"\"{unread[0]['text'][:70]}\"), against {len(points) + len(typicals)} read. The point table may use "
                "another layout (object types spelled out, other columns); these points wait for the AI reader.")
        log(f"Coverage: {text}")
        facts.append({"id": "issue:coverage-submittal-unread-points", "kind": "issue", "label": text,
                      "data": {"text": text, "severity": "coverage", "rows": len(unread)}, "src": unread[0]["src"],
                      "method": "rule", "conf": 0.5, "step": "submittal", "ask": {"q": text, "field": None,
                                                                                  "options": []}})
    return facts


def _sheet(ws) -> str:
    cands = [w.text for w in ws if re.fullmatch(r"C-\d{3}", w.text)]
    return cands[-1] if cands else pdfdoc.sheet_number(ws)


# A riser device named after a plant rather than a unit: CHW-PLANT, HW_SYS. The medium gives the Brick system and
# which scheduled units are its parts.
PLANT = re.compile(r"^(?P<medium>CHW|HHW|HW|CDW|CW)[-_ ]?(?:PLANT|SYS|SYSTEM)$", re.I)
PLANT_SYSTEM = {"CHW": ("Chilled_Water_System", "chilled water", ("Chiller", "Chilled_Water_Pump")),
                "HW": ("Hot_Water_System", "hot water", ("Boiler", "Hot_Water_Pump")),
                "HHW": ("Hot_Water_System", "hot water", ("Boiler", "Hot_Water_Pump")),
                "CW": ("Condenser_Water_System", "condenser water", ("Cooling_Tower", "Condenser_Water_Pump")),
                "CDW": ("Condenser_Water_System", "condenser water", ("Cooling_Tower", "Condenser_Water_Pump"))}


def _riser_unit(r: dict, by_normal: dict, riser: list[dict]) -> tuple[dict, list[dict]] | None:
    """Riser topology (W7) for a device that matches no scheduled unit, where the documents support a unit:
      - a plant (CHW-PLANT): a system of the medium's class, whose parts are the scheduled units of that medium
        (chillers and chilled water pumps); only when at least one such unit is scheduled;
      - a numbered unit of a named plan tag (EF-LAB-1, EF-LAB-2 on the riser, EF-LAB on the plans): a unit of its
        own with the plan unit's class, when the riser numbers two or more of them.
    Returns (the unit's equipment fact, its hasPart relation facts), or None."""
    dev = r["dev"]
    if m := PLANT.match(dev):
        cls, medium, part_classes = PLANT_SYSTEM[m["medium"].upper()]
        parts = [e for e in by_normal.values() if e["data"].get("class") in part_classes]
        if not parts:
            return None
        norm = re.sub(r"[^A-Z0-9]", "", dev.upper())
        why = (f"the riser's {dev} controls the {medium} plant: {', '.join(e['data']['tag'] for e in parts)} "
               "are its parts")
        unit = {"tag": dev, "normal": norm, "class": cls, "family": "system", "terminal": False, "schedule": "",
                "attrs": {"from": "riser", "medium": medium}, "note": why}
        rels = [{"src": norm, "rel": "hasPart", "dst": e["data"]["normal"], "medium": medium, "why": why}
                for e in parts]
        return unit, rels
    tag = tags.parse(dev)
    if not tag or not tag.suffix or tag.number:
        return None
    base = re.sub(r"\d+$", "", tag.normal)
    eq = by_normal.get(base)
    siblings = [x for x in riser if (t := tags.parse(x["dev"])) and re.sub(r"\d+$", "", t.normal) == base
                and t.normal != base]
    if not eq or base == tag.normal or len(siblings) < 2:
        return None
    n = tag.normal[len(base):]
    d = eq["data"]
    why = f"the riser numbers {len(siblings)} {d['tag']} units ({', '.join(x['dev'] for x in siblings)}): {dev} is one"
    unit = {"tag": f"{d['tag']}{n}", "normal": tag.normal, "class": d.get("class"), "family": d.get("family"),
            "terminal": bool(d.get("terminal")), "schedule": "", "attrs": {"from": "riser", "numbered_from": d["tag"]},
            "note": why}
    return unit, []


def _devices(riser, equipment, log) -> list[dict]:
    by_normal = {e["data"]["normal"]: e for e in equipment}
    out = []
    unmatched = 0
    for r in riser:
        norm = tags.normal(r["dev"])
        eq = by_normal.get(norm) if norm else None
        data = {"device": r["dev"], "controller": r["ctrl"], "trunk": r["trunk"], "trunk_name": r.get("trunk_name"),
                "address": int(r["addr"]),
                "instance": int(r["inst"]), "location": r["loc"], "equip": eq["data"]["normal"] if eq else None}
        conf, ask = 0.95, None
        if eq and eq["data"]["tag"] != r["dev"]:
            data["note"] = f"named {r['dev']} in the BMS, {eq['data']['tag']} on the drawings: same tag"
        if not eq and (made := _riser_unit(r, by_normal, riser)):
            unit, rels = made
            data["equip"], data["note"] = unit["normal"], unit["note"]
            conf = 0.8  # proposed: the riser alone says so, a person or a second source confirms
            out.append({"id": f"equip:riser:{unit['normal']}", "kind": "equipment", "label": unit["tag"],
                        "data": unit, "src": r["src"], "method": "rule", "conf": conf, "step": "submittal",
                        "ask": None})
            for rel in rels:
                out.append({"id": f"rel:{rel['src']}:hasPart:{rel['dst']}", "kind": "relation",
                            "label": f"{unit['tag']} has part {by_normal[rel['dst']]['data']['tag']}", "data": rel,
                            "src": r["src"], "method": "rule", "conf": conf, "step": "submittal", "ask": None})
            log(f"Riser: {unit['note']}")
        elif not eq:
            unmatched += 1
            conf = 0.5
            stem = (norm or re.sub(r"[^A-Z]", "", r["dev"]))[:4]
            near = [e for n, e in by_normal.items() if stem and n.startswith(stem[:3])][:4]
            options = [{"value": e["data"]["normal"], "label": f"It is {e['data']['tag']}"} for e in near]
            options.append({"value": "__new__", "label": "A unit of its own (not in the schedules)"})
            ask = {"q": f"The submittal has controller {r['dev']} ({r['ctrl']}, {r['loc']}) that matches no scheduled "
                        "equipment. What is it?", "field": "equip", "options": options}
        out.append({"id": f"ctrl:{r['dev']}", "kind": "controller", "label": f"{r['dev']} · {r['ctrl']}",
                    "data": data, "src": r["src"], "method": "parsed", "conf": conf, "step": "submittal", "ask": ask})
    log(f"Controllers: {len(riser)} on the riser, {len(riser) - unmatched} linked to scheduled equipment"
        + (f", {unmatched} to identify" if unmatched else ""))
    return out


def _points(points, typicals, riser, log) -> list[dict]:
    rows = list(points)
    by_example: dict[str, list] = {}
    for t in typicals:
        by_example.setdefault(t["ref"].split(".")[1], []).append(t)
    for example, tmpl in by_example.items():
        prefix = tags.parse(example).prefix if tags.parse(example) else None
        units = [r for r in riser if tags.parse(r["dev"]) and tags.parse(r["dev"]).prefix == prefix]
        for u in units:
            for t in tmpl:
                rows.append(t | {"ref": t["ref"].replace("FC-x", u["trunk"]).replace(f".{example}.", f".{u['dev']}."),
                                 "typical": example})
        log(f"Typical {example}: {len(tmpl)} points applied to {len(units)} {prefix} controllers")
    out = []
    seen = set()
    for r in rows:
        if r["ref"] in seen:
            continue
        seen.add(r["ref"])
        device = r["ref"].split(".")[1]
        cls, c = classify(r["desc"], r["pt"])
        term = by_term(r["desc"], r["pt"]) is not None
        conf = point_conf(cls, c, step="submittal", base=0.55, cap=0.95, term=term)
        out.append({"id": f"pt:{r['ref']}", "kind": "point", "label": f"{device}.{r['pt']}",
                    "data": {"ref": r["ref"], "device": device, "short": r["pt"], "description": r["desc"],
                             "io": r["io"], "units": r.get("units") or "", "object": r.get("obj") or "",
                             "object_instance": int(r["inst"]) if r.get("inst") else None,
                             "class": cls, "class_conf": c, "typical": r.get("typical"),
                             **({"term": True} if term else {})},
                    "src": r["src"], "method": "rule", "conf": conf, "step": "submittal", "ask": None})
    low = sum(1 for f in out if f["conf"] < 0.9)
    log(f"Points: {len(out)} ({len(points)} listed, {len(out) - len(points)} from typicals); "
        f"{len(out) - low} classified with confidence, {low} to review")
    return out


def _room_check(rows, placements, log) -> list[dict]:
    plan = {p["data"]["normal"]: p for p in placements}
    out, agree, differ = [], 0, 0
    for r in rows:
        norm = tags.normal(r["box"])
        p = plan.get(norm)
        plan_room = p["data"].get("room") if p else None
        data = {"tag": r["box"], "normal": norm, "room": r["room"], "floor": r["floor"], "room_name": r["name"],
                "plan_room": plan_room}
        if plan_room == r["room"]:
            agree += 1
            conf, ask, data["agree"] = 0.97, None, True
        elif p:
            differ += 1
            conf, data["agree"] = 0.5, False
            ask = {"q": f"Where is {r['box']}? The submittal's room schedule says {r['room']} {r['name']}; "
                        f"the floor plan reading says {plan_room}.", "field": "room",
                   "options": [{"value": r["room"], "label": f"{r['room']} (submittal)"},
                               {"value": plan_room, "label": f"{plan_room} (floor plan)"}]}
        else:
            conf, ask, data["agree"] = 0.85, None, None
        out.append({"id": f"rs:{norm}", "kind": "room_check", "label": f"{r['box']} serves room {r['room']}",
                    "data": data, "src": r["src"], "method": "parsed", "conf": conf, "step": "submittal", "ask": ask})
    if rows:
        log(f"Room schedule: {len(rows)} boxes — {agree} agree with the floor plans, {differ} differ (asked)")
    return out
