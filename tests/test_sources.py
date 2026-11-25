"""Many sources in one project (db/store.py): proposed by default, each source replaces only its own rows, agreement
confirms, conflicts wait for review, aliases resolve one unit across sources, and older databases migrate."""

import json
import sqlite3

from projectmodel import review
from projectmodel.db.store import AutoAccept, Claim, Edge, Node, Store

P = "site/documents"


def node(id, cls, conf=0.5, src="f.csv", kind="equipment", aliases=(), status=None, method="rule"):
    return Node(id, kind, id, cls, src, "row 1", method, conf, aliases=list(aliases), status=status)


def edge(s, rel, d, conf=0.5, src="f.csv", **attrs):
    return Edge(s, rel, d, src, "row 1", "rule", conf, attrs)


def rows(store, table="nodes"):
    return {(r["id"] if table == "nodes" else (r["src"], r["rel"], r["dst"])): r
            for r in (store.nodes(P) if table == "nodes" else store.edges(P))}


def test_machine_rows_are_proposed_unless_the_auto_accept_rule_confirms_them():
    s = Store(":memory:")
    s.write_source(P, "a", 1, [node("low", "AHU", 0.85), node("high", "AHU", 0.95),
                               node("held", "AHU", 0.99, status="proposed")])
    n = rows(s)
    assert (n["low"]["status"], n["low"]["confirmed_by"]) == ("proposed", None)
    assert (n["high"]["status"], n["high"]["confirmed_by"]) == ("confirmed", "auto")  # told apart from a person
    assert n["held"]["status"] == "proposed"  # the writer asked a question: a person answers it
    off = Store(":memory:", auto=AutoAccept(threshold=None))
    off.write_source(P, "a", 1, [node("high", "AHU", 0.99)])
    assert rows(off)["high"]["status"] == "proposed"


def test_rerunning_one_source_leaves_other_sources_and_people_decisions_intact():
    s = Store(":memory:")
    s.write_source(P, "schedules", 1, [node("ahu", "AHU"), node("vav", "VAV"), node("gone", "Pump")],
                   [edge("ahu", "feeds", "vav", medium="air")])
    s.write_source(P, "bms", 1, [node("pt1", "Temp_Sensor", kind="point", src="bms.csv")],
                   [edge("vav", "hasPoint", "pt1", src="bms.csv")])
    review.fix_class(s, _km(), P, ["vav"], "VAV", "sam")  # a person's decision
    before = {k: tuple(v) for k, v in rows(s).items() if k != "gone"}
    out = s.write_source(P, "schedules", 2, [node("ahu", "AHU", 0.6), node("vav", "AHU")],
                         [edge("ahu", "feeds", "vav", medium="air")])
    n, e = rows(s), rows(s, "edges")
    assert "gone" not in n and out["deleted"] == 1
    assert n["ahu"]["revision"] == 2 and n["ahu"]["confidence"] == 0.6
    assert tuple(n["pt1"]) == before["pt1"] and ("vav", "hasPoint", "pt1") in e  # the BMS's rows are untouched
    assert (n["vav"]["class"], n["vav"]["method"], n["vav"]["source"]) == ("VAV", "human", "review")  # kept
    assert n["vav"]["confirmed_by"] == "human"
    s.remove_source(P, "bms")
    assert "pt1" not in rows(s) and "ahu" in rows(s)


def test_a_row_passes_to_another_source_when_its_owner_stops_stating_it():
    s = Store(":memory:")
    s.write_source(P, "schedules", 1, [node("ahu", "AHU", 0.7)])
    s.write_source(P, "plans", 1, [node("ahu", "AHU", 0.6, src="plan.pdf")])
    assert rows(s)["ahu"]["source"] == "schedules"
    out = s.write_source(P, "schedules", 2, [])
    r = rows(s)["ahu"]
    assert out["released"] == 1 and (r["source"], r["source_file"], r["confidence"]) == ("plans", "plan.pdf", 0.6)


