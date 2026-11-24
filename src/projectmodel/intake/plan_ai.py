"""The AI plan reader (plan-workflow-ai W6, §6.2 row 1): the `plan_meaning` job on top of the floor-plan rules.

Candidates in, ids out (§6.1):
1. Pages. Page sorting (`pages.py`) picks the pages worth a call: the pages the rules read as a floor, the plan pages
   of the mechanical (or an unnamed) discipline, then pages the rules could not sort (the model sorts those as it
   reads them). At most MAX_PAGES per file.
2. Candidates from the text layer (`pdfdoc.words`), each with an id: room label candidates R1… (a number such as
   154, 1205 or 216B, with the words printed just above and below it) and equipment tag candidates T1… (AHU-1,
   FC-1.16, a two-line hexagon "SAV" over "3", a sensor callout "(SAV-3)"), with where each occurrence is drawn.
3. The page image at a known DPI (`pdfdoc.page_image`), cropped to the drawing, the ids drawn beside the candidates.
4. The model answers the page kind, the floor of each view, which candidates are rooms (with the name copied from
   the words given), and the room each tag serves or sits in, by id, with a confidence.
5. Rules check every answer: an id we never gave is dropped; a name whose words are not printed next to the label is
   dropped; a floor that is not one of the sheet's views, a room number that does not start with its level digit, or
   a room far from every occurrence of its tag lowers the confidence; a room box that does not hold its label is
   dropped.
6. The confidence is calibrated per job, model and kind (`calibration.py`, fitted by `scripts/eval.py plan_meaning
   --fit`) and capped at AI_CAP, below auto-accept: the answers are proposals. They merge with the rules' facts:
   agreement keeps or raises the rules' confidence and settles their question; a disagreement becomes the model's
   proposal with the rules' answer kept in the fact (`rule_room`, `rule_floor`); what only the model found is added
   with method `llm`.

Every call goes through the job runner, so every attempt is a row in llm_calls (input, output, cost, latency); the
summary gives the cost per sheet. Answers are kept in the building's state, so re-reading the step asks again only
the pages that changed. With PM_AI=off or no credentials nothing is called and the facts are the rules' facts.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from math import dist
from pathlib import Path

from ..calibration import calibrate_model
from . import pages as page_sort
from . import pdfdoc, tags
from .state import AUTO_ACCEPT

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data/kg.sqlite"
JOB = "plan_meaning"
AI_CAP = 0.85  # below AUTO_ACCEPT: a model's reading of a plan is a proposal
MAX_PAGES = 12  # model calls per file; the rest of a whole drawing set keeps the rules' reading and says so
MAX_ROOM_CANDS = 220
MAX_TAG_CANDS = 160
DPI = 100.0
MAX_PX = 3600

ROOM_WORD = re.compile(r"^[A-Z]?\d{3,4}[A-Z]?$")
TAG_WORD = re.compile(r"^\(?(\(E\))?([A-Z]{1,5})[- ]?(\d{1,3}(?:\.\d{1,2})?)([A-Z])?\)?[.,;:]?$")
AIR_DEVICE = re.compile(r"^[A-Z]{1,2}-\d{1,2}$")  # S-1, R-2, D-4: diffuser and grille types, with a CFM under them
ONE_LETTER_UNITS = {"B", "F", "P"}  # B-1 boiler, F-1 furnace, P-1 pump; other single letters are devices (S-1, R-1)
NOT_EQUIPMENT = {"SA", "L", "D", "S", "R", "E", "M", "T", "X", "CD", "GC", "FD", "SD", "VD", "BD"}
UNITS = {"CFM", "GPM", "MBH", "KW", "HP", "LBS", "SF", "X", "TONS", "SQ", "FT"}
LEVEL_FLOORS = re.compile(r"^(L\d{1,2}|B\d|RF)$")


# ---------------------------------------------------------------- candidates

@dataclass
class PageCands:
    page: int
    sheet: str
    size: tuple[float, float]
    rooms: dict[str, dict] = field(default_factory=dict)  # R1 -> {text, word, xy, above, below, context}
    tags: dict[str, dict] = field(default_factory=dict)   # T1 -> {text, normal, occ: [{xy, bbox, role, word}]}
    titles: list[str] = field(default_factory=list)

    @property
    def by_number(self) -> dict[str, str]:
        return {c["text"]: rid for rid, c in self.rooms.items()}


def _clean(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", t.upper())


def _context(ws, w, above: bool) -> list:
    """Lines of words just above (or below) a label, nearest first, centred on it."""
    if above:
        near = [v for v in ws if v is not w and -40 <= v.top - w.top <= -2 and abs(v.cx - w.cx) < 90]
    else:
        near = [v for v in ws if v is not w and 2 <= v.top - w.top <= 32 and abs(v.cx - w.cx) < 90]
    rows: list[list] = []
    for v in sorted(near, key=lambda v: v.top, reverse=above):
        if rows and abs(rows[-1][0].top - v.top) <= 2.5:
            rows[-1].append(v)
        else:
            rows.append([v])
    rows = rows[:3]  # the nearest three lines, then in reading order
    return [sorted(r, key=lambda v: v.x0) for r in sorted(rows, key=lambda r: r[0].top)]


def room_candidates(ws) -> list[dict]:
    """Every number that could be a room label, with the words around it. Airflow values (a number under a diffuser
    type such as S-1 or D-4 and nothing else above it), numbers followed by a unit, and one-off fonts (title block,
    notes) are left out."""
    out = []
    for w in ws:
        if not ROOM_WORD.match(w.text) or w.size < 5:
            continue
        right = [v for v in ws if abs(v.top - w.top) < 3 and 0 < v.x0 - w.x1 < 25]
        if any(v.text.upper().strip(".") in UNITS for v in right):
            continue
        above, below = _context(ws, w, True), _context(ws, w, False)
        words_above = [v for r in above for v in r]
        device = any(AIR_DEVICE.match(v.text) and v.top - w.top > -16 for v in words_above)
        has_name = any(re.search(r"[A-Za-z]{2,}", v.text) and not AIR_DEVICE.match(v.text) for v in words_above)
        if device and not has_name:
            continue
        out.append({"text": w.text, "word": w, "xy": (round(w.cx), round(w.cy)), "above": above, "below": below})
    groups = defaultdict(list)
    for c in out:
        groups[(c["word"].font, c["word"].size)].append(c)
    keep = [c for g in groups.values() if len(g) >= 2 for c in g]
    keep.sort(key=lambda c: (c["word"].top, c["word"].x0))
    return keep[:MAX_ROOM_CANDS]


def _tag_text(prefix: str, num: str, suf: str) -> str:
    return f"{prefix}-{num}{suf or ''}"


def tag_candidates(ws) -> dict[str, list[dict]]:
    """Occurrences of each equipment tag, by its written form (AHU-1, FC-1.16, SAV-3). Single words, two-line
    hexagons (a type word over its number), and sensor callouts in parentheses, "(EH-1/EF-7)" naming two units."""
    tees = [w for w in ws if w.text in ("T", "S") and w.size <= 10]
    occ: dict[str, list[dict]] = defaultdict(list)

    def add(text, w, bbox, xy, paren=False, existing=False):
        m = TAG_WORD.match(text)
        if not m:
            return
        prefix, num, suf = m.group(2), m.group(3), m.group(4) or ""
        if prefix in NOT_EQUIPMENT or (len(prefix) == 1 and prefix not in ONE_LETTER_UNITS):
            return
        near_t = min((dist((t.cx, t.cy), xy) for t in tees), default=1e9)
        role = "sensor callout" if paren or near_t < 28 else "unit label"
        occ[_tag_text(prefix, num, suf)].append({"xy": (round(xy[0]), round(xy[1])), "bbox": bbox, "role": role,
                                                 "existing": existing or bool(m.group(1)), "word": w})

    for w in ws:
        t = w.text
        if "/" in t and t.startswith("(") and t.endswith(")"):  # (EH-1/EF-7): one sensor for two units
            for part in t.strip("()").split("/"):
                add(part, w, w.bbox, (w.cx, w.cy), paren=True)
            continue
        if TAG_WORD.match(t):
            add(t, w, w.bbox, (w.cx, w.cy), paren=t.startswith("(") and t.endswith(")"),
                existing=t.startswith("(E)"))
            continue
        if re.fullmatch(r"[A-Z]{1,4}", t) and t not in ("T", "S", "X", "N", "E", "W"):
            below = [v for v in ws if 0 <= v.top - w.bottom < 9 and abs(v.cx - w.cx) < 7
                     and re.fullmatch(r"\d{1,2}", v.text)]
            if below:  # a two-line hexagon: the type over the number
                n = below[0]
                box = [round(min(w.x0, n.x0), 1), round(w.top, 1), round(max(w.x1, n.x1), 1), round(n.bottom, 1)]
                add(f"{t}-{n.text}", w, box, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
    return occ


def candidates(ws, page: int = 0, size=(0.0, 0.0)) -> PageCands:
    pc = PageCands(page, pdfdoc.sheet_id(ws), size)
    for n, c in enumerate(room_candidates(ws), 1):
        pc.rooms[f"R{n}"] = c
    occ = tag_candidates(ws)
    for n, text in enumerate(sorted(occ, key=tags_key)[:MAX_TAG_CANDS], 1):
        pc.tags[f"T{n}"] = {"text": text, "normal": normal_of(text), "occ": occ[text]}
    pc.titles = [t for t, _ in page_sort._title_lines(ws)
                 if re.search(r"\bPLANS?\b|\bLEVEL\b|\bFLOOR\b|\bROOF\b|\bBASEMENT\b", t)][:12]
    return pc


def tags_key(text: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def normal_of(text: str) -> str:
    """The tag's comparison form: the knowledge model's (tags.normal) when it knows the prefix, else the letters and
    digits as written (FC-1.16 -> FC1.16)."""
    return tags.normal(text) or re.sub(r"[-\s()]", "", text.upper())


def _words_line(rows) -> str:
    return " / ".join(" ".join(v.text for v in r) for r in rows) or "-"


def prompt_values(pc: PageCands, file_name: str) -> dict:
    room_lines = [f"{rid} '{c['text']}' at ({c['xy'][0]},{c['xy'][1]}); above: {_words_line(c['above'])}; "
                  f"below: {_words_line(c['below'])}" for rid, c in pc.rooms.items()]
    tag_lines = []
    for tid, t in pc.tags.items():
        occ = "; ".join(f"{o['role']}{' (existing)' if o['existing'] else ''} at ({o['xy'][0]},{o['xy'][1]})"
                        for o in t["occ"][:6])
        tag_lines.append(f"{tid} {t['text']}: {occ}")
    return {"sheet": pc.sheet or "(no sheet number)", "page_no": pc.page + 1, "file": file_name,
            "width": round(pc.size[0]), "height": round(pc.size[1]),
            "titles": "\n".join(f"- {t}" for t in pc.titles) or "(none found)",
            "room_lines": "\n".join(room_lines) or "(none)", "tag_lines": "\n".join(tag_lines) or "(none)",
            "room_ids": list(pc.rooms), "tag_ids": list(pc.tags)}


def page_crop(pc: PageCands, margin: float = 150) -> list[float] | None:
    pts = [c["xy"] for c in pc.rooms.values()] + [o["xy"] for t in pc.tags.values() for o in t["occ"]]
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = pc.size
    return [max(0.0, min(xs) - margin), max(0.0, min(ys) - margin), min(w, max(xs) + margin),
            min(h, max(ys) + margin)]


def page_image(path: Path, pc: PageCands, overlay: bool = True) -> pdfdoc.PageImage:
    labels = []
    if overlay:
        labels = [{"id": rid, "bbox": c["word"].bbox, "color": "#1F5FD0"} for rid, c in pc.rooms.items()]
        labels += [{"id": tid, "bbox": o["bbox"], "color": "#D02020"} for tid, t in pc.tags.items() for o in t["occ"]]
    return pdfdoc.page_image(path, pc.page, dpi=DPI, crop=page_crop(pc), labels=labels, max_px=MAX_PX)


# ---------------------------------------------------------------- asking

def request_key(values: dict, img: pdfdoc.PageImage, prompt_ref: str) -> str:
    h = hashlib.sha1(json.dumps({k: v for k, v in values.items()}, sort_keys=True, default=str).encode())
    h.update(hashlib.sha1(img.png()).digest())
    return f"{prompt_ref}:{h.hexdigest()[:20]}"


def logged_answer(store, model: str, values: dict, user_content: list) -> dict | None:
    """An answer already paid for: the latest successful call in llm_calls with this exact request, model and prompt
    version, whose output still passes the job's checks."""
    from ..ai.calls import parse_json, request_log
    from ..ai.jobs import check_output, job_request
    from ..ai.models import get_model
    from ..ai.providers import ModelError

    if store is None:
        return None
    req, prompt = job_request(JOB, values, user_content)
    rows = store.conn.execute(
        "SELECT id, output, cost_usd, latency_s FROM llm_calls WHERE job = ? AND ok = 1 AND model = ? AND prompt = ?"
        " AND input = ? ORDER BY id DESC", (JOB, get_model(model).id, prompt.ref, request_log(req))).fetchall()
    for r in rows:
        try:
            blocks = json.loads(r["output"] or "[]")
            out = parse_json("".join(b.get("text", "") for b in blocks if b.get("type") == "text"))
        except (ModelError, ValueError, AttributeError):
            continue
        if check_output(JOB, out, values) is None:
            return {"output": out, "model": model, "calls": [r["id"]], "cost_usd": r["cost_usd"],
                    "latency_s": r["latency_s"], "logged": True}
    return None


