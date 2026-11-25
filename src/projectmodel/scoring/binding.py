"""Point binding on Troop D under another integrator's naming (plan-workflow-ai W7, §6.2 row 6).

Binding: which BMS object is the point the controls submittal promised. On Troop D the two sides were generated from
one list, so every name lines up and an exact reference binds all 847. A real BMS export comes from the integrator's
own database: its folders, point names, descriptions and BACnet instances need not match the submittal's.

Scenarios. Each one rewrites Troop D's BMS export (and, for "missing", drops points on either side) the way another
integrator would write it. The rewrites are mechanical functions of the original rows, so each scenario's answer key
is built from the Troop D key, exactly:

    baseline    the export as generated
    names       point names re-abbreviated and reordered (OCC-CLG-SP -> COOL_OCC_STPT, ZN-T -> SPACE_TEMP) and
                descriptions in the integrator's terse wording ("Occ Clg SP", parentheticals dropped)
    folders     equipment folders renamed (VAVE-07 -> VAVR_1_07, FVAV-03 -> FPB_1_03, CH-1A -> CHLR_1A,
                EF-LAB-1 -> LEF_1, CHW-PLANT -> CHW_SYS); device instances kept
    instances   device instances renumbered and devices named by them (DEV100037), object instances renumbered
    missing     8% of BMS objects and 8% of submittal points dropped (by a stable hash of the reference)
    integrator  all of it at once: names, folders, renumbered instances, missing points
    integrator_names_only   the same with no descriptions (a Niagara station's export): added after the first
                rules-only results showed the six above bound 99-100% by rules; frozen before anything ran on it

Key: for every submittal point the scenario keeps, the BMS reference it is (after the rewrite), or None when the BMS
side dropped it. The scenarios and keys were committed before any binder ran on them; they are never tuned after.

Scores (`score`): precision and recall of the submittal point -> BMS object pairs, and the share auto-bound (calibrated
confidence at or above auto-accept) with how many of those are wrong.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TROOP_D = ROOT / "data/ground_truth/troop_d"
BMS_EXPORT = ROOT / "test_packages/troop_d/5_bms_export.csv"
REF = re.compile(r"^(?P<nae>[^/]+)/(?P<trunk>[^.]+)\.(?P<device>[^.]+)\.(?P<name>.+)$")
ORIG = "_orig"  # hidden column: the row's reference in the original export (dropped before the CSV is written)

# Integrator B's point-name vocabulary: token by token, letters apart from their number (SF1 -> SUPFAN1).
NAME_TOKENS = {
    "ZN": "SPACE", "T": "TEMP", "SP": "STPT", "DA": "DISCH", "SA": "SUP", "F": "FLOW", "DPR": "DMPR", "O": "OUT",
    "C": "CMD", "S": "STS", "E": "ENA", "HTG": "HEAT", "CLG": "COOL", "A": "ALM", "P": "PRESS", "H": "RH",
    "SAFLOW": "AIRFLOW", "SCHEDULE": "SCHED", "MA": "MIX", "RA": "RET", "OA": "OUTSIDE", "SF": "SUPFAN",
    "EF": "EXHFAN", "EAD": "EXHDMPR", "RAD": "RETDMPR", "MOA": "MINOA", "CHWV": "CHWVLV", "CHWS": "CHWST",
    "CHWR": "CHWRT", "CCLA": "CCLAT", "BLDG": "BLDG", "BLDGP": "BLDGPRESS", "DAP": "DUCTPRESS", "FLT": "FILTER",
    "DP": "DIFF", "HSP": "HISTATIC", "LSP": "LOSTATIC", "LT": "FRZ", "SMK": "SMOKE", "HUM": "HUMID", "PH": "PREHEAT",
    "ECON": "ECONO", "LEAK": "DRAINPAN", "SYS": "SYSTEM", "RESET": "RST", "ISOV": "ISOVLV", "EVAP": "EVAP",
    "FS": "FLOWSW", "COND": "COND", "SUCT": "SUCTION", "AMB": "AMBIENT", "LCHWT": "LCHWT", "EEWT": "EVAPEWT",
    "LEWT": "EVAPLWT", "COMM": "COMMSTS", "MODE": "MODE", "RUN": "RUN", "CWS": "CHWST", "CWR": "CHWRT",
    "CW": "CHW", "LEAD": "LEAD", "LAG": "LAG", "ON": "ON", "OFF": "OFF", "CH": "CHLR", "CWP": "PUMP",
    "BYP": "BYPASS", "SPD": "SPEED", "FAN": "FAN", "OCC": "OCC", "UNOCC": "UNOCC",
}
# ... and its terse descriptions: phrases first, then words.
DESC_PHRASES = [("Chilled Water", "CHW"), ("Start/Stop", "S/S"), ("Air Temperature", "Air Temp")]
DESC_WORDS = {
    "Zone": "Space", "Temperature": "Temp", "Setpoint": "SP", "Occupied": "Occ", "Unoccupied": "Unocc",
    "Cooling": "Clg", "Heating": "Htg", "Discharge": "Disch", "Supply": "Sup", "Return": "Ret", "Airflow": "Air Flow",
    "Damper": "Dmpr", "Output": "Out", "Status": "Sts", "Command": "Cmd", "Enable": "Ena", "Exhaust": "Exh",
    "Pressure": "Press", "Humidity": "RH", "Outdoor": "OA", "Minimum": "Min", "Differential": "Diff",
    "Electric": "Elec", "Parallel": "Par", "Building": "Bldg", "Entering": "Ent", "Leaving": "Lvg",
    "Evaporator": "Evap", "Evaporating": "Evap", "Condensing": "Cond", "Communication": "Comm", "Operation": "Op",
    "Operating": "Op", "Generator": "Gen", "Detector": "Det", "Schedule": "Sched", "Adjust": "Adj", "Speed": "Spd",
}
# Integrator B's equipment folders: prefix map, terminal boxes with their floor (VAVR_1_07).
FOLDER_PREFIX = {"VAV": "VAV", "VAVE": "VAVR", "FVAV": "FPB", "AHU": "AH", "CH": "CHLR", "CWP": "CHWP", "MS": "SPLIT"}
FOLDER_NAMED = {"CHW-PLANT": "CHW_SYS", "EF-LAB-1": "LEF_1", "EF-LAB-2": "LEF_2", "EF-RR": "EF_RR",
                "EF-CONT": "EF_CONT"}
TERMINALS = ("VAV", "VAVE", "FVAV")
DROP_PCT = 8


def _hash(salt: str, text: str) -> int:
    return int(hashlib.sha1(f"{salt}:{text}".encode()).hexdigest(), 16)


@lru_cache
def key_equipment() -> dict[str, dict]:
    """The Troop D key's equipment by BMS device name."""
    return {e["bms_name"]: e for e in csv.DictReader((TROOP_D / "equipment.csv").open()) if e["bms_name"]}


