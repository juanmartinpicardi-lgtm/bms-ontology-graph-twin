"""The raw record: the one shape every source adapter produces and the mapper consumes.

Fields follow CLAUDE.md section 3, plus `source_file` / `source_row` so every fact stays
traceable to where it came from. Fields a source cannot supply are None, never guessed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RawRecord:
    source_id: str  # id of the point within its source (unique per source file)
    source_system: str  # e.g. "haystack-blind/names_only"; later "niagara", "cpo"
    source_file: str
    source_row: int  # 1-based data row in source_file (header excluded)
    name: str
    display_name: str | None = None
    path: str | None = None  # folder chain, "/"-separated
    device_id: str | None = None
    object_id: str | None = None
    units: str | None = None
    kind: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
