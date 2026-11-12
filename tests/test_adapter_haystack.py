import csv
from pathlib import Path

import pytest

from projectmodel.adapters.haystack import read_blind_export

ROOT = Path(__file__).resolve().parents[1]
SITES = ["alpha"]
VARIANTS = ["names_only", "names_paths"]


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize("variant", VARIANTS)
def test_every_point_becomes_one_record(site, variant):
    src = ROOT / "data/blind" / site / f"{variant}.csv"
    with src.open() as f:
        rows = list(csv.DictReader(f))
    with (ROOT / "data/ground_truth" / site / "blind_key.csv").open() as f:
        key_ids = [r["blind_id"] for r in csv.DictReader(f)]

    records = read_blind_export(src)
    assert len(records) == len(rows) == len(key_ids)
    assert [r.source_id for r in records] == key_ids
    for i, (rec, row) in enumerate(zip(records, rows), 1):
        assert rec.source_row == i and rec.source_file == str(src)
        assert rec.source_system == f"haystack-blind/{variant}"
        assert rec.name == row["name"]
        assert rec.path == (row.get("path") or None)
        assert rec.device_id is rec.object_id is rec.units is rec.kind is rec.display_name is None
        assert rec.extra == {}


def test_paths_only_in_path_variant():
    only = read_blind_export(ROOT / "data/blind/alpha/names_only.csv")
    paths = read_blind_export(ROOT / "data/blind/alpha/names_paths.csv")
    assert all(r.path is None for r in only)
    assert all(r.path for r in paths)


def test_refuses_ground_truth_and_unknown_files(tmp_path):
    with pytest.raises(ValueError, match="answers"):
        read_blind_export(ROOT / "data/ground_truth/alpha/points.csv")
    other = tmp_path / "points.csv"
    other.write_text("blind_id,name\npt-1,x\n")
    with pytest.raises(ValueError, match="unknown blind export"):
        read_blind_export(other)


def test_rejects_extra_columns_and_duplicates(tmp_path):
    bad = tmp_path / "names_only.csv"
    bad.write_text("blind_id,name,equipRef\npt-1,SAT,a-0001\n")
    with pytest.raises(ValueError, match="columns"):
        read_blind_export(bad)
    bad.write_text("blind_id,name\npt-1,SAT\npt-1,RAT\n")
    with pytest.raises(ValueError, match="duplicate"):
        read_blind_export(bad)
