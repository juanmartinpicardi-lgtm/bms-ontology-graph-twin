"""PDF pages as words with positions, lines, and images with highlighted boxes.

Coordinates are PDF points from the page's top-left corner (pdfplumber's x0, top, x1, bottom), the same for the
extractors and the viewer, so a fact's bbox can be drawn on the page it came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

SHEET = re.compile(r"^[A-Z]{1,2}-\d{3}(?:\.\d)?$")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    font: str
    size: float

    @property
    def bold(self) -> bool:
        return "bold" in self.font.lower()

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def bbox(self) -> list[float]:
        return [round(self.x0, 1), round(self.top, 1), round(self.x1, 1), round(self.bottom, 1)]


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self) -> list[float]:
        return [round(min(w.x0 for w in self.words), 1), round(min(w.top for w in self.words), 1),
                round(max(w.x1 for w in self.words), 1), round(max(w.bottom for w in self.words), 1)]


def page_count(path: Path) -> int:
    return len(pdfium.PdfDocument(path))


def page_size(path: Path, page: int) -> tuple[float, float]:
    w, h = pdfium.PdfDocument(path)[page].get_size()
    return w, h


@lru_cache(maxsize=64)
def words(path: Path, page: int) -> tuple[Word, ...]:
    with pdfplumber.open(path) as pdf:
        p = pdf.pages[page]
        raw = p.extract_words(extra_attrs=["fontname", "size"], use_text_flow=False)
    return tuple(Word(w["text"], w["x0"], w["top"], w["x1"], w["bottom"], w["fontname"].split("+")[-1],
                      round(w["size"], 1)) for w in raw)


def lines(ws: tuple[Word, ...] | list[Word], tol: float = 2.5, gap: float = 40) -> list[Line]:
    """Words on one baseline, split where the horizontal gap is wide (columns of a drawing are far apart)."""
    out: list[Line] = []
    for row in _rows(ws, tol):
        row.sort(key=lambda w: w.x0)
        cur = [row[0]]
        for w in row[1:]:
            if w.x0 - cur[-1].x1 > gap:
                out.append(Line(tuple(cur)))
                cur = [w]
            else:
                cur.append(w)
        out.append(Line(tuple(cur)))
    return out


def _rows(ws, tol):
    rows: list[list[Word]] = []
    for w in sorted(ws, key=lambda w: (w.top, w.x0)):
        if rows and abs(rows[-1][0].top - w.top) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def text(path: Path, page: int) -> str:
    return "\n".join(l.text for l in lines(words(path, page), gap=12))


def sheet_number(ws) -> str:
    """The sheet number in the title block: the largest text that looks like M-101."""
    cands = [w for w in ws if SHEET.match(w.text)]
    return max(cands, key=lambda w: (w.size, w.x0)).text if cands else ""


@lru_cache(maxsize=32)
def _render(path: Path, page: int, scale: float) -> Image.Image:
    return pdfium.PdfDocument(path)[page].render(scale=scale).to_pil().convert("RGB")


def render(path: Path, page: int, width: int = 1400, boxes: list[dict] | None = None,
           crop: list[float] | None = None) -> Image.Image:
    """The page as an image `width` pixels wide, optionally cropped to `crop` (PDF points), with `boxes` drawn:
    each {"bbox": [x0, top, x1, bottom], "color": "#hex", "width": px, "fill": bool}."""
    pw, ph = page_size(path, page)
    region = crop or [0, 0, pw, ph]
    scale = width / (region[2] - region[0])
    img = _render(path, page, round(min(scale, 4.0), 3)).copy()
    s = img.width / pw
    if crop:
        img = img.crop([int(v * s) for v in crop])
    if boxes:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        ox, oy = (crop[0], crop[1]) if crop else (0, 0)
        for b in boxes:
            x0, y0, x1, y1 = [(b["bbox"][i] - (ox if i % 2 == 0 else oy)) * s for i in range(4)]
            pad = b.get("pad", 3)
            rect = [x0 - pad, y0 - pad, x1 + pad, y1 + pad]
            color = _rgb(b.get("color", "#4DA3E8"))
            if b.get("fill"):
                draw.rectangle(rect, fill=color + (60,))
            draw.rectangle(rect, outline=color + (255,), width=b.get("width", 2))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    if img.width != width:
        img = img.resize((width, round(img.height * width / img.width)))
    return img


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
