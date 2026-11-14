"""Store a project's sequences of operation as behaviour edges in the graph (method document).

Usage: .venv/bin/python scripts/load_sequences.py alpha/names_paths [--db data/kg.sqlite]
run_mapper.py already does this after mapping; run this after editing data/documents/<site>/sequences.yaml.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.conventions import scopes_for  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.sequences import store_behaviour  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="<site>/<variant>, e.g. alpha/names_paths")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    args = ap.parse_args()
    out = store_behaviour(Store(args.db), load_knowledge_model(conventions=scopes_for(args.project)), args.project)
    print(json.dumps(out, indent=2) if out else "No sequences document for this site.")
