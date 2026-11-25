"""Point binding (plan-workflow-ai §6.2 row 6, W7): which BMS object is the point the controls submittal promised.

Rules first, the model for what they leave (candidates in, ids out):

Devices. A BMS device is the submittal's (riser's) device when, first match wins:
  1. it has the same name;
  2. it is the same tag spelled another way (VAVE-07 = VAVE07 = VAVE_07, VAV_3_19 = VAV-19);
  3. it has the same BACnet device instance;
  4. it sits at the same address on the same trunk (an MS/TP address is unique on its trunk).
A gateway is one device for several units (the split systems behind one card): its units are paired by their number.

Points, on each pair of devices, each pass binding only what is still free:
  reference         the same object reference (NAE/FC-1.AHU-1.SF-C)
  device object     the same device instance, object type and object instance
  same name         the same point name, punctuation and the device's own name aside (EF-LAB-1-C = C)
  same description  the same description, parentheticals aside, unique on the device
  words             template roles: the point's words after the knowledge model's abbreviations, its Brick class,
                    its I/O kind and its number (SF3) agree with one free object far better than with any other,
                    and that object's best point is this one
What is left goes to the `point_bind` job: one question per point, with the free objects of its device ranked by the
same score (at most MAX_CANDIDATES), each with an id. The model answers an id or none, a confidence and a reason. Two
points picking one object: the more confident keeps it. Typicals (the same point and the same candidates on 19 boxes)
are asked once.

Confidence: every binding's raw confidence is calibrated per rule and per model (knowledge_model/calibration/
point_bind.json, fitted by `scripts/eval.py point_bind --fit`); a model with no calibration yet is capped below
auto-accept. The binding is a claim of the BMS step on the submittal's point (publish.py): the two agree or conflict
through W3's claims.

With PM_AI=off or no credentials nothing is called: the rules' bindings, and the points they leave unbound.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .. import calibration
from . import tags

JOB = "point_bind"
CALLER = "binding"  # calibration stratum of the model's answers (calibration.model_keys)
MAX_CANDIDATES = 10
AI_CAP = 0.85  # a model answer with no calibration yet stays below auto-accept
BATCH = 8
RAW = {"reference": 0.99, "device object": 0.96, "same name": 0.95, "same description": 0.92}
WORDS_MIN, WORDS_MARGIN = 0.6, 0.15  # the words rule binds a pair this good, this far ahead of the next one
IO = {"analog-input": "AI", "analog-output": "AO", "analog-value": "AV", "binary-input": "BI", "binary-output": "BO",
      "binary-value": "BV", "multi-state-value": "MV", "multi-state-input": "MI", "multi-state-output": "MO",
      "analoginput": "AI", "analogoutput": "AO", "analogvalue": "AV", "binaryinput": "BI", "binaryoutput": "BO",
      "binaryvalue": "BV", "multistatevalue": "MV"}


@dataclass
class Point:
    """A point the submittal promises."""
    id: str
    ref: str
    device: str
    short: str
    description: str
    io: str
    units: str = ""
    object: str = ""
    object_instance: int | None = None


@dataclass
class Obj:
    """A BMS object, as the export writes it."""
    ref: str
    device: str
    name: str
    description: str
    object_type: str = ""
    object_instance: int | None = None
    device_instance: int | str | None = None
    units: str = ""


@dataclass
class Bound:
    point: str            # submittal point id (pt:<ref>)
    obj: str              # BMS reference
    rule: str             # reference, device object, same name, same description, words, model
    raw: float
    conf: float
    method: str = "rule"  # rule | llm
    why: str = ""
    model: str | None = None
    calls: list = field(default_factory=list)


@dataclass
class Question:
    key: str
    values: dict
    points: list[Point]
    candidates: list[list[Obj]]  # per point, the objects behind the candidate ids
    answer: dict | None = None


# devices ------------------------------------------------------------------------------------------------------------

def _io(text: str | None) -> str:
    t = (text or "").strip().lower()
    return IO.get(t, IO.get(t.replace(" ", "").replace("-", ""), (text or "").strip().upper()[:2]))


def folder_tag(name: str) -> str | None:
    """The tag a device folder names, however it is spelled: VAVE-07, VAVE07, VAVE_07, VAV_3_19 (floor 3, box 19)."""
    n = name.strip().upper()
    for cand in (n, n.replace("_", "-"), re.sub(r"[_-]\d[_-](\d+[A-Z]?)$", r"-\1", n)):
        if t := tags.normal(cand):
            return t
    return None


def _trailing_number(name: str) -> int | None:
    m = re.search(r"(\d+)[A-Z]?$", name.upper())
    return int(m.group(1)) if m else None


def _pair_group(subs: list[str], bms: list[str]) -> dict[str, str]:
    """Pair the units behind one device instance or address (a gateway): one each, or by their numbers."""
    if len(subs) == 1 and len(bms) == 1:
        return {bms[0]: subs[0]}
    ns, nb = {_trailing_number(s): s for s in subs}, {_trailing_number(b): b for b in bms}
    if len(ns) == len(subs) and len(nb) == len(bms) and None not in ns and set(ns) == set(nb):
        return {nb[k]: ns[k] for k in ns}
    return {}


def match_devices(sub: dict[str, dict], bms: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """BMS device -> (the submittal's device, why). `sub` and `bms`: name -> {instance, trunk, address}."""
    out: dict[str, tuple[str, str]] = {}
    used: set[str] = set()

    def take(b: str, s: str, via: str) -> None:
        out[b] = (s, via)
        used.add(s)

    for b in bms:
        if b in sub:
            take(b, b, "same name")
    by_tag: dict[str, list[str]] = {}
    for s in sub:
        if s not in used and (t := folder_tag(s)):
            by_tag.setdefault(t, []).append(s)
    for b in bms:
        if b not in out and (t := folder_tag(b)) and len(by_tag.get(t, [])) == 1 and by_tag[t][0] not in used:
            take(b, by_tag[t][0], "same tag")
    for via, key in (("device instance", lambda i: str(i.get("instance") or "")),
                     ("trunk and address", lambda i: f"{i.get('trunk') or ''}|{i.get('address') or ''}"
                      if i.get("trunk") and i.get("address") not in (None, "") else "")):
        groups_s: dict[str, list[str]] = {}
        groups_b: dict[str, list[str]] = {}
        for s, i in sub.items():
            if s not in used and (k := key(i)):
                groups_s.setdefault(k, []).append(s)
        for b, i in bms.items():
            if b not in out and (k := key(i)):
                groups_b.setdefault(k, []).append(b)
        for k, bs in groups_b.items():
            for b, s in _pair_group(groups_s.get(k, []), bs).items():
                take(b, s, via)
    return out


# scoring a pair -----------------------------------------------------------------------------------------------------

def _matcher():
    from .submittal import _matcher
    return _matcher()


_WORDS: dict[str, tuple[frozenset, str | None]] = {}
_WLOCK = threading.Lock()


def _words(text: str) -> tuple[frozenset, str | None]:
    """The canonical words of a point's text (the knowledge model's abbreviations and synonyms) and its class."""
    with _WLOCK:
        if text in _WORDS:
            return _WORDS[text]
    g = _matcher().classify(text)
    out = (frozenset(g.words) | frozenset(u.lower() for u in g.unknown), g.cls)
    with _WLOCK:
        _WORDS[text] = out
    return out


def _strip(name: str, device: str) -> str:
    """A point name without its device's name in front (EF-LAB-1-C -> C, LEF_1_CMD -> CMD)."""
    for sep in ("-", "_", ".", " "):
        if device and name.upper().startswith(device.upper() + sep):
            return name[len(device) + 1:]
    return name


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"\(.*?\)", "", text or "").upper())


