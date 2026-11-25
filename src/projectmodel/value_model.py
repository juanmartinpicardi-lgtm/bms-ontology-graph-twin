"""Value specs for the 3D equipment view (spec-equipment-3d §6).

`describe(cls, role, part, deck, template)` says how a point is simulated: its kind, unit, typical value and range, and
the *driver*: which signal of the equipment's simulated state it follows (sim.js computes the signals).

- The unit is inferred from the point's class, never read from the source: blind exports carry no units and the
  answer key's would leak. Every spec says so (`unit_source: "inferred"`).
- The behaviour comes from the slot role first (a `Valve_Command` in the cooling-valve slot follows the cooling
  load), then from the class family for points with no slot.
- Anything unknown is a slow random walk labelled "generic".
"""

from __future__ import annotations

TEMP, PCT, INWC, CFM, GPM, PSI = "°F", "%", "inH₂O", "cfm", "gpm", "psi"
RUN, ON, OCC, FILTER = ["OFF", "RUN"], ["OFF", "ON"], ["UNOCC", "OCC"], ["CLEAN", "DIRTY"]
VALVE, ALARM, MODE = ["CLOSED", "OPEN"], ["NORMAL", "ALARM"], ["HEAT", "COOL"]


def _spec(kind: str, unit: str | None, base: float, rng: tuple[float, float], driver: str, **extra) -> dict:
    return {"kind": kind, "unit": unit, "base": base, "range": list(rng), "driver": driver, **extra}


def _binary(states: list[str], driver: str, **extra) -> dict:
    return {"kind": "binary", "unit": None, "base": 1, "range": [0, 1], "states": states, "driver": driver, **extra}


