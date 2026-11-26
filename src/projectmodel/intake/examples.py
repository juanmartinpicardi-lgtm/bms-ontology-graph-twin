"""Example projects for the guided setup: three public bid sets a person can start a new building from.

A building started from an example offers that project's documents, and only that project's, at every step: a new
building never mixes documents from two projects (Intake.example). A building started from the person's own documents
offers no example at all.

    troop_d     Missouri State Highway Patrol Troop D Crime Lab: the worked example (test_packages/troop_d), one file
                per step. Steps 4 and 5 are synthetic, written from its answer key.
    msu_mbb     Montana State University, Molecular Bioscience Building renovation (dev set, docs/real-document-sets.md)
    itd_d1_lab  Idaho Transportation Department, District 1 Testing Laboratory (dev set, same doc)

The held-out set (liberty_boe) is never an example: showing it in the app would expose its documents and results, and
it would stop counting as held out (CLAUDE.md §5).

The two real sets are one drawing PDF each. A step's document is the sheets a person would pick for it (the page lists
of scripts/run_real_sets.py), copied into data/examples/<slug>/ the first time it is asked for. The raw PDF is never
changed. It is not in git: when missing it is downloaded from the owner's site and checked against the sha256 in
data/raw/SOURCES.md. Neither set has a controls submittal or a BMS export: the submittal step gets the design points
list on the drawings (a stand-in, said so on screen), and the BMS step gets nothing.
"""
from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .steps import TEST_PACKAGE, BY_ID

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data/raw"
CACHE = ROOT / "data/examples"


@dataclass(frozen=True)
class Doc:
    """One step's example document: a file of the test package, or pages of a project's drawing PDF."""
    name: str                      # the file name the step receives
    what: str                      # what it is, in a few words
    file: str = ""                 # a test-package file (troop_d)
    pages: tuple[int, ...] = ()    # 1-based pages of the project's drawing PDF
    stand_in: str = ""             # set when the document is not the real thing the step asks for: why


@dataclass(frozen=True)
class Example:
    slug: str
    name: str
    place: str
    address: str
    kind: str
    owner: str
    blurb: str
    docs: dict[str, Doc]
    drawings: str = ""             # the project's drawing PDF in data/raw/<slug>/
    url: str = ""                  # where that PDF is downloaded from when missing
    notes: tuple[str, ...] = field(default=())


MSU_URL = "https://www.montana.edu/pdc/projects/22-0045%20Plans.pdf"
ITD_URL = ("https://apps.itd.idaho.gov/Apps/NonHwyConstructionProjects/PDFS/"
           "ITD%20D1%20Laboratory%20Building%20-%20%20Mechanical%20Bid%20Set%2005-14-24.pdf")

EXAMPLES: dict[str, Example] = {e.slug: e for e in [
    Example(
        "troop_d", "Troop D Crime Lab", "Springfield, MO", "425 East Phelps Street, Springfield, MO 65806, USA",
        "Crime lab and offices, 3 floors + roof", "State of Missouri, Office of Administration",
        "The worked example. Real bid drawings for steps 1 to 3; the submittal and BMS export are synthetic, written "
        "from its answer key, so every step has a document.",
        {"plans": Doc("1_floor_plans.pdf", "Mechanical plans M-101 to M-104", file="1_floor_plans.pdf"),
         "schedules": Doc("2_equipment_schedules.pdf", "Schedules M-401, flow diagrams M-301 to M-303",
                          file="2_equipment_schedules.pdf"),
         "sequences": Doc("3_sequences.pdf", "Sequences of operation M-304", file="3_sequences.pdf"),
         "submittal": Doc("4_controls_submittal.pdf", "Controls submittal (synthetic)", file="4_controls_submittal.pdf"),
         "bms": Doc("5_bms_export.csv", "BMS point export (synthetic)", file="5_bms_export.csv")},
        notes=("Has an answer key: the Review step scores the readers against it.",)),
    Example(
        "msu_mbb", "MSU Molecular Bioscience Building", "Bozeman, MT",
        "Molecular Bioscience Building, Montana State University, Bozeman, MT 59717, USA",
        "University lab and office renovation, 3 levels", "Montana State University",
        "A partial renovation of an occupied lab building: new fan coils, chiller, boilers and pumps next to existing "
        "(E) equipment. Floor-dotted tags (FC-1.16) and a vertical title block.",
        {"plans": Doc("MSU_floor_plans_M201-M203.pdf", "HVAC plans M.201 to M.203", pages=(22, 23, 24)),
         "schedules": Doc("MSU_schedules_M101-M102_M401.pdf", "Schedules M.101, M.102, flow diagrams M.401",
                          pages=(20, 21, 29)),
         "sequences": Doc("MSU_sequences_M502.pdf", "Sequences of operation M.502", pages=(31,)),
         "submittal": Doc("MSU_points_list_M501-M502.pdf", "Controls M.501 and the design points list M.502",
                          pages=(30, 31),
                          stand_in="No controls submittal was published. These are the design points list and "
                                   "controls sheets from the drawings, the closest thing available.")},
        drawings="22-0045 Plans.pdf", url=MSU_URL),
    Example(
        "itd_d1_lab", "ITD District 1 Testing Laboratory", "Coeur d'Alene, ID",
        "600 W Prairie Ave, Coeur d'Alene, ID 83815, USA",
        "New single-storey materials testing lab, 27 rooms", "Idaho Transportation Department",
        "A new lab building with lab exhaust, hydronic heating and rooftop units. Two-line hexagon tags and Title "
        "Case room names.",
        {"plans": Doc("ITD_floor_plans_M1.0-M2.0.pdf", "HVAC, exhaust, hydronic and roof plans M1.0 to M2.0",
                      pages=(3, 4, 5, 6)),
         "schedules": Doc("ITD_schedules_M5.0-M5.3.pdf", "Mechanical schedules M5.0 to M5.3", pages=(12, 13, 14, 15)),
         "sequences": Doc("ITD_sequences_M6.0-M6.5.pdf", "Mechanical controls and sequences M6.0 to M6.5",
                          pages=(16, 17, 18, 19, 20, 21)),
         "submittal": Doc("ITD_points_list_M6.2-M6.3.pdf", "Design points list M6.2 to M6.3", pages=(18, 19),
                          stand_in="No controls submittal was published. These are the design points list sheets "
                                   "from the drawings, the closest thing available.")},
        drawings="ITD D1 Laboratory Building - Mechanical Bid Set 05-14-24.pdf", url=ITD_URL),
]}

