"""W2: Brick Turtle export with provenance, SHACL (Brick's shapes and our building rules), and the report the Complete
graph page reads."""
import json
from pathlib import Path

import pytest
import rdflib
from rdflib.namespace import RDF, RDFS, SH

from projectmodel.db.store import Edge, Node, Store
from projectmodel.export import PM, class_uri, export_project, load_export, load_shapes, node_uri, relation_uri, validate
from projectmodel.export import run as export_run
from projectmodel.export.brick import UNDECLARED, UNIT
from projectmodel.knowledge_model import BA, BRICK, REC, load_knowledge_model

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/kg.sqlite"
P = "test/site"
SRC = "setup:test"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


def n(id_, kind, cls, conf=0.95, **attrs):
    return Node(id_, kind, id_.split(":")[-1], cls, "plans.pdf", "page 1", "rule", conf, attrs=attrs)


def e(src, rel, dst, conf=0.95, **attrs):
    return Edge(src, rel, dst, "plans.pdf", "page 1", "rule", conf, attrs=attrs)


def small_store(nodes, edges) -> Store:
    """Confidence 0.95 is confirmed by the store's auto-accept, 0.5 stays proposed."""
    store = Store(":memory:")
    store.write_source(P, SRC, store.start_run(P, "test"), nodes, edges)
    return store


def building():
    """A tiny, valid building: an AHU feeding a VAV in a room, the VAV's points hosted by a controller on a trunk."""
    nodes = [n("unit:AHU1", "equipment", "AHU"), n("unit:VAV1", "equipment", "VAV"),
             n("room:101", "location", "Room"), n("floor:L1", "location", "Floor"),
             n("pt:ZNT", "point", "Zone_Air_Temperature_Sensor", unit="unit:DEG_F", units="°F"),
             n("pt:DPR", "point", "Damper_Command"), n("pt:SAT", "point", "Supply_Air_Temperature_Sensor"),
             n("ctrl:1", "controller", "Field_Controller"), n("net:FC-1", "network", "Field_Network")]
    edges = [e("unit:AHU1", "feeds", "unit:VAV1", medium="air"), e("unit:VAV1", "hasPoint", "pt:ZNT"),
             e("unit:VAV1", "hasPoint", "pt:DPR"), e("unit:AHU1", "hasPoint", "pt:SAT"),
             e("unit:VAV1", "serves", "room:101"), e("unit:AHU1", "hasLocation", "floor:L1"),
             e("floor:L1", "hasPart", "room:101"), e("pt:ZNT", "isHostedBy", "ctrl:1"),
             e("ctrl:1", "isOnNetwork", "net:FC-1"), e("ctrl:1", "controls", "unit:VAV1")]
    return nodes, edges


# --- export --------------------------------------------------------------------------------------------------------

def test_terms_come_from_the_knowledge_model(km):
    assert class_uri(km, "VAV") == BRICK.VAV
    assert class_uri(km, "Field_Controller") == BA.Field_Controller
    assert class_uri(km, "Unit_Heater") == BA.Unit_Heater
    # W1: locations are written as the rec: class that replaces Brick 1.4's deprecated one
    assert class_uri(km, "Room") == REC.Room and class_uri(km, "Floor") == REC.Level
    assert class_uri(km, "HVAC_Zone") == REC.HVACZone
    assert class_uri(km, "Not_A_Class") is None
    assert relation_uri(km, "hasPoint") == BRICK.hasPoint and relation_uri(km, "serves") == BA.serves
    assert relation_uri(km, "drives") == BA.drives and relation_uri(km, "isHostedBy") == BA.isHostedBy
    assert relation_uri(km, "madeUp") is None


