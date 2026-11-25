"""2D system graphics, drawn from the graph's `feeds` edges (through the twin payload, so they agree with the twin):

    water   the plant: pumps, chillers, boilers, towers, exchangers and what they feed (the AHU coils), in columns by
            their place along the feeds chain; plant equipment with no feeds edge (expansion tanks, specialties) sits
            in a strip under it, labelled as not connected in the graph.
    air     each air handler and the terminal units it feeds, in a grid off its duct header; terminal units no
            handler feeds sit in a strip.

Every edge drawn is a feeds edge in the graph; nothing is inferred from names or positions.
"""

from __future__ import annotations

from ..value_model import describe, sample
from .drawing import Drawing, text_width
from .floor import SYS_COLOR, FlatGraphic, zone_temp
from .qa import check_drawing

W, MARGIN, HEAD = 1000, 20, 46
PLANT = ("Pump", "Chiller", "Boiler", "Cooling tower", "Heat exchanger", "Hydronic specialty")
HANDLERS = ("AHU", "RTU")
TERMINALS = ("VAV", "VAV (fan powered)", "VAV (dual duct)", "Fan coil")
BOX_W, BOX_H, COL_GAP, ROW_GAP = 130, 44, 70, 18


def medium(via: str) -> str:
    v = (via or "").lower()
    if "air" in v:
        return "supply"
    if "condenser" in v:
        return "condenser_water"
    if "hot" in v or "heat" in v:
        return "hot_water"
    if "steam" in v:
        return "steam"
    return "chilled_water"


def _head(d: Drawing, title: str, sub: str) -> None:
    d.text(MARGIN, 26, title, size=16, weight=700, kind="title")
    d.text(MARGIN + text_width(title, 16) + 14, 26, sub, size=11, fill="muted", kind="title")
    d.rect(W - MARGIN - 82, 12, 82, 20, rx=10, fill="none", stroke="warn", width=1.2, kind="badge")
    d.text(W - MARGIN - 41, 26, "SIMULATED", size=10, weight=700, fill="warn", anchor="middle", kind="badge")


def _unit(d: Drawing, e: dict, x: float, y: float, w: float = BOX_W, h: float = BOX_H) -> None:
    d.rect(x, y, w, h, rx=5, fill="card", stroke=SYS_COLOR.get(e.get("sys"), "accent"), width=1.5, kind="unit",
           ref=e["id"], title=f"{e['name']} · {e['cls']}")
    d.text(x + 8, y + 16, e["name"], size=11, weight=700, kind="unit_label", ref=e["id"])
    t = zone_temp(e)
    if w >= 120 or not t:
        d.text(x + 8, y + 30, e["type"], size=9, fill="muted", kind="unit_label", ref=e["id"])
    if t and w >= 120 and h >= 44:
        d.text(x + w - 8, y + h - 6, t, size=9, fill="accent", anchor="end", kind="value", ref=e["id"])
    elif t:
        d.text(x + 8, y + 30, t, size=9, fill="accent", kind="value", ref=e["id"])


