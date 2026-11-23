"""Coverage: what a step expected to find against what it found, so no step ends with nothing and says nothing.

The stress test (scripts/stress_intake.py, docs/assessment-rules-vs-ai.md) showed readers that read zero rooms, zero
sequences or zero points from another firm's documents, and asked nothing. After every step, check() looks at the
step's facts (and its PDFs' text layer) and returns an issue for each gap, as a question the person sees in the setup:

    plans       no floor named in any title; a floor with no room labels read; pages with no text layer
    schedules   no schedule rows
    sequences   no sequence headings
    submittal   no points, no controllers on a riser
    bms         no object column; no device linked to equipment

Each issue says what was expected, what was found, and what to try (another file, or the AI reader when it is
built). These are rules, never a model: they decide when the rules have run out.
"""

from __future__ import annotations

from pathlib import Path

from . import pdfdoc

PARTIAL = 0.25  # more than this share of a step's items unlinked is a partial read, said once, not only item by item
SCANNED_WORDS = 25  # a page with fewer words than this has no usable text layer (a scan, or a picture of a sheet)


def _issue(step: str, key: str, text: str, file: str = "", page: int | None = None) -> dict:
    return {"id": f"issue:coverage-{step}-{key}", "kind": "issue", "label": text,
            "data": {"text": text, "severity": "coverage"},
            "src": {"file": file, "page": page, "bbox": None}, "method": "rule", "conf": 0.5, "step": step,
            "ask": {"q": text, "field": None, "options": []}}


def _scanned(step: str, files: list[tuple[Path, str]]) -> list[dict]:
    out = []
    for path, name in files:
        if path.suffix.lower() != ".pdf":
            continue
        n = pdfdoc.page_count(path)
        empty = [p + 1 for p in range(n) if len(pdfdoc.words(path, p)) < SCANNED_WORDS]
        if empty:
            shown = ", ".join(map(str, empty[:8])) + ("…" if len(empty) > 8 else "")
            text = (f"{name}: {len(empty)} of {n} pages have no readable text (page {shown}), so the rules can't "
                    "read them. Is it a scan? Upload the original PDF if you have it; otherwise these pages wait "
                    "for the AI reader.")
            out.append(_issue(step, f"scanned-{name}", text, name, empty[0] - 1))
    return out


STEP_OF = {"rooms": "plans", "equipment": "schedules", "sequences": "sequences", "points": "submittal",
           "devices": "bms"}


def _main(run: dict) -> dict[str, int]:
    rd, kinds = run.get("read", {}), run["asks"].get("seq_kinds")
    return {"rooms": rd.get("rooms", 0), "equipment": rd.get("equipment", 0),
            "sequences": kinds.get("sequence", 0) if isinstance(kinds, dict) else 0, "points": rd.get("points", 0),
            "devices": int(str(rd.get("devices linked", "0/0")).split("/")[0])}


def stress_state(run: dict, base: dict) -> tuple[str, list[str]]:
    """One stress scenario (scripts/stress_intake.py) against the baseline: reads (within 10% everywhere), asks
    (short somewhere, and each short step raised a coverage question), quiet (short, with no coverage question: a
    partial read nobody is told about), silent (a step read nothing and asked nothing)."""
    m, b = _main(run), _main(base)
    short = [k for k in b if b[k] and m[k] < 0.9 * b[k]]
    if run.get("silent"):
        return "silent", short
    if not short:
        return "reads", short
    told = run.get("coverage", {})
    return ("asks" if all(told.get(STEP_OF[k]) for k in short) else "quiet"), short


def check(step: str, facts: list[dict], files: list[tuple[Path, str]]) -> list[dict]:
    """Issues for what the step should have found and didn't. Empty when coverage looks normal."""
    kinds: dict[str, list[dict]] = {}
    for f in facts:
        kinds.setdefault(f["kind"], []).append(f)
    n = lambda k: len(kinds.get(k, []))  # noqa: E731
    first = files[0][1] if files else ""
    out = _scanned(step, files)
    if step == "plans":
        if not n("floor"):
            out.append(_issue(step, "no-floor", "No floor plan was recognised: no sheet title names a level (\"PLAN - "
                              "LEVEL 1\", \"FIRST FLOOR PLAN\"…). If these are floor plans, their titles use another "
                              "style; tell us which floor each page is, or wait for the AI reader.", first))
        for fl in kinds.get("floor", []):
            if not fl["data"].get("rooms"):
                out.append(_issue(step, f"no-rooms-{fl['data']['floor']}",
                                  f"{fl['label']}: the page was read but no room labels were found. Rooms may be "
                                  "numbered another way (letters, more digits) or the names sit below the numbers.",
                                  fl["src"].get("file", first), fl["src"].get("page")))
    elif step == "schedules" and not n("equipment"):
        out.append(_issue(step, "no-rows", "No equipment schedule rows were found: no table titled \"… SCHEDULE\" "
                          "with rows starting with an equipment tag. Check the file, or wait for the AI reader.", first))
    elif step == "sequences" and not n("sequence"):
        out.append(_issue(step, "no-sequences", "No sequence was found: no system heading like \"AIR HANDLING UNIT:\" "
                          "with sections A., B., C. The document may use another style (numbered or Title Case "
                          "headings, spec sections).", first))
    elif step == "submittal":
        if not n("point"):
            out.append(_issue(step, "no-points", "No points were read from the submittal: no point schedule rows "
                              "in the expected format (point, description, AI/AO/BI/BO, terminal, reference). "
                              "Another controls vendor's layout needs the AI reader.", first))
        if not n("controller"):
            out.append(_issue(step, "no-riser", "No controllers were read from a network riser (trunk headings like "
                              "\"FC-1 - …\" with address, device, controller, instance rows).", first))
        else:
            lone = [c for c in kinds["controller"] if not c["data"].get("equip")]
            if len(lone) > PARTIAL * n("controller"):
                out.append(_issue(step, "few-linked", f"{len(lone)} of {n('controller')} controllers on the riser match "
                                  "no scheduled equipment, so their points have no unit. The submittal may name units "
                                  "another way than the schedules (floor in the tag, another scheme): answer one, or "
                                  "add the scheme as a setup rule.", first))
    elif step == "bms":
        aliases = kinds.get("alias", [])
        if not n("bms_object"):
            out.append(_issue(step, "no-objects", "No BMS objects were read: no column names the objects (Item "
                              "Reference, Name, Path…). Which column holds each point's reference?", first))
        elif aliases and not any(a["data"].get("equip") for a in aliases):
            out.append(_issue(step, "no-links", f"None of the {len(aliases)} BMS devices could be linked to "
                              "equipment: their names carry no equipment tag and match no device instance on the "
                              "riser.", first))
        elif aliases and (lone := [a for a in aliases if not a["data"].get("equip")]) \
                and len(lone) > PARTIAL * len(aliases):
            out.append(_issue(step, "few-links", f"{len(lone)} of {len(aliases)} BMS devices are linked to no "
                              "equipment. The BMS may name devices another way than the drawings; answer one, or add "
                              "the scheme as a setup rule.", first))
    return out
