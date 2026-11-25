"""A small vector drawing: shapes with ids, rendered to SVG (the app) and to PNG (the vision check).

Graphics are code and data, never pixels (plan §6.1 principle 4): every shape is placed by a builder, so the QA rules
can check what is where without looking at an image. Each shape may carry `ref` (what it stands for: a part, a point
id, an equipment id) and `kind` ("part", "label", "leader", "anchor", "unit"...), which both the SVG (as data-*
attributes) and the QA read.

Coordinates are drawing units (≈ px at scale 1), y down, origin top left.
"""

from __future__ import annotations

import html
import io
import math
from dataclasses import dataclass, field

# Colours per theme. Air and water follow the 3D viewer's conventions (outside green, return red, mixed amber,
# supply blue; chilled water blue, hot water red, condenser water teal).
PALETTES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#6b7178", "line": "#8a9097", "fill": "#eef0f3",
              "part": "#d9dde2", "card": "#ffffff", "card_line": "#c9ced4", "accent": "#1c6fd1",
              "ok": "#1f9d55", "warn": "#d98a1a", "bad": "#d23b2f", "off": "#8a9097", "ghost": "#8fb8e8",
              "outside": "#2f9e44", "return": "#d6493f", "mixed": "#d99a1a", "supply": "#2f80d8", "exhaust": "#b0533c",
              "chilled_water": "#2f80d8", "hot_water": "#d6493f", "condenser_water": "#2fb39c", "steam": "#9aa3ad",
              "refrigerant": "#7a5cc7", "gas": "#e0b23a", "electric": "#3a3e44", "room": "#f6f7f9",
              "room_line": "#d4d8dd"},
    "dark": {"bg": "#16181c", "ink": "#e8eaed", "muted": "#9aa1a9", "line": "#7d848c", "fill": "#23262b",
             "part": "#2e3238", "card": "#1d2025", "card_line": "#3a3f46", "accent": "#5aa2f0",
             "ok": "#3fcf7a", "warn": "#f2b134", "bad": "#f04438", "off": "#7d848c", "ghost": "#6f9fd8",
             "outside": "#4cc26a", "return": "#f06a5f", "mixed": "#f2b134", "supply": "#5aa2f0", "exhaust": "#e0866c",
             "chilled_water": "#5aa2f0", "hot_water": "#f06a5f", "condenser_water": "#45d0b6", "steam": "#b8c0c9",
             "refrigerant": "#a58cf0", "gas": "#f2c94c", "electric": "#c9ced4", "room": "#1d2025",
             "room_line": "#33383f"},
}
FONT = "Inter, 'Helvetica Neue', Arial, sans-serif"
CHAR_W = 0.56  # average glyph width / font size, for layout before rendering


def text_width(text: str, size: float) -> float:
    return len(text) * size * CHAR_W


@dataclass
class Shape:
    type: str                      # rect | line | poly | circle | text | path
    geo: dict                      # x, y, w, h / x1.. / pts / cx, cy, r / d (path, with its bbox in geo["bbox"])
    style: dict = field(default_factory=dict)  # stroke, fill (palette keys or #hex), width, dash, opacity, size, weight
    kind: str = ""
    ref: str = ""
    title: str = ""

    def bbox(self) -> tuple[float, float, float, float]:
        g = self.geo
        if self.type == "rect":
            return g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]
        if self.type == "line":
            return min(g["x1"], g["x2"]), min(g["y1"], g["y2"]), max(g["x1"], g["x2"]), max(g["y1"], g["y2"])
        if self.type == "poly":
            xs, ys = [p[0] for p in g["pts"]], [p[1] for p in g["pts"]]
            return min(xs), min(ys), max(xs), max(ys)
        if self.type == "circle":
            return g["cx"] - g["r"], g["cy"] - g["r"], g["cx"] + g["r"], g["cy"] + g["r"]
        if self.type == "text":
            size = self.style.get("size", 11)
            w = text_width(g["text"], size)
            x = g["x"] - (w / 2 if self.style.get("anchor") == "middle" else w if self.style.get("anchor") == "end" else 0)
            return x, g["y"] - size * 0.8, x + w, g["y"] + size * 0.25
        return tuple(g.get("bbox", (0, 0, 0, 0)))


