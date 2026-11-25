"""2D equipment schematics, one per template, in the style integrators deliver: an AHU section left to right, a VAV
box with its inlet and discharge, a fan in its duct, a pump on its pipe. Each layout draws the parts the variant says
(the same `variant` the 3D viewer gets) and registers every part by its anchors.yaml name.

    LAYOUTS[template_id](sheet, variant) -> (width, height) of the equipment area

Coordinates: the area's top left is (0, 0); air and water run left to right where they can.
"""

from __future__ import annotations

from . import symbols as S
from .symbols import Sheet

W = 900  # equipment area width; heights vary per type


def ahu(sh: Sheet, v: dict) -> tuple[int, int]:
    y, top = 170, 60  # supply level; return duct level
    if v.get("mixing_box", True):
        S.duct(sh, "outside_air_inlet", [(10, y), (120, y)], "outside")
        S.casing(sh, "mixing_box", 110, y - 45, 90, 90)
        S.damper(sh, "mixing_box.oa_damper", 122, y)
        S.damper(sh, "mixing_box.ra_damper", 160, y - 45, vertical=False)
        S.duct(sh, "return_duct", [(720, top), (160, top), (160, y - 55)], "return")
        if v.get("relief_outlet"):
            S.duct(sh, None, [(160, top), (60, top)], "return", arrows=True)
            S.damper(sh, "relief_outlet.damper", 80, top)
            S.block(sh, "relief_outlet", 30, top - 14, 20, 28, fill="bg")
            S.caption(sh, 40, top - 22, "Relief")
        S.caption(sh, 40, y - 22, "Outside air")
        x = 210
    else:
        S.duct(sh, "outside_air_inlet", [(10, y), (110, y)], "mixed")
        S.duct(sh, "return_duct", [(720, top), (60, top)], "return")
        x = 120
    S.casing(sh, "casing", x - 10, y - 55, 380, 110)
    S.filt(sh, "pre_filter", x, y - 30, 18, 60)
    S.filt(sh, "bag_filter", x + 26, y - 30, 26, 60)
    x += 64
    if v.get("heating_coil"):
        S.coil(sh, "heating_coil", x, y - 30, 24, 60, "hot_water")
        S.valve(sh, "heating_coil.valve", x + 12, y + 62, medium="hot_water")
        S.pipe(sh, None, [(x + 12, y + 30), (x + 12, y + 53)], "hot_water", arrows=False)
        x += 40
    S.coil(sh, "cooling_coil", x, y - 30, 24, 60, "chilled_water")
    S.valve(sh, "cooling_coil.valve", x + 12, y + 62, medium="chilled_water")
    S.pipe(sh, None, [(x + 12, y + 30), (x + 12, y + 53)], "chilled_water", arrows=False)
    x += 80
    S.fan(sh, "supply_fan", x, y, 26)
    S.device(sh, "supply_fan.vfd", x - 20, y + 64, "VFD")
    sh.d.line(x, y + 26, x, y + 64, stroke="muted", width=1, dash="3 3")
    S.duct(sh, "supply_duct", [(x + 30, y), (W - 20, y)], "supply")
    S.caption(sh, W - 60, y + 30, "Supply air")
    if v.get("return_fan"):
        S.fan(sh, "return_fan", 560, top, 18, facing=3.14159)
        S.device(sh, "return_fan.vfd", 590, top + 18, "VFD")
    S.caption(sh, 680, top - 18, "Return air")
    S.block(sh, "building_ref", W - 70, 20, 50, 36, "Bldg")
    S.device(sh, "controller", 330, y + 90, "DDC", 46, 24)
    return W, y + 125


