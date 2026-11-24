"""The sequences of operation as linked text: every unit tag, every word naming the sequence's own units, and every
point phrase in a sequence points at what it means in the building's knowledge graph, like the Sequences page of a
project (app/sequences.html).

    unit     a tag in the text (AHU-1, EF-LAB): the unit, if the schedules have it
    units    the words that name the sequence's units (VAV boxes, the air handler): every unit it applies to
    point    a point phrase (discharge air temperature, outside air damper): the points of those units that match it

A link is `ok` when the graph has what it names, `gap` when the sequence needs it and the graph does not (yet): a
point phrase is a gap until the controls submittal has given the units their points. Values with a unit (55 °F,
0.5 in.wc) are marked as setpoints. Rules only, no LLM.

Control logic (W8, below `payload`): the same links, one step further, as relations between points.

    candidates(b, seq)   the ids a sequence's logic may use: <TYPE>.<short> for a point of a unit type (AHU.DA-T,
                         VAV.ZN-T), unit:<TYPE> for equipment, role:<TYPE>.<role> for a template slot the units lack
    rule_relations(q)    rules alone: "X shall modulate to maintain <phrase>" is a loop, "interlocked with AHU01" an
                         interlock, "if <device> trips, <fans> shall be shut down" a safety
    edges(b, logic)      the relations as graph edges between the building's points (each relation applied to every
                         unit of its type), for the setup's own source `setup:sequence_logic`
The model's reading of the same sections is intake/sequence_ai.py (job `sequence_read`).
"""
from __future__ import annotations

import re

from . import tags

# Phrases a sequence uses for points, longest first when matched. Each is looked up among the points of the units
# the sequence applies to (every word of the phrase in the point's description), then classed with the knowledge
# model's matcher for what the sequence implies.
POINT_PHRASES = [
    "discharge air temperature", "supply air temperature", "mixed air temperature", "return air temperature",
    "outside air temperature", "outdoor air temperature", "zone temperature", "space temperature",
    "room temperature", "zone humidity", "space humidity", "relative humidity", "duct static pressure",
    "building static pressure", "discharge static pressure", "static pressure", "differential pressure",
    "carbon dioxide", "CO2", "airflow", "air flow", "supply fan speed", "exhaust fan speed", "supply fan status",
    "outside air damper", "outdoor air damper", "return air damper", "exhaust air damper", "minimum outdoor air",
    "damper position", "reheat valve", "heating valve", "cooling valve", "chilled water valve", "hot water valve",
    "electric heat", "chilled water supply temperature", "chilled water return temperature",
    "hot water supply temperature", "occupancy sensor", "filter", "smoke detector", "freezestat", "freeze stat",
    "humidity", "zone temperature setpoint", "cooling setpoint", "heating setpoint",
]
# Words that name the sequence's own units, by family.
UNIT_WORDS = {
    "ahu": r"air handling units?|air handlers?|AHUs?\b",
    "vav": r"(?:VAV |terminal )(?:boxes|box|units?)|VAVs?\b",
    "fvav": r"(?:fan powered |FVAV |VAV )?(?:terminal units?|boxes|box)|FVAVs?\b|VAVs?\b",
    "ef": r"exhaust fans?|EFs?\b",
    "chiller": r"chillers?|chilled water pumps?",
    "boiler": r"boilers?",
    "fcu": r"fan coil units?|FCUs?\b",
    "pump": r"(?:chilled water |hot water |condenser water )?pumps?\b",
}
TAGLIKE = re.compile(r"\b[A-Z]{2,5}-?[A-Z]*\d*[A-Z]?\b")
VALUE = re.compile(r"[-+]?\d+(?:\.\d+)?\s*(?:degrees?(?: F)?|deg ?F|°F|%\s*RH|%|”\s*wc|\"\s*wc|in\.?\s*wc|gpm|cfm|"
                   r"minutes?|min)\b", re.I)