def test_export_writes_brick_facts_with_provenance(km):
    store = small_store(*building())
    ex = export_project(store, P, km)
    g, prov = ex.graph, ex.prov
    vav, room, znt = node_uri(P, "unit:VAV1"), node_uri(P, "room:101"), node_uri(P, "pt:ZNT")
    assert (vav, RDF.type, BRICK.VAV) in g and (room, RDF.type, REC.Room) in g
    assert (vav, BA.serves, room) in g and (vav, BRICK.hasPoint, znt) in g
    assert (znt, BRICK.hasUnit, UNIT.DEG_F) in g and (znt, PM.unitText, rdflib.Literal("°F")) in prov
    # node provenance on the node itself
    assert str(prov.value(vav, PM.method)) == "rule" and float(prov.value(vav, PM.confidence)) == 0.95
    assert str(prov.value(vav, PM.status)) == "confirmed" and str(prov.value(vav, PM.sourceFile)) == "plans.pdf"
    assert str(prov.value(vav, PM.source)) == SRC and str(prov.value(vav, PM.id)) == "unit:VAV1"
    # edge provenance on a reified statement of exactly that triple
    st = [s for s in prov.subjects(RDF.type, RDF.Statement)
          if (s, RDF.subject, vav) in prov and (s, RDF.predicate, BA.serves) in prov]
    assert len(st) == 1 and (st[0], RDF.object, room) in prov
    assert str(prov.value(st[0], PM.method)) == "rule" and str(prov.value(st[0], PM.sourceRef)) == "page 1"
    feeds = next(s for s in prov.subjects(RDF.predicate, BRICK.feeds))
    assert str(prov.value(feeds, PM.medium)) == "air"
    # the facts graph is plain Brick: no provenance in it
    assert not set(g.predicates()) & {PM.method, PM.status, RDF.subject}
    assert ex.summary["nodes"] == 9 and ex.summary["edges"] == 10 and not ex.summary["edges_left_out"]


def test_statuses_and_left_out_edges(km):
    nodes, edges = building()
    nodes.append(n("pt:DAT", "point", "Discharge_Air_Temperature_Sensor", conf=0.5))  # stays proposed
    edges.append(e("unit:VAV1", "hasPoint", "pt:DAT"))  # confirmed edge to a proposed point
    edges.append(e("unit:VAV1", "feeds", "room:101", conf=0.5))  # a proposed edge
    store = small_store(nodes, edges)
    with store.conn:  # a person rejected the damper
        store.conn.execute("UPDATE nodes SET status = 'rejected' WHERE project = ? AND id = 'pt:DPR'", (P,))
    confirmed = export_project(store, P, km)
    ids = {str(o) for o in confirmed.prov.objects(None, PM.id)}
    assert "pt:DAT" not in ids and "pt:DPR" not in ids
    assert confirmed.summary["edges_left_out"] == {"hasPoint": 2}  # to the proposed DAT and the rejected damper
    everything = export_project(store, P, km, include_proposed=True)
    ids = {str(o) for o in everything.prov.objects(None, PM.id)}
    assert "pt:DAT" in ids and "pt:DPR" not in ids  # rejected rows never leave
    assert (node_uri(P, "unit:VAV1"), BRICK.feeds, node_uri(P, "room:101")) in everything.graph
    assert everything.summary["nodes_by_status"] == {"confirmed": 8, "proposed": 1}
    assert everything.summary["edges_left_out"] == {"hasPoint": 1}  # the edge to the rejected damper


def test_undeclared_terms_are_exported_and_listed(km):
    store = small_store([n("unit:X", "equipment", "Flux_Capacitor"), n("unit:Y", "equipment", "AHU")],
                        [e("unit:X", "levitates", "unit:Y")])
    ex = export_project(store, P, km)
    assert (node_uri(P, "unit:X"), RDF.type, UNDECLARED.Flux_Capacitor) in ex.graph
    assert (node_uri(P, "unit:X"), UNDECLARED.levitates, node_uri(P, "unit:Y")) in ex.graph
    assert ex.summary["undeclared"] == {"classes": ["Flux_Capacitor"], "relations": ["levitates"]}


