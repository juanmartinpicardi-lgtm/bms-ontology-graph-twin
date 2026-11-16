"""The drawing itself, taken out of a plan page as vectors: every stroked line, rectangle and curve inside the plan
area, and every word. The 3D building draws these instead of a picture of the page, so the plan stays sharp at any
zoom.

Coordinates are fractions of the plan area (0..1 across, 0..1 down), packed small:
    seg   int16 x0, y0, x1, y1 per segment (0..32767), base64
    wt    uint8 per segment: line weight class 0..3 (thin .. wall), base64
    words [text, x, y, height] with x, y the word's centre and height as a fraction of the plan height

A scanned page has no vectors: `image` then holds a high-resolution picture of the plan area instead.
"""
from __future__ import annotations

import base64
import io
from array import array
from pathlib import Path

import pdfplumber

from . import pdfdoc

MIN_VECTORS = 400  # fewer segments than this: the page is a scan, use the picture


def _weight(lw: float) -> int:
    return 0 if lw < 0.4 else 1 if lw < 0.8 else 2 if lw < 1.1 else 3


def plan(path: Path, page: int, crop: list[float]) -> dict:
    x0, y0, x1, y1 = crop
    w, h = x1 - x0, y1 - y0
    seg, wt = array("h"), array("B")

    def q(v: float) -> int:
        return max(0, min(32767, round(v * 32767)))

    def add(a, b, weight: int) -> None:
        ax, ay, bx, by = (a[0] - x0) / w, (a[1] - y0) / h, (b[0] - x0) / w, (b[1] - y0) / h
        if min(ax, ay, bx, by) < -0.002 or max(ax, ay, bx, by) > 1.002:
            return
        p = (q(ax), q(ay), q(bx), q(by))
        if p[0] == p[2] and p[1] == p[3]:
            return
        seg.extend(p)
        wt.append(weight)

    with pdfplumber.open(path) as pdf:
        pg = pdf.pages[page]
        for o in pg.lines + pg.curves + pg.rects:
            pts = o.get("pts") or []
            if len(pts) < 2:
                continue
            weight = _weight(float(o.get("linewidth") or 0))
            closed = o["object_type"] == "rect" or (o.get("fill") and not o.get("stroke"))
            if o["object_type"] == "rect" and not o.get("stroke"):
                continue  # a filled patch, not line work
            for a, b in zip(pts, pts[1:]):
                add(a, b, weight)
            if closed and len(pts) > 2:
                add(pts[-1], pts[0], weight)
    words = [[wd.text, round((wd.cx - x0) / w, 4), round((wd.cy - y0) / h, 4), round(wd.size / h, 5)]
             for wd in pdfdoc.words(path, page) if x0 <= wd.cx <= x1 and y0 <= wd.cy <= y1]
    out = {"n": len(wt), "seg": base64.b64encode(seg.tobytes()).decode(), "wt": base64.b64encode(wt.tobytes()).decode(),
           "words": words, "image": ""}
    if len(wt) < MIN_VECTORS:
        buf = io.BytesIO()
        pdfdoc.render(path, page, width=3200, crop=crop).convert("L").save(buf, "PNG", optimize=True)
        out["image"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return out
