"""Agent tools: the knowledge graph as a small set of read-only functions an agent can call.

An agent should not read SQLite or guess node ids. It calls:
  find_nodes   search equipment and points by name words and class
  describe     one node with everything around it: class, parts, points with their template role, what feeds it,
               required points that are missing
  upstream     what a node depends on, following feeds links backwards (VAV <- AHU <- chilled water plant)
  downstream   what a node affects, following feeds links forwards
  behaviour    control loops, interlocks, resets and requests the sequences of operation state for a node

Every fact comes back with `trust`, so the agent can tell a checked fact from a guess:
  verified  a person decided it (method human)
  stated    a project document says so (method document): intent, not confirmed as built
  likely    the mapper decided it with confidence >= LIKELY
  unsure    the mapper decided it with lower confidence
`likely` rests on the mapper's confidence, which is not calibrated yet (see the score report's calibration table).

TOOLS holds the tool definitions (name, description, JSON schema), `call` runs one by name with JSON arguments and
returns JSON-ready data, so any LLM provider's tool loop can use them. Nothing here writes to the graph.
"""

from __future__ import annotations

import json
from collections import deque

from .db.store import Store
from .equipment_view import assign_slots
from .knowledge_model import KnowledgeModel
from .tree import UNPLACED, TreeNode, build_tree, provenance

LIKELY = 0.8  # the score report's confidence threshold


def trust(prov: dict) -> str:
    if prov.get("method") == "human":
        return "verified"
    if prov.get("method") == "document":
        return "stated"
    return "likely" if (prov.get("confidence") or 0) >= LIKELY else "unsure"


class GraphTools:
    def __init__(self, store: Store, km: KnowledgeModel, project: str):
        self.store, self.km, self.project = store, km, project
        self.tree = build_tree(store, project)
        live = [e for e in store.edges(project) if e["status"] != "rejected"]
        self.feeds = [(e["src"], e["dst"], json.loads(e["attrs"]).get("medium"), provenance(e))
                      for e in live if e["rel"] == "feeds"]
        self.document_edges = [e for e in live if e["method"] == "document"]
        self._roles: dict[str, tuple[dict, list]] = {}

    # helpers -----------------------------------------------------------------------------------

    def _get(self, node_id: str) -> TreeNode:
        n = self.tree.by_id.get(node_id)
        if n is None or node_id == UNPLACED:
            raise KeyError(f"no node {node_id!r} in {self.project}; use find_nodes to get ids")
        return n

    def _equipment_of(self, n: TreeNode) -> TreeNode | None:
        return n if n.kind == "equipment" else self.tree.by_id.get(self.tree.parent.get(n.id, ""))

    def _brief(self, n: TreeNode) -> dict:
        out = {"id": n.id, "kind": n.kind, "name": n.label, "class": n.cls, "trust": trust(n.prov),
               "confidence": n.prov.get("confidence")}
        if n.kind == "point" and (eq := self._equipment_of(n)):
            out["equipment"] = {"id": eq.id, "name": eq.label}
        return out

    def _is_a(self, cls: str | None, want: str) -> bool:
        return bool(cls) and (cls == want or (cls in self.km.classes and want in self.km.classes
                                              and self.km.is_a(cls, want)))

    def _points(self, eq: TreeNode) -> list[tuple[TreeNode, str | None]]:
        """The equipment's points, with those of its parts that are not equipment in their own right (a fan's VFD
        folder), each with the part's name as context."""
        out = [(p, None) for p in eq.points]
        for c in eq.children:
            if not c.attrs.get("template"):
                out += [(p, c.label) for p in c.points]
        return [(p, ctx) for p, ctx in out if p.prov.get("status") != "rejected"]

    def _slot_roles(self, eq: TreeNode) -> tuple[dict[str, str], list[str]]:
        """point id -> template slot role, and the required roles no point fills."""
        if eq.id not in self._roles:
            t = self.km.templates.get(eq.attrs.get("template") or "")
            roles, missing = {}, []
            if t:
                slots, _ = assign_slots(t, [{"id": p.id, "label": p.label, "cls": p.cls, "context": ctx}
                                            for p, ctx in self._points(eq)], self.km)
                roles = {pid: role for role, pids in slots.items() for pid in pids}
                missing = [s.role for s in t.slots if s.required and not slots.get(s.role)]
            self._roles[eq.id] = (roles, missing)
        return self._roles[eq.id]

    def _link(self, other: str, medium: str | None, prov: dict) -> dict:
        n = self.tree.by_id[other]
        return {"id": n.id, "name": n.label, "class": n.cls, "medium": medium, "trust": trust(prov),
                "confidence": prov.get("confidence")}

    # tools -------------------------------------------------------------------------------------

    def find_nodes(self, query: str = "", cls: str = "", kind: str = "", limit: int = 20) -> dict:
        words = query.lower().split()
        hits = []
        for n in self.tree.by_id.values():
            if n.id == UNPLACED or (kind and n.kind != kind) or (cls and not self._is_a(n.cls, cls)):
                continue
            eq = self._equipment_of(n)
            text = f"{n.label} {eq.label if eq and eq is not n else ''}".lower()
            if all(w in text for w in words):
                hits.append(n)
        hits.sort(key=lambda n: (n.kind != "equipment", len(n.label), n.label))
        return {"total": len(hits), "nodes": [self._brief(n) for n in hits[:limit]]}

    def describe(self, node_id: str) -> dict:
        n = self._get(node_id)
        out = self._brief(n) | {"source": {k: n.prov.get(k) for k in ("source_file", "source_ref", "method", "revision")}}
        if n.kind == "point":
            eq = self._equipment_of(n)
            out["role"] = self._slot_roles(eq)[0].get(n.id) if eq else None
            out["other_candidate_classes"] = [c for c, _ in n.attrs.get("alternatives", []) if c != n.cls][:3]
            out["behaviour"] = self.behaviour(node_id)["facts"]
            return out
        roles, missing = self._slot_roles(n)
        parent = self.tree.by_id.get(self.tree.parent.get(n.id, ""))
        out |= {
            "template": n.attrs.get("template"),
            "part_of": {"id": parent.id, "name": parent.label, "class": parent.cls} if parent else None,
            "parts": [self._brief(c) for c in n.children],
            "fed_by": [self._link(s, m, p) for s, d, m, p in self.feeds if d == n.id],
            "feeds": [self._link(d, m, p) for s, d, m, p in self.feeds if s == n.id],
            "points": [self._brief(p) | {"role": roles.get(p.id), "on_part": ctx} for p, ctx in self._points(n)],
            "missing_required_points": missing,
        }
        for p in out["points"]:
            del p["equipment"], p["kind"]
        return out

    def _walk(self, node_id: str, forward: bool, medium: str) -> dict:
        start = self._equipment_of(self._get(node_id))
        if start is None:
            return {"from": node_id, "nodes": []}
        seen, out, queue = {start.id}, [], deque([(start.id, 0)])
        while queue:
            cur, depth = queue.popleft()
            for s, d, m, prov in self.feeds:
                here, other = (s, d) if forward else (d, s)
                if here != cur or other in seen or (medium and m != medium):
                    continue
                seen.add(other)
                out.append(self._link(other, m, prov) | {"steps": depth + 1, "via": cur})
                queue.append((other, depth + 1))
        return {"from": {"id": start.id, "name": start.label}, "total": len(out), "nodes": out}

    def upstream(self, node_id: str, medium: str = "") -> dict:
        return self._walk(node_id, False, medium)

    def downstream(self, node_id: str, medium: str = "") -> dict:
        return self._walk(node_id, True, medium)

    def behaviour(self, node_id: str) -> dict:
        n = self._get(node_id)
        ids = {n.id} | ({p.id for p, _ in self._points(n)} if n.kind == "equipment" else set())
        facts = []
        for e in self.document_edges:
            if e["src"] not in ids and e["dst"] not in ids:
                continue
            attrs = json.loads(e["attrs"])
            end = lambda i: {k: v for k, v in self._brief(self.tree.by_id[i]).items()  # noqa: E731
                             if k in ("id", "name", "class", "equipment")}
            fact = {"relation": e["rel"], "from": end(e["src"]), "to": end(e["dst"]), "loop": attrs.get("loop"),
                    "sequences": attrs.get("sequences", []), "source": f"{provenance(e)['source_file']} · {e['source_ref']}",
                    "trust": "stated"}
            if attrs.get("conflict"):
                fact["conflict"] = "the sequence implies another class for: " + ", ".join(attrs["conflict"])
            facts.append(fact)
        note = None if facts else "No sequence of operations covers this node yet."
        return {"node": {"id": n.id, "name": n.label}, "facts": facts, "note": note}


