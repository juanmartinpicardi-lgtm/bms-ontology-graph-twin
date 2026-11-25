"""The learning loop (plan-workflow-ai §5.5, work package W10; spec-memory-skills §6; spec-tribal-knowledge T3): fixes
people make in review become proposed conventions; a person approves one; from the next run the rules do the work.

    fixes(store, project)                       every class fix and move a person made, with its features (review.py)
    find(store, km, project)                    rules only: repeated fixes -> candidate conventions, each with its
                                                possible patterns and what each would change now (a dry run)
    propose(store, km, project, router=None)    candidates -> pending proposals. The memory_curator job, when models
                                                are on, picks one of the rules' patterns and phrases the proposal:
                                                candidates in, ids out; it never writes a class or a pattern
    pending(store) · proposal(store, id) · approve(store, km, id, by) · reject(store, id, by, why)

What counts as a pattern (rules first): MIN_FIXES or more fixes of points with the same class change (before ->
after), on equipment of the same template, whose names share a word that is not the equipment's own name. The
convention it proposes is a scoped class hint: names like these, on that template, are `after` instead of `before`
({pattern, class, template, instead_of}, conventions.py). A fix on a guided-setup project proposes a setup term
(phrase -> class) instead. Moves (a point put on other equipment) and equipment class fixes are captured with their
features but propose nothing yet: no rule kind regroups points or retypes equipment from a name.

Checks before anyone sees a proposal: the class and template exist in the knowledge model (the same check as any
convention file); a pattern that contradicts a person's decision (a point a person classed otherwise, that the
pattern would change) is dropped; what each pattern would change now is counted on the project's current graph.

Approving writes the entry to knowledge/skills/<scope>/learned-conventions-<name>/ (spec-memory-skills §5.1): SKILL.md
(version bumped, approver, evidence) and rules/conventions.yaml (class hints) or rules/terms.yaml (setup terms). The
mapper and the setup read those files on their next run (conventions.load_layers, conventions.learned_terms), as
method=rule with the convention's id in the provenance. A person's decision is never overridden: review rows are not
replaced by any run (db/store.py). Rejected proposals stay rejected: the same proposal is not made again.

Proposals wait in SQLite (`proposals`, spec-memory-skills §5.2), not in git: only approved conventions are files.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .db.store import REVIEW, Store
from .knowledge_model import KnowledgeModel
from .review import name_words

MIN_FIXES = 2   # the same fix made twice is a pattern (plan §7, W10)
EXAMPLES = 5
JOB = "memory_curator"

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL,
    scope       TEXT NOT NULL,
    op          TEXT NOT NULL,              -- rules.patch
    target      TEXT,                       -- the skill the entry goes into
    payload     TEXT NOT NULL,              -- JSON: kind, entry, file, options, chosen, title
    why         TEXT NOT NULL,
    evidence    TEXT NOT NULL,              -- JSON: the fixes (node, name, before, after, by, template)
    lane        TEXT NOT NULL DEFAULT 'approve',
    checks      TEXT NOT NULL,              -- JSON: would_change, examples, contradicted options, model
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    model       TEXT,
    llm_call    INTEGER,
    decided_by  TEXT,
    decided_at  TEXT,
    reason      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def ensure_schema(store: Store) -> None:
    store.conn.executescript(SCHEMA)


# 1. capture --------------------------------------------------------------------------------------------------------

@dataclass
class Fix:
    project: str
    node: str
    kind: str                 # class | move
    before: str | None        # the machine's class, or the equipment the point left
    after: str | None         # the person's class, or the equipment the point went to
    by: str
    at: str
    f: dict = field(default_factory=dict)   # features (review.features)

    @property
    def name(self) -> str:
        return self.f.get("name", "")


def fixes(store: Store, project: str) -> list[Fix]:
    """Every class fix and every move a person made on `project`, oldest first."""
    out = []
    for r in store.conn.execute("SELECT * FROM nodes WHERE project = ? AND source = ? AND method = 'human'",
                                (project, REVIEW)):
        rv = json.loads(r["attrs"] or "{}").get("review") or {}
        before = (rv.get("previous") or {}).get("class")
        if rv.get("action") == "fix" and before != r["class"]:
            out.append(Fix(project, r["id"], "class", before, r["class"], rv.get("by", ""), rv.get("at", ""),
                           rv.get("features") or {"name": r["label"], "words": name_words(r["label"]),
                                                  "kind": r["kind"]}))
    for e in store.conn.execute("SELECT * FROM edges WHERE project = ? AND rel = 'hasPoint' AND method = 'human'"
                                " AND status = 'confirmed'", (project,)):
        rv = json.loads(e["attrs"] or "{}").get("review") or {}
        if rv.get("action") == "move":
            left = (rv.get("previous") or {}).get("equipment") or [None]
            out.append(Fix(project, e["dst"], "move", left[0], e["src"], rv.get("by", ""), rv.get("at", ""),
                           rv.get("features") or {}))
    return sorted(out, key=lambda x: (x.at, x.node))


# 2. find the pattern (rules) -----------------------------------------------------------------------------------------

def _w(word: str) -> str:
    """A regex for one name word, not inside a longer word."""
    return rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"


def _name_regex(name: str) -> str:
    """The name itself, case-insensitive, any number where it has a number."""
    return re.sub(r"\d+", r"\\d+", re.escape(name.strip()))


@dataclass
class Option:
    id: str
    pattern: str              # regex on the point name (class hints) or the phrase (setup terms)
    says: str                 # in words
    would_change: list[str] = field(default_factory=list)   # point ids this would change now (not the evidence)
    examples: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    id: str                   # C1, C2... in one find() run
    project: str
    kind: str                 # class_hints | terms
    before: str
    after: str
    template: str | None
    fixes: list[Fix]
    options: list[Option]
    chosen: str               # the option the rules pick
    dropped: list[dict] = field(default_factory=list)   # options that contradict a person's decision

    def option(self, oid: str) -> Option:
        return next(o for o in self.options if o.id == oid)


def _is_setup(project: str, fx: list[Fix]) -> bool:
    return project.endswith("/documents") or any(str(x.f.get("source", "")).startswith("setup:") for x in fx)


def _graph(store: Store, project: str) -> dict[str, dict]:
    """Point id -> name, class, description, method, source and its equipment's template, as the graph is now."""
    equip = {r["id"]: json.loads(r["attrs"] or "{}").get("template")
             for r in store.conn.execute("SELECT id, attrs FROM nodes WHERE project = ? AND kind = 'equipment'",
                                         (project,))}
    on = {e["dst"]: e["src"] for e in store.conn.execute(
        "SELECT src, dst FROM edges WHERE project = ? AND rel = 'hasPoint' AND status != 'rejected'"
        " ORDER BY method = 'human'", (project,))}  # a person's placement last, so it wins
    out = {}
    for r in store.conn.execute("SELECT * FROM nodes WHERE project = ? AND kind = 'point'", (project,)):
        a = json.loads(r["attrs"] or "{}")
        out[r["id"]] = {"name": r["label"], "class": r["class"], "description": a.get("description", ""),
                        "human": r["method"] == "human" or r["source"] == REVIEW, "template": equip.get(on.get(r["id"]))}
    return out