def _numbers(name: str) -> frozenset:
    return frozenset(int(n) for n in re.findall(r"\d+", name))


def point_text(p: Point) -> str:
    return f"{_strip(p.short, p.device)} {re.sub(r'[(].*?[)]', '', p.description)}"


def obj_text(o: Obj) -> str:
    return f"{_strip(o.name, o.device)} {re.sub(r'[(].*?[)]', '', o.description)}"


def score(p: Point, o: Obj) -> float:
    """How well a BMS object fits a submittal point, from what both say: shared words (Jaccard), the same Brick class,
    the same I/O kind, the same number in the name, the same units. Roughly 0 (nothing in common) to 1.6."""
    wp, cp = _words(point_text(p))
    wo, co = _words(obj_text(o))
    s = len(wp & wo) / max(1, len(wp | wo))
    if cp and cp == co:
        s += 0.25
    ip, io = _io(p.io or p.object), _io(o.object_type)
    if ip and io and ip not in ("BN", "SO") and io:
        s += 0.15 if ip == io else 0.05 if ip[0] == io[0] else -0.3
    np_, no = _numbers(_strip(p.short, p.device)), _numbers(_strip(o.name, o.device))
    if np_ and no:
        s += 0.2 if np_ == no else -0.5
    elif np_ != no:
        s -= 0.1
    if p.units and o.units:
        s += 0.1 if p.units.strip().lower() == o.units.strip().lower() else -0.05
    return round(s, 4)


