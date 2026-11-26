"""2D system graphics, drawn from the graph's `feeds` edges (through the twin payload, so they agree with the twin):

    water   the plant: pumps, chillers, boilers, towers, exchangers and what they feed (the AHU coils), in columns by
            their place along the feeds chain; plant equipment with no feeds edge (expansion tanks, specialties) sits
            in a strip under it, labelled as not connected in the graph.
    air     each air handler and the terminal units it feeds, in a grid off its duct header; terminal units no
            handler feeds sit in a strip.

Every edge drawn is a feeds edge in the graph; nothing is inferred from names or positions.
"""

from __future__ import annotations

import re

from ..value_model import describe, sample
from .drawing import Drawing, text_width
from .floor import SYS_COLOR, FlatGraphic, zone_temp
from .qa import check_drawing

W, MARGIN, HEAD = 1000, 20, 52
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


def natural(name: str) -> list:
    """Sort key: VAV 1-2-2 before VAV 1-2-10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name or "")]


MEDIUM_NAME = {"supply": "Supply air", "chilled_water": "Chilled water", "hot_water": "Hot water",
               "condenser_water": "Condenser water", "steam": "Steam"}


def _head(d: Drawing, title: str, sub: str, media: list[str] = ()) -> None:
    """Title, what is drawn, the SIMULATED badge, and a legend of the media drawn and the status dots."""
    d.text(MARGIN, 26, title, size=16, weight=700, kind="title")
    d.text(MARGIN + text_width(title, 16) + 14, 26, sub, size=11, fill="muted", kind="title")
    d.rect(W - MARGIN - 82, 12, 82, 20, rx=10, fill="none", stroke="warn", width=1.2, kind="badge")
    d.text(W - MARGIN - 41, 26, "SIMULATED", size=10, weight=700, fill="warn", anchor="middle", kind="badge")
    x, y = MARGIN, 44
    for m in media:
        d.line(x, y, x + 22, y, stroke=m, width=3.5, kind="legend")
        d.text(x + 28, y + 4, MEDIUM_NAME.get(m, m), size=10, fill="muted", kind="legend")
        x += 28 + text_width(MEDIUM_NAME.get(m, m), 10) + 22
    for state, label in (("ok", "zone near setpoint"), ("warn", "zone warm"), ("accent", "zone cool")):
        d.circle(x + 4, y, 4, fill=state, stroke=state, width=1, kind="legend")
        d.text(x + 13, y + 4, label, size=10, fill="muted", kind="legend")
        x += 13 + text_width(label, 10) + 18


def _zone_state(t: str) -> str | None:
    """ok / warm / cool from a simulated zone temperature text, or None without one."""
    m = re.search(r"-?\d+(\.\d+)?", t or "")
    if not m:
        return None
    v = float(m.group(0))
    if "°C" in t:
        v = v * 9 / 5 + 32
    return "warn" if v > 72.5 else "accent" if v < 67.5 else "ok"


def _unit(d: Drawing, e: dict, x: float, y: float, w: float = BOX_W, h: float = BOX_H, stroke: str | None = None,
          sub: str | None = None) -> None:
    """One unit: a card with its name, its type (or `sub`), and its zone temperature with a status dot."""
    d.rect(x, y, w, h, rx=6, fill="card", stroke=stroke or SYS_COLOR.get(e.get("sys"), "accent"), width=1.5,
           kind="unit", ref=e["id"], title=f"{e['name']} · {e['cls']}")
    d.text(x + 8, y + 15, e["name"], size=11 if w >= 120 else 10, weight=700, kind="unit_label", ref=e["id"])
    t = zone_temp(e)
    state = _zone_state(t)
    if w >= 120 or not t:
        d.text(x + 8, y + 29, sub if sub is not None else e["type"], size=9, fill="muted", kind="unit_label",
               ref=e["id"])
    if t:
        tx, ty = (x + w - 8, y + h - 7) if (w >= 120 and h >= 44) else (x + w - 8, y + h - 7)
        d.text(tx, ty, t, size=9, fill="ink", anchor="end", kind="value", ref=e["id"])
        if state:
            d.circle(x + w - 8 - text_width(t, 9) - 7, ty - 3, 3.2, fill=state, stroke=state, width=1, kind="value",
                     ref=e["id"])


def _strip(d: Drawing, items: list[dict], y: float, label: str, w: float = 110, h: float = 36) -> float:
    if not items:
        return y
    d.text(MARGIN, y + 8, f"{label}: {len(items)}", size=11, weight=600, fill="muted", kind="footer")
    y += 20
    per = max(1, int((W - 2 * MARGIN + 10) // (w + 10)))
    for i, e in enumerate(items):
        _unit(d, e, MARGIN + (i % per) * (w + 10), y + (i // per) * (h + 10), w, h, stroke="line")
    return y + ((len(items) + per - 1) // per) * (h + 10)


def _strip_h(n: int, w: float = 110, h: float = 36) -> float:
    if not n:
        return 0
    per = max(1, int((W - 2 * MARGIN + 10) // (w + 10)))
    return 20 + ((n + per - 1) // per) * (h + 10) + 10


TW, TH, TGAP, TROW = 104, 38, 10, 24  # a terminal tile, the gap between tiles, the space a row's header needs


def _grid_h(n: int, per: int) -> float:
    return max(1, (n + per - 1) // per) * (TH + TROW)


def _grid(d: Drawing, src: str, kids: list[str], E: dict, gx: float, y0: float, per: int, trunk: float,
          stroke: str, pos: dict) -> float:
    """The units `src` feeds, in rows off a header: one drop per unit, each a feeds edge. Returns the last header's
    y (where the trunk must reach)."""
    last = y0
    for k, i in enumerate(kids):
        row, col = divmod(k, per)
        x = gx + col * (TW + TGAP)
        ty = y0 + row * (TH + TROW) + 18
        header = ty - 9
        if col == 0:
            end = gx + (min(per, len(kids) - row * per) - 1) * (TW + TGAP) + TW / 2
            d.line(trunk, header, end, header, stroke=stroke, width=3, kind="edge", ref=src)
            last = header
        d.line(x + TW / 2, header, x + TW / 2, ty, stroke=stroke, width=2, kind="edge", ref=f"{src}>{i}")
        _unit(d, E[i], x, ty, TW, TH, stroke=stroke)
        pos[i] = (x, ty)
    return last


def plant_role(cls: str) -> str | None:
    """The value_model role of a water plant's own point, so it simulates in water units (gpm, CHW temperatures)."""
    if "Flow_Sensor" in cls:
        return "chw_flow"
    if "Temperature_Sensor" in cls:
        return "chw_entering_temp" if ("Entering" in cls or "Return" in cls) else "chw_leaving_temp"
    if cls.endswith("_Command"):
        return "cmd"
    return None


