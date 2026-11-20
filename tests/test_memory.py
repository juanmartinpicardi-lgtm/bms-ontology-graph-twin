"""Memory and skills M1: the files under knowledge/ load and validate; bad files fail with a clear message."""

import shutil
from pathlib import Path

import pytest
import yaml

from projectmodel.conventions import scopes_for
from projectmodel.intake.schedules import LAYOUTS
from projectmodel.knowledge_model import load_knowledge_model
from projectmodel.memory import CAPS, KNOWLEDGE_DIR, KnowledgeError, load_knowledge

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def km():
    return load_knowledge_model()


@pytest.fixture(scope="module")
def kb(km):
    return load_knowledge(km=km)


@pytest.fixture
def tmp_kb(tmp_path):
    root = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, root)
    return root


def test_seed_content_loads_and_validates(kb):
    assert {"global", "designer/true-engineering-group", "contractor/ozark-valley-controls", "site/alpha"} <= set(kb.memory)
    assert {"troubleshoot-warm-zone", "classify-vav-points", "read-metasys-submittal",
            "read-true-engineering-schedules"} <= set(kb.skills)
    principles = [e.text for e in kb.memory["global"].active if e.kind == "principle"]
    assert any("intent" in t and "installed" in t for t in principles)


def test_every_scope_is_within_its_cap(kb):
    for mf in kb.memory.values():
        assert mf.chars <= mf.cap <= CAPS[mf.scope.split("/")[0]]


def test_project_scopes_layer_from_general_to_specific(kb):
    assert kb.scopes_for("alpha/names_paths") == ["global", "site/alpha"]
    assert kb.scopes_for("crime-lab-demo/documents") == [
        "global", "designer/true-engineering-group", "contractor/ozark-valley-controls"]
    assert kb.scopes_for(None) == ["global"]
    assert kb.scopes_for("unknown/x") == ["global"]


def test_memory_text_is_general_first_with_citable_ids(kb):
    text = kb.memory_text(kb.scopes_for("alpha/names_paths"))
    assert text.index("## global") < text.index("## site/alpha")
    assert "[m-0001] (principle)" in text and "[m-0301]" in text
    assert "designer/" not in text


def test_skills_index_and_view(kb):
    idx = kb.skills_index(kb.scopes_for("crime-lab-demo/documents"))
    names = [s["name"] for s in idx]
    assert names[:2] == ["classify-vav-points", "troubleshoot-warm-zone"]  # global first
    assert "read-true-engineering-schedules" in names and "read-metasys-submittal" in names
    assert "read-true-engineering-schedules" not in [s["name"] for s in kb.skills_index(["global", "site/alpha"])]
    assert "## Procedure" in kb.skill_view("troubleshoot-warm-zone")
    assert "FAN POWERED" in kb.skill_view("read-true-engineering-schedules", "rules/layouts.yaml")
    with pytest.raises(KeyError):
        kb.skill_view("troubleshoot-warm-zone", "../../memory/global.yaml")


def test_layouts_skill_matches_the_schedule_reader(kb):
    """Until M3 moves the reader onto the skill, the seeded layouts must equal the code's."""
    data = kb.skills["read-true-engineering-schedules"].rule_data("layouts.yaml")
    assert [(lay["title"], lay["columns"]) for lay in data["layouts"]] == [(t, c) for t, c in LAYOUTS]


def test_conventions_skip_memory_only_scopes():
    assert scopes_for("crime-lab-demo/documents") == []
    assert scopes_for("alpha/names_paths") == ["site/alpha"]


# failures --------------------------------------------------------------------------------------------------------

def _edit_yaml(path: Path, fn):
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_over_cap_fails_with_the_file_and_the_numbers(tmp_kb, km):
    _edit_yaml(tmp_kb / "memory/site/alpha.yaml",
               lambda d: d["entries"].append({**d["entries"][0], "id": "m-9999", "text": "x " * 1400}))
    with pytest.raises(KnowledgeError, match=r"memory/site/alpha.yaml: \d+ characters of active memory, over the cap"):
        load_knowledge(tmp_kb, km=km)


