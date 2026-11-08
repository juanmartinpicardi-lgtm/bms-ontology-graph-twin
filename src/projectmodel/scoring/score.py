"""Score a mapped project in the store against its ground truth.

H1  grouping: share of points (that have true equipment) placed on the right equipment. Predicted
    equipment are matched one-to-one to true equipment by largest point overlap, so splitting or
    merging equipment costs points. Ungrouped points count as wrong.
H2  classification: share of points (that have a ground-truth class) with exactly the right class,
    overall and among auto-accepted points. "compatible" also counts a parent/child of the true class.
Review: share of points not auto-accepted (confidence below the threshold, or no class) and not
    already decided by a human.
Cost and time per 1,000 points come from the latest run and its logged LLM calls.
Also reported: equipment class accuracy, feeds/hasPart precision and recall, a confidence
calibration table, and H2 split by where the point name came from (BMS name vs dis fallback).
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..db.store import Store
from ..knowledge_model import KnowledgeModel

ROOT = Path(__file__).resolve().parents[3]
GT_DIR = ROOT / "data/ground_truth"
DEFAULT_ACCEPT = 0.8  # provisional; chosen on Alpha (dev) only


@dataclass
class GroundTruth:
    points: dict[str, dict]  # point_id -> row
    equipment: dict[str, dict]
    relations: set[tuple[str, str, str]]  # (src, rel, dst)
    key: dict[str, dict]  # blind_id -> {point_id, name_source}


def load_ground_truth(site: str, gt_dir: Path = GT_DIR) -> GroundTruth:
    d = gt_dir / site

    def read(name):
        with (d / name).open() as f:
            return list(csv.DictReader(f))

    return GroundTruth(
        points={r["point_id"]: r for r in read("points.csv")},
        equipment={r["equip_id"]: r for r in read("equipment.csv")},
        relations={(r["src"], r["rel"], r["dst"]) for r in read("equip_relations.csv")},
        key={r["blind_id"]: r for r in read("blind_key.csv")},
    )


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def match_equipment(pred_groups: dict[str, list[str]], true_equip_of: dict[str, str]) -> dict[str, str]:
    """One-to-one match predicted equipment -> true equipment, greedily by point overlap."""
    overlaps = []
    for g, pts in pred_groups.items():
        for t, n in Counter(true_equip_of[p] for p in pts if true_equip_of.get(p)).items():
            overlaps.append((n, g, t))
    matched, used = {}, set()
    for n, g, t in sorted(overlaps, key=lambda x: (-x[0], x[1], x[2])):
        if g not in matched and t not in used:
            matched[g] = t
            used.add(t)
    return matched


def score_project(store: Store, project: str, gt: GroundTruth, km: KnowledgeModel, accept: float) -> dict:
    # A rejected class counts as no class.
    nodes = [dict(n) | ({"class": None} if n["status"] == "rejected" else {}) for n in store.nodes(project)]
    if not nodes:
        raise ValueError(f"project {project!r} has no nodes; run the mapper first")
    points = [n for n in nodes if n["kind"] == "point"]
    equip = {n["id"]: n for n in nodes if n["kind"] == "equipment"}
    point_of = {n["id"]: gt.key[json.loads(n["attrs"])["source_id"]]["point_id"] for n in points}
    name_source = {n["id"]: gt.key[json.loads(n["attrs"])["source_id"]]["name_source"] for n in points}

    # H1 grouping
    group_of = {e["dst"]: e["src"] for e in store.edges(project, "hasPoint") if e["status"] != "rejected"}
    true_equip_of = {pid: gt.points[point_of[pid]]["equip_id"] for pid in point_of}
    pred_groups = defaultdict(list)
    for pid, gid in group_of.items():
        pred_groups[gid].append(pid)
    matched = match_equipment(pred_groups, true_equip_of)
    with_equip = [pid for pid in point_of if true_equip_of[pid]]
    grouped_right = sum(1 for pid in with_equip if pid in group_of and matched.get(group_of[pid]) == true_equip_of[pid])

    # H2 classification and review
    def accepted(n) -> bool:
        if n["status"] == "rejected":
            return False
        return n["method"] == "human" or n["status"] == "confirmed" or (bool(n["class"]) and n["confidence"] >= accept)

    def compatible(pred: str | None, true: str) -> bool:
        if not pred or pred not in km.classes or true not in km.classes:
            return pred == true
        return pred != "Point" and true != "Point" and (km.is_a(pred, true) or km.is_a(true, pred))

    labelled = [n for n in points if gt.points[point_of[n["id"]]]["brick_class"]]
    true_cls = {n["id"]: gt.points[point_of[n["id"]]]["brick_class"] for n in labelled}
    exact = [n for n in labelled if n["class"] == true_cls[n["id"]]]
    compat = [n for n in labelled if compatible(n["class"], true_cls[n["id"]])]
    auto = [n for n in labelled if accepted(n)]
    auto_exact = [n for n in auto if n["class"] == true_cls[n["id"]]]
    to_review = [n for n in points if not accepted(n)]
    unreachable = sum(1 for n in labelled if true_cls[n["id"]] not in km.classes)

    by_source = {}
    for src in ("source", "dis"):
        sub = [n for n in labelled if name_source[n["id"]] == src]
        by_source[src] = {"n": len(sub), "exact_pct": _pct(sum(1 for n in sub if n["class"] == true_cls[n["id"]]), len(sub))}

    calibration = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.7, 0.8, 0.9):
        hi = {0.0: 0.2, 0.2: 0.4, 0.4: 0.6, 0.6: 0.7, 0.7: 0.8, 0.8: 0.9, 0.9: 1.01}[lo]
        sub = [n for n in labelled if lo <= n["confidence"] < hi]
        calibration.append({"conf": f"{lo:.1f}-{min(hi, 1.0):.1f}", "n": len(sub),
                            "exact_pct": _pct(sum(1 for n in sub if n["class"] == true_cls[n["id"]]), len(sub))})

    # Equipment class (for matched equipment with a ground-truth class)
    eq_pairs = [(equip[g]["class"], gt.equipment[t]["brick_class"]) for g, t in matched.items()
                if gt.equipment[t]["brick_class"] and g in equip]
    eq_exact = sum(1 for p, t in eq_pairs if p == t)

    # Relations, translated to true equipment ids through the match
    def rel_scores(rel: str) -> dict:
        pred = {(matched.get(e["src"]), rel, matched.get(e["dst"])) for e in store.edges(project, rel)
                if e["status"] != "rejected"}
        pred_ok = {p for p in pred if p[0] and p[2]}
        true = {r for r in gt.relations if r[1] == rel}
        hit = len(pred_ok & true)
        return {"predicted": len(pred), "true": len(true), "precision_pct": _pct(hit, len(pred)),
                "recall_pct": _pct(hit, len(true))}

    run = store.conn.execute("SELECT revision, seconds FROM runs WHERE project = ? ORDER BY revision DESC LIMIT 1",
                             (project,)).fetchone()
    cost = store.conn.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd), 0), COALESCE(SUM(latency_s), 0)"
                              " FROM llm_calls WHERE project = ? AND revision = ?", (project, run["revision"])).fetchone()
    per_k = 1000 / max(1, len(points))

    return {
        "project": project,
        "points": len(points),
        "accept_threshold": accept,
        "H1_grouped_right_pct": _pct(grouped_right, len(with_equip)),
        "H1_points_with_true_equipment": len(with_equip),
        "H1_points_ungrouped": sum(1 for pid in with_equip if pid not in group_of),
        "H2_labelled_points": len(labelled),
        "H2_exact_pct": _pct(len(exact), len(labelled)),
        "H2_compatible_pct": _pct(len(compat), len(labelled)),
        "H2_auto_accepted_pct_of_labelled": _pct(len(auto), len(labelled)),
        "H2_auto_accepted_exact_pct": _pct(len(auto_exact), len(auto)),
        "H2_unreachable_classes": unreachable,
        "review_pct": _pct(len(to_review), len(points)),
        "human_decided": sum(1 for n in points if n["method"] == "human" or n["status"] != "proposed"),
        "equipment_class_exact_pct": _pct(eq_exact, len(eq_pairs)),
        "equipment_matched": len(matched),
        "equipment_true": len(gt.equipment),
        "feeds": rel_scores("feeds"),
        "hasPart": rel_scores("hasPart"),
        "by_name_source": by_source,
        "calibration": calibration,
        "llm_calls": cost[0],
        "cost_usd_per_1000_points": round(cost[1] * per_k, 4),
        "seconds_per_1000_points": round((run["seconds"] or 0) * per_k, 3),
        "revision": run["revision"],
    }
