"""QA for generated graphics, rules first (plan §5.4, §6.2 row 8). Rules read the payload and the drawing's shapes,
never pixels.

An equipment (its 3D model, Equipments page), from the payload alone, `check_binding`:
    anchors   every anchor (template slot) has a point, or is optional (its slot isn't required)
    points    every point of the equipment is on an anchor, or listed as having no slot

A floor or system graphic (a 2D drawing), `check_drawing`:
    bounds    nothing is placed off the drawing
    drawn     every unit expected is on it
    overlap   cards don't overlap (a warning, not a failure)

An equipment with no points at all (a unit heater on its own line-voltage thermostat) is reported as "no points":
there is nothing to bind.
"""

from __future__ import annotations

from .drawing import Drawing

TOL = 0.5


def _inside(b, w, h) -> bool:
    return b[0] >= -TOL and b[1] >= -TOL and b[2] <= w + TOL and b[3] <= h + TOL


def _overlap(a, b, pad: float = 0.0) -> bool:
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


def bounds_check(d: Drawing) -> dict:
    off = [s for s in d.shapes if not _inside(s.bbox(), d.width, d.height)]
    refs = sorted({s.ref or s.kind or s.type for s in off})
    return {"rule": "bounds", "ok": not off, "level": "fail" if off else "ok",
            "detail": "everything is on the drawing" if not off else f"{len(off)} shapes off the drawing",
            "refs": refs}


def overlap_check(d: Drawing, area: tuple[float, float, float, float] | None = None) -> dict:
    cards = [s.bbox() for s in d.of_kind("card")]
    hits = sum(1 for i in range(len(cards)) for j in range(i + 1, len(cards)) if _overlap(cards[i], cards[j], 0.5))
    on_eq = sum(1 for c in cards if area and _overlap(c, area, 0.5))
    ok = not hits and not on_eq
    return {"rule": "overlap", "ok": ok, "level": "ok" if ok else "warn",
            "detail": "no card overlaps another or the equipment" if ok else
                      f"{hits} card overlaps, {on_eq} cards over the equipment", "refs": []}


def check_binding(payload: dict) -> dict:
    """QA of one equipment's points on its template's anchors: {status, checks: [...], counts}."""
    slots = payload["slots"]
    missing = [s["role"] for s in slots if s["required"] and not s["points"]]
    empty_optional = [s["role"] for s in slots if not s["required"] and not s["points"]]
    filled = [s["role"] for s in slots if s["points"]]
    checks = [{"rule": "anchors", "ok": not missing, "level": "fail" if missing else "ok",
               "detail": (f"{len(filled)} anchors have points, {len(empty_optional)} empty and optional"
                          + (f"; required with no point: {', '.join(missing)}" if missing else "")),
               "refs": missing}]
    pts = set(payload["points"])
    on_slot = {p for s in slots for p in s["points"]} & pts
    listed = set(payload.get("unplaced", [])) & pts
    nowhere = sorted(pts - on_slot - listed)
    checks.append({"rule": "points", "ok": not nowhere, "level": "fail" if nowhere else "ok",
                   "detail": (f"{len(on_slot)} on their anchor, {len(listed)} listed with no slot"
                              + (f"; on neither: {len(nowhere)}" if nowhere else "")),
                   "refs": nowhere})
    if not pts:
        status = "no points"
    elif any(c["level"] == "fail" for c in checks):
        status = "fail"
    else:
        status = "pass"
    return {"status": status, "checks": checks,
            "counts": {"points": len(pts), "bound": len(on_slot), "unplaced": len(listed),
                       "anchors": len(slots), "anchors_filled": len(filled), "required_missing": len(missing)}}


def check_drawing(d: Drawing, area=None, expected: set[str] | None = None, kind: str = "unit") -> dict:
    """QA of a floor or system graphic: bounds, and (with `expected`) every expected id drawn as a `kind` shape."""
    checks = [bounds_check(d)]
    if expected is not None:
        drawn = {s.ref for s in d.of_kind(kind)}
        miss = sorted(expected - drawn)
        checks.append({"rule": "drawn", "ok": not miss, "level": "fail" if miss else "ok",
                       "detail": f"{len(expected & drawn)} of {len(expected)} drawn", "refs": miss})
    checks.append(overlap_check(d, area))
    status = "fail" if any(c["level"] == "fail" for c in checks) else "warn" if any(
        c["level"] == "warn" for c in checks) else "pass"
    return {"status": status, "checks": checks}