@lru_cache
def key_points() -> dict[str, dict]:
    """The Troop D key's points by reference (the submittal and the BMS export were generated with the same one)."""
    return {p["bms_name"]: p for p in csv.DictReader((TROOP_D / "points.csv").open())}


def original_rows() -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(BMS_EXPORT.read_text(encoding="utf-8-sig"))))
    return [dict(r, **{ORIG: r["Item Reference"]}) for r in rows]


def _device(r: dict) -> str:
    return re.sub(r"\s*\(.*\)$", "", r["Device"]).strip()


def _with(r: dict, device: str | None = None, name: str | None = None) -> dict:
    """The row with its device folder and point name changed, its reference rebuilt to match."""
    m = REF.match(r["Item Reference"])
    dev, nm = device or m["device"], name or m["name"]
    model = re.search(r"\(.*\)$", r["Device"])
    return dict(r, **{"Item Reference": f"{m['nae']}/{m['trunk']}.{dev}.{nm}", "Name": nm,
                      "Device": dev + (f" {model.group(0)}" if model else "")})


def _split_name(name: str, device: str) -> tuple[str, str]:
    """(device prefix in the name, the rest): EF-LAB-1-C on EF-LAB-1 -> ("EF-LAB-1", "C")."""
    return (device, name[len(device) + 1:]) if name.startswith(device + "-") else ("", name)


def rename_point(name: str, device: str) -> str:
    """Integrator B's name for a point: tokens mapped, the first two swapped when there are three or more
    (OCC-CLG-SP -> COOL_OCC_STPT), joined by underscores. A device prefix in the name stays in front."""
    prefix, rest = _split_name(name, device)
    out = []
    for t in rest.split("-"):
        m = re.fullmatch(r"([A-Z]+)(\d*)([A-Z]?)", t)
        out.append(NAME_TOKENS.get(m[1], m[1]) + m[2] + m[3] if m else t)
    if len(out) >= 3:
        out[0], out[1] = out[1], out[0]
    return (f"{prefix}_" if prefix else "") + "_".join(out)


