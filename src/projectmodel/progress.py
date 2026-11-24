"""Progress: how complete each project's graph is, layer by layer, and what to do next to complete it.

Built on the graph standard (graph_standard.status), so the numbers are the ones the Complete graph page shows.
For each project:

    layers      the six layers (spaces, systems, equipment, points, behaviour, trust), each 0-100
    overall     the mean of the measurable facts
    next        the facts furthest from done, each with what to do, which page does it, and the roadmap package
                (roadmap.py) that builds it when nothing in the app can yet

Buildings still in the guided setup are measured on their steps instead (setup()): steps read, questions open,
coverage gaps. Alpha is the demo set: it is measured like any project and never changed by this module.
"""
from __future__ import annotations

from . import graph_standard as gs
from .roadmap import BY_ID

DEMO = "alpha"

# fact -> (what to do, app page that does it or None, roadmap package or None). Documents-first wording: a new
# building comes through the guided setup.
NEXT = {
    "site": ("Add the building in the guided setup: its name and address make the site and building, its floor plans "
             "the floors under it.", "views/add_building.py", None),
    "spaces": ("Upload the floor plans in the guided setup to add floors and rooms.", "views/add_building.py", "W6"),
    "serves": ("Answer the plan's questions on which room each terminal unit serves.", "views/add_building.py", "W6"),
    "systems": ("Plants and loops come from plant folders today; air systems and plants read from the documents "
                "are not built yet.", None, None),
    "membership": ("Place each pump and chiller in its plant or loop.", "tree_app.py", None),
    "equipment": ("Upload the equipment schedules to reconcile the equipment list.", "views/add_building.py", None),
    "equip_class": ("Review equipment left with a generic type.", "tree_app.py", None),
    "feeds": ("Check which air handler feeds each terminal unit.", "tree_app.py", "W7"),
    "nameplate": ("Upload the equipment schedules: make, model and capacity per unit.", "views/add_building.py", None),
    "controllers": ("Upload the controls submittal (its riser) or a BMS export with device instances, and answer "
                    "which unit each unmatched controller runs.", "views/add_building.py", "W7"),
    "networks": ("The riser's trunk headings or the BMS export's trunk column put each controller on its network.",
                 "views/add_building.py", "W7"),
    "point": ("Upload the BMS export with device instances and object ids, so a rename doesn't break a point.",
              "views/add_building.py", "W12"),
    "point_equip": ("Place the points left without equipment.", "tree_app.py", "W7"),
    "point_class": ("Review the points left with a generic class.", "tree_app.py", "W5"),
    "point_props": ("Units come with the submittal's point schedule or the BMS export; a Niagara or CPO export adds "
                    "writability.", "views/add_building.py", "W12"),
    "required": ("Find or record the points each equipment template expects.", "views/equipment_3d.py", None),
    "loops": ("Add the sequence of operations to link setpoints, sensors and outputs.", "views/sequences.py", "W8"),
    "interlocks": ("Interlocks, resets and requests come from the sequence of operations.", "views/sequences.py", "W8"),
    "modes": ("Modes and schedules come from the sequence of operations.", "views/sequences.py", "W8"),
    "intent_values": ("Intended setpoints come from the sequence of operations.", "views/sequences.py", "W8"),
    "intent_asbuilt": ("Compare the sequence with the control programs (needs the Niagara or CPO export).", None,
                       "W12"),
    "provenance": ("Every fact already carries its source.", None, None),
    "validation": ("Fix what breaks the building rules (one air handler per terminal, no feed cycles).", "tree_app.py",
                   "W2"),
    "agreement": ("Add a second document (schedule, submittal) so key facts are confirmed twice.",
                  "views/add_building.py", "W3"),
    "calibration": ("Confidence must match accuracy: measured against ground truth.", None, "W5"),
}


