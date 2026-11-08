"""Equipment tree of one project: equipment nested by hasPart, points under their equipment, and the
provenance of every node and of the edge that places it. Rejected edges are left out; rejected
nodes stay in the tree (marked) so a reviewer can still see them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .db.store import Store

UNPLACED = "eq:(unplaced)"
ROOT = Path(__file__).resolve().parents[2]


def provenance(row) -> dict:
    """The provenance fields of a node or edge row, with the source file relative to the repo."""
    attrs = json.loads(row["attrs"])
    src = row["source_file"]
    try:
        src = str(Path(src).resolve().relative_to(ROOT))
    except ValueError:
        pass
    out = {"source_file": src, "source_ref": row["source_ref"], "method": row["method"],
           "confidence": row["confidence"], "status": row["status"], "revision": row["revision"]}
    if "review" in attrs:
        out["review"] = attrs["review"]
    return out


@dataclass
class TreeNode:
    id: str
    kind: str
    label: str
    cls: str | None
    prov: dict
    attrs: dict
    via: dict | None = None  # provenance of the edge that places this node under its parent
    children: list[TreeNode] = field(default_factory=list)  # equipment parts
    points: list[TreeNode] = field(default_factory=list)
    depth: int = 0

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    @property
    def total_points(self) -> int:
        return sum(len(n.points) for n in self.walk())


@dataclass
class Tree:
    roots: list[TreeNode]
    by_id: dict[str, TreeNode]
    parent: dict[str, str]
    feeds: list[tuple[str, str, dict]]  # (src, dst, edge provenance)

    def walk(self):
        for r in self.roots:
            yield from r.walk()

    def path(self, node_id: str) -> list[TreeNode]:
        """Ancestors from the root down to (and including) the node."""
        out, seen = [], set()
        while node_id and node_id not in seen:
            seen.add(node_id)
            out.append(self.by_id[node_id])
            node_id = self.parent.get(node_id)
        return out[::-1]

    def fed_by(self, node_id: str):
        return [(s, p) for s, d, p in self.feeds if d == node_id]

    def feeds_to(self, node_id: str):
        return [(d, p) for s, d, p in self.feeds if s == node_id]


def _node(row) -> TreeNode:
    return TreeNode(row["id"], row["kind"], row["label"], row["class"], provenance(row), json.loads(row["attrs"]))


def build_tree(store: Store, project: str) -> Tree:
    equip = {r["id"]: _node(r) for r in store.nodes(project, "equipment")}
    points = {r["id"]: _node(r) for r in store.nodes(project, "point")}
    live = lambda rel: [e for e in store.edges(project, rel) if e["status"] != "rejected"]  # noqa: E731

    parent: dict[str, str] = {}
    for e in sorted(live("hasPart"), key=lambda e: (e["method"] != "human", e["src"])):
        if e["src"] in equip and e["dst"] in equip and e["dst"] not in parent:
            parent[e["dst"]] = e["src"]
            equip[e["dst"]].via = provenance(e)
    # Break any cycle so every equipment is reachable from a root.
    for start in list(parent):
        seen, cur = set(), start
        while cur in parent and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
        if cur in seen:
            equip[cur].via = None
            del parent[cur]
    for child, par in parent.items():
        equip[par].children.append(equip[child])

    placed = set()
    for e in sorted(live("hasPoint"), key=lambda e: (e["method"] != "human", e["src"])):
        if e["src"] in equip and e["dst"] in points and e["dst"] not in placed:
            placed.add(e["dst"])
            points[e["dst"]].via = provenance(e)
            equip[e["src"]].points.append(points[e["dst"]])
            parent[e["dst"]] = e["src"]

    roots = sorted((n for i, n in equip.items() if i not in parent), key=lambda n: n.label)
    loose = [p for i, p in points.items() if i not in placed]
    if loose:
        bucket = TreeNode(UNPLACED, "equipment", "(points not on any equipment)", None, {}, {}, points=loose)
        equip[UNPLACED] = bucket
        for p in loose:
            parent[p.id] = UNPLACED
        roots.append(bucket)

    def settle(n: TreeNode, depth: int):
        n.depth = depth
        n.children.sort(key=lambda c: c.label)
        n.points.sort(key=lambda p: p.label)
        for p in n.points:
            p.depth = depth + 1
        for c in n.children:
            settle(c, depth + 1)

    for r in roots:
        settle(r, 0)
    feeds = [(e["src"], e["dst"], provenance(e)) for e in live("feeds") if e["src"] in equip and e["dst"] in equip]
    return Tree(roots, equip | points, parent, feeds)