# rules --------------------------------------------------------------------------------------------------------------

def calibrated(raw: float, rule: str, model: str | None = None) -> float:
    cal = calibration.load(JOB)
    if model:
        keys = calibration.model_keys(model, CALLER)
        if not cal or not any(k in cal.curves for k in keys):
            return round(min(raw, AI_CAP), 4)
        return round(cal.apply(raw, keys), 4)
    return round(cal.apply(raw, (f"rule|{rule}",)), 4) if cal else raw


def bind_rules(points: list[Point], objs: list[Obj], devices: dict[str, tuple[str, str]],
               device_instance: dict[str, int | None]) -> tuple[dict[str, Bound], dict[str, list[Obj]]]:
    """The rules' bindings (point id -> Bound) and, per point they leave, its device's free objects."""
    bound: dict[str, Bound] = {}
    taken: set[str] = set()

    def bind(p: Point, o: Obj, rule: str, raw: float, why: str) -> None:
        bound[p.id] = Bound(p.id, o.ref, rule, raw, calibrated(raw, rule), why=why)
        taken.add(o.ref)

    by_ref = {o.ref: o for o in objs}
    for p in points:  # the same reference, whatever the devices are called
        if (o := by_ref.get(p.ref)) is not None:
            bind(p, o, "reference", RAW["reference"], "the same object reference")
    sub_of = {b: s for b, (s, _) in devices.items()}
    objs_of: dict[str, list[Obj]] = {}
    for o in objs:
        if (s := sub_of.get(o.device)) is not None:
            objs_of.setdefault(s, []).append(o)
    points_of: dict[str, list[Point]] = {}
    for p in points:
        points_of.setdefault(p.device, []).append(p)

    for dev, ps in points_of.items():
        cands = objs_of.get(dev, [])
        if not cands:
            continue

        def free_p():
            return [p for p in ps if p.id not in bound]

        def free_o():
            return [o for o in cands if o.ref not in taken]

        inst = device_instance.get(dev)
        bms_inst = {o.device_instance for o in cands}
        for p in free_p():  # the same BACnet object, where the submittal gives one and the device instances agree
            if not (p.object and p.object_instance is not None and inst is not None and str(inst) in map(str, bms_inst)):
                continue
            hit = [o for o in free_o() if _io(o.object_type) == _io(p.object) and o.object_instance == p.object_instance]
            if len(hit) == 1:
                bind(p, hit[0], "device object", RAW["device object"], f"the same BACnet object {p.object} "
                                                                       f"{p.object_instance} on device {inst}")
        for rule, key_p, key_o in (("same name", lambda p: _norm(_strip(p.short, p.device)),
                                    lambda o: _norm(_strip(o.name, o.device))),
                                   ("same description", lambda p: _norm(p.description), lambda o: _norm(o.description))):
            fo = free_o()
            index: dict[str, list[Obj]] = {}
            for o in fo:
                if k := key_o(o):
                    index.setdefault(k, []).append(o)
            counts: dict[str, int] = {}
            for p in free_p():
                counts[key_p(p)] = counts.get(key_p(p), 0) + 1
            for p in free_p():
                k = key_p(p)
                if k and counts[k] == 1 and len(index.get(k, [])) == 1:
                    bind(p, index[k][0], rule, RAW[rule], f"the {rule.split()[1]} is the same")
        # template roles: mutual best pairs, far ahead of the runners-up
        fp, fo = free_p(), free_o()
        if fp and fo:
            sc = {(p.id, o.ref): score(p, o) for p in fp for o in fo}
            pairs = sorted(sc.items(), key=lambda x: -x[1])
            pid = {p.id: p for p in fp}
            oid = {o.ref: o for o in fo}
            for (a, b), s in pairs:
                if s < WORDS_MIN:
                    break
                if a in bound or b in taken:
                    continue
                second_p = max((v for (x, y), v in sc.items() if x == a and y != b and y not in taken), default=0.0)
                second_o = max((v for (x, y), v in sc.items() if y == b and x != a and x not in bound), default=0.0)
                margin = min(s - second_p, s - second_o)
                if margin >= WORDS_MARGIN:
                    raw = round(min(0.89, 0.4 + 0.3 * min(s, 1.5) / 1.5 + 0.4 * min(margin, 0.5)), 4)
                    bind(pid[a], oid[b], "words", raw, f"words, class, I/O and number agree (score {s:.2f}, "
                                                       f"{margin:.2f} ahead)")
    left: dict[str, list[Obj]] = {}
    for dev, ps in points_of.items():
        free = [o for o in objs_of.get(dev, []) if o.ref not in taken]
        for p in ps:
            if p.id not in bound and free:
                left[p.id] = sorted(free, key=lambda o: (-score(p, o), o.ref))[:MAX_CANDIDATES]
    return bound, left


