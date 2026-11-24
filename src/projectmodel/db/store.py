"""SQLite store for the knowledge graph: nodes and edges, every one with provenance, for one project fed by many
sources.

Every node and edge stores: source (the run that owns the row), source_file, source_ref (row number, page or folder
path), method (parsed | rule | template | llm | human | document), confidence (0-1), status (proposed | confirmed |
rejected), confirmed_by (why it is confirmed), revision.

Many sources, one project
    A source is one input that can be read again on its own: the mapper on one export (`mapper:names_paths.csv`), one
    step of the guided setup (`setup:bms`), one document of sequences (`document:<file>`). `write_source` replaces
    what that source said before and nothing else: other sources' rows and every decision a person made in the app
    (source `review`) stay.

    What each source states is kept in `claims`, one row per source and fact. The first source to state a fact owns
    its node or edge row; a later source stating the same fact adds a claim. When the owner stops stating it, the row
    passes to another source that still does, or goes.

Statuses: nothing is confirmed by accident
    A machine row is written `proposed`. `settle` confirms it only when
      - two or more sources state the same fact (same node and class, or same edge): confirmed_by = agreement;
      - or its confidence reaches the auto-accept threshold (AutoAccept, 0.9 by default): confirmed_by = auto;
    and never while sources disagree (a node with two classes, a point on two equipment, a unit fed by two air
    handlers): that row stays proposed with attrs.conflict listing the other sources' answers. A writer can also hold
    a row for review (status `proposed`, e.g. a question the guided setup asked). A person's decision (method human)
    is confirmed_by = human.

Aliases
    `aliases` maps the names other sources use for a node to its id: schedule_tag, bms_name, bms_path, device_object
    (BACnet device instance:object), bacnet_device, submittal_ref, haystack_id, export_id (a row id in a blind
    export). A source's new node is first
    resolved through them, so the same unit read from a schedule, a submittal and a BMS export is one node.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

METHODS = ("parsed", "rule", "template", "llm", "human", "document")
STATUSES = ("proposed", "confirmed", "rejected")
CONFIRMED_BY = ("human", "agreement", "auto")
# location: a site, building, floor, zone or room of a building added from its documents; controller and network: the
# BACnet devices and trunks of a controls riser or a BMS export (ba:Field_Controller, ba:Field_Network)
KINDS = ("point", "equipment", "location", "controller", "network")
REVIEW = "review"  # the source of rows a person decided in the app (review.py): no source run replaces them
ALIAS_SCHEMES = ("schedule_tag", "bms_name", "bms_path", "device_object", "bacnet_device", "submittal_ref",
                 "haystack_id", "export_id")
# Relations where a second, different answer from another source is a conflict, keyed by the end that has one answer:
# a point is on one equipment and lives in one controller, a unit is in one place and serves one room here, a unit has
# one feeder per medium.
FUNCTIONAL = {"hasPoint": "dst", "hasLocation": "src", "serves": "src", "feeds": "dst", "isHostedBy": "src"}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS nodes (
    project     TEXT NOT NULL,
    id          TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN {KINDS}),
    label       TEXT NOT NULL,
    class       TEXT,
    source_file TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    method      TEXT NOT NULL CHECK (method IN {METHODS}),
    confidence  REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status      TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN {STATUSES}),
    revision    INTEGER NOT NULL,
    attrs       TEXT NOT NULL DEFAULT '{{}}',
    source      TEXT NOT NULL DEFAULT '',
    confirmed_by TEXT CHECK (confirmed_by IS NULL OR confirmed_by IN {CONFIRMED_BY}),
    PRIMARY KEY (project, id)
);
CREATE TABLE IF NOT EXISTS edges (
    project     TEXT NOT NULL,
    src         TEXT NOT NULL,
    rel         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    method      TEXT NOT NULL CHECK (method IN {METHODS}),
    confidence  REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status      TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN {STATUSES}),
    revision    INTEGER NOT NULL,
    attrs       TEXT NOT NULL DEFAULT '{{}}',
    source      TEXT NOT NULL DEFAULT '',
    confirmed_by TEXT CHECK (confirmed_by IS NULL OR confirmed_by IN {CONFIRMED_BY}),
    PRIMARY KEY (project, src, rel, dst)
);
CREATE TABLE IF NOT EXISTS claims (           -- what each source states: a node and its class, or an edge
    project     TEXT NOT NULL,
    source      TEXT NOT NULL,
    src         TEXT NOT NULL,                -- the node id, or the edge's src
    rel         TEXT NOT NULL DEFAULT '',     -- '' for a node
    dst         TEXT NOT NULL DEFAULT '',     -- '' for a node
    value       TEXT,                         -- a node's class; an edge's medium (feeds); NULL: no opinion
    source_file TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    method      TEXT NOT NULL CHECK (method IN {METHODS}),
    confidence  REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status      TEXT CHECK (status IS NULL OR status IN {STATUSES}),  -- set: the writer held or decided it
    revision    INTEGER NOT NULL,
    PRIMARY KEY (project, source, src, rel, dst)
);
CREATE INDEX IF NOT EXISTS claims_fact ON claims (project, src, rel, dst);
CREATE TABLE IF NOT EXISTS aliases (          -- the names sources use for a node
    project     TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    scheme      TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT NOT NULL,
    source_file TEXT NOT NULL,
    method      TEXT NOT NULL CHECK (method IN {METHODS}),
    confidence  REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (project, source, scheme, value, node_id)
);
CREATE INDEX IF NOT EXISTS aliases_value ON aliases (project, scheme, value);
CREATE TABLE IF NOT EXISTS runs (
    project     TEXT NOT NULL,
    revision    INTEGER NOT NULL,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    source_file TEXT NOT NULL,
    seconds     REAL,
    summary     TEXT,
    PRIMARY KEY (project, revision)
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL,
    revision    INTEGER NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT,
    input       TEXT NOT NULL,
    output      TEXT,
    cost_usd    REAL NOT NULL DEFAULT 0,
    latency_s   REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    job         TEXT,                        -- the job in ai/jobs.py (point_class, agent_chat...)
    prompt      TEXT,                        -- prompt id and version, e.g. point_class@1
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    ok          INTEGER NOT NULL DEFAULT 1,  -- 0: the call failed or its output was invalid
    error       TEXT
);
CREATE TABLE IF NOT EXISTS agent_chats (       -- the agent dock's conversations, for its history
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL DEFAULT '',
    person      TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    log         TEXT NOT NULL,                -- what the dock shows: turns with steps, model, cost
    api         TEXT NOT NULL,                -- the messages sent to the model, so the conversation can go on
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project      TEXT NOT NULL,
    target_kind  TEXT NOT NULL CHECK (target_kind IN ('node', 'edge', 'project')),
    target_id    TEXT NOT NULL,
    target_label TEXT NOT NULL,
    topic        TEXT NOT NULL CHECK (topic IN ('naming', 'history', 'operations', 'maintenance', 'other')),
    body         TEXT NOT NULL,
    author       TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'review', 'interview', 'document')),
    source_ref   TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'superseded')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
NEW_ROW_COLUMNS = {"source": "TEXT NOT NULL DEFAULT ''",
                   "confirmed_by": f"TEXT CHECK (confirmed_by IS NULL OR confirmed_by IN {CONFIRMED_BY})"}
DERIVED = ("sources", "agree", "conflict")  # attrs keys settle() writes; recomputed every time


@dataclass(frozen=True)
class AutoAccept:
    """When a machine row is confirmed without a person. `threshold`: confidence at or above which a row is confirmed
    (None: never). `agreement`: how many distinct sources must state the same fact to confirm it (0: never)."""
    threshold: float | None = 0.9
    agreement: int = 2

    @classmethod
    def from_env(cls) -> "AutoAccept":
        """PM_AUTO_ACCEPT=0.95 (a threshold) or off; PM_AUTO_AGREE=2 (sources) or 0 (off)."""
        t = os.environ.get("PM_AUTO_ACCEPT", "0.9").strip().lower()
        return cls(threshold=None if t in ("off", "none", "") else float(t),
                   agreement=int(os.environ.get("PM_AUTO_AGREE", "2")))


@dataclass
class Node:
    id: str
    kind: str
    label: str
    cls: str | None
    source_file: str
    source_ref: str
    method: str
    confidence: float
    attrs: dict = field(default_factory=dict)
    aliases: list[tuple[str, str]] = field(default_factory=list)  # (scheme, value)
    status: str | None = None  # None: settle decides; proposed: hold for review; confirmed/rejected: method human


@dataclass
class Edge:
    src: str
    rel: str
    dst: str
    source_file: str
    source_ref: str
    method: str
    confidence: float
    attrs: dict = field(default_factory=dict)
    status: str | None = None


@dataclass
class Claim:
    """A source stating a fact it does not write a row for: another source owns the row, or the source only names
    the node (rel ''). It never creates a row, but it counts for agreement and conflict, takes the row over if the
    owner stops stating it, and can carry aliases for the node."""
    src: str
    source_file: str
    source_ref: str
    method: str
    confidence: float
    rel: str = ""
    dst: str = ""
    value: str | None = None
    aliases: list[tuple[str, str]] = field(default_factory=list)
    status: str | None = None


def legacy_source(project: str, method: str, source_file: str) -> str:
    """The source of a row written before rows had one: a person's decision in the app, a sequences document, the
    guided setup, or the mapper on its input file (the name `Mapper.run` uses)."""
    if method == "human" and source_file == "review":
        return REVIEW
    if method == "document":
        return f"document:{source_file}"
    if project.endswith("/documents"):
        return "setup:legacy"
    return f"mapper:{Path(source_file).name}"


class Store:
    def __init__(self, path: Path | str, auto: AutoAccept | None = None):
        self.path = str(path)
        self.auto = auto or AutoAccept.from_env()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate_methods()
        self._migrate_row_columns()
        self.conn.executescript(SCHEMA)
        self._migrate_llm_calls()
        if self.conn.execute("SELECT 1 FROM nodes WHERE source = '' UNION ALL SELECT 1 FROM edges WHERE source = ''"
                             " LIMIT 1").fetchone():
            self._migrate_sources()

    LLM_CALL_COLUMNS = {"job": "TEXT", "prompt": "TEXT", "input_tokens": "INTEGER NOT NULL DEFAULT 0",
                        "output_tokens": "INTEGER NOT NULL DEFAULT 0", "cached_tokens": "INTEGER NOT NULL DEFAULT 0",
                        "ok": "INTEGER NOT NULL DEFAULT 1", "error": "TEXT"}

    # migrations ---------------------------------------------------------------------------------

    def _migrate_llm_calls(self) -> None:
        """Older databases have llm_calls without the job, prompt, token and outcome columns: add them."""
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(llm_calls)")}
        with self.conn:
            for col, decl in self.LLM_CALL_COLUMNS.items():
                if col not in have:
                    self.conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {col} {decl}")

    def _migrate_methods(self) -> None:
        """Older databases check method (or a node's kind) against a shorter list; rebuild those tables with the
        current checks, keeping the columns they have."""
        for table in ("nodes", "edges", "claims", "aliases"):
            row = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not row or all(f"'{m}'" in row[0] for m in METHODS + (KINDS if table == "nodes" else ())):
                continue
            cols = ", ".join(r[1] for r in self.conn.execute(f"PRAGMA table_info({table})"))
            with self.conn:
                self.conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
                self.conn.executescript(SCHEMA)
                self.conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {table}_old")
                self.conn.execute(f"DROP TABLE {table}_old")

    def _migrate_row_columns(self) -> None:
        """Older nodes and edges have no source or confirmed_by: add them (empty, filled by _migrate_sources)."""
        with self.conn:
            for table in ("nodes", "edges"):
                have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if not have:
                    continue
                for col, decl in NEW_ROW_COLUMNS.items():
                    if col not in have:
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    def _migrate_sources(self) -> None:
        """Rows written before sources existed: give each its source (legacy_source), record what it states as that
        source's claim, then settle every project, so machine rows written `confirmed` become proposed unless the
        auto-accept rule confirms them. People's decisions keep their status."""
        with self.conn:
            for table, key in (("nodes", "id, '', ''"), ("edges", "src, rel, dst")):
                for r in self.conn.execute(f"SELECT rowid, project, method, source_file FROM {table} "
                                           "WHERE source = ''").fetchall():
                    self.conn.execute(f"UPDATE {table} SET source = ? WHERE rowid = ?",
                                      (legacy_source(r["project"], r["method"], r["source_file"]), r["rowid"]))
                value = "class" if table == "nodes" else "json_extract(attrs, '$.medium')"
                self.conn.execute(
                    f"INSERT OR IGNORE INTO claims (project, source, src, rel, dst, value, source_file, source_ref,"
                    f" method, confidence, status, revision) SELECT project, source, {key}, {value}, source_file,"
                    f" source_ref, method, confidence, CASE WHEN method = 'human' THEN status END, revision"
                    f" FROM {table} WHERE source != ?", (REVIEW,))
        for (project,) in self.conn.execute("SELECT DISTINCT project FROM nodes").fetchall():
            self.settle(project)

    # runs ---------------------------------------------------------------------------------------

    def start_run(self, project: str, source_file: str) -> int:
        cur = self.conn.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM runs WHERE project = ?", (project,))
        revision = cur.fetchone()[0]
        self.conn.execute("INSERT INTO runs (project, revision, source_file) VALUES (?, ?, ?)",
                          (project, revision, source_file))
        return revision

    # writing one source -------------------------------------------------------------------------

    def write_source(self, project: str, source: str, revision: int, nodes: list[Node] = (),
                     edges: list[Edge] = (), claims: list[Claim] = ()) -> dict:
        """Replace everything `source` said about `project` with these nodes, edges and claims, then settle the
        project's statuses. Other sources' rows and people's decisions (source review) are left as they are.

        A new node is first resolved through the aliases other sources gave: if one of its aliases names an existing
        node, it is that node. Returns counts: written, claimed (stated a row someone else owns), released (rows this
        source no longer states that passed to another source), deleted, resolved (nodes found through an alias)."""
        if source == REVIEW:
            raise ValueError("source 'review' is a person's decisions in the app, written by review.py")
        nodes, edges, claims = list(nodes), list(edges), list(claims)
        out = dict.fromkeys(("written", "claimed", "released", "deleted", "resolved"), 0)
        with self.conn:
            remap = self._resolve(project, source, nodes)
            out["resolved"] = len(remap)
            if remap:
                to = lambda i: remap.get(i, i)  # noqa: E731
                for n in nodes:
                    n.id = to(n.id)
                for e in edges:
                    e.src, e.dst = to(e.src), to(e.dst)
                for c in claims:
                    c.src = to(c.src)
                    c.dst = to(c.dst) if c.rel else c.dst
            self.conn.execute("DELETE FROM claims WHERE project = ? AND source = ?", (project, source))
            self.conn.execute("DELETE FROM aliases WHERE project = ? AND source = ?", (project, source))

            claim_rows, alias_rows = [], []

            def claim(src, rel, dst, value, sf, sr, method, conf, status):
                claim_rows.append((project, source, src, rel, dst, value, sf, sr, method, round(conf, 4), status,
                                   revision))

            def alias(node_id, pairs, sf, method, conf):
                alias_rows.extend((project, node_id, scheme, str(value), source, sf, method, round(conf, 4))
                                  for scheme, value in pairs if value not in (None, ""))

            # nodes
            owned = {r["id"] for r in self.conn.execute("SELECT id FROM nodes WHERE project = ? AND source = ?",
                                                        (project, source))}
            stated = {n.id for n in nodes}
            for n in nodes:
                if n.id in owned or not self._has_node(project, n.id):
                    self.conn.execute(
                        "INSERT OR REPLACE INTO nodes (project, id, kind, label, class, source_file, source_ref,"
                        " method, confidence, status, revision, attrs, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                        " ?, ?, ?)",
                        (project, n.id, n.kind, n.label, n.cls, n.source_file, n.source_ref, n.method,
                         round(n.confidence, 4), n.status or "proposed", revision, json.dumps(n.attrs, default=str),
                         source))
                    out["written"] += 1
                else:
                    out["claimed"] += 1
                claim(n.id, "", "", n.cls, n.source_file, n.source_ref, n.method, n.confidence, n.status)
                alias(n.id, n.aliases, n.source_file, n.method, n.confidence)

            # edges
            owned_e = {(r["src"], r["rel"], r["dst"]) for r in self.conn.execute(
                "SELECT src, rel, dst FROM edges WHERE project = ? AND source = ?", (project, source))}
            stated_e = set()
            for e in edges:
                key = (e.src, e.rel, e.dst)
                if key in stated_e:
                    continue
                stated_e.add(key)
                if key in owned_e or not self.conn.execute(
                        "SELECT 1 FROM edges WHERE project = ? AND src = ? AND rel = ? AND dst = ?",
                        (project, *key)).fetchone():
                    self.conn.execute(
                        "INSERT OR REPLACE INTO edges (project, src, rel, dst, source_file, source_ref, method,"
                        " confidence, status, revision, attrs, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (project, *key, e.source_file, e.source_ref, e.method, round(e.confidence, 4),
                         e.status or "proposed", revision, json.dumps(e.attrs, default=str), source))
                    out["written"] += 1
                else:
                    out["claimed"] += 1
                claim(*key, (e.attrs or {}).get("medium"), e.source_file, e.source_ref, e.method, e.confidence,
                      e.status)

            # claims that write no row
            for c in claims:
                claim(c.src, c.rel, c.dst, c.value, c.source_file, c.source_ref, c.method, c.confidence, c.status)
                if not c.rel:
                    alias(c.src, c.aliases, c.source_file, c.method, c.confidence)
            self.conn.executemany(
                "INSERT OR REPLACE INTO claims (project, source, src, rel, dst, value, source_file, source_ref,"
                " method, confidence, status, revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", claim_rows)
            self.conn.executemany(
                "INSERT OR IGNORE INTO aliases (project, node_id, scheme, value, source, source_file, method,"
                " confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", alias_rows)

            # rows this source owned and no longer writes: to another source that still states them, else gone
            for nid in owned - stated:
                out["released" if self._release(project, "nodes", (nid, "", "")) else "deleted"] += 1
            for key in owned_e - stated_e:
                out["released" if self._release(project, "edges", key) else "deleted"] += 1
        self.settle(project)
        return out

    def remove_source(self, project: str, source: str) -> dict:
        """Everything `source` said about `project` goes; rows other sources still state pass to them."""
        return self.write_source(project, source, self._revision(project))

    def _revision(self, project: str) -> int:
        return self.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM runs WHERE project = ?",
                                 (project,)).fetchone()[0]

    def _has_node(self, project: str, node_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM nodes WHERE project = ? AND id = ?", (project, node_id)).fetchone() \
            is not None

    def _resolve(self, project: str, source: str, nodes: list[Node]) -> dict[str, str]:
        """New node id -> existing node id, through the aliases other sources gave. Only for nodes that do not exist
        yet, and only when the aliases name exactly one node."""
        remap = {}
        for n in nodes:
            if not n.aliases or self._has_node(project, n.id):
                continue
            hits = set()
            for scheme, value in n.aliases:
                hits |= {r[0] for r in self.conn.execute(
                    "SELECT node_id FROM aliases WHERE project = ? AND scheme = ? AND value = ? AND source != ?",
                    (project, scheme, str(value), source))}
            hits = {h for h in hits if self._has_node(project, h)}
            if len(hits) == 1:
                remap[n.id] = hits.pop()
        return remap

    def _release(self, project: str, table: str, key: tuple[str, str, str]) -> bool:
        """The owner stopped stating this row. Hand it to the most confident source that still states it (its
        provenance, and its class for a node, replace the row's); delete it when none does. People's decisions are
        never released (they are not owned by a source run)."""
        c = self.conn.execute("SELECT * FROM claims WHERE project = ? AND src = ? AND rel = ? AND dst = ?"
                              " ORDER BY confidence DESC, source LIMIT 1", (project, *key)).fetchone()
        where, args = ("id = ?", [key[0]]) if table == "nodes" else ("src = ? AND rel = ? AND dst = ?", list(key))
        if c is None:
            self.conn.execute(f"DELETE FROM {table} WHERE project = ? AND {where}", [project, *args])
            return False
        cls = ", class = COALESCE(?, class)" if table == "nodes" else ""
        self.conn.execute(
            f"UPDATE {table} SET source = ?, source_file = ?, source_ref = ?, method = ?, confidence = ?, revision = ?,"
            f" status = 'proposed'{cls} WHERE project = ? AND {where}",
            [c["source"], c["source_file"], c["source_ref"], c["method"], c["confidence"], c["revision"],
             *([c["value"]] if table == "nodes" else []), project, *args])
        return True

    # statuses -----------------------------------------------------------------------------------

    def settle(self, project: str) -> dict:
        """Recompute every row's status from its claims (see the module docstring), and record in attrs the sources
        that state it (`sources`, when more than one), those that agree with it (`agree`, when two or more) and the
        other sources' different answers (`conflict`). Never changes a confidence or a person's decision. Returns
        counts by confirmed_by and conflicts."""
        claims = defaultdict(list)
        by_fkey = defaultdict(list)
        for c in self.conn.execute("SELECT * FROM claims WHERE project = ?", (project,)):
            claims[(c["src"], c["rel"], c["dst"])].append(c)
            if c["rel"] in FUNCTIONAL:
                by_fkey[(c["rel"], *self._fkey(c))].append(c)
        counts = defaultdict(int)
        updates = {"nodes": [], "edges": []}
        for table in ("nodes", "edges"):
            key_cols = ("id",) if table == "nodes" else ("src", "rel", "dst")
            for r in self.conn.execute(f"SELECT * FROM {table} WHERE project = ?", (project,)):
                key = (r["id"], "", "") if table == "nodes" else (r["src"], r["rel"], r["dst"])
                cs = claims.get(key, [])
                attrs = json.loads(r["attrs"] or "{}")
                derived_before = {k: attrs.pop(k) for k in DERIVED if k in attrs}
                sources = sorted({c["source"] for c in cs})
                if r["source"] == REVIEW or r["method"] == "human":
                    status = r["status"]
                    by = "human" if status == "confirmed" else None
                    agree, conflict = [], []
                else:
                    if table == "nodes":
                        agree = sorted({c["source"] for c in cs if r["class"] is not None and c["value"] == r["class"]})
                        conflict = [c for c in cs if c["value"] is not None and r["class"] is not None
                                    and c["value"] != r["class"]]
                    else:
                        agree = sources
                        rivals = by_fkey.get((r["rel"], *self._fkey(r)), []) if r["rel"] in FUNCTIONAL else []
                        conflict = [c for c in rivals
                                    if (c["src"], c["dst"]) != (r["src"], r["dst"]) and c["source"] not in sources]
                    held = any(c["status"] == "proposed" for c in cs if c["source"] == r["source"])
                    status, by = self._decide(r["confidence"], len(agree), bool(conflict), held)
                if len(sources) > 1:
                    attrs["sources"] = sources
                if len(agree) > 1:
                    attrs["agree"] = agree
                if conflict:
                    attrs["conflict"] = [{"source": c["source"], **({"class": c["value"]} if table == "nodes" else
                                                                    {"src": c["src"], "dst": c["dst"]}),
                                          "confidence": c["confidence"], "method": c["method"],
                                          "source_file": c["source_file"], "source_ref": c["source_ref"]}
                                         for c in conflict]
                    counts["conflict"] += 1
                counts[by or status] += 1
                derived_after = {k: attrs[k] for k in DERIVED if k in attrs}
                if status != r["status"] or by != r["confirmed_by"] or derived_after != derived_before:
                    updates[table].append((status, by, json.dumps(attrs, default=str), project,
                                           *(r[k] for k in key_cols)))
        with self.conn:
            self.conn.executemany("UPDATE nodes SET status = ?, confirmed_by = ?, attrs = ? WHERE project = ?"
                                  " AND id = ?",
                                  updates["nodes"])
            self.conn.executemany("UPDATE edges SET status = ?, confirmed_by = ?, attrs = ? WHERE project = ? AND"
                                  " src = ? AND rel = ? AND dst = ?", updates["edges"])
        return dict(counts)

    @staticmethod
    def _fkey(r) -> tuple:
        """The end of a functional relation that has one answer (and the medium, for feeds)."""
        end = FUNCTIONAL[r["rel"]]
        if r["rel"] == "feeds":
            medium = r["value"] if "value" in r.keys() else json.loads(r["attrs"] or "{}").get("medium")
            return (r[end], medium) if medium else (r[end], object())  # no medium: never compared
        return (r[end],)

    def _decide(self, confidence: float, n_agree: int, conflict: bool, held: bool) -> tuple[str, str | None]:
        if conflict or held:
            return "proposed", None
        if self.auto.agreement and n_agree >= self.auto.agreement:
            return "confirmed", "agreement"
        if self.auto.threshold is not None and confidence >= self.auto.threshold:
            return "confirmed", "auto"
        return "proposed", None

    # the older writers, now one source each -----------------------------------------------------

    def replace_machine_rows(self, project: str, revision: int, nodes: list[Node], edges: list[Edge],
                             source: str | None = None) -> dict:
        """The mapper's rows for one input (source `mapper:<file name>`). A point a person placed on equipment keeps
        that placement only. With no rows and no source, every mapper source of the project is removed."""
        if source is None and not nodes and not edges:
            out = {}
            for s in [s for s in self.sources(project) if s.startswith("mapper:")]:
                out = self.remove_source(project, s)
            return out
        source = source or f"mapper:{Path(nodes[0].source_file).name if nodes else ''}"
        placed = {r[0] for r in self.conn.execute(
            "SELECT dst FROM edges WHERE project = ? AND rel = 'hasPoint' AND method = 'human'"
            " AND status = 'confirmed'", (project,))}
        edges = [e for e in edges if not (e.rel == "hasPoint" and e.dst in placed)]
        return self.write_source(project, source, revision, nodes, edges)

    def replace_document_edges(self, project: str, source_file: str, revision: int, edges: list[Edge]) -> dict:
        """Every edge one document stated for this project (method document, source `document:<file>`)."""
        edges = [Edge(e.src, e.rel, e.dst, source_file, e.source_ref, "document", e.confidence, e.attrs, e.status)
                 for e in edges]
        return self.write_source(project, f"document:{source_file}", revision, [], edges)

    def delete_project(self, project: str) -> None:
        """Remove a project's graph: rows, claims, aliases and runs (not its notes)."""
        with self.conn:
            for table in ("nodes", "edges", "claims", "aliases", "runs"):
                self.conn.execute(f"DELETE FROM {table} WHERE project = ?", (project,))

    # reading ------------------------------------------------------------------------------------

    def sources(self, project: str) -> list[str]:
        """The sources that state something about this project (not people's decisions)."""
        return [r[0] for r in self.conn.execute(
            "SELECT source FROM claims WHERE project = ? UNION SELECT source FROM nodes WHERE project = ? AND"
            " source NOT IN ('', ?) UNION SELECT source FROM edges WHERE project = ? AND source NOT IN ('', ?)"
            " ORDER BY 1", (project, project, REVIEW, project, REVIEW))]

    def resolve(self, project: str, scheme: str, value: str) -> str | None:
        """The node a source's name for it points to, if exactly one."""
        hits = {r[0] for r in self.conn.execute("SELECT node_id FROM aliases WHERE project = ? AND scheme = ? AND"
                                                " value = ?", (project, scheme, str(value)))}
        return hits.pop() if len(hits) == 1 else None

    def aliases(self, project: str, node_id: str | None = None) -> list[sqlite3.Row]:
        q, args = "SELECT * FROM aliases WHERE project = ?", [project]
        if node_id:
            q, args = q + " AND node_id = ?", args + [node_id]
        return self.conn.execute(q + " ORDER BY node_id, scheme, value", args).fetchall()

    def claims(self, project: str, src: str | None = None) -> list[sqlite3.Row]:
        q, args = "SELECT * FROM claims WHERE project = ?", [project]
        if src:
            q, args = q + " AND src = ?", args + [src]
        return self.conn.execute(q, args).fetchall()

    def agreement(self, project: str, kinds: tuple[str, ...] | None = None, rels: tuple[str, ...] | None = None) -> dict:
        """How far the project's sources agree: live machine facts (nodes of `kinds` and edges of `rels`, all when
        None; not rejected, not people's), those two or more sources state, those confirmed by agreement, and those
        in conflict."""
        out = {"sources": [s for s in self.sources(project)], "facts": 0, "stated_twice": 0, "agreed": 0,
               "conflicts": 0}
        for table, col, only in (("nodes", "kind", kinds), ("edges", "rel", rels)):
            q = f"SELECT attrs, confirmed_by FROM {table} WHERE project = ? AND status != 'rejected' AND source != ?"
            if only is not None:
                q += f" AND {col} IN ({','.join('?' * len(only))})"
            for r in self.conn.execute(q, (project, REVIEW, *(only or ()))):
                a = json.loads(r["attrs"] or "{}")
                out["facts"] += 1
                out["stated_twice"] += len(a.get("sources", [])) > 1
                out["agreed"] += r["confirmed_by"] == "agreement"
                out["conflicts"] += bool(a.get("conflict"))
        return out
    # runs, model calls, chats ---------------------------------------------------------------

    def finish_run(self, project: str, revision: int, seconds: float, summary: dict) -> None:
        with self.conn:
            self.conn.execute("UPDATE runs SET seconds = ?, summary = ? WHERE project = ? AND revision = ?",
                              (seconds, json.dumps(summary), project, revision))

    def log_llm_call(self, project: str, revision: int, provider: str, model: str | None, input: str,
                     output: str | None, cost_usd: float, latency_s: float, *, job: str | None = None,
                     prompt: str | None = None, input_tokens: int = 0, output_tokens: int = 0,
                     cached_tokens: int = 0, ok: bool = True, error: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO llm_calls (project, revision, provider, model, input, output, cost_usd, latency_s, job,"
                " prompt, input_tokens, output_tokens, cached_tokens, ok, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project, revision, provider, model, input, output, cost_usd, latency_s, job, prompt, input_tokens,
                 output_tokens, cached_tokens, int(ok), error),
            )
        return cur.lastrowid

    def save_chat(self, chat_id: str, title: str, log: list, api: list, project: str = "", person: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO agent_chats (id, project, person, title, log, api) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET project = excluded.project, person = excluded.person,"
                " title = excluded.title, log = excluded.log, api = excluded.api, updated_at = datetime('now')",
                (chat_id, project or "", person or "", title, json.dumps(log, default=str), json.dumps(api, default=str)))

    def chats(self, limit: int = 30) -> list[dict]:
        """The latest conversations, newest first: id, title, project, person, updated_at, turns."""
        rows = self.conn.execute("SELECT id, title, project, person, updated_at, json_array_length(log) AS n"
                                 " FROM agent_chats ORDER BY updated_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def chat(self, chat_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM agent_chats WHERE id = ?", (chat_id,)).fetchone()
        return None if r is None else {**dict(r), "log": json.loads(r["log"]), "api": json.loads(r["api"])}

    def delete_chat(self, chat_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM agent_chats WHERE id = ?", (chat_id,))

    def nodes(self, project: str, kind: str | None = None) -> list[sqlite3.Row]:
        q, args = "SELECT * FROM nodes WHERE project = ?", [project]
        if kind:
            q, args = q + " AND kind = ?", args + [kind]
        return self.conn.execute(q, args).fetchall()

    def edges(self, project: str, rel: str | None = None) -> list[sqlite3.Row]:
        q, args = "SELECT * FROM edges WHERE project = ?", [project]
        if rel:
            q, args = q + " AND rel = ?", args + [rel]
        return self.conn.execute(q, args).fetchall()
