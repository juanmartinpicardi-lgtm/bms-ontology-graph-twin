"""Run the guided-setup readers, unchanged, on the real public document sets of W0 (docs/real-document-sets.md).

    .venv/bin/python scripts/run_real_sets.py            # check the files, run every set, write reports/real_sets.json
    .venv/bin/python scripts/run_real_sets.py --fetch    # first download any missing file into data/raw/<set>/

Each set is run twice, the way a person could upload it:
  - "sheets": the sheets a person would pick for each step (page numbers below, from the set's profile);
  - "whole set": the whole drawing PDF uploaded at the plans, schedules and sequences steps.
No set has a contractor's controls submittal or a BMS export. Where the drawings carry a design points list, those
sheets are also given to the submittal step in the "sheets" run, as the closest thing a person would have; the BMS
step gets nothing.

Held-out set (`role: heldout`): only headline counts are written. Never print or read its questions or issues when
choosing fixes, and never tune rules or prompts on it (CLAUDE.md §5).

The raw PDFs are never changed: the chosen pages are copied into a temporary folder. Results: reports/real_sets.json.
Slow: about 30 minutes, most of it the 78-sheet MSU drawing set read whole by three readers. `--sheets` skips the
whole-set runs (about 1 minute).
"""
from __future__ import annotations

import hashlib, json, os, sys, tempfile, time, urllib.request

os.environ.setdefault("PM_AI", "off")  # rules only, so the numbers are the rules' (set PM_AI=on to include model calls)
from collections import Counter
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from projectmodel.intake import steps  # noqa: E402
from projectmodel.intake.state import Intake  # noqa: E402

RAW = ROOT / "data/raw"

# Download URL per file (the sha256 of each is in data/raw/SOURCES.md). Pages are 1-based pages of the drawing PDF.
MSU = "https://www.montana.edu/pdc/projects/22-0045%20"
SETS = {
    "msu_mbb": {
        "role": "dev",
        "title": "Montana State University, Molecular Bioscience Building renovations (PPA 22-0045), Bozeman MT",
        "files": {
            "22-0045 Plans.pdf": MSU + "Plans.pdf",
            "22-0045 Molecular Bioscience Building Renovations and Maintenance Project Manual Final.pdf":
                MSU + "Molecular%20Bioscience%20Building%20Renovations%20and%20Maintenance%20Project%20Manual%20Final.pdf",
            "22-0045 Addendum 1.pdf": MSU + "Addendum%201.pdf",
            "22-0045 Addendum 2.pdf": MSU + "Addendum%202.pdf",
            "22-0045 Addendum 3 updated.pdf": MSU + "Addendum%203%20updated.pdf",
        },
        "drawings": "22-0045 Plans.pdf",
        "pages": {"plans": [22, 23, 24], "schedules": [20, 21, 29], "sequences": [31], "submittal": [30, 31]},
    },
    "itd_d1_lab": {
        "role": "dev",
        "title": "Idaho Transportation Department, District 1 Testing Laboratory (D231130 phase 2), Coeur d'Alene ID",
        "files": {
            "ITD D1 Laboratory Building - Mechanical Bid Set 05-14-24.pdf":
                "https://apps.itd.idaho.gov/Apps/NonHwyConstructionProjects/PDFS/"
                "ITD%20D1%20Laboratory%20Building%20-%20%20Mechanical%20Bid%20Set%2005-14-24.pdf",
        },
        "drawings": "ITD D1 Laboratory Building - Mechanical Bid Set 05-14-24.pdf",
        "pages": {"plans": [3, 4, 5, 6], "schedules": [12, 13, 14, 15], "sequences": [16, 17, 18, 19, 20, 21],
                  "submittal": [18, 19]},
    },
    "liberty_boe": {
        "role": "heldout",
        "title": "Liberty County School System, Board of Education building HVAC replacement (RFP 2026-07), "
                 "Hinesville GA",
        "files": {
            "2026-07 Drawings.pdf":
                "https://www.libertyschools.org/ourpages/auto/2025/12/5/62988481/2026-07%20Drawings.pdf",
        },
        "drawings": "2026-07 Drawings.pdf",
        "pages": {"plans": [8, 9, 10, 11], "schedules": [3], "sequences": [13], "submittal": [12]},
    },
}
STEP_FILE = {"plans": "1_floor_plans.pdf", "schedules": "2_equipment_schedules.pdf", "sequences": "3_sequences.pdf",
             "submittal": "4_controls_submittal.pdf"}