# the model ----------------------------------------------------------------------------------------------------------

def _obj_line(o: Obj) -> str:
    bits = [_strip(o.name, o.device), o.description or "(no description)", o.object_type or "", o.units or ""]
    return " · ".join(b for b in bits if b)


def _point_line(p: Point) -> str:
    bits = [_strip(p.short, p.device), p.description, p.io, p.units]
    return " · ".join(b for b in bits if b)


def questions(points: list[Point], left: dict[str, list[Obj]], devices: dict[str, tuple[str, str]],
              equip_class: dict[str, str | None], prompt_ref: str, cache: dict | None = None) -> list[Question]:
    """One question per distinct point and candidate list: typicals on 19 boxes are one question."""
    from ..ai.prompts import load_prompt  # noqa: F401 - the prompt must exist before questions are built

    bms_of = {}
    for b, (s, _) in devices.items():
        bms_of.setdefault(s, []).append(b)
    out: dict[str, Question] = {}
    for p in points:
        cands = left.get(p.id)
        if not cands:
            continue
        ids = [f"B{i + 1}" for i in range(len(cands))]
        lines = "\n".join(f"- {i}: {_obj_line(o)}" for i, o in zip(ids, cands))
        values = {"point": _point_line(p), "equipment_class": equip_class.get(p.device) or "(unknown)",
                  "device": p.device, "bms_device": ", ".join(sorted(bms_of.get(p.device, []))) or "(unknown)",
                  "candidates": lines, "candidate_list": ids}
        text = json.dumps([prompt_ref, values["point"], values["equipment_class"], lines])
        key = hashlib.sha1(text.encode()).hexdigest()
        q = out.get(key)
        if q is None:  # the first unit's device names stand for the typical's
            q = out[key] = Question(key, values, [], [], answer=(cache or {}).get(key))
        q.points.append(p)
        q.candidates.append(cands)
    return list(out.values())


