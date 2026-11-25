"""The documents behind a project's graph, for the agent: where a fact was read (file, page, sheet, box), the page
itself, and the sequences of operation as the readers left them (sections, setpoints, gaps, conflicts).

    docs = DocumentIndex.for_project("troop-d/documents")      # the guided setup's building, if there is one
    src = docs.source(node_row_prov)                           # {"cite": "src:2_equipment_schedules.pdf#p1", ...}
    png = docs.crop_png("src:2_equipment_schedules.pdf#p1", bbox)

The graph keeps a fact's file and a short reference ("M-401 page 1", "row 12"). The box a reader saw it in lives
with the building's setup (intake/state.py facts), so it is looked up there; when the setup is not at hand, the words
of the fact's name are looked for on the page. Read-only: nothing here writes anything.

Citation ids (the agent cites them as [[id]], the dock and the scorer resolve them):
    src:<file>#p<page>      a page of a project document (page counted from 1)
    src:<file>#r<row>       a row of a table export (the BMS CSV)
    seq:<sequence>          a sequence of operation, seq:<sequence>/<section> one of its sections
    issue:<id>              a gap or conflict a reader raised (a sequence step that has no point, two sections that
                            cannot both hold)
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REF = re.compile(r"^(?:(?P<sheet>[A-Z]{1,3}-?\d{1,4}[A-Z]?)\s+)?(?:page\s+(?P<page>\d+))?\s*(?:row\s+(?P<row>\d+))?")
SRC = re.compile(r"^src:(?P<file>.+)#(?:p(?P<page>\d+)|r(?P<row>\d+))$")


def site_dirs(project: str) -> list[Path]:
    """Folders where a project's documents may sit, most specific first: the test package, the raw downloads and the
    documents folder, for the site name as written and with dashes as underscores (troop-d -> troop_d)."""
    site = project.split("/")[0]
    names = list(dict.fromkeys([site, site.replace("-", "_")]))
    return [ROOT / base / n for n in names for base in ("test_packages", "data/raw", "data/documents")]


def parse_ref(ref: str) -> dict:
    """'M-401 page 1' -> {"sheet": "M-401", "page": 1}; 'row 12' -> {"row": 12}; 'M-304 page 1 · Air Handling Unit E.'
    -> {"sheet": "M-304", "page": 1}."""
    m = REF.match((ref or "").split(" · ")[0].strip())
    out: dict = {}
    if m:
        if m.group("sheet"):
            out["sheet"] = m.group("sheet")
        if m.group("page"):
            out["page"] = int(m.group("page"))
        if m.group("row"):
            out["row"] = int(m.group("row"))
    return out


def src_cite(file: str, page: int | None = None, row: int | None = None) -> str:
    return f"src:{file}#p{page}" if page is not None else f"src:{file}#r{row or 0}"


def parse_src_cite(cite: str) -> dict | None:
    m = SRC.match(cite or "")
    if not m:
        return None
    return {"file": m.group("file"), "page": int(m.group("page")) if m.group("page") else None,
            "row": int(m.group("row")) if m.group("row") else None}


@dataclass
class Sequence:
    """One sequence of operation as the rules read it (intake/sequence_text.py)."""
    id: str                      # "air-handling-unit"
    title: str
    family: str | None
    applies_to: list[str]        # unit tags (AHU01, VAV01...)
    sections: list[dict]         # {letter, title, text, bbox}
    setpoints: list[dict]        # {section, value, unit, text}
    file: str
    page: int | None             # from 1
    sheet: str | None
    bbox: list[float] | None
    issues: list[dict] = field(default_factory=list)   # {id, text, sections, by, kind}

    @property
    def cite(self) -> str:
        return f"seq:{self.id}"

    def section(self, letter: str) -> dict | None:
        return next((s for s in self.sections if s["letter"] == letter), None)


class DocumentIndex:
    """A project's documents and what the readers found in them. `intake` is the guided setup's building
    (intake/state.Intake) when the project came from one."""

    def __init__(self, project: str, intake=None, dirs: list[Path] | None = None):
        self.project, self.intake = project, intake
        self.dirs = dirs if dirs is not None else site_dirs(project)
        self._facts: list[dict] | None = None

    @classmethod
    def for_project(cls, project: str) -> "DocumentIndex":
        intake = None
        if project.endswith("/documents"):
            try:
                from ..intake.state import Intake
                it = Intake(project.split("/")[0])
                intake = it if it.s else None
            except Exception:  # noqa: BLE001 - no setup state: pages are still found in the site's folders
                intake = None
        return cls(project, intake)

    # files ---------------------------------------------------------------------------------------------------------

    def path(self, file: str) -> Path | None:
        name = Path(file or "").name
        if not name:
            return None
        if self.intake is not None and (p := self.intake.file_by_name(name)) and p.exists():
            return p
        p = Path(file)
        if p.is_absolute() and p.exists():
            return p
        if (ROOT / file).exists():
            return ROOT / file
        for d in self.dirs:
            if (d / name).exists():
                return d / name
        return None

    def page_size(self, file: str, page: int) -> tuple[float, float] | None:
        path = self.path(file)
        if path is None or path.suffix.lower() != ".pdf":
            return None
        from ..intake import pdfdoc
        try:
            return pdfdoc.page_size(path, page - 1)
        except Exception:  # noqa: BLE001 - a page number outside the file
            return None

    # facts the setup read, with their boxes ----------------------------------------------------------------------

    def facts(self) -> list[dict]:
        if self._facts is None:
            self._facts = self.intake.facts(live=True) if self.intake is not None else []
        return self._facts

    def box_for(self, node_id: str, attrs: dict, file: str, page: int | None) -> list[float] | None:
        """The box the setup read this node in, on that page of that file; else where its name is on the page."""
        if page is None:
            return None
        name = Path(file).name
        keys = {node_id, node_id.split(":", 1)[-1]}
        for k in ("tag", "ref", "normal", "number"):
            if attrs.get(k):
                keys.add(str(attrs[k]))
        if node_id.startswith("ctrl:"):
            keys.add(f"instance:{node_id[5:]}")
        best = None
        for f in self.facts():
            s = f.get("src") or {}
            if Path(s.get("file") or "").name != name or s.get("page") != page - 1 or not s.get("bbox"):
                continue
            d = f.get("data") or {}
            mine = {f["id"], f["id"].split(":", 1)[-1], str(d.get("tag", "")), str(d.get("ref", "")),
                    str(d.get("normal", "")), str(d.get("number", ""))}
            if d.get("instance") is not None:
                mine.add(f"instance:{d['instance']}")
            if keys & (mine - {""}):
                best = s["bbox"]
                if f["id"] == node_id or f["id"].split(":", 1)[-1] == node_id.split(":", 1)[-1]:
                    break
        if best is not None:
            return [round(float(v), 1) for v in best]
        return self.find_words(file, page, [k for k in keys if k and ":" not in k])

    def find_words(self, file: str, page: int, names: list[str]) -> list[float] | None:
        """The box of the first of `names` found as a word on the page (PDF points), or None."""
        path = self.path(file)
        if path is None or path.suffix.lower() != ".pdf":
            return None
        ws = _words(str(path), page - 1)
        want = {n.upper().replace("-", "") for n in names if len(n) >= 3}
        for w in ws:
            if w[0].upper().replace("-", "") in want:
                return [round(v, 1) for v in w[1:]]
        return None

    # sequences -----------------------------------------------------------------------------------------------------

    def sequences(self) -> list[Sequence]:
        out = []
        issues = [f for f in self.facts() if f["kind"] == "issue" and f.get("step") == "sequences"]
        for f in self.facts():
            if f["kind"] != "sequence" or f.get("status") == "rejected":
                continue
            d, s = f["data"], f["src"]
            sid = f["id"].split(":", 1)[-1]
            seq = Sequence(sid, d.get("title") or f["label"], d.get("family"), list(d.get("applies_to") or []),
                           list(d.get("sections") or []), list(d.get("setpoints") or []), s.get("file", ""),
                           (s["page"] + 1) if s.get("page") is not None else None, s.get("sheet"), s.get("bbox"))
            for i in issues:
                text = i["data"].get("text") or i["label"]
                if f"'{seq.title}'" not in text and not i["id"].startswith(f"issue:ai-{sid}-") \
                        and not i["id"].startswith(f"issue:{sid}-"):
                    continue
                ai = (i["data"].get("ai") or {})
                secs = re.findall(r"'\s*([A-Z0-9, ]+?):", text)
                letters = sorted({x.strip() for part in secs for x in part.split(",") if x.strip()})
                seq.issues.append({"id": i["id"], "text": text, "sections": letters, "by": ai.get("by", "rule"),
                                   "kind": ai.get("kind") or ("gap" if "missing" in text or "no " in text else "check"),
                                   "status": i.get("status"), "src": i.get("src")})
            out.append(seq)
        return out

    def sequence(self, sid: str) -> Sequence | None:
        return next((s for s in self.sequences() if s.id == sid), None)

    def issue(self, issue_id: str) -> dict | None:
        return next((i for s in self.sequences() for i in s.issues if i["id"] == issue_id), None)

    # pages as images -----------------------------------------------------------------------------------------------

    def crop_png(self, file: str, page: int, bbox: list[float] | None = None, pad: float = 60.0,
                 dpi: float = 110.0) -> bytes | None:
        """The page around `bbox` (or the whole page), with the box drawn, as PNG bytes; None when the file is not
        here or is not a PDF."""
        path = self.path(file)
        if path is None or path.suffix.lower() != ".pdf":
            return None
        from ..intake import pdfdoc
        size = pdfdoc.page_size(path, page - 1)
        crop, labels = None, None
        if bbox:
            w = max(bbox[2] - bbox[0], 160.0)
            h = max(bbox[3] - bbox[1], 90.0)
            cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
            crop = [max(0.0, cx - w / 2 - pad), max(0.0, cy - h / 2 - pad), min(size[0], cx + w / 2 + pad),
                    min(size[1], cy + h / 2 + pad)]
            labels = [{"id": "", "bbox": bbox, "color": "#D02020"}]
        pim = pdfdoc.page_image(path, page - 1, dpi=dpi if bbox else 60.0, crop=crop, labels=labels, max_px=1600,
                                gray=False)
        buf = io.BytesIO()
        pim.image.save(buf, format="PNG")
        return buf.getvalue()


@lru_cache(maxsize=32)
def _words(path: str, page: int) -> list[tuple[str, float, float, float, float]]:
    from ..intake import pdfdoc
    try:
        return [(w.text, w.x0, w.top, w.x1, w.bottom) for w in pdfdoc.words(Path(path), page)]
    except Exception:  # noqa: BLE001 - not a page of this file
        return []


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)
