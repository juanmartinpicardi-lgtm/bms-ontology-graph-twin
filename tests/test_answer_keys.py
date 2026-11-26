"""Answer keys written by a person: the key files, the fixed sample, the scoring that prefers them, the page.

Key files go to a temporary folder (answer_keys.GT is pointed at it), so the repo's keys are never touched."""

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from projectmodel import answer_keys as ak
from projectmodel.scoring import eval as ev
from projectmodel.scoring import human_keys as hk
from projectmodel.scoring import sequences as sq

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src/projectmodel/app/views/answer_keys.py"
HAVE_PDFS = (ROOT / "data/raw/msu_mbb/22-0045 Plans.pdf").exists()


@pytest.fixture()
def gt(tmp_path, monkeypatch):
    """A temporary ground_truth folder: the repo's agent keys copied in, the human keys written there."""
    dst = tmp_path / "ground_truth"
    for site in ("msu_mbb", "itd_d1_lab", "troop_d"):
        (dst / site).mkdir(parents=True)
        for f in ("plans.yaml", "sequences.yaml"):
            if (ak.GT / site / f).exists():
                shutil.copy(ak.GT / site / f, dst / site / f)
    shutil.copy(ak.MANIFEST, dst / ak.MANIFEST.name)
    monkeypatch.setattr(ak, "GT", dst)
    monkeypatch.setattr(ak, "MANIFEST", dst / ak.MANIFEST.name)
    return dst


def plan_item(tag="FC-1.17", floor="L1", rooms=("999",), answer="here", minutes=1.5, revealed=False, **kw):
    return {"id": f"M201|{tag}", "sheet": "M201", "page": 22, "tag": tag, "answer": answer, "floor": floor,
            "rooms": list(rooms), "room_names": {r: "OFFICE" for r in rooms}, "rel": "serves", "status": "done",
            "minutes": minutes, "revealed": revealed, "extra": False, "source_page": 22, **kw}


def seq_item(rels, section="E", none=False, **kw):
    return {"id": f"air-handling-unit|{section}", "sequence": "air-handling-unit", "section": section,
            "title": "Supply Fan Control", "none": none, "relations": rels, "gaps": [], "status": "done",
            "minutes": 3.0, "revealed": False,
            "source": {"file": "3_sequences.pdf", "page": 1, "sheet": "M-304", "section": "air-handling-unit E"}, **kw}


def rel(a, r, z, kind="interlock", loop=""):
    return {"from": a, "rel": r, "to": z, "kind": kind, "loop": loop}


# the files ---------------------------------------------------------------------------------------------------------

def test_plan_key_round_trip_and_agent_key_untouched(gt):
    agent_file = gt / "msu_mbb/plans.yaml"
    before = hashlib.sha256(agent_file.read_bytes()).hexdigest()
    data = ak.load("plans", "msu_mbb")
    assert data["items"] == [] and not ak.exists("plans", "msu_mbb")
    ak.upsert(data, plan_item())
    ak.upsert(data, plan_item("SS-2", floor="RF", rooms=(), answer="roof", **{"id": "M202|SS-2", "sheet": "M202"}))
    ak.upsert(data, plan_item("ERV-3", answer="not_unit", rooms=(), floor=""))
    ak.upsert(data, plan_item("FC-1.18", answer="unsure", rooms=(), floor=""))
    ak.upsert(data, plan_item("FC-1.20", status="draft"))  # a draft is saved but is not in the key
    p = ak.save("plans", "msu_mbb", data)
    assert p == gt / "msu_mbb/plans.human.yaml"
    again = ak.load("plans", "msu_mbb")
    assert [i["id"] for i in again["items"]] == [i["id"] for i in data["items"]]
    assert all(i["by"] == "human" and i["at"] for i in again["items"])
    raw = yaml.safe_load(p.read_text())
    assert raw["by"] == "human" and set(raw) >= {"sheets", "tags", "unsure", "items", "set", "file"}
    t = raw["tags"]["FC-1.17"]  # the agent key's schema, plus by / at / revealed / minutes / page
    assert (t["floor"], t["rooms"], t["rel"], t["by"], t["revealed"], t["minutes"], t["page"]) == \
        ("L1", ["999"], "serves", "human", False, 1.5, 22)
    assert raw["tags"]["SS-2"]["rooms"] == [] and raw["tags"]["SS-2"]["floor"] == "RF"
    assert "ERV-3" not in raw["tags"] and "FC-1.20" not in raw["tags"]
    assert raw["unsure"] == ["FC-1.18"] and raw["not_units"] == ["ERV-3"]
    assert {s["sheet"] for s in raw["sheets"]} == {"M201", "M202"}
    assert hashlib.sha256(agent_file.read_bytes()).hexdigest() == before  # never overwritten
    assert ak.done_items(again) and len(ak.done_items(again)) == 4


