"""Render the Troop D synthetic controls submittal as a PDF, laid out like a real temperature-controls submittal:
title, sheet index, legend, network riser, then per system a point schedule, sequence and bill of materials,
then the room, valve and damper schedules.

The contractor is fictitious. Every sheet says it is a synthetic test document.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from projectmodel.troop_d import (AHU_POINTS, CHILLER_POINTS, CONTRACTOR, DOC_DIR, FAN_BOX_POINTS, LAB_EF_POINTS,
                                  NAE, PLANT_POINTS, PUMP_POINTS, REHEAT_POINTS, SIMPLE_EF_POINTS, SPLIT_POINTS,
                                  VAV_POINTS, Equip)

PAGE = landscape(letter)
ISSUE_DATE = date(2026, 2, 16)        # a plausible submittal date after the Oct 2025 bid; fixed so output is stable
JOB = "OVC-25-0417"

styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=15, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11.5, spaceBefore=6, spaceAfter=4)
BODY = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8.6, leading=11)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.4, leading=9)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=7, leading=8.4)


# ---------------------------------------------------------------- sequences (contractor restatement of M-304)

SEQUENCES = {
    "AHU01": [
        ("General", "AHU01 is controlled by a FAC4911 field controller with an IOM4711 expansion module on trunk "
         "FC-1, reporting to the existing Metasys NAE. The controller runs stand-alone if the NAE is lost."),
        ("Occupancy", "OCC-SCHEDULE follows the Troop D Crime Lab schedule set in Metasys. Per M-304 the unit runs "
         "occupied at all times; the schedule is kept adjustable."),
        ("Supply fan", "When OCC-SCHEDULE is occupied and no safety is tripped, SF-C starts the supply fan wall. "
         "SF-O modulates to hold DA-P at DAP-SP (set by the TAB contractor with all boxes at minimum). The duct "
         "static probe is 2/3 down the medium pressure duct. An alarm is raised if any of SF1-S to SF9-S does not "
         "prove within 30 s of SF-C. The redundant VFD takes over automatically on a VFD fault."),
        ("Building pressure", "MOA-O opens to minimum when occupied and modulates further open to hold BLDG-P at "
         "BLDGP-SP (+0.02 in.wc). If BLDG-P rises above BLDGP-SP, EF1-C and EF2-C enable and EF1-O, EF2-O modulate "
         "the exhaust fan walls, with EAD1-O and EAD2-O open."),
        ("Economizer", "Enabled when OA-T is below 55 °F (adj.) and RA-H is below 60 %RH (adj.). ECON-O modulates "
         "to hold MA-T at or below 60 °F; RAD-O closes and the exhaust fans enable while the economizer is open. "
         "Above 55 °F OA-T, ECON-O closes to minimum and stays disabled until OA-T falls below 55 °F."),
        ("Ventilation", "Occupied: MOA-O at the scheduled minimum (8,500 cfm measured at OA-F) unless the economizer "
         "is active. Disabled or unoccupied: MOA-O and ECON-O closed."),
        ("Electric preheat", "PH-E enables and PH-O modulates when MA-T falls below MA-SP (55 °F); disabled above it."),
        ("Humidification", "HUM-E enables when RA-H falls below 40 %RH; HUM-O modulates to hold HUM-H at HUM-SP "
         "(45 %RH). HUM-E disables when RA-H rises above 45 %RH."),
        ("Cooling", "When MA-T rises above 55 °F, CHWV-O modulates the 3-way valve to hold DA-T at DA-SP (53 °F). "
         "When OA-T is below 40 °F, CHWV-O is closed."),
        ("Safeties", "Manual reset from SYS-RESET. LT-A (freezestat): SF-C and EF1-C/EF2-C off, CHWV-O open and "
         "the duty chilled water pump enabled at 25 %. SMK-A (fire alarm / duct smoke): fans off. HSP-A (discharge "
         "above 3.0 in.wc) or LSP-A (inlet below -2.0 in.wc): fans off. LEAK-A: CHWV-O closed, alarm to Metasys."),
        ("Shutdown", "SF-C, EF1-C, EF2-C off; SF-O, EF1-O, EF2-O at 0 %; MOA-O and ECON-O closed; CHWV-O closed "
         "unless OA-T is below 32 °F, then 25 % open."),
    ],
    "CHW": [
        ("General", "The chilled water plant is controlled by a FAC2611 on trunk FC-1. Chillers CH-1A and CH-1B are "
         "integrated over BACnet MS/TP through their factory controllers."),
        ("Pumps", "CWP-1 and CWP-2 run duty/standby; CWP-LEAD rotates weekly (adj.). The duty pump starts when "
         "AHU01 calls for cooling (CHWV-O open) at the chiller minimum flow, and speeds up as CWR-T rises above 55 °F. "
         "The standby pump starts on a duty pump fault (CWP-x-A) or failure to prove (CWP-x-S). Pumps stop after "
         "CHWV-O has been in full bypass for 10 min (adj.). On AHU01 LT-A, the duty pump runs at 25 %."),
        ("Chillers", "Lead/lag by CH-LEAD, rotated weekly. With the pumps proven, the lead chiller ISOV-C opens and "
         "CH-E enables; it holds LEWT at LCHWT-SP (42 °F). When CW-F rises above LAG-ON-SP (140 gpm) the lag "
         "chiller ISOV-C opens and CH-E enables; both share load to 42 °F. Below LAG-OFF-SP (130 gpm) the lag "
         "chiller disables and its valve closes."),
    ],
    "VAV": [
        ("Applies to", "VAV-01 to VAV-19 (cooling only, no heater). Controller VMA1930 with NSB8 display sensor."),
        ("Modes", "OCC-SCHEDULE from AHU01. Occupied: SAFLOW-SP between minimum and cooling maximum. Unoccupied: "
         "minimum airflow set to zero; OCC-CLG-SP set back to UNOCC-CLG-SP."),
        ("Cooling", "As ZN-T rises above OCC-CLG-SP (adjusted by ZN-SP), SAFLOW-SP rises toward the cooling maximum; "
         "DPR-O modulates to hold SA-F at SAFLOW-SP. When satisfied, back to minimum."),
        ("Heating", "None: these boxes have no heater (see M-401). M-304 describes reheat for this group; not "
         "programmed. Raised as RFI-03."),
        ("Monitoring", "DA-T duct sensor, monitoring only."),
    ],
    "VAVE": [
        ("Applies to", "VAVE-01 to VAVE-19 (electric reheat, SCR). Controller VMA1930 with NSB8 display sensor."),
        ("Cooling", "As for VAV: DPR-O modulates SA-F between minimum and cooling maximum on ZN-T above OCC-CLG-SP."),
        ("Heating", "As ZN-T falls below OCC-HTG-SP, HTG-E enables and HTG-O modulates to hold DA-T at 90 °F "
         "(adj.); SAFLOW-SP goes to the heating airflow. When satisfied, HTG-O to 0 %, HTG-E off, airflow to "
         "minimum. Airflow switch interlock is in the heater, wired by Div. 26."),
    ],
    "FVAV": [
        ("Applies to", "FVAV-01 to FVAV-18 (parallel fan powered, electric heat). Controller VMA1930."),
        ("Cooling", "FAN-C off. DPR-O modulates SA-F between minimum primary and cooling maximum on ZN-T."),
        ("Heating", "As ZN-T falls below OCC-HTG-SP, DPR-O to minimum primary, FAN-C on (proven by FAN-S), "
         "HTG-E on and HTG-O modulates to hold DA-T at 90 °F (adj.). When satisfied: HTG-O 0 %, HTG-E off, "
         "FAN-C off."),
    ],
    "EF": [
        ("EF-LAB-1, EF-LAB-2", "Run continuously. BYP-O modulates the internal bypass damper to hold the exhaust "
         "duct static (EF-LAB-x-P) as fume hoods open and close. The airflow station and static probe replace the "
         "existing devices (field verify)."),
        ("EF-RR", "Interlocked with AHU01: enabled when any of SF1-S to SF9-S proves, disabled otherwise."),
        ("EF-CONT", "Runs continuously; alarm to Metasys if EF-CONT-S is off while commanded on."),
        ("EF-LOCAL", "Local controls, not on the BAS."),
    ],
    "MS": [
        ("MS-1 to MS-3", "LG mini-splits monitored through one LG PI485 BACnet gateway: run status, room "
         "temperature, mode and fault. Control stays on the LG wall controllers (M-401 note 3)."),
    ],
}

BOM = {
    "AHU01": [("1", "FAC4911-0", "Field Advanced Controller, 34 I/O"), ("1", "MS-IOM4711-0", "I/O module, 16 points"),
              ("1", "NSB8 enclosure", "Panel AHU01-CP, in room 144"), ("3", "TE-6311P", "Duct averaging temperature sensor (DA-T, MA-T, CCLA-T)"),
              ("2", "TE-6311M", "Duct temperature sensor (RA-T) / outdoor (OA-T)"),
              ("3", "HE-6800", "Humidity transmitter (RA-H, OA-H, HUM-H)"), ("3", "DPT2650", "Differential pressure transmitter (DA-P, BLDG-P, FLT-DP)"),
              ("2", "Air flow station", "OA-F, SA-F"), ("1", "A70HA", "Low limit, manual reset (LT-A)"),
              ("2", "P32AC", "High / low static pressure switch"), ("1", "Water sensor", "Drain pan (LEAK-A)"),
              ("7", "M9220-GGA", "Damper actuator, proportional (ECON, MOA, RAD, EAD1, EAD2 + 2 spare)"),
              ("1", "VG1841 + M9109", "3-way chilled water valve and actuator (CHWV)"), ("4", "VFD", "Supply 2, exhaust 2 (one redundant each)")],
    "CHW": [("1", "FAC2611-0", "Field Advanced Controller (plant)"), ("2", "IOM2721", "Pump I/O (CWP-1, CWP-2)"),
            ("2", "TE-6300W", "Immersion sensor and well (CWS-T, CWR-T)"), ("1", "Flow meter", "Insertion flow meter (CW-F)"),
            ("2", "VFD", "Pump VFD01, VFD02"), ("2", "M9124", "Chiller isolation valve actuator, on/off")],
    "VAV": [("56", "MS-VMA1930-0", "VAV controller with integral actuator and airflow sensor"),
            ("56", "NS-BCN7004-0 / NSB8", "Network sensor with display and setpoint adjust"),
            ("56", "TE-6311M", "Duct discharge air temperature sensor"),
            ("18", "RIBU1C", "Relay for parallel fan (FVAV)")],
    "EF": [("4", "IOM2721", "Exhaust fan I/O (EF-LAB-1, EF-LAB-2, EF-RR, EF-CONT)"),
           ("2", "DPT2650", "Exhaust duct static (EF-LAB)"), ("2", "Air flow station", "Lab exhaust airflow (replace existing)"),
           ("2", "M9220", "Bypass damper actuator")],
    "MS": [("1", "LG PI485", "BACnet gateway for MS-1, MS-2, MS-3")],
}


# ---------------------------------------------------------------- page furniture

def _frame(canvas, doc):
    canvas.saveState()
    w, h = PAGE
    canvas.setLineWidth(0.8)
    canvas.rect(0.3 * inch, 0.3 * inch, w - 0.6 * inch, h - 0.6 * inch)
    # title block
    tb_y = 0.3 * inch
    canvas.line(0.3 * inch, tb_y + 0.5 * inch, w - 0.3 * inch, tb_y + 0.5 * inch)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawString(0.45 * inch, tb_y + 0.32 * inch, "MSHP TROOP D CRIME LAB - UPDATE HVAC & CHILLER - R2517-01")
    canvas.setFont("Helvetica", 7)
    canvas.drawString(0.45 * inch, tb_y + 0.15 * inch, f"Section 23 09 00 Controls Submittal  |  {CONTRACTOR}  |  Job {JOB}  |  Rev 0  {ISSUE_DATE:%m/%d/%Y}")
    sheet = getattr(doc, "_sheet", ("", ""))
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 0.45 * inch, tb_y + 0.28 * inch, f"{sheet[0]}")
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 0.45 * inch, tb_y + 0.12 * inch, f"{sheet[1]}  |  page {doc.page}")
    canvas.setFillColor(colors.HexColor("#b00020"))
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawCentredString(w / 2, h - 0.22 * inch, "SYNTHETIC TEST DOCUMENT - written for software testing from the public bid set; "
                             "not issued by or for any real contractor; not for construction")
    canvas.restoreState()


class _Doc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, _Sheet):
            self._sheet = (flowable.number, flowable.title)


class _Sheet(Spacer):
    """Zero-height marker: sets the sheet number and title shown in the title block from here on."""

    def __init__(self, number: str, title: str):
        super().__init__(0, 0)
        self.number, self.title = number, title


def _table(rows, widths=None, header=True, font=7):
    data = [[Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > 28 else c for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("FONT", (0, 0), (-1, -1), "Helvetica", font), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
          ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
    if header:
        st += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", font), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8"))]
    t.setStyle(TableStyle(st))
    return t


# ---------------------------------------------------------------- sections

def _point_schedule(e: Equip) -> Table:
    rows = [["Point", "Description", "Type", "Units", "Terminal", "Object", "Inst.", "Metasys reference"]]
    for p in e.points:
        rows.append([p.short if e.kind not in ("pump", "ef") else f"{e.bms_name}-{p.short}", p.description, p.io,
                     p.units, p.terminal or ("BACnet" if p.io == "BN" else "software"), p.object_type, p.instance, p.bms_name])
    return _table(rows, [0.95 * inch, 2.35 * inch, 0.4 * inch, 0.5 * inch, 0.6 * inch, 1.05 * inch, 0.4 * inch, 3.6 * inch])


def _typical_schedule(templates, example: str) -> Table:
    rows = [["Point", "Description", "Type", "Units", "Terminal", f"Example ({example})"]]
    ins = {"AI": 0, "AO": 0, "BI": 0, "BO": 0}
    for short, desc, io, units, _cls, _role in templates:
        term = "software"
        if io in ins:
            ins[io] += 1
            term = {"AI": "UI", "AO": "AO", "BI": "BI", "BO": "BO"}[io] + str(ins[io])
        rows.append([short, desc, io, units, term, f"{NAE}/FC-x.{example}.{short}"])
    return _table(rows, [1.1 * inch, 2.9 * inch, 0.45 * inch, 0.55 * inch, 0.7 * inch, 3.8 * inch])


def _sequence(key: str):
    out = []
    for title, text in SEQUENCES[key]:
        out.append(Paragraph(f"<b>{title}.</b> {text}", BODY))
        out.append(Spacer(0, 3))
    return out


def _bom(key: str) -> Table:
    return _table([["Qty", "Part", "Description"]] + [list(r) for r in BOM[key]], [0.5 * inch, 1.8 * inch, 5.5 * inch])


def _riser(equips: list[Equip]):
    out = [Paragraph(f"Existing Metasys {NAE} (NAE55) in Mechanical Room 144, on the State network. New MS/TP "
                     "trunks FC-1 to FC-4 at 38.4 kbps, addresses 0-3 reserved. Device instance = 3000 + trunk x 100 + address.", BODY),
           Spacer(0, 4)]
    for trunk, label in [("FC-1", "Plant, AHU, exhaust, gateways"), ("FC-2", "Level 1 terminal units"),
                         ("FC-3", "Level 2 terminal units"), ("FC-4", "Level 3 terminal units")]:
        rows = [["Addr", "Device", "Controller", "Dev. inst.", "Location"]]
        for e in sorted((e for e in equips if e.trunk == trunk), key=lambda e: (e.address, e.tag)):
            rows.append([e.address, e.bms_name, e.controller, e.device_instance,
                         f"{e.floor} / {e.room}" if e.kind in ("vav", "vave", "fvav") else {"L1": "Level 1", "RF": "Roof"}.get(e.floor, e.floor) + f" / {e.room}"])
        out += [Paragraph(f"<b>{trunk}</b> - {label}", H2), _table(rows, [0.5 * inch, 1.2 * inch, 2.2 * inch, 0.8 * inch, 1.6 * inch])]
    return out


def _room_schedule(spec: dict, equips: list[Equip]):
    names = {num: name for rooms in spec["rooms"].values() for num, name in rooms.items()}
    rows = [["Floor", "Room", "Name", "Box", "AHU", "Type", "Clg max", "Min", "Htg", "kW", "Controller", "FC:Addr"]]
    for e in (e for e in equips if e.kind in ("vav", "vave", "fvav")):
        a = e.attrs
        rows.append([e.floor, e.room, names.get(e.room, ""), e.tag, "AHU01",
                     {"vav": "LMHS clg only", "vave": "LMHS elec. reheat", "fvav": f"KQFP-{a.get('unit_size')} parallel"}[e.kind],
                     a["cooling_cfm"], a["min_cfm"], a.get("heating_cfm", "-") or "-", a.get("heat_kw", "-") or "-",
                     "VMA1930", f"{e.trunk}:{e.address}"])
    return _table(rows, [0.45 * inch, 0.5 * inch, 1.75 * inch, 0.7 * inch, 0.55 * inch, 1.3 * inch,
                         0.6 * inch, 0.45 * inch, 0.45 * inch, 0.4 * inch, 0.8 * inch, 0.7 * inch])


def render(model: dict, path: Path = DOC_DIR / "submittal_230900_controls.pdf") -> Path:
    spec, equips = model["spec"], model["equips"]
    by = lambda k: [e for e in equips if e.kind == k]  # noqa: E731
    doc = _Doc(str(path), pagesize=PAGE, title="Troop D Crime Lab - 23 09 00 Controls Submittal (synthetic)",
               author=CONTRACTOR, leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.45 * inch,
               bottomMargin=0.95 * inch)
    w, h = PAGE
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(0.5 * inch, 0.95 * inch, w - 1.0 * inch, h - 1.4 * inch)],
                                       onPageEnd=_frame)])
    s = []

    sheets = [("C-000", "Title"), ("C-001", "Sheet index"), ("C-002", "Legend and abbreviations"),
              ("C-100", "Network riser"), ("C-200", "AHU01 point schedule"), ("C-201", "AHU01 sequence of operation"),
              ("C-202", "AHU01 bill of material"), ("C-300", "Chilled water plant point schedule"),
              ("C-301", "Chilled water plant sequence and bill of material"), ("C-400", "VAV typical"),
              ("C-401", "VAVE typical"), ("C-402", "FVAV typical"), ("C-403", "Terminal units bill of material"),
              ("C-500", "Exhaust fans"), ("C-600", "Mini-split monitoring"), ("C-700", "Room schedule"),
              ("C-800", "Valve and damper schedules"), ("C-900", "Clarifications and RFIs")]

    def sheet(i):
        num, title = sheets[i]
        s.append(_Sheet(num, title))
        s.append(Paragraph(f"{num}  {title}", H1))

    # C-000 title
    sheet(0)
    s += [Spacer(0, 30), Paragraph("<b>SECTION 23 09 00 - INSTRUMENTATION AND CONTROLS FOR HVAC</b>", H1),
          Paragraph("Shop drawings, point schedules, sequences of operation and product data", H2), Spacer(0, 14),
          _table([["Project", "Update HVAC & Chiller, Troop D Crime Lab (State project R2517-01)"],
                  ["Location", spec["site"]["address"]],
                  ["Owner", spec["site"]["owner"]],
                  ["Engineer of record", "per bid documents dated 10/06/2025"],
                  ["Controls contractor", CONTRACTOR],
                  ["System", "Johnson Controls Metasys, extension of the existing site system"],
                  ["Submittal", f"Job {JOB}, revision 0, {ISSUE_DATE:%B %d, %Y}"],
                  ["Status", "For review"]], [1.8 * inch, 6.5 * inch], header=False, font=8.5),
          Spacer(0, 18),
          Paragraph("This document is synthetic. It was written for testing software that reads building documents. "
                    "Equipment, rooms, capacities and sequences follow the State of Missouri public bid set for "
                    "project R2517-01. Controllers, addresses, point names and the network are invented.", SMALL),
          PageBreak()]

    # C-001 index
    sheet(1)
    s += [_table([["Sheet", "Title"]] + [list(x) for x in sheets], [1.0 * inch, 4.5 * inch]), PageBreak()]

    # C-002 legend
    sheet(2)
    legend = [["Abbrev.", "Meaning", "Abbrev.", "Meaning"],
              ["-T", "temperature", "-H", "humidity"], ["-P", "pressure", "-DP", "differential pressure"],
              ["-F", "airflow or water flow", "-S", "status"], ["-C", "command (start/stop, enable)", "-O", "analog output"],
              ["-E", "enable", "-A", "alarm"], ["-SP", "setpoint", "OCC", "occupancy"],
              ["DA", "discharge air", "SA", "supply air"], ["MA", "mixed air", "RA", "return air"],
              ["OA / MOA", "outdoor air / minimum outdoor air", "EA / EAD", "exhaust air / exhaust damper"],
              ["CCLA", "cooling coil leaving air", "LT", "low temperature (freezestat)"],
              ["HSP / LSP", "high / low static pressure switch", "CHWV", "chilled water valve"],
              ["PH", "preheat", "HUM", "humidifier"], ["ZN", "zone", "DPR", "damper"],
              ["HTG / CLG", "heating / cooling", "UNOCC", "unoccupied"],
              ["EEWT / LEWT", "entering / leaving evaporator water temp.", "ISOV", "isolation valve"],
              ["CWS / CWR", "chilled water supply / return", "CWP", "chilled water pump"],
              ["AI AO BI BO", "hardware input / output", "AV BV MV", "software value"], ["BN", "BACnet integration point", "UI", "universal input"]]
    s += [_table(legend, [1.0 * inch, 3.0 * inch, 1.0 * inch, 3.0 * inch]), Spacer(0, 8),
          Paragraph("Tags: drawing tags (VAVE07, CH01a) are used on schedules. Metasys object names use the site "
                    "convention: VAVE-07, CH-1A, AHU-1, CWP-1, EF-LAB-1, MS-1.", BODY), PageBreak()]

    # C-100 riser
    sheet(3)
    s += _riser(equips) + [PageBreak()]

    ahu = by("ahu")[0]
    sheet(4); s += [_point_schedule(ahu), PageBreak()]
    sheet(5); s += _sequence("AHU01") + [PageBreak()]
    sheet(6); s += [_bom("AHU01"), PageBreak()]

    sheet(7)
    for e in by("system") + by("chiller") + by("pump"):
        s += [Paragraph(f"{e.bms_name} - {e.controller}, {e.trunk} address {e.address}", H2), _point_schedule(e)]
    s.append(PageBreak())
    sheet(8); s += _sequence("CHW") + [Spacer(0, 6), _bom("CHW"), PageBreak()]

    sheet(9); s += [_typical_schedule(VAV_POINTS, "VAV-07"), Spacer(0, 6)] + _sequence("VAV") + [PageBreak()]
    sheet(10); s += [_typical_schedule(VAV_POINTS + REHEAT_POINTS, "VAVE-07"), Spacer(0, 6)] + _sequence("VAVE") + [PageBreak()]
    sheet(11); s += [_typical_schedule(VAV_POINTS + REHEAT_POINTS + FAN_BOX_POINTS, "FVAV-03"), Spacer(0, 6)] + _sequence("FVAV") + [PageBreak()]
    sheet(12); s += [_bom("VAV"), PageBreak()]

    sheet(13)
    for e in by("ef"):
        if e.points:
            s += [Paragraph(f"{e.bms_name} - {e.controller}, {e.trunk} address {e.address}", H2), _point_schedule(e)]
    s += [Spacer(0, 6)] + _sequence("EF") + [_bom("EF"), PageBreak()]

    sheet(14)
    for e in by("split"):
        s += [Paragraph(f"{e.bms_name} ({e.tag}) - room {e.room}", H2), _point_schedule(e)]
    s += [Spacer(0, 6)] + _sequence("MS") + [_bom("MS"), PageBreak()]

    sheet(15); s += [Paragraph("Room numbers and names from floor plans M-101 to M-103. All boxes are fed by AHU01.", BODY),
                     Spacer(0, 4), _room_schedule(spec, equips), PageBreak()]

    sheet(16)
    s += [Paragraph("Valve schedule", H2),
          _table([["Tag", "Serves", "Type", "Size", "Flow (gpm)", "Actuator", "Fail", "Control"],
                  ["CHWV", "AHU01 chilled water coils", "3-way globe", '3"', "183", "M9109 proportional", "last position", "CHWV-O"],
                  ["ISOV-1A", "CH-1A evaporator", "butterfly", '3"', "105.9", "M9124 on/off", "last position", "CH-1A ISOV-C"],
                  ["ISOV-1B", "CH-1B evaporator", "butterfly", '3"', "105.9", "M9124 on/off", "last position", "CH-1B ISOV-C"]],
                 [0.8 * inch, 1.8 * inch, 0.9 * inch, 0.5 * inch, 0.8 * inch, 1.3 * inch, 0.9 * inch, 1.2 * inch]),
          Paragraph("Damper schedule", H2),
          _table([["Tag", "Serves", "Actuator", "Qty", "Fail", "Control"],
                  ["ECON", "AHU01 economizer outdoor air", "M9220-GGA", "2", "closed", "ECON-O"],
                  ["MOA", "AHU01 minimum outdoor air (8,500 cfm)", "M9220-GGA", "1", "closed", "MOA-O"],
                  ["RAD", "AHU01 return air", "M9220-GGA", "1", "open", "RAD-O"],
                  ["EAD1, EAD2", "AHU01 exhaust (building pressure)", "M9220-GGA", "2", "closed", "EAD1-O, EAD2-O"],
                  ["BYP-1, BYP-2", "EF-LAB-1, EF-LAB-2 internal bypass", "M9220", "2", "open", "EF-LAB-x-BYP-O"]],
                 [1.0 * inch, 2.6 * inch, 1.1 * inch, 0.4 * inch, 0.7 * inch, 1.5 * inch]),
          PageBreak()]

    sheet(17)
    rfis = [["No.", "Subject", "Question / clarification"],
            ["RFI-01", "Exhaust fan schedule", "No exhaust fan schedule in the bid set. EF-LAB, EF-RR, EF-CONT taken from M-104 and M-304. Two EF-LAB numbered EF-LAB-1, EF-LAB-2 here."],
            ["RFI-02", "Stair VAV-18, VAV-19", "Boxes on level 3, sensors on level 2 stairs (M-102). Sensors placed as shown; confirm."],
            ["RFI-03", "VAV heating", "M-304 VAV heating paragraph describes electric reheat; VAV-01 to VAV-19 have no heater on M-401. Heating not programmed for these."],
            ["RFI-04", "FVAV15 airflow", "Heating cfm 360 is below minimum primary 840 on M-401. Programmed as scheduled; confirm."],
            ["CL-01", "Unit heaters", "UH01 to UH05 have their own thermostats and are not connected to the BAS."],
            ["CL-02", "EF-LOCAL", "Local controls; not connected to the BAS."]]
    s += [_table(rfis, [0.7 * inch, 1.6 * inch, 6.5 * inch])]

    doc.build(s)
    return path