# slot role -> spec. The fan a point belongs to (supply / return) comes from the role, or from its part for VFD
# points that sit on a fan's sub-equipment.
ROLES: dict[str, dict] = {
    "supply_temp": _spec("analog", TEMP, 55, (50, 65), "supply_temp"),
    "return_temp": _spec("analog", TEMP, 72, (65, 80), "return_temp"),
    "mixed_temp": _spec("analog", TEMP, 63, (45, 80), "mixed_temp"),
    "outside_temp": _spec("analog", TEMP, 70, (30, 105), "outdoor_temp"),
    "zone_temp": _spec("analog", TEMP, 72, (65, 82), "zone_temp"),
    "discharge_temp": _spec("analog", TEMP, 56, (50, 95), "discharge_temp"),
    "static_pressure": _spec("analog", INWC, 1.5, (0, 2.5), "static_pressure"),
    "building_pressure": _spec("analog", INWC, 0.03, (-0.1, 0.1), "building_pressure"),
    "filter_dp": _spec("analog", INWC, 0.6, (0.1, 1.5), "filter_dp"),
    "return_humidity": _spec("analog", "%RH", 45, (20, 70), "humidity"),
    "cooling_valve": _spec("command", PCT, 40, (0, 100), "cooling_valve"),
    "heating_valve": _spec("command", PCT, 0, (0, 100), "heating_valve"),
    "reheat_valve": _spec("command", PCT, 0, (0, 100), "reheat_valve"),
    "economizer_damper": _spec("command", PCT, 30, (0, 100), "oa_damper"),
    "relief_damper": _spec("command", PCT, 20, (0, 100), "relief_damper"),
    "damper": _spec("command", PCT, 50, (0, 100), "vav_damper"),
    "supply_fan_speed": _spec("command", PCT, 70, (0, 100), "fan_speed", fan="supply"),
    "return_fan_speed": _spec("command", PCT, 60, (0, 100), "fan_speed", fan="return"),
    "supply_fan_cmd": _binary(ON, "fan_run", fan="supply"),
    "return_fan_cmd": _binary(ON, "fan_run", fan="return"),
    "supply_fan_status": _binary(RUN, "fan_run", fan="supply"),
    "return_fan_status": _binary(RUN, "fan_run", fan="return"),
    "fan_cmd": _binary(RUN, "fan_run", fan="terminal"),
    "vfd_frequency": _spec("analog", "Hz", 42, (0, 60), "fan_freq", fan="supply"),
    "vfd_power": _spec("analog", "kW", 8, (0, 20), "fan_power", fan="supply"),
    "airflow": _spec("analog", CFM, 700, (0, 1500), "airflow"),
    "airflow_sp": _spec("setpoint", CFM, 700, (0, 1500), "airflow_sp"),
    "oa_flow": _spec("analog", CFM, 3000, (0, 12000), "oa_flow"),
    "occupancy": _binary(OCC, "occupancy"),
    "filter_status": _binary(FILTER, "filter_status"),
    # FCU
    "fan_status": _binary(RUN, "fan_run", fan="terminal"),
    # plant: chiller, boiler, pump. A plant's status/enable/power follow that unit's own run state (lead/lag).
    "chw_leaving_temp": _spec("analog", TEMP, 44, (38, 60), "chw_supply"),
    "chw_entering_temp": _spec("analog", TEMP, 54, (40, 65), "chw_return"),
    "chw_leaving_sp": _spec("setpoint", TEMP, 44, (40, 50), "constant"),
    "cw_entering_temp": _spec("analog", TEMP, 80, (60, 95), "cw_supply"),
    "cw_leaving_temp": _spec("analog", TEMP, 90, (60, 105), "cw_return"),
    "chw_flow": _spec("analog", GPM, 900, (0, 1500), "chw_flow"),
    "cw_flow": _spec("analog", GPM, 1100, (0, 1800), "cw_flow"),
    "hw_leaving_temp": _spec("analog", TEMP, 160, (100, 190), "hw_supply"),
    "hw_entering_temp": _spec("analog", TEMP, 140, (90, 180), "hw_return"),
    "hw_leaving_sp": _spec("setpoint", TEMP, 160, (120, 180), "constant"),
    "firing_rate": _spec("command", PCT, 40, (0, 100), "firing_rate"),
    "enable": _binary(ON, "unit_run"),
    "status": _binary(RUN, "unit_run"),
    "cmd": _binary(ON, "unit_run"),
    "power": _spec("analog", "kW", 150, (0, 400), "unit_power"),
    "speed": _spec("command", PCT, 75, (0, 100), "pump_speed"),
    "dp": _spec("analog", PSI, 12, (0, 25), "pump_dp"),
    "dp_sp": _spec("setpoint", PSI, 12, (5, 20), "constant"),
    "evap_iso_valve": _binary(VALVE, "unit_run"),
    "cond_iso_valve": _binary(VALVE, "unit_run"),
    "iso_valve": _binary(VALVE, "unit_run"),
    # W9: RVAV, RTU, unit heater, split system, cooling tower, heat exchanger, meter
    "reheat_cmd": _spec("command", PCT, 0, (0, 100), "reheat_valve"),
    "reheat_enable": _binary(ON, "reheat_on"),
    "setpoint_adjust": _spec("analog", TEMP, 0, (-3, 3), "constant"),
    "cooling_stage": _binary(ON, "dx_stage"),
    "heating_stage": _spec("command", PCT, 0, (0, 100), "heating_valve"),
    "zone_sp": _spec("setpoint", TEMP, 72, (65, 78), "constant"),
    "alarm": _binary(ALARM, "alarm"),
    "fault": _binary(ALARM, "alarm"),
    "heat_cmd": _spec("command", PCT, 0, (0, 100), "uh_heat"),
    "heat_enable": _binary(ON, "uh_run"),
    "heating_sp": _spec("setpoint", TEMP, 60, (50, 70), "constant"),
    "mode": _binary(MODE, "split_mode"),
    "fan_speed": _spec("command", PCT, 70, (0, 100), "tower_fan"),
    "fan_freq": _spec("analog", "Hz", 42, (0, 60), "tower_freq"),
    "cw_sp": _spec("setpoint", TEMP, 80, (70, 85), "constant"),
    "control_valve": _spec("command", PCT, 40, (0, 100), "firing_rate"),
    "hw_flow": _spec("analog", GPM, 120, (0, 300), "hw_flow"),
    "energy": _spec("analog", "kWh", 125000, (0, 1e9), "meter_energy"),
    "cost": _spec("analog", "$", 1800, (0, 1e6), "constant"),
}

