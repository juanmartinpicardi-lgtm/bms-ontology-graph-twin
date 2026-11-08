"""Human review actions on a mapped project. The review screen calls these; so can tests.

Every action turns the row into method=human, keeps what the machine proposed under
attrs.review.previous, and records who decided and when. Human rows survive mapper reruns.

  accept        - the proposed class is right                   -> status confirmed
  fix_class     - replace the class with a knowledge-model one   -> status confirmed, confidence 1
  reject        - the proposed class is wrong, no replacement     -> status rejected (scored as no class)
  move_points   - put points on another equipment                 -> human hasPoint edge, old edge rejected
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .db.store import Store
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
                "source_file = 'review', source_ref = ? WHERE project = ? AND id = ?",
                (new_cls, status, confidence, json.dumps(attrs), f"{action} by {reviewer}", project, r["id"]),
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
    for kind in kinds:
        if km.classes[cls].kind != kind:
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
                store.conn.execute("UPDATE edges SET method = 'human', status = 'rejected', attrs = ? "
                                   "WHERE project = ? AND src = ? AND rel = 'hasPoint' AND dst = ?",
                                   (attrs, project, e["src"], pid))
            store.conn.execute(
                "INSERT INTO edges (project, src, rel, dst, source_file, source_ref, method, confidence, status,"
                " revision, attrs) VALUES (?, ?, 'hasPoint', ?, 'review', ?, 'human', 1.0, 'confirmed',"
                " (SELECT COALESCE(MAX(revision), 0) FROM runs WHERE project = ?), ?)"
                " ON CONFLICT (project, src, rel, dst) DO UPDATE SET method = 'human', status = 'confirmed',"
                " confidence = 1.0, attrs = excluded.attrs",
                (project, equip_id, pid, f"move by {reviewer}", project, attrs),
            )
    return len(point_ids)
