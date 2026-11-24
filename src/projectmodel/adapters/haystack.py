"""Haystack adapter: blind exports of the Haystack example sites -> raw records.

In Phase 0 the "export" the pipeline receives is a blind CSV built from a Haystack site
(see data/blind/README.md), so this adapter reads those, never the tagged source. It is thin
on purpose: one CSV row becomes one RawRecord, with no interpretation of the name.

Haystack has no BACnet device/object ids or kinds in the blind inputs, so those stay None. An export may add a
`units` column (the point's unit as written, e.g. "°F"): it is passed through as is, never interpreted here.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..records import RawRecord

VARIANTS = {
    "names_only": ["blind_id", "name"],
    "names_paths": ["blind_id", "name", "path"],
}


def read_blind_export(path: Path) -> list[RawRecord]:
    path = Path(path)
    if "ground_truth" in path.resolve().parts:
        raise ValueError(f"refusing to read answers as mapper input: {path}")
    variant = path.stem
    if variant not in VARIANTS:
        raise ValueError(f"unknown blind export {path.name}; expected one of {sorted(VARIANTS)}")

    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames not in (VARIANTS[variant], VARIANTS[variant] + ["units"]):
            raise ValueError(f"{path}: columns {reader.fieldnames}, expected {VARIANTS[variant]} (+ units)")
        records, seen = [], set()
        for row_no, row in enumerate(reader, 1):
            sid = row["blind_id"]
            if sid in seen:
                raise ValueError(f"{path}:{row_no}: duplicate blind_id {sid}")
            seen.add(sid)
            records.append(RawRecord(
                source_id=sid,
                source_system=f"haystack-blind/{variant}",
                source_file=str(path),
                source_row=row_no,
                name=row["name"],
                path=row.get("path") or None,
                units=(row.get("units") or "").strip() or None,
            ))
    return records
