"""A project's documents: every file the project knows about, in one list with a category, for the Documentation page.

Three origins, one list:
    setup    the files the guided setup read (data/intake/<site>/uploads/<step>/): plans, schedules, sequences, the
             controls submittal, the BMS export. Their category is the step that read them. Replacing or deleting one
             reads that step again and re-publishes it, so the knowledge graph follows.
    library  files added on the Documentation page (data/library/<site>/files/), with a category picked by the person
             or guessed from the name. They are kept and shown; the readers do not read them (yet).
    source   the raw source data a Haystack site was mapped from (data/raw/haystack/<site>.*) and its documents
             (data/documents/<site>/). Read-only: the app never changes the raw source files.

Nothing here writes to a source system. Write-back to a source tool happens only when the user asks, with a
preview, a confirm and a log of every write (CLAUDE.md §8).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "data/library"
RAW = ROOT / "data/raw"
DOCUMENTS = ROOT / "data/documents"

# In the order the page shows them: the guided setup's five, then what else a building project collects.
CATEGORIES = {
    "Floor plans": "map",
    "Equipment schedules": "table_view",
    "Sequences of operation": "sync_alt",
    "Controls submittal": "description",
    "BMS export": "dns",
    "Source data": "database",
    "Specifications": "menu_book",
    "Points lists": "list_alt",
    "Manuals and datasheets": "build",
    "Photos and site": "photo_camera",
    "Reports": "assessment",
    "Contracts and correspondence": "mail",
    "Other": "draft",
}
STEP_CATEGORY = {"plans": "Floor plans", "schedules": "Equipment schedules", "sequences": "Sequences of operation",
                 "submittal": "Controls submittal", "bms": "BMS export"}

# Guessing a category from a file's name and type: the first rule that matches wins.
_GUESS = [
    (r"floor.?plan|\bplans?\b|\bM-?1\d\d\b|layout", "Floor plans"),
    (r"schedule", "Equipment schedules"),
    (r"sequence|\bsoo\b|control.?logic", "Sequences of operation"),
    (r"submittal|riser", "Controls submittal"),
    (r"points?.?list|point.?schedule|io.?list", "Points lists"),
    (r"\bbms\b|\bbas\b|export|niagara|station|\.bog$|trend", "BMS export"),
    (r"spec|project.?manual|division|23.?09", "Specifications"),
    (r"manual|datasheet|data.?sheet|o&m|cut.?sheet|catalog|iom", "Manuals and datasheets"),
    (r"photo|site.?visit|\.(jpe?g|png|heic|webp|gif|tiff?)$", "Photos and site"),
    (r"report|commissioning|\bcx\b|test.?and.?balance|tab.?report|audit", "Reports"),
    (r"contract|rfi|letter|memo|minutes|\.(eml|msg)$", "Contracts and correspondence"),
    (r"\.(csv|xlsx?|tsv)$", "Points lists"),
]

KIND = {  # extension -> (what it is, Material icon)
    "pdf": ("PDF", "picture_as_pdf"), "csv": ("CSV table", "table"), "tsv": ("Table", "table"),
    "xlsx": ("Excel workbook", "grid_on"), "xls": ("Excel workbook", "grid_on"),
    "docx": ("Word document", "article"), "doc": ("Word document", "article"),
    "pptx": ("PowerPoint", "slideshow"), "txt": ("Text", "notes"), "md": ("Markdown", "notes"),
    "json": ("JSON", "data_object"), "yaml": ("YAML", "data_object"), "yml": ("YAML", "data_object"),
    "zinc": ("Haystack Zinc", "data_object"), "ttl": ("RDF Turtle", "hub"), "xml": ("XML", "code"),
    "png": ("Image", "image"), "jpg": ("Image", "image"), "jpeg": ("Image", "image"), "gif": ("Image", "image"),
    "webp": ("Image", "image"), "heic": ("Image", "image"), "tif": ("Image", "image"), "tiff": ("Image", "image"),
    "dwg": ("CAD drawing", "architecture"), "dxf": ("CAD drawing", "architecture"), "ifc": ("BIM model", "view_in_ar"),
    "rvt": ("Revit model", "view_in_ar"), "bog": ("Niagara station", "dns"), "zip": ("Archive", "folder_zip"),
    "eml": ("Email", "mail"), "msg": ("Email", "mail"),
}
IMAGES = {"png", "jpg", "jpeg", "gif", "webp"}
TEXT = {"txt", "md", "json", "yaml", "yml", "zinc", "ttl", "xml", "csv", "tsv"}


@dataclass
class Doc:
    id: str
    name: str
    category: str
    path: Path
    size: int
    added: float
    origin: str           # setup | library | source
    step: str = ""        # the guided-setup step that read it (origin setup)
    note: str = ""

    @property
    def ext(self) -> str:
        return self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""

    @property
    def kind(self) -> str:
        return KIND.get(self.ext, (self.ext.upper() or "File", "draft"))[0]

    @property
    def icon(self) -> str:
        return KIND.get(self.ext, ("", "draft"))[1]

    @property
    def editable(self) -> bool:
        return self.origin != "source"


def guess_category(name: str) -> str:
    n = name.lower()
    for pattern, cat in _GUESS:
        if re.search(pattern, n, re.I):
            return cat
    return "Other"


def site_of(project: str) -> str:
    return project.split("/")[0]


# ---------------------------------------------------------------- the library's own files

def _dir(site: str) -> Path:
    return LIBRARY / site


def _index(site: str) -> list[dict]:
    p = _dir(site) / "index.json"
    return json.loads(p.read_text()) if p.exists() else []


def _save_index(site: str, rows: list[dict]) -> None:
    d = _dir(site)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "index.json.tmp"
    tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    tmp.replace(d / "index.json")


def _store(site: str, name: str, data: bytes) -> tuple[str, Path]:
    digest = hashlib.sha256(data).hexdigest()
    name = Path(name).name
    path = _dir(site) / "files" / f"{digest[:10]}_{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest, path


def add(project: str, name: str, data: bytes, category: str | None = None) -> Doc:
    """Keep a file in the project's library. The same content twice is kept once."""
    site = site_of(project)
    rows = _index(site)
    digest, path = _store(site, name, data)
    for r in rows:
        if r["sha256"] == digest:
            return _doc(site, r)
    row = {"id": f"lib:{digest[:12]}", "name": Path(name).name, "category": category or guess_category(name),
           "file": str(path.relative_to(_dir(site))), "sha256": digest, "size": len(data), "added": time.time()}
    rows.append(row)
    _save_index(site, rows)
    return _doc(site, row)


