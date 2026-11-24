"""Human review actions on a mapped project. The review screen calls these; so can tests.

`queue` is what waits for a person: the proposed nodes and edges, conflicts between sources first, then by
confidence. Confirmed rows (by a person, by two agreeing sources, or by the auto-accept rule) are not in it.

Every action turns the row into method=human and source=review (confirmed_by=human), keeps what the machine proposed
under attrs.review.previous, and records who decided and when. Rows with source review survive every source's rerun.

  accept        - the proposed class is right                   -> status confirmed
  fix_class     - replace the class with a knowledge-model one   -> status confirmed, confidence 1
  reject        - the proposed class is wrong, no replacement     -> status rejected (scored as no class)
  move_points   - put points on another equipment                 -> human hasPoint edge, old edge rejected
  accept_edges / reject_edges - a link (feeds, hasPoint, serves...) is right / wrong
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .db.store import REVIEW, Store
from .knowledge_model import KnowledgeModel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _update_nodes(store: Store, project: str, ids: list[str], reviewer: str, action: str,
                  cls: str | None = None, keep_class: bool = True) -> int:
    rows = store.conn.execute(
        f"SELECT * FROM nodes WHERE project = ? AND id IN ({','.join('?' * len(ids))})", [project, *ids]
    ).fetchall() if ids else []
    with store.conn:
        for r in rows:
            attrs = json.loads(r["attrs"])
            previous = attrs.get("review", {}).get("previous") or {
                "class": r["class"], "method": r["method"], "confidence": r["confidence"], "status": r["status"]}
            attrs["review"] = {"action": action, "by": reviewer, "at": _now(), "previous": previous}
            new_cls = r["class"] if keep_class else cls
            status = "rejected" if action == "reject" else "confirmed"
            confidence = 1.0 if action == "fix" else r["confidence"]
            store.conn.execute(
                "UPDATE nodes SET class = ?, method = 'human', status = ?, confidence = ?, attrs = ?, "
                "source_file = 'review', source_ref = ?, source = ?, confirmed_by = ? WHERE project = ? AND id = ?",
                (new_cls, status, confidence, json.dumps(attrs), f"{action} by {reviewer}", REVIEW,
                 "human" if status == "confirmed" else None, project, r["id"]),
            )
    return len(rows)


def accept(store: Store, project: str, ids: list[str], reviewer: str) -> int:
    return _update_nodes(store, project, ids, reviewer, "accept")


def reject(store: Store, project: str, ids: list[str], reviewer: str) -> int:
    return _update_nodes(store, project, ids, reviewer, "reject")


def fix_class(store: Store, km: KnowledgeModel, project: str, ids: list[str], cls: str, reviewer: str) -> int:
    kinds = {r["kind"] for r in store.conn.execute(
        f"SELECT kind FROM nodes WHERE project = ? AND id IN ({','.join('?' * len(ids))})", [project, *ids])} if ids else set()
    if cls not in km.classes:
        raise ValueError(f"{cls} is not a class in the knowledge model")
    allowed = {"point": {"point"}, "equipment": {"equipment", "system"}}  # an equipment node may be a plant/loop
    for kind in kinds:
        if km.classes[cls].kind not in allowed[kind]:
            raise ValueError(f"{cls} is a {km.classes[cls].kind} class, cannot be given to a {kind}")
    return _update_nodes(store, project, ids, reviewer, "fix", cls=cls, keep_class=False)


def move_points(store: Store, project: str, point_ids: list[str], equip_id: str, reviewer: str) -> int:
    if not store.conn.execute("SELECT 1 FROM nodes WHERE project = ? AND id = ? AND kind = 'equipment'",
                              (project, equip_id)).fetchone():
        raise ValueError(f"{equip_id} is not an equipment node in {project}")
    attrs = json.dumps({"review": {"action": "move", "by": reviewer, "at": _now()}})
    with store.conn:
        for pid in point_ids:
            old = store.conn.execute("SELECT * FROM edges WHERE project = ? AND rel = 'hasPoint' AND dst = ? "
                                     "AND status != 'rejected'", (project, pid)).fetchall()
            for e in old:
                if e["src"] == equip_id:
                    continue
                store.conn.execute("UPDATE edges SET method = 'human', status = 'rejected', attrs = ?, source = ?,"
                                   " confirmed_by = NULL WHERE project = ? AND src = ? AND rel = 'hasPoint' AND dst = ?",
                                   (attrs, REVIEW, project, e["src"], pid))
            store.conn.execute(
                "INSERT INTO edges (project, src, rel, dst, source_file, source_ref, method, confidence, status,"
                " revision, attrs, source, confirmed_by) VALUES (?, ?, 'hasPoint', ?, 'review', ?, 'human', 1.0,"
                " 'confirmed', (SELECT COALESCE(MAX(revision), 0) FROM runs WHERE project = ?), ?, ?, 'human')"
                " ON CONFLICT (project, src, rel, dst) DO UPDATE SET method = 'human', status = 'confirmed',"
                " confidence = 1.0, attrs = excluded.attrs, source = excluded.source, confirmed_by = 'human',"
                " source_file = 'review', source_ref = excluded.source_ref",
                (project, equip_id, pid, f"move by {reviewer}", project, attrs, REVIEW),
            )
    return len(point_ids)


def _update_edges(store: Store, project: str, keys: list[tuple[str, str, str]], reviewer: str, action: str) -> int:
    n = 0
    with store.conn:
        for src, rel, dst in keys:
            r = store.conn.execute("SELECT * FROM edges WHERE project = ? AND src = ? AND rel = ? AND dst = ?",
                                   (project, src, rel, dst)).fetchone()
            if r is None:
                continue
            attrs = json.loads(r["attrs"])
            previous = attrs.get("review", {}).get("previous") or {
                "method": r["method"], "confidence": r["confidence"], "status": r["status"], "source": r["source"]}
            attrs["review"] = {"action": action, "by": reviewer, "at": _now(), "previous": previous}
            status = "rejected" if action == "reject" else "confirmed"
            store.conn.execute(
                "UPDATE edges SET method = 'human', status = ?, attrs = ?, source_file = 'review', source_ref = ?,"
                " source = ?, confirmed_by = ? WHERE project = ? AND src = ? AND rel = ? AND dst = ?",
                (status, json.dumps(attrs), f"{action} by {reviewer}", REVIEW,
                 "human" if status == "confirmed" else None, project, src, rel, dst))
            n += 1
    return n


def accept_edges(store: Store, project: str, keys: list[tuple[str, str, str]], reviewer: str) -> int:
    """(src, rel, dst) links a person confirms."""
    return _update_edges(store, project, keys, reviewer, "accept")


def reject_edges(store: Store, project: str, keys: list[tuple[str, str, str]], reviewer: str) -> int:
    """(src, rel, dst) links a person rejects: they leave every view and stay rejected on reruns."""
    return _update_edges(store, project, keys, reviewer, "reject")


def queue(store: Store, project: str, kind: str | None = None) -> list[dict]:
    """What waits for a person: every proposed node (of `kind`, if given) and, unless a kind is given, every proposed
    edge. Conflicts between sources come first, then the least confident. Each item: target (node | edge), id (a node
    id, or src|rel|dst), label, class or rel, confidence, method, source, conflict (other sources' answers)."""
    out = []
    q, args = "SELECT * FROM nodes WHERE project = ? AND status = 'proposed'", [project]
    if kind:
        q, args = q + " AND kind = ?", args + [kind]
    for r in store.conn.execute(q, args):
        a = json.loads(r["attrs"] or "{}")
        out.append({"target": "node", "id": r["id"], "kind": r["kind"], "label": r["label"], "class": r["class"],
                    "confidence": r["confidence"], "method": r["method"], "source": r["source"],
                    "source_file": r["source_file"], "source_ref": r["source_ref"], "conflict": a.get("conflict", [])})
    if not kind:
        for r in store.conn.execute("SELECT * FROM edges WHERE project = ? AND status = 'proposed'", (project,)):
            a = json.loads(r["attrs"] or "{}")
            out.append({"target": "edge", "id": f"{r['src']}|{r['rel']}|{r['dst']}", "kind": "edge",
                        "label": f"{r['src']} {r['rel']} {r['dst']}", "rel": r["rel"], "src": r["src"],
                        "dst": r["dst"], "confidence": r["confidence"], "method": r["method"], "source": r["source"],
                        "source_file": r["source_file"], "source_ref": r["source_ref"],
                        "conflict": a.get("conflict", [])})
    return sorted(out, key=lambda x: (not x["conflict"], x["confidence"], x["id"]))
