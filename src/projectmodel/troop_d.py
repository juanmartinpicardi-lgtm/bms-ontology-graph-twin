"""Troop D test building: a synthetic controls submittal, BMS export and answer key built from the public bid set.

The bid set (data/raw/troop_d/) gives floor plans, equipment schedules and the sequence of operations. What a
real project adds later, the controls contractor's submittal and the BMS database, is not public. This module
writes both, as a controls contractor would, from `data/documents/troop_d/building.yaml`, and writes the answer
key at the same time, so every fact in the two documents is known exactly.

Invented here (not in the bid set): controller models and addresses, the MS/TP network, point names, BACnet
instances, BMS equipment names. Everything else is traced to a sheet of the bid set.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "data/documents/troop_d/building.yaml"
DOC_DIR = ROOT / "data/documents/troop_d"
GT_DIR = ROOT / "data/ground_truth/troop_d"

CONTRACTOR = "Ozark Valley Controls (fictitious)"
NAE = "TROOPD-NAE01"


# ---------------------------------------------------------------- point templates
# (short name, description, IO, units, Brick class, sequence role)
# IO: AI/AO/BI/BO are wired points; AV/BV/MV are software values; "BN" means read over BACnet from the unit's
# own controller (chillers, mini-splits).

VAV_POINTS = [
    ("ZN-T", "Zone Temperature", "AI", "°F", "Zone_Air_Temperature_Sensor", "zone_temp"),
    ("ZN-SP", "Zone Setpoint Adjust (NSB8 warmer/cooler)", "AI", "°F", "Temperature_Adjust_Sensor", "setpoint_adjust"),
    ("DA-T", "Discharge Air Temperature", "AI", "°F", "Discharge_Air_Temperature_Sensor", "discharge_temp"),
    ("SA-F", "Supply Airflow", "AI", "cfm", "Discharge_Air_Flow_Sensor", "airflow"),
    ("DPR-O", "Damper Output", "AO", "%", "Damper_Position_Command", "damper"),
    ("SAFLOW-SP", "Airflow Setpoint", "AV", "cfm", "Discharge_Air_Flow_Setpoint", "airflow_sp"),
    ("OCC-SCHEDULE", "Occupancy Command (from AHU01 schedule)", "BV", "", "Occupancy_Command", "occupancy"),
    ("OCC-CLG-SP", "Occupied Cooling Setpoint", "AV", "°F", "Occupied_Cooling_Zone_Air_Temperature_Setpoint", "occ_cooling_sp"),
    ("OCC-HTG-SP", "Occupied Heating Setpoint", "AV", "°F", "Occupied_Heating_Zone_Air_Temperature_Setpoint", "occ_heating_sp"),
    ("UNOCC-CLG-SP", "Unoccupied Cooling Setpoint", "AV", "°F", "Unoccupied_Cooling_Zone_Air_Temperature_Setpoint", "unocc_cooling_sp"),
    ("UNOCC-HTG-SP", "Unoccupied Heating Setpoint", "AV", "°F", "Unoccupied_Heating_Zone_Air_Temperature_Setpoint", "unocc_heating_sp"),
]
REHEAT_POINTS = [
    ("HTG-E", "Electric Heat Enable", "BO", "", "Heating_Enable_Command", "reheat_enable"),
    ("HTG-O", "Electric Heat Output (SCR)", "AO", "%", "Heating_Command", "reheat"),
]
FAN_BOX_POINTS = [
    ("FAN-C", "Parallel Fan Command", "BO", "", "Fan_Command", "fan_cmd"),
    ("FAN-S", "Parallel Fan Status", "BI", "", "Fan_Status", "fan_status"),
]

AHU_POINTS = (
    [("SF-C", "Supply Fan Wall Start/Stop", "BO", "", "Start_Stop_Command", "supply_fan_cmd"),
     ("SF-O", "Supply Fan Wall Speed (VFD)", "AO", "%", "Fan_Speed_Command", "supply_fan_speed")]
    + [(f"SF{i}-S", f"Supply Fan {i} Status", "BI", "", "Fan_Status", "supply_fan_status") for i in range(1, 10)]
    + [(f"EF{i}-C", f"Exhaust Fan Wall {i} Start/Stop", "BO", "", "Start_Stop_Command", "exhaust_fan_cmd") for i in (1, 2)]
    + [(f"EF{i}-O", f"Exhaust Fan Wall {i} Speed (VFD)", "AO", "%", "Fan_Speed_Command", "exhaust_fan_speed") for i in (1, 2)]
    + [(f"EF{i}-S", f"Exhaust Fan Wall {i} Status", "BI", "", "Fan_Status", "exhaust_fan_status") for i in (1, 2)]
    + [
        ("DA-T", "Supply Air Temperature", "AI", "°F", "Discharge_Air_Temperature_Sensor", "discharge_temp"),
        ("CCLA-T", "Cooling Coil Leaving Air Temperature", "AI", "°F", "Air_Temperature_Sensor", "coil_leaving_temp"),
        ("MA-T", "Mixed Air Temperature", "AI", "°F", "Mixed_Air_Temperature_Sensor", "mixed_temp"),
        ("RA-T", "Return Air Temperature", "AI", "°F", "Return_Air_Temperature_Sensor", "return_temp"),
        ("RA-H", "Return Air Humidity", "AI", "%RH", "Return_Air_Humidity_Sensor", "return_humidity"),
        ("OA-T", "Outdoor Air Temperature", "AI", "°F", "Outside_Air_Temperature_Sensor", "outside_temp"),
        ("OA-H", "Outdoor Air Humidity", "AI", "%RH", "Outside_Air_Humidity_Sensor", "outside_humidity"),
        ("OA-F", "Minimum Outdoor Airflow (flow station)", "AI", "cfm", "Outside_Air_Flow_Sensor", "outside_flow"),
        ("SA-F", "Supply Airflow (flow station)", "AI", "cfm", "Supply_Air_Flow_Sensor", "supply_flow"),
        ("DA-P", "Supply Duct Static Pressure", "AI", "in.wc", "Supply_Air_Static_Pressure_Sensor", "static_pressure"),
        ("BLDG-P", "Building Static Pressure", "AI", "in.wc", "Building_Air_Static_Pressure_Sensor", "building_pressure"),
        ("FLT-DP", "Filter Differential Pressure", "AI", "in.wc", "Filter_Differential_Pressure_Sensor", "filter_dp"),
        ("HUM-H", "Steam Generator Leaving Air Humidity", "AI", "%RH", "Discharge_Air_Humidity_Sensor", "supply_humidity"),
        ("CHWS-T", "Coil Chilled Water Supply Temperature", "AI", "°F", "Entering_Chilled_Water_Temperature_Sensor", "chw_entering_temp"),
        ("CHWR-T", "Coil Chilled Water Return Temperature", "AI", "°F", "Leaving_Chilled_Water_Temperature_Sensor", "chw_leaving_temp"),
        ("LT-A", "Low Temperature Detector (Freezestat)", "BI", "", "Freeze_Status", "freeze"),
        ("HSP-A", "High Static Pressure Switch", "BI", "", "Alarm", "high_static_alarm"),
        ("LSP-A", "Low Static Pressure Switch", "BI", "", "Alarm", "low_static_alarm"),
        ("SMK-A", "Duct Smoke Detector", "BI", "", "Smoke_Detection_Alarm", "smoke"),
        ("LEAK-A", "Drain Pan Water Sensor", "BI", "", "Leak_Alarm", "leak"),
        ("CHWV-O", "Chilled Water 3-Way Valve", "AO", "%", "Valve_Position_Command", "chw_valve"),
        ("PH-E", "Electric Preheat Enable", "BO", "", "Heating_Enable_Command", "preheat_enable"),
        ("PH-O", "Electric Preheat Output", "AO", "%", "Preheat_Command", "preheat"),
        ("HUM-E", "Steam Humidifier Enable", "BO", "", "Enable_Command", "humidifier_enable"),
        ("HUM-O", "Steam Humidifier Output", "AO", "%", "Humidify_Command", "humidifier"),
        ("ECON-O", "Economizer Damper", "AO", "%", "Damper_Position_Command", "economizer_damper"),
        ("MOA-O", "Minimum Outdoor Air Damper", "AO", "%", "Damper_Position_Command", "min_oa_damper"),
        ("RAD-O", "Return Air Damper", "AO", "%", "Damper_Position_Command", "return_damper"),
        ("EAD1-O", "Exhaust Air Damper 1", "AO", "%", "Damper_Position_Command", "exhaust_damper"),
        ("EAD2-O", "Exhaust Air Damper 2", "AO", "%", "Damper_Position_Command", "exhaust_damper"),
        ("OCC-SCHEDULE", "Occupancy Schedule", "BV", "", "Occupancy_Command", "occupancy"),
        ("DA-SP", "Supply Air Temperature Setpoint (53 °F)", "AV", "°F", "Discharge_Air_Temperature_Setpoint", "discharge_temp_sp"),
        ("DAP-SP", "Duct Static Pressure Setpoint (set by TAB)", "AV", "in.wc", "Supply_Air_Static_Pressure_Setpoint", "static_pressure_sp"),
        ("BLDGP-SP", "Building Pressure Setpoint (+0.02 in.wc)", "AV", "in.wc", "Building_Air_Static_Pressure_Setpoint", "building_pressure_sp"),
        ("MA-SP", "Mixed Air Temperature Setpoint (55 °F)", "AV", "°F", "Mixed_Air_Temperature_Setpoint", "mixed_temp_sp"),
        ("HUM-SP", "Supply Humidity Setpoint (45 %RH)", "AV", "%RH", "Discharge_Air_Humidity_Setpoint", "humidity_sp"),
        ("SYS-RESET", "Safety Reset (freezestat, static switches)", "BV", "", "Command", "reset"),
    ]
)

CHILLER_POINTS = [
    ("CH-E", "Chiller Enable", "BO", "", "Enable_Command", "enable"),
    ("ISOV-C", "Chiller Isolation Valve Open/Close", "BO", "", "Valve_Command", "isolation_valve"),
    ("COMM", "BACnet Communication Status", "BN", "", "Communication_Loss_Alarm", "comm"),
    ("MODE", "Operation Mode", "BN", "", "Mode_Status", "mode"),
    ("EEWT", "Entering Evaporator Water Temperature", "BN", "°F", "Entering_Chilled_Water_Temperature_Sensor", "chw_entering_temp"),
    ("LEWT", "Leaving Evaporator Water Temperature", "BN", "°F", "Leaving_Chilled_Water_Temperature_Sensor", "chw_leaving_temp"),
    ("AMB-T", "Ambient Temperature", "BN", "°F", "Outside_Air_Temperature_Sensor", "outside_temp"),
    ("EVAP-FS", "Evaporator Flow Switch", "BN", "", "Status", "flow_switch"),
    ("SUCT-T", "Suction Temperature", "BN", "°F", "Temperature_Sensor", "suction_temp"),
    ("COND-P", "Condensing Pressure", "BN", "psig", "Pressure_Sensor", "condensing_pressure"),
    ("EVAP-P", "Evaporating Pressure", "BN", "psig", "Pressure_Sensor", "evaporating_pressure"),
    ("LCHWT-SP", "Leaving Chilled Water Setpoint (42 °F)", "BN", "°F", "Leaving_Chilled_Water_Temperature_Setpoint", "chw_leaving_sp"),
]
PLANT_POINTS = [
    ("CWS-T", "Chilled Water Supply Temperature", "AI", "°F", "Leaving_Chilled_Water_Temperature_Sensor", "supply_temp"),
    ("CWR-T", "Chilled Water Return Temperature", "AI", "°F", "Entering_Chilled_Water_Temperature_Sensor", "return_temp"),
    ("CW-F", "Chilled Water Flow", "AI", "gpm", "Chilled_Water_Flow_Sensor", "flow"),
    ("CH-LEAD", "Lead Chiller Select (rotates weekly)", "MV", "", "Lead_Lag_Command", "chiller_lead"),
    ("CWP-LEAD", "Duty Pump Select (rotates weekly)", "MV", "", "Lead_Lag_Command", "pump_lead"),
    ("LAG-ON-SP", "Lag Chiller Enable Flow (140 gpm)", "AV", "gpm", "Setpoint", "lag_on_flow"),
    ("LAG-OFF-SP", "Lag Chiller Disable Flow (130 gpm)", "AV", "gpm", "Setpoint", "lag_off_flow"),
]
PUMP_POINTS = [
    ("C", "Pump Start/Stop", "BO", "", "Start_Stop_Command", "cmd"),
    ("S", "Pump Status", "BI", "", "Run_Status", "status"),
    ("O", "Pump Speed (VFD)", "AO", "%", "Speed_Command", "speed"),
    ("A", "VFD Fault", "BI", "", "Fault_Status", "fault"),
]
LAB_EF_POINTS = [
    ("C", "Exhaust Fan Enable", "BO", "", "Start_Stop_Command", "cmd"),
    ("S", "Exhaust Fan Status", "BI", "", "Fan_Status", "status"),
    ("SPD", "Exhaust Fan Speed", "BO", "", "Fan_Speed_Command", "speed"),
    ("P", "Exhaust Duct Static Pressure", "AI", "in.wc", "Exhaust_Air_Static_Pressure_Sensor", "static_pressure"),
    ("F", "Exhaust Airflow", "AI", "cfm", "Exhaust_Air_Flow_Sensor", "airflow"),
    ("BYP-O", "Bypass Damper", "AO", "%", "Damper_Position_Command", "bypass_damper"),
]
SIMPLE_EF_POINTS = [
    ("C", "Exhaust Fan Start/Stop", "BO", "", "Start_Stop_Command", "cmd"),
    ("S", "Exhaust Fan Status", "BI", "", "Fan_Status", "status"),
]
SPLIT_POINTS = [
    ("RUN-S", "Unit Run Status", "BN", "", "Run_Status", "status"),
    ("ZN-T", "Room Temperature", "BN", "°F", "Zone_Air_Temperature_Sensor", "zone_temp"),
    ("MODE", "Operating Mode", "BN", "", "Mode_Status", "mode"),
    ("FLT-A", "Unit Fault", "BN", "", "Fault_Status", "fault"),
]

OBJECT_TYPE = {"AI": "analog-input", "AO": "analog-output", "BI": "binary-input", "BO": "binary-output",
               "AV": "analog-value", "BV": "binary-value", "MV": "multi-state-value", "BN": "analog-value"}


# ---------------------------------------------------------------- model

@dataclass
class Point:
    id: str
    equip_id: str
    short: str
    description: str
    io: str
    units: str
    brick_class: str
    role: str
    bms_name: str = ""
    object_type: str = ""
    instance: int = 0
    terminal: str = ""


@dataclass
class Equip:
    id: str
    tag: str                      # as on the drawings and in the submittal
    bms_name: str                 # as in the Metasys database
    kind: str                     # ahu, vav, vave, fvav, chiller, pump, ef_lab, ef, split, uh, part, system
    brick_class: str
    floor: str = ""
    room: str = ""
    sheet: str = "M-401"
    attrs: dict = field(default_factory=dict)
    controller: str = ""
    trunk: str = ""
    address: int | None = None
    device_instance: int | None = None
    parent: str = ""
    confidence: str = "high"
    note: str = ""
    points: list[Point] = field(default_factory=list)


def bms_name(tag: str) -> str:
    """Metasys names differ from drawing tags, as on real jobs: VAVE07 -> VAVE-07, CH01a -> CH-1A, EF-LAB1 -> EF-LAB-1."""
    import re
    m = re.fullmatch(r"(F?VAVE?|AHU|MS|UH|CWP)(\d+)", tag)
    if m:
        prefix, num = m.groups()
        return f"{prefix}-{int(num)}" if prefix in ("AHU", "MS", "UH", "CWP") else f"{prefix}-{num}"
    m = re.fullmatch(r"CH(\d+)([ab])", tag)
    if m:
        return f"CH-{int(m.group(1))}{m.group(2).upper()}"
    m = re.fullmatch(r"EF-LAB(\d)", tag)
    if m:
        return f"EF-LAB-{m.group(1)}"
    return tag


def load_spec(path: Path = SPEC) -> dict:
    return yaml.safe_load(path.read_text())


def build(spec: dict) -> dict:
    """Turn the building spec into equipment with controllers, points and names. Pure: no files."""
    equips: list[Equip] = []

    def add(e: Equip, templates) -> Equip:
        for short, desc, io, units, cls, role in templates:
            e.points.append(Point(id=f"{e.id}.{short}", equip_id=e.id, short=short, description=desc, io=io,
                                  units=units, brick_class=cls, role=role))
        equips.append(e)
        return e

    a = spec["ahu"][0]
    ahu = add(Equip(id="td-AHU01", tag=a["tag"], bms_name=bms_name(a["tag"]), kind="ahu", brick_class="AHU",
                    floor=a["location"]["floor"], room=a["location"]["room"], sheet=a["sheet"],
                    attrs={k: a[k] for k in ("make", "supply_cfm", "outside_cfm", "exhaust_cfm", "preheat_kw",
                                             "cooling_mbh", "chw_gpm")}), AHU_POINTS)
    for ptag, pcls, pname in [("SF", "Supply_Fan", "Supply fan wall (9 fans, 2 VFDs)"),
                              ("EF", "Exhaust_Fan", "Exhaust fan walls (2 x 2 fans, 2 VFDs)"),
                              ("CHWV", "Chilled_Water_Valve", "Chilled water 3-way valve"),
                              ("HUM", "Humidifier", "Steam generator, Neptronic SKE4"),
                              ("ECON", "Economizer_Damper", "Economizer damper"),
                              ("OAD", "Outside_Damper", "Minimum outdoor air damper"),
                              ("RAD", "Return_Damper", "Return air damper"),
                              ("EAD", "Exhaust_Damper", "Exhaust air dampers (2)")]:
        equips.append(Equip(id=f"td-AHU01-{ptag}", tag=f"AHU01-{ptag}", bms_name="", kind="part",
                            brick_class=pcls, floor=ahu.floor, room=ahu.room, sheet="M-303", parent=ahu.id,
                            attrs={"description": pname}))

    plant = add(Equip(id="td-CHWS", tag="CHW SYSTEM", bms_name="CHW-PLANT", kind="system",
                      brick_class="Chilled_Water_System", floor="L1", room="144", sheet="M-303"), PLANT_POINTS)
    for c in spec["chillers"]:
        add(Equip(id=f"td-{c['tag']}", tag=c["tag"], bms_name=bms_name(c["tag"]), kind="chiller",
                  brick_class="Chiller", floor="L1", room="exterior", sheet=c["sheet"], parent=plant.id,
                  attrs={k: c[k] for k in ("make", "model", "tons", "gpm", "ewt", "lwt")}), CHILLER_POINTS)
    for p in spec["pumps"]:
        add(Equip(id=f"td-{p['tag']}", tag=p["tag"], bms_name=bms_name(p["tag"]), kind="pump",
                  brick_class="Chilled_Water_Pump", floor="L1", room="144", sheet=p["sheet"], parent=plant.id,
                  attrs={k: p[k] for k in ("make", "model", "gpm", "head_ft", "hp", "vfd")}), PUMP_POINTS)

    def boxes(rows, kind, cls, templates):
        for r in rows:
            if kind == "fvav":
                tag, clg, mn, htg, kw, size, fan, floor, room, conf, *note = r
                attrs = {"make": "Krueger", "model": "KQFP", "unit_size": size, "cooling_cfm": clg,
                         "min_cfm": mn, "heating_cfm": htg, "heat_kw": kw, "fan_cfm": fan}
            else:
                tag, clg, mn, htg, kw, inlet, floor, room, conf, *note = r
                attrs = {"make": "Krueger", "model": "LMHS", "inlet_in": inlet, "cooling_cfm": clg, "min_cfm": mn}
                if kw:
                    attrs |= {"heating_cfm": htg, "heat_kw": kw}
            add(Equip(id=f"td-{tag}", tag=tag, bms_name=bms_name(tag), kind=kind, brick_class=cls, floor=floor,
                      room=room, attrs=attrs, confidence=conf, note=note[0] if note else ""), templates)

    boxes(spec["vav"], "vav", "VAV", VAV_POINTS)
    boxes(spec["vave"], "vave", "RVAV", VAV_POINTS + REHEAT_POINTS)
    boxes(spec["fvav"], "fvav", "RVAV", VAV_POINTS + REHEAT_POINTS + FAN_BOX_POINTS)

    for f in spec["exhaust_fans"]:
        tmpl = LAB_EF_POINTS if f["kind"] == "lab" else SIMPLE_EF_POINTS if f["on_bas"] else []
        add(Equip(id=f"td-{f['tag']}", tag=f["tag"], bms_name=bms_name(f["tag"]) if f["on_bas"] else "",
                  kind="ef", brick_class="Exhaust_Fan", floor=f["location"]["floor"], room=f["location"]["room"],
                  sheet="M-104", note=f.get("note", ""), attrs={"control": f["kind"]}), tmpl)
    for s in spec["mini_splits"]:
        add(Equip(id=f"td-{s['tag']}", tag=s["tag"], bms_name=bms_name(s["tag"]), kind="split",
                  brick_class="HVAC_Equipment", floor=s["location"]["floor"], room=s["location"]["room"],
                  attrs={k: s[k] for k in ("make", "outdoor", "indoor", "mbh")},
                  note="ductless mini-split: no Brick class"), SPLIT_POINTS)
    for u in spec["unit_heaters"]:
        equips.append(Equip(id=f"td-{u['tag']}", tag=u["tag"], bms_name="", kind="uh", brick_class="Unit_Heater",
                            floor=u["location"]["floor"], room=u["location"]["room"], attrs={"kw": u["kw"]},
                            note="own thermostat, not on the BAS"))

    _assign_network(equips)
    _name_points(equips)
    return {"spec": spec, "equips": equips}


def _assign_network(equips: list[Equip]) -> None:
    """MS/TP trunks: FC-1 plant and AHU, FC-2/3/4 terminal units per level. Addresses from 4 (0-3 reserved)."""
    controller = {"ahu": "FAC4911 + IOM4711", "system": "FAC2611", "chiller": "York chiller BACnet card",
                  "pump": "IOM2721", "vav": "VMA1930", "vave": "VMA1930", "fvav": "VMA1930",
                  "ef": "IOM2721", "split": "LG PI485 BACnet gateway"}
    trunk_of_floor = {"L1": "FC-2", "L2": "FC-3", "L3": "FC-4"}
    nxt = {"FC-1": 4, "FC-2": 4, "FC-3": 4, "FC-4": 4}
    shared_gateway = None
    for e in equips:
        if e.kind in ("part", "uh") or not e.points:
            continue
        if e.kind == "split":                       # one gateway for the three units
            e.controller, e.trunk = controller["split"], "FC-1"
            if shared_gateway is None:
                shared_gateway = nxt["FC-1"]; nxt["FC-1"] += 1
            e.address = shared_gateway
        else:
            trunk = trunk_of_floor[e.floor] if e.kind in ("vav", "vave", "fvav") else "FC-1"
            e.controller, e.trunk, e.address = controller[e.kind], trunk, nxt[trunk]
            nxt[trunk] += 1
        e.device_instance = 3000 + int(e.trunk[-1]) * 100 + e.address


def _name_points(equips: list[Equip]) -> None:
    """Metasys reference names and BACnet object instances; terminals for wired points."""
    for e in equips:
        counters: dict[str, int] = {}
        ins = {"AI": 0, "AO": 0, "BI": 0, "BO": 0}
        for p in e.points:
            ot = OBJECT_TYPE[p.io]
            counters[ot] = counters.get(ot, 0) + 1
            p.object_type, p.instance = ot, counters[ot]
            name = p.short if e.kind not in ("pump", "ef") else f"{e.bms_name}-{p.short}"
            p.bms_name = f"{NAE}/{e.trunk}.{e.bms_name}.{name}"
            if p.io in ins:
                ins[p.io] += 1
                kind = {"AI": "UI", "AO": "AO", "BI": "BI", "BO": "BO"}[p.io]
                p.terminal = f"{kind}{ins[p.io]}"


# ---------------------------------------------------------------- answer key and BMS export

def write_answer_key(model: dict, out: Path = GT_DIR) -> dict:
    spec, equips = model["spec"], model["equips"]
    out.mkdir(parents=True, exist_ok=True)

    spaces = [{"space_id": "td-site", "kind": "site", "rec_class": "rec:Building", "number": "",
               "name": spec["site"]["name"], "floor": "", "parent": "", "sheet": ""}]
    for f in spec["floors"]:
        spaces.append({"space_id": f"td-{f['id']}", "kind": "floor", "rec_class": "rec:Level", "number": f["id"],
                       "name": f["name"], "floor": f["id"], "parent": "td-site", "sheet": f["sheet"]})
    sheet_of = {f["id"]: f["sheet"] for f in spec["floors"]}
    for floor, rooms in spec["rooms"].items():
        for num, name in rooms.items():
            spaces.append({"space_id": f"td-room-{num}", "kind": "room", "rec_class": "rec:Room", "number": num,
                           "name": name, "floor": floor, "parent": f"td-{floor}", "sheet": sheet_of[floor]})
    spaces.append({"space_id": "td-exterior", "kind": "outdoor", "rec_class": "rec:OutdoorSpace", "number": "",
                   "name": "Chiller yard", "floor": "L1", "parent": "td-site", "sheet": "M-101"})
    spaces.append({"space_id": "td-roof", "kind": "roof", "rec_class": "rec:Space", "number": "", "name": "Roof",
                   "floor": "RF", "parent": "td-RF", "sheet": "M-104"})
    _csv(out / "spaces.csv", spaces)

    def space_of(e: Equip) -> str:
        return {"exterior": "td-exterior", "roof": "td-roof"}.get(e.room, f"td-room-{e.room}")

    _csv(out / "equipment.csv", [{
        "equip_id": e.id, "tag": e.tag, "bms_name": e.bms_name, "kind": e.kind, "brick_class": e.brick_class,
        "parent_equip_id": e.parent, "floor": e.floor, "space_id": space_of(e) if e.room else "",
        "location_confidence": e.confidence, "controller": e.controller, "trunk": e.trunk,
        "mstp_address": e.address if e.address is not None else "", "device_instance": e.device_instance or "",
        "point_count": len(e.points), "source_sheet": e.sheet,
        "attrs": json.dumps(e.attrs, ensure_ascii=False), "note": e.note} for e in equips])

    points = [p for e in equips for p in e.points]
    _csv(out / "points.csv", [{
        "point_id": p.id, "equip_id": p.equip_id, "short_name": p.short, "bms_name": p.bms_name,
        "description": p.description, "io": p.io, "object_type": p.object_type, "instance": p.instance,
        "units": p.units, "brick_class": p.brick_class, "role": p.role} for p in points])

    rels = []
    ahu = next(e for e in equips if e.kind == "ahu")
    plant = next(e for e in equips if e.kind == "system")
    for e in equips:
        if e.kind in ("vav", "vave", "fvav"):
            rels.append({"src": ahu.id, "rel": "feeds", "dst": e.id, "medium": "air", "source": "M-101..M-103 ductwork"})
        if e.parent:
            rels.append({"src": e.parent, "rel": "hasPart", "dst": e.id, "medium": "", "source": e.sheet})
        if e.room and e.kind != "system":
            rels.append({"src": e.id, "rel": "hasLocation", "dst": space_of(e), "medium": "", "source": "floor plans"})
        if e.kind in ("vav", "vave", "fvav"):
            rels.append({"src": e.id, "rel": "feeds", "dst": space_of(e), "medium": "air",
                         "source": f"thermostat on plan ({e.confidence})"})
    for c in (e for e in equips if e.kind == "chiller"):
        for p in (e for e in equips if e.kind == "pump"):
            rels.append({"src": p.id, "rel": "feeds", "dst": c.id, "medium": "chilled_water", "source": "M-301 piping diagram"})
        rels.append({"src": c.id, "rel": "feeds", "dst": ahu.id, "medium": "chilled_water", "source": "M-301 piping diagram"})
    ef_rr = next(e for e in equips if e.tag == "EF-RR")
    rels.append({"src": ef_rr.id, "rel": "requires", "dst": ahu.id, "medium": "", "source": "M-304 EF-RR interlock"})
    _csv(out / "relations.csv", rels)

    issues = [{"id": d["id"], "kind": "design", "text": d["text"]} for d in spec["design_issues"]]
    issues.append({"id": "SY-1", "kind": "naming",
                   "text": "BMS names differ from drawing tags on purpose (VAVE07 -> VAVE-07, CH01a -> CH-1A, "
                           "AHU01 -> AHU-1): the merge step must link them."})
    for e in equips:
        if e.confidence == "medium":
            issues.append({"id": f"LOC-{e.tag}", "kind": "location", "text": f"{e.tag} in room {e.room}: {e.note}"})
    _csv(out / "issues.csv", issues)

    summary = {
        "site": spec["site"]["name"], "generated_by": "src/projectmodel/troop_d.py",
        "equipment": len(equips), "equipment_on_bas": sum(1 for e in equips if e.points),
        "points": len(points), "spaces": len(spaces),
        "by_kind": {k: sum(1 for e in equips if e.kind == k) for k in sorted({e.kind for e in equips})},
        "locations_medium_confidence": sum(1 for e in equips if e.confidence == "medium"),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def write_bms_export(model: dict, path: Path = DOC_DIR / "bms_export.csv") -> int:
    """One row per object, shaped like a Metasys point export: what a site database dump looks like."""
    rows = []
    for e in model["equips"]:
        for p in e.points:
            rows.append({"Item Reference": p.bms_name, "Name": p.bms_name.rsplit(".", 1)[-1],
                         "Description": p.description, "Object Type": p.object_type,
                         "Instance": p.instance, "Units": p.units, "Device": f"{e.bms_name} ({e.controller})",
                         "Device Instance": e.device_instance, "Trunk": e.trunk, "Address": e.address})
    _csv(path, rows)
    return len(rows)


def _csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