def _doc(site: str, r: dict) -> Doc:
    return Doc(r["id"], r["name"], r["category"], _dir(site) / r["file"], r["size"], r["added"], "library")


def set_category(project: str, doc_id: str, category: str) -> None:
    site = site_of(project)
    rows = _index(site)
    for r in rows:
        if r["id"] == doc_id:
            r["category"] = category
    _save_index(site, rows)


# ---------------------------------------------------------------- one list for the page

def documents(project: str) -> list[Doc]:
    """Every document of the project, by category (CATEGORIES order), then name."""
    site = site_of(project)
    out: list[Doc] = []
    from .intake.state import Intake
    it = Intake(site)
    if it.s:
        for step, files in it.s.get("files", {}).items():
            for f in files:
                out.append(Doc(f"setup:{step}:{f['name']}", f["name"], STEP_CATEGORY.get(step, "Other"), it.path(f),
                               f["size"], f.get("added", it.s.get("created", 0)), "setup", step,
                               "Read in the guided setup"))
    out += [_doc(site, r) for r in _index(site)]
    for p in sorted((RAW / "haystack").glob(f"{site}.*")):
        out.append(Doc(f"src:{p.name}", p.name, "Source data", p, p.stat().st_size, p.stat().st_mtime, "source",
                       note="Project Haystack export the graph was mapped from. Read-only."))
    for p in sorted((DOCUMENTS / site).glob("*")) if (DOCUMENTS / site).is_dir() else []:
        if p.is_file() and p.name != "README.md":
            out.append(Doc(f"src:doc:{p.name}", p.name, guess_category(p.name), p, p.stat().st_size,
                           p.stat().st_mtime, "source", note="Prepared with the project. Read-only."))
    order = list(CATEGORIES)
    return sorted(out, key=lambda d: (order.index(d.category) if d.category in order else len(order),
                                      d.name.lower()))


