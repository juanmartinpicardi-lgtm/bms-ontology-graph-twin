"""How complete one project's knowledge graph and digital twin are: the cards on top of the twin.

    cards = completeness(store, "alpha/names_paths", twin_payload(...))

Each card is a share (0-1) with what it counts, read from the graph (nodes, edges) and the twin's payload:

  Graph trusted       points and equipment confirmed: by a person, by two agreeing sources, or by the auto-accept
                      rule (db/store.py); the rest are proposed, in the review queue
  Points on equipment points with a hasPoint link from an equipment
  Equipment classed   equipment with a specific class (not empty, not plain "Equipment")
  Equipment linked    equipment in at least one feeds or hasPart link
  On a controller     points that live in a controller (isHostedBy), with the controllers, their networks and the
                      equipment they control (controls)
  Point units         points whose unit is known: a unit as written (most with a QUDT id), or none needed (binary)
  Site and building   a Site node, a Building node, and every floor part of the building
  Twin from facts     equipment the twin places from a fact in the graph (a room, a stated floor), not inferred
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .db.store import Store
from .graph_standard import unitless


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
    nodes = q("SELECT kind, COUNT(*) n, SUM(status = 'confirmed') ok, AVG(confidence) avg,"
              " SUM(status = 'proposed') low FROM nodes"
              " WHERE project = ? AND status != 'rejected' AND kind IN ('point', 'equipment') GROUP BY kind",
              (project,)).fetchall()
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

    def count(sql: str, *args) -> int:
        return q(sql, (project, *args)).fetchone()[0]

    n_ctrl = count("SELECT COUNT(*) FROM nodes WHERE project = ? AND kind = 'controller' AND status != 'rejected'")
    n_net = count("SELECT COUNT(*) FROM nodes WHERE project = ? AND kind = 'network' AND status != 'rejected'")
    hosted = count(f"SELECT COUNT(DISTINCT src) FROM edges WHERE {live} AND rel = 'isHostedBy'")
    n_controlled = count(f"SELECT COUNT(DISTINCT dst) FROM edges WHERE {live} AND rel = 'controls'")
    pt_attrs = [json.loads(r[0] or "{}") for r in q("SELECT attrs FROM nodes WHERE project = ? AND kind = 'point'"
                                                     " AND status != 'rejected'", (project,))]
    with_unit = sum(1 for a in pt_attrs if a.get("units"))
    qudt = sum(1 for a in pt_attrs if a.get("unit"))
    n_unitless = sum(1 for a in pt_attrs if not a.get("units") and unitless(a))
    spaces = dict(q("SELECT class, COUNT(*) FROM nodes WHERE project = ? AND kind = 'location' AND status != 'rejected'"
                    " AND class IN ('Site', 'Building', 'Floor') GROUP BY class", (project,)).fetchall())
    floors_in = count("SELECT COUNT(DISTINCT e.dst) FROM edges e JOIN nodes b ON b.project = e.project AND b.id = e.src"
                      " JOIN nodes f ON f.project = e.project AND f.id = e.dst WHERE e.project = ?"
                      " AND e.status != 'rejected' AND e.rel = 'hasPart' AND b.class = 'Building'"
                      " AND f.class = 'Floor'")
    n_floors = spaces.get("Floor", 0)
    site_checks = [spaces.get("Site", 0) > 0, spaces.get("Building", 0) > 0, floors_in == n_floors]

    cards = [
        Card("trusted", "Graph trusted", "verified", _pct(trusted, total),
             f"{review:,} to review · avg. confidence {avg:.0%}"),
        Card("grouped", "Points on equipment", "sensors", _pct(grouped, n_points),
             f"{grouped:,} of {n_points:,} points"),
        Card("classed", "Equipment classed", "category", _pct(classed, n_equip),
             f"{classed:,} of {n_equip:,} · {sum(1 for r in classes if r['class'])} classes"),
        Card("linked", "Equipment linked", "account_tree", _pct(linked, n_equip),
             f"{rels.get('feeds', 0):,} feeds · {rels.get('hasPart', 0):,} parts"),
        Card("controlled", "On a controller", "memory", _pct(hosted, n_points),
             f"{hosted:,} of {n_points:,} points · {n_ctrl:,} controllers on {n_net:,} networks · "
             f"{n_controlled:,} equipment controlled" if n_ctrl else "no controllers: needs the riser or BMS devices"),
        Card("units", "Point units", "straighten", _pct(with_unit + n_unitless, n_points),
             f"{with_unit:,} with a unit ({qudt:,} QUDT) · {n_unitless:,} binary" if with_unit or n_unitless
             else "no units in the input"),
        Card("site", "Site and building", "location_city", _pct(sum(site_checks), len(site_checks)) if
             spaces.get("Site") or spaces.get("Building") else 0.0,
             f"site {'yes' if site_checks[0] else 'no'} · building {'yes' if site_checks[1] else 'no'} · "
             f"{floors_in} of {n_floors} floors in it"),
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
