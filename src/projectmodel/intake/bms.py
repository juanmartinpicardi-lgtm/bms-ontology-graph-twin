"""BMS export (CSV) -> which BMS device is which piece of equipment ("same as"), and whether the BMS has the points
the submittal promised.

Rules:
1. Columns are found by name: the object reference (Item Reference, Reference, Object Name...), the device, the
   description, units, object type and instance.
2. A device is the same thing as a piece of equipment when it is named after the same tag (VAVE-07 = VAVE07), or when
   the submittal's riser lists the same device name and links it.
3. Each BMS object is bound to the submittal point it is (intake/binding.py): by reference, BACnet object, name,
   description or template role, and the `point_bind` job for what the rules leave. A device is the riser's device by
   name, tag, device instance or trunk and address. With no submittal, the object becomes a point of its own,
   classified from its description.
4. Gaps both ways are reported: points promised but missing in the BMS, BMS objects no document mentions.
5. What the export says about the BACnet side is kept as written, for the graph: a device's instance, trunk and
   address; an object's type, instance and units.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from . import binding, tags
from .submittal import by_term, classify, point_conf

COLUMNS = {  # first match wins; Metasys, Niagara and generic BACnet export headers
    "ref": ["item reference", "reference", "object reference", "object name", "point name", "path", "ord",
            "point path", "name"],
    "device": ["device", "controller", "device name", "parent", "controller name"],
    "description": ["description", "desc", "point description", "display name"],
    "units": ["units", "unit", "facets"],
    "object": ["object type", "type", "point type"],
    "instance": ["instance", "object instance"],
    "device_instance": ["device instance", "device id", "dev. inst.", "device instance number"],
    "trunk": ["trunk", "network", "field bus", "fieldbus", "bus"],
    "address": ["address", "mac address", "mstp address", "ms/tp address"],
}


def _column(header: list[str], key: str) -> str | None:
    low = {h.lower().strip(): h for h in header}
    return next((low[c] for c in COLUMNS[key] if c in low), None)


def read(path: Path, name: str, equipment: list[dict], controllers: list[dict], points: list[dict], log,
         ai: binding.AI | None = None) -> list[dict]:
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
    # The riser's device whatever the BMS calls it: the same name or tag, device instance (DEV3104), trunk and address.
    dmap = binding.match_devices(
        {c["data"]["device"]: {k: c["data"].get(k) for k in ("instance", "trunk", "address")} for c in controllers},
        {dev: _bacnet_device(objs[0], col) for dev, objs in devices.items()})
    facts = []
    linked = 0
    for dev, objs in devices.items():
        norm = tags.normal(dev)
        sub_dev, how = dmap.get(dev, (None, None))
        ctrl = by_ctrl.get(sub_dev) if sub_dev else None
        eq_norm = ctrl["data"].get("equip") if ctrl and ctrl["data"].get("equip") else (norm if norm in by_normal else None)
        via = ("submittal riser" if how == "same name" else f"{how} on the riser") \
            if ctrl and ctrl["data"].get("equip") else "same tag" if eq_norm else None
        src = {"file": name, "page": None, "bbox": None, "row": objs[0]["_row"]}
        data = {"device": dev, "objects": len(objs), "equip": eq_norm, "via": via,
                **({"riser_device": sub_dev, "riser_via": how} if sub_dev and sub_dev != dev else {}),
                **_bacnet_device(objs[0], col)}
        if eq_norm:
            linked += 1
            eq = by_normal.get(eq_norm)
            label = f"BMS {dev} = {eq['data']['tag'] if eq else eq_norm}"
            facts.append({"id": f"alias:{dev}", "kind": "alias", "label": label, "data": data, "src": src,
                          "method": "rule", "conf": 0.96 if via != "same tag" else 0.93, "step": "bms", "ask": None})
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
    bound = _bind(rows, col, device_of, points, controllers, equipment, dmap, log, ai)
    matched = 0
    bms_only = []
    for dev, objs in devices.items():
        for r in objs:
            ref = r[col["ref"]]
            src = {"file": name, "page": None, "bbox": None, "row": r["_row"]}
            b = bound.get(ref)
            if b:
                matched += 1
                facts.append({"id": f"obj:{ref}", "kind": "bms_object", "label": ref,
                              "data": {"ref": ref, "device": dev, "point": b.point, "matched": True,
                                       "bind": {"rule": b.rule, "raw": b.raw, "conf": b.conf, "why": b.why,
                                                **({"model": b.model, "calls": b.calls} if b.model else {})},
                                       **_bacnet_object(r, col)},
                              "src": src, "method": b.method, "conf": b.conf, "step": "bms", "ask": None})
            else:
                desc = r.get(col["description"] or "", "") or ref.rsplit(".", 1)[-1]
                cls, c = classify(desc, ref.rsplit(".", 1)[-1])
                term = by_term(desc, ref.rsplit(".", 1)[-1]) is not None
                bms_only.append(ref)
                facts.append({"id": f"obj:{ref}", "kind": "bms_object", "label": ref,
                              "data": {"ref": ref, "device": dev, "point": None, "matched": False,
                                       "description": desc, "class": cls, "class_conf": c,
                                       "units": r.get(col["units"] or "", ""), **_bacnet_object(r, col),
                                       **({"term": True} if term else {})},
                              "src": src, "method": "rule",
                              "conf": point_conf(cls, c, step="bms", base=0.5, cap=0.9, term=term),
                              "step": "bms", "ask": None})
    got = {b.point for b in bound.values()}
    missing = [ref for ref, p in promised.items() if p["id"] not in got]
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


def _bind(rows, col, device_of, points, controllers, equipment, dmap, log, ai) -> dict[str, binding.Bound]:
    """BMS reference -> the submittal point it is (intake/binding.py)."""
    if not points:
        return {}
    pts = [binding.Point(p["id"], d["ref"], d["device"], d.get("short") or d["ref"].rsplit(".", 1)[-1],
                         d.get("description") or "", d.get("io") or "", d.get("units") or "", d.get("object") or "",
                         d.get("object_instance")) for p in points for d in [p["data"]]]
    objs = [binding.Obj(r[col["ref"]], device_of(r), re.split(r"[./]", r[col["ref"]])[-1],
                        _cell(r, col, "description"), _cell(r, col, "object"), _int(_cell(r, col, "instance")),
                        _int(_cell(r, col, "device_instance")), _cell(r, col, "units")) for r in rows]
    eq_class = {e["data"]["normal"]: e["data"].get("class") for e in equipment}
    inst = {c["data"]["device"]: c["data"].get("instance") for c in controllers}
    cls = {c["data"]["device"]: eq_class.get(c["data"].get("equip")) for c in controllers}
    bound, _ = binding.bind(pts, objs, dmap, inst, cls, log, ai)
    return {b.obj: b for b in bound.values()}


def _cell(r: dict, col: dict, key: str) -> str:
    return str(r.get(col[key] or "", "") or "").strip()


def _int(text: str) -> int | str | None:
    return int(text) if text.isdigit() else (text or None)


def _bacnet_device(r: dict, col: dict) -> dict:
    """The device's BACnet instance, trunk and address, where the export has those columns."""
    out = {"instance": _int(_cell(r, col, "device_instance")), "trunk": _cell(r, col, "trunk") or None,
           "address": _int(_cell(r, col, "address"))}
    return {k: v for k, v in out.items() if v is not None}


def _bacnet_object(r: dict, col: dict) -> dict:
    """The object's type, instance and units, and its device's instance, as the export writes them."""
    out = {"object_type": _cell(r, col, "object") or None, "object_instance": _int(_cell(r, col, "instance")),
           "device_instance": _int(_cell(r, col, "device_instance")), "units": _cell(r, col, "units") or None}
    return {k: v for k, v in out.items() if v is not None}


def _issue(id_, text, name):
    return {"id": f"issue:{id_}", "kind": "issue", "label": text, "data": {"text": text, "severity": "check"},
            "src": {"file": name, "page": None, "bbox": None}, "method": "rule", "conf": 0.5, "step": "bms",
            "ask": {"q": text, "field": None, "options": []}}