def _effect(pattern: str, kind: str, template: str | None, before: str, after: str, graph: dict, evidence: set
            ) -> tuple[list[str], list[str]]:
    """(points this would change now, people's decisions it contradicts), evidence left out."""
    change, contra = [], []
    if kind == "terms":
        def hit(p):
            return p["name"].lower() == pattern.lower() or re.search(rf"(?<!\w){re.escape(pattern)}(?!\w)",
                                                                     p["description"], re.I)
    else:
        rx = re.compile(pattern)

        def hit(p):
            return (template is None or p["template"] == template) and rx.search(p["name"])
    for pid, p in graph.items():
        if pid in evidence or not hit(p):
            continue
        if p["human"]:
            if p["class"] != after:
                contra.append(pid)
        elif p["class"] == before or kind == "terms":
            if p["class"] != after:
                change.append(pid)
    return sorted(change), sorted(contra)


def _components(fx: list[Fix], key) -> list[list[Fix]]:
    """Fixes linked when they share a key word (union-find), in order."""
    parent = list(range(len(fx)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    words = [key(x) for x in fx]
    for i in range(len(fx)):
        for j in range(i + 1, len(fx)):
            if words[i] & words[j]:
                parent[root(j)] = root(i)
    groups = defaultdict(list)
    for i, x in enumerate(fx):
        groups[root(i)].append(x)
    return list(groups.values())


def _key_words(x: Fix) -> set[str]:
    own = set(name_words(x.f.get("equipment_label") or ""))
    return {w for w in x.f.get("words") or name_words(x.name) if w not in own and len(w) > 1 or w == "%"}


def _class_options(comp: list[Fix], template: str | None) -> list[tuple[str, str]]:
    names = sorted({x.name.strip() for x in comp}, key=str.lower)
    out = [("names", "(?i)^(?:" + "|".join(_name_regex(n) for n in names) + ")$",
            "named " + " or ".join(f"“{n}”" for n in names)
            + (" (any number)" if any(re.search(r"\d", n) for n in names) else ""))]
    shared = set.intersection(*(_key_words(x) for x in comp))
    order = [w for w in (comp[0].f.get("words") or name_words(comp[0].name)) if w in shared]
    order = list(dict.fromkeys(order))
    if order:
        out.append(("words", "(?i)^" + "".join(f"(?=.*{_w(w)})" for w in order),
                    "whose name has the word" + ("s " if len(order) > 1 else " ")
                    + " and ".join(f"“{w}”" for w in order)))
    where = f" on {template.upper()} equipment" if template else ""
    return [(i, p, f"points {s}{where}") for i, p, s in out]


def _term_options(comp: list[Fix]) -> list[tuple[str, str, str]]:
    out = []
    shorts = {x.name.strip() for x in comp}
    if len(shorts) == 1:
        out.append(("short", shorts.pop(), "points whose short name is that"))
    descs = [str(x.f.get("description") or "").strip() for x in comp]
    if all(descs):
        if len(set(d.lower() for d in descs)) == 1:
            out.append(("description", descs[0], "points whose description has that phrase"))
        else:
            run = _common_run([d.split() for d in descs])
            if run and (len(run) > 1 or len(run[0]) > 3):
                out.append(("phrase", " ".join(run), "points whose description has that phrase"))
    return [(i, p, f"{s}: “{p}”") for i, p, s in out]


def _common_run(seqs: list[list[str]]) -> list[str]:
    """The longest run of words (case-insensitive) every sequence has."""
    first, best = seqs[0], []
    low = [[w.lower() for w in s] for s in seqs]
    for i in range(len(first)):
        for j in range(len(first), i + len(best), -1):
            run = low[0][i:j]
            if all(any(s[k:k + len(run)] == run for k in range(len(s) - len(run) + 1)) for s in low[1:]):
                best = first[i:j]
                break
    return best


def find(store: Store, km: KnowledgeModel, project: str, min_fixes: int = MIN_FIXES) -> list[Candidate]:
    """Repeated fixes on `project` as candidate conventions. Rules only, no model."""
    fx = [x for x in fixes(store, project) if x.kind == "class" and x.before and x.after
          and x.f.get("kind", "point") == "point" and km.classes.get(x.after) and km.classes[x.after].kind == "point"]
    setup = _is_setup(project, fx)
    graph = _graph(store, project)
    groups = defaultdict(list)
    for x in fx:
        groups[(x.before, x.after, None if setup else x.f.get("template"))].append(x)
    out = []
    for (before, after, template), members in sorted(groups.items(), key=lambda kv: [str(k) for k in kv[0]]):
        key = (lambda x: {w.lower() for w in str(x.f.get("description") or "").split()} | {x.name.lower()}) \
            if setup else _key_words
        for comp in _components(members, key):
            if len(comp) < min_fixes:
                continue
            kind = "terms" if setup else "class_hints"
            evidence = {x.node for x in comp}
            options, dropped = [], []
            raw = _term_options(comp) if setup else _class_options(comp, template)
            seen = set()
            for oid, pattern, says in raw:
                change, contra = _effect(pattern, kind, template, before, after, graph, evidence)
                if contra:
                    dropped.append({"option": oid, "pattern": pattern, "contradicts": contra[:EXAMPLES],
                                    "n": len(contra)})
                    continue
                if tuple(change) in seen and options:
                    continue  # the same points as a narrower option
                seen.add(tuple(change))
                options.append(Option(oid, pattern, says, change, [graph[p]["name"] for p in change[:EXAMPLES]]))
            if not options:
                continue
            # The narrowest option that teaches something beyond the fixes themselves; else the narrowest.
            chosen = next((o.id for o in options if o.would_change), options[0].id)
            out.append(Candidate(f"C{len(out) + 1}", project, kind, before, after, template, comp, options, chosen,
                                 dropped))
    return out


# 3. propose --------------------------------------------------------------------------------------------------------

def scope_of(project: str) -> str:
    return f"site/{project.split('/')[0]}"


def skill_name(scope: str) -> str:
    return f"learned-conventions-{scope.split('/', 1)[1]}"


def entry_of(c: Candidate, oid: str) -> dict:
    o = c.option(oid)
    if c.kind == "terms":
        return {"phrase": o.pattern, "class": c.after}
    return {"pattern": o.pattern, "class": c.after, **({"template": c.template} if c.template else {}),
            "instead_of": c.before}


def proposal_id(scope: str, kind: str, entry: dict) -> str:
    key = json.dumps([scope, kind, entry], sort_keys=True)
    return "lc-" + hashlib.sha1(key.encode()).hexdigest()[:6]


def default_text(c: Candidate, oid: str) -> tuple[str, str]:
    """Title and reason the rules write when no model phrases them."""
    o = c.option(oid)
    names = sorted({x.name for x in c.fixes})
    title = f"{o.says[0].upper()}{o.says[1:]} are {c.after}, not {c.before}"
    who = sorted({x.by for x in c.fixes if x.by})
    why = (f"{len(c.fixes)} fixes ({', '.join(f'“{n}”' for n in names[:3])}{'…' if len(names) > 3 else ''}"
           f"{' by ' + ', '.join(who) if who else ''}) changed {c.before} to {c.after}. "
           f"Now it would change {len(o.would_change)} other point{'s' if len(o.would_change) != 1 else ''}"
           f" the rules call {c.before}.")
    return title, why


def _prompt_values(cands: list[Candidate]) -> dict:
    lines = []
    for c in cands:
        lines.append(f"## {c.id}: {c.before} -> {c.after}" + (f" on {c.template} equipment" if c.template else ""))
        for x in c.fixes:
            lines.append(f"- fix: “{x.name}”" + (f" in folder {x.f.get('folder')}" if x.f.get("folder") else "")
                         + (f", description “{x.f['description']}”" if x.f.get("description") else ""))
        for o in c.options:
            lines.append(f"- option {c.id}.{o.id}: {o.says}; would change {len(o.would_change)} other points now"
                         + (f", e.g. {', '.join(f'“{e}”' for e in o.examples)}" if o.examples else ""))
        lines.append("")
    return {"candidates": "\n".join(lines).strip(), "candidate_ids": [c.id for c in cands],
            "option_ids": {c.id: [o.id for o in c.options] for c in cands}}


def _ask_model(cands: list[Candidate], router, store: Store, project: str) -> tuple[dict, dict]:
    """{candidate id: {option, title, why}} from the memory_curator job, and what the call cost. Empty when models
    are off or every model failed: the rules' own choice and wording stand."""
    from .ai.calls import default_router
    from .ai.jobs import run_job
    from .ai.providers import ModelError, ModelUnavailable

    router = router or default_router()
    if not cands or not router.ready:
        return {}, {"off": router.why_not_ready() if not router.ready else ""}
    try:
        res = run_job(JOB, _prompt_values(cands), router=router, store=store, project=project)
    except (ModelError, ModelUnavailable) as e:
        return {}, {"error": str(e)[:300]}
    picks = {p["candidate"]: p for p in res.output["choices"]}
    call = next((a["call"] for a in reversed(res.attempts) if a.get("call")), None)
    return picks, {"model": res.model, "cost_usd": round(res.cost_usd, 5), "seconds": round(res.latency_s, 2),
                   "call": call}


def propose(store: Store, km: KnowledgeModel, project: str, *, router=None, min_fixes: int = MIN_FIXES,
            use_model: bool = True) -> list[dict]:
    """Find the patterns in `project`'s fixes and record each as a pending proposal (spec-memory-skills §5.2).
    A proposal already decided (approved or rejected) is not made again; a pending one is refreshed with the latest
    evidence and dry run. Returns the pending proposals touched."""
    ensure_schema(store)
    cands = find(store, km, project, min_fixes)
    picks, call = _ask_model(cands, router, store, project) if use_model else ({}, {"off": "not asked"})
    scope = scope_of(project)
    out = []
    with store.conn:
        for c in cands:
            pick = picks.get(c.id) or {}
            oid = pick.get("option", "").split(".")[-1] if pick.get("option") else c.chosen
            if oid not in {o.id for o in c.options}:
                oid = c.chosen
            title, why = default_text(c, oid)
            if pick.get("title") and pick.get("why"):
                title, why = pick["title"].strip(), pick["why"].strip()
            entry = entry_of(c, oid)
            pid = proposal_id(scope, c.kind, entry)
            row = store.conn.execute("SELECT status FROM proposals WHERE id = ?", (pid,)).fetchone()
            if row and row["status"] != "pending":
                continue
            o = c.option(oid)
            payload = {"kind": c.kind, "entry": entry, "skill": skill_name(scope),
                       "file": "rules/terms.yaml" if c.kind == "terms" else "rules/conventions.yaml",
                       "title": title, "chosen": oid, "rules_chose": c.chosen, "before": c.before, "after": c.after,
                       "template": c.template,
                       "options": [{"id": x.id, "pattern": x.pattern, "says": x.says, "would_change": len(x.would_change),
                                    "examples": x.examples} for x in c.options]}
            evidence = [{"node": x.node, "name": x.name, "before": x.before, "after": x.after, "by": x.by, "at": x.at,
                         "folder": x.f.get("folder", ""), "equipment": x.f.get("equipment"),
                         "template": x.f.get("template"), "role": x.f.get("role"),
                         "description": x.f.get("description", ""), "source": x.f.get("source")} for x in c.fixes]
            checks = {"knowledge_model": "ok", "would_change": len(o.would_change), "examples": o.examples,
                      "would_change_ids": o.would_change, "dropped": c.dropped,
                      "phrased_by": call.get("model") if pick else "rules", "model_call": call}
            store.conn.execute(
                "INSERT INTO proposals (id, project, scope, op, target, payload, why, evidence, lane, checks, status,"
                " model, llm_call) VALUES (?, ?, ?, 'rules.patch', ?, ?, ?, ?, 'approve', ?, 'pending', ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET payload = excluded.payload, why = excluded.why,"
                " evidence = excluded.evidence, checks = excluded.checks, model = excluded.model,"
                " llm_call = excluded.llm_call",
                (pid, project, scope, skill_name(scope), json.dumps(payload), why, json.dumps(evidence),
                 json.dumps(checks), call.get("model") if pick else None, call.get("call") if pick else None))
            out.append(pid)
    return [proposal(store, p) for p in out]


def _row(r) -> dict:
    d = dict(r)
    for k in ("payload", "evidence", "checks"):
        d[k] = json.loads(d[k] or "{}")
    return d


def proposal(store: Store, pid: str) -> dict | None:
    ensure_schema(store)
    r = store.conn.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
    return _row(r) if r else None


def pending(store: Store, project: str | None = None, status: str = "pending") -> list[dict]:
    ensure_schema(store)
    q, args = "SELECT * FROM proposals WHERE status = ?", [status]
    if project:
        q, args = q + " AND project = ?", args + [project]
    return [_row(r) for r in store.conn.execute(q + " ORDER BY created_at, id", args)]


# 4. approve / reject -------------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _skill_md(name: str, scope: str, version: int, rules: list[str], approved_by: str, evidence: list[str],
              entries: list[dict]) -> str:
    front = {"name": name,
             "description": f"Naming conventions people taught by their review fixes on {scope}, approved one by one.",
             "version": version,
             "metadata": {"projectmodel": {"scope": scope, "applies_to": {"step": "mapper and setup"}, "rules": rules,
                                           "status": "active", "locked": False, "method": "curator",
                                           "approved_by": approved_by, "evidence": evidence}}}
    lines = [f"- `{e.get('id')}` {e.get('why', '').strip() or ''} (approved by {e.get('approved_by')}, "
             f"{e.get('approved_at')})" for e in entries]
    body = f"""# Learned conventions: {scope}

## When to use
Every mapper run and guided-setup reading of a project in scope {scope}. The rules in `rules/` are loaded without a
model (conventions.load_layers, conventions.learned_terms); nothing here needs reading by hand.

## Procedure
1. A person fixes the same kind of point at least {MIN_FIXES} times in review.
2. The curator (curator.py) proposes a convention from those fixes; a person approves it in Tribal knowledge.
3. The entry is added here with its id; points it decides carry that id in their provenance (method rule).

## Pitfalls
- A convention never overrides a person's decision: review rows are never replaced by a run.
- A class hint with `instead_of` applies only where the rules would otherwise say that class.

## Verification
`scripts/learning_loop.py` re-runs the mapper and scores the points each convention touched, never the points the
fixes came from.

## Conventions
""" + "\n".join(lines) + "\n"
    return "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n" + body


def approve(store: Store, km: KnowledgeModel, pid: str, by: str, *, knowledge: Path | None = None,
            entry: dict | None = None) -> Path:
    """A person approves proposal `pid` (optionally with an edited entry): it is written to the scope's learned
    conventions skill and checked against the knowledge model before anything is saved. Returns the rules file."""
    from .conventions import ConventionError, Layer, _knowledge_root, apply_conventions

    if not by.strip():
        raise ValueError("an approval needs the approver's name")
    p = proposal(store, pid)
    if p is None:
        raise KeyError(f"no proposal {pid}")
    if p["status"] != "pending":
        raise ValueError(f"proposal {pid} is already {p['status']}")
    pay = p["payload"]
    scope, kind, name = p["scope"], pay["kind"], pay["skill"]
    folder = _knowledge_root(knowledge) / "skills" / scope / name
    rules_path = folder / pay["file"]
    data = (yaml.safe_load(rules_path.read_text()) or {}) if rules_path.exists() else {}
    when = date.today().isoformat()
    e = dict(entry or pay["entry"])
    if kind == "terms":
        if e.get("class") not in km.classes or km.classes[e["class"]].kind != "point":
            raise ValueError(f"{e.get('class')} is not a point class of the knowledge model")
        data.setdefault("terms", {})[e["phrase"]] = e["class"]
        data.setdefault("provenance", {})[e["phrase"]] = {"id": pid, "approved_by": by, "approved_at": when,
                                                         "why": p["why"], "evidence": len(p["evidence"])}
        entries = [{"id": v["id"], "why": f"“{k}” is {data['terms'][k]}. {v.get('why', '')}",
                    "approved_by": v["approved_by"], "approved_at": v["approved_at"]}
                   for k, v in data["provenance"].items()]
    else:
        e |= {"id": pid, "why": p["why"], "approved_by": by, "approved_at": when, "evidence": len(p["evidence"])}
        hints = [h for h in data.get("class_hints") or [] if h.get("id") != pid] + [e]
        data = {"description": f"Learned from review fixes on {scope}; each entry approved by a person.",
                **{k: v for k, v in data.items() if k != "class_hints"}, "class_hints": hints}
        try:
            apply_conventions(km, [Layer(scope, rules_path, {"scope": scope, **data}, name)])
        except ConventionError as err:
            raise ValueError(f"the convention does not check against the knowledge model: {err}") from err
        entries = hints
    md = folder / "SKILL.md"
    old = {}
    if md.exists():
        from .conventions import _skill_front
        old = _skill_front(md)
    pm = ((old.get("metadata") or {}).get("projectmodel")) or {}
    rules = sorted(set(pm.get("rules") or []) | {pay["file"]})
    if kind != "terms" and (folder / "rules/terms.yaml").exists():
        tp = yaml.safe_load((folder / "rules/terms.yaml").read_text()) or {}
        entries = entries + [{"id": v["id"], "why": f"“{k}” is {tp['terms'][k]}.", "approved_by": v["approved_by"],
                              "approved_at": v["approved_at"]} for k, v in (tp.get("provenance") or {}).items()]
    if kind == "terms" and (folder / "rules/conventions.yaml").exists():
        cp = yaml.safe_load((folder / "rules/conventions.yaml").read_text()) or {}
        entries = (cp.get("class_hints") or []) + entries
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120))
    md.write_text(_skill_md(name, scope, int(old.get("version") or 0) + 1, rules, by,
                            sorted(set(pm.get("evidence") or []) | {pid}), entries))
    with store.conn:
        store.conn.execute("UPDATE proposals SET status = 'approved', decided_by = ?, decided_at = ?, payload = ?"
                           " WHERE id = ?", (by, _now(), json.dumps(pay if entry is None else pay | {"entry": entry}),
                                             pid))
    return rules_path


