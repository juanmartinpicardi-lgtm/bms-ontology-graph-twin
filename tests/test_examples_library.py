"""Example projects for the guided setup (intake/examples.py) and a project's documents (library.py)."""

from pathlib import Path

import pytest

from projectmodel import library
from projectmodel.intake import examples, steps
from projectmodel.intake.state import Intake


def test_three_examples_and_never_the_held_out_set():
    assert set(examples.EXAMPLES) == {"troop_d", "msu_mbb", "itd_d1_lab"}
    assert "liberty_boe" not in examples.EXAMPLES  # held out: never shown in the app (CLAUDE.md §5)


def test_every_example_document_belongs_to_a_step():
    ids = {s.id for s in steps.STEPS}
    for ex in examples.EXAMPLES.values():
        assert set(ex.docs) <= ids
        for d in ex.docs.values():
            assert bool(d.file) != bool(d.pages)  # a test-package file, or pages of the drawings


def test_real_sets_have_no_bms_export_and_say_why():
    for slug in ("msu_mbb", "itd_d1_lab"):
        assert examples.doc(slug, "bms") is None
        assert examples.doc(slug, "submittal").stand_in
    assert "BMS export" in examples.missing_note("bms")


def test_a_building_remembers_its_example_across_a_restart(tmp_path):
    it = Intake.create("MSU", root=tmp_path, example="msu_mbb")
    assert it.example == "msu_mbb"
    it.reset()
    assert Intake(it.slug, root=tmp_path).example == "msu_mbb"
    assert Intake.create("Own", root=tmp_path).example is None


@pytest.mark.skipif(not steps.TEST_PACKAGE.exists(), reason="no test package")
def test_troop_d_files_come_from_the_test_package():
    assert examples.file_for("troop_d", "bms") == steps.TEST_PACKAGE / "5_bms_export.csv"
    assert examples.file_for("msu_mbb", "bms") is None


def test_category_guess():
    assert library.guess_category("M-101 Floor Plan Level 1.pdf") == "Floor plans"
    assert library.guess_category("Equipment schedules.pdf") == "Equipment schedules"
    assert library.guess_category("SOO AHU-1.docx") == "Sequences of operation"
    assert library.guess_category("site photo 3.jpg") == "Photos and site"
    assert library.guess_category("AHU-1 IOM manual.pdf") == "Manuals and datasheets"
    assert library.guess_category("random.bin") == "Other"


def test_library_add_list_recategorise_replace_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "LIBRARY", tmp_path / "library")
    monkeypatch.setattr(library, "RAW", tmp_path / "raw")
    monkeypatch.setattr(library, "DOCUMENTS", tmp_path / "documents")
    p = "nosuchsite/documents"
    d = library.add(p, "points list.csv", b"a,b\n1,2\n")
    assert d.category == "Points lists" and d.origin == "library"
    assert library.add(p, "copy.csv", b"a,b\n1,2\n").id == d.id  # the same content is kept once
    library.set_category(p, d.id, "BMS export")
    assert library.find(p, d.id).category == "BMS export"
    new = library.replace(p, library.find(p, d.id), "points list v2.csv", b"a,b\n3,4\n")
    assert new.name == "points list v2.csv" and new.path.read_bytes() == b"a,b\n3,4\n"
    assert new.category == "BMS export"
    library.delete(p, new)
    assert library.documents(p) == []


def test_source_data_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "RAW", tmp_path / "raw")
    monkeypatch.setattr(library, "LIBRARY", tmp_path / "library")
    monkeypatch.setattr(library, "DOCUMENTS", tmp_path / "documents")
    (tmp_path / "raw/haystack").mkdir(parents=True)
    (tmp_path / "raw/haystack/site.json").write_text("{}")
    (d,) = library.documents("site/names_paths")
    assert d.origin == "source" and not d.editable
    with pytest.raises(ValueError):
        library.delete("site/names_paths", d)
    assert Path(tmp_path / "raw/haystack/site.json").exists()