SAME = {"outdoor": "outside", "oa": "outside", "temp": "temperature", "rh": "humidity", "sp": "setpoint",
        "stpt": "setpoint", "co2": "co2", "dioxide": "co2", "flow": "airflow"}


def _words(s: str) -> list[str]:
    return [SAME.get(w, w) for w in re.findall(r"[a-z0-9]+", s.lower())]


def payload(b: dict, classify=None) -> dict:
    """Every sequence of the building with its sections as segments [{t}, {t, ref}, {t, value}], and the refs."""
    equip = b["equip"]
    by_tag = {e["tag"].upper(): e for e in equip.values()}
    by_normal = {n: e for n, e in equip.items()}
    by_device = {e["controller"]["device"]: n for n, e in equip.items() if e.get("controller")}
    pts_of: dict[str, list[dict]] = {}
    for p in b["points"]:
        n = by_device.get(p["data"]["device"])
        if n:
            pts_of.setdefault(n, []).append(p)
    phrase_re = re.compile(r"(?<![\w-])(" + "|".join(re.escape(p) for p in sorted(POINT_PHRASES, key=len, reverse=True))
                           + r")(?![\w-])", re.I)
    out = []
    for s in b["sequences"]:
        d = s["data"]
        units = [by_tag[t.upper()] for t in d["applies_to"] if t.upper() in by_tag]
        refs: dict[str, dict] = {}

        def unit_ref(e: dict) -> str:
            key = f"unit:{e['normal']}"
            refs.setdefault(key, {"kind": "equipment", "label": e["tag"], "node": key, "fact": e["fact"],
                                  "cls": e["class"], "status": "ok", "points": e["points"]})
            return key

        def point_ref(phrase: str) -> str:
            key = "pt:" + " ".join(_words(phrase))
            if key in refs:
                return key
            want = set(_words(phrase)) - {"air", "the"} or set(_words(phrase))
            cls = classify(phrase, "")[0] if classify else None
            if cls and not want <= set(_words(cls.replace("_", " "))):
                cls = None  # the matcher's guess does not say what the phrase says: no implied class
            hits = []
            for e in units:
                for p in pts_of.get(e["normal"], []):
                    pd = p["data"]
                    have = set(_words(pd["description"])) | set(_words(pd.get("short") or ""))
                    if want <= have or (cls and pd["class"] == cls):
                        hits.append({"node": f"pt:{pd['ref']}", "label": pd.get("short") or pd["ref"].split(".")[-1],
                                     "unit": e["tag"], "fact": p["id"], "cls": pd["class"],
                                     "description": pd["description"]})
            refs[key] = {"kind": "point", "label": phrase.lower() if phrase != "CO2" else phrase, "cls": cls,
                         "points": hits[:60], "count": len(hits), "status": "ok" if hits else "gap",
                         "fact": hits[0]["fact"] if hits else None, "node": hits[0]["node"] if hits else None}
            return key

        words = UNIT_WORDS.get(d.get("family") or "")
        unit_re = re.compile(rf"(?<![\w-])({words})(?![\w-])", re.I) if words and units else None
        all_key = f"units:{s['id']}"
        if unit_re:
            refs[all_key] = {"kind": "units", "label": f"{len(units)} units", "status": "ok",
                             "units": [unit_ref(e) for e in units]}

        def segments(text: str) -> list[dict]:
            spans = []  # (start, end, seg)
            for m in phrase_re.finditer(text):
                spans.append((m.start(), m.end(), {"t": m.group(0), "ref": point_ref(m.group(1))}))
            if unit_re:
                for m in unit_re.finditer(text):
                    spans.append((m.start(), m.end(), {"t": m.group(0), "ref": all_key}))
            for m in TAGLIKE.finditer(text):
                t = tags.parse(m.group(0))
                if not t:
                    continue
                e = by_tag.get(m.group(0).upper()) or by_normal.get(t.normal)
                if e:
                    spans.append((m.start(), m.end(), {"t": m.group(0), "ref": unit_ref(e)}))
                else:
                    key = f"unit:?{t.normal}"
                    refs.setdefault(key, {"kind": "equipment", "label": m.group(0), "status": "gap", "cls": t.cls})
                    spans.append((m.start(), m.end(), {"t": m.group(0), "ref": key}))
            for m in VALUE.finditer(text):
                spans.append((m.start(), m.end(), {"t": m.group(0), "value": True}))
            spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
            segs, at = [], 0
            for a, z, seg in spans:
                if a < at:
                    continue  # overlaps a longer match already taken
                if a > at:
                    segs.append({"t": text[at:a]})
                segs.append(seg)
                at = z
            if at < len(text):
                segs.append({"t": text[at:]})
            return segs

        sections = [{"letter": x["letter"], "title": x["title"],
                     "segs": segments(re.sub(r"\s+", " ", x["text"]).strip())} for x in d["sections"]]
        found = {"ok": 0, "gap": 0}
        for r in refs.values():
            found[r["status"]] = found.get(r["status"], 0) + 1
        out.append({"id": s["id"], "fact": s["id"], "title": d["title"], "family": d.get("family"),
                    "status": s["status"], "conf": s["conf"],
                    "applies": [unit_ref(e) for e in units],
                    "missing": [t for t in d["applies_to"] if t.upper() not in by_tag],
                    "setpoints": d.get("setpoints", []), "sections": sections, "refs": refs, "found": found,
                    "src": {"file": s["src"].get("file"), "sheet": s["src"].get("sheet"),
                            "page": s["src"].get("page")}})
    return {"sequences": out}


