"""Troop D synthetic test set: the generated answer key and BMS export are self-consistent."""
from collections import Counter

import pytest

from projectmodel.troop_d import build, bms_name, load_spec

BOX = {"vav", "vave", "fvav"}


@pytest.fixture(scope="module")
def model():
    return build(load_spec())


def test_counts(model):
    kinds = Counter(e.kind for e in model["equips"])
    assert (kinds["vav"], kinds["vave"], kinds["fvav"]) == (19, 19, 18)
    assert kinds["chiller"] == 2 and kinds["pump"] == 2 and kinds["ahu"] == 1


def test_ids_and_names_unique(model):
    points = [p for e in model["equips"] for p in e.points]
    assert len({p.id for p in points}) == len(points)
    assert len({p.bms_name for p in points}) == len(points)
    devices = {(e.trunk, e.address) for e in model["equips"] if e.address is not None and e.kind != "split"}
    assert len(devices) == sum(1 for e in model["equips"] if e.address is not None and e.kind != "split")


def test_every_box_has_a_room_on_a_known_floor(model):
    rooms = {num: floor for floor, rs in model["spec"]["rooms"].items() for num in rs}
    for e in model["equips"]:
        if e.kind in BOX:
            assert rooms.get(e.room) == e.floor, e.tag


def test_brick_classes_exist(model):
    brickschema = pytest.importorskip("brickschema")
    from rdflib import Namespace
    from rdflib.namespace import OWL, RDF
    brick = Namespace("https://brickschema.org/schema/Brick#")
    classes = set(brickschema.Graph(load_brick=True).subjects(RDF.type, OWL.Class))
    used = {e.brick_class for e in model["equips"]} | {p.brick_class for e in model["equips"] for p in e.points}
    assert {c for c in used if brick[c] not in classes} == set()


@pytest.mark.parametrize("tag,expected", [("VAVE07", "VAVE-07"), ("FVAV03", "FVAV-03"), ("AHU01", "AHU-1"),
                                          ("CH01a", "CH-1A"), ("EF-LAB1", "EF-LAB-1"), ("EF-RR", "EF-RR")])
def test_bms_names_differ_from_tags(tag, expected):
    assert bms_name(tag) == expected
