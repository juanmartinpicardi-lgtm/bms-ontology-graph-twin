"""Context engine (spec-agent §4): what the person is looking at, as chips, and the small packet the agent gets.

Built by rules, deterministic and cheap: no model decides what the context is.

    state = ScreenState(page="Equipment_3D", project="alpha/names_paths")
    state.focus = Ref("equipment", "eq:Airside VAV-1-23", "VAV-1-23")
    chips = chips_for(state)                       # what the dock shows (the person can drop or pin each)
    packet = context_packet(chips, state, tools)   # what the agent gets: ids, labels, short summaries

A chip's key is stable for the same thing, so dropping a chip drops that thing (a new selection is a new chip).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Levels from general to specific (spec-agent §4.2); the packet's level is the most specific chip's.
LEVELS = ("general", "project", "review", "setup", "document", "floor", "room", "equipment", "point")
KIND_LEVEL = {"project": "project", "review": "review", "setup": "setup", "document": "document", "floor": "floor",
              "room": "room", "location": "room", "zone": "room", "equipment": "equipment", "point": "point",
              "scenario": "equipment"}
KIND_ICON = {"project": "apartment", "floor": "layers", "room": "meeting_room", "location": "meeting_room",
             "zone": "meeting_room", "equipment": "hvac", "point": "sensors", "document": "description",
             "setup": "add_business", "review": "fact_check", "scenario": "science"}


@dataclass(frozen=True)
class Ref:
    kind: str     # project | floor | room | equipment | point | document | setup | review | scenario
    id: str
    label: str


@dataclass
class ScreenState:
    """Published by the page on every run (spec-agent §4.1)."""
    page: str = ""                    # url path of the page, e.g. "Equipment_3D"
    title: str = ""                   # the page's title, e.g. "Equipment 3D"
    project: str | None = None        # "alpha/names_paths" on project pages
    project_label: str = ""
    focus: Ref | None = None          # the one thing the page is about (the equipment on Equipment 3D...)
    selection: list[Ref] = field(default_factory=list)
    floor: Ref | None = None
    scenario: Ref | None = None
    document: Ref | None = None
    setup_step: Ref | None = None
    view: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Chip:
    kind: str
    id: str
    label: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def icon(self) -> str:
        return KIND_ICON.get(self.kind, "label")

    @property
    def level(self) -> str:
        return KIND_LEVEL.get(self.kind, "general")


def chips_for(state: ScreenState) -> list[Chip]:
    """Chips from general to specific: project, setup step, document, floor, focus, selection, scenario."""
    out: list[Chip] = []
    if state.project:
        out.append(Chip("project", state.project, state.project_label or state.project))
    for ref in (state.setup_step, state.document, state.floor, state.focus, *state.selection, state.scenario):
        if ref is not None:
            c = Chip(ref.kind, ref.id, ref.label)
            if c not in out:
                out.append(c)
    return out


def merge_chips(page_chips: list[Chip], pinned: list[Chip], dropped: set[str]) -> list[Chip]:
    """What the agent will use: the page's chips minus the dropped ones, plus the pinned ones (kept across pages)."""
    out = [c for c in page_chips if c.key not in dropped]
    out += [c for c in pinned if c not in out]
    return out


def level_of(chips: list[Chip]) -> str:
    return max((c.level for c in chips), key=LEVELS.index, default="general")


def context_packet(chips: list[Chip], state: ScreenState, tools: Any = None, summary: dict | None = None) -> dict:
    """The agent's context for one turn: small (ids, labels, short summaries; a few hundred tokens). `tools` is the
    project's GraphTools when there is one, used to add each node's class, trust and links; `summary` the project's
    sizes. Anything more the agent fetches with tools."""
    packet: dict[str, Any] = {"page": state.title or state.page, "level": level_of(chips)}
    project = next((c for c in chips if c.kind == "project"), None)
    if project:
        packet["project"] = {"id": project.id, "name": project.label, **(summary or {})}
    things = []
    for c in chips:
        if c.kind == "project":
            continue
        item: dict[str, Any] = {"kind": c.kind, "id": c.id, "label": c.label}
        if tools is not None and c.kind in ("equipment", "point", "room", "location", "zone"):
            item.update(_node_summary(tools, c.id))
        things.append(item)
    if things:
        packet["looking_at"] = things
    if state.view:
        packet["view"] = state.view
    return packet


def _node_summary(tools: Any, node_id: str) -> dict:
    try:
        d = tools.describe(node_id)
    except KeyError:
        return {"note": "not in this project's graph"}
    out = {"class": d.get("class"), "trust": d.get("trust")}
    if d.get("kind") == "point":
        out["equipment"] = (d.get("equipment") or {}).get("name")
        out["role"] = d.get("role")
    else:
        out["points"] = len(d.get("points", []))
        out["fed_by"] = [x["name"] for x in d.get("fed_by", [])][:3]
        out["feeds"] = len(d.get("feeds", []))
        if d.get("missing_required_points"):
            out["missing_required_points"] = d["missing_required_points"][:5]
    return {k: v for k, v in out.items() if v not in (None, [], "")}