# --- control logic (W8): candidates, rules alone, graph edges ----------------------------------------------------

TYPE_NUMBER = re.compile(r"[-_ ]?\d+[A-Za-z]?$")
FAMILY_TEMPLATE = {"vav": "vav", "fvav": "vav", "ahu": "ahu", "fcu": "fcu", "chiller": "chiller", "boiler": "boiler",
                   "pump": "pump"}
# A plant controller the riser does not tie to one unit (CHW-PLANT) belongs to the sequence of its plant.
PLANT_WORDS = {"chiller": ("CHW", "CHILL"), "boiler": ("HW", "BOIL")}
STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "from", "with", "by", "is", "be", "shall", "will",
        "should", "as", "at", "all", "each", "unit", "its", "required", "requirements"}
OUTPUT_IO = ("AO", "BO")
INPUT_IO = ("AI", "BI")


def type_of(tag: str) -> str:
    """The unit type a tag or device names: the tag without its number (AHU01 -> AHU, CH01a -> CH, VAVE-07 -> VAVE,
    EF-LAB-1 -> EF-LAB, EF-RR -> EF-RR)."""
    t = tag.strip().upper()
    return TYPE_NUMBER.sub("", t) or t


def _content(s: str) -> set[str]:
    return {w for w in _words(re.sub(r"\(.*?\)", " ", s)) if w not in STOP and not w.isdigit()}


def _slot(template, cls: str | None, description: str) -> str | None:
    """The template slot a point fills: a slot whose words the description has first, then a slot without words."""
    if not template or not cls:
        return None
    low = description.lower()
    for s in template.slots:
        if cls in s.classes and s.words and any(w in low for w in s.words):
            return s.role
    return next((s.role for s in template.slots if cls in s.classes and not s.words), None)