def reword(desc: str) -> str:
    """Integrator B's terse description: parentheticals dropped, phrases and words abbreviated."""
    d = re.sub(r"\s*\(.*?\)", "", desc).strip()
    for a, b in DESC_PHRASES:
        d = d.replace(a, b)
    return " ".join(DESC_WORDS.get(w, w) for w in d.split())


def rename_folder(device: str) -> str:
    if device in FOLDER_NAMED:
        return FOLDER_NAMED[device]
    m = re.fullmatch(r"([A-Z]+)-(\d+)([A-Z]?)", device)
    if not m:
        return device.replace("-", "_")
    prefix = FOLDER_PREFIX.get(m[1], m[1])
    if m[1] in TERMINALS:
        floor = key_equipment()[device]["floor"]
        return f"{prefix}_{floor[1:] if floor[0] == 'L' else floor}_{int(m[2]):02d}"
    return f"{prefix}_{int(m[2])}{m[3]}"


def names(rows: list[dict]) -> list[dict]:
    return [_with(dict(r, Description=reword(r["Description"])), name=rename_point(r["Name"], _device(r)))
            for r in rows]


def folders(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        dev = _device(r)
        new = rename_folder(dev)
        prefix, rest = _split_name(r["Name"], dev)
        name = r["Name"] if not prefix else f"{new}-{rest}"
        # a name built by `names` already: "EF-LAB-1_CMD"
        if r["Name"].startswith(dev + "_"):
            name = new + r["Name"][len(dev):]
        out.append(_with(r, device=new, name=name))
    return out


def _new_instances(rows: list[dict]) -> dict[str, int]:
    devices = sorted({r["Device Instance"] for r in rows}, key=int)
    return {d: 100000 + 37 * (k + 1) for k, d in enumerate(devices)}


def renumber(rows: list[dict], rename_devices: bool) -> list[dict]:
    """Device instances renumbered (100037, 100074...), object instances renumbered per device and object type in
    reverse row order; with `rename_devices`, each device folder named by its new instance (DEV100037)."""
    inst = _new_instances(rows)
    seq: dict[tuple, int] = {}
    new_obj: dict[int, int] = {}
    for n in range(len(rows) - 1, -1, -1):
        r = rows[n]
        k = (r["Device Instance"], r["Object Type"])
        seq[k] = seq.get(k, 0) + 1
        new_obj[n] = seq[k]
    # A gateway is one BACnet device for several units (the three split systems): DEV100407-1, -2, -3.
    shared: dict[str, list[str]] = {}
    for r in rows:
        units = shared.setdefault(r["Device Instance"], [])
        if _device(r) not in units:
            units.append(_device(r))
    out = []
    for n, r in enumerate(rows):
        dev_inst = inst[r["Device Instance"]]
        units = shared[r["Device Instance"]]
        r = dict(r, **{"Device Instance": str(dev_inst), "Instance": str(new_obj[n])})
        if rename_devices:
            dev = _device(r)
            prefix, rest = _split_name(r["Name"], dev)
            folder = f"DEV{dev_inst}" + (f"-{units.index(dev) + 1}" if len(units) > 1 else "")
            r = _with(r, device=folder, name=r["Name"] if not prefix else rest)
        out.append(r)
    return out


def drop_bms(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _hash("bms", r[ORIG]) % 100 >= DROP_PCT]


def dropped_submittal(scenario: str) -> set[str]:
    """Submittal references the scenario drops (the submittal does not list them)."""
    if scenario not in ("missing", "integrator", "integrator_names_only"):
        return set()
    return {ref for ref in key_points() if _hash("submittal", ref) % 100 < DROP_PCT}


SCENARIOS: dict[str, Callable[[list[dict]], list[dict]]] = {
    "baseline": lambda rows: rows,
    "names": names,
    "folders": folders,
    "instances": lambda rows: renumber(rows, rename_devices=True),
    "missing": drop_bms,
    "integrator": lambda rows: drop_bms(renumber(folders(names(rows)), rename_devices=False)),
    # Added after the first rules-only results (the six above bound 99-100% by rules): many exports (a Niagara
    # station's) carry no description at all, so the name is all there is. Frozen before anything ran on it.
    "integrator_names_only": lambda rows: [dict(r, Description="") for r in
                                           drop_bms(renumber(folders(names(rows)), rename_devices=False))],
}
TITLES = {
    "baseline": "Troop D as generated (names line up)",
    "names": "point names re-abbreviated and reordered, terse descriptions",
    "folders": "equipment folders renamed (VAVE-07 -> VAVR_1_07)",
    "instances": "device and object instances renumbered, devices named DEV<instance>",
    "missing": "8% of points missing on each side",
    "integrator": "another integrator: all of the above at once",
    "integrator_names_only": "another integrator, names only (no descriptions)",
}


def variant_rows(scenario: str) -> list[dict]:
    """The scenario's BMS rows, each with its original reference in ORIG."""
    return SCENARIOS[scenario](original_rows())


def variant_csv(scenario: str) -> bytes:
    rows = variant_rows(scenario)
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=[k for k in rows[0] if k != ORIG])
    w.writeheader()
    w.writerows([{k: v for k, v in r.items() if k != ORIG} for r in rows])
    return out.getvalue().encode()


