"""BMS export (CSV) -> which BMS device is which piece of equipment ("same as"), and whether the BMS has the points
the submittal promised.

Rules:
1. Columns are found by name: the object reference (Item Reference, Reference, Object Name...), the device, the
   description, units, object type and instance.
2. A device is the same thing as a piece of equipment when it is named after the same tag (VAVE-07 = VAVE07), or when
   the submittal's riser lists the same device name and links it.
3. Each BMS object is matched to a submittal point by reference. With no submittal, the object becomes a point of its
   own, classified from its description.
4. Gaps both ways are reported: points promised but missing in the BMS, BMS objects no document mentions.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from . import tags
from .submittal import classify

COLUMNS = {
    "ref": ["item reference", "reference", "object reference", "object name", "point name", "name"],
    "device": ["device", "controller", "device name"],
    "description": ["description", "desc"],
    "units": ["units", "unit"],
    "object": ["object type", "type"],
    "instance": ["instance", "object instance"],
}


def _column(header: list[str], key: str) -> str | None:
    low = {h.lower().strip(): h for h in header}
    return next((low[c] for c in COLUMNS[key] if c in low), None)


def read(path: Path, name: str, equipment: list[dict], controllers: list[dict], points: list[dict], log) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    if not rows:
        log("The file has no rows.")
        return []
    header = list(rows[0])
    col = {k: _column(header, k) for k in COLUMNS}
    log(f"{name}: {len(rows)} objects; columns used: " + ", ".join(f"{k} = '{v}'" for k, v in col.items() if v))
    if not col["ref"]:
        log("No column names the objects (Item Reference, Name...): cannot read this export.")
        return []

    def device_of(r):
        if col["device"]:
            return re.sub(r"\s*\(.*\)$", "", r[col["device"]]).strip()
        parts = r[col["ref"]].split(".")
        return parts[-2] if len(parts) >= 3 else ""

    devices: dict[str, list[dict]] = {}
    for i, r in enumerate(rows):
        devices.setdefault(device_of(r), []).append(r | {"_row": i + 2})

    by_normal = {e["data"]["normal"]: e for e in equipment}
    by_ctrl = {c["data"]["device"]: c for c in controllers}
    facts = []
    linked = 0
    for dev, objs in devices.items():
        norm = tags.normal(dev)
        ctrl = by_ctrl.get(dev)
        eq_norm = ctrl["data"].get("equip") if ctrl and ctrl["data"].get("equip") else (norm if norm in by_normal else None)
        via = "submittal riser" if ctrl and ctrl["data"].get("equip") else "same tag" if eq_norm else None
        src = {"file": name, "page": None, "bbox": None, "row": objs[0]["_row"]}
        data = {"device": dev, "objects": len(objs), "equip": eq_norm, "via": via}
        if eq_norm:
            linked += 1
            eq = by_normal.get(eq_norm)
            label = f"BMS {dev} = {eq['data']['tag'] if eq else eq_norm}"
            facts.append({"id": f"alias:{dev}", "kind": "alias", "label": label, "data": data, "src": src,
                          "method": "rule", "conf": 0.96 if via == "submittal riser" else 0.93, "step": "bms", "ask": None})
        else:
            options = [{"value": e["data"]["normal"], "label": f"It is {e['data']['tag']}"}
                       for n, e in by_normal.items() if norm and n[:3] == norm[:3]][:4]
            options.append({"value": "__new__", "label": "Equipment of its own"})
            facts.append({"id": f"alias:{dev}", "kind": "alias", "label": f"BMS {dev} = ?", "data": data, "src": src,
                          "method": "rule", "conf": 0.4, "step": "bms",
                          "ask": {"q": f"BMS device {dev} ({len(objs)} objects) matches no equipment. What is it?",
                                  "field": "equip", "options": options}})
    log(f"Devices: {len(devices)} in the export, {linked} linked to equipment"
        + (f", {len(devices) - linked} to identify" if len(devices) > linked else ""))

    promised = {p["data"]["ref"]: p for p in points}
    matched = 0
    bms_only = []
    for dev, objs in devices.items():
        for r in objs:
            ref = r[col["ref"]]
            src = {"file": name, "page": None, "bbox": None, "row": r["_row"]}
            p = promised.get(ref)
            if p:
                matched += 1
                facts.append({"id": f"obj:{ref}", "kind": "bms_object", "label": ref,
                              "data": {"ref": ref, "device": dev, "point": p["id"], "matched": True},
                              "src": src, "method": "rule", "conf": 0.97, "step": "bms", "ask": None})
            else:
                desc = r.get(col["description"] or "", "") or ref.rsplit(".", 1)[-1]
                cls, c = classify(desc, ref.rsplit(".", 1)[-1])
                bms_only.append(ref)
                facts.append({"id": f"obj:{ref}", "kind": "bms_object", "label": ref,
                              "data": {"ref": ref, "device": dev, "point": None, "matched": False,
                                       "description": desc, "class": cls, "class_conf": c,
                                       "units": r.get(col["units"] or "", "")},
                              "src": src, "method": "rule", "conf": round(min(0.9, 0.5 + 0.4 * c), 2) if cls else 0.4,
                              "step": "bms", "ask": None})
    found = {r[col["ref"]] for r in rows}
    missing = [ref for ref in promised if ref not in found]
    if points:
        log(f"Points: {matched} of {len(promised)} submittal points are in the BMS"
            + (f"; {len(missing)} promised but missing" if missing else "")
            + (f"; {len(bms_only)} BMS objects in no document" if bms_only else ""))
    if missing:
        text = f"{len(missing)} points in the submittal are not in the BMS export (e.g. {', '.join(missing[:3])})."
        facts.append(_issue("bms-missing", text, name))
    if bms_only and points:
        text = f"{len(bms_only)} BMS objects are in no document (e.g. {', '.join(bms_only[:3])})."
        facts.append(_issue("bms-extra", text, name))
    return facts


def _issue(id_, text, name):
    return {"id": f"issue:{id_}", "kind": "issue", "label": text, "data": {"text": text, "severity": "check"},
            "src": {"file": name, "page": None, "bbox": None}, "method": "rule", "conf": 0.5, "step": "bms",
            "ask": {"q": text, "field": None, "options": []}}