def vav(sh: Sheet, v: dict, electric: bool | None = None) -> tuple[int, int]:
    y = 110
    electric = v.get("electric") if electric is None else electric
    decks = [("", y)] if not v.get("dual_duct") else [("@cold", y - 30), ("@hot", y + 30)]
    for suffix, yy in decks:
        name = "inlet_duct" if suffix in ("", "@cold") else "inlet_duct_2"
        S.duct(sh, name, [(10, yy), (240, yy)], "supply" if suffix != "@hot" else "return")
        S.flow_cross(sh, f"flow_cross{suffix}", 90, yy)
        S.butterfly(sh, f"damper{suffix}", 170, yy)
    if v.get("dual_duct"):
        sh.parts["flow_cross"], sh.parts["damper"] = sh.parts["flow_cross@cold"], sh.parts["damper@cold"]
    x = 250
    w = 130 + (70 if v.get("fan_powered") else 0) + (50 if v.get("reheat") else 0)
    S.casing(sh, "box", x, y - 45, w, 90)
    S.caption(sh, 40, y - 20 - (30 if v.get("dual_duct") else 0), "Primary air")
    cx = x + 20
    if v.get("fan_powered"):
        S.fan(sh, "fan", cx + 35, y, 20, facing=0)
        sh.d.line(cx + 35, y - 45, cx + 35, y - 70, stroke="return", width=2)
        S.caption(sh, cx + 35, y - 74, "Plenum air")
        cx += 70
    if v.get("reheat"):
        rx = x + w - 60
        if electric:
            S.heater(sh, "reheat_coil", rx, y - 30, 24, 60)
            S.device(sh, "reheat_coil.scr", rx - 8, y - 82, "SCR", 40, 22)
            sh.d.line(rx + 12, y - 60, rx + 12, y - 30, stroke="muted", width=1, dash="3 3")
        else:
            S.coil(sh, "reheat_coil", rx, y - 30, 24, 60, "hot_water")
            S.valve(sh, "reheat_coil.valve", rx + 12, y + 72, medium="hot_water")
            S.pipe(sh, None, [(rx + 12, y + 30), (rx + 12, y + 63)], "hot_water", arrows=False)
    x1 = x + w
    S.device(sh, "controller", x1 + 30, y - 82, "DDC", 40, 22)
    S.duct(sh, "discharge_duct", [(x1, y), (x1 + 200, y), (x1 + 200, y + 70)], "supply")
    sh.d.rect(x1 + 180, y + 70, 40, 8, fill="part", stroke="ink", width=1.4, kind="part", ref="diffuser")
    S.wall(sh, x1 + 290, 20, y + 100)
    S.sensor_box(sh, "zone_sensor", x1 + 300, y - 15)
    S.caption(sh, x1 + 313, y + 40, "Zone")
    return max(W, x1 + 340), y + 110


def rvav(sh: Sheet, v: dict) -> tuple[int, int]:
    return vav(sh, {**v, "reheat": True})


def fcu(sh: Sheet, v: dict) -> tuple[int, int]:
    y = 110
    S.louvers(sh, "return_grille", 60, y - 30, 14, 60)
    S.caption(sh, 30, y - 40, "Return air")
    S.casing(sh, "casing", 80, y - 50, 360, 100)
    S.filt(sh, "filter", 95, y - 30)
    S.fan(sh, "fan", 170, y, 22)
    x = 230
    if v.get("cooling_coil", True):
        S.coil(sh, "cooling_coil", x, y - 30, 24, 60, "chilled_water")
        S.valve(sh, "cooling_coil.valve", x + 12, y + 72)
        S.pipe(sh, None, [(x + 12, y + 30), (x + 12, y + 63)], "chilled_water", arrows=False)
        x += 50
    if v.get("heating_coil"):
        S.coil(sh, "heating_coil", x, y - 30, 24, 60, "hot_water")
        S.valve(sh, "heating_coil.valve", x + 12, y + 72, medium="hot_water")
        S.pipe(sh, None, [(x + 12, y + 30), (x + 12, y + 63)], "hot_water", arrows=False)
    S.device(sh, "controller", 360, y - 82, "DDC", 40, 22)
    S.duct(sh, None, [(440, y), (600, y)], "supply")
    S.louvers(sh, "discharge_grille", 600, y - 30, 14, 60)
    S.wall(sh, 700, 20, y + 90)
    S.sensor_box(sh, "zone_sensor", 712, y - 15)
    S.caption(sh, 725, y + 40, "Zone")
    return W, y + 110


