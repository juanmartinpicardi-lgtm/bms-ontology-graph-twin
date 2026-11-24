"""Equipment schedules -> equipment with nameplate data, and the first connections between them.

Rules:
1. A schedule row is a line that starts with an equipment tag. Its schedule is the nearest "... SCHEDULE" title
   above it whose columns it sits under.
2. The columns of a schedule are read with a layout (LAYOUTS below), chosen by words of the title. Layouts are the
   engineer's habits, not the building's: a new engineer may need a new layout. A row in a schedule with no layout
   keeps its raw values and is asked about.
3. The class comes from the tag (knowledge model), refined by the row: a VAVE with heater kW is electric reheat.
4. Checks: tags on the plans with no schedule row, rows with no tag on the plans, values that contradict each other.
5. Connections: with one AHU, it feeds every terminal unit; chillers feed the AHUs with a chilled water coil; pumps
   feed the chillers. Pages with no schedule (piping and control diagrams) count as evidence when they show the tags
   together.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import pdfdoc, tags

# Columns after the tag, in order. "-" in a cell is an empty value. Names ending in _cfm, _kw... are numbers.
LAYOUTS = [
    ("FAN POWERED", ["make", "model", "unit_size", "inlet", "cooling_cfm", "min_cfm", "fan_type", "heating_cfm",
                     "fan_volts", "heat_kw", "leaving_air_f", "heater_volts"]),
    ("VAV TERMINAL", ["make", "model", "inlet", "cooling_cfm", "heating_cfm", "min_cfm", "heat_kw", "leaving_air_f",
                      "heater_volts"]),
    ("CHILLER", ["make", "model", "tons", "ambient_f", "gpm", "pressure_drop_ft", "ewt_f", "lwt_f", "volts"]),
    ("PUMP", ["make", "model", "suction", "discharge", "gpm", "head_ft", "hp", "rpm"]),
    ("MINI-SPLIT", ["make", "outdoor_model", "indoor_model", "design_db_wb", "heating_design", "cooling_mbh",
                    "heating_mbh", "volts"]),
    ("UNIT HEATER", ["make", "model", "kw", "amps", "breaker", "volts"]),
    ("AIR HANDLING", ["make", "supply_cfm", "outside_cfm", "supply_esp", "supply_fan_hp", "supply_volts",
                      "exhaust_cfm", "exhaust_esp", "exhaust_fan_hp", "exhaust_volts", "preheat_cfm", "preheat_ewt_lwt",
                      "preheat_kw", "preheat_volts", "cooling_sensible_mbh", "cooling_mbh", "cooling_eat",
                      "cooling_lat", "chw_ewt_lwt", "chw_gpm", "chw_wpd_ft", "humidifier_make", "humidifier_cfm",
                      "humidifier_lbs_hr", "humidifier_kw", "humidifier_volts", "weight_lbs"]),
    ("HYDRONIC SPECIALTIES", ["description"]),
]
TAG_LIKE = re.compile(r"^[A-Z]{1,6}-?\d+[A-Z]?(?:-\d+[A-Z]?)+$|^[A-Z]{1,6}-?\d+[A-Z]?$")  # letters then numbers
TWO_WORD_MAKES = {"BELL", "AMERICAN"}  # BELL & GOSSETT, AMERICAN WHEATLEY
SPECIALTY_CLASS = [("BUFFER TANK", "Chilled_Water_Storage_Tank"), ("EXPANSION TANK", "Chilled_Water_Thermal_Expansion_Tank"),
                   ("SEPERATOR", "Equipment"), ("SEPARATOR", "Equipment"), ("FEEDER", "Equipment")]


def read(paths: list[tuple[Path, str]], plan_tags: dict[str, dict], log) -> list[dict]:
    """`plan_tags`: normal tag -> its placement fact from the floor plans (may be empty)."""
    facts: list[dict] = []
    diagram_tags: dict[str, set[str]] = {}
    unread: list[tuple] = []
    for path, name in paths:
        for page in range(pdfdoc.page_count(path)):
            ws = pdfdoc.words(path, page)
            sheet = pdfdoc.sheet_number(ws)
            lines = pdfdoc.lines(ws, gap=45)
            titles = [l for l in lines if "SCHEDULE" in l.text and l.words[0].size >= 8 and not tags.parse(l.words[0].text)]
            rows = _rows(ws)
            src = {"file": name, "page": page, "sheet": sheet}
            if not rows:
                found = {t.normal for w in ws if (t := tags.parse(w.text))}
                diagram_tags[f"{sheet or name} p{page + 1}"] = found
                log(f"Page {page + 1} · {sheet}: no schedule rows; a diagram showing {len(found)} tags "
                    f"({', '.join(sorted(found)[:6])}{'…' if len(found) > 6 else ''})")
                continue
            got = [_row_fact(r, _title_for(r, titles), src) for r in rows]
            got = [f for f in got if f]
            # Rows under a schedule title that start with something tag-shaped the tag rules don't know (VAVE-1-07,
            # an owner's own scheme): read nothing from them, but count them so the step can say so.
            unread += [(r, src) for r in _tag_column(
                [r for r in _rows(ws, lambda t: bool(TAG_LIKE.match(t)) and not tags.parse(t)) if _title_for(r, titles)])]
            by_title: dict[str, int] = {}
            for f in got:
                by_title[f["data"]["schedule"]] = by_title.get(f["data"]["schedule"], 0) + 1
            for t, n in by_title.items():
                log(f"Page {page + 1} · {sheet}: {t.title()} — {n} rows")
            facts += got
    facts = _dedupe(facts)
    if len(unread) >= 3 and len(unread) > 0.1 * len(facts):
        examples = ", ".join(sorted({r.words[0].text for r, _ in unread})[:4])
        text = (f"{len(unread)} schedule rows start with a tag the rules don't recognise ({examples}…), against "
                f"{len(facts)} read. The tags may follow another scheme (floor in the tag, an owner's standard); add "
                "the scheme as a setup rule, or these rows wait for the AI reader.")
        log(f"Coverage: {text}")
        facts.append(_issue("coverage-schedules-unread-rows", text, unread[0][1] | {"bbox": unread[0][0].bbox},
                            severity="coverage"))
    facts += _checks(facts, plan_tags, log)
    facts += _connections(facts, diagram_tags, log)
    return facts


def _rows(ws, is_start=lambda t: tags.parse(t)) -> list[pdfdoc.Line]:
    """Schedule rows. Tables stand side by side with gaps no wider than the gaps between cells, so a row is anchored
    on its tag: a tag with nothing just left of it and cells to its right. The row runs to the next such tag on the
    same baseline (the first cell of the next table) or the end of the line. `is_start`: what counts as a tag."""
    def same_line(a, b):
        return abs(a.top - b.top) < 3

    starts = []
    for w in ws:
        if not is_start(w.text):
            continue
        line = [v for v in ws if same_line(v, w)]
        left = [v for v in line if v.x1 <= w.x0 and w.x0 - v.x1 < 30]
        right = [v for v in line if v.x0 >= w.x1 and v.x0 - w.x1 < 90]
        if not left and right:
            starts.append(w)
    rows = []
    for w in starts:
        nxt = min((s.x0 for s in starts if same_line(s, w) and s.x0 > w.x0), default=1e9)
        cells = sorted((v for v in ws if same_line(v, w) and w.x0 <= v.x0 < nxt), key=lambda v: v.x0)
        # stop at a wide gap: what follows belongs to a drawing note, not to the row
        out = [cells[0]]
        for v in cells[1:]:
            if v.x0 - out[-1].x1 > 120:
                break
            out.append(v)
        if len(out) >= 3:
            rows.append(pdfdoc.Line(tuple(out)))
    return rows


def _tag_column(rows: list[pdfdoc.Line]) -> list[pdfdoc.Line]:
    """Rows whose first cell is in a column of tags: at least 3 starts aligned on the left, all different, with one
    letter prefix (VAVE-1-01, VAVE-1-02...). A model number repeated down a column (KNUDB181A) is not a tag."""
    cols: dict[int, list[pdfdoc.Line]] = {}
    for r in rows:
        cols.setdefault(round(r.words[0].x0 / 6), []).append(r)
    out = []
    for col in cols.values():
        texts = [r.words[0].text for r in col]
        prefixes = {re.match(r"[A-Z]+", t).group() for t in texts}
        if len(col) >= 3 and len(set(texts)) == len(texts) and len(prefixes) == 1:
            out += col
    return out


def _title_for(row, titles):
    """The nearest title above the row that is centred over the row's span."""
    x0, x1, top = row.bbox[0], row.bbox[2], row.words[0].top
    above = [t for t in titles if t.words[0].top < top and x0 - 100 <= (t.bbox[0] + t.bbox[2]) / 2 <= x1 + 100]
    return min(above, key=lambda t: top - t.words[0].top, default=None)