def test_two_sources_agreeing_wait_for_the_expert_with_a_note_and_disagreeing_ones_for_review():
    """Agreement is the expert's call (plan §8.5): the fact stays proposed, noted with the agreeing sources and their
    combined confidence; review.accept_agreed accepts those in one go."""
    s = Store(":memory:")
    s.write_source(P, "schedules", 1, [node("ahu", "AHU"), node("vav", "VAV"), node("p", "Temp_Sensor", kind="point")],
                   [edge("ahu", "feeds", "vav", medium="air"), edge("vav", "hasPoint", "p")])
    s.write_source(P, "plans", 1, [node("ahu", "AHU", src="plan.pdf"), node("vav", "FCU", src="plan.pdf")])
    s.write_source(P, "bms", 1, [node("vav2", "VAV")],
                   [edge("ahu", "feeds", "vav", src="bms.csv", medium="air"), edge("vav2", "hasPoint", "p")])
    n, e = rows(s), rows(s, "edges")
    assert (n["ahu"]["status"], n["ahu"]["confirmed_by"]) == ("proposed", None)
    ahu = json.loads(n["ahu"]["attrs"])
    assert ahu["agree"] == ["plans", "schedules"] and ahu["agree_confidence"] == 0.75  # 1 - 0.5 * 0.5
    assert n["vav"]["status"] == "proposed"
    c = json.loads(n["vav"]["attrs"])["conflict"][0]
    assert (c["source"], c["class"], c["source_file"]) == ("plans", "FCU", "plan.pdf")
    assert e[("ahu", "feeds", "vav")]["status"] == "proposed"
    assert json.loads(e[("ahu", "feeds", "vav")]["attrs"])["agree"] == ["bms", "schedules"]
    for key in (("vav", "hasPoint", "p"), ("vav2", "hasPoint", "p")):  # a point on two equipment: both kept, held
        assert e[key]["status"] == "proposed" and json.loads(e[key]["attrs"])["conflict"]
    a = s.agreement(P)
    assert (a["stated_twice"], a["agree"], a["agree_open"], a["agreed"], a["conflicts"]) == (3, 2, 2, 0, 3)
    assert [x["id"] for x in review.queue(s, P)][:3] == ["vav", "vav2|hasPoint|p", "vav|hasPoint|p"]
    q = {x["id"]: x for x in review.queue(s, P)}
    assert q["ahu"]["agree"] == ["plans", "schedules"] and q["ahu"]["agree_confidence"] == 0.75
    assert {x["id"] for x in review.agreed(s, P)} == {"ahu", "ahu|feeds|vav"}  # agreeing, no conflict
    assert review.agreed(s, P, min_confidence=0.8) == []
    assert review.accept_agreed(s, P, "expert") == 2
    n, e = rows(s), rows(s, "edges")
    assert (n["ahu"]["status"], n["ahu"]["confirmed_by"], n["ahu"]["method"]) == ("confirmed", "human", "human")
    assert e[("ahu", "feeds", "vav")]["confirmed_by"] == "human" and n["vav"]["status"] == "proposed"


def test_the_old_agreement_rule_can_be_brought_back():
    s = Store(":memory:", auto=AutoAccept(agreement=2))
    s.write_source(P, "schedules", 1, [node("ahu", "AHU")])
    s.write_source(P, "plans", 1, [node("ahu", "AHU", src="plan.pdf")])
    assert (rows(s)["ahu"]["status"], rows(s)["ahu"]["confirmed_by"]) == ("confirmed", "agreement")


def test_claims_count_but_never_create_rows():
    s = Store(":memory:")
    s.write_source(P, "schedules", 1, [node("ahu", "AHU")])
    s.write_source(P, "bms", 1, claims=[Claim("ahu", "bms.csv", "row 3", "rule", 0.9, aliases=[("bms_name", "AHU_1")]),
                                        Claim("nobody", "bms.csv", "row 4", "rule", 0.9)])
    assert set(rows(s)) == {"ahu"} and json.loads(rows(s)["ahu"]["attrs"])["sources"] == ["bms", "schedules"]
    assert s.resolve(P, "bms_name", "AHU_1") == "ahu"