def csv_transform(scenario: str) -> Callable[[list[dict]], list[dict]]:
    """For scripts/stress_intake.py: rows of the export as read -> the scenario's rows (BMS side only)."""
    def fn(rows: list[dict]) -> list[dict]:
        rows = [dict(r, **{ORIG: r["Item Reference"]}) for r in rows]
        return [{k: v for k, v in r.items() if k != ORIG} for r in SCENARIOS[scenario](rows)]
    return fn


def key(scenario: str) -> dict[str, str | None]:
    """Submittal reference -> the BMS reference it is in this scenario, or None when the BMS side dropped it. Built
    from the Troop D key: every key point is on both sides of the original export with the same reference."""
    now = {r[ORIG]: r["Item Reference"] for r in variant_rows(scenario)}
    gone = dropped_submittal(scenario)
    return {ref: now.get(ref) for ref in key_points() if ref not in gone}


# running and scoring ------------------------------------------------------------------------------------------------

def base_intake():
    """Troop D's guided setup, rules only (scoring/eval.py's intake run, cached): its submittal points, controllers
    and equipment are the submittal side of every scenario."""
    from . import eval as ev
    return ev._cache(("intake", "troop_d"), lambda: ev.intake_run("troop_d"))["intake"]


def run(scenario: str, ai=None, log=lambda m: None) -> dict:
    """The BMS step on the scenario's export, with the submittal points it keeps; raw confidences. `ai`: an
    intake.binding.AI to let the point_bind job bind what the rules leave."""
    import tempfile

    from .. import calibration as cal
    from ..intake import bms

    it = base_intake()
    gone = dropped_submittal(scenario)
    points = [p for p in it.facts(kind="point", live=True) if p["data"]["ref"] not in gone]
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "5_bms_export.csv"
        path.write_bytes(variant_csv(scenario))
        with cal.disabled():
            facts = bms.read(path, path.name, it.facts(kind="equipment", live=True),
                             it.facts(kind="controller", live=True), points, log, ai=ai)
    return {"scenario": scenario, "points": points, "facts": facts}


def pairs(facts: list[dict]) -> dict[str, dict]:
    """Submittal reference -> {bms, rule, raw, model} for every bound BMS object."""
    out = {}
    for f in facts:
        d = f["data"]
        if f["kind"] == "bms_object" and d.get("matched") and d.get("point"):
            b = d.get("bind", {})
            out[d["point"][3:]] = {"bms": d["ref"], "rule": b.get("rule", "reference"), "raw": b.get("raw", f["conf"]),
                                   "model": b.get("model"), "device": d["device"], "calls": b.get("calls") or []}
    return out


def items(scenario: str, got: dict[str, dict]) -> list[dict]:
    """One scored item per binding made: raw confidence, right or not, calibration keys and fold group (the
    submittal's device, the same in every scenario)."""
    from .. import calibration as cal
    from ..intake.binding import CALLER

    k = key(scenario)
    out = []
    for sub, g in got.items():
        model = g.get("model")
        keys = cal.model_keys(model, CALLER) if model else (f"rule|{g['rule']}",)
        # one model answer is one judgment, however many typicals it binds: its points share a fold
        group = f"answer:{g['calls'][0]}" if model and g.get("calls") else REF.match(sub)["device"]
        out.append({"raw": float(g["raw"]), "ok": k.get(sub) == g["bms"], "keys": list(keys), "rule": g["rule"],
                    "group": group, "set": scenario, "model": model, "fixed": False, "id": sub})
    return out


