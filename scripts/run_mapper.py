"""Run the mapper on one blind export and write the proposed knowledge graph to SQLite.

Usage: .venv/bin/python scripts/run_mapper.py alpha names_paths [--db data/kg.sqlite] [--llm none]
The project name in the database is "<site>/<variant>".
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.adapters.haystack import read_blind_export  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.mapper.llm import get_provider  # noqa: E402
from projectmodel.mapper.pipeline import Mapper  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("variant", choices=["names_only", "names_paths"])
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    ap.add_argument("--llm", default="none")
    args = ap.parse_args()

    records = read_blind_export(ROOT / "data/blind" / args.site / f"{args.variant}.csv")
    mapper = Mapper(load_knowledge_model(), llm=get_provider(args.llm))
    summary = mapper.run(records, Store(args.db), f"{args.site}/{args.variant}")
    print(json.dumps(summary, indent=2))