def chiller(sh: Sheet, v: dict) -> tuple[int, int]:
    S.casing(sh, "evaporator", 220, 150, 300, 50)
    S.caption(sh, 370, 180, "Evaporator")
    S.compressor(sh, "compressor", 170, 130, 50, 50)
    S.device(sh, "control_panel", 560, 60, "Panel", 60, 40)
    S.pipe(sh, "chw_leaving_pipe", [(520, 165), (W - 20, 165)], "chilled_water")
    S.pipe(sh, "chw_entering_pipe", [(W - 20, 190), (520, 190)], "chilled_water")
    S.valve(sh, "chw_entering_pipe.valve", 760, 190)
    S.caption(sh, W - 60, 155, "CHW supply")
    S.caption(sh, W - 60, 210, "CHW return")
    if v.get("water_cooled"):
        S.casing(sh, "condenser", 220, 60, 300, 50)
        S.caption(sh, 370, 90, "Condenser")
        S.pipe(sh, "cw_leaving_pipe", [(520, 75), (W - 20, 75)], "condenser_water")
        S.pipe(sh, "cw_entering_pipe", [(W - 20, 100), (520, 100)], "condenser_water")
        S.valve(sh, "cw_entering_pipe.valve", 760, 100, medium="condenser_water")
    else:
        S.casing(sh, "condenser", 220, 50, 300, 60)
        for i in range(4):
            S.prop_fan(sh, None, 260 + i * 75, 80, 16)
        S.caption(sh, 370, 40, "Air-cooled condenser")
    sh.d.line(195, 130, 220, 85, stroke="refrigerant", width=2)
    sh.d.line(195, 150, 220, 170, stroke="refrigerant", width=2)
    return W, 230


def boiler(sh: Sheet, v: dict) -> tuple[int, int]:
    S.casing(sh, "casing", 220, 90, 280, 100)
    S.caption(sh, 360, 145, "Boiler")
    S.block(sh, "burner", 160, 115, 60, 50, "Burner")
    S.block(sh, "flue", 440, 20, 30, 70, fill="part")
    S.caption(sh, 455, 14, "Flue")
    S.device(sh, "control_panel", 300, 205, "Panel", 60, 30)
    S.pipe(sh, "hw_leaving_pipe", [(500, 110), (W - 20, 110)], "hot_water")
    S.pipe(sh, "hw_entering_pipe", [(W - 20, 170), (500, 170)], "hot_water")
    S.caption(sh, W - 60, 100, "HW supply")
    S.caption(sh, W - 60, 190, "HW return")
    return W, 250


def pump(sh: Sheet, v: dict) -> tuple[int, int]:
    med = v.get("medium") if v.get("medium") in ("chilled_water", "hot_water", "condenser_water") else "chilled_water"
    y = 120
    S.pipe(sh, "suction_pipe", [(20, y), (330, y)], med)
    S.pump(sh, "volute", 350, y, 22)
    S.block(sh, "motor", 380, y - 18, 70, 36, "M")
    S.pipe(sh, "discharge_pipe", [(350, y - 22), (350, 50), (W - 20, 50)], med)
    S.valve(sh, "discharge_pipe.valve", 620, 50, medium=med)
    if v.get("vfd"):
        S.device(sh, "vfd", 470, y - 12, "VFD", 44, 26)
        sh.d.line(450, y, 470, y, stroke="muted", width=1, dash="3 3")
    else:
        S.device(sh, "vfd", 470, y - 12, "Starter", 50, 26)
    S.caption(sh, 60, y - 12, "Suction")
    S.caption(sh, W - 70, 40, "Discharge")
    return W, 170


def rtu(sh: Sheet, v: dict) -> tuple[int, int]:
    y, roof = 110, 200
    sh.d.line(0, roof, W, roof, stroke="room_line", width=4, kind="context")
    S.caption(sh, 20, roof + 16, "Roof", anchor="start")
    S.block(sh, "outside_air_hood", 40, y - 40, 40, 60, "Hood", fill="bg")
    S.caption(sh, 60, y - 48, "Outside air")
    S.casing(sh, "casing", 80, y - 55, 720, 120)
    S.block(sh, "economizer", 90, y - 45, 80, 100, fill="none")
    S.damper(sh, "economizer.oa_damper", 100, y - 10, 16, 50)
    S.duct(sh, "return_duct", [(140, roof + 60), (140, y + 65)], "return")
    S.caption(sh, 170, roof + 50, "Return air", anchor="start")
    S.filt(sh, "filter", 190, y - 35, 22, 70)
    S.coil(sh, "evaporator_coil", 230, y - 35, 26, 70, "refrigerant")
    S.fan(sh, "supply_fan", 320, y, 26)
    S.device(sh, "supply_fan.vfd", 300, y - 100, "VFD")
    if v.get("heat") == "electric":
        S.heater(sh, "heat_section", 380, y - 35, 26, 70)
    else:
        S.coil(sh, "heat_section", 380, y - 35, 26, 70, "gas")
    S.duct(sh, "supply_duct", [(460, y + 65), (460, roof + 60)], "supply")
    S.caption(sh, 490, roof + 50, "Supply air", anchor="start")
    sh.d.line(560, y - 55, 560, y + 65, stroke="line", width=2)
    S.compressor(sh, "compressor", 620, y + 20)
    S.coil(sh, "condenser_coil", 760, y - 35, 22, 70, "refrigerant")
    S.prop_fan(sh, "condenser_fan", 690, y - 30, 20)
    S.caption(sh, 690, y - 64, "Condensing section")
    S.device(sh, "controller", 480, y - 45, "DDC", 46, 24)
    S.wall(sh, 640, roof + 10, roof + 110)
    S.sensor_box(sh, "zone_sensor", 652, roof + 40)
    S.caption(sh, 665, roof + 85, "Zone")
    return W, roof + 115