def ask_page(values: dict, img: pdfdoc.PageImage, router, store, project: str, model: str | None = None) -> dict:
    """One page through the job: {output, model, calls, cost_usd, latency_s} or {error}."""
    from ..ai.jobs import get_job, run_job
    from ..ai.providers import ModelError

    content = [img.block()]
    for m in ([model] if model else [router.first_enabled(get_job(JOB).chain + list(get_job(JOB).contender))]):
        if (a := logged_answer(store, m, values, content)) is not None:
            return a
    try:
        res = run_job(JOB, values, router=router, store=store, project=project, model=model, user_content=content)
    except ModelError as e:
        return {"error": str(e)[:400]}
    return {"output": res.output, "model": res.model, "calls": [a["call"] for a in res.attempts if a["call"]],
            "cost_usd": res.cost_usd, "latency_s": res.latency_s}


# ---------------------------------------------------------------- checking an answer

def _name_ok(name: str, c: dict) -> bool:
    """Every word of the name is printed next to the label (above or below it)."""
    have = "|".join(_clean(v.text) for rows in (c["above"], c["below"]) for r in rows for v in r)
    want = [_clean(x) for x in re.split(r"[\s/]+", name) if _clean(x)]
    return bool(want) and all(x in have for x in want)


def _level_digit_ok(number: str, floor: str) -> bool | None:
    if not floor.startswith("L"):
        return None
    from .floorplans import _on_level
    return _on_level(number, floor[1:])


