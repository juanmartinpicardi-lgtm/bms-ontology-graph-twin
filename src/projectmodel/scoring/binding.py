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
    if scenario not in ("missing", "integrator"):
        return set()
    return {ref for ref in key_points() if _hash("submittal", ref) % 100 < DROP_PCT}


SCENARIOS: dict[str, Callable[[list[dict]], list[dict]]] = {
    "baseline": lambda rows: rows,
    "names": names,
    "folders": folders,
    "instances": lambda rows: renumber(rows, rename_devices=True),
    "missing": drop_bms,
    "integrator": lambda rows: drop_bms(renumber(folders(names(rows)), rename_devices=False)),
}
TITLES = {
    "baseline": "Troop D as generated (names line up)",
    "names": "point names re-abbreviated and reordered, terse descriptions",
    "folders": "equipment folders renamed (VAVE-07 -> VAVR_1_07)",
    "instances": "device and object instances renumbered, devices named DEV<instance>",
    "missing": "8% of points missing on each side",
    "integrator": "another integrator: all of the above at once",
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