def _row_fact(row, title, src) -> dict | None:
    tag = tags.parse(row.words[0].text)
    title_text = re.sub(r"\s+\d+\.\s.*$", "", title.text).strip() if title else ""
    tokens = [w.text for w in row.words[1:]]
    layout = next((cols for key, cols in LAYOUTS if key in title_text.upper()), None)
    attrs, ask, conf = {}, None, 0.95
    if layout and layout == ["description"]:
        attrs["description"] = " ".join(tokens)
    elif layout:
        attrs = _apply(layout, tokens)
    else:
        attrs["values"] = " ".join(tokens)
        conf = 0.6
        ask = {"q": f"{tag.text} is in a schedule I have no layout for ({title_text or 'no title found'}). "
                    "Keep it as equipment with its raw values?", "field": None, "options": []}
    cls, note = tag.cls, ""
    if tag.prefix == "VAVE":
        kw = attrs.get("heat_kw")
        if isinstance(kw, (int, float)) and kw > 0:
            cls, note, conf = "RVAV", f"VAVE with {kw} kW heater: electric reheat, not exhaust", min(conf, 0.93)
        else:
            cls, note, conf = "VAV", "VAVE without heater kW: exhaust VAV?", 0.6
            ask = {"q": f"{tag.text}: VAVE but no heater kW. Exhaust VAV or reheat box?", "field": "class",
                   "options": [{"value": "Exhaust_VAV", "label": "Exhaust VAV"},
                               {"value": "RVAV", "label": "Reheat VAV"}]}
    if tag.prefix == "HS":
        cls = next((c for k, c in SPECIALTY_CLASS if k in attrs.get("description", "")), "Equipment")
    data = {"tag": tag.text, "normal": tag.normal, "class": cls, "family": tag.family, "terminal": tag.terminal,
            "schedule": title_text or "untitled schedule", "attrs": attrs, "note": note}
    return {"id": f"equip:{tag.normal}", "kind": "equipment", "label": tag.text, "data": data,
            "src": src | {"bbox": row.bbox}, "method": "parsed", "conf": conf, "step": "schedules", "ask": ask}