def checked(answer: dict, pc: PageCands) -> dict:
    """The model's answer for one page after the rules' checks: {kind, floors, rooms: [...], placements: [...],
    dropped: n}. Each room and placement carries `raw` (the model's confidence after the checks) and `checks`."""
    out = answer["output"]
    floors = [v["floor"] for v in out.get("views", []) if LEVEL_FLOORS.match(v["floor"])]
    floors = list(dict.fromkeys(floors))
    res = {"kind": out.get("page_kind", "other"), "floors": floors,
           "titles": {v["floor"]: v.get("title", "") for v in out.get("views", [])}, "rooms": [], "placements": [],
           "dropped": 0}
    if res["kind"] != "plan" or not floors:
        return res
    pw, ph = pc.size
    rooms_by_id = {}
    for r in out.get("rooms", []):
        c = pc.rooms.get(r["id"])
        if c is None or r["id"] in rooms_by_id:
            res["dropped"] += 1
            continue
        raw, checks = float(r["confidence"]), []
        name = (r.get("name") or "").strip()
        if name and not _name_ok(name, c):
            checks.append(f"name {name!r} is not printed next to the label: dropped")
            name, raw = "", raw * 0.8
        floor = r["floor"] if r["floor"] in floors else floors[0]
        if floor != r["floor"]:
            checks.append(f"floor {r['floor']} is not a view of the sheet")
            raw *= 0.8
        if _level_digit_ok(c["text"], floor) is False:
            checks.append(f"number does not start with the level ({floor})")
            raw *= 0.85
        box = r.get("box")
        if box and not (box[0] <= c["xy"][0] <= box[2] and box[1] <= c["xy"][1] <= box[3]
                        and 0 <= box[0] < box[2] <= pw + 1 and 0 <= box[1] < box[3] <= ph + 1
                        and (box[2] - box[0]) * (box[3] - box[1]) < 0.25 * pw * ph):
            checks.append("box does not hold the label: dropped")
            box = None
        item = {"id": r["id"], "number": c["text"], "name": name, "floor": floor, "box": box, "raw": round(raw, 4),
                "model_conf": float(r["confidence"]), "checks": checks, "anchor": (c["word"].cx, c["word"].top - 6),
                "bbox": c["word"].bbox}
        rooms_by_id[r["id"]] = item
        res["rooms"].append(item)
    seen_tags = set()
    for p in out.get("placements", []):
        t = pc.tags.get(p["tag"])
        if t is None or p["tag"] in seen_tags:
            res["dropped"] += 1
            continue
        seen_tags.add(p["tag"])
        raw, checks = float(p["confidence"]), []
        room = rooms_by_id.get(p["room"]) if p.get("room") else None
        if p.get("room") and room is None:
            checks.append(f"room {p['room']} is not a room it listed: dropped")
            raw *= 0.6
        floor = p["floor"] if p["floor"] in floors else (room["floor"] if room else floors[0])
        if floor != p["floor"]:
            checks.append(f"floor {p['floor']} is not a view of the sheet")
            raw *= 0.8
        if room and room["floor"] != floor:
            checks.append("the room is on another view")
            raw *= 0.7
        in_box = None
        if room:
            d = min(dist(o["xy"], room["anchor"]) for o in t["occ"])
            if d > 700:
                checks.append(f"every occurrence is {round(d)} pt from the room label")
                raw *= 0.7
            if room["box"]:
                b = room["box"]
                in_box = any(b[0] <= o["xy"][0] <= b[2] and b[1] <= o["xy"][1] <= b[3] for o in t["occ"])
                if not in_box:
                    checks.append("no occurrence inside the room's box")
                    raw *= 0.85
        best = min(t["occ"], key=lambda o: (o["role"] != ("sensor callout" if p["rel"] == "serves" else "unit label"),
                                            dist(o["xy"], room["anchor"]) if room else 0))
        res["placements"].append({"tag": t["text"], "normal": t["normal"], "id": p["tag"],
                                  "room": room["number"] if room else None, "floor": floor,
                                  "rel": "serves" if p["rel"] == "serves" else "located in", "raw": round(raw, 4),
                                  "model_conf": float(p["confidence"]), "why": p.get("why", ""), "checks": checks,
                                  "in_box": in_box, "occ": t["occ"], "at": best})
    return res