def test_round_trip(km, tmp_path):
    store = small_store(*building())
    ex = export_project(store, P, km, include_proposed=True)
    path = ex.write(tmp_path / "x.ttl")
    back = load_export(path)
    assert len(back["nodes"]) == ex.summary["nodes"] and len(back["edges"]) == ex.summary["edges"]
    assert not back["statements_without_fact"] and back["ids_roundtrip"]
    assert back["nodes"]["room:101"] == str(REC.Room)
    assert ("unit:VAV1", str(BA.serves), "room:101") in back["edges"]
    # a statement whose triple was removed from the file is not counted as an edge
    g = rdflib.Graph().parse(path)
    g.remove((node_uri(P, "unit:VAV1"), BA.serves, node_uri(P, "room:101")))
    back = load_export(g.serialize(format="turtle"))
    assert len(back["edges"]) == ex.summary["edges"] - 1 and back["statements_without_fact"] == 1


# --- SHACL ---------------------------------------------------------------------------------------------------------

def rule(report, rid):
    return next(r for r in report["rules"] if r["id"] == rid)


def test_every_building_rule_is_small_and_explained():
    g = load_shapes()
    shapes = [s for s in g.subjects(RDF.type, SH.NodeShape) if str(s).startswith("urn:projectmodel:shapes#")]
    assert len(shapes) >= 10
    for s in shapes:
        assert g.value(s, RDFS.label) and len(str(g.value(s, RDFS.comment) or "")) > 40, s


def test_a_valid_building_passes_every_building_rule(km):
    report = validate(export_project(small_store(*building()), P, km), km)
    building_rules = [r for r in report["rules"] if r["origin"] == "building"]
    assert building_rules and not [r for r in building_rules if r["failed"]], \
        [(r["id"], r["failing"]) for r in building_rules if r["failed"]]
    assert rule(report, "shape:VAVHasZoneTemperature")["passed"] == 1
    assert rule(report, "shape:HostedByController")["passed"] == 1
    assert rule(report, "shape:ServesLocation")["passed"] == 1
    assert rule(report, "shape:TemperatureUnit")["passed"] == 2  # °F passes; no unit is not checked


def test_building_rules_catch_gaps(km):
    nodes, edges = building()
    nodes += [n("unit:VAV2", "equipment", "RVAV"),  # an RVAV is a VAV: needs a zone temperature sensor
              n("pt:ORPHAN", "point", "Fan_Status"),  # on no equipment
              n("pt:SP", "point", "Air_Temperature_Setpoint", unit="unit:IN_H2O")]  # a temperature in in.wc
    edges = [x for x in edges if x.rel != "feeds"]
    edges += [e("unit:AHU1", "hasPoint", "pt:SP"),
              e("unit:VAV1", "hasPoint", "pt:SAT"),  # SAT now on two units
              e("unit:AHU1", "hasLocation", "unit:VAV1"),  # a place that is a unit
              e("pt:DPR", "isHostedBy", "unit:AHU1"),  # hosted by a unit, not a controller
              e("unit:AHU1", "feeds", "room:101"),  # feeds into a room: that is serves
              e("pt:ZNT", "drives", "unit:VAV1")]  # a control relation ending on equipment
    report = validate(export_project(small_store(nodes, edges), P, km), km)
    failing = {r["id"]: {f["id"] for f in r["failing"]} for r in report["rules"] if r["origin"] == "building"}
    assert failing["shape:VAVHasZoneTemperature"] == {"unit:VAV2"}
    assert failing["shape:PointOnOneEquipment"] == {"pt:ORPHAN", "pt:SAT"}
    assert failing["shape:HasLocationIsLocation"] == {"unit:AHU1"}
    assert failing["shape:HostedByController"] == {"pt:DPR"}
    assert failing["shape:FeedsBetweenEquipment"] == {"unit:AHU1"}
    assert failing["shape:ControlBetweenPoints"] == {"pt:ZNT"}
    assert failing["shape:TemperatureUnit"] == {"pt:SP"}
    assert "unit:VAV2" in failing["shape:EquipmentHasPoints"]
    assert not report["conforms"]
    r = rule(report, "shape:PointOnOneEquipment")
    assert r["targets"] == r["passed"] + r["failed"] and r["failing"][0]["messages"]