MAIN_KIND = {"plans": "room", "schedules": "equipment", "sequences": "sequence", "submittal": "point",
             "bms": "bms_object"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_hashes() -> dict[str, str]:
    """sha256 per file from data/raw/SOURCES.md, the one place they are recorded (rows `| slug/file | … | sha |`)."""
    out = {}
    for line in (RAW / "SOURCES.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and "/" in cells[0] and len(cells[-1]) == 64:
            out[cells[0]] = cells[-1]
    return out


def check(fetch: bool) -> dict[str, str]:
    known, bad = load_hashes(), []
    for slug, s in SETS.items():
        for name, url in s["files"].items():
            p = RAW / slug / name
            if not p.exists() and fetch:
                p.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req) as r, p.open("wb") as f:
                    f.write(r.read())
            if not p.exists():
                bad.append(f"missing {p.relative_to(ROOT)} (run with --fetch)")
                continue
            want = known.get(f"{slug}/{name}")
            if not want:
                bad.append(f"no sha256 recorded for {slug}/{name} in data/raw/SOURCES.md")
            elif sha256(p) != want:
                bad.append(f"sha256 differs for {slug}/{name}: not the copy recorded in SOURCES.md")
    if bad:
        sys.exit("\n".join(bad))
    return known


def extract(src: Path, pages: list[int], dst: Path) -> None:
    pdf, out = pdfium.PdfDocument(src), pdfium.PdfDocument.new()
    out.import_pages(pdf, [p - 1 for p in pages])
    out.save(dst)


def run(slug: str, mode: str) -> dict:
    s = SETS[slug]
    src = RAW / slug / s["drawings"]
    tmp = Path(tempfile.mkdtemp())
    it = Intake.create(f"real-{slug}-{mode}", root=tmp / "intake")
    per_step, t0 = {}, time.time()
    for st in steps.STEPS[:-1]:
        if mode == "sheets":
            pages = s["pages"].get(st.id)
            if not pages:
                per_step[st.id] = {"uploaded": None}
                continue
            f = tmp / STEP_FILE[st.id]
            extract(src, pages, f)
            upload = {"file": s["drawings"], "pages": pages}
        else:
            if st.id not in ("plans", "schedules", "sequences"):
                per_step[st.id] = {"uploaded": None}
                continue
            f, upload = src, {"file": s["drawings"], "pages": "all"}
        it.add_file(st.id, STEP_FILE[st.id], f.read_bytes())
        t1 = time.time()
        try:
            steps.run(it, st.id, lambda m: None)
        except Exception as e:  # a crash is a result too
            per_step[st.id] = {"uploaded": upload, "crash": f"{type(e).__name__}: {e}"[:200]}
            continue
        facts = it.facts(st.id)
        cov = [f for f in facts if f["kind"] == "issue" and f["data"].get("severity") == "coverage"]
        qs = it.open_questions(st.id)
        per_step[st.id] = {
            "uploaded": upload, "secs": round(time.time() - t1, 1),
            "facts_by_kind": dict(Counter(f["kind"] for f in facts)),
            "main_kind": MAIN_KIND[st.id], "main_read": sum(1 for f in facts if f["kind"] == MAIN_KIND[st.id]),
            "coverage_issues": [c["label"] for c in cov],
            "questions": len(qs),
            "question_samples": [q["ask"]["q"] for q in qs[:12]],
            "question_kinds": dict(Counter(q["kind"] for q in qs)),
            "log": it.log(st.id)[-6:],
        }
    live = lambda k: it.facts(kind=k, live=True)  # noqa: E731
    floors = sorted({f["data"].get("floor") or f["label"] for f in live("floor")}, key=str)
    headline = {"floors": len(floors), "rooms": len(live("room")), "equipment": len(live("equipment")),
                "equipment_by_class": dict(Counter(f["data"].get("class") or f["data"].get("type") or "?"
                                                   for f in live("equipment")).most_common(12)),
                "sequences": len(live("sequence")), "points": len(live("point")),
                "coverage_issues": sum(len(v.get("coverage_issues", [])) for v in per_step.values()),
                "questions": sum(v.get("questions", 0) for v in per_step.values()),
                "silent_steps": [k for k, v in per_step.items() if v.get("uploaded") and not v.get("crash")
                                 and not v["main_read"] and not v["questions"]],
                "crashes": [k for k, v in per_step.items() if v.get("crash")]}
    out = {"set": slug, "role": s["role"], "mode": mode, "secs": round(time.time() - t0, 1), "headline": headline}
    if s["role"] == "dev":
        out["floors_read"] = floors
        out["steps"] = per_step
    return out


def main() -> None:
    check("--fetch" in sys.argv)
    modes = ("sheets",) if "--sheets" in sys.argv else ("sheets", "whole set")
    res = [run(slug, mode) for slug in SETS for mode in modes]
    out = ROOT / "reports/real_sets.json"
    keep = {(r["set"], r["mode"]): r for r in (json.loads(out.read_text()) if out.exists() else [])}
    keep.update({(r["set"], r["mode"]): r for r in res})  # --sheets keeps the last whole-set results
    for r in keep.values():
        if SETS[r["set"]]["role"] == "heldout":  # headline counts only, never a breakdown
            r["headline"].pop("equipment_by_class", None)
    out.write_text(json.dumps([keep[k] for k in sorted(keep)], indent=1, ensure_ascii=False))
    for r in res:
        print(f"\n## {r['set']} ({r['role']}) — {r['mode']} ({r['secs']}s)")
        print("   ", {k: v for k, v in r["headline"].items() if k != "equipment_by_class"})
        for k, v in r.get("steps", {}).items():
            if v.get("uploaded"):
                print(f"   {k:10s} read {v.get('main_read', '-')} {MAIN_KIND[k]}, {v.get('questions', '-')} questions,"
                      f" {len(v.get('coverage_issues', []))} coverage issues {v.get('crash', '')}")


if __name__ == "__main__":
    main()
