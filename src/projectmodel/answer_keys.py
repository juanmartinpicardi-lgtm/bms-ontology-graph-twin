"""Answer keys written by a person (docs/answer-key-guide.md).

The plan reader (job `plan_meaning`) and the sequence reader (job `sequence_read`) are scored against keys that the
AI agent which built each reader also wrote (data/ground_truth/<set>/plans.yaml, sequences.yaml). This module is the
file side of the "Answer keys" page, where an engineer writes independent keys for a fixed, seeded sample of each
set. It is also what the scoring reads (scoring/human_keys.py).

    data/ground_truth/<set>/plans.human.yaml        which tag is in / serves which room, on the sampled sheets
    data/ground_truth/<set>/sequences.human.yaml    which control relations each sampled section states
    data/ground_truth/answer_key_sample.yaml        the fixed sample per set (made once by scripts/answer_key_sample.py)

A key file has the agent key's schema (`sheets`, `tags`, `unsure` for plans; `sequences` for sequences), so the same
scoring reads it, and an `items` list, the record of each item the engineer worked on, with `by: human`, `at`,
`revealed` (the reader's answer was shown after the item was done) and `minutes`. `items` is the file's source; the
agent-schema part is derived from the done items on every save. The agent keys are never written here.

Held out: `liberty_boe` is never offered, never read and never written.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GT = ROOT / "data/ground_truth"
MANIFEST = GT / "answer_key_sample.yaml"

HELD_OUT = {"liberty_boe"}
JOBS = {"plans": ("msu_mbb", "itd_d1_lab"), "sequences": ("troop_d",)}
JOB_TITLE = {"plans": "Plan sheets", "sequences": "Sequences"}
FILE_NAME = {"plans": "plans.human.yaml", "sequences": "sequences.human.yaml"}

SEED = "answer-keys-v1"
# Minutes of an engineer's time the fixed sample is cut to, per set: about 1 hour 50 minutes for all three.
BUDGET_MIN = {"msu_mbb": 24.0, "itd_d1_lab": 30.0, "troop_d": 45.0}
MIN_PER_TAG = 1.2       # find the tag on the sheet, read its room(s), answer
MIN_PER_SHEET = 1.5     # first look at a sheet: its views, floors, where the rooms are
MIN_PER_SECTION = 1.0   # a section's base time, plus its reading time:
WORDS_PER_MIN = 50.0    # words of section text read, thought about and entered per minute
IDLE_CAP_MIN = 10.0     # time on one item counted at most this long between two saves (a coffee is not work)

PLAN_ANSWERS = ("here", "roof", "not_unit", "unsure")
PLAN_ANSWER_TEXT = {
    "here": "A unit here: it serves or sits in a room",
    "roof": "A unit here, in no room (on the roof, outdoors)",
    "not_unit": "Not a unit on this sheet (a callout, a reference, something else)",
    "unsure": "I can't tell from the documents",
}
REL_TEXT = {"serves": "serves (a terminal unit, by its thermostat)", "located_in": "sits in (the unit is in the room)"}
KIND_RELS = {"loop": ("drives", "feedback"), "interlock": ("requires", "requests"), "reset": ("resets",),
             "mode": ("switches",)}
KIND_TEXT = {"loop": "loop: setpoint drives / measurement feeds back to an output",
             "interlock": "interlock: a condition is required for, or requests, a point",
             "reset": "reset: a point moves another point's setpoint", "mode": "mode or schedule: switches a point"}
KIND_PART = {"interlock": "interlocks", "reset": "resets", "mode": "modes"}


def rel(p: Path) -> str:
    """A path as the page shows it: from the repo root when it is inside it."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# which sets -------------------------------------------------------------------------------------------------------

def offered(job: str) -> list[str]:
    """The sets the page offers for a job. Never a held-out set."""
    return [s for s in JOBS[job] if s not in HELD_OUT]


def job_of(site: str) -> str:
    if site in HELD_OUT or site.split("/")[0] in HELD_OUT:
        raise ValueError(f"{site} is held out: no answer key is written, read or scored for it")
    job = next((j for j, sets in JOBS.items() if site in sets), None)
    if job is None:
        raise ValueError(f"{site} has no answer key to write")
    return job


def check_set(job: str, site: str) -> None:
    if site in HELD_OUT or site.split("/")[0] in HELD_OUT:
        raise ValueError(f"{site} is held out: no answer key is written, read or scored for it")
    if site not in JOBS.get(job, ()):
        raise ValueError(f"{site} has no {job} answer key to write")


