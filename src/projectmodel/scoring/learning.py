"""The learning loop, measured (W10): does a convention learned from two review fixes make the other points of its
pattern right, and nothing else wrong?

    simulate("alpha/names_paths")      ->  report (dict);  print_report(report)
    scripts/learning_loop.py            the command;  scripts/eval.py learning  the same, from the eval harness

Steps, all in a temporary database and a temporary copy of knowledge/ (PM_KNOWLEDGE_DIR), so the repo's files and
Alpha's default scores never change:
  1. Map the project with its conventions, as `scripts/score.py` does, and score it: the baseline.
  2. Error patterns, from the answer key: wrong points grouped by (machine class, true class, equipment template),
     kept when they have more than `fixes` points, so some are left to measure on.
  3. A simulated reviewer fixes `fixes` points of each pattern to the key's class (review.fix_class: method human).
     Those are the only points the curator sees the key through.
  4. The curator proposes conventions (rules; the memory_curator model phrases them when models are on). A person's
     approval is simulated: every proposal is approved.
  5. The mapper runs again, now with the approved conventions, and the project is scored again.

Reported per convention: the points it decided (its id in their provenance), the fixed points left out; how many of
those were wrong before and are wrong after. Per pattern: its points that were not fixed, wrong before and after.
Overall: class exact on every labelled point except the fixed ones. And the same site's names-only export, where no
fix was made, before and after (the conventions are site-wide). The fixed points are never counted as improvement.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REVIEWER = "simulated reviewer"
HELD_OUT = {"liberty_boe"}


@contextlib.contextmanager
def _knowledge_copy(tmp: Path):
    """A copy of knowledge/ that approvals write to, in force for the block."""
    from ..memory import KNOWLEDGE_DIR

    dst = tmp / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, dst)
    before = os.environ.get("PM_KNOWLEDGE_DIR")
    os.environ["PM_KNOWLEDGE_DIR"] = str(dst)
    try:
        yield dst
    finally:
        if before is None:
            os.environ.pop("PM_KNOWLEDGE_DIR", None)
        else:
            os.environ["PM_KNOWLEDGE_DIR"] = before


def truth(store, project: str, gt) -> dict[str, str]:
    """Point node id -> the answer key's class (labelled points only)."""
    out = {}
    for n in store.nodes(project, "point"):
        row = gt.points[gt.key[json.loads(n["attrs"])["source_id"]]["point_id"]]
        if row["brick_class"]:
            out[n["id"]] = row["brick_class"]
    return out


def _classes(store, project: str) -> dict[str, dict]:
    return {n["id"]: {"class": None if n["status"] == "rejected" else n["class"], "name": n["label"],
                      "confidence": n["confidence"], "method": n["method"],
                      "convention": json.loads(n["attrs"] or "{}").get("convention", [])}
            for n in store.nodes(project, "point")}


def _exact(classes: dict, key: dict, skip: set, accept: float | None = None) -> dict:
    ids = [p for p in key if p not in skip and (accept is None or (classes[p]["confidence"] >= accept
                                                                   and classes[p]["class"]))]
    ok = sum(classes[p]["class"] == key[p] for p in ids)
    return {"n": len(ids), "exact": ok, "pct": round(100 * ok / len(ids), 1) if ids else None}


def error_patterns(store, project: str, key: dict, min_points: int) -> list[dict]:
    """Wrong points grouped by (machine class, true class, equipment template), biggest first."""
    from ..curator import _graph

    graph, classes = _graph(store, project), _classes(store, project)
    groups = defaultdict(list)
    for pid, true in key.items():
        c = classes[pid]["class"]
        if c and c != true:
            groups[(c, true, graph[pid]["template"])].append(pid)
    out = [{"before": b, "after": a, "template": t, "points": sorted(ps),
            "names": sorted({classes[p]["name"] for p in ps})[:6]}
           for (b, a, t), ps in groups.items() if len(ps) >= min_points]
    return sorted(out, key=lambda x: (-len(x["points"]), x["before"], x["after"]))