def score(scenario: str, got: dict[str, dict], conf: dict[str, float] | None = None,
          threshold: float = 0.9) -> dict:
    """Precision and recall of the bindings against the scenario's key; auto-bound: bindings whose (calibrated)
    confidence `conf` reaches the threshold, as a share of the key's bindings, and how many of them are wrong."""
    k = key(scenario)
    want = {s: b for s, b in k.items() if b}
    tp = sum(1 for s, g in got.items() if want.get(s) == g["bms"])
    fp = len(got) - tp
    precision = round(100 * tp / len(got), 1) if got else None
    recall = round(100 * tp / len(want), 1) if want else None
    f1 = round(2 * precision * recall / (precision + recall), 1) if precision and recall else 0.0
    out = {"scenario": scenario, "points": len(k), "key_bindings": len(want), "bound": len(got), "right": tp,
           "wrong": fp, "missed": len(want) - tp, "precision_pct": precision, "recall_pct": recall, "f1": f1,
           "by_rule": {}}
    for s, g in got.items():
        r = out["by_rule"].setdefault(g["rule"], {"n": 0, "right": 0})
        r["n"] += 1
        r["right"] += want.get(s) == g["bms"]
    if conf is not None:
        auto = [s for s in got if conf.get(s, 0.0) >= threshold]
        out["auto"] = {"threshold": threshold, "n": len(auto),  # share of the scenario's submittal points
                       "pct": round(100 * len(auto) / len(k), 1) if k else None,
                       "wrong": sum(1 for s in auto if want.get(s) != got[s]["bms"])}
    return out


# the eval (scripts/eval.py point_bind) --------------------------------------------------------------------------

VARIATIONS = [s for s in SCENARIOS if s != "baseline"]


def _pooled(rows: list[dict]) -> dict:
    """Precision, recall and F1 over several scenarios' rows (summed counts)."""
    tp, bound, want = (sum(r[k] for r in rows) for k in ("right", "bound", "key_bindings"))
    p = round(100 * tp / bound, 1) if bound else None
    r = round(100 * tp / want, 1) if want else None
    return {"precision_pct": p, "recall_pct": r, "f1": round(2 * p * r / (p + r), 1) if p and r else 0.0,
            "right": tp, "bound": bound, "key_bindings": want}