def find(project: str, doc_id: str) -> Doc | None:
    return next((d for d in documents(project) if d.id == doc_id), None)


def delete(project: str, doc: Doc, store=None) -> None:
    """Remove a document. A setup file: its step is read again without it and re-published."""
    if doc.origin == "source":
        raise ValueError("Source data is read-only: the raw sources are never changed.")
    site = site_of(project)
    if doc.origin == "library":
        rows = [r for r in _index(site) if r["id"] != doc.id]
        doc.path.unlink(missing_ok=True)
        _save_index(site, rows)
        return
    _reread(project, doc.step, store, remove=doc.name)


def replace(project: str, doc: Doc, name: str, data: bytes, store=None) -> Doc | None:
    """Put a new version in the old one's place, in the same category. A setup file: its step is read again with the
    new file and re-published, so the knowledge graph follows."""
    if doc.origin == "source":
        raise ValueError("Source data is read-only: the raw sources are never changed.")
    site = site_of(project)
    if doc.origin == "library":
        rows = _index(site)
        digest, path = _store(site, name, data)
        for r in rows:
            if r["id"] == doc.id:
                if Path(_dir(site) / r["file"]) != path:
                    (_dir(site) / r["file"]).unlink(missing_ok=True)
                r.update(name=Path(name).name, file=str(path.relative_to(_dir(site))), sha256=digest, size=len(data),
                         added=time.time())
        _save_index(site, rows)
        return next((_doc(site, r) for r in rows if r["id"] == doc.id), None)
    _reread(project, doc.step, store, remove=doc.name, add=(name, data))
    return None


def _reread(project: str, step: str, store, remove: str = "", add: tuple[str, bytes] | None = None) -> None:
    from .intake import steps
    from .intake.publish import publish
    from .intake.state import Intake
    it = Intake(site_of(project))
    if remove:
        it.remove_file(step, remove)
    if add:
        it.add_file(step, *add)
    steps.run(it, step, lambda m: None)
    if store is not None and project.endswith("/documents"):
        publish(it, store, steps=[step])


def _digest_key(doc: Doc) -> str:
    return f"{doc.id}|{doc.size}"


def get_digest(project: str, doc: Doc) -> dict | None:
    """What a model said this document is (file_ai.digest), kept so it is not asked twice for the same file."""
    p = _dir(site_of(project)) / "digests.json"
    return (json.loads(p.read_text()) if p.exists() else {}).get(_digest_key(doc))


def save_digest(project: str, doc: Doc, digest: dict) -> None:
    d = _dir(site_of(project))
    d.mkdir(parents=True, exist_ok=True)
    p = d / "digests.json"
    rows = json.loads(p.read_text()) if p.exists() else {}
    rows[_digest_key(doc)] = digest
    p.write_text(json.dumps(rows, indent=1, ensure_ascii=False))


def summary(docs: list[Doc]) -> dict:
    by_cat: dict[str, int] = {}
    for d in docs:
        by_cat[d.category] = by_cat.get(d.category, 0) + 1
    return {"count": len(docs), "bytes": sum(d.size for d in docs), "by_category": by_cat}