def _system_medium(s: dict) -> str:
    c = (s.get("cls", "") + " " + s.get("name", "")).lower()
    return "hot_water" if ("hot" in c or "hw" in c.split() or "heat" in c) else \
        "condenser_water" if "condenser" in c else "steam" if "steam" in c else "chilled_water"


def _card_h(s: dict) -> float:
    return 26 + 15 * len(s.get("points", [])) + 6


def _system_card(d: Drawing, s: dict, x: float, y: float, w: float) -> float:
    """A plant system's own points (lead/lag, plant supply and return temperatures) in one card. Returns its height."""
    pts = sorted(s.get("points", []), key=lambda p: p["n"])
    h = _card_h(s)
    m = _system_medium(s)
    d.rect(x, y, w, h, rx=6, fill="card", stroke=m, width=1.5, kind="unit", ref=s["id"],
           title=f"{s['name']} · {s['cls']}")
    d.rect(x, y, 5, h, rx=2, fill=m, stroke=m, width=0.5, kind="band")
    d.text(x + 12, y + 17, f"{s['name']} · {s['cls'].replace('_', ' ')}", size=11, weight=700, kind="unit_label",
           ref=s["id"])
    for k, p in enumerate(pts):
        ty = y + 34 + 15 * k
        role = plant_role(p["c"])
        v = (sample(describe(p["c"], role), f"{s['id']}/{p['n']}") if role or p["c"] not in ("", "Sensor", "Point")
             else {"text": "no unit", "state": "off"})  # a generic Sensor: nothing to simulate
        d.text(x + 14, ty, p["n"], size=10, weight=600, kind="label", ref=f"{s['id']}/{p['n']}")
        d.text(x + w - 10, ty, v["text"], size=10, anchor="end", kind="value", ref=f"{s['id']}/{p['n']}",
               fill={"ok": "ok", "warn": "warn", "off": "muted"}.get(v["state"], "accent"))
    return h