def calibrated(raw: float, model: str | None, kind: str) -> float:
    return calibrate_model(JOB, raw, model, kind)


# ---------------------------------------------------------------- reading a file

def pick_pages(path: Path, rule_pages: set[int], log) -> list[int]:
    """Pages worth a model call, best first: the rules' floor pages, mechanical (or unnamed discipline) plans,
    pages the rules could not sort; demolition plans last."""
    sorted_pages = page_sort.sort(path)
    log(f"Page sorting: {page_sort.summary(sorted_pages)} ({len(sorted_pages)} pages)")

    def rank(s):
        demo = any("DEMO" in t for t in s.titles)
        if s.page in rule_pages:
            return (0, demo, s.page)
        if s.kind == "plan" and s.discipline in ("M", "H", ""):
            return (1, demo, s.page)
        if s.kind == "unsorted":
            return (2, demo, s.page)
        return None

    ranked = sorted((r, s.page) for s in sorted_pages if (r := rank(s)) is not None)
    chosen = [p for _, p in ranked]
    if len(chosen) > MAX_PAGES:
        log(f"AI plan reader: {len(chosen)} pages could be plans; reading the first {MAX_PAGES} "
            f"(the rest keep the rules' reading)")
    return chosen[:MAX_PAGES]


def read_pages(path: Path, file_name: str, page_list: list[int], *, router, store, project: str, cache: dict,
               model: str | None = None, log=print, overlay: bool = True) -> list[dict]:
    """Ask the job about each page. Returns [{page, cands, answer, checked}] (answer has `error` when it failed)."""
    out = []
    from ..ai.prompts import load_prompt
    ref = load_prompt(JOB).ref
    for page in page_list:
        ws = pdfdoc.words(path, page)
        pc = candidates(ws, page, pdfdoc.page_size(path, page))
        if not pc.rooms and not pc.tags:
            out.append({"page": page, "cands": pc, "answer": None, "checked": None, "skipped": "no candidates"})
            continue
        values = prompt_values(pc, file_name)
        img = page_image(path, pc, overlay)
        key = request_key(values, img, ref) + (f":{model}" if model else "")
        a = cache.get(key)
        cached = a is not None
        if a is None:
            a = ask_page(values, img, router, store, project, model)
            if not a.get("error"):
                cache[key] = a
        a = dict(a, cached=cached)
        ch = checked(a, pc) if not a.get("error") else None
        out.append({"page": page, "cands": pc, "answer": a, "checked": ch})
        if a.get("error"):
            log(f"AI plan reader, page {page + 1}: {a['error'][:200]}")
        else:
            log(f"AI plan reader, page {page + 1} ({pc.sheet or 'no sheet number'}): {ch['kind']}, "
                f"floors {', '.join(ch['floors']) or '-'}, {len(ch['rooms'])} rooms, {len(ch['placements'])} "
                f"placements ({a.get('model')}, ${a.get('cost_usd', 0):.4f}{', saved answer' if cached else ''})")
    return out