def test_sequence_key_round_trip(gt):
    data = ak.load("sequences", "troop_d")
    ak.upsert(data, seq_item([rel("AHU.DAP-SP", "drives", "AHU.SF-O", "loop", "Duct static"),
                              rel("AHU.DA-P", "feedback", "AHU.SF-O", "loop", "Duct static"),
                              rel("AHU.SF1-S", "requires", "AHU.SF-C"),
                              rel("AHU.OCC-SCHEDULE", "switches", "AHU.SF-C", "mode")]))
    ak.upsert(data, seq_item([], section="M", none=True, **{"id": "air-handling-unit|M"}))
    ak.save("sequences", "troop_d", data)
    d = ak.load_derived("sequences", "troop_d")
    ahu = d["sequences"]["air-handling-unit"]
    assert d["covered"] == {"air-handling-unit": ["E", "M"]}  # a 'none' section is covered, with no relation
    assert ahu["loops"][0]["setpoint"] == "AHU.DAP-SP" and ahu["loops"][0]["measured"] == "AHU.DA-P"
    assert ahu["loops"][0]["output"] == "AHU.SF-O" and ahu["loops"][0]["by"] == "human"
    assert ahu["interlocks"][0]["page"] == 1 and ahu["modes"][0]["rel"] == "switches"
    rels = sq.key_relations(ahu)  # the same scoring reads it
    assert sorted(sorted(r["rel"])[0] for r in rels) == ["drives", "feedback", "requires", "switches"]
    assert not (gt / "troop_d/sequences.yaml").read_text().count("by: human")


def test_reveal_is_recorded(gt):
    data = ak.load("plans", "msu_mbb")
    ak.upsert(data, plan_item(revealed=False))
    ak.save("plans", "msu_mbb", data)
    rec = next(i for i in ak.load("plans", "msu_mbb")["items"])
    rec["revealed"] = True
    ak.save("plans", "msu_mbb", ak.upsert(ak.load("plans", "msu_mbb"), rec))
    assert ak.load_derived("plans", "msu_mbb")["tags"]["FC-1.17"]["revealed"] is True
    assert ak.progress("plans", "msu_mbb")["revealed"] == 1


def test_progress_and_pace(gt):
    pr = ak.progress("plans", "msu_mbb", {"items": []})
    assert pr["done"] == 0 and pr["est_left_min"] == pr["est_total_min"] and pr["total"] == 17
    sample = ak.sample_for("msu_mbb")["items"]
    items = [{"id": s["id"], "status": "done", "minutes": s["est_min"] * 2} for s in sample[:4]]
    slow = ak.progress("plans", "msu_mbb", {"items": items})
    assert slow["done"] == 4 and slow["pace"] == 2.0  # four done at twice the estimate: the rest scaled up
    assert slow["est_left_min"] > pr["est_left_min"] * 1.5 * 0.7
    rec = ak.add_minutes({"id": "x", "minutes": 1.0}, since=0.0, now_ts=3600.0)
    assert rec["minutes"] == 1.0 + ak.IDLE_CAP_MIN  # an hour away counts as the cap


# the fixed sample --------------------------------------------------------------------------------------------------

def test_sample_is_fixed_and_fits_the_time():
    m = ak.load_manifest()["sets"]
    assert set(m) == {"msu_mbb", "itd_d1_lab", "troop_d"}
    total = sum(ak.progress(x["job"], s, {"items": []})["est_total_min"] for s, x in m.items())
    assert 60 <= total <= 120  # 1 to 2 hours for the three sets
    for s, x in m.items():
        ids = [i["id"] for i in x["items"]]
        assert len(ids) == len(set(ids)) and 10 <= len(ids) < x["universe"]
        assert x["seed"] == f"{ak.SEED}:{s}"
    groups = {"a": [{"id": f"a{i}", "est_min": 1.0} for i in range(10)], "b": [{"id": f"b{i}", "est_min": 1.0}
                                                                                for i in range(4)]}
    one = ak.pick_sample(groups, 7.0, "seed")
    assert one == ak.pick_sample(groups, 7.0, "seed") != ak.pick_sample(groups, 7.0, "other")
    assert len([i for i in one if i["id"][0] == "a"]) > len([i for i in one if i["id"][0] == "b"])  # by size