def key_path(job: str, site: str) -> Path:
    check_set(job, site)
    return GT / site / FILE_NAME[job]


def agent_key_path(job: str, site: str) -> Path:
    check_set(job, site)
    return GT / site / FILE_NAME[job].replace(".human", "")


# the fixed sample -------------------------------------------------------------------------------------------------

def item_id(job: str, a: str, b: str) -> str:
    """plans: sheet|tag; sequences: sequence id|section letter."""
    return f"{a}|{b}"


def pick_sample(groups: dict[str, list[dict]], budget_min: float, seed: str, *, first_cost: float = 0.0) -> list[dict]:
    """A fixed, seeded sample that costs about `budget_min`: each group's items are shuffled by the seed, then taken
    from the group that has given the smallest share of its items so far (so every group is sampled in proportion to
    its size) until the estimate reaches the budget. A group's first item also costs `first_cost` (a sheet's first
    look). Returns the items in their original order. Every item has an `est_min`."""
    rng = random.Random(seed)
    order = {g: rng.sample(range(len(items)), len(items)) for g, items in sorted(groups.items())}
    taken: dict[str, list[int]] = {g: [] for g in order}
    spent = 0.0
    while spent < budget_min:
        open_ = [g for g in order if len(taken[g]) < len(order[g])]
        if not open_:
            break
        g = min(open_, key=lambda g: (len(taken[g]) / len(order[g]), g))  # the group least sampled for its size
        i = order[g][len(taken[g])]
        spent += groups[g][i]["est_min"] + (first_cost if not taken[g] else 0.0)
        taken[g].append(i)
    return [it for g, items in groups.items() for i, it in enumerate(items) if i in taken[g]]


def section_minutes(words: int) -> float:
    return round(MIN_PER_SECTION + words / WORDS_PER_MIN, 1)


def load_manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text()) if MANIFEST.exists() else {}


def sample_for(site: str) -> dict:
    """The set's fixed sample: {job, seed, budget_min, overhead_min, items: [{id, ..., est_min}]}."""
    check_set(job_of(site), site)
    m = load_manifest().get("sets", {}).get(site)
    if not m:
        raise FileNotFoundError(f"no sample for {site}: run scripts/answer_key_sample.py")
    return m


# reading and writing a key file -----------------------------------------------------------------------------------

def blank(job: str, site: str, file: str = "") -> dict:
    return {"set": site, "file": file, "by": "human", "engineer": "", "seed": SEED, "items": []}


def load(job: str, site: str) -> dict:
    """The set's human key file, or an empty one. `items` is a list of records, in the order they were first saved."""
    p = key_path(job, site)
    if not p.exists():
        return blank(job, site)
    d = yaml.safe_load(p.read_text()) or {}
    d.setdefault("items", [])
    return d


def exists(job: str, site: str) -> bool:
    return key_path(job, site).exists()


def done_items(data: dict) -> list[dict]:
    return [i for i in data.get("items", []) if i.get("status") == "done"]


def upsert(data: dict, rec: dict) -> dict:
    """Put one item record into the key's items (replacing the same id). `at` is set to now."""
    rec = dict(rec, by="human", at=now())
    items = data.setdefault("items", [])
    for n, old in enumerate(items):
        if old["id"] == rec["id"]:
            items[n] = rec
            return data
    items.append(rec)
    return data


def _header(job: str, site: str) -> str:
    agent = FILE_NAME[job].replace(".human", "")
    return (f"# Human answer key for {site} ({JOB_TITLE[job].lower()}), written with the Answer keys page of the app.\n"
            f"# Independent of the agent key ({agent}), which is never read while the engineer works.\n"
            "# `items` is what the engineer saved (by: human, at, revealed, minutes, the source page); the rest of the\n"
            "# file is derived from the done items, in the agent key's schema, on every save.\n")


def save(job: str, site: str, data: dict) -> Path:
    """Write the key file: the derived agent-schema part from the done items, then `items`."""
    check_set(job, site)
    out = {"set": site, "file": data.get("file", ""), "by": "human", "engineer": data.get("engineer", ""),
           "seed": data.get("seed", SEED)}
    out |= (derive_plans if job == "plans" else derive_sequences)(done_items(data))
    out["items"] = data.get("items", [])
    p = key_path(job, site)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(_header(job, site) + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=110))
    tmp.replace(p)
    return p