def test_a_new_node_resolves_to_an_existing_one_through_aliases():
    s = Store(":memory:")
    s.write_source(P, "schedules", 1, [node("unit:ahu1", "AHU", aliases=[("schedule_tag", "AHU-1")])])
    s.write_source(P, "submittal", 1, [node("ctrl:DEV3104", "AHU", aliases=[("schedule_tag", "AHU-1"),
                                                                           ("submittal_ref", "DEV3104")])],
                   [edge("ctrl:DEV3104", "hasPoint", "pt:x")])
    assert set(rows(s)) == {"unit:ahu1"} and ("unit:ahu1", "hasPoint", "pt:x") in rows(s, "edges")
    assert json.loads(rows(s)["unit:ahu1"]["attrs"])["agree"] == ["schedules", "submittal"]
    assert s.resolve(P, "submittal_ref", "DEV3104") == s.resolve(P, "schedule_tag", "AHU-1") == "unit:ahu1"


def test_review_actions_take_rows_out_of_the_queue_and_survive_reruns():
    s = Store(":memory:")
    s.write_source(P, "a", 1, [node("e", "AHU"), node("p", "Temp_Sensor", kind="point")], [edge("e", "hasPoint", "p")])
    assert len(review.queue(s, P)) == 3 and len(review.queue(s, P, kind="point")) == 1
    review.accept(s, P, ["p"], "sam")
    review.reject_edges(s, P, [("e", "hasPoint", "p")], "sam")
    assert [x["id"] for x in review.queue(s, P)] == ["e"]
    s.write_source(P, "a", 2, [node("e", "AHU"), node("p", "Temp_Sensor", kind="point")], [edge("e", "hasPoint", "p")])
    e = rows(s, "edges")[("e", "hasPoint", "p")]
    assert (e["status"], e["source"]) == ("rejected", "review") and [x["id"] for x in review.queue(s, P)] == ["e"]


def test_an_older_database_migrates(tmp_path):
    db = tmp_path / "kg.sqlite"
    c = sqlite3.connect(db)
    cols = ("project TEXT, {k}, source_file TEXT, source_ref TEXT, method TEXT, confidence REAL, status TEXT,"
            " revision INTEGER, attrs TEXT DEFAULT '{{}}'")
    c.execute(f"CREATE TABLE nodes ({cols.format(k='id TEXT, kind TEXT, label TEXT, class TEXT')},"
              " PRIMARY KEY (project, id))")
    c.execute(f"CREATE TABLE edges ({cols.format(k='src TEXT, rel TEXT, dst TEXT')},"
              " PRIMARY KEY (project, src, rel, dst))")
    c.executemany("INSERT INTO nodes VALUES ('alpha/names_paths', ?, 'point', ?, 'Temp_Sensor', ?, '1', ?, ?,"
                  " 'confirmed', 3, '{}')",
                  [("a", "a", "/x/data/blind/alpha/names_paths.csv", "rule", 0.5),
                   ("b", "b", "/x/data/blind/alpha/names_paths.csv", "template", 0.95),
                   ("c", "c", "review", "human", 0.3)])
    c.execute("INSERT INTO edges VALUES ('alpha/names_paths', 'e', 'drives', 'a', 'seq.yaml', 's1', 'document', 0.5,"
              " 'confirmed', 3, '{}')")
    c.commit()
    c.close()
    s = Store(db)
    n = {r["id"]: r for r in s.nodes("alpha/names_paths")}
    assert {k: (r["source"], r["status"], r["confirmed_by"]) for k, r in n.items()} == {
        "a": ("mapper:names_paths.csv", "proposed", None), "b": ("mapper:names_paths.csv", "confirmed", "auto"),
        "c": ("review", "confirmed", "human")}
    assert s.edges("alpha/names_paths")[0]["source"] == "document:seq.yaml"
    assert len(s.claims("alpha/names_paths")) == 3  # every machine row is its source's claim; decisions are not
    # The mapper's next run owns the migrated rows: it replaces them and leaves the document and the decision.
    s.write_source("alpha/names_paths", "mapper:names_paths.csv", 4, [Node("a", "point", "a", "Temp_Sensor", "n.csv",
                                                                          "1", "rule", 0.5)])
    assert {r["id"] for r in s.nodes("alpha/names_paths")} == {"a", "c"} and s.edges("alpha/names_paths")
    Store(db)  # opening again changes nothing
    assert {r["id"] for r in Store(db).nodes("alpha/names_paths")} == {"a", "c"}


def _km():
    class C:
        kind = "equipment"

    class KM:
        classes = {"VAV": C(), "AHU": C()}
    return KM()