def reject(store: Store, pid: str, by: str, why: str = "") -> None:
    """A person rejects proposal `pid`; the reason is kept (the curator does not propose it again)."""
    p = proposal(store, pid)
    if p is None:
        raise KeyError(f"no proposal {pid}")
    with store.conn:
        store.conn.execute("UPDATE proposals SET status = 'rejected', decided_by = ?, decided_at = ?, reason = ?"
                           " WHERE id = ?", (by, _now(), why, pid))


def learned(knowledge: Path | None = None) -> list[dict]:
    """Every approved learned convention on disk: scope, id, kind, what it says, who approved it."""
    from .conventions import _knowledge_root, entry_text

    out = []
    for f in sorted((_knowledge_root(knowledge) / "skills").glob("*/*/learned-conventions-*/rules/*.yaml")):
        scope = "/".join(f.parts[-5:-3])
        data = yaml.safe_load(f.read_text()) or {}
        for h in data.get("class_hints") or []:
            out.append({"scope": scope, "id": h.get("id", ""), "kind": "class hint", "pattern": h["pattern"],
                        "says": " ".join([h["class"], *([f"on {h['template']}"] if h.get("template") else []),
                                          *([f"instead of {h['instead_of']}"] if h.get("instead_of") else [])]),
                        "approved_by": h.get("approved_by", ""), "approved_at": str(h.get("approved_at", ""))})
        for phrase, cls in (data.get("terms") or {}).items():
            pv = (data.get("provenance") or {}).get(phrase) or {}
            out.append({"scope": scope, "id": pv.get("id", ""), "kind": "setup term", "pattern": phrase,
                        "says": entry_text(cls), "approved_by": pv.get("approved_by", ""),
                        "approved_at": str(pv.get("approved_at", ""))})
    return out
