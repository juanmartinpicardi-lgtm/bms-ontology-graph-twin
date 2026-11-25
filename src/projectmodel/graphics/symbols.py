"""2D symbols in the style integrators deliver (flat, schematic, one colour per medium), each registering the part it
draws so point labels can sit on it. Part names are those of `knowledge_model/templates/anchors.yaml`.

A `Sheet` wraps a Drawing with the parts drawn so far: `parts[name]` is the part's box, `paths[name]` the polyline of
a duct or pipe (for anchors with `at`, a fraction along it).
"""

from __future__ import annotations

import math

from .drawing import Drawing, along

AIR_W, PIPE_W = 24, 5


class Sheet:
    def __init__(self, d: Drawing):
        self.d = d
        self.parts: dict[str, tuple[float, float, float, float]] = {}
        self.paths: dict[str, list[tuple[float, float]]] = {}

    def mark(self, name: str | None, x0, y0, x1, y1) -> None:
        if name:
            self.parts[name] = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def anchor(self, part: str, at: float | None = None) -> tuple[float, float] | None:
        """Where a label's leader ends: along a path at `at`, else the part's centre; a sub-part not drawn falls back
        to its parent ("cooling_coil.valve" -> "cooling_coil"). None when neither is drawn."""
        if part in self.paths and at is not None:
            x, y, _ = along(self.paths[part], at)
            return x, y
        for name in (part, part.split(".")[0], part.split("@")[0]):
            if name in self.parts:
                x0, y0, x1, y1 = self.parts[name]
                return (x0 + x1) / 2, (y0 + y1) / 2
            if name in self.paths:
                x, y, _ = along(self.paths[name], 0.5)
                return x, y
        return None


# --- runs ------------------------------------------------------------------------------------------------------

