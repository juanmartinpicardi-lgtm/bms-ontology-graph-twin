import json
from pathlib import Path

import pytest
import yaml

from projectmodel.adapters.haystack import read_blind_export
from projectmodel.conventions import ConventionError, apply_conventions, load_layers, scopes_for
from projectmodel.db.store import Store
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.mapper.pipeline import HINT_CONFIDENCE, Mapper
from projectmodel.records import RawRecord
from projectmodel.scoring.score import load_ground_truth, score_project

ROOT = Path(__file__).resolve().parents[1]
P = "alpha/names_paths"


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


def write(d: Path, scope: str, **body) -> None:
    f = d / f"{scope}.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(yaml.safe_dump({"scope": scope, **body}))


def merged(km, d, scopes):
    return apply_conventions(km, load_layers(scopes, d))


# --- layering ------------------------------------------------------------------------------------

def test_layer_order_is_contractor_customer_site(km, tmp_path):
    write(tmp_path, "site/s", abbreviations={"zz": ["supply"]})
    write(tmp_path, "contractor/c", abbreviations={"zz": ["return"]})
    write(tmp_path, "customer/k", abbreviations={"zz": ["exhaust"]})
    layers = load_layers(["site/s", "contractor/c", "customer/k"], tmp_path)
    assert [la.scope for la in layers] == ["contractor/c", "customer/k", "site/s"]
    m = apply_conventions(km, layers)
    assert m.name_rules.expand("zz") == [["supply"]]                 # site, the last layer, wins
    assert m.abbreviation_origin["zz"] == "site/s:abbreviations.zz"
    assert m.conventions == ["contractor/c", "customer/k", "site/s"]


def test_override_vs_extend(km, tmp_path):
    assert km.name_rules.expand("evap") == [["evaporator"]]
    vav_patterns = len(km.templates["vav"].name_patterns)
    write(tmp_path, "contractor/c", abbreviations={"evap": ["exhaust"]},
          equipment_patterns={"vav": [r"\bZN[-_ ]?\d"]},
          class_hints=[{"pattern": "^A$", "class": "Sensor"}, {"pattern": "^B$", "class": "Sensor"}])
    write(tmp_path, "site/s", equipment_patterns={"vav": [r"\bZONE BOX\b"]},
          class_hints=[{"pattern": "^B$", "class": "Temperature_Sensor"}, {"pattern": "^C$", "class": "Sensor"}])
    m = merged(km, tmp_path, ["contractor/c", "site/s"])
    assert m.name_rules.expand("evap") == [["exhaust"]]              # abbreviations: override
    assert len(m.templates["vav"].name_patterns) == vav_patterns + 2  # patterns: extend
    assert m.templates["vav"].matches_name("ZN-3")
    # hints: extend, later layer first, same pattern text replaced
    assert [(h.pattern.pattern, h.cls, h.origin) for h in m.class_hints] == [
        ("^B$", "Temperature_Sensor", "site/s:class_hints[0]"), ("^C$", "Sensor", "site/s:class_hints[1]"),
        ("^A$", "Sensor", "contractor/c:class_hints[0]")]
    # the base model is untouched
    assert km.name_rules.expand("evap") == [["evaporator"]]
    assert len(km.templates["vav"].name_patterns) == vav_patterns and not km.templates["vav"].matches_name("ZN-3")
    assert km.class_hints == [] and km.conventions == []


def test_projects_yaml_and_real_alpha_file(km):
    assert scopes_for("alpha/names_paths") == ["site/alpha"]
    assert scopes_for("bravo/names_paths") == []
    assert scopes_for("nowhere/x") == []
    m = load_knowledge_model(conventions=["site/alpha"], brick=km.graph)
    assert m.name_rules.unknown_tokens("Efficiency (CC)") == []


# --- validation ----------------------------------------------------------------------------------

def test_validation_names_file_and_key(km, tmp_path):
    write(tmp_path, "site/bad", abbreviations={"qq": ["notaword"], "a b": ["supply"]},
          equipment_patterns={"vav": ["(unclosed"], "nope": ["x"]},
          class_hints=[{"pattern": "x", "class": "Not_A_Class"}, {"pattern": "y", "class": "AHU"}, {"pattern": "["}],
          ignore=[{"pattern": "z"}], colour="blue")
    with pytest.raises(ConventionError) as e:
        merged(km, tmp_path, ["site/bad"])
    text = str(e.value)
    for expected in ["site/bad.yaml: abbreviations.qq: expands to 'notaword'",
                     "site/bad.yaml: abbreviations.a b: key contains a separator",
                     "site/bad.yaml: equipment_patterns.vav[0]: bad regex",
                     "site/bad.yaml: equipment_patterns.nope: 'nope' is not a template",
                     "site/bad.yaml: class_hints[0]: class 'Not_A_Class' is not a point class",
                     "site/bad.yaml: class_hints[1]: class 'AHU' is not a point class",
                     "site/bad.yaml: class_hints[2]: must be {pattern",
                     "site/bad.yaml: ignore[0]: must be {pattern",
                     "site/bad.yaml: unknown key 'colour'"]:
        assert expected in text, expected