def evaluate(sets: list[str] | None = None, models: list[str] | None = None, *, router=None, store=None,
             fit: bool = False, budget: float | None = None, log=print) -> dict:
    """Rules alone, then each model plus the rules, on every scenario. Calibration: the rules' bindings (per rule) and
    each model's answers, held out by k-fold (folds by the submittal's device, a model answer's points together).
    The §6.4 verdict for each model: model + rules beats rules alone on F1 pooled over the variations; the model's
    calibrated answers within 5 points per band of 30+; $ per 1,000 points under the budget."""
    from .. import calibration as cal
    from ..ai.calls import Router
    from ..ai.jobs import get_job
    from ..ai.prompts import load_prompt
    from ..intake.binding import AI, JOB
    from .eval import K_FOLDS, _heldout, auto_accept, by_question

    sets = sets or list(SCENARIOS)
    unknown = [s for s in sets if s not in SCENARIOS]
    if unknown:
        raise ValueError(f"unknown binding scenarios {unknown}; known: {list(SCENARIOS)}")
    out = {"job": JOB, "sets": sets, "k_folds": K_FOLDS, "min_n": cal.MIN_N, "band_n": cal.BAND_N,
           "tolerance": cal.TOLERANCE, "budget_usd_per_1000": budget, "prompt": load_prompt(JOB).ref,
           "calibration_before": cal.load(JOB).ref or "none", "rows": [], "skipped": []}
    threshold = auto_accept()
    runs: dict[str, dict] = {}  # label -> {scenario: (got, items, summary)}
    for s in sets:
        got = pairs(run(s, log=lambda m: None)["facts"])
        runs.setdefault("rules", {})[s] = (got, items(s, got), {})
    models_ = models or [*get_job(JOB).chain, *get_job(JOB).contender]
    router = router or Router()
    if not router.ready:
        out["skipped"] = [{"model": m, "why": router.why_not_ready() or "model calls are off"} for m in models_]
        log(f"{JOB}: model rows skipped ({out['skipped'][0]['why']})")
        models_ = []
    elif store is None:
        from ..db.store import Store
        store = Store(ROOT / "data/kg.sqlite")
    for m in models_:
        cache: dict = {}  # one model's answers, shared by the scenarios that ask the same question
        per, skipped = {}, None
        for s in sets:
            ai = AI(project=f"eval:{JOB}", router=router, store=store, model=m, cache=cache)
            got = pairs(run(s, ai=ai, log=log)["facts"])
            summ = ai.summary
            if summ.get("questions") and summ.get("not_enabled", 0) == summ["questions"]:
                skipped = f"{m}: not enabled on this GCP project"
                break
            per[s] = (got, items(s, got), summ)
            log(f"   {m} on {s}: {summ.get('questions', 0)} questions, {summ.get('model_bound', 0)} bound, "
                f"{summ.get('none', 0)} none, {summ.get('error', 0)} failed, ${summ.get('paid_usd', 0.0):.3f}")
        if skipped:
            out["skipped"].append({"model": m, "why": skipped})
            log(f"{JOB}: {skipped}")
            continue
        runs[m] = per

    # Calibration items: the rules' bindings once, and each model's answers (one per question).
    rule_items = [i for _, its, _ in runs["rules"].values() for i in its]
    model_q = {m: by_question([i for _, its, _ in per.values() for i in its if i["model"]])
               for m, per in runs.items() if m != "rules"}
    fit_items = rule_items + [q for qs in model_q.values() for q in qs]
    held = _heldout(JOB, fit_items) if fit_items else []
    rule_conf = {(i["set"], i["id"]): c for i, c in zip(fit_items, held) if not i["model"]}
    answer_conf = {(i["model"], i["group"]): c for i, c in zip(fit_items, held) if i["model"]}

    def conf_of(i):
        return answer_conf.get((i["model"], i["group"]), 0.0) if i["model"] else rule_conf.get((i["set"], i["id"]), 0.0)

    rules_rows = {}
    for label, per in runs.items():
        rows = []
        for s, (got, its, summ) in per.items():
            conf = {i["id"]: conf_of(i) for i in its}
            row = score(s, got, conf, threshold) | {"label": f"{s} · {label if label == 'rules' else label + ' + rules'}",
                                                     "kind": "rules" if label == "rules" else "model+rules",
                                                     "set": s, "model": None if label == "rules" else label}
            if label != "rules":
                row["cost"] = {k: summ.get(k) for k in ("questions", "asked", "logged", "cached", "calls",
                                                         "model_bound", "none", "error", "paid_usd")}
                row["usd_per_1000"] = round(1000 * (summ.get("paid_usd") or 0.0) / max(1, row["points"]), 4)
                row["rules_f1"] = rules_rows[s]["f1"]
            else:
                rules_rows[s] = row
            rows.append(row)
        out["rows"] += rows
        var = [r for r in rows if r["set"] in VARIATIONS]
        if not var:
            continue
        pooled = _pooled(var) | {"label": f"variations · {label if label == 'rules' else label + ' + rules'}",
                                 "kind": "pooled", "model": None if label == "rules" else label}
        all_items = [i for s, (_, its, _) in per.items() for i in its]
        pooled["calibrated_by_point"] = cal.band_table([conf_of(i) for i in all_items], [i["ok"] for i in all_items])
        pooled["raw_by_point"] = cal.band_table([i["raw"] for i in all_items], [i["ok"] for i in all_items])
        if label == "rules":
            out["rules_pooled"] = pooled
        else:
            qs = model_q[label]
            pooled["model_answers"] = len(qs)
            pooled["raw"] = cal.band_table([q["raw"] for q in qs], [q["ok"] for q in qs])
            pooled["calibrated"] = cal.band_table([answer_conf[(label, q["group"])] for q in qs], [q["ok"] for q in qs])
            pooled["raw_worst_gap"], pooled["calibrated_worst_gap"] = (cal.worst_gap(pooled["raw"]),
                                                                       cal.worst_gap(pooled["calibrated"]))
            pooled["calibrated_by_point_worst_gap"] = cal.worst_gap(pooled["calibrated_by_point"])
            points = sum(r["points"] for r in var)
            pooled["usd_per_1000"] = round(1000 * sum(r["cost"]["paid_usd"] or 0.0 for r in var) / max(1, points), 4)
            pooled["rules_f1"] = out["rules_pooled"]["f1"]
            pooled["verdict"] = cal.verdict(metric=pooled["f1"], rules_metric=out["rules_pooled"]["f1"],
                                            table=pooled["calibrated"], usd_per_1000=pooled["usd_per_1000"],
                                            budget=budget)
        out["rows"].append(pooled)
    out["rules_calibrated_worst_gap"] = cal.worst_gap(cal.band_table([rule_conf[(i["set"], i["id"])] for i in rule_items],
                                                                     [i["ok"] for i in rule_items]))
    if fit:
        if not fit_items:
            log(f"{JOB}: nothing to fit; the stored calibration is unchanged")
        else:
            c = cal.fit(JOB, fit_items)
            p = cal.save(c, {"sets": sets, "n": len(fit_items), "k_folds": K_FOLDS, "min_n": cal.MIN_N,
                             "strata": sorted(k for k in c.curves if k != "*"),
                             "heldout_worst_gap": {r["label"]: r.get("calibrated_worst_gap") for r in out["rows"]
                                                   if r["kind"] == "pooled" and r.get("model")}})
            out["calibration_after"] = c.ref
            log(f"{JOB}: calibration {c.ref} written to {p.relative_to(ROOT)}")
    return out