# A role whose meaning depends on the equipment type: a pump's `speed` follows the plant, an exhaust fan's its fan.
TEMPLATE_ROLES: dict[tuple[str, str], dict] = {
    ("exhaust_fan", "status"): _binary(RUN, "fan_run", fan="exhaust"),
    ("exhaust_fan", "cmd"): _binary(ON, "fan_run", fan="exhaust"),
    ("exhaust_fan", "speed"): _spec("command", PCT, 100, (0, 100), "fan_speed", fan="exhaust"),
    ("exhaust_fan", "frequency"): _spec("analog", "Hz", 60, (0, 60), "fan_freq", fan="exhaust"),
    ("exhaust_fan", "power"): _spec("analog", "kW", 2, (0, 5), "fan_power", fan="exhaust"),
    ("exhaust_fan", "flow"): _spec("analog", CFM, 1200, (0, 4000), "ef_flow"),
    ("exhaust_fan", "static_pressure"): _spec("analog", INWC, -0.4, (-1.5, 0), "generic"),
    ("exhaust_fan", "damper"): _binary(VALVE, "fan_run", fan="exhaust"),
    ("unit_heater", "zone_temp"): _spec("analog", TEMP, 62, (45, 75), "uh_zone"),
    ("unit_heater", "fan_cmd"): _binary(ON, "uh_run"),
    ("unit_heater", "fan_status"): _binary(RUN, "uh_run"),
    ("unit_heater", "heating_valve"): _spec("command", PCT, 0, (0, 100), "uh_heat"),
    ("unit_heater", "discharge_temp"): _spec("analog", TEMP, 95, (55, 120), "uh_discharge"),
    ("split_system", "status"): _binary(RUN, "unit_run"),
    ("split_system", "enable"): _binary(ON, "unit_run"),
    ("split_system", "fan_speed"): _spec("command", PCT, 60, (0, 100), "fan_speed", fan="terminal"),
    ("rtu", "zone_temp"): _spec("analog", TEMP, 72, (65, 82), "zone_temp"),
    ("cooling_tower", "cmd"): _binary(ON, "unit_run"),
    ("cooling_tower", "status"): _binary(RUN, "unit_run"),
    ("cooling_tower", "power"): _spec("analog", "kW", 15, (0, 40), "unit_power"),
    ("cooling_tower", "cw_leaving_temp"): _spec("analog", TEMP, 80, (60, 95), "cw_supply"),
    ("cooling_tower", "cw_entering_temp"): _spec("analog", TEMP, 90, (60, 105), "cw_return"),
    ("heat_exchanger", "hw_leaving_temp"): _spec("analog", TEMP, 140, (100, 180), "hw_supply"),
    ("heat_exchanger", "hw_entering_temp"): _spec("analog", TEMP, 120, (90, 170), "hw_return"),
    ("meter", "power"): _spec("analog", "kW", 180, (0, 600), "meter_power"),
    ("meter", "flow"): _spec("analog", GPM, 40, (0, 300), "generic"),
}

# Typical setpoints (°F unless said), by the words of the class.
SETPOINTS = [
    (("Unoccupied", "Cooling"), 82), (("Unoccupied", "Heating"), 62),
    (("Cooling", "Zone"), 74), (("Heating", "Zone"), 70),
    (("Supply_Air_Temperature",), 55), (("Discharge_Air_Temperature",), 55),
    (("Temperature",), 72),
]


def setpoint(cls: str) -> dict:
    if "Pressure" in cls:
        return _spec("setpoint", INWC, 1.5, (0, 2.5), "constant")
    if "Flow" in cls:
        return _spec("setpoint", CFM, 800, (0, 1500), "constant")
    if "Humidity" in cls:
        return _spec("setpoint", "%RH", 50, (30, 60), "constant")
    if "Temperature" in cls:
        base = next(v for words, v in SETPOINTS if all(w in cls for w in words))
        return _spec("setpoint", TEMP, base, (base - 10, base + 10), "constant")
    return _spec("setpoint", None, 50, (0, 100), "constant", generic=True)


