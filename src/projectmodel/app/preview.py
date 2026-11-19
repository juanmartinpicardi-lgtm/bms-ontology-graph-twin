"""A small picture of a project's digital building for the All projects cards: its levels as an exploded isometric
stack, each slab dotted with the equipment the twin places on it. Plain SVG, so a page of cards costs no 3D viewer.
The levels and the equipment per level come from the same payload the digital twin page draws (twin_view.py)."""

from __future__ import annotations

import html
import math

COS, SIN = math.cos(math.pi / 6), math.sin(math.pi / 6)
W, D, T, GAP = 150.0, 96.0, 5.0, 30.0  # slab width, depth, thickness, distance between levels (px)


def mix(a: str, b: str, share: float) -> str:
    """`share` of colour a over colour b (both #RRGGBB): the SVG is shown as an image, so no CSS color-mix."""
    ca, cb = (tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in (a, b))
    return "#" + "".join(f"{round(x * share + y * (1 - share)):02X}" for x, y in zip(ca, cb))


def _pt(u: float, v: float, z: float, ox: float, oy: float) -> str:
    return f"{ox + (u - v) * COS:.1f},{oy + (u + v) * SIN - z:.1f}"


def _poly(points: list[tuple[float, float, float]], ox: float, oy: float, fill: str, stroke: str,
          extra: str = "") -> str:
    pts = " ".join(_pt(u, v, z, ox, oy) for u, v, z in points)
    return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1" {extra}/>'


def building_svg(levels: list[dict], counts: dict[str, int], c: dict, ghost: bool = False) -> str:
    """`levels` bottom to top ({id, name, kind}); `counts` equipment per level id; `c` the app theme colours.
    `ghost`: a building still being set up, drawn as a dashed outline."""
    if not levels:
        levels, ghost = [{"id": f"L{i}", "name": f"Level {i}", "kind": "zones"} for i in (1, 2, 3)], True
    n = len(levels)
    ox = 30 + D * COS  # the slab's back-left corner (u=0, v=0) is the leftmost point at x = ox - D*COS
    top = (n - 1) * GAP + 14
    oy = top + 8
    width = ox + W * COS + 70
    height = oy + (W + D) * SIN + 14
    tone = {"plant": c["warn"], "roof": c["mute"], "zones": c["accent"]}
    dash = 'stroke-dasharray="4 3"' if ghost else ""
    out = [f'<svg viewBox="0 0 {width:.0f} {height:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Preview of the digital building">',
           f'<ellipse cx="{ox + (W - D) / 2 * COS:.1f}" cy="{oy + (W + D) / 2 * SIN + 6:.1f}" rx="{(W + D) * COS / 1.9:.1f}"'
           f' ry="{(W + D) * SIN / 2.6:.1f}" fill="{c["text"]}" opacity=".06"/>']
    for i, lv in enumerate(levels):
        z = i * GAP
        col = tone.get(lv.get("kind"), c["accent"])
        fill_top = "none" if ghost else mix(col, c["card"], .16)
        fill_side = "none" if ghost else mix(col, c["card"], .32)
        stroke = c["mute"] if ghost else mix(col, c["card"], .7)
        out.append(_poly([(W, 0, z), (W, D, z), (W, D, z - T), (W, 0, z - T)], ox, oy, fill_side, stroke, dash))
        out.append(_poly([(0, D, z), (W, D, z), (W, D, z - T), (0, D, z - T)], ox, oy, fill_side, stroke, dash))
        out.append(_poly([(0, 0, z), (W, 0, z), (W, D, z), (0, D, z)], ox, oy, fill_top, stroke,
                         dash or 'fill-opacity=".72"'))  # glass: the units below show through
        k = min(counts.get(lv["id"], 0), 40)
        if k and not ghost:  # the level's equipment as dots on a grid across the slab
            cols = min(k, 10)
            rows = math.ceil(k / cols)
            for j in range(k):
                u = W * (0.1 + 0.8 * ((j % cols) + 0.5) / cols)
                v = D * (0.15 + 0.7 * ((j // cols) + 0.5) / rows)
                x, y = _pt(u, v, z, ox, oy).split(",")
                out.append(f'<circle cx="{x}" cy="{y}" r="2.1" fill="{col}"/>')
        lx, ly = _pt(W, D * 0.0, z, ox, oy).split(",")
        label = html.escape(lv["id"]) + (f" · {counts.get(lv['id'], 0)}" if not ghost else "")
        out.append(f'<text x="{float(lx) + 8:.1f}" y="{float(ly) + 4:.1f}" font-size="10" font-weight="600" '
                   f'fill="{c["mute"]}" font-family="Helvetica, Arial, sans-serif">{label}</text>')
    out.append("</svg>")
    return "".join(out)