def exhaust_fan(sh: Sheet, v: dict) -> tuple[int, int]:
    if v.get("inline"):
        y = 110
        S.duct(sh, "duct", [(20, y), (W - 120, y)], "exhaust")
        S.casing(sh, "housing", 360, y - 45, 140, 90)
        S.fan(sh, "fan", 430, y, 28)
        S.damper(sh, "damper", 620, y)
        S.block(sh, "curb", W - 110, y - 20, 1, 40, fill="none")  # indoors: no curb (kept for the anchor list)
        S.device(sh, "controller", 380, y - 100, "Starter", 56, 26)
        S.device(sh, "fan.vfd", 460, y - 100, "VFD")
        S.caption(sh, 60, y - 22, "Exhaust air")
        S.caption(sh, W - 150, y - 22, "To outside")
        return W, y + 80
    roof = 220
    sh.d.line(0, roof, W, roof, stroke="room_line", width=4, kind="context")
    S.caption(sh, 30, roof + 16, "Roof", anchor="start")
    S.duct(sh, "duct", [(450, roof + 110), (450, 130)], "exhaust", w=34)
    S.damper(sh, "damper", 450, roof + 60, 16, 44, vertical=False)
    S.block(sh, "curb", 405, roof - 40, 90, 40, "Curb", fill="part")
    S.casing(sh, "housing", 390, 50, 120, 120)
    S.fan(sh, "fan", 450, 110, 30, facing=-1.5708)
    sh.d.poly([(450, 50), (450, 10)], stroke="exhaust", width=3, kind="flow")
    S.caption(sh, 450, 8, "Discharge")
    S.device(sh, "controller", 600, roof - 34, "Starter", 56, 26)
    S.device(sh, "fan.vfd", 600, roof - 74, "VFD")
    S.caption(sh, 520, roof + 100, "Exhaust air", anchor="start")
    return W, roof + 120


def unit_heater(sh: Sheet, v: dict) -> tuple[int, int]:
    y = 110
    sh.d.line(0, 20, W, 20, stroke="room_line", width=4, kind="context")
    for x in (330, 470):
        sh.d.line(x, 20, x, y - 45, stroke="muted", width=1.5)
    S.casing(sh, "casing", 300, y - 45, 200, 90)
    S.caption(sh, 230, y - 6, "Room air")
    S.prop_fan(sh, "fan", 340, y, 24)
    if v.get("hot_water"):
        S.coil(sh, "heater", 400, y - 30, 26, 60, "hot_water")
        S.valve(sh, "heater.valve", 413, y - 70, medium="hot_water", vertical=True)
        S.pipe(sh, None, [(413, y - 45), (413, y - 60)], "hot_water", arrows=False)
    else:
        S.heater(sh, "heater", 400, y - 30, 26, 60)
    S.louvers(sh, "louvers", 480, y - 30, 14, 60)
    S.chevrons(sh, [(506, y), (600, y)], "hot_water")
    S.caption(sh, 560, y + 26, "Warm air")
    S.wall(sh, 720, 20, y + 110)
    S.sensor_box(sh, "thermostat", 732, y)
    S.caption(sh, 745, y + 48, "Thermostat")
    S.device(sh, "controller", 732, y - 50, "Disc.", 40, 24)
    return W, y + 120


