from pathlib import Path

import pytest

from projectmodel import review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.projects import label, list_projects, site_of, summaries

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def store():
    km = load_knowledge_model()
    s = Store(":memory:")
    for site, variant in [("alpha", "names_only"), ("alpha", "names_paths")]:
        Mapper(km).run(read_blind_export(ROOT / f"data/blind/{site}/{variant}.csv"), s, f"{site}/{variant}")
    return s


def test_list_projects_by_site_richest_input_first(store):
    assert list_projects(store) == ["alpha/names_paths", "alpha/names_only"]


def test_labels_and_roles():
    assert label("alpha/names_paths") == "Alpha · Names + folders"
    assert site_of("alpha/names_only").role == "dev"
    assert site_of("gamma/x").name == "Gamma"  # unknown sites still get a readable name


def test_summaries(store):
    s = summaries(store)
    assert s["alpha/names_paths"]["nodes"] == {"equipment": 184, "point": 1842}
    assert s["alpha/names_paths"]["links"]["feeds"] > 0 and s["alpha/names_paths"]["revision"] == 1
    assert s["alpha/names_paths"]["human"] == 0
    pid = store.nodes("alpha/names_paths", "point")[0]["id"]
    review.accept(store, "alpha/names_paths", [pid], "ana")
    assert summaries(store)["alpha/names_paths"]["human"] == 1
