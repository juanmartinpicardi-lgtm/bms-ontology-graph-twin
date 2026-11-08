"""Value specs for the 3D equipment view (spec-equipment-3d §6).

`describe(cls, role, part, template)` says how a point is simulated: its kind, unit, typical value and range, and
the *driver*: which signal of the equipment's simulated state it follows (sim.js computes the signals).

- The unit is inferred from the point's class, never read from the source: blind exports carry no units and the
  answer key's would leak. Every spec says so (`unit_source: "inferred"`).
- The behaviour comes from the slot role first (a `Valve_Command` in the cooling-valve slot follows the cooling
  load), then from the class family for points with no slot.
- Anything unknown is a slow random walk labelled "generic".
"""

from __future__ import annotations

TEMP, PCT, INWC, CFM = "°F", "%", "inH₂O", "cfm"
RUN, ON, OCC, FILTER = ["OFF", "RUN"], ["OFF", "ON"], ["UNOCC", "OCC"], ["CLEAN", "DIRTY"]


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


def describe(cls: str | None, role: str | None, part: str | None = None, deck: str | None = None) -> dict:
    """How to simulate one point (see the module docstring)."""
    cls = cls or ""
    if role in ROLES:
        spec = dict(ROLES[role])
        if "fan" in spec and part and part.split(".")[0] in ("supply_fan", "return_fan"):
            spec["fan"] = part.split(".")[0].removesuffix("_fan")  # VFD points on the return fan's sub-equipment
    elif role and cls.endswith("_Setpoint"):
        spec = setpoint(cls)
    else:
        spec = by_class(cls)
    if deck:
        spec["deck"] = deck
    spec["unit_source"] = "inferred"
    spec["from_class"] = cls or None
    return spec
