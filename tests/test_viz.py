import json
from pathlib import Path

import pytest

from projectmodel import review
from projectmodel.adapters.haystack import read_blind_export
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import Mapper
from projectmodel.viz import graph_payload, render_html

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture
def store(km):
    s = Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), s, P)
    return s


def test_instance_layer_matches_store(store):
    g = graph_payload(store, P)
    assert g["counts"]["nodes"] == {"equipment": 184, "point": 1842}
    ids = {n["id"] for n in g["nodes"]}
    assert all(link["source"] in ids and link["target"] in ids for link in g["links"])
    assert {"hasPart", "hasPoint", "feeds"} <= set(g["counts"]["links"])
    assert all(n["prov"]["method"] for n in g["nodes"])


def test_model_layer_links_every_typed_instance(store, km):
    g = graph_payload(store, P, km)
    classes = {n["cls"] for n in g["nodes"] if n["kind"] == "class"}
    typed = [n for n in g["nodes"] if n["layer"] == "instance" and n["cls"] in km.classes]
    assert g["counts"]["links"]["type"] == len(typed)
    assert {"VAV", "AHU", "Point", "Equipment"} <= classes  # used classes plus their ancestors
    assert sum(n["attrs"]["instances"] for n in g["nodes"] if n["kind"] == "class") == len(typed)
    # subClassOf links follow the model's own hierarchy
    parent = {link["source"][4:]: link["target"][4:] for link in g["links"] if link["rel"] == "subClassOf"}
    assert parent["VAV"] == km.classes["VAV"].subset_parent


def test_rejected_link_left_out(store):
    e = store.edges(P, "hasPoint")[0]
    other = next(n["id"] for n in store.nodes(P, "equipment") if n["id"] != e["src"])
    review.move_points(store, P, [e["dst"]], other, "ana")
    g = graph_payload(store, P)
    hp = [(link["source"], link["prov"]["method"]) for link in g["links"]
          if link["rel"] == "hasPoint" and link["target"] == e["dst"]]
    assert hp == [(other, "human")]


def test_render_embeds_data_safely(store):
    g = graph_payload(store, P)
    g["nodes"][0]["label"] = "</script><b>x"
    html = render_html(g)
    assert "/*__DATA__*/" not in html and "</script><b>" not in html
    start = html.index("const DATA = ") + len("const DATA = ")
    data = json.loads(html[start:html.index(";\n", start)].replace("<\\/", "</"))
    assert data["nodes"][0]["label"] == "</script><b>x"
