"""Robustness check for the guided setup: run every reader on the Troop D package with one realistic variation at a
time (another firm's titles, room numbers, tag style, heading style; another vendor's submittal or BMS export; a
scanned sheet; the whole drawing set uploaded) and score each run against the Troop D answer key.

    .venv/bin/python scripts/stress_intake.py              # every scenario (about 3 minutes)
    .venv/bin/python scripts/stress_intake.py plans: bms:  # only scenarios whose name contains one of the words

The variations are applied to the words read from the PDFs (pdfdoc.words) or to the CSV rows, so the documents on
disk are never changed. Results go to reports/stress_intake.json. See docs/assessment-rules-vs-ai.md.
"""
import csv, io, json, re, sys, tempfile, time
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from projectmodel.intake import pdfdoc, score, steps
from projectmodel.intake.state import Intake

P = steps.TEST_PACKAGE
ORIG = pdfdoc.words
FILES = {s.id: s.test_file for s in steps.STEPS[:-1]}

def per_word(fn):
    return lambda ws: tuple(replace(w, text=fn(w.text)) if fn(w.text) != w.text else w for w in ws)

TAG = re.compile(r"^(VAVE|FVAV|VAV)-?(\d+)([A-Z]?)$")
ROOM = re.compile(r"^(\d{3})([A-Z]?)$")
def caps_to_title(t):
    return t.title() if t.isupper() and len(t) > 2 and t.isalpha() else t
def section_numbers(t):
    m = re.match(r"^([A-H])\.$", t); return f"{ord(m[1]) - 64}." if m else t
def label_above(ws):  # room number drawn above its name instead of below
    out = []
    for w in ws:
        if ROOM.match(w.text):
            h = w.bottom - w.top; out.append(replace(w, top=w.top - 2.4 * h, bottom=w.bottom - 2.4 * h))
        else: out.append(w)
    return tuple(out)
def niagara_ref(t):
    m = re.match(r"^TROOPD-NAE01/(FC-\d+)\.([^.]+)\.(.+)$", t)
    return f"/Drivers/BacnetNetwork/{m[2].replace('-', '_')}/points/{m[3].replace('-', '_')}" if m else t
IO_LONG = {"AI": "AnalogInput", "AO": "AnalogOutput", "BI": "BinaryInput", "BO": "BinaryOutput", "AV": "AnalogValue",
           "BV": "BinaryValue", "MV": "MultiStateValue"}

def csv_variant(fn):
    rows = list(csv.DictReader(io.StringIO((P / FILES["bms"]).read_text(encoding="utf-8-sig"))))
    rows = fn(rows); out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return out.getvalue().encode()
def niagara_columns(rows):
    m = {"Item Reference": "Path", "Name": "Display Name", "Description": "Point Description", "Units": "Facets",
         "Device": "Parent", "Object Type": "Point Type"}
    return [{m.get(k, k): v for k, v in r.items()} for r in rows]
def device_by_instance(rows):
    return [dict(r, Device=f"DEV{r['Device Instance']}") for r in rows]

BID = ROOT / "data/raw/troop_d/R2517-01_Final_Bid_Plans.pdf"
SCENARIOS = {
    "baseline": {},
    "plans: whole 27-sheet drawing set uploaded": {"upload": {"plans": BID}},
    "plans: scanned (no text layer)": {"words": {"plans": lambda ws: ()}},
    "plans: titles say 'FLR' not 'LEVEL'": {"words": {"plans": per_word(lambda t: "FLR" if t == "LEVEL" else t)}},
    "plans + submittal: 4-digit room numbers": {"words": {"plans": per_word(lambda t: ROOM.sub(r"1\1\2", t)),
                                                         "submittal": per_word(lambda t: ROOM.sub(r"1\1\2", t))}},
    "plans: room number above its name": {"words": {"plans": label_above}},
    "plans: room names and titles in Title Case": {"words": {"plans": per_word(caps_to_title)}},
    "plans: view titles in Title Case": {"words": {"plans": per_word(
        lambda t: t.title() if t in ("MECHANICAL", "PLAN", "LEVEL", "ROOF", "HVAC", "FLOOR") else t)}},
    "all PDFs: tags with floor (VAVE-1-07)": {"words": {k: per_word(lambda t: TAG.sub(r"\1-1-\2\3", t))
                                                       for k in ("plans", "schedules", "sequences", "submittal")}},
    "schedules: whole 27-sheet drawing set uploaded": {"upload": {"schedules": BID}},
    "schedules: 'VAV' titles read 'AIR TERMINAL'": {"words": {"schedules": per_word(lambda t: "AIR" if t == "VAV" else t)}},
    "sequences: whole 27-sheet drawing set uploaded": {"upload": {"sequences": BID}},
    "sequences: headings in Title Case": {"words": {"sequences": per_word(caps_to_title)}},
    "sequences: sections numbered 1. 2. 3.": {"words": {"sequences": per_word(section_numbers)}},
    "sequences: sections as bullets": {"words": {"sequences": per_word(lambda t: "•" if re.fullmatch(r"[A-H]\.", t)
                                                                         else t)}},
    # W8: the sequence logic reads sections and phrases; another engineer's wording must still read or ask.
    "sequences: 'AIR HANDLER' heading, sections lettered A)": {"words": {"sequences": per_word(
        lambda t: "HANDLER" if t == "HANDLING" else f"{t[0]})" if re.fullmatch(r"[A-M]\.", t) else t)}},
    "sequences: degrees written °F, 'interlocked' as 'tied'": {"words": {"sequences": per_word(
        lambda t: {"degrees": "°F", "interlocked": "tied"}.get(t, t))}},
    "submittal: Niagara-style references": {"words": {"submittal": per_word(niagara_ref)}},
    "submittal: trunks named BUS-n": {"words": {"submittal": per_word(lambda t: t.replace("FC-", "BUS-"))}},
    "submittal: object types spelled out": {"words": {"submittal": per_word(lambda t: IO_LONG.get(t, t))}},
    "bms: Niagara export columns": {"csv": niagara_columns},
    "bms: devices named by instance": {"csv": device_by_instance},
}

