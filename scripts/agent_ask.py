"""Ask the agent one question on a project, from the command line: the steps it takes, its answer, model and cost.

    .venv/bin/python scripts/agent_ask.py "Why is zone 2-14 warm?"
    .venv/bin/python scripts/agent_ask.py --project alpha/names_paths --focus "eq:Airside AHU-2" "What does this feed?"

Uses the same agent, tools, memory and logging as the dock (every call lands in llm_calls).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.agent.chat import Agent, Event  # noqa: E402
from projectmodel.agent.context import Ref, ScreenState, chips_for, context_packet  # noqa: E402
from projectmodel.agent_tools import GraphTools  # noqa: E402
from projectmodel.ai.calls import Router  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402
from projectmodel.knowledge_model import load_knowledge_model  # noqa: E402
from projectmodel.memory import load_knowledge  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--project", default="alpha/names_paths")
    ap.add_argument("--focus", help="a node id the person is looking at")
    ap.add_argument("--model", help="pin a model (fable, opus, sonnet, haiku, hydrogen, argon); default: auto")
    ap.add_argument("--effort", choices=["low", "medium", "high"], help="override the job's effort")
    ap.add_argument("--quiet", action="store_true", help="print only the summary line")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    args = ap.parse_args()

    store, km = Store(args.db), load_knowledge_model()
    tools = GraphTools(store, km, args.project)
    state = ScreenState(page="cli", title="Command line", project=args.project, project_label=args.project)
    if args.focus:
        n = tools.tree.by_id.get(args.focus)
        state.focus = Ref("equipment" if args.focus.startswith("eq:") else "point", args.focus,
                          n.label if n else args.focus)
    packet = context_packet(chips_for(state), state, tools)

    def on(ev: Event) -> None:
        if args.quiet:
            return
        if ev.type == "text":
            print(ev.data, end="", flush=True)
        elif ev.type == "tool":
            print(f"\n  → {ev.data['name']} {ev.data['input']}", flush=True)
        elif ev.type == "tool_result":
            print(f"    {ev.data['summary']}", flush=True)
        elif ev.type == "model":
            print(f"[{ev.data['model']}]", flush=True)

    agent = Agent(Router(), tools=tools, knowledge=load_knowledge(km=km), project=args.project, store=store)
    res = agent.run([], args.question, packet, emit=on, model=args.model, effort=args.effort)
    print(f"\n\nmodel {res.model} · {len(res.steps)} tool calls · ${res.cost_usd:.4f} · {res.seconds:.1f} s · "
          f"calls {res.calls}")
    if not args.quiet:
        print(f"cited: {res.cited}")
    if res.error:
        print(f"ERROR: {res.error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
