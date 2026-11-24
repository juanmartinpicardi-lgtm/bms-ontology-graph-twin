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


# ---------------------------------------------------------------- sheet numbers in any style

# M-101 (Troop D), M201 and M.201 (MSU), M1.0 and M5.2 (ITD), FP-1, E-2.1: a discipline letter or two, then a number
SHEET_ANY = re.compile(r"^[A-Z]{1,2}[-.]?\d{1,3}(?:\.\d{1,2})?[A-Z]?$")


def sheet_id(ws) -> str:
    """The sheet number in the title block, in any of the usual styles (M-101, M201, M.201, M1.0): the largest text
    that looks like one. The strict M-101 style wins when the page has one (`sheet_number`, as before)."""
    if strict := sheet_number(ws):
        return strict
    cands = [w for w in ws if SHEET_ANY.match(w.text) and w.size >= 14]
    return max(cands, key=lambda w: (w.size, w.x0)).text if cands else ""


# ---------------------------------------------------------------- vision input (plan-workflow-ai §6.3)

@dataclass(frozen=True)
class PageImage:
    """A page rendered for a vision model, with the mapping back to `words` coordinates (PDF points from the page's
    top-left corner). A point (x, y) on the page is pixel ((x - crop[0]) * scale, (y - crop[1]) * scale)."""
    image: Image.Image
    dpi: float
    crop: tuple[float, float, float, float]  # the region shown, in PDF points

    @property
    def scale(self) -> float:
        return self.dpi / 72.0

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.crop[0]) * self.scale, (y - self.crop[1]) * self.scale

    def to_pt(self, px: float, py: float) -> tuple[float, float]:
        return px / self.scale + self.crop[0], py / self.scale + self.crop[1]

    def png(self) -> bytes:
        import io
        buf = io.BytesIO()
        self.image.save(buf, "PNG", optimize=True)
        return buf.getvalue()

    def block(self) -> dict:
        """The image as an Anthropic-shape content block (the Gemini provider converts it)."""
        import base64
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                            "data": base64.b64encode(self.png()).decode()}}


def page_image(path: Path, page: int, dpi: float = 72.0, crop: list[float] | None = None,
               labels: list[dict] | None = None, max_px: int = 3200, gray: bool = True) -> PageImage:
    """The page (or `crop` of it, PDF points) rendered at `dpi` (lowered so the longer side is at most `max_px`),
    optionally with candidate ids drawn on it: `labels` = [{"id": "R12", "bbox": [x0, top, x1, bottom],
    "color": "#hex"}], each a thin box with its id beside it, so a model can answer "R12" for what it sees there."""
    pw, ph = page_size(path, page)
    region = tuple(crop) if crop else (0.0, 0.0, pw, ph)
    w_pt, h_pt = region[2] - region[0], region[3] - region[1]
    dpi = min(dpi, max_px * 72.0 / max(w_pt, h_pt))
    scale = dpi / 72.0
    pdf_page = pdfium.PdfDocument(path)[page]
    full = pdf_page.render(scale=scale, grayscale=gray).to_pil().convert("RGB")
    img = full.crop([round(region[0] * scale), round(region[1] * scale), round(region[2] * scale),
                     round(region[3] * scale)])
    pim = PageImage(img, dpi, region)
    if labels:
        from PIL import ImageFont
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=max(9, round(7 * scale)))
        for lab in labels:
            x0, y0 = pim.to_px(lab["bbox"][0], lab["bbox"][1])
            x1, y1 = pim.to_px(lab["bbox"][2], lab["bbox"][3])
            color = _rgb(lab.get("color", "#D02020"))
            draw.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=color, width=1)
            tx, ty = x1 + 3, y0 - 2
            tw = draw.textlength(lab["id"], font=font)
            draw.rectangle([tx - 1, ty, tx + tw + 1, ty + font.size + 1], fill=(255, 255, 255))
            draw.text((tx, ty), lab["id"], fill=color, font=font)
    return pim
