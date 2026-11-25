"""2D equipment graphic: the template's schematic with every bound point on its anchor.

The input is the same payload the 3D viewer gets (`equipment_view.equipment_payload`): points bound to template slots
through the graph (hasPoint + class), each slot's anchor from anchors.yaml. So 2D and 3D always agree on what is where.

    payload --(LAYOUTS[template])--> parts on the sheet --(anchor part/at)--> a card per anchor with its points

Cards sit in bands above and below the equipment (a band per side, in rows), each with a leader to its anchor, so
they never overlap the equipment or each other. A required slot with no point gets a dashed "expected, not found"
card. Points with no slot are listed under the drawing. Values are simulated (value_model.sample) and say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..value_model import sample
from .drawing import Drawing, Shape, text_width
from .layouts import LAYOUTS
from .symbols import Sheet

MARGIN, HEAD, CARD_ROW, CARD_PAD, CARD_GAP, ROW_GAP = 16, 44, 15, 6, 10, 12
STATUS = {"confirmed": "ok", "proposed": "warn", "rejected": "bad"}


@dataclass
class Graphic:
    drawing: Drawing
    template: str
    placed: dict[str, tuple[float, float]] = field(default_factory=dict)   # point id -> anchor (drawing coords)
    unanchored: list[str] = field(default_factory=list)                    # placed by slot, but its part isn't drawn
    ghosts: list[str] = field(default_factory=list)                        # required roles with no point
    area: tuple[float, float, float, float] = (0, 0, 0, 0)                 # the equipment's box in the drawing

    def svg(self, theme: str = "light", **kw) -> str:
        return self.drawing.svg(theme, **kw)

    def png(self, theme: str = "light", scale: float = 1.5) -> bytes:
        return self.drawing.png(theme, scale)


def _shift(s: Shape, dx: float, dy: float) -> Shape:
    g = dict(s.geo)
    if s.type == "rect":
        g["x"] += dx; g["y"] += dy  # noqa: E702
    elif s.type == "line":
        g["x1"] += dx; g["x2"] += dx; g["y1"] += dy; g["y2"] += dy  # noqa: E702
    elif s.type == "poly":
        g["pts"] = [(x + dx, y + dy) for x, y in g["pts"]]
    elif s.type == "circle":
        g["cx"] += dx; g["cy"] += dy  # noqa: E702
    elif s.type == "text":
        g["x"] += dx; g["y"] += dy  # noqa: E702
    return Shape(s.type, g, s.style, s.kind, s.ref, s.title)


def _short(text: str, n: int = 26) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _cards(payload: dict) -> list[dict]:
    """One card per anchor (part + at): its points, or the role it expects when a required slot is empty."""
    cards: dict[tuple, dict] = {}
    for slot in payload["slots"]:
        a = slot["anchor"]
        pts = [p for p in slot["points"] if p in payload["points"]]
        for pid in pts:
            p = payload["points"][pid]
            key = (p.get("part") or a["part"], p.get("at") if p.get("at") is not None else a.get("at"))
            cards.setdefault(key, {"part": key[0], "at": key[1], "points": [], "ghost": []})["points"].append(pid)
        if slot["required"] and not pts:
            key = (a["part"], a.get("at"))
            cards.setdefault(key, {"part": key[0], "at": key[1], "points": [], "ghost": []})["ghost"].append(slot["role"])
    return list(cards.values())


def _card_lines(card: dict, payload: dict) -> list[dict]:
    lines = []
    for pid in sorted(card["points"], key=lambda i: payload["points"][i]["label"]):
        p = payload["points"][pid]
        v = sample(p.get("sim") or {}, pid) if p.get("sim") else {"text": "", "state": None}
        lines.append({"pid": pid, "name": _short(p["label"]), "value": v["text"], "state": v["state"],
                      "status": STATUS.get(p.get("status") or "", "warn"), "cls": p.get("cls") or ""})
    for role in card["ghost"]:
        lines.append({"pid": None, "role": role, "name": role.replace("_", " "), "value": "expected, not found",
                      "state": None, "status": "off", "cls": ""})
    return lines


def render(payload: dict, *, title: str | None = None) -> Graphic:
    tid = payload["equipment"]["template"]
    if tid not in LAYOUTS:
        raise ValueError(f"no 2D layout for template {tid!r}")
    # 1. the equipment, drawn at the origin, to know where its anchors are
    sheet = Sheet(Drawing(0, 0))
    aw, ah = LAYOUTS[tid](sheet, payload.get("variant") or {})

    # 2. cards: size, then band (above or below, by the anchor's height) and row
    cards = []
    for c in _cards(payload):
        pos = sheet.anchor(c["part"], c["at"])
        lines = _card_lines(c, payload)
        w = max(110.0, max(text_width(ln["name"], 10) + text_width(ln["value"], 10) + 28 for ln in lines) + 2 * CARD_PAD)
        cards.append({**c, "pos": pos, "lines": lines, "w": w, "h": len(lines) * CARD_ROW + 2 * CARD_PAD})
    width = max(aw, 640) + 2 * MARGIN
    placed_cards = [c for c in cards if c["pos"]]
    lost = [c for c in cards if not c["pos"]]

    def rows(band: list[dict]) -> list[list[dict]]:
        out, cur, x = [], [], MARGIN
        for c in sorted(band, key=lambda c: c["pos"][0]):
            if cur and x + c["w"] > width - MARGIN:
                out.append(cur)
                cur, x = [], MARGIN
            cur.append(c)
            x += c["w"] + CARD_GAP
        return out + ([cur] if cur else [])

    above = rows([c for c in placed_cards if c["pos"][1] < ah / 2])
    below = rows([c for c in placed_cards if c["pos"][1] >= ah / 2])
    row_h = lambda r: max(c["h"] for c in r)  # noqa: E731
    top_h = sum(row_h(r) + ROW_GAP for r in above) + (ROW_GAP if above else 0)
    bot_h = sum(row_h(r) + ROW_GAP for r in below) + (ROW_GAP if below else 0)
    oy = HEAD + top_h + 10
    ox = MARGIN + (width - 2 * MARGIN - aw) / 2

    # unplaced list under the drawing: a wrapped run of names
    unplaced = [payload["points"][i] | {"id": i} for i in payload.get("unplaced", [])]
    lines_un, cur, x = [], [], MARGIN
    for p in unplaced:
        t = f"{p['label']} ({p.get('cls') or 'no class'})"
        w = text_width(t, 10) + 14
        if cur and x + w > width - MARGIN:
            lines_un.append(cur)
            cur, x = [], MARGIN
        cur.append((p["id"], t, x))
        x += w
    if cur:
        lines_un.append(cur)
    lost_lines = sum(len(c["lines"]) for c in lost)
    foot_h = (28 + 15 * len(lines_un) if unplaced else 0) + (28 + 15 * lost_lines if lost else 0) + 22
    height = oy + ah + 10 + bot_h + foot_h

    d = Drawing(width, height, title or f"{payload['equipment']['label']} · 2D graphic")
    eq = payload["equipment"]
    d.text(MARGIN, 24, eq["label"], size=16, weight=700, kind="title")
    sub = f"{eq.get('cls') or ''} · template {tid} · fit {round(100 * eq.get('slot_fill', 0))}%"
    d.text(MARGIN + text_width(eq["label"], 16) + 14, 24, sub, size=11, fill="muted", kind="title")
    d.rect(width - MARGIN - 82, 10, 82, 20, rx=10, fill="none", stroke="warn", width=1.2, kind="badge")
    d.text(width - MARGIN - 41, 24, "SIMULATED", size=10, weight=700, fill="warn", anchor="middle", kind="badge")
    for s in sheet.d.shapes:
        d.add(_shift(s, ox, oy))
    area = (ox, oy, ox + aw, oy + ah)
    g = Graphic(d, tid, area=area)

    def draw_card(c: dict, x: float, y: float, side: str) -> None:
        ax, ay = c["pos"][0] + ox, c["pos"][1] + oy
        ghost = not c["points"]
        ex, ey = x + c["w"] / 2, (y + c["h"]) if side == "above" else y
        d.line(ex, ey, ax, ay, stroke="ghost" if ghost else "muted", width=1, dash="3 3" if ghost else None,
               kind="leader", ref=c["part"])
        d.circle(ax, ay, 3.5, fill="ghost" if ghost else "accent", stroke="bg", width=1.2, kind="anchor", ref=c["part"])
        d.rect(x, y, c["w"], c["h"], rx=5, fill="card", stroke="ghost" if ghost else "card_line", width=1.2,
               dash="4 3" if ghost else None, kind="card", ref=c["part"])
        for i, ln in enumerate(c["lines"]):
            ty = y + CARD_PAD + (i + 1) * CARD_ROW - 4
            if ln["pid"]:
                d.circle(x + CARD_PAD + 3, ty - 3.5, 3, fill=ln["status"], stroke=ln["status"], width=1,
                         kind="status", ref=ln["pid"])
                d.text(x + CARD_PAD + 11, ty, ln["name"], size=10, weight=600, kind="label", ref=ln["pid"])
                d.text(x + c["w"] - CARD_PAD, ty, ln["value"], size=10, anchor="end",
                       fill={"ok": "ok", "warn": "warn", "off": "muted"}.get(ln["state"], "accent"), kind="value",
                       ref=ln["pid"])
                g.placed[ln["pid"]] = (ax, ay)
            else:
                d.text(x + CARD_PAD, ty, ln["name"], size=10, weight=600, fill="ghost", kind="ghost", ref=ln["role"])
                d.text(x + c["w"] - CARD_PAD, ty, ln["value"], size=10, anchor="end", fill="ghost", kind="ghost",
                       ref=ln["role"])
                g.ghosts.append(ln["role"])

    def xs(r: list[dict]) -> list[float]:
        """Each card centred over its anchor where it can be: pushed right past its left neighbour, then back left
        to fit the drawing."""
        out, cur = [], MARGIN
        for c in r:
            x = max(cur, c["pos"][0] + ox - c["w"] / 2)
            out.append(x)
            cur = x + c["w"] + CARD_GAP
        limit = width - MARGIN
        for i in range(len(r) - 1, -1, -1):
            out[i] = max(MARGIN, min(out[i], limit - r[i]["w"]))
            limit = out[i] - CARD_GAP
        return out

    y = oy - 10
    for r in above:  # nearest row first, going up
        y -= row_h(r) + ROW_GAP
        for c, x in zip(r, xs(r)):
            draw_card(c, x, y + (row_h(r) - c["h"]), "above")
    y = oy + ah + 10 + ROW_GAP
    for r in below:
        for c, x in zip(r, xs(r)):
            draw_card(c, x, y, "below")
        y += row_h(r) + ROW_GAP

    # footer: points on parts this variant doesn't draw, then points with no slot
    y = oy + ah + 10 + bot_h + 14
    if lost:
        d.text(MARGIN, y, "Bound to a part this drawing doesn't show:", size=11, weight=600, fill="bad", kind="footer")
        for c in lost:
            for ln in c["lines"]:
                y += 15
                ref = ln["pid"] or ln.get("role", "")
                d.text(MARGIN + 10, y, f"{ln['name']} → {c['part']}", size=10, fill="bad", kind="lost", ref=ref)
                if ln["pid"]:
                    g.unanchored.append(ln["pid"])
        y += 22
    if unplaced:
        d.text(MARGIN, y, f"Not on the drawing: {len(unplaced)} point{'s' * (len(unplaced) != 1)} with no slot "
                          "in the template", size=11, weight=600, fill="muted", kind="footer")
        for row in lines_un:
            y += 15
            for pid, t, x in row:
                d.text(x, y, t, size=10, fill="muted", kind="unplaced", ref=pid)
    return g