def chevrons(sh: Sheet, pts, color: str, every: float = 70, size: float = 6) -> None:
    L = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    n = max(1, int(L // every))
    for i in range(n):
        x, y, a = along(pts, (i + 0.5) / n)
        c, s = math.cos(a), math.sin(a)
        tip = (x + c * size, y + s * size)
        back = [(x - c * size + -s * size, y - s * size + c * size), (x - c * size - -s * size, y - s * size - c * size)]
        sh.d.poly([back[0], tip, back[1]], stroke=color, width=2, kind="flow")


def duct(sh: Sheet, name: str | None, pts, air: str = "supply", w: float = AIR_W, arrows: bool = True) -> None:
    sh.d.poly(pts, stroke="line", width=w + 3, kind="part", ref=name or "")
    sh.d.poly(pts, stroke="fill", width=w, kind="part", ref=name or "")
    if arrows:
        chevrons(sh, pts, air)
    if name:
        sh.paths[name] = list(pts)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        sh.mark(name, min(xs) - w / 2, min(ys) - w / 2, max(xs) + w / 2, max(ys) + w / 2)


def pipe(sh: Sheet, name: str | None, pts, medium: str, w: float = PIPE_W, arrows: bool = True) -> None:
    sh.d.poly(pts, stroke=medium, width=w, kind="part", ref=name or "")
    if arrows:
        chevrons(sh, pts, medium, every=90, size=5)
    if name:
        sh.paths[name] = list(pts)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        sh.mark(name, min(xs) - w, min(ys) - w, max(xs) + w, max(ys) + w)


# --- parts ------------------------------------------------------------------------------------------------------

def block(sh: Sheet, name: str | None, x, y, w, h, text: str = "", fill: str = "part", dash: str | None = None,
          size: float = 10) -> None:
    sh.d.rect(x, y, w, h, rx=4, fill=fill, stroke="line", width=1.5, dash=dash, kind="part", ref=name or "")
    if text:
        sh.d.text(x + w / 2, y + h / 2 + size * 0.35, text, anchor="middle", size=size, fill="muted", kind="part_text")
    sh.mark(name, x, y, x + w, y + h)


def casing(sh: Sheet, name: str, x, y, w, h) -> None:
    sh.d.rect(x, y, w, h, rx=6, fill="none", stroke="line", width=2.5, kind="part", ref=name)
    sh.mark(name, x, y, x + w, y + h)


def damper(sh: Sheet, name: str | None, cx, cy, w=16, h=50, vertical: bool = True) -> None:
    """Opposed-blade damper across an air path: a frame with blades drawn as short diagonals."""
    if not vertical:
        w, h = h, w
    sh.d.rect(cx - w / 2, cy - h / 2, w, h, fill="bg", stroke="ink", width=1.5, kind="part", ref=name or "")
    n = 3
    for i in range(n):
        if vertical:
            yy = cy - h / 2 + (i + 0.5) * h / n
            sh.d.line(cx - w / 2 + 2, yy + (4 if i % 2 else -4), cx + w / 2 - 2, yy - (4 if i % 2 else -4), stroke="ink", width=1.5)
        else:
            xx = cx - w / 2 + (i + 0.5) * w / n
            sh.d.line(xx + (4 if i % 2 else -4), cy - h / 2 + 2, xx - (4 if i % 2 else -4), cy + h / 2 - 2, stroke="ink", width=1.5)
    sh.mark(name, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def butterfly(sh: Sheet, name: str, cx, cy, r=13) -> None:
    sh.d.circle(cx, cy, r, fill="bg", stroke="ink", width=1.5, kind="part", ref=name)
    sh.d.line(cx - r * 0.7, cy + r * 0.7, cx + r * 0.7, cy - r * 0.7, stroke="ink", width=2)
    sh.mark(name, cx - r, cy - r, cx + r, cy + r)


def flow_cross(sh: Sheet, name: str, cx, cy, r=12) -> None:
    sh.d.line(cx - r, cy, cx + r, cy, stroke="ink", width=1.5, kind="part", ref=name)
    sh.d.line(cx, cy - r, cx, cy + r, stroke="ink", width=1.5, kind="part", ref=name)
    sh.d.circle(cx, cy, 3, fill="ink", stroke="ink", width=1)
    sh.mark(name, cx - r, cy - r, cx + r, cy + r)


def filt(sh: Sheet, name: str, x, y, w=22, h=60) -> None:
    sh.d.rect(x, y, w, h, fill="bg", stroke="ink", width=1.5, kind="part", ref=name)
    n, pts = 6, []
    for i in range(n * 2 + 1):
        pts.append((x + (3 if i % 2 == 0 else w - 3), y + 2 + i * (h - 4) / (n * 2)))
    sh.d.poly(pts, stroke="muted", width=1.2)
    sh.mark(name, x, y, x + w, y + h)


def coil(sh: Sheet, name: str, x, y, w=24, h=60, medium: str = "chilled_water") -> None:
    sh.d.rect(x, y, w, h, fill="bg", stroke=medium, width=2, kind="part", ref=name)
    for i in range(6):
        y0 = y + 4 + i * (h - 8) / 6
        sh.d.line(x + 3, y0 + (h - 8) / 6, x + w - 3, y0, stroke=medium, width=1.2)
    sh.mark(name, x, y, x + w, y + h)


def heater(sh: Sheet, name: str, x, y, w=24, h=60) -> None:
    """Electric heating element: a box with a zigzag resistor."""
    sh.d.rect(x, y, w, h, fill="bg", stroke="hot_water", width=2, kind="part", ref=name)
    n, pts = 5, []
    for i in range(n * 2 + 1):
        pts.append((x + w / 2 + (-w / 2 + 5 if i % 2 else w / 2 - 5) * (0 if i in (0, n * 2) else 1), y + 4 + i * (h - 8) / (n * 2)))
    sh.d.poly(pts, stroke="hot_water", width=1.6)
    sh.mark(name, x, y, x + w, y + h)


def fan(sh: Sheet, name: str, cx, cy, r=22, facing: float = 0.0) -> None:
    """Centrifugal fan: housing circle with an outlet tangent, wheel with blades."""
    a = facing
    c, s = math.cos(a), math.sin(a)
    sh.d.poly([(cx - s * r, cy + c * r), (cx - s * r + c * r * 1.1, cy + c * r + s * r * 1.1),
               (cx + s * r * 0.2 + c * r * 1.1, cy - c * r * 0.2 + s * r * 1.1)], closed=True, fill="part", stroke="ink",
              width=1.5, kind="part", ref=name)
    sh.d.circle(cx, cy, r, fill="part", stroke="ink", width=1.8, kind="part", ref=name)
    for i in range(3):
        b = i * 2 * math.pi / 3 + 0.4
        sh.d.poly([(cx, cy), (cx + math.cos(b) * r * 0.8, cy + math.sin(b) * r * 0.8),
                   (cx + math.cos(b + 0.5) * r * 0.55, cy + math.sin(b + 0.5) * r * 0.55)], closed=True, fill="ink", stroke="ink", width=1)
    sh.mark(name, cx - r, cy - r, cx + r, cy + r)


def prop_fan(sh: Sheet, name: str, cx, cy, r=18) -> None:
    """Propeller / axial fan seen from the side: a circle with two blades."""
    sh.d.circle(cx, cy, r, fill="bg", stroke="ink", width=1.8, kind="part", ref=name)
    sh.d.poly([(cx - r * 0.8, cy - r * 0.25), (cx + r * 0.8, cy + r * 0.25)], stroke="ink", width=4)
    sh.d.poly([(cx - r * 0.25, cy + r * 0.8), (cx + r * 0.25, cy - r * 0.8)], stroke="ink", width=4)
    sh.mark(name, cx - r, cy - r, cx + r, cy + r)


def valve(sh: Sheet, name: str, cx, cy, s=9, medium: str = "chilled_water", vertical: bool = False) -> None:
    """Two-way valve (bow tie) with its actuator on a stem."""
    if vertical:
        sh.d.poly([(cx - s, cy - s), (cx + s, cy - s), (cx - s, cy + s), (cx + s, cy + s)], closed=True, fill="bg",
                  stroke=medium, width=1.8, kind="part", ref=name)
    else:
        sh.d.poly([(cx - s, cy - s), (cx + s, cy + s), (cx + s, cy - s), (cx - s, cy + s)], closed=True, fill="bg",
                  stroke=medium, width=1.8, kind="part", ref=name)
    sh.d.line(cx, cy, cx, cy - s - 7, stroke="ink", width=1.5)
    sh.d.rect(cx - 7, cy - s - 16, 14, 9, rx=2, fill="ink", stroke="ink", width=1)
    sh.mark(name, cx - s, cy - s - 16, cx + s, cy + s)


def pump(sh: Sheet, name: str, cx, cy, r=16) -> None:
    sh.d.circle(cx, cy, r, fill="bg", stroke="ink", width=1.8, kind="part", ref=name)
    sh.d.poly([(cx - r * 0.55, cy - r * 0.6), (cx + r * 0.75, cy), (cx - r * 0.55, cy + r * 0.6)], closed=True,
              fill="ink", stroke="ink", width=1)
    sh.mark(name, cx - r, cy - r, cx + r, cy + r)


def compressor(sh: Sheet, name: str, cx, cy, w=36, h=30) -> None:
    sh.d.poly([(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 4), (cx + w / 2, cy + h / 4), (cx - w / 2, cy + h / 2)],
              closed=True, fill="part", stroke="ink", width=1.8, kind="part", ref=name)
    sh.mark(name, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def louvers(sh: Sheet, name: str, x, y, w=14, h=50) -> None:
    sh.d.rect(x, y, w, h, fill="bg", stroke="ink", width=1.5, kind="part", ref=name)
    for i in range(4):
        yy = y + 6 + i * (h - 12) / 3
        sh.d.line(x + 2, yy - 4, x + w - 2, yy + 4, stroke="ink", width=1.5)
    sh.mark(name, x, y, x + w, y + h)


def sensor_box(sh: Sheet, name: str, x, y, text="T", w=26, h=30) -> None:
    """Wall sensor / thermostat."""
    sh.d.rect(x, y, w, h, rx=4, fill="bg", stroke="ink", width=1.5, kind="part", ref=name)
    sh.d.text(x + w / 2, y + h / 2 + 4, text, anchor="middle", size=11, weight=600, fill="ink")
    sh.mark(name, x, y, x + w, y + h)


def wall(sh: Sheet, x, y0, y1) -> None:
    sh.d.rect(x - 3, y0, 6, y1 - y0, fill="room_line", stroke="room_line", width=1, kind="context")


def device(sh: Sheet, name: str, x, y, text: str, w=40, h=24) -> None:
    """Controls hardware: VFD, DDC controller, SCR, gateway, starter."""
    sh.d.rect(x, y, w, h, rx=3, fill="card", stroke="ink", width=1.4, kind="part", ref=name)
    sh.d.text(x + w / 2, y + h / 2 + 3.5, text, anchor="middle", size=9, weight=600, fill="ink")
    sh.mark(name, x, y, x + w, y + h)


def caption(sh: Sheet, x, y, text: str, anchor: str = "middle", fill: str = "muted", size: float = 10) -> None:
    sh.d.text(x, y, text, anchor=anchor, size=size, fill=fill, kind="caption")