def test_sequence_sample_is_what_the_documents_give(gt):
    """The troop_d sample is rebuilt from the committed test package, so it must equal the saved one."""
    assert ak.build_sample("troop_d")["items"] == ak.sample_for("troop_d")["items"]


@pytest.mark.skipif(not HAVE_PDFS, reason="the real drawing PDFs are not in data/raw")
def test_plan_sample_is_what_the_documents_give(gt):
    for s in ("msu_mbb", "itd_d1_lab"):
        assert ak.build_sample(s)["items"] == ak.sample_for(s)["items"]


def test_held_out_set_is_never_offered(gt):
    assert all("liberty_boe" not in ak.offered(j) for j in ak.JOBS)
    assert "liberty_boe" not in str(ak.load_manifest())
    for job in ak.JOBS:
        with pytest.raises(ValueError):
            ak.check_set(job, "liberty_boe")
        with pytest.raises(ValueError):
            ak.key_path(job, "liberty_boe")
    with pytest.raises(ValueError):
        ak.load("plans", "liberty_boe")
    with pytest.raises(ValueError):
        ak.sample_for("liberty_boe")
    assert not list(ak.GT.glob("liberty_boe*")) and not list((ROOT / "data/ground_truth").glob("liberty_boe*"))


# scoring prefers the human key -------------------------------------------------------------------------------------

def placement(tag, floor, room):
    from projectmodel.intake.plan_ai import normal_of
    return {"kind": "placement", "data": {"normal": normal_of(tag), "floor": floor, "room": room}}


def test_plan_scoring_prefers_the_human_key_and_reports_both(gt):
    agent = ev.plan_key("msu_mbb")
    assert agent["tags"]["FC-1.17"]["rooms"] == ["155"] and agent["tags"]["FC-1.18"]["rooms"] == ["160"]
    facts = [placement("FC-1.17", "L1", "155"), placement("FC-1.18", "L1", "160")]
    before = ev.plan_score("msu_mbb", facts)
    assert before["placements_ok"] == 2 and ev.plan_key_used("msu_mbb") == agent  # no human key: unchanged
    assert hk.plan_compare("msu_mbb", facts, agent) is None

    data = ak.load("plans", "msu_mbb")
    ak.upsert(data, plan_item("FC-1.17", rooms=("999",)))                        # the person disagrees with the agent
    ak.upsert(data, plan_item("FC-1.18", rooms=("160",)))                        # and agrees here
    ak.upsert(data, plan_item("FC-1.16", rooms=("154",)))                        # agent has L1 154|153: agrees
    ak.upsert(data, plan_item("FC-1.19", answer="not_unit", rooms=(), floor=""))  # the agent has it as a unit
    ak.save("plans", "msu_mbb", data)

    after = ev.plan_score("msu_mbb", facts)
    assert after["tags"] == before["tags"] - 1   # FC-1.19 is no unit here: not scored
    assert after["placements_ok"] == 1           # FC-1.17 now wrong (the human key says 999), FC-1.18 right
    assert any("FC-1.17" in w for w in after["wrong"])
    c = hk.plan_compare("msu_mbb", facts + [placement("FC-1.16", "L1", "154")], agent)
    assert (c["tags"], c["right"], c["agent_same_tags"], c["agent_right"]) == (3, 2, 3, 3)
    ag = c["agreement"]
    assert (ag["both"], ag["agree"]) == (3, 2) and ag["agree_pct"] == 66.7 and "FC-1.17" in ag["differ"][0]
    assert ag["agent_has_human_says_no_unit"] == ["FC-1.19"]
    assert hk.plan_combine([c, c])["tags"] == 6


