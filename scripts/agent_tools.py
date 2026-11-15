"""Call one agent tool on a project's knowledge graph and print the JSON an agent would get.

Usage: .venv/bin/python scripts/agent_tools.py find_nodes '{"query": "VAV 1-2-81", "kind": "equipment"}'
       .venv/bin/python scripts/agent_tools.py describe '{"node_id": "eq:Airside AHU-2/VAV 1-2-81"}'
       .venv/bin/python scripts/agent_tools.py --list
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.agent_tools import TOOLS, GraphTools, call  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tool", nargs="?")
    ap.add_argument("args", nargs="?", default="{}", help="JSON arguments")
    ap.add_argument("--project", default="alpha/names_paths")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    ap.add_argument("--list", action="store_true", help="print the tool definitions")
    a = ap.parse_args()
    if a.list or not a.tool:
        print(json.dumps(TOOLS, indent=2))
    else:
        tools = GraphTools(Store(a.db), load_knowledge_model(), a.project)
        print(json.dumps(call(tools, a.tool, json.loads(a.args)), indent=2, ensure_ascii=False))