def logged_answer(store, model: str, values: dict) -> dict | None:
    """An answer already paid for: the latest successful call with this exact request, model and prompt version."""
    from ..ai.calls import parse_json, request_log
    from ..ai.jobs import check_output, job_request
    from ..ai.models import get_model
    from ..ai.providers import ModelError

    if store is None:
        return None
    req, prompt = job_request(JOB, values)
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
            return {"pick": out["pick"], "confidence": float(out["confidence"]), "why": out["why"], "model": model,
                    "calls": [r["id"]], "cost_usd": 0.0, "paid_usd": r["cost_usd"], "latency_s": 0.0,
                    "logged": True}
    return None


def ask(values: dict, router, store, project: str, model: str | None = None) -> dict:
    from ..ai.jobs import get_job, run_job
    from ..ai.providers import ModelError

    for m in ([model] if model else [k for k in (*get_job(JOB).chain, *get_job(JOB).contender)
                                     if k not in getattr(router, "not_enabled", {})][:1]):
        if (a := logged_answer(store, m, values)) is not None:
            return a
    try:
        res = run_job(JOB, values, router=router, store=store, project=project, model=model)
    except ModelError as e:
        return {"error": str(e)[:300]}
    o = res.output
    return {"pick": o["pick"], "confidence": float(o["confidence"]), "why": o["why"], "model": res.model,
            "calls": [a["call"] for a in res.attempts if a["call"]], "cost_usd": res.cost_usd,
            "latency_s": res.latency_s}


def ask_all(qs: list[Question], router, store, project: str, model: str | None = None, batch: int = BATCH,
            log=lambda m: None) -> None:
    todo = [q for q in qs if q.answer is None]
    if not todo:
        return
    local = threading.local()
    done = [0]

    def one(q: Question) -> None:
        st = store
        if store is not None and store.path != ":memory:":
            if not hasattr(local, "store"):
                from ..db.store import Store
                local.store = Store(store.path)
            st = local.store
        q.answer = ask(q.values, router, st, project, model)
        done[0] += 1
        if done[0] % 50 == 0:
            log(f"AI point binding: {done[0]}/{len(todo)} questions")

    one(todo[0])
    if todo[0].answer.get("error") and ("404" in todo[0].answer["error"] or "not enabled" in todo[0].answer["error"]):
        for q in todo[1:]:
            q.answer = dict(todo[0].answer)
        return
    if store is None or store.path == ":memory:" or batch <= 1:
        for q in todo[1:]:
            one(q)
        return
    with ThreadPoolExecutor(max_workers=batch) as pool:
        list(pool.map(one, todo[1:]))


def apply_answers(qs: list[Question], bound: dict[str, Bound]) -> dict:
    """The model's picks become bindings (method llm, calibrated confidence). One object, one point: the more
    confident answer keeps it. Returns counts."""
    picks: list[tuple[float, Point, Obj, dict]] = []
    n = {"answered": 0, "none": 0, "error": 0}
    for q in qs:
        a = q.answer or {}
        if a.get("error"):
            n["error"] += len(q.points)
            continue
        if not a.get("pick"):
            n["none"] += len(q.points)
            continue
        idx = int(a["pick"][1:]) - 1
        for p, cands in zip(q.points, q.candidates):
            picks.append((a["confidence"], p, cands[idx], a))
    taken = {b.obj for b in bound.values()}
    for conf, p, o, a in sorted(picks, key=lambda x: -x[0]):
        if o.ref in taken or p.id in bound:
            continue
        taken.add(o.ref)
        n["answered"] += 1
        bound[p.id] = Bound(p.id, o.ref, "model", conf, calibrated(conf, "model", a.get("model")), method="llm",
                            why=a.get("why", ""), model=a.get("model"), calls=a.get("calls", []))
    return n


