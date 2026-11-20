"""The sequences of operation as linked text: every unit tag, every word naming the sequence's own units, and every
point phrase in a sequence points at what it means in the building's knowledge graph, like the Sequences page of a
project (app/sequences.html).

    unit     a tag in the text (AHU-1, EF-LAB): the unit, if the schedules have it
    units    the words that name the sequence's units (VAV boxes, the air handler): every unit it applies to
    point    a point phrase (discharge air temperature, outside air damper): the points of those units that match it

A link is `ok` when the graph has what it names, `gap` when the sequence needs it and the graph does not (yet): a
point phrase is a gap until the controls submittal has given the units their points. Values with a unit (55 °F,
0.5 in.wc) are marked as setpoints. Rules only, no LLM.
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