def test_wrong_scope_and_missing_file(km, tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site/x.yaml").write_text("scope: site/y\n")
    with pytest.raises(ConventionError, match=r"site/x.yaml: scope: must be 'site/x'"):
        merged(km, tmp_path, ["site/x"])
    with pytest.raises(ConventionError, match=r"site/missing: no file missing.yaml"):
        load_layers(["site/missing"], tmp_path)
    with pytest.raises(ConventionError, match="scope must be"):
        load_layers(["builder/x"], tmp_path)


# --- mapper provenance ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def alpha_run(km):
    s = Store(":memory:")
    Mapper(load_knowledge_model(conventions=["site/alpha"], brick=km.graph)).run(
        read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), s, P)
    return s


def test_class_hint_decides_and_is_recorded(alpha_run):
    rows = {n["label"]: n for n in alpha_run.nodes(P, "point") if "(CC)" in n["label"]}
    eff = rows["Efficiency (CC)"]
    assert (eff["class"], eff["method"], eff["confidence"]) == ("Sensor", "rule", HINT_CONFIDENCE)
    assert json.loads(eff["attrs"])["convention"] == ["site/alpha:class_hints[0]", "site/alpha:abbreviations.cc"]
    flow = json.loads(rows["Chilled Water Flow (CC)"]["attrs"])
    assert flow["convention"] == ["site/alpha:abbreviations.cc"] and flow["unknown_tokens"] == []
    run = json.loads(alpha_run.conn.execute("SELECT summary FROM runs WHERE project = ?", (P,)).fetchone()[0])
    assert run["conventions"] == ["site/alpha"]


def test_conventions_change_alpha_score_and_report_says_so(km, alpha_run):
    gt = load_ground_truth("alpha")
    blind = Store(":memory:")
    Mapper(km).run(read_blind_export(ROOT / "data/blind/alpha/names_paths.csv"), blind, P)
    a, b = score_project(alpha_run, P, gt, km, 0.8), score_project(blind, P, gt, km, 0.8)
    assert (a["conventions"], b["conventions"]) == (["site/alpha"], [])
    assert a["H2_exact_pct"] > b["H2_exact_pct"]


def rec(i, name, path):
    return RawRecord(f"x{i}", "test", "t.csv", i, name, path=path)


def test_equipment_pattern_and_ignore(km, tmp_path):
    write(tmp_path, "site/z", equipment_patterns={"vav": [r"\bZN[-_ ]?\d"]},
          ignore=[{"pattern": "^Reheat", "reason": "Reheat removed 2022"}])
    m = merged(km, tmp_path, ["site/z"])
    records = [rec(1, "Zone Temp", "ZN-3"), rec(2, "Discharge Air Flow", "ZN-3"), rec(3, "Damper Cmd", "ZN-3"),
               rec(4, "Reheat Valve Cmd", "ZN-3")]
    blind, conv = Store(":memory:"), Store(":memory:")
    Mapper(km).run(records, blind, "t")
    Mapper(m).run(records, conv, "t")
    before = json.loads(blind.nodes("t", "equipment")[0]["attrs"])
    assert before["evidence"]["name_patterns"] == [] and "convention" not in before  # typed from points only
    eq = conv.nodes("t", "equipment")[0]
    assert (eq["class"], eq["method"]) == ("VAV", "rule")
    attrs = json.loads(eq["attrs"])
    assert attrs["evidence"]["name_patterns"] == ["vav"]
    assert attrs["convention"] == ["site/z:equipment_patterns.vav[0]"]
    pts = {n["label"]: json.loads(n["attrs"]) for n in conv.nodes("t", "point")}
    assert pts["Reheat Valve Cmd"]["ignore"] == {"reason": "Reheat removed 2022", "convention": "site/z:ignore[0]"}
    assert "site/z:ignore[0]" in pts["Reheat Valve Cmd"]["convention"]
    assert "ignore" not in pts["Zone Temp"]


def test_ignored_point_is_scored_but_sent_to_review(km, tmp_path):
    gt = load_ground_truth("alpha")
    records = read_blind_export(ROOT / "data/blind/alpha/names_paths.csv")
    write(tmp_path, "site/alpha", ignore=[{"pattern": "^Chilled Water Flow \\(CC\\)$", "reason": "dead"}])
    s = Store(":memory:")
    Mapper(merged(km, tmp_path, ["site/alpha"])).run(records, s, P)
    blind = Store(":memory:")
    Mapper(km).run(records, blind, P)
    a, b = score_project(s, P, gt, km, 0.8), score_project(blind, P, gt, km, 0.8)
    assert a["H2_exact_pct"] == b["H2_exact_pct"]                         # still scored
    assert a["H2_auto_accepted_pct_of_labelled"] < b["H2_auto_accepted_pct_of_labelled"]  # but not auto-accepted