@dataclass
class AI:
    """How the binding job is run: by the setup (the app's router and store), or by the eval (one model)."""
    project: str = "intake"
    cache: dict | None = None
    router: object | None = None
    store: object | None = None
    model: str | None = None
    batch: int = BATCH
    summary: dict = field(default_factory=dict)  # the last run's counts and cost (set by `bind`)


def bind(points: list[Point], objs: list[Obj], devices: dict[str, tuple[str, str]],
         device_instance: dict[str, int | None], equip_class: dict[str, str | None], log=lambda m: None,
         ai: AI | None = None) -> tuple[dict[str, Bound], dict]:
    """Rules, then (when `ai` is given and models can be called) the point_bind job. Returns point id -> Bound and a
    summary for the log and the scorer."""
    bound, left = bind_rules(points, objs, devices, device_instance)
    summary = {"rules": len(bound), "left": len(left), "questions": 0, "asked": 0, "logged": 0, "cached": 0,
               "cost_usd": 0.0, "calls": 0, "model_bound": 0, "none": 0, "error": 0, "off": ""}
    if not left or ai is None:
        return bound, summary
    from ..ai.calls import default_router
    from ..ai.prompts import load_prompt
    from ..ai.providers import ModelUnavailable

    router = ai.router or default_router()
    if not router.ready:
        summary["off"] = router.why_not_ready()
        log(f"AI point binding off ({summary['off']}): {len(left)} points stay unbound for review.")
        return bound, summary
    store = ai.store
    if store is None:
        from ..db.store import Store
        from .point_ai import DB
        store = Store(DB)
    if not getattr(router, "learnt", True) and hasattr(router, "learn"):
        router.learn(store)
    cache = ai.cache if ai.cache is not None else {}
    qs = questions(points, left, devices, equip_class, load_prompt(JOB).ref, cache)
    summary["questions"] = len(qs)
    new = {q.key for q in qs if q.answer is None}
    log(f"AI point binding: {len(left)} points the rules left → {len(qs)} questions to {JOB} ({len(new)} new)…")
    try:
        ask_all(qs, router, store, f"{ai.project}", ai.model, ai.batch, log)
    except ModelUnavailable as e:
        summary["off"] = str(e)
    for q in qs:
        a = q.answer
        if a is None:
            continue
        if q.key not in new:
            summary["cached"] += 1
        elif a.get("logged"):
            summary["logged"] += 1
        else:
            summary["asked"] += 1
            summary["calls"] += len(a.get("calls", []))
            summary["cost_usd"] += a.get("cost_usd", 0.0)
        # what this building's answers cost when first paid for, wherever they come from now
        summary["paid_usd"] = summary.get("paid_usd", 0.0) + (a.get("cost_usd") or a.get("paid_usd") or 0.0)
        summary["not_enabled"] = summary.get("not_enabled", 0) + bool(
            a.get("error") and ("404" in a["error"] or "not enabled" in a["error"].lower()))
        if not a.get("error"):
            cache[q.key] = a
    n = apply_answers(qs, bound)
    summary.update(model_bound=n["answered"], none=n["none"], error=n["error"],
                   cost_usd=round(summary["cost_usd"], 4), paid_usd=round(summary.get("paid_usd", 0.0), 4))
    ai.summary = summary
    log(f"AI point binding: {n['answered']} bound by the model, {n['none']} answered none, {n['error']} failed; "
        f"{summary['asked']} asked (${summary['cost_usd']:.3f}), {summary['logged'] + summary['cached']} from earlier "
        "answers.")
    return bound, summary
