"""Build a project's knowledge graph: map one blind export into the database, then store its sequences' behaviour.

Used by scripts/run_mapper.py and by the app on first start (a fresh checkout, e.g. on Streamlit Cloud, has no
database: data/*.sqlite is not in git). Rules only, no LLM: same result every time, no key needed.
"""

from __future__ import annotations

from pathlib import Path

from .adapters.haystack import VARIANTS, read_blind_export
from .conventions import scopes_for
from .db.store import Store
from .knowledge_model import load_knowledge_model
from .mapper.llm import get_provider
from .mapper.pipeline import Mapper
from .projects import INPUTS, SITES
from .sequences import store_behaviour

ROOT = Path(__file__).resolve().parents[2]


def map_project(site: str, variant: str, db: Path | str, llm: str = "none", blind: bool = False) -> dict:
    project = f"{site}/{variant}"
    records = read_blind_export(ROOT / "data/blind" / site / f"{variant}.csv")
    km = load_knowledge_model(conventions=[] if blind else scopes_for(project))
    store = Store(db)
    summary = Mapper(km, llm=get_provider(llm, km)).run(records, store, project)
    # The sequences' behaviour edges point at mapped nodes: reload them on the graph just built.
    if (behaviour := store_behaviour(store, km, project)) is not None:
        summary["behaviour"] = {k: behaviour[k] for k in ("stored", "edges")} | {"skipped": len(behaviour["skipped"])}
    return summary


def build_all(db: Path | str) -> None:
    """Every site with every input that has a blind export. Other inputs (e.g. "documents") come from the
    guided setup, not from a CSV, so there is nothing to map for them here."""
    for site in SITES:
        for variant in INPUTS:
            if variant in VARIANTS:
                map_project(site, variant, db)