def _facts(it: dict) -> dict:
    return {"by": "human", "at": it.get("at"), "revealed": bool(it.get("revealed")),
            "minutes": round(float(it.get("minutes") or 0.0), 2)}


def derive_plans(done: list[dict]) -> dict:
    """The agent key's schema from done plan items: sheets (the rooms the engineer named), tags, unsure."""
    sheets: dict[str, dict] = {}
    tags: dict[str, dict] = {}
    unsure: list[str] = []
    not_units: list[str] = []
    for it in sorted(done, key=lambda i: (i["page"], i["tag"])):
        sh = sheets.setdefault(it["sheet"], {"page": it["page"], "sheet": it["sheet"], "floors": [], "rooms": {}})
        if it["answer"] in ("here", "roof"):
            if it.get("floor") and it["floor"] not in sh["floors"]:
                sh["floors"].append(it["floor"])
            for num, name in (it.get("room_names") or {}).items():
                sh["rooms"].setdefault(str(num), name)
            rooms = [] if it["answer"] == "roof" else [str(r) for r in it.get("rooms") or []]
            if it["tag"] not in tags:  # a tag on two sheets: the first sheet that has the unit keeps it
                tags[it["tag"]] = {"floor": it.get("floor") or ("RF" if it["answer"] == "roof" else ""),
                                   "rooms": rooms, "rel": it.get("rel") or "serves", "page": it.get("source_page")
                                   or it["page"], "sheet": it["sheet"], **_facts(it)}
                if it.get("note"):
                    tags[it["tag"]]["note"] = it["note"]
        elif it["answer"] == "unsure":
            unsure.append(it["tag"])
        else:
            not_units.append(it["tag"])
    unsure = [t for t in dict.fromkeys(unsure) if t not in tags]
    not_units = [t for t in dict.fromkeys(not_units) if t not in tags and t not in unsure]
    return {"sheets": list(sheets.values()), "tags": tags, "unsure": unsure, "not_units": not_units}


def derive_sequences(done: list[dict]) -> dict:
    """The agent key's schema from done sequence items. `covered` lists, per sequence, the sections the engineer
    answered (a section with `none` is covered and has no relation): scoring uses the human key on those only."""
    seqs: dict[str, dict] = {}
    covered: dict[str, list[str]] = {}
    for it in done:
        s = seqs.setdefault(it["sequence"], {"title": it.get("title", ""), "loops": [], "interlocks": [], "resets": [],
                                             "modes": [], "gaps": [], "conflicts": []})
        covered.setdefault(it["sequence"], []).append(it["section"])
        base = {"section": it["section"], **_facts(it), "page": it.get("source", {}).get("page")}
        loops: dict[tuple, dict] = {}
        for r in it.get("relations") or []:
            if r["kind"] == "loop":
                lp = loops.setdefault((r.get("loop") or r["to"], r["to"]),
                                      {"name": r.get("loop") or r["to"], "setpoint": None, "measured": None,
                                       "output": r["to"], **base})
                lp["setpoint" if r["rel"] == "drives" else "measured"] = r["from"]
            else:
                s[KIND_PART[r["kind"]]].append({"from": r["from"], "rel": r["rel"], "to": r["to"], **base})
        s["loops"] += list(loops.values())
        s["gaps"] += [{"section": it["section"], "text": g, **_facts(it)} for g in it.get("gaps") or []]
    return {"sequences": seqs, "covered": {k: sorted(v) for k, v in covered.items()}}


def load_derived(job: str, site: str) -> dict | None:
    """The agent-schema key derived from the done items, or None when there is no key file or nothing is done."""
    if not exists(job, site):
        return None
    d = load(job, site)
    if not done_items(d):
        return None
    return {"set": site, "file": d.get("file", ""), "by": "human", "seed": d.get("seed", SEED),
            **(derive_plans if job == "plans" else derive_sequences)(done_items(d))}


# progress and the time estimate -----------------------------------------------------------------------------------