def test_plan_report_has_both_only_with_a_human_key(gt):
    rows, _, _ = ev.plan_meaning_rows(["msu_mbb"], [], router=None, log=lambda m: None) if HAVE_PDFS else ([], 0, 0)
    if not HAVE_PDFS:
        pytest.skip("the real drawing PDFs are not in data/raw")
    assert "human_key" not in rows[0]
    data = ak.load("plans", "msu_mbb")
    ak.upsert(data, plan_item("FC-1.17", rooms=("155",)))
    ak.save("plans", "msu_mbb", data)
    ev._CACHE.clear()
    rows, _, _ = ev.plan_meaning_rows(["msu_mbb"], [], router=None, log=lambda m: None)
    hkd = rows[0]["human_key"]
    assert hkd["tags"] == 1 and "agreement" in hkd and hkd["agent_same_tags"] == 1
    out = []
    ev.print_plan_row(rows[0], out.append)
    text = "\n".join(out)
    assert "vs human key" in text and "vs agent key" in text and "keys agree" in text


def test_sequence_scoring_prefers_the_human_key_and_reports_both(gt):
    agent = sq.load_key("troop_d")
    assert hk.sequence_effective_key("troop_d", agent) is agent  # no human key: the agent key itself
    ahu = agent["sequences"]["air-handling-unit"]
    e_before = [i for i in ahu["interlocks"] if i["section"] == "E"]
    assert e_before and not [i for i in ahu["interlocks"] if i["section"] == "M" and i["from"] == "AHU.XX"]

    data = ak.load("sequences", "troop_d")
    ak.upsert(data, seq_item([rel("AHU.SF1-S", "requires", "AHU.SF-C"),           # in the agent key too
                              rel("AHU.XX-S", "requires", "AHU.SF-C")]))          # only the person has it
    ak.save("sequences", "troop_d", data)
    key = hk.sequence_effective_key("troop_d", agent)
    rels = key["sequences"]["air-handling-unit"]["interlocks"]
    assert [i for i in rels if i["section"] == "E" and i["from"] == "AHU.XX-S"]
    assert not [i for i in rels if i["section"] == "E" and i["from"] == ["AHU.SF1-S", "AHU.SF2-S"]]
    assert [i for i in rels if i["section"] == "G"] == [i for i in ahu["interlocks"] if i["section"] == "G"]
    assert ahu["interlocks"] == agent["sequences"]["air-handling-unit"]["interlocks"]  # the agent key is not changed

    logic = {"seq:air-handling-unit": {"relations": [
        {"from": "AHU.SF1-S", "rel": "requires", "to": "AHU.SF-C", "section": "E"},
        {"from": "AHU.ZZ", "rel": "requires", "to": "AHU.SF-C", "section": "E"},
        {"from": "AHU.OA-T", "rel": "requires", "to": "AHU.ECON-O", "section": "G"},   # not a keyed section: ignored
        {"from": "AHU.QQ", "rel": "requires", "to": "AHU.SF-C", "section": ""}]}}
    c = hk.sequence_compare(logic, agent, "troop_d")
    assert c["sections"] == 1 and c["unattributed_answers"] == 1
    assert (c["vs_human"]["tp"], c["vs_human"]["fp"], c["vs_human"]["required"], c["vs_human"]["found"]) == (1, 1, 2, 1)
    a = c["vs_agent"]  # section E in the agent key: nine fan statuses one relation, the freezestat is L
    assert a["tp"] == 1 and a["fp"] == 1
    ag = c["agreement"]
    assert ag["human_relations"] == 2 and ag["human_in_agent"] == 1 and ag["agent_in_human"] == 1
    assert 0 < ag["agree_pct"] < 100


def test_sequence_eval_reports_both_only_with_a_human_key(gt):
    r0 = ev.evaluate("sequence_read", ["troop_d"], log=lambda m: None)
    assert all("human_key" not in row for row in r0["rows"]) and "human_sections" not in r0["key"]
    data = ak.load("sequences", "troop_d")
    ak.upsert(data, seq_item([rel("AHU.SF1-S", "requires", "AHU.SF-C"), rel("AHU.ZZ", "requires", "AHU.SF-C")]))
    ak.save("sequences", "troop_d", data)
    r1 = ev.evaluate("sequence_read", ["troop_d"], log=lambda m: None)
    rules = r1["rows"][0]
    assert r1["key"]["human_sections"] == 1 and rules["human_key"]["sections"] == 1
    out = []
    ev.sequence_read_print(r1, out.append)
    text = "\n".join(out)
    assert "vs human key" in text and "vs agent key" in text and "keys agree" in text


# the page ----------------------------------------------------------------------------------------------------------

