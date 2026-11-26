"""Read any common file into what a reader (rules or a model) can use: its text, and its images.

    read(name, data) -> Content(kind, text, images, pages, note)

PDF (text layer, and page images when it has none), Word, PowerPoint and Excel (their XML, no extra library), OpenDocument
text, CSV/TSV, plain text, Markdown, JSON, YAML, XML, Haystack Zinc, Turtle, email (.eml), and images (sent to a model
as they are). What cannot be read here (CAD, BIM models, Niagara .bog, old binary Office files) says so in `note`.

`for_step(name, data, types)` turns a file into the type a guided-setup step reads: an image into a one-page PDF for the
drawing steps, a spreadsheet into CSV for the BMS step.
"""
from __future__ import annotations

import csv
import email
import email.policy
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

TEXT_EXT = {"txt", "md", "json", "yaml", "yml", "zinc", "ttl", "xml", "csv", "tsv", "log", "ini", "cfg", "html", "htm"}
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff"}
OFFICE = {"docx", "pptx", "xlsx", "odt"}
UNREADABLE = {"dwg": "a CAD drawing", "dxf": "a CAD drawing", "rvt": "a Revit model", "ifc": "a BIM model",
              "bog": "a Niagara station", "doc": "an old Word file (save it as .docx)",
              "xls": "an old Excel file (save it as .xlsx)", "ppt": "an old PowerPoint file (save it as .pptx)",
              "msg": "an Outlook message (save it as .eml)", "zip": "an archive (unzip it first)"}
# Every type the app accepts for upload where "any file" is allowed.
ACCEPTED = sorted(TEXT_EXT | IMAGE_EXT | OFFICE | {"pdf", "eml"} | set(UNREADABLE))
MAX_TEXT = 200_000


@dataclass
class Content:
    kind: str                                       # pdf, word, excel, powerpoint, text, table, email, image, ...
    text: str = ""
    images: list[tuple[str, bytes]] = field(default_factory=list)  # (media type, bytes)
    pages: int = 0
    note: str = ""

    @property
    def readable(self) -> bool:
        return bool(self.text.strip() or self.images)


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def read(name: str, data: bytes) -> Content:
    ext = ext_of(name)
    try:
        if ext == "pdf":
            return _pdf(data)
        if ext == "docx":
            return Content("word", _xml_text(data, ["word/document.xml"], para="p"))
        if ext == "odt":
            return Content("text document", _xml_text(data, ["content.xml"], para="p"))
        if ext == "pptx":
            return _pptx(data)
        if ext == "xlsx":
            return Content("excel", _xlsx_csv(data, all_sheets=True))
        if ext == "eml":
            return _eml(data)
        if ext in IMAGE_EXT:
            return _image(data, ext)
        if ext in ("csv", "tsv"):
            return Content("table", _decode(data))
        if ext in TEXT_EXT or not ext:
            text = _decode(data)
            if ext in ("html", "htm"):
                text = re.sub(r"<[^>]+>", " ", text)
            return Content("text", text)
        if ext in UNREADABLE:
            return Content(ext, note=f"This is {UNREADABLE[ext]}: it is kept, but its content cannot be read here yet.")
        text = _decode(data)
        if text and sum(c.isprintable() or c.isspace() for c in text[:2000]) > 0.95 * len(text[:2000]):
            return Content("text", text)
        return Content(ext or "file", note=f"A .{ext} file: kept, but its content cannot be read here yet.")
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, OSError) as e:
        return Content(ext or "file", note=f"Could not read this file: {e}")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = data.decode(enc)
            if enc != "utf-16" or text.count("\x00") == 0:
                return text[:MAX_TEXT]
        except UnicodeDecodeError:
            continue
    return ""


def _pdf(data: bytes) -> Content:
    import pdfplumber
    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages[:60]):
            t = page.extract_text() or ""
            if t.strip():
                parts.append(f"--- page {i + 1} ---\n{t}")
    text = "\n".join(parts)[:MAX_TEXT]
    images = []
    if len(text.strip()) < 40:  # a scan: the first pages as images, for a model that reads them
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(data)
        for i in range(min(3, len(doc))):
            buf = io.BytesIO()
            doc[i].render(scale=1.4).to_pil().convert("RGB").save(buf, "JPEG", quality=80)
            images.append(("image/jpeg", buf.getvalue()))
    return Content("pdf", text, images, n, "" if text.strip() else "No text layer: a scan. Its first pages are read "
                                                                     "as images.")