def candidates(b: dict, seq: dict, km=None) -> dict:
    """The ids one sequence's logic may use, from what the building has now (intake/model.building):

    points    <TYPE>.<short>: a point of the sequence's units, one id per point of a unit type (typicals are one id;
              the terminal units of one sequence are one type, VAV and VAVE -> VAV), with how many units have it
    related   the same for units the sequence is tied to: the schedules' feeds both ways, tags and unit words in its text
    units     unit:<TYPE>: the equipment (the end of ba:requests)
    roles     role:<TYPE>.<role>: the template slots no point of the units fills (a step that needs one is a gap)
    refs      per id, the graph node of every unit's point (pt:<ref>) or unit (unit:<normal>), for the edges"""
    d = seq["data"]
    equip = b["equip"]
    by_tag = {e["tag"].upper(): n for n, e in equip.items()}
    own = [by_tag[t.upper()] for t in d["applies_to"] if t.upper() in by_tag]
    group: dict[str, str] = {}
    if own and all(equip[n]["terminal"] for n in own):  # typicals with options (VAV and VAVE): one type
        g = min({type_of(equip[n]["tag"]) for n in own}, key=lambda t: (len(t), t))
        group = dict.fromkeys(own, g)
    else:
        group = {n: type_of(equip[n]["tag"]) for n in own}
    own_types = set(group.values())
    text = " ".join(f"{x['title']}: {x['text']}" for x in d["sections"])
    related: set[str] = set()
    for r in b["relations"]:
        rd = r["data"]
        if rd["rel"] == "feeds" and rd["src"] in equip and rd["dst"] in equip:
            if rd["src"] in group:
                related.add(rd["dst"])
            if rd["dst"] in group:
                related.add(rd["src"])
    for m in TAGLIKE.finditer(text):
        t = tags.parse(m.group(0))
        n = by_tag.get(m.group(0).upper()) or (t.normal if t and t.normal in equip else None)
        if n:
            related.add(n)
    for fam, words in UNIT_WORDS.items():
        if fam != d.get("family") and re.search(rf"(?<![\w-])({words})(?![\w-])", text, re.I):
            related |= {n for n, e in equip.items() if e["family"] == fam}
    for n in sorted(related - set(group)):
        if equip[n].get("status") != "rejected":
            group[n] = type_of(equip[n]["tag"])
    plant = PLANT_WORDS.get(d.get("family") or "", ())
    by_device = {e["controller"]["device"]: n for n, e in equip.items() if e.get("controller")}
    size: dict[str, set] = {}
    for n, g in group.items():
        size.setdefault(g, set()).add(n)
    points: dict[str, dict] = {}
    for p in b["points"]:
        if p.get("status") == "rejected":
            continue
        pd = p["data"]
        dev = pd.get("device") or ""
        n = by_device.get(dev)
        if n in group:
            g, unit, own_pt = group[n], n, group[n] in own_types and n in own
        elif n is None and dev and (type_of(dev) in own_types or any(w in dev.upper() for w in plant)):
            g, unit, own_pt = type_of(dev), dev, True  # a controller of the plant the riser ties to no unit
            size.setdefault(g, set()).add(dev)
        else:
            continue
        short = pd.get("short") or pd["ref"].rsplit(".", 1)[-1]
        if short.upper().startswith(dev.upper() + "-"):
            short = short[len(dev) + 1:]
        pid = f"{g}.{short}"
        c = points.setdefault(pid, {"id": pid, "type": g, "short": short, "description": pd.get("description") or short,
                                    "cls": pd.get("class"), "io": (pd.get("io") or "").upper(), "own": own_pt,
                                    "units": [], "refs": {}})
        c["units"].append(equip[unit]["tag"] if unit in equip else unit)
        c["refs"][unit] = f"pt:{pd['ref']}"
    with_points: dict[str, set] = {}  # a unit with no point at all (EF-LAB, whose fans have controllers of their own)
    for c in points.values():  # does not count against its type's coverage
        with_points.setdefault(c["type"], set()).update(c["refs"])
    for c in points.values():
        c["of"] = len(with_points[c["type"]])
        c["setpoint"] = ("setpoint" in _words(c["description"]) or (c["cls"] or "").endswith("_Setpoint")
                         or c["short"].upper().endswith("-SP"))
    units = {}
    for n, g in group.items():
        u = units.setdefault(f"unit:{g}", {"id": f"unit:{g}", "type": g, "units": [], "refs": {},
                                           "cls": equip[n]["class"], "family": equip[n]["family"],
                                           "own": g in own_types})
        u["units"].append(equip[n]["tag"])
        u["refs"][n] = f"unit:{n}"
    roles = {}
    if km is not None:
        for g in sorted(own_types):
            fam = next(equip[n]["family"] for n, x in group.items() if x == g)
            tpl = km.templates.get(FAMILY_TEMPLATE.get(fam, ""))
            if not tpl:
                continue
            filled = set()
            for c in points.values():
                if c["type"] == g and (role := _slot(tpl, c["cls"], c["description"])):
                    c["role"] = role
                    filled.add(role)
            for s in tpl.slots:
                if s.role not in filled:
                    roles[f"role:{g}.{s.role}"] = {"id": f"role:{g}.{s.role}", "type": g, "role": s.role,
                                                    "classes": list(s.classes),
                                                    "setpoint": all(x.endswith("Setpoint") for x in s.classes)}
    return {"seq": seq["id"], "title": d["title"], "family": d.get("family"), "applies_to": d["applies_to"],
            "types": sorted(own_types), "points": points, "units": units, "roles": roles,
            "sections": d["sections"], "src": seq["src"]}


