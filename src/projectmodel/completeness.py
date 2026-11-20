"""How complete one project's knowledge graph and digital twin are: the cards on top of the twin.

    cards = completeness(store, "alpha/names_paths", twin_payload(...))

Each card is a share (0-1) with what it counts, read from the graph (nodes, edges) and the twin's payload:

  Graph trusted       points and equipment at confidence >= TRUSTED, or decided by a person
  Points on equipment points with a hasPoint link from an equipment
  Equipment classed   equipment with a specific class (not empty, not plain "Equipment")
  Equipment linked    equipment in at least one feeds or hasPart link
  Twin from facts     equipment the twin places from a fact in the graph (a room, a stated floor), not inferred
"""

from __future__ import annotations

from dataclasses import dataclass

from .db.store import Store

TRUSTED = 0.8  # as the project cards (views/projects.py)


@dataclass
class Card:
    key: str
    title: str
    icon: str        # a Material Symbols name
    share: float     # 0-1
    sub: str         # what it counts

    @property
    def tone(self) -> str:
        return "good" if self.share >= 0.9 else "warn" if self.share >= 0.6 else "bad"


def _pct(n: int, total: int) -> float:
    return n / total if total else 0.0


def completeness(store: Store, project: str, payload: dict | None = None) -> list[Card]:
    q = store.conn.execute
    nodes = q("SELECT kind, COUNT(*) n, SUM(confidence >= ? OR method = 'human') ok, AVG(confidence) avg,"
              " SUM(confidence < ? AND method != 'human') low FROM nodes"
              " WHERE project = ? AND status != 'rejected' AND kind IN ('point', 'equipment') GROUP BY kind",
              (TRUSTED, TRUSTED, project)).fetchall()
    by = {r["kind"]: r for r in nodes}
    total = sum(r["n"] for r in nodes)
    trusted = sum(r["ok"] or 0 for r in nodes)
    avg = sum((r["avg"] or 0) * r["n"] for r in nodes) / total if total else 0
    review = sum(r["low"] or 0 for r in nodes)
    n_points = by["point"]["n"] if "point" in by else 0
    n_equip = by["equipment"]["n"] if "equipment" in by else 0

    live = "project = ? AND status != 'rejected'"
    grouped = q(f"SELECT COUNT(DISTINCT dst) FROM edges WHERE {live} AND rel = 'hasPoint'", (project,)).fetchone()[0]
    classes = q("SELECT class, COUNT(*) n FROM nodes WHERE project = ? AND kind = 'equipment' AND status != 'rejected'"
                " GROUP BY class", (project,)).fetchall()
    classed = sum(r["n"] for r in classes if r["class"] and r["class"] != "Equipment")
    rels = dict(q(f"SELECT rel, COUNT(*) FROM edges WHERE {live} AND rel IN ('feeds', 'hasPart') GROUP BY rel",
                  (project,)).fetchall())
    linked = q(f"SELECT COUNT(*) FROM nodes WHERE project = ? AND kind = 'equipment' AND status != 'rejected' AND id IN"
               f" (SELECT src FROM edges WHERE {live} AND rel IN ('feeds', 'hasPart')"
               f"  UNION SELECT dst FROM edges WHERE {live} AND rel IN ('feeds', 'hasPart'))",
               (project, project, project)).fetchone()[0]

    cards = [
        Card("trusted", "Graph trusted", "verified", _pct(trusted, total),
             f"{review:,} to review · avg. confidence {avg:.0%}"),
        Card("grouped", "Points on equipment", "sensors", _pct(grouped, n_points),
             f"{grouped:,} of {n_points:,} points"),
        Card("classed", "Equipment classed", "category", _pct(classed, n_equip),
             f"{classed:,} of {n_equip:,} · {sum(1 for r in classes if r['class'])} classes"),
        Card("linked", "Equipment linked", "account_tree", _pct(linked, n_equip),
             f"{rels.get('feeds', 0):,} feeds · {rels.get('hasPart', 0):,} parts"),
    ]
    if payload is not None:
        equip = payload.get("equip", [])
        rooms = sum(1 for e in equip if e.get("room"))
        stated = sum(1 for e in equip if not e.get("room") and e.get("floor_hint"))
        floors = len(payload.get("levels", []))
        how = "floors from the documents" if payload.get("source") == "graph" else "floors inferred"
        cards.append(Card("twin", "Twin from facts", "domain", _pct(rooms + stated, len(equip)),
                          f"{rooms:,} in rooms · {stated:,} on a stated floor · {floors} levels, {how}"))
    return cards