def test_brick_shapes_run(km):
    """Brick's own shapes must really run: given an extra shapes graph, shifty skips the shapes inside the data, so
    a regression here would make every Brick check pass silently."""
    nodes, edges = building()
    edges.append(e("unit:AHU1", "hasPoint", "unit:VAV1"))  # equipment as a point: Brick's Equipment shape refuses
    report = validate(export_project(small_store(nodes, edges), P, km), km)
    brick = [r for r in report["rules"] if r["origin"] == "brick" and r["severity"] == "violation"]
    assert any(f["id"] == "unit:AHU1" for r in brick for f in r["failing"]), brick
    assert report["totals"]["brick_violations"] >= 1


# --- the command and its report -------------------------------------------------------------------------------------

@pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")
def test_alpha_export_and_report(km, tmp_path):
    rep = export_run.run("alpha", km, out=tmp_path / "a.ttl", report_dir=tmp_path)
    assert rep["roundtrip"]["ok"] and rep["project"] == "alpha/names_paths" and rep["scope"] == "confirmed"
    assert rep["export"]["nodes"] > 0 and not rep["export"]["undeclared"]["classes"]
    assert not rep["export"]["undeclared"]["relations"]
    export_run.run("alpha", km, include_proposed=True, out=tmp_path / "b.ttl", report_dir=tmp_path)
    doc = json.loads((tmp_path / "alpha.json").read_text())
    assert set(doc["scopes"]) == {"confirmed", "with_proposed"}  # a run keeps the other scope
    assert doc["scopes"]["with_proposed"]["export"]["nodes"] >= rep["export"]["nodes"]
    assert "pass" in export_run.text(rep) and "round trip: ok" in export_run.text(rep)


def test_troop_d_export_covers_the_riser(km, tmp_path):
    rep = export_run.run("troop_d", km, include_proposed=True, out=tmp_path / "t.ttl", report_dir=tmp_path)
    ex = rep["export"]
    assert rep["roundtrip"]["ok"] and not ex["undeclared"]["classes"] and not ex["undeclared"]["relations"]
    assert ex["nodes_by_kind"].get("controller") and ex["nodes_by_kind"].get("network")
    assert {"isHostedBy", "isOnNetwork", "controls", "serves", "hasPoint"} <= set(ex["edges_by_relation"])
    hosted = rule(rep, "shape:HostedByController")
    assert hosted["targets"] > 500 and hosted["failed"] == 0  # every point's host is one controller
    assert rule(rep, "shape:ControllerOnNetwork")["failed"] == 0
    assert ex["with_unit"].get("point", 0) > 500


def test_committed_reports_are_readable():
    reports = export_run.load_reports()
    assert {"alpha", "troop_d"} <= set(reports)
    for name, doc in reports.items():
        for scope, rep in doc["scopes"].items():
            assert scope in export_run.SCOPES.values() and rep["roundtrip"]["ok"], (name, scope)
            assert all({"label", "targets", "passed", "failed", "failing"} <= set(r) for r in rep["rules"])
            assert rep["turtle"].startswith("data/export/") and str(ROOT) not in json.dumps(rep)


@pytest.mark.skipif(not DB.exists(), reason="run scripts/run_mapper.py first")
def test_complete_graph_page_shows_the_shacl_report():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "src/projectmodel/app/views/complete_graph.py"), default_timeout=120).run()
    assert not at.exception
    assert any("SHACL" in h.value for h in at.header)
    assert at.dataframe and any(m.label == "Building rules passing" for m in at.metric)
    at.selectbox(key="shacl_project").set_value("troop_d").run()
    assert not at.exception and any(m.label == "Nodes exported" for m in at.metric)
