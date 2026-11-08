"""Notes: free-text tribal knowledge attached to equipment, points, links or a whole project.

Notes are context, never graph facts: they don't change classes or scores, and a mapper run never
touches them. They are keyed by node id (or "src|rel|dst" for an edge), which survive re-runs; if the
target disappears from the graph the note is reported as orphaned, never dropped. No hard delete:
editing changes the body, and a note leaves the active list by being resolved or superseded.
"""

from __future__ import annotations

from .db.store import Store

TARGET_KINDS = ("node", "edge", "project")
TOPICS = ("naming", "history", "operations", "maintenance", "other")
SOURCES = ("manual", "review", "interview", "document")  # interview, document: reserved for later phases
NOTE_STATUSES = ("active", "resolved", "superseded")


def edge_id(src: str, rel: str, dst: str) -> str:
    return f"{src}|{rel}|{dst}"


def _check(name: str, value: str, allowed: tuple) -> None:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}, not {value!r}")


def add_note(store: Store, project: str, target_kind: str, target_id: str, target_label: str, topic: str,
             body: str, author: str, source: str = "manual", source_ref: str = "") -> int:
    _check("target_kind", target_kind, TARGET_KINDS)
    _check("topic", topic, TOPICS)
    _check("source", source, SOURCES)
    if target_kind == "project":
        target_id = ""
    if not body.strip():
        raise ValueError("a note needs a body")
    if not author.strip():
        raise ValueError("a note needs an author")
    with store.conn:
        cur = store.conn.execute(
            "INSERT INTO notes (project, target_kind, target_id, target_label, topic, body, author, source,"
            " source_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project, target_kind, target_id, target_label, topic, body.strip(), author.strip(), source, source_ref))
    return cur.lastrowid


def update_note(store: Store, note_id: int, body: str, topic: str | None = None) -> None:
    if not body.strip():
        raise ValueError("a note needs a body")
    if topic is not None:
        _check("topic", topic, TOPICS)
    with store.conn:
        store.conn.execute("UPDATE notes SET body = ?, topic = COALESCE(?, topic), updated_at = datetime('now')"
                           " WHERE id = ?", (body.strip(), topic, note_id))


def set_status(store: Store, note_id: int, status: str) -> None:
    _check("status", status, NOTE_STATUSES)
    with store.conn:
        store.conn.execute("UPDATE notes SET status = ?, updated_at = datetime('now') WHERE id = ?",
                           (status, note_id))


def get_note(store: Store, note_id: int) -> dict | None:
    r = store.conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(r) if r else None


def notes_for(store: Store, project: str, target_kind: str, target_id: str,
              status: str | None = None) -> list[dict]:
    """Notes on one target, oldest first. `status=None` returns every status."""
    q = "SELECT * FROM notes WHERE project = ? AND target_kind = ? AND target_id = ?"
    args = [project, target_kind, "" if target_kind == "project" else target_id]
    if status:
        q, args = q + " AND status = ?", args + [status]
    return [dict(r) for r in store.conn.execute(q + " ORDER BY id", args)]


def notes_by_project(store: Store, project: str, topic: str | None = None,
                     status: str | None = "active") -> list[dict]:
    q, args = "SELECT * FROM notes WHERE project = ?", [project]
    if topic:
        q, args = q + " AND topic = ?", args + [topic]
    if status:
        q, args = q + " AND status = ?", args + [status]
    return [dict(r) for r in store.conn.execute(q + " ORDER BY id", args)]


def orphaned(store: Store, project: str) -> list[dict]:
    """Notes whose node or edge is no longer in the project's graph (any status, so nothing gets lost)."""
    node_ids = {r[0] for r in store.conn.execute("SELECT id FROM nodes WHERE project = ?", (project,))}
    edge_ids = {edge_id(*r) for r in store.conn.execute("SELECT src, rel, dst FROM edges WHERE project = ?",
                                                        (project,))}
    out = []
    for n in notes_by_project(store, project, status=None):
        if (n["target_kind"] == "node" and n["target_id"] not in node_ids) or \
                (n["target_kind"] == "edge" and n["target_id"] not in edge_ids):
            out.append(n)
    return out


def active_counts(store: Store, project: str) -> dict[tuple[str, str], int]:
    """(target_kind, target_id) -> number of active notes."""
    return {(r[0], r[1]): r[2] for r in store.conn.execute(
        "SELECT target_kind, target_id, COUNT(*) FROM notes WHERE project = ? AND status = 'active'"
        " GROUP BY target_kind, target_id", (project,))}