def simulate(project: str = "alpha/names_paths", *, fixes: int = 2, max_patterns: int | None = None, router=None,
             also: list[str] | None = None, log=print) -> dict:
    """Run the loop on `project` (a site with an answer key) and score it honestly; see the module docstring.
    `also`: other projects of the same site, mapped and scored before and after without any fix (default: the other
    blind export of the site)."""
    from .. import curator, review
    from ..build import map_project
    from ..db.store import Store
    from ..knowledge_model import load_knowledge_model
    from .score import DEFAULT_ACCEPT, load_ground_truth, score_project

    site, variant = project.split("/")
    if site in HELD_OUT:
        raise ValueError(f"{site} is held out")
    also = also if also is not None else [f"{site}/{v}" for v in ("names_paths", "names_only") if v != variant]
    km = load_knowledge_model()  # the bare model: classes and templates for the checks, and scoring, as score.py
    gt = load_ground_truth(site)
    with tempfile.TemporaryDirectory() as tmp, _knowledge_copy(Path(tmp)) as kdir:
        db = Path(tmp) / "kg.sqlite"
        store = Store(db)
        for p in [project, *also]:
            map_project(*p.split("/"), db)
        key = truth(store, project, gt)
        base = _classes(store, project)
        base_score = score_project(store, project, gt, km, DEFAULT_ACCEPT)
        also_before = {p: (_classes(store, p), truth(store, p, gt)) for p in also}
        patterns = error_patterns(store, project, key, fixes + 1)[:max_patterns]
        log(f"{project}: {len(patterns)} error patterns with more than {fixes} points")

        fixed: set[str] = set()
        for pat in patterns:
            pat["fixed"] = pat["points"][:fixes]
            for pid in pat["fixed"]:
                review.fix_class(store, km, project, [pid], key[pid], REVIEWER)
            fixed |= set(pat["fixed"])
        proposals = curator.propose(store, km, project, router=router)
        log(f"curator: {len(proposals)} proposals from {len(fixed)} fixes")
        for p in proposals:
            curator.approve(store, km, p["id"], REVIEWER, knowledge=kdir)
        for p in [project, *also]:
            map_project(*p.split("/"), db)
        after = _classes(store, project)
        after_score = score_project(store, project, gt, km, DEFAULT_ACCEPT)
        cost = store.conn.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE job = ?",
                                  (curator.JOB,)).fetchone()

        convs = []
        for p in proposals:
            origin = f"{p['scope']}:{p['id']}"
            ev = {e["node"] for e in p["evidence"]}
            touched = [pid for pid, c in after.items() if origin in c["convention"] and pid not in fixed]
            labelled = [pid for pid in touched if pid in key]
            convs.append({
                "id": p["id"], "title": p["payload"]["title"], "entry": p["payload"]["entry"], "why": p["why"],
                "phrased_by": p["checks"].get("phrased_by"), "fixes": sorted(e["name"] for e in p["evidence"]),
                "patterns": [i for i, pat in enumerate(patterns) if ev & set(pat["fixed"])],
                "touched": len(touched), "labelled": len(labelled),
                "wrong_before": sum(base[x]["class"] != key[x] for x in labelled),
                "wrong_after": sum(after[x]["class"] != key[x] for x in labelled),
                "examples": sorted({after[x]["name"] for x in touched})[:5],
            })
        for i, pat in enumerate(patterns):
            rest = [x for x in pat["points"] if x not in fixed]
            pat |= {"id": i, "held_out": len(rest), "wrong_after": sum(after[x]["class"] != key[x] for x in rest),
                    "conventions": [c["id"] for c in convs if i in c["patterns"]]}
            pat.pop("points")
        also_rows = []
        for p in also:
            cb, k = also_before[p]
            ca = _classes(store, p)
            changed = [x for x in k if cb[x]["class"] != ca[x]["class"]]
            also_rows.append({"project": p, "before": _exact(cb, k, set()), "after": _exact(ca, k, set()),
                              "changed": len(changed),
                              "changed_right_after": sum(ca[x]["class"] == k[x] for x in changed),
                              "changed_right_before": sum(cb[x]["class"] == k[x] for x in changed)})
        return {
            "project": project, "fixes_per_pattern": fixes, "fixed_points": len(fixed),
            "patterns": patterns, "conventions": convs,
            "overall": {"before": _exact(base, key, fixed), "after": _exact(after, key, fixed),
                        "above_threshold_before": _exact(base, key, fixed, DEFAULT_ACCEPT),
                        "above_threshold_after": _exact(after, key, fixed, DEFAULT_ACCEPT),
                        "score_before": {k: base_score[k] for k in ("H2_exact_pct", "H2_auto_accepted_exact_pct",
                                                                    "review_pct", "human_decided")},
                        "score_after": {k: after_score[k] for k in ("H2_exact_pct", "H2_auto_accepted_exact_pct",
                                                                   "review_pct", "human_decided")},
                        "conventions_after": after_score["conventions"]},
            "also": also_rows,
            "model": {"calls": cost[0], "cost_usd": round(cost[1], 4)},
        }


def print_report(r: dict, out=print) -> None:
    o = r["overall"]
    out(f"\nLearning loop on {r['project']}: {r['fixes_per_pattern']} fixes per pattern, {r['fixed_points']} points "
        f"fixed by the simulated reviewer (never counted below)\n")
    out("Per convention (approved, then the mapper re-run): points it decided, fixed points left out")
    out(f"  {'id':<10}{'touched':>8}{'keyed':>7}{'wrong before':>14}{'wrong after':>13}  convention")
    for c in r["conventions"]:
        out(f"  {c['id']:<10}{c['touched']:>8}{c['labelled']:>7}{c['wrong_before']:>14}{c['wrong_after']:>13}  "
            f"{c['title']}")
    out("\nPer error pattern (machine -> key, on template): its points that were not fixed")
    out(f"  {'#':<4}{'held out':>9}{'wrong before':>14}{'wrong after':>13}  pattern; convention")
    for p in r["patterns"]:
        out(f"  {p['id']:<4}{p['held_out']:>9}{p['held_out']:>14}{p['wrong_after']:>13}  {p['before']} -> {p['after']}"
            f" on {p['template'] or 'any'} ({', '.join(p['names'][:3])}); {', '.join(p['conventions']) or 'none'}")
    b, a = o["before"], o["after"]
    out(f"\nClass exact, every keyed point except the fixed ones: {b['exact']}/{b['n']} ({b['pct']}%) -> "
        f"{a['exact']}/{a['n']} ({a['pct']}%)")
    b, a = o["above_threshold_before"], o["above_threshold_after"]
    out(f"  above the threshold: {b['exact']}/{b['n']} ({b['pct']}%) -> {a['exact']}/{a['n']} ({a['pct']}%)")
    out(f"scripts/score.py H2 exact (all points, fixes included): {o['score_before']['H2_exact_pct']}% -> "
        f"{o['score_after']['H2_exact_pct']}%; conventions after: {', '.join(o['conventions_after'])}")
    for x in r["also"]:
        out(f"{x['project']} (same site, no fix made there): {x['before']['exact']}/{x['before']['n']} "
            f"({x['before']['pct']}%) -> {x['after']['exact']}/{x['after']['n']} ({x['after']['pct']}%); "
            f"{x['changed']} points changed, {x['changed_right_before']} right before, {x['changed_right_after']} after")
    out(f"memory_curator calls: {r['model']['calls']}, ${r['model']['cost_usd']}")
