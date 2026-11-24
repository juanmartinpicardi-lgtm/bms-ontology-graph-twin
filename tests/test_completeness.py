"""The completeness cards on top of the twin (completeness.py)."""

from projectmodel.completeness import completeness
from projectmodel.db.store import Edge, Node, Store


def node(store, id, kind, cls=None, conf=1.0, method="rule"):
    status = "confirmed" if method == "human" else None  # a person's decision; else the store decides
    store.write_source("p", f"t:{id}", 1, [Node(id, kind, id, cls, "f", "r", method, conf, status=status)])


def edge(store, src, rel, dst):
    store.write_source("p", f"t:{src}-{rel}-{dst}", 1, edges=[Edge(src, rel, dst, "f", "r", "rule", 1.0)])


def test_cards_count_what_they_say(tmp_path):
    s = Store(tmp_path / "kg.sqlite")
    node(s, "ahu", "equipment", "AHU")
    node(s, "vav", "equipment", "VAV")
    node(s, "x", "equipment", "Equipment", conf=0.5)            # not classed, not linked, proposed: not trusted
    node(s, "t1", "point", "Temp_Sensor")
    node(s, "t2", "point", "Temp_Sensor", conf=0.4, method="human")  # a person decided: trusted
    node(s, "t3", "point", None, conf=0.3)                      # on no equipment, to review
    edge(s, "ahu", "feeds", "vav")
    edge(s, "vav", "hasPoint", "t1")
    edge(s, "vav", "hasPoint", "t2")
    payload = {"equip": [{"id": "ahu", "floor_hint": "L1"}, {"id": "vav", "room": "r1"}, {"id": "x"}],
               "levels": [{"id": "L1"}], "source": "graph"}
    cards = {c.key: c for c in completeness(s, "p", payload)}
    assert round(cards["trusted"].share, 2) == round(4 / 6, 2) and cards["trusted"].sub.startswith("2 to review")
    assert round(cards["grouped"].share, 2) == 0.67 and cards["grouped"].sub == "2 of 3 points"
    assert round(cards["classed"].share, 2) == 0.67
    assert round(cards["linked"].share, 2) == 0.67 and "1 feeds" in cards["linked"].sub
    assert round(cards["twin"].share, 2) == 0.67 and cards["twin"].tone == "warn"
    assert "floors from the documents" in cards["twin"].sub


def test_an_empty_project_has_zero_cards_and_no_twin_card_without_a_payload(tmp_path):
    cards = completeness(Store(tmp_path / "kg.sqlite"), "none")
    assert [c.key for c in cards] == ["trusted", "grouped", "classed", "linked", "controlled", "units", "site"]
    assert all(c.share == 0 and c.tone == "bad" for c in cards)
