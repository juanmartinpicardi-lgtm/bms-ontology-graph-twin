"""Scoring against answer keys a person wrote (answer_keys.py), next to the agent-written keys.

Where a human key exists (data/ground_truth/<set>/plans.human.yaml, sequences.human.yaml) and covers an item, the human
answer is the truth for that item: `plan_effective_key` and `sequence_effective_key` lay the human key over the agent
key and the existing scoring runs on the result unchanged. With no human key, both return the agent key as it is.

Both keys are also reported side by side on the items the human key covers:
  vs human key    the reader's answers scored against the human key, on its items
  vs agent key    the same answers on the same items against the agent key
  agreement       how often the two keys say the same thing on those items (a low number means the agent key, or the
                  human one, needs a second look before any reader is judged by either)

Plans score tag placements only (a floor and a room, or none); the human key does not list every room label of a sheet,
so room scoring stays on the agent key. Sequences score relations on the sections the human key answered.
"""
from __future__ import annotations

import copy
import re

from .. import answer_keys as ak
from . import sequences as sq


def _pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


# plans -------------------------------------------------------------------------------------------------------------

def _normal(text: str) -> str:
    from ..intake.plan_ai import normal_of
    return normal_of(text)


def placement_ok(fact: dict, k: dict) -> bool:
    """A placement fact (data: floor, room) against a key entry (floor, rooms; [] means no room)."""
    room, fl = fact["data"].get("room"), fact["data"].get("floor")
    return fl == k["floor"] and (room in [str(x) for x in k["rooms"]] if k["rooms"] else room is None)


def plan_human(site: str) -> dict | None:
    """The human plan key derived from its done items (tags, unsure, not_units), or None."""
    return ak.load_derived("plans", site)


def plan_effective_key(site: str, agent: dict) -> dict:
    """The agent key with the human key's answers laid over it, tag by tag (matched on the normalised tag)."""
    h = plan_human(site)
    if not h:
        return agent
    key = copy.deepcopy(agent)
    by_normal = {_normal(t): t for t in key["tags"]}
    for t, e in h["tags"].items():
        key["tags"][by_normal.get(_normal(t), t)] = {"floor": e["floor"], "rooms": list(e["rooms"]), "rel": e["rel"]}
    for t in [*h["unsure"], *h["not_units"]]:  # the human says it is no unit here, or can't tell: nothing to score
        key["tags"].pop(by_normal.get(_normal(t), t), None)
    return key


def plan_agreement(agent: dict, h: dict) -> dict:
    """The two keys on the tags the human key answered: the same floor and a room in common (or both in none)."""
    a_tags = {_normal(t): (t, k) for t, k in agent["tags"].items()}
    agree, differ, human_only, human_not_unit = 0, [], [], []
    for t, e in h["tags"].items():
        got = a_tags.get(_normal(t))
        if not got:
            human_only.append(t)
            continue
        ar, hr = {str(x) for x in got[1]["rooms"]}, {str(x) for x in e["rooms"]}
        if got[1]["floor"] == e["floor"] and ((not ar and not hr) or (ar & hr)):
            agree += 1
        else:
            differ.append(f"{t}: human {e['floor']}/{'|'.join(sorted(hr)) or '-'}, "
                          f"agent {got[1]['floor']}/{'|'.join(sorted(ar)) or '-'}")
    for t in [*h["unsure"], *h["not_units"]]:
        if _normal(t) in a_tags:
            human_not_unit.append(t)
    n = agree + len(differ)
    return {"both": n, "agree": agree, "agree_pct": _pct(agree, n), "differ": differ, "human_only": human_only,
            "agent_has_human_says_no_unit": human_not_unit}


def plan_compare(site: str, facts: list[dict], agent: dict) -> dict | None:
    """The reader's placements on the human key's tags, scored against each key; None with no human key."""
    h = plan_human(site)
    if not h:
        return None
    place = {f["data"]["normal"]: f for f in facts if f["kind"] == "placement"}
    a_tags = {_normal(t): k for t, k in agent["tags"].items()}
    n = placed = right_h = a_n = right_a = 0
    wrong = []
    for t, e in h["tags"].items():
        n += 1
        f = place.get(_normal(t))
        placed += bool(f)
        ok = bool(f) and placement_ok(f, e)
        right_h += ok
        if f and not ok:
            wrong.append(f"{t}: {f['data'].get('floor')}/{f['data'].get('room')} (human key {e['floor']}/"
                         f"{'|'.join(map(str, e['rooms'])) or '-'})")
        if (agent_k := a_tags.get(_normal(t))) is not None:
            a_n += 1
            right_a += bool(f) and placement_ok(f, agent_k)
    done = ak.done_items(ak.load("plans", site))
    return {"items": len(done), "tags": n, "placed": placed, "right": right_h, "right_pct": _pct(right_h, n),
            "agent_same_tags": a_n, "agent_right": right_a, "agent_right_pct": _pct(right_a, a_n), "wrong": wrong,
            "agreement": plan_agreement(agent, h), "revealed": sum(bool(i.get("revealed")) for i in done),
            "minutes": round(sum(float(i.get("minutes") or 0) for i in done), 1)}