def render_water(payload: dict) -> FlatGraphic:
    """The plant's own points (one card per plant system, side by side); the plant chain in columns along the feeds
    (pump, chiller, air handler); the terminal units a source feeds (reheat coils) in a grid under the chain, off
    their own header; plant equipment with no feeds edge in a strip."""
    E = {e["id"]: e for e in payload["equip"]}
    systems = sorted((e for e in payload["equip"] if e["type"] == "System" and e["sys"] == "Waterside"
                      and e.get("points")), key=lambda e: natural(e["name"]))
    wet = [r for r in payload["rels"] if medium(r["via"]) != "supply" and r["s"] in E and r["d"] in E]
    term = {r["d"] for r in wet if E[r["d"]]["type"] in TERMINALS and not any(x["s"] == r["d"] for x in wet)}
    chain = [r for r in wet if r["d"] not in term]
    ids = {r["s"] for r in chain} | {r["d"] for r in chain} | {r["s"] for r in wet if r["d"] in term}
    loose = sorted((e for e in payload["equip"] if e["type"] in PLANT and e["id"] not in ids | term),
                   key=lambda e: natural(e["name"]))
    depth = {i: 0 for i in ids}
    for _ in range(len(ids)):  # longest path; bounded, so a cycle can't loop
        changed = False
        for r in chain:
            if depth[r["d"]] < depth[r["s"]] + 1 and depth[r["s"]] + 1 < len(ids):
                depth[r["d"]] = depth[r["s"]] + 1
                changed = True
        if not changed:
            break
    cols: dict[int, list[str]] = {}
    for i in sorted(ids, key=lambda i: natural(E[i]["name"])):
        cols.setdefault(depth[i], []).append(i)
    # Systems' own points: cards side by side, two per row
    ncard = 2 if len(systems) > 1 else 1
    cw = (W - 2 * MARGIN - (ncard - 1) * 16) / ncard
    card_rows = [systems[k:k + ncard] for k in range(0, len(systems), ncard)]
    sys_h = sum(max(_card_h(s) for s in row) + 14 for row in card_rows) + (16 if systems else 0)
    n_rows = max((len(c) for c in cols.values()), default=0)
    plant_h = n_rows * (BOX_H + ROW_GAP) + 20 if ids else 0
    ncol = len(cols)
    span = ncol * BOX_W + max(0, ncol - 1) * COL_GAP
    lanes = 30  # room on the left for the lines down to the grids
    x0 = MARGIN + lanes + max(0, (W - 2 * MARGIN - lanes - span) / 2)
    # Terminal units per source, in grids under the chain
    feeds_term: dict[str, list[str]] = {}
    for r in wet:
        if r["d"] in term:
            feeds_term.setdefault(r["s"], []).append(r["d"])
    gx = MARGIN + lanes + 16
    per = max(1, int((W - MARGIN - gx + TGAP) // (TW + TGAP)))
    blocks_h = sum(_grid_h(len(set(k)), per) + 44 for k in feeds_term.values())
    media = sorted({medium(r["via"]) for r in wet} | {_system_medium(s) for s in systems},
                   key=lambda m: list(MEDIUM_NAME).index(m) if m in MEDIUM_NAME else 9)
    top = HEAD + 22
    height = top + sys_h + plant_h + blocks_h + _strip_h(len(loose)) + 24
    d = Drawing(W, height, "Water side · system graphic")
    _head(d, "Water side", f"{len(ids)} in the plant chain · {len(term)} terminal units · {len(wet)} feeds edges · "
                           f"{len(loose)} not connected", media)
    y = top
    if systems:
        d.text(MARGIN, y + 4, "PLANT SYSTEMS AND THEIR OWN POINTS", size=10, weight=700, fill="muted", kind="footer")
        y += 16
    for row in card_rows:
        for k, s in enumerate(row):
            _system_card(d, s, MARGIN + k * (cw + 16), y, cw)
        y += max(_card_h(s) for s in row) + 14
    top0 = top + sys_h
    pos: dict[str, tuple[float, float]] = {}
    for c, members in sorted(cols.items()):
        ctop = top0 + (plant_h - 20 - len(members) * (BOX_H + ROW_GAP) + ROW_GAP) / 2
        for k, i in enumerate(members):
            pos[i] = (x0 + c * (BOX_W + COL_GAP), ctop + k * (BOX_H + ROW_GAP))
    for r in chain:
        (sx, sy), (dx, dy) = pos[r["s"]], pos[r["d"]]
        a, b = (sx + BOX_W, sy + BOX_H / 2), (dx, dy + BOX_H / 2)
        mx = (a[0] + b[0]) / 2 if b[0] > a[0] else a[0] + 12
        d.poly([a, (mx, a[1]), (mx, b[1]), b], stroke=medium(r["via"]), width=2.5, kind="edge",
               ref=f"{r['s']}>{r['d']}")
        d.poly([(b[0] - 7, b[1] - 4), b, (b[0] - 7, b[1] + 4)], stroke=medium(r["via"]), width=2, kind="flow")
    for i, (x, yy) in list(pos.items()):
        _unit(d, E[i], x, yy)
    # The grids: one per source, its line coming down a lane on the left
    yb = top0 + plant_h
    for k, (src, kids) in enumerate(sorted(feeds_term.items(), key=lambda kv: natural(E[kv[0]]["name"]))):
        kids = sorted(set(kids), key=lambda i: natural(E[i]["name"]))
        m = next(medium(r["via"]) for r in wet if r["s"] == src and r["d"] in kids)
        gh = _grid_h(len(kids), per)
        d.rect(MARGIN, yb + 6, W - 2 * MARGIN, gh + 32, rx=8, fill="fill", stroke="none", width=0, kind="band")
        what = {"hot_water": "reheat coils", "chilled_water": "cooling coils"}.get(m, "units")
        d.text(gx, yb + 24, f"{E[src]['name']} feeds {len(kids)} terminal {what} · {MEDIUM_NAME.get(m, m).lower()}",
               size=11, weight=600, kind="footer")
        lane = MARGIN + 10 + k * 6
        sx, sy = pos[src]
        last = _grid(d, src, kids, E, gx, yb + 30, per, lane, m, pos)
        d.poly([(sx, sy + BOX_H / 2), (lane, sy + BOX_H / 2), (lane, last)], stroke=m, width=3, kind="edge", ref=src)
        yb += gh + 44
    _strip(d, loose, yb, "Plant equipment with no feeds edge in the graph")
    expected = ids | term | {e["id"] for e in loose} | {s["id"] for s in systems}
    return FlatGraphic(d, "water", check_drawing(d, None, expected, "unit"), dict(pos), [e["id"] for e in loose])


def render_air(payload: dict) -> FlatGraphic:
    """Each air handler in its own band, with the terminal units it feeds in rows off its supply duct; terminal units
    no handler feeds in a strip."""
    E = {e["id"]: e for e in payload["equip"]}
    air = [r for r in payload["rels"] if medium(r["via"]) == "supply" and r["s"] in E and r["d"] in E]
    handlers = sorted({r["s"] for r in air} | {e["id"] for e in payload["equip"] if e["type"] in HANDLERS},
                      key=lambda i: natural(E[i]["name"]))
    fed = {}
    for r in air:
        fed.setdefault(r["s"], []).append(r["d"])
    served = {d for ds in fed.values() for d in ds}
    loose = sorted((e for e in payload["equip"] if e["type"] in TERMINALS and e["id"] not in served
                    and e["id"] not in handlers), key=lambda e: natural(e["name"]))
    gx = MARGIN + BOX_W + 46
    per = max(1, int((W - MARGIN - 8 - gx + TGAP) // (TW + TGAP)))
    blocks = []
    y = HEAD + 26
    for h in handlers:
        kids = sorted(set(fed.get(h, [])), key=lambda i: natural(E[i]["name"]))
        bh = max(BOX_H + 30, _grid_h(len(kids), per) + 8)
        blocks.append((h, kids, y, bh))
        y += bh + 16
    height = y + _strip_h(len(loose), TW, TH) + 10
    d = Drawing(W, height, "Air side · system graphic")
    _head(d, "Air side", f"{len(handlers)} air handler{'s' * (len(handlers) != 1)} · {len(served)} terminal units "
                         f"fed · {len(loose)} not fed in the graph", ["supply"])
    pos = {}
    for h, kids, y0, bh in blocks:
        d.rect(MARGIN - 6, y0 - 4, W - 2 * MARGIN + 12, bh + 8, rx=8, fill="fill", stroke="none", width=0, kind="band")
        hx, hy = MARGIN + 4, y0 + 8
        temps = [_zone_state(zone_temp(E[i])) for i in kids]
        warm = sum(1 for t in temps if t == "warn")
        _unit(d, E[h], hx, hy, sub=f"{E[h]['type']} · feeds {len(kids)}" + (f" · {warm} warm" if warm else ""))
        pos[h] = (hx, hy)
        trunk = hx + BOX_W + 20
        if kids:
            d.line(hx + BOX_W, hy + BOX_H / 2, trunk, hy + BOX_H / 2, stroke="supply", width=4, kind="edge", ref=h)
            last = _grid(d, h, kids, E, gx, y0, per, trunk, "supply", pos)
            d.line(trunk, hy + BOX_H / 2, trunk, max(last, hy + BOX_H / 2), stroke="supply", width=4, kind="edge",
                   ref=h)
    _strip(d, loose, y, "Terminal units no air handler feeds in the graph", TW, TH)
    expected = set(handlers) | served | {e["id"] for e in loose}
    return FlatGraphic(d, "air", check_drawing(d, None, expected, "unit"), pos, [e["id"] for e in loose])
