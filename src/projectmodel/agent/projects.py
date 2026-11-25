"""Open a project for the agent: its store, its project id and its documents.

    store, project, docs = open_project("troop_d")            # the Troop D graph the agent eval uses
    store, project, docs = open_project("alpha/names_paths")   # a project in the app's store

`troop_d` is the Troop D test package (test_packages/troop_d) run through the guided setup with rules only, as
`export/run.py` builds it, plus W8's control relations: the `sequence_read` answers frozen in
tests/fixtures/troop_d_sequence_read.json (Gemini 4 Hydrogen, the model this GCP project answers that job with),
merged, calibrated and checked by intake/sequence_ai.py exactly as the setup does, and published as the setup's
`setup:sequence_logic` source. No model is called, so every run gets the same graph. It is built once into
data/eval/agent/ (git-ignored) and reused; `rebuild=True` builds it again.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from ..db.store import Store
from .documents import DocumentIndex

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data" / "kg.sqlite"
EVAL_DIR = ROOT / "data" / "eval" / "agent"
SEQUENCE_ANSWERS = ROOT / "tests" / "fixtures" / "troop_d_sequence_read.json"
TROOP_D = "troop_d"
BUILD_VERSION = 1  # bump when the build changes, so a stale cached build is rebuilt


class _AnswersOnly:
    """A router for sequence_ai.read that is 'ready' but is never called: every answer is already in the building's
    saved answers."""
    ready, learnt, not_enabled = True, True, {}

    def why_not_ready(self) -> str:
        return ""


def _seed_sequence_answers(it, answers: dict) -> int:
    """Put the frozen answers in the building's saved answers (keyed as sequence_ai.read looks them up)."""
    from ..ai.prompts import load_prompt
    from ..intake import sequence_ai
    from ..intake.model import building

    ref = load_prompt(sequence_ai.JOB).ref
    cache = it.s.setdefault(sequence_ai.STATE_KEY, {})
    n = 0
    for q in sequence_ai.questions(building(it)):
        a = answers.get(q.seq["id"])
        if a:
            cache[sequence_ai.question_key(q, ref)] = {**a, "cost_usd": 0.0, "logged": True}
            n += 1
    it.save()
    return n


def build_troop_d(root: Path = EVAL_DIR, answers_path: Path | None = SEQUENCE_ANSWERS) -> tuple[Store, str, DocumentIndex]:
    """Build the Troop D graph into `root` (intake/ and troop_d.sqlite). See the module docstring."""
    from ..ai.calls import set_default_router
    from ..ai.config import load_config
    from ..intake import sequence_ai, steps
    from ..intake.publish import publish, statements
    from ..intake.state import Intake

    root = Path(root)
    shutil.rmtree(root / "intake", ignore_errors=True)
    db = root / "troop_d.sqlite"
    db.unlink(missing_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("PM_AI")
    os.environ["PM_AI"] = "off"  # the readers' rules only, as export/run.py builds it: no point_class calls
    load_config.cache_clear()
    set_default_router(None)
    try:
        it = Intake.create("Troop D", root=root / "intake", test=True)
        for s in steps.STEPS[:-1]:
            it.add_file(s.id, s.test_file, (steps.TEST_PACKAGE / s.test_file).read_bytes())
            steps.run(it, s.id, lambda m: None)
        store = Store(db)
        project = publish(it, store)
        n_seq = 0
        if answers_path and Path(answers_path).exists():
            answers = json.loads(Path(answers_path).read_text())["answers"]
            n_seq = _seed_sequence_answers(it, answers)
            logic = sequence_ai.statements(it, statements(it), router=_AnswersOnly())
            if logic:
                t0 = time.time()
                rev = store.start_run(project, "W8 sequence logic (frozen answers)")
                edges = logic[sequence_ai.SOURCE]["edges"]
                written = store.write_source(project, sequence_ai.SOURCE, rev, [], edges, [])
                store.finish_run(project, rev, round(time.time() - t0, 2), {"source": sequence_ai.SOURCE,
                                                                             "written": written})
        (root / "build.json").write_text(json.dumps({"version": BUILD_VERSION, "project": project, "slug": it.slug,
                                                     "sequences_answered": n_seq, "built": time.time()}))
        return store, project, DocumentIndex(project, Intake(it.slug, root=root / "intake"))
    finally:
        if old is None:
            os.environ.pop("PM_AI", None)
        else:
            os.environ["PM_AI"] = old
        load_config.cache_clear()
        set_default_router(None)


def troop_d(root: Path = EVAL_DIR, rebuild: bool = False) -> tuple[Store, str, DocumentIndex]:
    """The Troop D graph, built once and reused."""
    from ..intake.state import Intake

    meta = root / "build.json"
    if not rebuild and meta.exists() and (root / "troop_d.sqlite").exists():
        m = json.loads(meta.read_text())
        it = Intake(m["slug"], root=root / "intake")
        if m.get("version") == BUILD_VERSION and it.s:
            return Store(root / "troop_d.sqlite"), m["project"], DocumentIndex(m["project"], it)
    return build_troop_d(root)


def open_project(name: str, db: Path = STORE, rebuild: bool = False) -> tuple[Store, str, DocumentIndex]:
    if name == TROOP_D:
        return troop_d(rebuild=rebuild)
    store = Store(db)
    return store, name, DocumentIndex.for_project(name)