def print_report(r: dict, out=print) -> None:
    from .. import calibration as cal

    def f(v, unit=""):
        return "-" if v is None else f"{v}{unit}"

    out(f"\n=== {r['job']} · scenarios {', '.join(r['sets'])} · prompt {r['prompt']} · calibration "
        f"{r.get('calibration_after') or r['calibration_before']}")
    for s in r["skipped"]:
        out(f"  skipped {s['model']}: {s['why']}")
    out(f"\n  {'scenario':24} {'run':18} {'P %':>6} {'R %':>6} {'F1':>6} {'bound':>6} {'wrong':>6} {'missed':>6} "
        f"{'auto %':>7} {'auto wrong':>10} {'$/1000':>8}")
    for row in r["rows"]:
        if row["kind"] == "pooled":
            continue
        a = row.get("auto", {})
        out(f"  {row['set']:24} {row['label'].split(' · ', 1)[1]:18} {f(row['precision_pct']):>6} "
            f"{f(row['recall_pct']):>6} {row['f1']:>6} {row['bound']:>6} {row['wrong']:>6} {row['missed']:>6} "
            f"{f(a.get('pct')):>7} {a.get('wrong', '-'):>10} {f(row.get('usd_per_1000')):>8}")
    if r.get("rules_calibrated_worst_gap") is not None:
        out(f"\n  rules' bindings, calibrated per rule (held out): worst gap {r['rules_calibrated_worst_gap']} pts")
    for row in r["rows"]:
        if row["kind"] != "pooled":
            continue
        out(f"\n  {row['label']}: precision {f(row['precision_pct'], '%')}, recall {f(row['recall_pct'], '%')}, "
            f"F1 {row['f1']}" + (f" (rules alone {row['rules_f1']}), ${row['usd_per_1000']} per 1,000 points"
                                 if row.get("model") else ""))
        if not row.get("model"):
            continue
        out(f"    calibration of the model's {row['model_answers']} answers   {'band':9}{'raw: n':>8} {'conf':>6} "
            f"{'right':>6}   {'held-out: n':>12} {'conf':>6} {'right':>6}")
        for a, b in zip(row["raw"], row["calibrated"]):
            if a["n"] or b["n"]:
                out(f"{'':40}{a['band']:9}{a['n']:>8} {f(a['mean_conf_pct']):>6} {f(a['accuracy_pct']):>6}   "
                    f"{b['n']:>12} {f(b['mean_conf_pct']):>6} {f(b['accuracy_pct']):>6}")
        out(f"    worst gap (bands of {cal.BAND_N}+): raw {f(row['raw_worst_gap'])} pts, calibrated "
            f"{f(row['calibrated_worst_gap'])} pts; every binding, per point, calibrated "
            f"{f(row['calibrated_by_point_worst_gap'])} pts (target ≤ {cal.TOLERANCE:g})")
        out(f"    verdict         {row['verdict']['says']}")