def test_a_cap_above_the_scope_limit_fails(tmp_kb):
    _edit_yaml(tmp_kb / "memory/site/alpha.yaml", lambda d: d.update(cap=9000))
    with pytest.raises(KnowledgeError, match="above the site limit of 2500"):
        load_knowledge(tmp_kb)


def test_a_bad_class_in_skill_rules_fails(tmp_kb, km):
    skill = tmp_kb / "skills/contractor/ozark-valley-controls/read-metasys-submittal"
    (skill / "rules").mkdir()
    (skill / "rules/terms.yaml").write_text("terms:\n  zone temp: Zone_Air_Temperature_Sensor\n  wiggle: Not_A_Class\n")
    md = skill / "SKILL.md"
    md.write_text(md.read_text().replace("    status: active", "    rules: [rules/terms.yaml]\n    status: active", 1))
    with pytest.raises(KnowledgeError, match="terms.wiggle: class 'Not_A_Class' is not in the knowledge model"):
        load_knowledge(tmp_kb, km=km)


def test_a_bad_class_in_skill_conventions_fails(tmp_kb, km):
    skill = tmp_kb / "skills/global/classify-vav-points"
    (skill / "rules").mkdir()
    (skill / "rules/conventions.yaml").write_text("class_hints:\n  - {pattern: '(?i)^dmpr$', class: Dampr_Command}\n")
    md = skill / "SKILL.md"
    md.write_text(md.read_text().replace("    status: active", "    rules: [rules/conventions.yaml]\n    status: active", 1))
    with pytest.raises(KnowledgeError, match="Dampr_Command"):
        load_knowledge(tmp_kb, km=km)


def test_scope_must_match_the_place(tmp_kb):
    _edit_yaml(tmp_kb / "memory/site/alpha.yaml", lambda d: d.update(scope="site/bravo"))
    with pytest.raises(KnowledgeError, match="the file's place says 'site/alpha'"):
        load_knowledge(tmp_kb)


def test_entry_fields_are_checked(tmp_kb):
    def bad(d):
        d["entries"][0]["kind"] = "rumour"
        d["entries"][1]["id"] = d["entries"][0]["id"]
    _edit_yaml(tmp_kb / "memory/global.yaml", bad)
    with pytest.raises(KnowledgeError) as e:
        load_knowledge(tmp_kb)
    msg = str(e.value)
    assert "kind 'rumour'" in msg and "id m-0001 is also used" in msg


def test_skill_name_must_match_folder_and_have_a_procedure(tmp_kb):
    md = tmp_kb / "skills/global/troubleshoot-warm-zone/SKILL.md"
    md.write_text(md.read_text().replace("name: troubleshoot-warm-zone", "name: Troubleshoot_Zone")
                  .replace("## Procedure", "## Steps"))
    with pytest.raises(KnowledgeError) as e:
        load_knowledge(tmp_kb)
    assert "lowercase words joined by hyphens" in str(e.value) and "'## Procedure'" in str(e.value)


def test_a_misspelt_project_scope_fails(tmp_kb, tmp_path):
    conv = tmp_path / "conventions"
    conv.mkdir()
    (conv / "projects.yaml").write_text("alpha/names_paths: [site/alpah]\n")
    with pytest.raises(KnowledgeError, match="scope 'site/alpah' has no memory, skill or conventions file"):
        load_knowledge(tmp_kb, conv_dir=conv)


def test_a_person_profile_holds_no_principles(tmp_kb):
    (tmp_kb / "people").mkdir(exist_ok=True)
    (tmp_kb / "people/ana.yaml").write_text(yaml.safe_dump({"scope": "person/ana", "entries": [
        {"id": "p-1", "kind": "principle", "text": "Always X.", "method": "human", "author": "ana",
         "created": "2026-11-20"}]}))
    with pytest.raises(KnowledgeError, match="profile holds preferences and facts"):
        load_knowledge(tmp_kb)