class Drawing:
    def __init__(self, width: float, height: float, title: str = ""):
        self.width, self.height, self.title = width, height, title
        self.shapes: list[Shape] = []

    # --- primitives --------------------------------------------------------------------------------------------
    def add(self, s: Shape) -> Shape:
        self.shapes.append(s)
        return s

    def rect(self, x, y, w, h, *, rx=0, kind="", ref="", title="", **style) -> Shape:
        return self.add(Shape("rect", {"x": x, "y": y, "w": w, "h": h, "rx": rx}, style, kind, ref, title))

    def line(self, x1, y1, x2, y2, *, kind="", ref="", **style) -> Shape:
        return self.add(Shape("line", {"x1": x1, "y1": y1, "x2": x2, "y2": y2}, style, kind, ref))

    def poly(self, pts, *, closed=False, kind="", ref="", title="", **style) -> Shape:
        return self.add(Shape("poly", {"pts": [tuple(p) for p in pts], "closed": closed}, style, kind, ref, title))

    def circle(self, cx, cy, r, *, kind="", ref="", title="", **style) -> Shape:
        return self.add(Shape("circle", {"cx": cx, "cy": cy, "r": r}, style, kind, ref, title))

    def text(self, x, y, text, *, kind="", ref="", **style) -> Shape:
        return self.add(Shape("text", {"x": x, "y": y, "text": str(text)}, style, kind, ref))

    # --- queries -----------------------------------------------------------------------------------------------
    def of_kind(self, kind: str) -> list[Shape]:
        return [s for s in self.shapes if s.kind == kind]

    def bounds(self) -> tuple[float, float, float, float]:
        boxes = [s.bbox() for s in self.shapes] or [(0, 0, 0, 0)]
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    # --- rendering ---------------------------------------------------------------------------------------------
    def svg(self, theme: str = "light", *, max_width: str | None = "100%") -> str:
        P = PALETTES.get(theme, PALETTES["light"])
        col = lambda c: P.get(c, c) if c else "none"  # noqa: E731
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width:.0f} {self.height:.0f}" '
               f'width="{self.width:.0f}" height="{self.height:.0f}" '
               f'style="{f"max-width:{max_width};height:auto;" if max_width else ""}background:{P["bg"]};'
               f'font-family:{FONT}" role="img" aria-label="{html.escape(self.title)}">']
        if self.title:
            out.append(f"<title>{html.escape(self.title)}</title>")
        for s in self.shapes:
            st = s.style
            attrs = []
            if s.type != "text":
                attrs.append(f'stroke="{col(st.get("stroke", "line"))}"')
                attrs.append(f'stroke-width="{st.get("width", 1.5)}"')
                attrs.append(f'fill="{col(st.get("fill"))}"')
                if st.get("dash"):
                    attrs.append(f'stroke-dasharray="{st["dash"]}"')
                attrs.append('stroke-linejoin="round" stroke-linecap="round"')
            if st.get("opacity") is not None:
                attrs.append(f'opacity="{st["opacity"]}"')
            if s.kind:
                attrs.append(f'data-kind="{s.kind}"')
            if s.ref:
                attrs.append(f'data-ref="{html.escape(s.ref)}"')
            a = " ".join(attrs)
            tip = f"<title>{html.escape(s.title)}</title>" if s.title else ""
            g = s.geo
            if s.type == "rect":
                el = (f'<rect x="{g["x"]:.1f}" y="{g["y"]:.1f}" width="{g["w"]:.1f}" height="{g["h"]:.1f}" '
                      f'rx="{g.get("rx", 0)}" {a}>{tip}</rect>')
            elif s.type == "line":
                el = f'<line x1="{g["x1"]:.1f}" y1="{g["y1"]:.1f}" x2="{g["x2"]:.1f}" y2="{g["y2"]:.1f}" {a}/>'
            elif s.type == "poly":
                pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in g["pts"])
                tag = "polygon" if g.get("closed") else "polyline"
                el = f'<{tag} points="{pts}" {a}>{tip}</{tag}>'
            elif s.type == "circle":
                el = f'<circle cx="{g["cx"]:.1f}" cy="{g["cy"]:.1f}" r="{g["r"]:.1f}" {a}>{tip}</circle>'
            elif s.type == "text":
                anchor = st.get("anchor", "start")
                el = (f'<text x="{g["x"]:.1f}" y="{g["y"]:.1f}" font-size="{st.get("size", 11)}" '
                      f'font-weight="{st.get("weight", 400)}" fill="{col(st.get("fill", "ink"))}" '
                      f'text-anchor="{anchor}" {a}>{html.escape(g["text"])}</text>')
            else:
                el = ""
            out.append(el)
        out.append("</svg>")
        return "".join(out)

    def png(self, theme: str = "light", scale: float = 1.5) -> bytes:
        """The drawing as a PNG (PIL), for the vision check. Same shapes as the SVG; text in PIL's default font."""
        from PIL import Image, ImageDraw, ImageFont

        P = PALETTES.get(theme, PALETTES["light"])
        col = lambda c: P.get(c, c) if c and c != "none" else None  # noqa: E731
        img = Image.new("RGB", (max(1, round(self.width * scale)), max(1, round(self.height * scale))), P["bg"])
        d = ImageDraw.Draw(img)
        fonts: dict[int, ImageFont.ImageFont] = {}

        def font(size):
            px = max(8, round(size * scale))
            if px not in fonts:
                try:
                    fonts[px] = ImageFont.load_default(size=px)
                except TypeError:  # Pillow < 10.1
                    fonts[px] = ImageFont.load_default()
            return fonts[px]

        sc = lambda *v: [x * scale for x in v]  # noqa: E731
        for s in self.shapes:
            st, g = s.style, s.geo
            stroke, fill = col(st.get("stroke", "line")), col(st.get("fill"))
            w = max(1, round(st.get("width", 1.5) * scale))
            if s.type == "rect":
                box = sc(g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"])
                if box[2] - box[0] < 1 or box[3] - box[1] < 1:
                    continue
                d.rounded_rectangle(box, radius=g.get("rx", 0) * scale, fill=fill, outline=stroke, width=w)
            elif s.type == "line":
                d.line(sc(g["x1"], g["y1"], g["x2"], g["y2"]), fill=stroke, width=w)
            elif s.type == "poly":
                pts = [tuple(sc(x, y)) for x, y in g["pts"]]
                if g.get("closed"):
                    d.polygon(pts, fill=fill, outline=stroke, width=w)
                else:
                    d.line(pts, fill=stroke, width=w, joint="curve")
            elif s.type == "circle":
                cx, cy, r = sc(g["cx"], g["cy"], g["r"])
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=stroke, width=w)
            elif s.type == "text":
                f = font(st.get("size", 11))
                x, y = sc(g["x"], g["y"])
                anchor = {"middle": "ms", "end": "rs"}.get(st.get("anchor"), "ls")
                d.text((x, y), g["text"].replace("₂", "2"), fill=col(st.get("fill", "ink")), font=f, anchor=anchor)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


def img_tag(svg: str, alt: str = "", style: str = "max-width:100%;height:auto") -> str:
    """The SVG as an <img> (a data URI): Streamlit's st.html sanitises inline SVG away, an image it keeps."""
    import base64

    data = base64.b64encode(svg.encode()).decode()
    return f'<img src="data:image/svg+xml;base64,{data}" alt="{html.escape(alt)}" style="{style}">'


def along(pts: list[tuple[float, float]], at: float) -> tuple[float, float, float]:
    """Point and direction angle (radians) at `at` (0-1) along a polyline."""
    lens = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    s = max(0.0, min(1.0, at)) * sum(lens)
    for i, L in enumerate(lens):
        if s <= L or i == len(lens) - 1:
            t = 0 if L == 0 else min(1.0, s / L)
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, math.atan2(y1 - y0, x1 - x0)
        s -= L
    return pts[-1][0], pts[-1][1], 0.0