# ---------------------------------------------------------------- merging with the rules' facts

FLOOR_NAME = {"RF": "Roof"}


def floor_name(fl: str) -> str:
    if fl in FLOOR_NAME:
        return FLOOR_NAME[fl]
    if fl.startswith("B"):
        return "Basement" if fl == "B1" else f"Basement {fl[1:]}"
    return f"Level {fl[1:]}"


def _conf(raw: float, model: str | None, kind: str) -> tuple[float, float]:
    cal = calibrated(raw, model, kind)
    return cal, round(min(cal, AI_CAP), 2)


def merge(facts: list[dict], results: list[dict], file_name: str, log) -> dict:
    """Write the checked answers into the rules' facts (in place). Returns counts for the log and the scorer."""
    from .floorplans import _extent, _place_fact, _room_fact, tags_sort

    summary = {"floors_added": 0, "floors_changed": 0, "rooms_added": 0, "rooms_named": 0, "rooms_agreed": 0,
               "rooms_renamed": 0,
               "placements_added": 0, "placements_agreed": 0, "placements_changed": 0, "dropped": 0}
    by_id = {f["id"]: f for f in facts}
    floor_of_page: dict[int, list[str]] = defaultdict(list)
    for f in facts:
        if f["kind"] == "floor" and f["src"].get("file") == file_name:
            floor_of_page[f["src"]["page"]].append(f["data"]["floor"])
    ai_place: dict[str, list[tuple[dict, dict, str | None]]] = defaultdict(list)
    for r in results:
        ch, a = r["checked"], r["answer"]
        if not ch or ch["kind"] != "plan" or not ch["floors"]:
            continue
        summary["dropped"] += ch["dropped"]
        model, page, pc = a.get("model"), r["page"], r["cands"]
        src = {"file": file_name, "page": page, "sheet": pc.sheet}
        rule_floors = floor_of_page.get(page, [])
        # floors: the model's views replace a rules' floor it disagrees with on this page
        for fl in ch["floors"]:
            fid = f"floor:{fl}"
            if fid in by_id:
                by_id[fid]["data"].setdefault("ai", {"job": JOB, "model": model, "agreed": True})
                continue
            crop = _extent([x["anchor"] for x in ch["rooms"] if x["floor"] == fl]
                           or [p["at"]["xy"] for p in ch["placements"] if p["floor"] == fl], None)
            fact = {"id": fid, "kind": "floor", "label": floor_name(fl),
                    "data": {"floor": fl, "name": floor_name(fl), "crop": crop,
                             "rooms": sum(1 for x in ch["rooms"] if x["floor"] == fl),
                             "title": ch["titles"].get(fl, ""), "rule_floor": rule_floors[0] if rule_floors else None,
                             "ai": {"job": JOB, "model": model, "calls": a.get("calls", [])}},
                    "src": src | {"bbox": None}, "method": "llm", "conf": AI_CAP, "step": "plans", "ask": None}
            facts.append(fact)
            by_id[fid] = fact
            summary["floors_added" if not rule_floors else "floors_changed"] += 1
        for rf in rule_floors:
            if rf not in ch["floors"]:  # the rules' floor for this sheet is not one the model sees: move its facts
                to = ch["floors"][0]
                log(f"AI plan reader: {pc.sheet or f'page {page + 1}'} read as {floor_name(to)}, not "
                    f"{floor_name(rf)} as the rules read its title")
                for f in facts:
                    if f["kind"] in ("room", "placement") and f["data"].get("floor") == rf \
                            and f["src"].get("page") == page and f["src"].get("file") == file_name:
                        f["data"]["rule_floor"], f["data"]["floor"] = rf, to
                still = any(f["kind"] in ("room", "placement") and f["data"].get("floor") == rf for f in facts)
                old = by_id.get(f"floor:{rf}")
                if old is not None and not still and old["src"].get("page") == page:
                    facts.remove(old)
                    del by_id[old["id"]]
        # rooms
        for x in ch["rooms"]:
            cal, conf = _conf(x["raw"], model, "room")
            ai = {"job": JOB, "model": model, "name": x["name"], "floor": x["floor"], "raw": x["raw"],
                  "calibrated": cal, "checks": x["checks"], "box": x["box"], "calls": a.get("calls", [])}
            fid = f"room:{x['number']}"
            f = by_id.get(fid)
            if f is None:
                f = _room_fact({"number": x["number"], "name": x["name"], "anchor": x["anchor"], "bbox": x["bbox"]},
                               x["floor"], src)
                f["data"]["name"] = x["name"].title()
                f["label"] = f"{x['number']} {x['name'].title()}".strip()
                f["method"], f["data"]["ai"] = "llm", ai
                # the rules' question (no name, odd number) stays; the confidence is the model's, calibrated
                f["conf"] = conf if not f.get("ask") else min(conf, f["conf"])
                facts.append(f)
                by_id[fid] = f
                summary["rooms_added"] += 1
                continue
            f["data"]["ai"] = ai
            rule_name = f["data"].get("name", "")
            if not rule_name and x["name"]:
                f["data"]["name"], f["data"]["rule_name"] = x["name"].title(), ""
                f["label"] = f"{x['number']} {x['name'].title()}"
                f["method"], f["conf"] = "llm", conf
                if f.get("ask") and f["ask"].get("field") == "name":
                    f["ask"] = None
                summary["rooms_named"] += 1
            elif _clean(rule_name) == _clean(x["name"]) or not x["name"]:
                f["conf"] = max(f["conf"], conf)
                summary["rooms_agreed"] += 1
            else:  # both read a name, not the same one: the model's (printed there, checked) is the proposal
                f["data"]["rule_name"], f["data"]["name"] = rule_name, x["name"].title()
                f["label"] = f"{x['number']} {x['name'].title()}"
                f["method"], f["conf"] = "llm", min(conf, 0.7)
                f["ask"] = {"q": f"Room {x['number']}: is it {x['name'].title()} (AI plan reader, {round(cal * 100)}% "
                                 f"sure) or {rule_name.title()} (the rules)?", "field": "name",
                            "options": [{"value": x["name"].title(), "label": x["name"].title()},
                                        {"value": rule_name.title(), "label": rule_name.title()}]}
                summary["rooms_renamed"] += 1
            if x["box"]:
                f["data"]["box"] = x["box"]
        for p in ch["placements"]:
            ai_place[p["normal"]].append((p, a, page))
    # placements: one per tag, the model's best evidence across pages
    for normal in sorted(ai_place, key=tags_sort):
        cands = ai_place[normal]
        # a room on a floor first; else a roof plan's unit over a floor's mention; then the surest answer
        p, a, page = max(cands, key=lambda c: (c[0]["room"] is not None and c[0]["floor"] != "RF",
                                               c[0]["floor"] == "RF", c[0]["raw"]))
        model = a.get("model")
        cal, conf = _conf(p["raw"], model, "placement")
        ai = {"job": JOB, "model": model, "room": p["room"], "floor": p["floor"], "rel": p["rel"], "raw": p["raw"],
              "calibrated": cal, "why": p["why"], "checks": p["checks"], "calls": a.get("calls", []),
              "pages": sorted({c[2] for c in cands})}
        fid = f"place:{normal}"
        f = by_id.get(fid)
        if f is not None:
            f["data"]["ai"] = ai
            same = f["data"].get("room") == p["room"] and (p["room"] or f["data"].get("floor") == p["floor"])
            if same:
                f["conf"] = round(max(f["conf"], min(AI_CAP, max(conf, f["conf"]) + 0.05)), 2)
                if f.get("ask") and f["conf"] >= 0.75:
                    f["ask"] = None
                summary["placements_agreed"] += 1
            else:
                d = f["data"]
                d["rule_room"], d["rule_floor"], d["rule_conf"] = d.get("room"), d.get("floor"), f["conf"]
                d["room"], d["floor"], d["rel"] = p["room"], p["floor"], p["rel"]
                f["method"], f["conf"] = "llm", conf
                f["label"] = _place_label(d)
                f["ask"] = _ask(d, p, cal) if cal < 0.7 else None
                summary["placements_changed"] += 1
            continue
        tag = tags.parse(p["tag"])
        occ = p["occ"]
        label = next((o for o in occ if o["role"] == "unit label"), occ[0])
        data = {"tag": p["tag"], "normal": normal, "class": tag.cls if tag else None,
                "family": tag.family if tag else None, "floor": p["floor"], "rel": p["rel"],
                "unit_xy": label["xy"], "at_xy": p["at"]["xy"],
                "by": {"sensor callout": "thermostat", "unit label": "unit label"}[p["at"]["role"]],
                "also_on": [], "occurrences": [{"bbox": o["bbox"], "role": o["role"]} for o in occ],
                "room": p["room"], "ai": ai}
        res = results_by_page(results).get(page)
        fact = _place_fact(normal, data, {"file": file_name, "page": page, "sheet": res["cands"].sheet if res else "",
                                          "bbox": p["at"]["bbox"]}, conf, _ask(data, p, cal) if cal < 0.6 else None)
        fact["method"] = "llm"
        facts.append(fact)
        by_id[fid] = fact
        summary["placements_added"] += 1
    for f in facts:
        if f["kind"] == "floor":
            f["data"]["rooms"] = sum(1 for r in facts if r["kind"] == "room" and r["data"].get("floor") == f["data"]["floor"])
    return summary