def progress(job: str, site: str, data: dict | None = None) -> dict:
    """Items done and left of the fixed sample, minutes spent, and the estimate left. Once 4 items are done the
    estimate is scaled by the engineer's own pace (spent / estimated, between 0.5 and 3)."""
    sample = sample_for(site)
    data = data if data is not None else load(job, site)
    by_id = {i["id"]: i for i in data.get("items", [])}
    done = [it for it in sample["items"] if by_id.get(it["id"], {}).get("status") == "done"]
    draft = [it for it in sample["items"] if by_id.get(it["id"], {}).get("status") == "draft"]
    spent = sum(float(by_id[it["id"]].get("minutes") or 0.0) for it in sample["items"] if it["id"] in by_id)
    est_done = sum(it["est_min"] for it in done)
    pace = 1.0
    if len(done) >= 4 and est_done > 0:
        pace = min(3.0, max(0.5, sum(float(by_id[it["id"]].get("minutes") or 0.0) for it in done) / est_done))
    left = [it for it in sample["items"] if it not in done]
    est_left = sum(it["est_min"] for it in left) * pace
    sheets_left = len({it["group"] for it in left}) * MIN_PER_SHEET * pace if job == "plans" else 0.0
    revealed = sum(1 for i in done_items(data) if i.get("revealed"))
    return {"total": len(sample["items"]), "done": len(done), "draft": len(draft), "spent_min": round(spent, 1),
            "est_total_min": round(sum(i["est_min"] for i in sample["items"]) + sample.get("overhead_min", 0.0), 1),
            "est_left_min": round(est_left + sheets_left, 1), "pace": round(pace, 2), "revealed": revealed,
            "extra": sum(1 for i in data.get("items", []) if i.get("extra"))}


def add_minutes(rec: dict, since: float, now_ts: float) -> dict:
    """Add the time since `since` (a time.time()) to the item's minutes, counting at most IDLE_CAP_MIN."""
    rec["minutes"] = round(float(rec.get("minutes") or 0.0) + min(IDLE_CAP_MIN, max(0.0, (now_ts - since) / 60.0)), 2)
    return rec


# helpers for the page ---------------------------------------------------------------------------------------------

def room_hint(c: dict) -> str:
    """The name printed with a room label candidate (the words just above the number), or ''."""
    words: list[str] = []
    for row in reversed(c.get("above") or []):
        alpha = [w.text for w in row if re.fullmatch(r"[A-Za-z][A-Za-z/&.\-]{1,}", w.text)
                 and not re.fullmatch(r"[A-Z]{1,3}-\d.*", w.text)]
        if not alpha or len(words) >= 2:
            break
        words = alpha + words
    return " ".join(words)


# the documents each item is read from -----------------------------------------------------------------------------

def plan_file(site: str) -> Path:
    """The set's drawing PDF (gitignored; the key's `file` names it) and its keyed pages, from the agent key's header
    only: its sheets' page numbers and file name, never its answers."""
    check_set("plans", site)
    head = yaml.safe_load(agent_key_path("plans", site).read_text())
    return ROOT / "data/raw" / site / head["file"]


def plan_sheets(site: str) -> list[dict]:
    """The sheets the engineer keys: page and sheet number of each sheet the agent key covers (names of sheets, so
    both keys cover the same ones; nothing it says about rooms or tags)."""
    head = yaml.safe_load(agent_key_path("plans", site).read_text())
    return [{"page": s["page"], "sheet": s["sheet"]} for s in head["sheets"]]


def plan_universe(site: str) -> dict[str, list[dict]]:
    """Every (sheet, tag) the text layer of the keyed sheets shows, as the plan reader's candidates see them: items
    {id, sheet, page, tag, group, est_min}, grouped by sheet. Needs the PDF."""
    from .intake import pdfdoc, plan_ai

    pdf = plan_file(site)
    out: dict[str, list[dict]] = {}
    for sh in plan_sheets(site):
        page = sh["page"] - 1
        pc = plan_ai.candidates(pdfdoc.words(pdf, page), page, pdfdoc.page_size(pdf, page))
        out[sh["sheet"]] = [{"id": item_id("plans", sh["sheet"], t["text"]), "sheet": sh["sheet"], "page": sh["page"],
                             "tag": t["text"], "group": sh["sheet"], "est_min": MIN_PER_TAG}
                            for t in pc.tags.values()]
    return out


def sequence_universe(site: str) -> dict[str, list[dict]]:
    """Every section of every sequence the rules read in the set's sequences document, grouped by sequence."""
    from .scoring import eval as ev

    check_set("sequences", site)
    out: dict[str, list[dict]] = {}
    for q in ev.sequence_read_questions(site):
        sid = q.seq["id"].split(":", 1)[1]
        src = q.seq["src"]
        out[sid] = [{"id": item_id("sequences", sid, s["letter"]), "sequence": sid, "section": s["letter"],
                     "title": s["title"], "page": src.get("page", 0) + 1, "sheet": src.get("sheet"),
                     "file": src.get("file"), "group": sid, "est_min": section_minutes(len(s["text"].split()))}
                    for s in q.cands["sections"]]
    return out


