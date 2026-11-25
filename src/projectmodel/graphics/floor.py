"""2D floor graphic: one level's plan with its units in their rooms.

Input is the digital-twin payload (`twin_view.twin_payload`), so the floor graphic and the twin agree: a unit's level
and room come from the graph (hasLocation / serves to a Room, the room's `xy` on its plan sheet, normalised 0-1), and
the level's shape from the floor's `aspect`. Units sharing a room fan out around it; units on the level with no room
sit in a strip under the plan, so nothing is guessed onto the plan. Each unit shows its zone temperature (simulated,
value_model.sample) when it has a zone temperature point.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..value_model import describe, sample
from .drawing import Drawing, text_width
from .qa import check_drawing

W, MARGIN, HEAD = 1000, 20, 46
SYS_COLOR = {"Airside": "supply", "Waterside": "chilled_water", "Metering": "gas"}
ZONE_T = ("Zone_Air_Temperature_Sensor",)


@dataclass
class FlatGraphic:
    drawing: Drawing
    kind: str
    qa: dict
    placed: dict[str, tuple[float, float]]
    unplaced: list[str]

    def svg(self, theme: str = "light", **kw) -> str:
        return self.drawing.svg(theme, **kw)

    def png(self, theme: str = "light", scale: float = 1.5) -> bytes:
        return self.drawing.png(theme, scale)


def zone_temp(e: dict) -> str:
    """The unit's zone temperature, simulated, or "" when it has no such point."""
    for cls in ZONE_T:
        p = next((p for p in e.get("points", []) if p["c"] == cls), None)
        if p:
            return sample(describe(cls, None), f"{e['id']}/{p['n']}")["text"]
    return ""


def _overlaps(a, b, pad=2.0) -> bool:
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def render_floor(payload: dict, level: str) -> FlatGraphic:
    lv = next(lv for lv in payload["levels"] if lv["id"] == level)
    rooms = {r["id"]: r for r in payload.get("rooms", {}).get(level, [])}
    aspect = lv.get("aspect") or payload.get("aspect") or 0.65
    pw = W - 2 * MARGIN
    ph = pw * aspect
    units = [e for e in payload["equip"] if e.get("floor") == level and not e.get("parent")]
    on_plan = [e for e in units if e.get("room") in rooms and rooms[e["room"]].get("xy")]
    off_plan = [e for e in units if e not in on_plan]

    strip_rows = []
    x, row = MARGIN, []
    for e in off_plan:
        w = text_width(e["name"], 10) + 20
        if row and x + w > W - MARGIN:
            strip_rows.append(row)
            x, row = MARGIN, []
        row.append((e, x, w))
        x += w + 8
    if row:
        strip_rows.append(row)
    height = HEAD + ph + 20 + (30 + 36 * len(strip_rows) if strip_rows else 0) + 10

    d = Drawing(W, height, f"{lv['name']} · floor graphic")
    d.text(MARGIN, 26, lv["name"], size=16, weight=700, kind="title")
    d.text(MARGIN + text_width(lv["name"], 16) + 14, 26,
           f"{len(units)} units · {len(on_plan)} in their rooms · {len(rooms)} rooms", size=11, fill="muted",
           kind="title")
    d.rect(W - MARGIN - 82, 12, 82, 20, rx=10, fill="none", stroke="warn", width=1.2, kind="badge")
    d.text(W - MARGIN - 41, 26, "SIMULATED", size=10, weight=700, fill="warn", anchor="middle", kind="badge")
    ox, oy = MARGIN, HEAD
    d.rect(ox, oy, pw, ph, rx=4, fill="room", stroke="room_line", width=2, kind="plan", ref=level)
    for r in rooms.values():
        if r.get("xy"):
            rx, ry = ox + r["xy"][0] * pw, oy + r["xy"][1] * ph
            d.circle(rx, ry, 2, fill="room_line", stroke="room_line", width=1, kind="room", ref=r["id"])
            d.text(rx + 4, ry - 4, r["num"] or r["label"], size=8, fill="muted", kind="room", ref=r["id"])

    placed: dict[str, tuple[float, float]] = {}
    boxes: list[tuple] = []
    by_room: dict[str, list[dict]] = {}
    for e in on_plan:
        by_room.setdefault(e["room"], []).append(e)

    def marker(e: dict, cx: float, cy: float, ax: float | None = None, ay: float | None = None) -> None:
        t = zone_temp(e)
        w = max(text_width(e["name"], 10), text_width(t, 9)) + 14
        h = 30 if t else 18
        x0 = min(max(cx - w / 2, ox + 2), ox + pw - w - 2) if ax is not None else cx - w / 2
        y0 = min(max(cy - h / 2, oy + 2), oy + ph - h - 2) if ax is not None else cy - h / 2
        if ax is not None:  # on the plan: step down/right until clear of the units already drawn
            for k in range(40):
                b = (x0, y0, x0 + w, y0 + h)
                if not any(_overlaps(b, o) for o in boxes):
                    break
                y0 += h + 3
                if y0 + h > oy + ph - 2:
                    y0, x0 = oy + 2 + (k % 5) * 6, min(x0 + w + 4, ox + pw - w - 2)
            if not x0 <= ax <= x0 + w:  # a unit stacked under its room's dot needs no leader
                d.line(ax, ay, x0 + w / 2, y0 + h / 2, stroke="muted", width=0.8, kind="leader", ref=e["id"])
            d.circle(ax, ay, 3, fill="accent", stroke="bg", width=1, kind="anchor", ref=e["id"])
        boxes.append((x0, y0, x0 + w, y0 + h))
        color = SYS_COLOR.get(e.get("sys"), "accent")
        d.rect(x0, y0, w, h, rx=4, fill="card", stroke=color, width=1.4, kind="unit", ref=e["id"],
               title=f"{e['name']} · {e['cls']}" + (f" · {e.get('room_name')}" if e.get("room_name") else ""))
        d.text(x0 + 7, y0 + 13, e["name"], size=10, weight=600, kind="unit_label", ref=e["id"])
        if t:
            d.text(x0 + 7, y0 + 25, t, size=9, fill="accent", kind="value", ref=e["id"])
        placed[e["id"]] = (x0 + w / 2, y0 + h / 2)

    for rid, es in sorted(by_room.items()):
        rx, ry = ox + rooms[rid]["xy"][0] * pw, oy + rooms[rid]["xy"][1] * ph
        for e in sorted(es, key=lambda e: e["name"]):
            marker(e, rx, ry + 14, rx, ry)

    y = oy + ph + 20
    if strip_rows:
        d.text(MARGIN, y + 8, f"On this level, no room in the graph: {len(off_plan)}", size=11, weight=600,
               fill="muted", kind="footer")
        y += 22
        for row in strip_rows:
            for e, x, w in row:
                marker(e, x + w / 2, y + 15)
            y += 36
    qa = check_drawing(d, None, {e["id"] for e in units}, "unit")
    hits = sum(1 for i in range(len(boxes)) for j in range(i + 1, len(boxes)) if _overlaps(boxes[i], boxes[j], 0))
    qa["checks"].append({"rule": "markers", "ok": not hits, "level": "warn" if hits else "ok",
                         "detail": f"{hits} unit markers overlap" if hits else "no unit marker overlaps another",
                         "refs": []})
    if hits and qa["status"] == "pass":
        qa["status"] = "warn"
    return FlatGraphic(d, "floor", qa, placed, [e["id"] for e in off_plan])
