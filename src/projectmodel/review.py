"""Human review actions on a mapped project. The review screen calls these; so can tests.

`queue` is what waits for a person: the proposed nodes and edges, conflicts between sources first, then by
confidence. Confirmed rows (by a person, or by the auto-accept rule) are not in it. A row two or more documents agree
on stays in it, with the note `agree` (which sources) and `agree_confidence` (their combined confidence): agreement
is the expert's call (plan §8.5). `accept_agreed` accepts those rows in one go.

Every action turns the row into method=human and source=review (confirmed_by=human), keeps what the machine proposed
under attrs.review.previous (class, method, confidence, status, source), and records who decided and when. Rows with
source review survive every source's rerun.

Each decision also keeps, under attrs.review.features, what a rule could key on (the learning loop, curator.py): the
name and its words, the folder, the equipment it sits on with its class and template, the template slot role the
machine's class filled, the description (setup points) and the source that proposed it. A move keeps the same on the
new hasPoint edge, with the equipment it left.

  accept        - the proposed class is right                   -> status confirmed
  fix_class     - replace the class with a knowledge-model one   -> status confirmed, confidence 1
  reject        - the proposed class is wrong, no replacement     -> status rejected (scored as no class)
  move_points   - put points on another equipment                 -> human hasPoint edge, old edge rejected
  accept_edges / reject_edges - a link (feeds, hasPoint, serves...) is right / wrong
  accept_agreed - every proposed row two or more documents agree on (no conflict), at or above a combined confidence
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .db.store import REVIEW, Store
from .knowledge_model import KnowledgeModel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


WORD = re.compile(r"[A-Za-z%]+(?:/[A-Za-z]+)?")  # "Clg Dmpr Pos. %" -> clg dmpr pos %; "S/S" stays one word


def name_words(name: str) -> list[str]:
    """The lowercase words of a name, without numbers: what a convention's pattern can key on."""
    return [w.lower() for w in WORD.findall(name or "")]


def features(store: Store, project: str, row, km: KnowledgeModel | None = None) -> dict:
    """What a rule could key on for this node, as the machine saw it (see the module docstring)."""
    attrs = json.loads(row["attrs"] or "{}")
    out = {"name": row["label"], "words": name_words(row["label"]), "folder": attrs.get("path") or "",
           "source": row["source"], "kind": row["kind"]}
    if attrs.get("description"):
        out["description"] = attrs["description"]
    if row["kind"] == "point":
        e = store.conn.execute(
            "SELECT n.id, n.label, n.class, n.attrs FROM edges e JOIN nodes n ON n.project = e.project AND n.id = e.src"
            " WHERE e.project = ? AND e.rel = 'hasPoint' AND e.dst = ? AND e.status != 'rejected'"
            " ORDER BY e.method = 'human' DESC LIMIT 1", (project, row["id"])).fetchone()
        if e:
            tid = json.loads(e["attrs"] or "{}").get("template")
            out |= {"equipment": e["id"], "equipment_label": e["label"], "equipment_class": e["class"],
                    "template": tid}
            t = km.templates.get(tid) if km and tid else None
            prev = (attrs.get("review", {}).get("previous") or {}).get("class", row["class"])
            if t and prev:
                out["role"] = next((s.role for s in t.slots if prev in s.classes), None) or next(
                    (s.role for s in t.slots if any(km.is_a(prev, c) or km.is_a(c, prev) for c in s.classes)), None)
    return out


def _update_nodes(store: Store, project: str, ids: list[str], reviewer: str, action: str,
                  cls: str | None = None, keep_class: bool = True, km: KnowledgeModel | None = None) -> int:
    rows = store.conn.execute(
        f"SELECT * FROM nodes WHERE project = ? AND id IN ({','.join('?' * len(ids))})", [project, *ids]
    ).fetchall() if ids else []
    with store.conn:
        for r in rows:
            attrs = json.loads(r["attrs"])
            before = attrs.get("review", {})
            previous = before.get("previous") or {
                "class": r["class"], "method": r["method"], "confidence": r["confidence"], "status": r["status"],
                "source": r["source"]}
            feats = before.get("features") or features(store, project, r, km)
            attrs["review"] = {"action": action, "by": reviewer, "at": _now(), "previous": previous,
                               "features": feats}
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
    return _update_nodes(store, project, ids, reviewer, "fix", cls=cls, keep_class=False, km=km)


def move_points(store: Store, project: str, point_ids: list[str], equip_id: str, reviewer: str) -> int:
    if not store.conn.execute("SELECT 1 FROM nodes WHERE project = ? AND id = ? AND kind = 'equipment'",
                              (project, equip_id)).fetchone():
        raise ValueError(f"{equip_id} is not an equipment node in {project}")
    plain = json.dumps({"review": {"action": "move", "by": reviewer, "at": _now()}})
    with store.conn:
        for pid in point_ids:
            old = store.conn.execute("SELECT * FROM edges WHERE project = ? AND rel = 'hasPoint' AND dst = ? "
                                     "AND status != 'rejected'", (project, pid)).fetchall()
            point = store.conn.execute("SELECT * FROM nodes WHERE project = ? AND id = ?", (project, pid)).fetchone()
            attrs = plain if point is None else json.dumps({"review": {
                "action": "move", "by": reviewer, "at": _now(), "features": features(store, project, point),
                "previous": {"equipment": [e["src"] for e in old if e["src"] != equip_id],
                             "method": old[0]["method"] if old else None,
                             "source": old[0]["source"] if old else None},
                "equipment": equip_id}})
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
                    "source_file": r["source_file"], "source_ref": r["source_ref"], "conflict": a.get("conflict", []),
                    "agree": a.get("agree", []), "agree_confidence": a.get("agree_confidence")})
    if not kind:
        for r in store.conn.execute("SELECT * FROM edges WHERE project = ? AND status = 'proposed'", (project,)):
            a = json.loads(r["attrs"] or "{}")
            out.append({"target": "edge", "id": f"{r['src']}|{r['rel']}|{r['dst']}", "kind": "edge",
                        "label": f"{r['src']} {r['rel']} {r['dst']}", "rel": r["rel"], "src": r["src"],
                        "dst": r["dst"], "confidence": r["confidence"], "method": r["method"], "source": r["source"],
                        "source_file": r["source_file"], "source_ref": r["source_ref"],
                        "conflict": a.get("conflict", []), "agree": a.get("agree", []),
                        "agree_confidence": a.get("agree_confidence")})
    return sorted(out, key=lambda x: (not x["conflict"], x["confidence"], x["id"]))


def agreed(store: Store, project: str, min_confidence: float = 0.0) -> list[dict]:
    """The queue's rows two or more documents agree on, with no conflict, at or above `min_confidence` combined."""
    return [i for i in queue(store, project) if len(i["agree"]) > 1 and not i["conflict"]
            and (i["agree_confidence"] or 0) >= min_confidence]


def accept_agreed(store: Store, project: str, reviewer: str, min_confidence: float = 0.0) -> int:
    """The expert accepts, in one go, every proposed fact two or more documents agree on (see `agreed`). Each row
    becomes the reviewer's decision (method human), with the sources that agreed kept in attrs.review.previous."""
    items = agreed(store, project, min_confidence)
    n = _update_nodes(store, project, [i["id"] for i in items if i["target"] == "node"], reviewer, "accept")
    return n + _update_edges(store, project, [(i["src"], i["rel"], i["dst"]) for i in items if i["target"] == "edge"],
                             reviewer, "accept")