NO_DOC = ("None of the public bid sets has one: a {what} is written by the controls contractor after the bid, and it "
          "is not published. Skip this step for this project.")


class ExampleError(Exception):
    pass


def get(slug: str | None) -> Example | None:
    return EXAMPLES.get(slug or "")


def doc(slug: str | None, step_id: str) -> Doc | None:
    ex = get(slug)
    return ex.docs.get(step_id) if ex else None


def missing_note(step_id: str) -> str:
    t = BY_ID[step_id].title
    return NO_DOC.format(what=t if t[:3].isupper() else t.lower())  # "BMS export" keeps its capitals


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _known_sha(slug: str, name: str) -> str:
    """sha256 recorded in data/raw/SOURCES.md for `slug/name` (rows `| slug/file | … | sha |`)."""
    for line in (RAW / "SOURCES.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == f"{slug}/{name}" and len(cells[-1]) == 64:
            return cells[-1]
    return ""


def drawings_path(ex: Example) -> Path:
    """The project's drawing PDF, downloaded and checked first when it is not on disk yet."""
    p = RAW / ex.slug / ex.drawings
    if p.exists():
        return p
    want = _known_sha(ex.slug, ex.drawings)
    tmp = p.with_suffix(".part")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(ex.url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:
            f.write(r.read())
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise ExampleError(f"Could not download the {ex.name} drawings from the owner's site ({e}).") from e
    if want and _sha256(tmp) != want:
        tmp.unlink(missing_ok=True)
        raise ExampleError(f"The {ex.name} drawings on the owner's site are not the copy recorded in "
                           "data/raw/SOURCES.md, so they were not used.")
    tmp.replace(p)
    return p


def available(slug: str, step_id: str) -> bool:
    """The step's document can be had without a download (it is cached, in the test package, or its source PDF is on
    disk)."""
    ex, d = get(slug), doc(slug, step_id)
    if not ex or not d:
        return False
    if d.file:
        return (TEST_PACKAGE / d.file).exists()
    return (CACHE / slug / d.name).exists() or (RAW / slug / ex.drawings).exists()


def file_for(slug: str, step_id: str) -> Path | None:
    """The step's example document as a file, made (and the source fetched) the first time it is asked for. None when
    the project has no document for the step."""
    ex, d = get(slug), doc(slug, step_id)
    if not ex or not d:
        return None
    if d.file:
        p = TEST_PACKAGE / d.file
        if not p.exists():
            raise ExampleError(f"{p.relative_to(ROOT)} is missing.")
        return p
    out = CACHE / slug / d.name
    if out.exists():
        return out
    import pypdfium2 as pdfium
    src = pdfium.PdfDocument(drawings_path(ex))
    pdf = pdfium.PdfDocument.new()
    pdf.import_pages(src, [n - 1 for n in d.pages])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    pdf.save(tmp)
    tmp.replace(out)
    return out