# rules alone: three sentence shapes ------------------------------------------------------------------------------

LOOP = re.compile(r"(?P<subj>[A-Za-z][\w \-/]*?)\s+(?:shall|will|should)\s+(?:[\w ,]*?\s)?(?:modulate|operate|control)\b"
                  r".*?\bto\s+maintain\s+(?:a|an|the)?\s*(?:maximum\s+|minimum\s+|positive\s+)?"
                  r"(?P<var>[A-Za-z][A-Za-z \-]*?)(?=\s+(?:of|at|setpoint|in|requirements)\b|\s*[.,(+]|\s*\d|$)", re.I)
INTERLOCK = re.compile(r"interlocked with (?:the\s+)?(?P<tag>[A-Z][A-Z0-9\-]+)", re.I)
SAFETY = re.compile(r"(?:if|when)\s+(?:the|a|an)?\s*(?P<cond>[^,]+?)\s+(?:senses|is triggered|is tripped|trips|is in alarm)"
                    r"\b.*?[\s,]the\s+(?P<tgt>[^.,]+?)\s+shall\s+be\s+(?:shut ?down|shut|closed|disabled|off)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[a-z0-9%)”\"])\.\s+|\s\d{1,2}\.\s+|\s[a-z]\.\s+", " " + text) if s.strip()]


def _match(c: dict, phrase: str, want: str, types: set[str] | None = None) -> str | None:
    """The point whose description best covers a phrase: want is output (AO/BO), input (AI/BI) or setpoint."""
    words = _content(phrase)
    if not words:
        return None
    best, score = None, 0.0
    for p in c["points"].values():
        if types and p["type"] not in types:
            continue
        if want == "output" and p["io"] not in OUTPUT_IO:
            continue
        if want == "input" and (p["io"] not in INPUT_IO or p["setpoint"]):
            continue
        if want == "setpoint" and not p["setpoint"]:
            continue
        have = _content(p["description"]) | _content(p["short"].replace("-", " "))
        hit = len(words & have)
        s = hit / min(len(words), len(have) or 1) + (0.01 if p["io"] == "BO" else 0)
        if hit and s > score:
            best, score = p["id"], s
    return best if score >= 0.5 else None


