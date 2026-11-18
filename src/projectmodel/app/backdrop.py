"""The page backdrop: a faint knowledge graph far behind the content.

Three depths of nodes and edges, the farthest smallest and dimmest, so the network reads as distance rather than
pattern. Generated once from a fixed seed (the same picture on every load) and drawn in one colour per theme, as an
SVG data URI the app's CSS puts on a fixed layer under everything.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from urllib.parse import quote

W, H = 1600, 1000
# (nodes, node radius, node opacity, edge width, edge opacity, neighbours per node): far, middle, near
LAYERS = [(70, 1.1, .35, .5, .10, 3), (34, 1.8, .45, .7, .13, 2), (14, 2.8, .55, .9, .16, 2)]


def _layer(rng: random.Random, n: int, r: float, op: float, ew: float, eop: float, k: int) -> str:
    # Denser towards the right and the top, where the page has the least content.
    pts = [(W * (1 - rng.random() ** 1.6), H * rng.random() ** 1.3) for _ in range(n)]
    edges = set()
    for i, (x, y) in enumerate(pts):
        near = sorted(range(n), key=lambda j: math.dist((x, y), pts[j]))[1:k + 1]
        edges.update(tuple(sorted((i, j))) for j in near)
    lines = "".join(f'<line x1="{pts[i][0]:.0f}" y1="{pts[i][1]:.0f}" x2="{pts[j][0]:.0f}" y2="{pts[j][1]:.0f}"/>'
                    for i, j in sorted(edges))
    dots = "".join(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r * (0.7 + rng.random() * 0.6):.1f}"/>' for x, y in pts)
    return (f'<g stroke-width="{ew}" stroke-opacity="{eop}">{lines}</g>'
            f'<g stroke="none" fill-opacity="{op}">{dots}</g>')


@lru_cache(maxsize=4)
def graph_backdrop(color: str) -> str:
    """The backdrop as a CSS url(...) in the given colour."""
    rng = random.Random(59)
    body = "".join(_layer(rng, *layer) for layer in LAYERS)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" '
           f'fill="{color}" stroke="{color}">{body}</svg>')
    return f'url("data:image/svg+xml,{quote(svg)}")'