def run_page(**state) -> AppTest:
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def test_page_offers_only_dev_sets_and_renders_the_sequences_job(gt):
    at = run_page(ak_job="Sequences")
    assert not at.exception
    assert any("troop_d" in o for sb in at.selectbox if sb.label == "Set" for o in sb.options)
    assert not any("liberty_boe" in str(o) for sb in at.selectbox for o in sb.options)
    assert at.get("progress")  # the progress bar
    assert any("The sample is fixed" in c.value for c in at.caption)
    item = next(sb for sb in at.selectbox if sb.label == "Item")
    assert len(item.options) == 17
    # blind: the page never shows the agent key's words or the rules' relations while the item is open
    page_text = " ".join(m.value for m in at.markdown)
    assert "proof of run within 30 s of command" not in page_text


def test_page_saves_a_sequence_item_and_marks_it_done(gt):
    at = run_page(ak_job="Sequences")
    item_id = at.session_state["ak_cur_troop_d"]
    assert item_id == "exhaust-fans|A"
    # nothing yet: a done item needs a relation or 'none'
    next(b for b in at.button if b.label == "Mark done").click()
    at.run()
    assert any("Add at least one relation" in e.value for e in at.error) and not ak.exists("sequences", "troop_d")
    next(c for c in at.checkbox if c.label.startswith("This section states no")).check()
    at.run()
    next(b for b in at.button if b.label == "Save draft").click()
    at.run()
    assert not at.exception
    d = ak.load("sequences", "troop_d")
    assert [(i["id"], i["status"], i["none"], i["by"]) for i in d["items"]] == [("exhaust-fans|A", "draft", True,
                                                                                  "human")]
    next(b for b in at.button if b.label == "Mark done").click()
    at.run()
    d = ak.load("sequences", "troop_d")
    assert d["items"][0]["status"] == "done" and d["items"][0]["minutes"] >= 0
    assert d["items"][0]["source"]["page"] == 1 and d["items"][0]["source"]["file"] == "3_sequences.pdf"
    assert any(b.label == "Show the reader's answer" for b in at.button)  # offered only once the item is done
    assert not any("exhaust-fans" in str(x) and "Rules:" in str(x) for x in at.markdown)  # nothing shown before
    next(b for b in at.button if b.label == "Show the reader's answer").click()
    at.run()
    assert not at.exception
    assert ak.load("sequences", "troop_d")["items"][0]["revealed"] is True
    assert any(m.value.startswith("- Rules:") for m in at.markdown)  # the reader's answer, now shown
    assert ak.progress("sequences", "troop_d")["revealed"] == 1


def test_page_adds_a_relation_from_the_pickers(gt):
    at = run_page(ak_job="Sequences")
    iid = at.session_state["ak_cur_troop_d"]
    frm = next(sb for sb in at.selectbox if sb.label == "From")
    ids = [o for o in frm.options]
    assert any(str(o).startswith("EF-") or "EF" in str(o) for o in ids)
    frm.select(frm.options[0])
    next(sb for sb in at.selectbox if sb.label == "Relation").select("requires")
    to = next(sb for sb in at.selectbox if sb.label == "To")
    to.select(to.options[1])
    at.run()
    next(b for b in at.button if b.label == "Add relation").click()
    at.run()
    assert len(at.session_state[f"ak_{iid}_rels"]) == 1
    next(b for b in at.button if b.label == "Mark done").click()
    at.run()
    rec = ak.load("sequences", "troop_d")["items"][0]
    assert rec["status"] == "done" and rec["relations"][0]["rel"] == "requires" and rec["relations"][0]["kind"] == "interlock"


@pytest.mark.skipif(not HAVE_PDFS, reason="the real drawing PDFs are not in data/raw")
def test_page_plan_item_with_the_sheet_image(gt):
    at = run_page(ak_job="Plan sheets")
    assert not at.exception
    iid = at.session_state["ak_cur_msu_mbb"]
    assert iid == ak.sample_for("msu_mbb")["items"][0]["id"]
    assert any("the tag is outlined in red" in c.value for c in at.caption)  # the sheet crop is shown
    radio = next(r for r in at.radio if r.label == "What is it on this sheet?")
    radio.set_value("roof")
    at.run()
    next(b for b in at.button if b.label == "Mark done").click()
    at.run()
    rec = ak.load("plans", "msu_mbb")["items"][0]
    assert rec["status"] == "done" and rec["answer"] == "roof" and rec["floor"] == "RF" and rec["rooms"] == []
    assert ak.load_derived("plans", "msu_mbb")["tags"][rec["tag"]]["rooms"] == []


