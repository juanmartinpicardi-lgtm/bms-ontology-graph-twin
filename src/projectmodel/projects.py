"""Projects: one building (site) mapped from one kind of input. A project id is "<site>/<input>".

Each project has its own knowledge graph, review decisions, graphics and tables. The knowledge model and
the shared tribal knowledge (contractor and customer conventions) sit above all projects.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db.store import Store

DEFAULT = "alpha/names_paths"


@dataclass(frozen=True)
class Site:
    name: str
    kind: str
    location: str
    role: str  # dev | test
    source: str


SITES = {
    "alpha": Site("Alpha", "Office · central plant + VAV", "Rolle, Switzerland", "dev",
                  "Project Haystack example site, donated by BuildingFit"),
}

INPUTS = {
    "names_paths": ("Names + folders", "Point names and the equipment folder each sits in, like a Niagara station tree"),
    "names_only": ("Names only", "Point names alone: the hardest case"),
    "documents": ("From documents", "Plans, schedules, sequences, controls submittal and BMS export, read in the "
                                    "guided setup (Projects → Add a building)"),
}


def site_of(project: str) -> Site:
    s = project.split("/")[0]
    if s in SITES:
        return SITES[s]
    from .intake.state import Intake  # a building added in the guided setup
    it = Intake(s)
    if it.s:
        loc = it.location or {}
        return Site(it.name, "Added from its documents", loc.get("address") or it.s.get("address", ""),
                    "dev", "Guided setup" + (" · test package" if it.s.get("test") else ""))
    return Site(s.title(), "", "", "dev", "")


def input_label(project: str) -> str:
    i = project.split("/", 1)[-1]
    return INPUTS.get(i, (i, ""))[0]


def label(project: str) -> str:
    return f"{site_of(project).name} · {input_label(project)}"


def list_projects(store: Store) -> list[str]:
    """By site, then inputs in INPUTS order (richest input first)."""
    order = list(INPUTS)
    projects = [r[0] for r in store.conn.execute("SELECT DISTINCT project FROM nodes")]
    return sorted(projects, key=lambda p: (p.split("/")[0], order.index(p.split("/", 1)[-1])
                                           if p.split("/", 1)[-1] in order else len(order)))


def main_projects(projects: list[str]) -> list[str]:
    """One project per building: its richest input (names + folders before names only). The app shows only these;
    the other inputs stay in the store for the scoring script."""
    seen: dict[str, str] = {}
    for p in projects:  # list_projects puts the richest input first
        seen.setdefault(p.split("/")[0], p)
    return list(seen.values())


def delete_site(store: Store, site: str) -> list[str]:
    """Remove every project (all inputs) of one building from the store: nodes, edges, claims, aliases, runs and notes. The raw
    sources are untouched, so a Haystack site comes back with scripts/run_mapper.py. Returns the projects removed."""
    gone = [p for p in list_projects(store) if p.split("/")[0] == site]
    with store.conn:
        for p in gone:
            for table in ("nodes", "edges", "claims", "aliases", "runs", "notes"):
                store.conn.execute(f"DELETE FROM {table} WHERE project = ?", (p,))
    return gone


def summaries(store: Store) -> dict[str, dict]:
    """Per project: node counts by kind, link counts by relation, last mapper run, human decisions."""
    out: dict[str, dict] = {}

    def row(p):
        return out.setdefault(p, {"nodes": {}, "links": {}, "revision": None, "mapped_at": None, "human": 0})

    for p, kind, n in store.conn.execute("SELECT project, kind, COUNT(*) FROM nodes GROUP BY project, kind"):
        row(p)["nodes"][kind] = n
    for p, rel, n in store.conn.execute(
            "SELECT project, rel, COUNT(*) FROM edges WHERE status != 'rejected' GROUP BY project, rel"):
        row(p)["links"][rel] = n
    for p, rev, at in store.conn.execute("SELECT project, MAX(revision), MAX(started_at) FROM runs GROUP BY project"):
        if p in out:
            out[p].update(revision=rev, mapped_at=at)
    for p, n in store.conn.execute(
            "SELECT project, SUM(n) FROM (SELECT project, COUNT(*) n FROM nodes WHERE method = 'human' GROUP BY project"
            " UNION ALL SELECT project, COUNT(*) FROM edges WHERE method = 'human' GROUP BY project) GROUP BY project"):
        if p in out:
            out[p]["human"] = n
    return out
