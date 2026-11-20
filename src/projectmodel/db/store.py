"""SQLite store for the knowledge graph: nodes and edges, every one with provenance.

Every node and edge stores: source_file, source_ref (row number or folder path), method
(parsed | rule | template | llm | human | document), confidence (0-1), status (proposed | confirmed | rejected),
revision. A mapper run replaces the project's machine-made rows and keeps human ones and document ones
(behaviour edges read from a sequence of operation). The mapper's best guess is accepted as is (status
confirmed); method and confidence still say how it was decided.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

METHODS = ("parsed", "rule", "template", "llm", "human", "document")
KEPT = ("human", "document")  # a mapper run never deletes these: people decided them, or a document states them
STATUSES = ("proposed", "confirmed", "rejected")
KINDS = ("point", "equipment", "location")  # location: a floor or room of a building added from its documents

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
    PRIMARY KEY (project, src, rel, dst)
);
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


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate_methods()
        self.conn.executescript(SCHEMA)
        self._migrate_llm_calls()

    LLM_CALL_COLUMNS = {"job": "TEXT", "prompt": "TEXT", "input_tokens": "INTEGER NOT NULL DEFAULT 0",
                        "output_tokens": "INTEGER NOT NULL DEFAULT 0", "cached_tokens": "INTEGER NOT NULL DEFAULT 0",
                        "ok": "INTEGER NOT NULL DEFAULT 1", "error": "TEXT"}

    def _migrate_llm_calls(self) -> None:
        """Older databases have llm_calls without the job, prompt, token and outcome columns: add them."""
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(llm_calls)")}
        with self.conn:
            for col, decl in self.LLM_CALL_COLUMNS.items():
                if col not in have:
                    self.conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {col} {decl}")

    def _migrate_methods(self) -> None:
        """Older databases check method (or a node's kind) against a shorter list; rebuild those tables with the
        current checks."""
        for table in ("nodes", "edges"):
            row = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not row or all(f"'{m}'" in row[0] for m in METHODS + (KINDS if table == "nodes" else ())):
                continue
            with self.conn:
                self.conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
                self.conn.executescript(SCHEMA)
                self.conn.execute(f"INSERT INTO {table} SELECT * FROM {table}_old")
                self.conn.execute(f"DROP TABLE {table}_old")

    def start_run(self, project: str, source_file: str) -> int:
        cur = self.conn.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM runs WHERE project = ?", (project,))
        revision = cur.fetchone()[0]
        self.conn.execute("INSERT INTO runs (project, revision, source_file) VALUES (?, ?, ?)",
                          (project, revision, source_file))
        return revision

    def replace_machine_rows(self, project: str, revision: int, nodes: list[Node], edges: list[Edge]) -> None:
        """Drop the project's machine rows (not human or document ones), then write this run's nodes and edges.
        Human rows win: a machine row never overwrites a node or edge a person already decided."""
        with self.conn:
            self.conn.execute(f"DELETE FROM nodes WHERE project = ? AND method NOT IN {KEPT}", (project,))
            self.conn.execute(f"DELETE FROM edges WHERE project = ? AND method NOT IN {KEPT}", (project,))
            # A point a person placed on equipment keeps that placement only.
            placed = {r[0] for r in self.conn.execute(
                "SELECT dst FROM edges WHERE project = ? AND rel = 'hasPoint' AND method = 'human'"
                " AND status = 'confirmed'", (project,))}
            edges = [e for e in edges if not (e.rel == "hasPoint" and e.dst in placed)]
            self.conn.executemany(
                "INSERT OR IGNORE INTO nodes (project, id, kind, label, class, source_file, source_ref, method,"
                " confidence, status, revision, attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)",
                [(project, n.id, n.kind, n.label, n.cls, n.source_file, n.source_ref, n.method,
                  round(n.confidence, 4), revision, json.dumps(n.attrs)) for n in nodes],
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO edges (project, src, rel, dst, source_file, source_ref, method,"
                " confidence, status, revision, attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)",
                [(project, e.src, e.rel, e.dst, e.source_file, e.source_ref, e.method,
                  round(e.confidence, 4), revision, json.dumps(e.attrs)) for e in edges],
            )

    def replace_document_edges(self, project: str, source_file: str, revision: int, edges: list[Edge]) -> None:
        """Replace every edge one document stated for this project (method document). Never touches a row
        that already holds the same src, rel and dst from another method."""
        with self.conn:
            self.conn.execute("DELETE FROM edges WHERE project = ? AND method = 'document' AND source_file = ?",
                              (project, source_file))
            self.conn.executemany(
                "INSERT OR IGNORE INTO edges (project, src, rel, dst, source_file, source_ref, method,"
                " confidence, status, revision, attrs) VALUES (?, ?, ?, ?, ?, ?, 'document', ?, 'confirmed', ?, ?)",
                [(project, e.src, e.rel, e.dst, source_file, e.source_ref, round(e.confidence, 4), revision,
                  json.dumps(e.attrs)) for e in edges],
            )

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