def test_the_page_is_in_the_navigation():
    assert 'views/answer_keys.py' in (ROOT / "src/projectmodel/app/main.py").read_text()


# the hosted app: drawings on demand, key files carried across restarts --------------------------------------------

class _Body:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def read(self, n=-1):
        out = self.data[self.pos:] if n < 0 else self.data[self.pos:self.pos + n]
        self.pos += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_drawing_checks_the_copy(gt, tmp_path, monkeypatch):
    monkeypatch.setattr(ak, "ROOT", tmp_path)
    body = b"%PDF-1.7 the bid set"
    url = ak.DRAWINGS["itd_d1_lab"][0]
    monkeypatch.setitem(ak.DRAWINGS, "itd_d1_lab", (url, hashlib.sha256(body).hexdigest(), 0.1))
    seen = []
    p = ak.fetch_drawing("itd_d1_lab", opener=lambda req: seen.append(req.full_url) or _Body(body))
    assert p == ak.plan_file("itd_d1_lab") and p.read_bytes() == body and seen == [url]
    assert not list(p.parent.glob("*.part"))
    assert ak.fetch_drawing("itd_d1_lab", opener=lambda req: pytest.fail("fetched twice")) == p  # already here
    p.unlink()
    with pytest.raises(ValueError, match="sha256"):
        ak.fetch_drawing("itd_d1_lab", opener=lambda req: _Body(b"something else"))
    assert not p.exists() and not list(p.parent.glob("*.part"))
    with pytest.raises(ValueError, match="held out"):
        ak.fetch_drawing("liberty_boe")


def test_a_downloaded_key_file_carries_the_work_across_a_restart(gt):
    data = ak.load("plans", "msu_mbb")
    ak.upsert(data, plan_item("FC-1.17"))
    ak.upsert(data, plan_item("FC-1.18", rooms=("120",)))
    data["engineer"] = "Pat"
    raw = ak.save("plans", "msu_mbb", data).read_bytes()
    ak.key_path("plans", "msu_mbb").unlink()  # the hosted app restarted: its disk is empty
    n = ak.import_key("plans", "msu_mbb", raw)
    assert n == {"items": 2, "added": 2, "replaced": 0, "kept": 0}
    back = ak.load("plans", "msu_mbb")
    assert [i["id"] for i in back["items"]] == ["M201|FC-1.17", "M201|FC-1.18"] and back["engineer"] == "Pat"
    assert ak.load_derived("plans", "msu_mbb")["tags"]  # the agent-schema part is rebuilt
    # merged per item: the record saved last wins
    newer = ak.load("plans", "msu_mbb")
    newer["items"][0] = dict(newer["items"][0], rooms=["130"], at="2999-01-01T00:00:00+00:00")
    ak.save("plans", "msu_mbb", newer)
    assert ak.import_key("plans", "msu_mbb", raw) == {"items": 2, "added": 0, "replaced": 0, "kept": 2}
    assert ak.load("plans", "msu_mbb")["items"][0]["rooms"] == ["130"]


@pytest.mark.parametrize("raw, match", [
    (b"set: itd_d1_lab\nby: human\nitems: []\n", "not 'msu_mbb'|for 'itd_d1_lab'"),
    (b"set: msu_mbb\nby: agent\nitems: []\n", "not a key file"),
    (b"set: msu_mbb\nby: human\nitems: [{tag: X}]\n", "no id"),
    (b"\xff\xfe", "not a key file"),
])
def test_a_wrong_key_file_is_refused(gt, raw, match):
    with pytest.raises(ValueError, match=match):
        ak.import_key("plans", "msu_mbb", raw)
    assert not ak.exists("plans", "msu_mbb")


def test_without_the_drawings_the_page_offers_to_fetch_them(gt, tmp_path, monkeypatch):
    monkeypatch.setattr(ak, "ROOT", tmp_path)  # no data/raw here
    at = run_page(ak_job="Plan sheets")
    assert not at.exception
    assert any(b.label == "Get the drawings" for b in at.button)
    assert any("public bid set" in i.value for i in at.info)


def test_the_hosted_app_warns_and_offers_the_key_file(gt, monkeypatch):
    monkeypatch.setattr(ak, "hosted", lambda: True)
    at = run_page(ak_job="Sequences")
    assert not at.exception
    assert any("forgets saved answers" in w.value for w in at.warning)
    assert at.get("file_uploader")