def _apply(layout: list[str], tokens: list[str]) -> dict:
    toks = [t for t in tokens if not re.fullmatch(r"\(\d+\)", t)]  # (9) = quantity markers in the AHU schedule
    counts = re.findall(r"\((\d+)\)\s+(\S+)", " ".join(tokens))
    out: dict = {}
    i = 0
    for col in layout:
        if i >= len(toks):
            break
        if col in ("make", "humidifier_make"):
            if toks[i] in TWO_WORD_MAKES and i + 2 < len(toks) and toks[i + 1] == "&":
                out[col] = " ".join(toks[i:i + 3]).title()
                i += 3
                continue
            if toks[i] in TWO_WORD_MAKES:
                out[col] = " ".join(toks[i:i + 2]).title()
                i += 2
                continue
            out[col] = toks[i].title()
            i += 1
            continue
        out[col] = _value(toks[i])
        i += 1
    if counts and "supply_cfm" in layout:  # AHU: (9) 7 -> nine supply fans of 7 hp
        fans = [int(n) for n, v in counts if v == str(out.get("supply_fan_hp", "")).rstrip("0").rstrip(".") or v == str(out.get("supply_fan_hp"))]
        if fans:
            out["supply_fans"] = fans[0]
    return {k: v for k, v in out.items() if v is not None}


def _value(t: str):
    if t in ("-", "--"):
        return None
    try:
        return int(t) if re.fullmatch(r"\d+", t) else float(t) if re.fullmatch(r"\d*\.\d+", t) else t
    except ValueError:
        return t


def _dedupe(facts):
    seen = {}
    for f in facts:
        seen.setdefault(f["id"], f)
    return list(seen.values())


# ---------------------------------------------------------------- checks

def _issue(id_, text, src, severity="check"):
    return {"id": f"issue:{id_}", "kind": "issue", "label": text, "data": {"text": text, "severity": severity},
            "src": src, "method": "rule", "conf": 0.5, "step": "schedules",
            "ask": {"q": text, "field": None, "options": []}}