def _xml_text(data: bytes, parts: list[str], para: str) -> str:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for part in parts:
            root = ET.fromstring(z.read(part))
            for p in root.iter():
                if p.tag.rsplit("}", 1)[-1] == para:
                    line = "".join(p.itertext())
                    if line.strip():
                        out.append(line)
    return "\n".join(out)[:MAX_TEXT]


def _pptx(data: bytes) -> Content:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
    parts = [f"--- slide {i + 1} ---\n" + _xml_text(data, [s], para="p") for i, s in enumerate(slides)]
    return Content("powerpoint", "\n".join(parts)[:MAX_TEXT], pages=len(slides))


def _xlsx_rows(data: bytes) -> dict[str, list[list[str]]]:
    """Every sheet's rows as text cells, read from the workbook's XML."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        book = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        sheets = {}
        for s in book.find("m:sheets", ns):
            path = target[s.get(f"{{{ns['r']}}}id")].lstrip("/")
            path = path if path.startswith("xl/") else f"xl/{path}"
            rows = []
            for row in ET.fromstring(z.read(path)).iter(f"{{{ns['m']}}}row"):
                cells: dict[int, str] = {}
                for c in row.findall("m:c", ns):
                    col = _col(c.get("r", "A1"))
                    v = c.find("m:v", ns)
                    t = c.get("t")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
                    else:
                        val = v.text if v is not None else ""
                    cells[col] = val or ""
                if cells:
                    rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
            sheets[s.get("name")] = rows
    return sheets


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _rows_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def _xlsx_csv(data: bytes, all_sheets: bool) -> str:
    sheets = _xlsx_rows(data)
    if not all_sheets:
        return _rows_csv(next(iter(sheets.values()), []))
    return "\n".join(f"--- sheet {name} ---\n{_rows_csv(rows)}" for name, rows in sheets.items())[:MAX_TEXT]


def _eml(data: bytes) -> Content:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    head = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Date", "Subject") if msg[h])
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body and body.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return Content("email", f"{head}\n\n{text}"[:MAX_TEXT])


def _image(data: bytes, ext: str) -> Content:
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.thumbnail((1600, 1600))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=85)
    return Content("image", images=[("image/jpeg", buf.getvalue())], pages=1)


# ---------------------------------------------------------------- converting for a guided-setup step

class NotForThisStep(ValueError):
    pass


def for_step(name: str, data: bytes, types: tuple[str, ...]) -> tuple[str, bytes]:
    """The file in a type the step reads, converted when it can be: images to a one-page PDF (drawing steps), Excel or
    TSV to CSV (BMS step). Raises NotForThisStep with the reason otherwise."""
    ext = ext_of(name)
    stem = Path(name).stem
    if ext in types:
        return name, data
    if "pdf" in types and ext in IMAGE_EXT:
        from PIL import Image
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).convert("RGB").save(buf, "PDF", resolution=150)
        return f"{stem}.pdf", buf.getvalue()
    if "csv" in types and ext == "xlsx":
        return f"{stem}.csv", _xlsx_csv(data, all_sheets=False).encode()
    if "csv" in types and ext == "tsv":
        rows = list(csv.reader(io.StringIO(_decode(data)), delimiter="\t"))
        return f"{stem}.csv", _rows_csv(rows).encode()
    want = " or ".join(t.upper() for t in types)
    hint = {"pdf": " Images are turned into a PDF page.", "csv": " Excel (.xlsx) and TSV files are turned into CSV."}
    raise NotForThisStep(f"{name}: this step reads {want}.{''.join(hint[t] for t in types if t in hint)}")


def step_types(types: tuple[str, ...]) -> list[str]:
    """What a step's uploader accepts: its own types and what for_step converts into them."""
    out = set(types)
    if "pdf" in types:
        out |= IMAGE_EXT
    if "csv" in types:
        out |= {"xlsx", "tsv"}
    return sorted(out)