def plan_combine(parts: list[dict]) -> dict | None:
    """Sum the per-set comparisons (the all-dev-sets row)."""
    parts = [p for p in parts if p]
    if not parts:
        return None
    s = {k: sum(p[k] for p in parts) for k in ("items", "tags", "placed", "right", "agent_same_tags", "agent_right",
                                              "revealed", "minutes")}
    both = sum(p["agreement"]["both"] for p in parts)
    agree = sum(p["agreement"]["agree"] for p in parts)
    return {**s, "right_pct": _pct(s["right"], s["tags"]), "agent_right_pct": _pct(s["agent_right"], s["agent_same_tags"]),
            "agreement": {"both": both, "agree": agree, "agree_pct": _pct(agree, both),
                          "human_only": [t for p in parts for t in p["agreement"]["human_only"]],
                          "differ": [t for p in parts for t in p["agreement"]["differ"]],
                          "agent_has_human_says_no_unit": [t for p in parts for t in
                                                           p["agreement"]["agent_has_human_says_no_unit"]]}}


# sequences ---------------------------------------------------------------------------------------------------------

def sec_letter(s) -> str:
    """A section as the keys name it: its letter or number, upper case ('e.' and 'E' are the same)."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper().split()[0] if str(s or "").strip() else "")


def sequence_human(site: str) -> dict | None:
    return ak.load_derived("sequences", site)


def _restrict(seq: dict, secs: set[str]) -> dict:
    """A key sequence cut to the sections `secs` (entries with no section are dropped)."""
    out = dict(seq)
    for part in ("loops", "interlocks", "resets", "modes", "gaps"):
        out[part] = [x for x in seq.get(part) or [] if sec_letter(x.get("section")) in secs]
    return out


def sequence_effective_key(site: str, agent: dict) -> dict:
    """The agent key with each answered section's relations and gaps replaced by the human key's."""
    h = sequence_human(site)
    if not h:
        return agent
    key = copy.deepcopy(agent)
    for sid, secs in h["covered"].items():
        S = {sec_letter(s) for s in secs}
        hs = h["sequences"][sid]
        a = key["sequences"].setdefault(sid, {"title": hs.get("title", ""), "loops": [], "interlocks": [],
                                              "resets": [], "modes": [], "gaps": [], "conflicts": []})
        for part in ("loops", "interlocks", "resets", "modes", "gaps"):
            a[part] = [x for x in a.get(part) or [] if sec_letter(x.get("section")) not in S] + list(hs[part])
    return key


def _overlap(a: dict, b: dict) -> bool:
    return bool(a["from"] & b["from"] and a["rel"] & b["rel"] and a["to"] & b["to"])


def sequence_agreement(agent: dict, h: dict) -> dict:
    """The two keys' relations on the answered sections: how many of each are in the other (any-of ends overlap)."""
    hr, ar = [], []
    for sid, secs in h["covered"].items():
        S = {sec_letter(s) for s in secs}
        hr += sq.key_relations(h["sequences"][sid])
        if sid in agent["sequences"]:
            ar += [r for r in sq.key_relations(_restrict(agent["sequences"][sid], S)) if not r["optional"]]
    h_in = sum(any(_overlap(x, y) for y in ar) for x in hr)
    a_in = sum(any(_overlap(x, y) for y in hr) for x in ar)
    return {"human_relations": len(hr), "human_in_agent": h_in, "agent_relations": len(ar), "agent_in_human": a_in,
            "agree_pct": _pct(h_in + a_in, len(hr) + len(ar))}


def sequence_compare(logic: dict[str, dict], agent: dict, site: str) -> dict | None:
    """A reading's relations on the sections the human key answered, scored against the human key and against the
    agent key (same sections); None with no human key. `logic` is {seq:<id>: {relations: [...]}}."""
    h = sequence_human(site)
    if not h:
        return None
    per_h, per_a = {}, {}
    unattributed = 0
    for sid, secs in h["covered"].items():
        S = {sec_letter(s) for s in secs}
        m = logic.get(f"seq:{sid}", {"relations": []})
        unattributed += sum(1 for r in m["relations"] if not sec_letter(r.get("section")))
        ans = [r for r in m["relations"] if sec_letter(r.get("section")) in S]
        per_h[sid] = sq.score(ans, sq.key_relations(h["sequences"][sid]))
        per_a[sid] = sq.score(ans, sq.key_relations(_restrict(agent["sequences"].get(sid, {}), S)))
    items = ak.done_items(ak.load("sequences", site))
    keep = ("tp", "fp", "dup", "required", "found", "precision_pct", "recall_pct", "f1")
    return {"sections": sum(len(v) for v in h["covered"].values()), "sequences": len(h["covered"]),
            "vs_human": {k: v for k, v in sq.summary(per_h).items() if k in keep},
            "vs_agent": {k: v for k, v in sq.summary(per_a).items() if k in keep},
            "agreement": sequence_agreement(agent, h), "unattributed_answers": unattributed,
            "revealed": sum(bool(i.get("revealed")) for i in items),
            "minutes": round(sum(float(i.get("minutes") or 0) for i in items), 1)}