def _checks(equip, plan_tags, log) -> list[dict]:
    out = []
    scheduled = {f["data"]["normal"]: f for f in equip if f["kind"] == "equipment"}
    if plan_tags:
        missing = sorted(set(plan_tags) - set(scheduled), key=_natural)
        if missing:
            shown = ", ".join(plan_tags[n]["data"]["tag"] for n in missing)
            src = plan_tags[missing[0]]["src"]
            out.append(_issue("no-schedule", f"On the floor plans but in no schedule: {shown}. Their size, make and "
                                             "model are unknown; ask the engineer for the schedule.", src))
            log(f"Check: {len(missing)} tags on the plans have no schedule row ({shown})")
            for n in missing:  # still equipment: the plan shows it, the tag gives its class
                p = plan_tags[n]
                tag = tags.parse(p["data"]["tag"])  # None for a form the knowledge model can't read yet (the AI
                # plan reader's FC-1.16, SAV-3): the unit stays, with no class
                out.append({"id": f"equip:{n}", "kind": "equipment", "label": p["data"]["tag"],
                            "data": {"tag": p["data"]["tag"], "normal": n, "class": tag.cls if tag else None,
                                     "family": tag.family if tag else None,
                                     "terminal": tag.terminal if tag else False, "schedule": "", "attrs": {},
                                     "note": "drawn on the plans, in no schedule: class from the tag only"},
                            "src": p["src"], "method": "rule", "conf": 0.8, "step": "schedules", "ask": None})
        off_plan = sorted(set(scheduled) - set(plan_tags), key=_natural)
        if off_plan:
            log(f"Note: {len(off_plan)} scheduled units are not drawn on the floor plans "
                f"({', '.join(scheduled[n]['data']['tag'] for n in off_plan)})")
    for f in scheduled.values():
        a = f["data"]["attrs"]
        h, m = a.get("heating_cfm"), a.get("min_cfm")
        if isinstance(h, (int, float)) and isinstance(m, (int, float)) and f["data"]["family"] == "fvav" and h < m:
            out.append(_issue(f"heating-below-min-{f['data']['normal']}",
                              f"{f['data']['tag']}: heating airflow {h} cfm is below its minimum primary {m} cfm. "
                              "Typo in the schedule?", f["src"]))
            log(f"Check: {f['data']['tag']} heating cfm {h} < minimum {m}")
    return out


def _natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ---------------------------------------------------------------- connections

def _rel(src_f, rel, dst_f, medium, conf, why, ask=None):
    s, d = src_f["data"], dst_f["data"]
    return {"id": f"rel:{s['normal']}:{rel}:{d['normal']}", "kind": "relation",
            "label": f"{s['tag']} {rel} {d['tag']}",
            "data": {"src": s["normal"], "rel": rel, "dst": d["normal"], "medium": medium, "why": why},
            "src": src_f["src"], "method": "rule", "conf": conf, "step": "schedules", "ask": ask}


def _connections(facts, diagram_tags, log) -> list[dict]:
    eq = [f for f in facts if f["kind"] == "equipment"]
    fam = lambda name: [f for f in eq if f["data"]["family"] == name]  # noqa: E731
    ahus, terminals = fam("ahu"), [f for f in eq if f["data"]["terminal"]]
    chillers, pumps = fam("chiller"), fam("pump")
    together = lambda a, b: any(a in s and b in s for s in diagram_tags.values())  # noqa: E731
    out = []
    if len(ahus) == 1:
        for t in terminals:
            out.append(_rel(ahus[0], "feeds", t, "air", 0.9, "the only air handler in the schedules"))
        log(f"Connected: {ahus[0]['data']['tag']} feeds {len(terminals)} terminal units (the only AHU)")
    elif ahus and terminals:
        log(f"{len(ahus)} AHUs: which one feeds each terminal unit needs the duct plans; left for review")
    for c in chillers:
        for a in ahus:
            if a["data"]["attrs"].get("chw_gpm"):
                seen = together(c["data"]["normal"], a["data"]["normal"])
                out.append(_rel(c, "feeds", a, "chilled water", 0.92 if seen else 0.8,
                                "AHU has a chilled water coil" + (", both on the piping diagram" if seen else "")))
        for p in pumps:
            seen = together(p["data"]["normal"], c["data"]["normal"])
            out.append(_rel(p, "feeds", c, "chilled water", 0.92 if seen else 0.75,
                            "chilled water pump" + (", both on the piping diagram" if seen else "")))
    if chillers:
        log(f"Connected: chilled water from {len(pumps)} pumps through {len(chillers)} chillers to the AHU coil")
    return out