def build_sample(site: str) -> dict:
    """The fixed sample for one set, from the documents alone (never from an answer key)."""
    job = job_of(site)
    groups = plan_universe(site) if job == "plans" else sequence_universe(site)
    first = MIN_PER_SHEET if job == "plans" else 0.0
    items = pick_sample(groups, BUDGET_MIN[site], f"{SEED}:{site}", first_cost=first)
    n_groups = len({i["group"] for i in items})
    return {"job": job, "seed": f"{SEED}:{site}", "budget_min": BUDGET_MIN[site],
            "universe": sum(len(v) for v in groups.values()),
            "overhead_min": round(n_groups * first, 1) if job == "plans" else 0.0, "items": items}


def write_manifest(sites: list[str] | None = None) -> Path:
    sites = sites or [s for j in JOBS for s in offered(j)]
    m = load_manifest() or {"note": "The fixed sample per set (scripts/answer_key_sample.py). Never edit by hand."}
    m.setdefault("sets", {})
    for s in sites:
        m["sets"][s] = build_sample(s)
    MANIFEST.write_text("# The fixed, seeded sample each engineer works through (src/projectmodel/answer_keys.py).\n"
                        + yaml.safe_dump(m, sort_keys=False, allow_unicode=True, width=110))
    return MANIFEST


# the readers' answers, shown only after an item is done (the page makes no model call) -----------------------------

def plan_reader_answers(site: str, tag: str) -> list[str]:
    """What the plan reader says about one tag: the rules' placement, and each model's saved answer where the eval
    kept one (data/eval/plan_meaning_answers.json). One line each. Calls no model."""
    from .ai.jobs import get_job
    from .ai.prompts import load_prompt
    from .intake import pdfdoc, plan_ai
    from .scoring import eval as ev

    check_set("plans", site)
    n = plan_ai.normal_of(tag)

    def line(who: str, floor, room) -> str:
        return f"{who}: floor {floor or '?'}, " + (f"room {room}" if room else "no room")

    out = []
    f = next((f for f in ev.plan_rules_facts(site) if f["kind"] == "placement" and f["data"]["normal"] == n), None)
    out.append(line("Rules", f["data"].get("floor"), f["data"].get("room")) if f else "Rules: did not place this tag")
    pdf = ev.plan_pdf(site)
    cache = ev._plan_answers()
    job = get_job("plan_meaning")
    ref = load_prompt("plan_meaning").ref
    for model in dict.fromkeys([*job.chain, *job.contender]):
        found = None
        for i in range(len(plan_sheets(site))):
            ws = pdfdoc.words(pdf, i)
            pc = plan_ai.candidates(ws, i, pdfdoc.page_size(pdf, i))
            values = plan_ai.prompt_values(pc, pdf.name)
            a = cache.get(plan_ai.request_key(values, plan_ai.page_image(pdf, pc, True), ref) + f":{model}")
            if a and not a.get("error"):
                found = next((p for p in plan_ai.checked(a, pc)["placements"] if p["normal"] == n), found)
        if found:
            out.append(line(f"Model {model}", found.get("floor"), found.get("room")))
    return out


def sequence_reader_answers(site: str, sequence: str, section: str) -> list[str]:
    """What the sequence reader says about one section: the rules' relations, and each model's logged answer
    (llm_calls in data/kg.sqlite, when it has one). One line per relation. Calls no model."""
    from .ai.jobs import get_job
    from .intake import sequence_ai
    from .scoring import eval as ev
    from .scoring.human_keys import sec_letter

    check_set("sequences", site)
    q = next(q for q in ev._cache(("seqq", site), lambda: ev.sequence_read_questions(site))
             if q.seq["id"] == f"seq:{sequence}")
    want = sec_letter(section)

    def lines(who: str, rels: list[dict]) -> list[str]:
        mine = [r for r in rels if sec_letter(r.get("section")) == want]
        return [f"{who}: {r['from']} {r['rel']} {r['to']}" for r in mine] or [f"{who}: no relation from this section"]

    out = lines("Rules", q.rules)
    db = ROOT / "data/kg.sqlite"
    if db.exists():
        from .db.store import Store
        store = Store(db)
        job = get_job("sequence_read")
        for model in dict.fromkeys([*job.chain, *job.contender]):
            a = sequence_ai.logged_answer(store, model, q.values)
            if a:
                out += lines(f"Model {model}", a["output"]["relations"])
    return out