def measure(store, km, project: str) -> dict[str, dict]:
    """The graph standard's status for one project, with its score and sequences when it has them."""
    from .scoring.score import DEFAULT_ACCEPT, GT_DIR, load_ground_truth, score_project
    from .sequences import behaviour, sequences_payload
    site = project.split("/")[0]
    score = seqs = None
    if (GT_DIR / site).exists():
        try:
            score = score_project(store, project, load_ground_truth(site), km, DEFAULT_ACCEPT)
        except Exception:  # ground truth for another input than this project's: measure without it
            score = None
    try:
        seqs = behaviour(sequences_payload(store, km, project))
    except Exception:  # no sequence document for this site
        seqs = None
    return gs.status(store, km, project, score, seqs)


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 1) if xs else None


def summarize(status: dict[str, dict], project: str, n_next: int = 4) -> dict:
    """Layers, overall and next steps from one project's status."""
    facts = {f["id"]: f for f in gs.FACTS}
    layers = []
    for lay in gs.LAYERS:
        ids = [f["id"] for f in gs.FACTS if f["layer"] == lay["id"]]
        pcts = [status[i]["pct"] for i in ids if status.get(i, {}).get("pct") is not None]
        done = sum(1 for i in ids if status.get(i, {}).get("state") == "done")
        layers.append({"id": lay["id"], "name": lay["name"], "icon": lay["icon"], "pct": _mean(pcts) or 0,
                       "done": done, "facts": len(ids)})
    overall = _mean([s["pct"] for s in status.values() if s.get("pct") is not None]) or 0
    gaps = sorted((i for i, s in status.items() if s.get("state") != "done" and i in facts),
                  key=lambda i: (status[i]["pct"] if status[i]["pct"] is not None else 50,
                                 [lay["id"] for lay in gs.LAYERS].index(facts[i]["layer"])))
    nxt = []
    for i in gaps:
        action, page, pkg = NEXT.get(i, ("", None, None))
        if not action:
            continue
        nxt.append({"fact": i, "name": facts[i]["name"], "pct": status[i]["pct"], "note": status[i]["note"],
                    "action": action, "page": page, "package": pkg,
                    "package_name": BY_ID[pkg]["name"] if pkg in BY_ID else None,
                    "in_app": page is not None})
    # What a person can do now first, then what waits for the roadmap.
    nxt = sorted(nxt, key=lambda x: not x["in_app"])[:n_next]
    return {"project": project, "demo": project.split("/")[0] == DEMO, "overall": overall, "layers": layers,
            "next": nxt, "done": sum(1 for s in status.values() if s.get("state") == "done"), "facts": len(gs.FACTS)}


def project_progress(store, km, project: str, n_next: int = 4) -> dict:
    return summarize(measure(store, km, project), project, n_next)


def setup(slug: str) -> dict:
    """A building in the guided setup: steps read, questions open, coverage gaps, and the next step to take."""
    from .intake.model import progress as step_progress
    from .intake.state import Intake
    from .intake.steps import STEPS
    it = Intake(slug)
    share = step_progress(it)["share"]  # read and answered, the share the All projects card shows
    steps = [s for s in STEPS if s.id != "review"]
    read = [s for s in steps if it.done(s.id)]
    questions = it.open_questions()
    coverage = [q for q in questions if q["kind"] == "issue" and q.get("data", {}).get("severity") == "coverage"]
    nxt = next((s for s in steps if not it.done(s.id)), None)
    published = (it.s or {}).get("published")
    if nxt:
        action = f"Step {nxt.n}: {nxt.ask.lower()}."
    elif questions:
        action = f"Answer the {len(questions)} open questions, then publish."
    elif not published:
        action = "Review and publish the building as a project."
    else:
        action = "Published. Re-read a step after any change."
    return {"slug": slug, "name": it.name, "steps": len(steps), "read": len(read),
            "pct": round(100 * share), "questions": len(questions), "coverage": len(coverage),
            "coverage_text": [q["label"] for q in coverage], "next": action,
            "published": published["project"] if published else None}