def by_class(cls: str) -> dict:
    """Spec for a point with no slot: its class family, with a neutral random walk."""
    if cls.endswith("_Setpoint"):
        return setpoint(cls)
    if cls.endswith("Status") and "Fan" in cls or cls in ("Run_Status", "On_Off_Status"):
        return _binary(RUN, "fan_run", fan="exhaust")
    if cls in ("Start_Stop_Command", "Run_Enable_Command", "Fan_Command"):
        return _binary(ON, "fan_run", fan="exhaust")
    if "Occupancy" in cls:
        return _binary(OCC, "occupancy")
    for word, unit, base, rng in [("Temperature", TEMP, 70, (60, 80)), ("Humidity", "%RH", 45, (30, 60)),
                                  ("Pressure", INWC, 0.5, (0, 1.5)), ("Flow", CFM, 800, (0, 2000)),
                                  ("Frequency", "Hz", 40, (0, 60)), ("Power", "kW", 5, (0, 20)),
                                  ("Speed_Sensor", "rpm", 1200, (0, 1800))]:
        if word in cls:
            return _spec("analog", unit, base, rng, "generic")
    if "Valve" in cls or "Damper" in cls or "Speed_Command" in cls:
        return _spec("command", PCT, 50, (0, 100), "generic")
    return _spec("analog", None, 50, (0, 100), "generic", generic=True)


def describe(cls: str | None, role: str | None, part: str | None = None, deck: str | None = None,
             template: str | None = None) -> dict:
    """How to simulate one point (see the module docstring)."""
    cls = cls or ""
    if (template, role) in TEMPLATE_ROLES:
        spec = dict(TEMPLATE_ROLES[(template, role)])
    elif role in ROLES:
        spec = dict(ROLES[role])
        if "fan" in spec and part and part.split(".")[0] in ("supply_fan", "return_fan"):
            spec["fan"] = part.split(".")[0].removesuffix("_fan")  # VFD points on the return fan's sub-equipment
        if role == "speed" and "Frequency" in cls:  # a pump VFD's output frequency
            spec.update(kind="analog", unit="Hz", base=45, range=[0, 60], driver="pump_freq")
    elif role and cls.endswith("_Setpoint"):
        spec = setpoint(cls)
    else:
        spec = by_class(cls)
    if deck:
        spec["deck"] = deck
    spec["unit_source"] = "inferred"
    spec["from_class"] = cls or None
    return spec


DECIMALS = {TEMP: 1, INWC: 2, "Hz": 1, "kW": 1, PSI: 1, "kWh": 0, "$": 0}


def sample(spec: dict, key: str = "") -> dict:
    """One simulated reading for a static graphic (the 2D schematics): the spec's typical value, nudged by a hash of
    `key` (the point id) within 3 % of its range, so a graphic looks the same every time. {"value", "text", "state"}.
    The 3D page runs the full simulator (sim.js); this is its still frame, and is labelled simulated the same way."""
    import zlib

    if spec.get("kind") == "binary":
        on = 0 if spec.get("driver") in ("alarm", "filter_status") else 1
        text = spec["states"][on]
        return {"value": on, "text": text,
                "state": "ok" if text in ("RUN", "ON", "OCC", "OPEN", "COOL", "HEAT") else "warn" if text in ("ALARM", "DIRTY") else "off"}
    lo, hi = spec.get("range") or [0, 100]
    u = (zlib.crc32(key.encode()) % 1000) / 1000 - 0.5
    x = spec.get("base", 0) + (0 if spec.get("kind") == "setpoint" else u * 0.06 * (hi - lo))
    unit = spec.get("unit")
    d = DECIMALS.get(unit, 0 if unit else 1)
    return {"value": x, "text": f"{x:,.{d}f} {unit}" if unit else f"{x:.{d}f}", "state": None}