def results_by_page(results: list[dict]) -> dict[int, dict]:
    return {r["page"]: r for r in results}


def _place_label(d: dict) -> str:
    where = f"room {d['room']}" if d.get("room") else {"RF": "roof"}.get(d["floor"], d["floor"])
    return f"{d['tag']} {d['rel']} {where}"


def _ask(d: dict, p: dict, cal: float) -> dict:
    verb = "serve" if d["rel"] == "serves" else "sit in"
    opts = []
    for room in (p["room"], d.get("rule_room")):
        if room and room not in [o["value"] for o in opts]:
            opts.append({"value": room, "label": f"Room {room}"})
    opts.append({"value": None, "label": "None of these / outside"})
    return {"q": f"Which room does {d['tag']} {verb}? The AI plan reader says "
                 f"{('room ' + p['room']) if p['room'] else 'no room'} ({round(cal * 100)}% sure): {p['why']}",
            "field": "room", "options": opts}


def refine(path: Path, file_name: str, facts: list[dict], log, *, project: str, cache: dict | None = None,
           router=None, store=None, model: str | None = None, max_pages: int | None = None) -> dict:
    """The plans step's AI pass over one file: pick pages, ask, check, merge into `facts` (in place)."""
    from ..ai.calls import default_router
    from ..ai.providers import ModelUnavailable

    cache = {} if cache is None else cache
    summary = {"pages": 0, "asked": 0, "cached": 0, "failed": 0, "calls": 0, "cost_usd": 0.0, "seconds": 0.0,
               "usd_per_sheet": None, "models": {}, "off": ""}
    router = router or default_router()
    if not router.ready:
        summary["off"] = router.why_not_ready()
        log(f"AI plan reader off ({summary['off']}): the plans keep the rules' reading.")
        return summary
    rule_pages = {f["src"]["page"] for f in facts if f["kind"] == "floor" and f["src"].get("file") == file_name}
    page_list = pick_pages(path, rule_pages, log)
    if max_pages is not None:
        page_list = page_list[:max_pages]
    if not page_list:
        return summary
    if store is None:
        from projectmodel.db.store import Store
        store = Store(DB)
    if not router.learnt and hasattr(router, "learn"):
        router.learn(store)
    t0 = time.perf_counter()
    try:
        results = read_pages(path, file_name, page_list, router=router, store=store, project=project, cache=cache,
                             model=model, log=log)
    except ModelUnavailable as e:
        summary["off"] = str(e)
        log(f"AI plan reader stopped ({e}); the plans keep the rules' reading.")
        return summary
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    for r in results:
        a = r["answer"]
        if a is None:
            continue
        summary["pages"] += 1
        if a.get("error"):
            summary["failed"] += 1
            continue
        if a.get("cached") or a.get("logged"):
            summary["cached"] += 1
        else:
            summary["asked"] += 1
            summary["calls"] += len(a.get("calls", []))
            summary["cost_usd"] += a.get("cost_usd", 0.0)
        summary["models"][a.get("model")] = summary["models"].get(a.get("model"), 0) + 1
    summary["cost_usd"] = round(summary["cost_usd"], 4)
    if summary["asked"]:
        summary["usd_per_sheet"] = round(summary["cost_usd"] / summary["asked"], 4)
    summary |= merge(facts, results, file_name, log)
    log(f"AI plan reader: {summary['pages']} sheets ({summary['asked']} asked, {summary['cached']} from earlier "
        f"answers, {summary['failed']} failed); ${summary['cost_usd']:.4f}"
        + (f", ${summary['usd_per_sheet']:.4f} per sheet" if summary["usd_per_sheet"] is not None else "")
        + f", {summary['seconds']} s. Rooms: {summary['rooms_added']} added, {summary['rooms_named']} named, "
        f"{summary['rooms_renamed']} renamed, {summary['rooms_agreed']} agreed. Placements: {summary['placements_added']} added, "
        f"{summary['placements_agreed']} agreed, {summary['placements_changed']} changed. Proposals stay below "
        f"{round(AUTO_ACCEPT * 100)}% for review.")
    return summary