def run(name, sc):
    words = sc.get("words", {})
    targets = {FILES[k]: fn for k, fn in words.items()}
    def patched(path, page):
        ws = ORIG(path, page)
        fn = targets.get(Path(path).name)
        return fn(ws) if fn else ws
    pdfdoc.words = patched
    it = Intake.create("stress", root=Path(tempfile.mkdtemp()))
    asks = {}
    t0 = time.time()
    for s in steps.STEPS[:-1]:
        f = sc.get("upload", {}).get(s.id, P / s.test_file)
        if s.id == "bms" and "csv" in sc:
            it.add_file(s.id, f.name, csv_variant(sc["csv"]))
        else:
            it.add_file(s.id, f.name if s.id not in sc.get("upload", {}) else FILES[s.id], f.read_bytes())
        try:
            steps.run(it, s.id, lambda m: None)
        except Exception as e:
            asks[s.id] = f"CRASH {type(e).__name__}: {e}"[:90]
            continue
        asks[s.id] = len(it.open_questions(s.id))
        if s.id == "sequences":
            from collections import Counter
            fs = it.facts("sequences"); asks["seq_kinds"] = dict(Counter(f["kind"] for f in fs)); asks["seq_setpoints"] = sum(len(f.get("data", {}).get("setpoints", []) or []) for f in fs)
    pdfdoc.words = ORIG
    # What was read, whatever it is called: the answer key uses Troop D's own names (room 109, device AHU-1), so a
    # variation that renames things (room 1109, device DEV3104) scores 0 there even when every item was read.
    aliases = it.facts(kind="alias", live=True)
    coverage = {}
    for f in it.facts(kind="issue"):
        if f["data"].get("severity") == "coverage":
            coverage[f["step"]] = coverage.get(f["step"], 0) + 1
    read = {"rooms": len(it.facts(kind="room", live=True)),
            "equipment": len(it.facts(kind="equipment", live=True)), "points": len(it.facts(kind="point", live=True)),
            "devices linked": f"{sum(1 for a in aliases if a['data'].get('equip'))}/{len(aliases)}"}
    try:
        rows = {r["measure"]: (r["machine"], r["out of"]) for r in score.score(it, "troop_d")}
    except Exception as e:
        rows = {"score": f"CRASH {e}"}
    return {"scenario": name, "secs": round(time.time() - t0, 1), "asks": asks, "read": read, "coverage": coverage, "silent": silent_steps(it, asks),
            "score": rows}

MAIN_KIND = {"plans": "room", "schedules": "equipment", "sequences": "sequence", "submittal": "point",
             "bms": "bms_object"}

def silent_steps(it, asks):
    """Steps that read none of their main kind and asked nothing: the failure a person never sees."""
    return [s for s, k in MAIN_KIND.items() if not it.facts(kind=k, live=True) and not asks.get(s)]

if __name__ == "__main__":
    only = sys.argv[1:]
    res = [run(n, s) for n, s in SCENARIOS.items() if not only or any(o in n for o in only)]
    out = ROOT / "reports/stress_intake.json"
    old = json.loads(out.read_text()) if out.exists() and only else []
    keep = {r["scenario"]: r for r in old}; keep.update({r["scenario"]: r for r in res})
    out.write_text(json.dumps(list(keep.values()), indent=1))
    for r in res:
        print("\n##", r["scenario"], f"({r['secs']}s)", "asks:", r["asks"], "read:", r["read"])
        for k, v in r["score"].items(): print(f"   {k:38s} {v}")
