"""SQLite store for the knowledge graph: nodes and edges, every one with provenance.

Every node and edge stores: source_file, source_ref (row number or folder path), method
(parsed | rule | template | llm | human), confidence (0-1), status (proposed | confirmed | rejected),
revision. A mapper run replaces the project's machine-made rows and keeps human ones.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

METHODS = ("parsed", "rule", "template", "llm", "human")
STATUSES = ("proposed", "confirmed", "rejected")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS nodes (
    project     TEXT NOT NULL,
    id          TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('point', 'equipment')),
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
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
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
        self.conn.executescript(SCHEMA)

    def start_run(self, project: str, source_file: str) -> int:
        cur = self.conn.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM runs WHERE project = ?", (project,))
        revision = cur.fetchone()[0]
        self.conn.execute("INSERT INTO runs (project, revision, source_file) VALUES (?, ?, ?)",
                          (project, revision, source_file))
        return revision

    def replace_machine_rows(self, project: str, revision: int, nodes: list[Node], edges: list[Edge]) -> None:
        """Drop the project's non-human rows, then write this run's nodes and edges.
        Human rows win: a machine row never overwrites a node or edge a person already decided."""
        with self.conn:
            self.conn.execute("DELETE FROM nodes WHERE project = ? AND method != 'human'", (project,))
            self.conn.execute("DELETE FROM edges WHERE project = ? AND method != 'human'", (project,))
            self.conn.executemany(
                "INSERT OR IGNORE INTO nodes (project, id, kind, label, class, source_file, source_ref, method,"
                " confidence, revision, attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(project, n.id, n.kind, n.label, n.cls, n.source_file, n.source_ref, n.method,
                  round(n.confidence, 4), revision, json.dumps(n.attrs)) for n in nodes],
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO edges (project, src, rel, dst, source_file, source_ref, method,"
                " confidence, revision, attrs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(project, e.src, e.rel, e.dst, e.source_file, e.source_ref, e.method,
                  round(e.confidence, 4), revision, json.dumps(e.attrs)) for e in edges],
            )

    def finish_run(self, project: str, revision: int, seconds: float, summary: dict) -> None:
        with self.conn:
            self.conn.execute("UPDATE runs SET seconds = ?, summary = ? WHERE project = ? AND revision = ?",
                              (seconds, json.dumps(summary), project, revision))

    def log_llm_call(self, project: str, revision: int, provider: str, model: str | None, input: str,
                     output: str | None, cost_usd: float, latency_s: float) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO llm_calls (project, revision, provider, model, input, output, cost_usd, latency_s)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project, revision, provider, model, input, output, cost_usd, latency_s),
            )

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