def _strip(d: Drawing, items: list[dict], y: float, label: str, w: float = 110, h: float = 36) -> float:
    if not items:
        return y
    d.text(MARGIN, y + 8, f"{label}: {len(items)}", size=11, weight=600, fill="muted", kind="footer")
    y += 20
    per = max(1, int((W - 2 * MARGIN + 10) // (w + 10)))
    for i, e in enumerate(items):
        _unit(d, e, MARGIN + (i % per) * (w + 10), y + (i // per) * (h + 10), w, h)
    return y + ((len(items) + per - 1) // per) * (h + 10)


def _strip_h(n: int, w: float = 110, h: float = 36) -> float:
    if not n:
        return 0
    per = max(1, int((W - 2 * MARGIN + 10) // (w + 10)))
    return 20 + ((n + per - 1) // per) * (h + 10) + 10


def plant_role(cls: str) -> str | None:
    """The value_model role of a water plant's own point, so it simulates in water units (gpm, CHW temperatures)."""
    if "Flow_Sensor" in cls:
        return "chw_flow"
    if "Temperature_Sensor" in cls:
        return "chw_entering_temp" if ("Entering" in cls or "Return" in cls) else "chw_leaving_temp"
    if cls.endswith("_Command"):
        return "cmd"
    return None


def _system_card(d: Drawing, s: dict, x: float, y: float, w: float) -> float:
    """A plant system's own points (lead/lag, plant supply and return temperatures) in one card. Returns its height."""
    pts = sorted(s.get("points", []), key=lambda p: p["n"])
    h = 26 + 15 * len(pts) + 6
    d.rect(x, y, w, h, rx=5, fill="card", stroke="chilled_water", width=1.5, dash="5 3", kind="unit", ref=s["id"],
           title=f"{s['name']} · {s['cls']}")
    d.text(x + 8, y + 17, f"{s['name']} · {s['cls'].replace('_', ' ')}", size=11, weight=700, kind="unit_label",
           ref=s["id"])
    for k, p in enumerate(pts):
        ty = y + 34 + 15 * k
        role = plant_role(p["c"])
        v = (sample(describe(p["c"], role), f"{s['id']}/{p['n']}") if role or p["c"] not in ("", "Sensor", "Point")
             else {"text": "no unit", "state": "off"})  # a generic Sensor: nothing to simulate
        d.text(x + 10, ty, p["n"], size=10, weight=600, kind="label", ref=f"{s['id']}/{p['n']}")
        d.text(x + w - 10, ty, v["text"], size=10, anchor="end", kind="value", ref=f"{s['id']}/{p['n']}",
               fill={"ok": "ok", "warn": "warn", "off": "muted"}.get(v["state"], "accent"))
    return h


def render_water(payload: dict) -> FlatGraphic:
    E = {e["id"]: e for e in payload["equip"]}
    systems = sorted((e for e in payload["equip"] if e["type"] == "System" and e["sys"] == "Waterside"
                      and e.get("points")), key=lambda e: e["name"])
    sys_h = sum(26 + 15 * len(s["points"]) + 6 + 12 for s in systems)
    wet = [r for r in payload["rels"] if medium(r["via"]) != "supply" and r["s"] in E and r["d"] in E]
    ids = {r["s"] for r in wet} | {r["d"] for r in wet}
    loose = sorted((e for e in payload["equip"] if e["type"] in PLANT and e["id"] not in ids), key=lambda e: e["name"])
    depth = {i: 0 for i in ids}
    for _ in range(len(ids)):  # longest path; bounded, so a cycle can't loop
        changed = False
        for r in wet:
            if depth[r["d"]] < depth[r["s"]] + 1 and depth[r["s"]] + 1 < len(ids):
                depth[r["d"]] = depth[r["s"]] + 1
                changed = True
        if not changed:
            break
    cols: dict[int, list[str]] = {}
    for i in sorted(ids, key=lambda i: E[i]["name"]):
        cols.setdefault(depth[i], []).append(i)
    n_rows = max((len(c) for c in cols.values()), default=0)
    plant_h = n_rows * (BOX_H + ROW_GAP) + 20
    ncol = len(cols)
    span = ncol * BOX_W + max(0, ncol - 1) * COL_GAP
    x0 = MARGIN + max(0, (W - 2 * MARGIN - span) / 2)
    height = HEAD + 20 + sys_h + plant_h + _strip_h(len(loose)) + 20
    d = Drawing(W, height, "Water side · system graphic")
    _head(d, "Water side", f"{len(ids)} connected by feeds · {len(wet)} feeds edges · {len(loose)} not connected")
    y = HEAD + 10
    for s in systems:  # the plant's own points, above the plant
        y += _system_card(d, s, MARGIN + max(0, (W - 2 * MARGIN - span) / 2), y, max(span, 320)) + 12
    top0 = HEAD + 20 + sys_h
    pos: dict[str, tuple[float, float]] = {}
    for c, members in sorted(cols.items()):
        top = top0 + (plant_h - 20 - len(members) * (BOX_H + ROW_GAP) + ROW_GAP) / 2
        for k, i in enumerate(members):
            pos[i] = (x0 + c * (BOX_W + COL_GAP), top + k * (BOX_H + ROW_GAP))
    for r in wet:
        (sx, sy), (dx, dy) = pos[r["s"]], pos[r["d"]]
        a, b = (sx + BOX_W, sy + BOX_H / 2), (dx, dy + BOX_H / 2)
        mx = (a[0] + b[0]) / 2 if b[0] > a[0] else a[0] + 12
        d.poly([a, (mx, a[1]), (mx, b[1]), b], stroke=medium(r["via"]), width=2.5, kind="edge",
               ref=f"{r['s']}>{r['d']}")
        d.poly([(b[0] - 7, b[1] - 4), b, (b[0] - 7, b[1] + 4)], stroke=medium(r["via"]), width=2, kind="flow")
    for i, (x, y) in pos.items():
        _unit(d, E[i], x, y)
    _strip(d, loose, top0 + plant_h, "Plant equipment with no feeds edge in the graph")
    expected = ids | {e["id"] for e in loose} | {s["id"] for s in systems}
    return FlatGraphic(d, "water", check_drawing(d, None, expected, "unit"), {i: p for i, p in pos.items()},
                       [e["id"] for e in loose])


def render_air(payload: dict) -> FlatGraphic:
    E = {e["id"]: e for e in payload["equip"]}
    air = [r for r in payload["rels"] if medium(r["via"]) == "supply" and r["s"] in E and r["d"] in E]
    handlers = sorted({r["s"] for r in air} | {e["id"] for e in payload["equip"] if e["type"] in HANDLERS},
                      key=lambda i: E[i]["name"])
    fed = {}
    for r in air:
        fed.setdefault(r["s"], []).append(r["d"])
    served = {d for ds in fed.values() for d in ds}
    loose = sorted((e for e in payload["equip"] if e["type"] in TERMINALS and e["id"] not in served
                    and e["id"] not in handlers), key=lambda e: e["name"])
    tw, th, gap = 104, 40, 10
    gx = MARGIN + BOX_W + 50
    per = max(1, int((W - MARGIN - gx + gap) // (tw + gap)))
    blocks = []
    y = HEAD + 20
    for h in handlers:
        kids = sorted(set(fed.get(h, [])), key=lambda i: E[i]["name"])
        rows = max(1, (len(kids) + per - 1) // per)
        bh = max(BOX_H + 10, rows * (th + 26))
        blocks.append((h, kids, y, bh))
        y += bh + 24
    height = y + _strip_h(len(loose), tw, th) + 10
    d = Drawing(W, height, "Air side · system graphic")
    _head(d, "Air side", f"{len(handlers)} air handler{'s' * (len(handlers) != 1)} · {len(served)} terminal units "
                         f"fed · {len(loose)} not fed in the graph")
    pos = {}
    for h, kids, y0, bh in blocks:
        hx, hy = MARGIN, y0 + 4
        _unit(d, E[h], hx, hy)
        pos[h] = (hx, hy)
        trunk = hx + BOX_W + 20
        if kids:
            d.line(hx + BOX_W, hy + BOX_H / 2, trunk, hy + BOX_H / 2, stroke="supply", width=4, kind="edge", ref=h)
        last_row_y = hy + BOX_H / 2
        for k, i in enumerate(kids):
            row, col = divmod(k, per)
            x = gx + col * (tw + gap)
            ty = y0 + row * (th + 26) + 18
            header = ty - 9
            if col == 0:
                end = gx + (min(per, len(kids) - row * per) - 1) * (tw + gap) + tw / 2
                d.line(trunk, header, end, header, stroke="supply", width=3, kind="edge", ref=h)
                last_row_y = header
            d.line(x + tw / 2, header, x + tw / 2, ty, stroke="supply", width=2, kind="edge", ref=f"{h}>{i}")
            _unit(d, E[i], x, ty, tw, th)
            pos[i] = (x, ty)
        if kids:
            d.line(trunk, hy + BOX_H / 2, trunk, max(last_row_y, hy + BOX_H / 2), stroke="supply", width=4,
                   kind="edge", ref=h)
    _strip(d, loose, y, "Terminal units no air handler feeds in the graph", tw, th)
    expected = set(handlers) | served | {e["id"] for e in loose}
    return FlatGraphic(d, "air", check_drawing(d, None, expected, "unit"), pos, [e["id"] for e in loose])