_ID = {"type": "string", "description": "Node id, as returned by find_nodes (e.g. 'eq:Airside AHU-2')."}
_MEDIUM = {"type": "string", "enum": ["", "air", "chilled_water", "hot_water"],
           "description": "Follow only links carrying this medium. Empty for all."}
TOOLS = [
    {"name": "find_nodes",
     "description": "Search the building's equipment and points by name words and Brick class. Start here to get ids.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words that must all appear in the name or its equipment's name."},
         "cls": {"type": "string", "description": "Brick class or parent class, e.g. 'VAV', 'Temperature_Sensor'."},
         "kind": {"type": "string", "enum": ["", "equipment", "point"]},
         "limit": {"type": "integer", "default": 20}}}},
    {"name": "describe",
     "description": "One equipment or point with its class, parts, points (with their role on the equipment), what "
                    "feeds it, required points that are missing, and where each fact comes from.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID}, "required": ["node_id"]}},
    {"name": "upstream",
     "description": "Everything a node depends on, following feeds links backwards (a VAV's AHU, then its plants).",
     "input_schema": {"type": "object", "properties": {"node_id": _ID, "medium": _MEDIUM}, "required": ["node_id"]}},
    {"name": "downstream",
     "description": "Everything a node affects, following feeds links forwards (the VAVs an AHU supplies).",
     "input_schema": {"type": "object", "properties": {"node_id": _ID, "medium": _MEDIUM}, "required": ["node_id"]}},
    {"name": "behaviour",
     "description": "Control loops, interlocks, resets and requests the sequences of operation state for a node. "
                    "Intent from a document, not confirmed as built.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID}, "required": ["node_id"]}},
]


def call(tools: GraphTools, name: str, args: dict | None = None) -> dict:
    """Run one tool by name. Errors come back as {"error": ...} so an agent can correct itself."""
    if name not in {t["name"] for t in TOOLS}:
        return {"error": f"unknown tool {name!r}; available: {[t['name'] for t in TOOLS]}"}
    try:
        return getattr(tools, name)(**(args or {}))
    except (KeyError, TypeError) as e:
        return {"error": str(e.args[0]) if e.args else str(e)}