def rule_relations(c: dict) -> list[dict]:
    """Control relations the rules read from a sequence's sections (rules alone: the bake-off's baseline)."""
    out, seen = [], set()

    def add(a, rel, z, kind, sec, why, loop=""):
        if a and z and a != z and (a, rel, z) not in seen:
            seen.add((a, rel, z))
            out.append({"from": a, "rel": rel, "to": z, "kind": kind, "loop": loop, "section": sec["letter"],
                        "confidence": 0.6, "why": why[:200], "method": "rule"})

    own = set(c["types"])
    for sec in c["sections"]:
        title_t = type_of(sec["title"])  # EF-RR: a section that is one unit's own sequence
        types = {title_t} if title_t in own else own
        for s in _sentences(re.sub(r"\s+", " ", sec["text"])):
            for m in LOOP.finditer(s):
                subj = re.split(r",", m.group("subj"))[-1]
                var = m.group("var")
                out_id = _match(c, subj, "output", types)
                meas = _match(c, var, "input", types)
                sp = _match(c, var + " setpoint", "setpoint", types)
                if out_id and meas:
                    add(meas, "feedback", out_id, "loop", sec, s, var.strip())
                    add(sp, "drives", out_id, "loop", sec, s, var.strip())
            for m in INTERLOCK.finditer(s):
                other = {type_of(m.group("tag"))}
                proof = (_match(c, "supply fan status", "input", other) or _match(c, "status", "input", other))
                cmd = _match(c, "start stop enable", "output", types)
                add(proof, "requires", cmd, "interlock", sec, s)
            for m in SAFETY.finditer(s):
                cond = _match(c, m.group("cond"), "input", own)
                for t in re.split(r",|\band\b", m.group("tgt")):
                    add(cond, "requires", _match(c, t, "output", own), "interlock", sec, s)
    return out


# graph edges ----------------------------------------------------------------------------------------------------

def _nodes(c: dict, cid: str) -> dict[str, str]:
    """unit (normal or device) -> graph node id, for a point or unit id of the candidate list."""
    x = c["points"].get(cid) or c["units"].get(cid)
    return dict(x["refs"]) if x else {}


def edges(cands: dict[str, dict], logic: dict[str, list[dict]], present: set[str]) -> tuple[list, list[dict]]:
    """Each relation of each sequence as edges between the building's nodes: on every unit of its type (a VAV loop on
    each of the 38 boxes); a single unit's point to every unit of the other type (AHU01's schedule switches each box);
    two plant types with each other (the 2 pumps' status and the 2 chillers' enable). An end that is not in the graph
    (a role the units lack, a plant controller no unit owns) is not stored, only counted. Returns (edges, skipped)."""
    from ..db.store import Edge

    found: dict[tuple, Edge] = {}
    skipped = []
    for sid, rels in logic.items():
        c = cands[sid]
        src = c["src"]
        for r in rels:
            a, z = _nodes(c, r["from"]), _nodes(c, r["to"])
            if a.keys() == z.keys():
                pairs = [(a[u], z[u]) for u in a]
            elif len(a) == 1 or len(z) == 1:
                pairs = [(x, y) for x in a.values() for y in z.values()]
            else:
                common = a.keys() & z.keys()
                pairs = ([(a[u], z[u]) for u in common] if common else
                         [(x, y) for x in a.values() for y in z.values()])
            pairs = [(x, y) for x, y in pairs if x in present and y in present and x != y]
            if not pairs:
                skipped.append({"sequence": sid, "from": r["from"], "rel": r["rel"], "to": r["to"],
                                "why": "an end is not in the graph"})
                continue
            ref = " ".join(x for x in (src.get("sheet") or "",
                                       f"page {src['page'] + 1}" if src.get("page") is not None else "") if x)
            for x, y in pairs:
                key = (x, r["rel"], y)
                if key in found:
                    continue
                attrs = {"intent": True, "sequence": sid, "section": r.get("section"), "kind": r.get("kind"),
                         "ids": [r["from"], r["to"]], "why": r.get("why", "")}
                attrs |= {k: r[k] for k in ("loop", "model", "rule_agrees", "raw", "calibrated") if r.get(k)}
                found[key] = Edge(x, r["rel"], y, src.get("file") or "sequences",
                                  f"{ref} · {c['title']} {r.get('section') or ''}.".strip(), r.get("method", "llm"),
                                  float(r["confidence"]), attrs)
    return list(found.values()), skipped