def split_system(sh: Sheet, v: dict) -> tuple[int, int]:
    y = 90
    S.wall(sh, 560, 20, 230)
    S.caption(sh, 280, 230, "Inside", anchor="middle")
    S.caption(sh, 720, 230, "Outside", anchor="middle")
    S.block(sh, "indoor_unit", 160, y - 30, 200, 50, "Indoor unit", fill="bg")
    S.prop_fan(sh, "indoor_unit.fan", 260, y + 40, 14)
    S.pipe(sh, "refrigerant_lines", [(360, y - 5), (640, y - 5), (640, 150)], "refrigerant", arrows=False)
    S.block(sh, "outdoor_unit", 600, 150, 180, 60, fill="bg")
    S.caption(sh, 690, 145, "Outdoor unit")
    S.compressor(sh, "outdoor_unit.compressor", 640, 180, 34, 28)
    S.prop_fan(sh, None, 730, 180, 20)
    S.device(sh, "gateway", 40, y - 25, "BACnet GW", 70, 26)
    sh.d.line(110, y - 12, 160, y - 12, stroke="muted", width=1, dash="3 3")
    S.sensor_box(sh, "zone_sensor", 200, 170)
    S.caption(sh, 213, 216, "Zone")
    return W, 240


def cooling_tower(sh: Sheet, v: dict) -> tuple[int, int]:
    S.casing(sh, "casing", 300, 70, 220, 170)
    S.block(sh, "fill", 320, 110, 180, 80, fill="part")
    for i in range(8):
        sh.d.line(330 + i * 22, 112, 330 + i * 22, 188, stroke="muted", width=1)
    S.block(sh, "basin", 300, 210, 220, 30, "Basin", fill="bg")
    S.prop_fan(sh, "fan", 410, 45, 24)
    S.device(sh, "fan.vfd", 560, 30, "VFD")
    S.pipe(sh, "cw_entering_pipe", [(W - 20, 95), (520, 95), (330, 95)], "condenser_water")
    S.valve(sh, "cw_entering_pipe.valve", 700, 95, medium="condenser_water")
    S.pipe(sh, "cw_leaving_pipe", [(300, 225), (40, 225)], "condenser_water")
    S.device(sh, "control_panel", 560, 160, "Panel", 60, 30)
    S.caption(sh, W - 80, 85, "CW from chillers")
    S.caption(sh, 90, 215, "CW to chillers")
    return W, 260


def heat_exchanger(sh: Sheet, v: dict) -> tuple[int, int]:
    prim = "steam" if v.get("primary") == "steam" else "hot_water"
    S.casing(sh, "shell", 320, 100, 260, 70)
    S.caption(sh, 450, 140, "Heat exchanger")
    S.pipe(sh, "primary_in_pipe", [(20, 60), (360, 60), (360, 100)], prim)
    S.valve(sh, "primary_in_pipe.valve", 200, 60, medium=prim)
    S.pipe(sh, "primary_out_pipe", [(360, 170), (360, 210), (20, 210)], prim)
    S.pipe(sh, "hw_leaving_pipe", [(540, 100), (540, 60), (W - 20, 60)], "hot_water")
    S.pipe(sh, "hw_entering_pipe", [(W - 20, 210), (540, 210), (540, 170)], "hot_water")
    S.device(sh, "control_panel", 420, 200, "Panel", 60, 30)
    S.caption(sh, 70, 50, "Steam in" if prim == "steam" else "Primary in")
    S.caption(sh, 70, 230, "Condensate" if prim == "steam" else "Primary out")
    S.caption(sh, W - 60, 50, "HW supply")
    S.caption(sh, W - 60, 230, "HW return")
    return W, 250


def meter(sh: Sheet, v: dict) -> tuple[int, int]:
    kind = v.get("kind") or "electric"
    med = {"gas": "gas", "water": "chilled_water", "chilled_water": "chilled_water", "hot_water": "hot_water"}.get(kind, "electric")
    S.pipe(sh, "line", [(20, 120), (W - 20, 120)], med, w=6)
    S.block(sh, "meter_body", 400, 70, 100, 80, fill="bg")
    sh.d.circle(450, 110, 28, fill="none", stroke="ink", width=1.5)
    S.block(sh, "display", 425, 100, 50, 20, fill="card")
    S.caption(sh, 450, 62, {"electric": "Electric meter", "gas": "Gas meter", "water": "Water meter",
                            "chilled_water": "Thermal meter (CHW)", "hot_water": "Thermal meter (HW)"}.get(kind, "Meter"))
    return W, 170


LAYOUTS = {"ahu": ahu, "vav": vav, "rvav": rvav, "fcu": fcu, "chiller": chiller, "boiler": boiler, "pump": pump,
           "rtu": rtu, "exhaust_fan": exhaust_fan, "unit_heater": unit_heater, "split_system": split_system,
           "cooling_tower": cooling_tower, "heat_exchanger": heat_exchanger, "meter": meter}
