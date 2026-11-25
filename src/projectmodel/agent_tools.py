"""Agent tools: the knowledge graph as a small set of read-only functions an agent can call.

An agent should not read SQLite or guess node ids. It calls:
  find_nodes     search equipment and points by name words and class
  describe       one node with everything around it: class, parts, points with their template role, what feeds it,
                 required points that are missing
  upstream       what a node depends on, following feeds links backwards (VAV <- AHU <- chilled water plant)
  downstream     what a node affects, following feeds links forwards
  behaviour      control loops, interlocks, resets and requests the sequences of operation state for a node
  source_page    where a fact was read: file, page, sheet and box (the dock shows the page crop)
  read_sequence  the sequence sections that apply to a unit, and the control relations published from them
  run_check      SHACL rules (W2), missing template points, unbound or loose points, a class that does not fit the
                 point's input or output, and sources that disagree (W3)
  show_graphic   the unit's graphic: W9's 2D + 3D graphic with its QA (graphics.graphic_ref), else Equipment 3D
  diagnose       "does it run as designed?": the rules gather the evidence step by step (sequence, loops, interlocks,
                 setpoints against the BMS and the schedule, checks, gaps) and say "unknown" where the graph has no data

Every fact comes back with `trust`, so the agent can tell a checked fact from a guess:
  verified  a person decided it (method human, or confirmed by a person)
  agreed    two or more independent sources state it (confirmed_by agreement, db/store.py)
  stated    a project document says so (method document): intent, not confirmed as built
  accepted  one source, confirmed by the auto-accept rule (confirmed_by auto): high confidence, nobody looked
  likely    proposed, with confidence >= LIKELY
  unsure    proposed, with lower confidence
`likely` and `accepted` rest on confidences that are calibrated per job (calibration.py), not on a person.

Every fact also comes back with a citation id (`cite`, or a node's `id`), which the agent writes as [[id]] and the
dock and the scorer resolve (`GraphTools.resolve`):
  unit:AHU1, pt:<ref> ...            graph nodes
  rel:<src>|<rel>|<dst>              a graph edge (a feeds link, a sequence's control relation)
  src:<file>#p<page>, #r<row>        a page (from 1) or row of a project document (agent/documents.py)
  seq:<sequence>[/<section>]         a sequence of operation, one of its sections
  issue:<id>                         a gap or conflict a reader raised
  check:<kind>[.<detail>]|<node>     a check result (shacl.<Rule>, template, binding, class, conflict, setpoint.<section>,
                                     live)
  graphic:<node>                     the unit's graphic

TOOLS holds the tool definitions (name, description, JSON schema), `call` runs one by name with JSON arguments and
returns JSON-ready data, so any LLM provider's tool loop can use them. Nothing here writes to the graph: a change
goes through a proposal a person confirms (spec-agent §9).
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable

from .db.store import Store
from .equipment_view import assign_slots
from .knowledge_model import CONTROL_RELATIONS, KnowledgeModel
from .tree import UNPLACED, TreeNode, build_tree, provenance

LIKELY = 0.8  # the score report's confidence threshold
TRUST_WORDS = ("verified", "agreed", "stated", "accepted", "likely", "unsure")
OUTPUT_IO = {"AO", "BO", "MO"}
INPUT_IO = {"AI", "BI", "MI"}
VALUE = re.compile(r"(?P<v>[-+]?\d+(?:\.\d+)?)\s*(?P<u>°\s*F|deg(?:rees)?\s*F|%\s*RH|in\.?\s*w\.?c\.?|”\s*wc|cfm|gpm|%)",
                   re.I)
TOLERANCE = {"°F": 0.6, "%RH": 1.0, "%": 1.0, "in.wc": 0.005, "cfm": 10.0, "gpm": 2.0}
# Schedule columns a sequence value can be checked against: (words in the loop's measured point, unit) -> attrs
SCHEDULE_FIELDS = [
    (("supply", "discharge"), "°F", ("cooling_lat", "lat_f", "lat")),
    (("leaving", "chilled"), "°F", ("lwt_f", "chw_lwt")),
    (("supply air", "airflow", "flow"), "cfm", ("supply_cfm", "cooling_cfm")),
]


def trust(prov: dict) -> str:
    if prov.get("method") == "human" or prov.get("confirmed_by") == "human":
        return "verified"
    if prov.get("confirmed_by") == "agreement" or len(prov.get("agree") or []) > 1:
        return "agreed"
    if prov.get("method") == "document":
        return "stated"
    if prov.get("confirmed_by") == "auto" and prov.get("status") == "confirmed":
        return "accepted"
    return "likely" if (prov.get("confidence") or 0) >= LIKELY else "unsure"


def rel_cite(src: str, rel: str, dst: str) -> str:
    return f"rel:{src}|{rel}|{dst}"


def check_cite(kind: str, node: str) -> str:
    return f"check:{kind}|{node}"


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _unit(u: str) -> str:
    u = u.lower().replace(" ", "")
    if "f" in u and ("°" in u or "deg" in u):
        return "°F"
    if "rh" in u:
        return "%RH"
    if "wc" in u or "”" in u:
        return "in.wc"
    return {"cfm": "cfm", "gpm": "gpm", "%": "%"}.get(u, u)


def values_in(text: str) -> list[tuple[float, str]]:
    return [(float(m.group("v")), _unit(m.group("u"))) for m in VALUE.finditer(text or "")]


# Graphic providers: each takes (tools, equipment node) and returns a graphic reference or None. W9's graphics module
# registers its own first; Equipment 3D (equipment_view.py) is the fallback that exists today.
GRAPHIC_PROVIDERS: list[Callable[["GraphTools", TreeNode], dict | None]] = []


class GraphTools:
    def __init__(self, store: Store, km: KnowledgeModel, project: str, docs=None):
        self.store, self.km, self.project = store, km, project
        self.tree = build_tree(store, project)
        self.rows = {r["id"]: r for r in store.nodes(project)}
        self.live_edges = [e for e in store.edges(project) if e["status"] != "rejected"]
        self.feeds = [(e["src"], e["dst"], json.loads(e["attrs"]).get("medium"), provenance(e))
                      for e in self.live_edges if e["rel"] == "feeds"]
        self.document_edges = [e for e in self.live_edges if e["method"] == "document"]
        self.control_edges = [e for e in self.live_edges if e["rel"] in CONTROL_RELATIONS]
        self.edge_by_key = {(e["src"], e["rel"], e["dst"]): e for e in store.edges(project)}
        self._docs = docs
        self._roles: dict[str, tuple[dict, list]] = {}
        self._shacl: dict | None = None
        self.issued: dict[str, dict] = {}   # every citation a tool returned in this session, with what it shows

    # helpers -----------------------------------------------------------------------------------

    @property
    def docs(self):
        if self._docs is None:
            from .agent.documents import DocumentIndex
            self._docs = DocumentIndex.for_project(self.project)
        return self._docs

    def _issue(self, cite: str, **what) -> str:
        self.issued.setdefault(cite, {}).update({k: v for k, v in what.items() if v is not None})
        return cite

    def _get(self, node_id: str) -> TreeNode:
        n = self.tree.by_id.get(node_id)
        if n is None or node_id == UNPLACED:
            raise KeyError(f"no node {node_id!r} in {self.project}; use find_nodes to get ids")
        return n

    def _equipment_of(self, n: TreeNode) -> TreeNode | None:
        return n if n.kind == "equipment" else self.tree.by_id.get(self.tree.parent.get(n.id, ""))

    def _label(self, node_id: str) -> str:
        if n := self.tree.by_id.get(node_id):
            return n.label
        r = self.rows.get(node_id)
        return r["label"] if r is not None else node_id

    def _brief(self, n: TreeNode) -> dict:
        out = {"id": n.id, "kind": n.kind, "name": n.label, "class": n.cls, "trust": trust(n.prov),
               "confidence": n.prov.get("confidence")}
        if n.kind == "point" and (eq := self._equipment_of(n)):
            out["equipment"] = {"id": eq.id, "name": eq.label}
        return out

    def _is_a(self, cls: str | None, want: str) -> bool:
        return bool(cls) and (cls == want or (cls in self.km.classes and want in self.km.classes
                                              and self.km.is_a(cls, want)))

    def _points(self, eq: TreeNode) -> list[tuple[TreeNode, str | None]]:
        """The equipment's points, with those of its parts that are not equipment in their own right (a fan's VFD
        folder), each with the part's name as context."""
        out = [(p, None) for p in eq.points]
        for c in eq.children:
            if not c.attrs.get("template"):
                out += [(p, c.label) for p in c.points]
        return [(p, ctx) for p, ctx in out if p.prov.get("status") != "rejected"]

    def _slot_roles(self, eq: TreeNode) -> tuple[dict[str, str], list[str]]:
        """point id -> template slot role, and the required roles no point fills."""
        if eq.id not in self._roles:
            t = self.km.templates.get(eq.attrs.get("template") or "")
            roles, missing = {}, []
            if t:
                slots, _ = assign_slots(t, [{"id": p.id, "label": p.label, "cls": p.cls, "context": ctx}
                                            for p, ctx in self._points(eq)], self.km)
                roles = {pid: role for role, pids in slots.items() for pid in pids}
                missing = [s.role for s in t.slots if s.required and not slots.get(s.role)]
            self._roles[eq.id] = (roles, missing)
        return self._roles[eq.id]

    def _link(self, other: str, medium: str | None, prov: dict) -> dict:
        n = self.tree.by_id[other]
        return {"id": n.id, "name": n.label, "class": n.cls, "medium": medium, "trust": trust(prov),
                "confidence": prov.get("confidence")}

    def _unit_and_ids(self, node_id: str) -> tuple[TreeNode, set[str]]:
        n = self._get(node_id)
        eq = self._equipment_of(n) or n
        return eq, {eq.id} | {p.id for p, _ in self._points(eq)}

    # tools: the graph ------------------------------------------------------------------------------------------

    def find_nodes(self, query: str = "", cls: str = "", kind: str = "", limit: int = 20) -> dict:
        words = query.lower().split()
        compact = "".join(ch for ch in query.lower() if ch.isalnum())
        hits, loose = [], []
        for n in self.tree.by_id.values():
            if n.id == UNPLACED or (kind and n.kind != kind) or (cls and not self._is_a(n.cls, cls)):
                continue
            eq = self._equipment_of(n)
            text = f"{n.label} {eq.label if eq and eq is not n else ''}".lower()
            if all(w in text for w in words):
                hits.append(n)
            elif compact and compact in "".join(ch for ch in text if ch.isalnum()):
                loose.append(n)  # the same name with other separators: "VAV-1-2-14" for "VAV 1-2-14", "AHU-1" for "AHU01"
        if not hits and not loose and compact:
            # "AHU-1" for the tag AHU01: the same letters and number, leading zeros aside
            key = re.sub(r"(?<=[a-z])0+(?=\d)", "", compact)
            loose = [n for n in self.tree.by_id.values() if n.id != UNPLACED and (not kind or n.kind == kind)
                     and re.sub(r"(?<=[a-z])0+(?=\d)", "", "".join(ch for ch in n.label.lower() if ch.isalnum())) == key]
        hits = hits or loose
        hits.sort(key=lambda n: (n.kind != "equipment", len(n.label), n.label))
        return {"total": len(hits), "nodes": [self._brief(n) for n in hits[:limit]]}

    def describe(self, node_id: str) -> dict:
        n = self._get(node_id)
        out = self._brief(n) | {"source": {k: n.prov.get(k) for k in ("source_file", "source_ref", "method", "revision")}}
        if (src := self._source_of_row(n.prov, n.id, n.attrs)) is not None:
            out["source"]["cite"] = src["cite"]
        if n.prov.get("sources"):
            out["stated_by"] = n.prov["sources"]
        if n.kind == "point":
            eq = self._equipment_of(n)
            out["role"] = self._slot_roles(eq)[0].get(n.id) if eq else None
            out["other_candidate_classes"] = [c for c, _ in n.attrs.get("alternatives", []) if c != n.cls][:3]
            for k in ("description", "io", "units"):
                if n.attrs.get(k):
                    out[k] = n.attrs[k]
            out["behaviour"] = self.behaviour(node_id)["facts"]
            return out
        roles, missing = self._slot_roles(n)
        parent = self.tree.by_id.get(self.tree.parent.get(n.id, ""))
        out |= {
            "template": n.attrs.get("template"),
            "part_of": {"id": parent.id, "name": parent.label, "class": parent.cls} if parent else None,
            "parts": [self._brief(c) for c in n.children],
            "fed_by": [self._link(s, m, p) for s, d, m, p in self.feeds if d == n.id],
            "feeds": [self._link(d, m, p) for s, d, m, p in self.feeds if s == n.id],
            "points": [self._brief(p) | {"role": roles.get(p.id), "on_part": ctx} for p, ctx in self._points(n)],
            "missing_required_points": missing,
        }
        skip = {"sources", "agree", "agree_confidence", "conflict", "alternatives", "controller", "points"}
        if data := {k: v for k, v in n.attrs.items() if k not in skip and v not in (None, "", [], {})}:
            out["data"] = data  # what the schedules and the setup stated about the unit (nameplate, tag, sequence)
        for p in out["points"]:
            del p["equipment"], p["kind"]
        return out

    def _walk(self, node_id: str, forward: bool, medium: str) -> dict:
        start = self._equipment_of(self._get(node_id))
        if start is None:
            return {"from": node_id, "nodes": []}
        seen, out, queue = {start.id}, [], deque([(start.id, 0)])
        while queue:
            cur, depth = queue.popleft()
            for s, d, m, prov in self.feeds:
                here, other = (s, d) if forward else (d, s)
                if here != cur or other in seen or (medium and m != medium):
                    continue
                seen.add(other)
                out.append(self._link(other, m, prov) | {"steps": depth + 1, "via": cur,
                                                         "cite": rel_cite(s, "feeds", d)})
                queue.append((other, depth + 1))
        return {"from": {"id": start.id, "name": start.label}, "total": len(out), "nodes": out}

    def upstream(self, node_id: str, medium: str = "") -> dict:
        return self._walk(node_id, False, medium)

    def downstream(self, node_id: str, medium: str = "") -> dict:
        return self._walk(node_id, True, medium)

    def _relation(self, e) -> dict:
        attrs = json.loads(e["attrs"])
        prov = provenance(e)
        end = lambda i: {"id": i, "name": self._label(i)}  # noqa: E731
        out = {"cite": rel_cite(e["src"], e["rel"], e["dst"]), "relation": e["rel"], "from": end(e["src"]),
               "to": end(e["dst"]), "says": f"{self._label(e['src'])} {e['rel']} {self._label(e['dst'])}",
               "trust": trust(prov), "status": e["status"]}
        if e["method"] == "document":
            out["trust"] = "stated"
        if attrs.get("loop"):
            out["loop"] = attrs["loop"]
        if attrs.get("kind"):
            out["kind"] = attrs["kind"]
        seq = (attrs.get("sequence") or "").split(":", 1)[-1]
        if seq and attrs.get("section"):
            out["section"] = attrs["section"]
            out["section_cite"] = f"seq:{seq}/{attrs['section']}"
        elif attrs.get("sequences"):
            out["sequences"] = attrs["sequences"]
        if attrs.get("model"):
            out["read_by"] = attrs["model"]
        if attrs.get("why"):
            out["why"] = attrs["why"][:160]
        if attrs.get("conflict"):
            out["conflict"] = "the sequence implies another class for: " + ", ".join(map(str, attrs["conflict"]))
        return out

    def behaviour(self, node_id: str) -> dict:
        n = self._get(node_id)
        ids = {n.id} | ({p.id for p, _ in self._points(n)} if n.kind == "equipment" else set())
        facts = []
        for e in self.control_edges:
            if e["src"] not in ids and e["dst"] not in ids:
                continue
            r = self._relation(e)
            fact = {"relation": r["relation"], "from": r["from"], "to": r["to"], "loop": r.get("loop"),
                    "sequences": r.get("sequences") or ([r["section_cite"]] if r.get("section_cite") else []),
                    "source": f"{provenance(e)['source_file']} · {e['source_ref']}", "trust": r["trust"],
                    "cite": r["cite"]}
            if r.get("conflict"):
                fact["conflict"] = r["conflict"]
            facts.append(fact)
        note = None if facts else "No sequence of operations covers this node yet."
        return {"node": {"id": n.id, "name": n.label}, "facts": facts, "note": note}

    # tools: documents ----------------------------------------------------------------------------------------

    def _source_of_row(self, prov: dict, node_id: str | None, attrs: dict) -> dict | None:
        from .agent.documents import parse_ref, src_cite
        file = prov.get("source_file") or ""
        if not file or file in ("guided setup", "sequences"):
            return None
        ref = parse_ref(prov.get("source_ref") or "")
        name = file.split("/")[-1]
        page, row = ref.get("page"), ref.get("row")
        bbox = self.docs.box_for(node_id, attrs, name, page) if node_id and page else None
        cite = src_cite(name, page, row)
        self._issue(cite, kind="page", file=name, page=page, row=row, sheet=ref.get("sheet"))
        if bbox:
            self.issued[cite].setdefault("boxes", [])
            if bbox not in self.issued[cite]["boxes"]:
                self.issued[cite]["boxes"].append(bbox)
        return {"cite": cite, "file": name, "page": page, "row": row, "sheet": ref.get("sheet"), "bbox": bbox}

    def source_page(self, ref: str) -> dict:
        """Where a fact was read. `ref`: a node id, a rel:/seq:/issue: citation, or a src: page citation."""
        from .agent.documents import parse_src_cite, src_cite
        out: dict
        if ref.startswith("src:"):
            p = parse_src_cite(ref)
            if p is None:
                raise KeyError(f"not a page citation: {ref!r}")
            out = {"cite": ref, "file": p["file"], "page": p["page"], "row": p["row"], "bbox": None}
            self._issue(ref, kind="page", file=p["file"], page=p["page"], row=p["row"])
        elif ref.startswith("seq:"):
            sid, _, letter = ref[4:].partition("/")
            seq = self.docs.sequence(sid)
            if seq is None:
                raise KeyError(f"no sequence {sid!r}; read_sequence lists them")
            sec = seq.section(letter) if letter else None
            if letter and sec is None:
                raise KeyError(f"sequence {sid!r} has no section {letter!r}")
            bbox = (sec or {}).get("bbox") or seq.bbox
            cite = src_cite(seq.file, seq.page)
            self._issue(cite, kind="page", file=seq.file, page=seq.page, sheet=seq.sheet)
            self.issued[cite].setdefault("boxes", []).append(bbox)
            out = {"cite": cite, "of": ref, "file": seq.file, "page": seq.page, "sheet": seq.sheet, "bbox": bbox,
                   "text": (sec["text"] if sec else "")[:1200] or None}
        elif ref.startswith("issue:"):
            i = self.docs.issue(ref)
            if i is None:
                raise KeyError(f"no issue {ref!r}")
            s = i.get("src") or {}
            page = s["page"] + 1 if s.get("page") is not None else None
            cite = src_cite(s.get("file", ""), page)
            self._issue(cite, kind="page", file=s.get("file"), page=page, sheet=s.get("sheet"))
            out = {"cite": cite, "of": ref, "file": s.get("file"), "page": page, "sheet": s.get("sheet"),
                   "bbox": s.get("bbox"), "text": i["text"]}
        elif ref.startswith("rel:"):
            src, rel, dst = ref[4:].split("|")
            e = self.edge_by_key.get((src, rel, dst))
            if e is None:
                raise KeyError(f"no relation {ref!r}")
            out = self._source_of_row(provenance(e), None, {}) or {"cite": None}
            attrs = json.loads(e["attrs"])
            seq = self.docs.sequence((attrs.get("sequence") or "").split(":", 1)[-1])
            if seq and (sec := seq.section(attrs.get("section") or "")):
                out["bbox"] = sec["bbox"]
                self.issued[out["cite"]].setdefault("boxes", []).append(sec["bbox"])
                out["section_cite"] = f"seq:{seq.id}/{sec['letter']}"
            out["of"] = ref
        else:
            r = self.rows.get(ref)
            if r is None:
                raise KeyError(f"no node {ref!r} in {self.project}; use find_nodes to get ids")
            attrs = json.loads(r["attrs"])
            out = self._source_of_row(provenance(r), ref, attrs) or {"cite": None, "note": "no document behind it"}
            out["of"] = ref
            claims = self.store.conn.execute(
                "SELECT source, source_file, source_ref, value FROM claims WHERE project = ? AND src = ? AND rel = ''",
                (self.project, ref)).fetchall()
            also = []
            for c in claims:
                s = self._source_of_row({"source_file": c["source_file"], "source_ref": c["source_ref"]}, ref, attrs)
                if s and s["cite"] != out.get("cite"):
                    also.append({"source": c["source"], "cite": s["cite"], "sheet": s["sheet"], "says": c["value"]})
            if also:
                out["also_stated_in"] = also
        out["found"] = bool(out.get("file") and self.docs.path(out["file"]))
        if out.get("cite") and out["found"] and out.get("page"):
            out["preview"] = "the dock shows this page, with the box drawn, when you cite " + out["cite"]
        return out

    def read_sequence(self, node_id: str, section: str = "") -> dict:
        """The sequences that apply to the unit (or the point's unit), and the control relations on its points."""
        eq, ids = self._unit_and_ids(node_id)
        tag, title = _norm(eq.attrs.get("tag") or eq.label), (eq.attrs.get("sequence") or "").lower()
        rels = [self._relation(e) for e in self.control_edges if e["src"] in ids or e["dst"] in ids]
        # a system (CHW-PLANT) follows the sequence that names every one of its parts (chillers, pumps)
        parts = {_norm(c.attrs.get("tag") or c.label) for c in eq.children if c.kind == "equipment"}
        mine = [s for s in self.docs.sequences()
                if tag in (names := {_norm(t) for t in s.applies_to}) or (title and s.title.lower() == title)
                or (parts and parts <= names)]
        related_ids = {r["section_cite"].split("/")[0][4:] for r in rels if r.get("section_cite")} - {s.id for s in mine}
        related = [s for s in self.docs.sequences() if s.id in related_ids]
        seqs = []
        for s, applies in [(s, True) for s in mine] + [(s, False) for s in related]:
            from .agent.documents import src_cite
            page = src_cite(s.file, s.page)
            self._issue(page, kind="page", file=s.file, page=s.page, sheet=s.sheet)
            self._issue(s.cite, kind="sequence", label=s.title, file=s.file, page=s.page, sheet=s.sheet, bbox=s.bbox)
            secs = []
            for x in s.sections:
                c = self._issue(f"{s.cite}/{x['letter']}", kind="section", label=f"{s.title} {x['letter']}. {x['title']}",
                                text=x["text"], file=s.file, page=s.page, sheet=s.sheet, bbox=x.get("bbox"))
                item = {"cite": c, "letter": x["letter"], "title": x["title"],
                        "setpoints": [f"{p['value']:g} {p['unit']}" for p in s.setpoints if p["section"] == x["letter"]]}
                if (section and x["letter"] == section) or (applies and not section and len(s.sections) <= 4):
                    item["text"] = " ".join(x["text"].split())[:900]
                secs.append(item)
            entry = {"cite": s.cite, "title": s.title, "applies_to_unit": applies, "source": page, "sheet": s.sheet,
                     "units": len(s.applies_to), "sections": secs}
            if applies and s.issues:
                entry["issues"] = [{"cite": self._issue(i["id"], kind="issue", text=i["text"], src=i.get("src")),
                                    "kind": i["kind"], "text": i["text"][:260], "by": i["by"]} for i in s.issues]
            seqs.append(entry)
        if section:
            rels = [r for r in rels if r.get("section") == section]
        out = {"unit": {"id": eq.id, "name": eq.label}, "sequences": seqs,
               "relations": [{k: r[k] for k in ("cite", "says", "kind", "loop", "section", "trust", "status")
                              if r.get(k) is not None} for r in rels]}
        if not seqs:
            out["note"] = "No sequence of operations in this project's documents names this unit."
        if not rels:
            out["note_relations"] = ("No control relations are published for this unit: the sequences' logic is read "
                                     "by the sequence_read job, which did not run for this building (PM_AI off).")
        elif any(r.get("read_by") for r in rels):
            out["relations_read_by"] = sorted({r["read_by"] for r in rels if r.get("read_by")})
            out["relations_note"] = "Proposed until a person confirms the logic: read by a model from the sections cited."
        return out

    # tools: checks -------------------------------------------------------------------------------------------

    def _shacl_failures(self) -> dict:
        """{node id: [{rule, label, severity, messages}]}, from validating the graph (confirmed and proposed rows) with
        W2's export and rules; cached for this session. Falls back to the saved report when validation can't run."""
        if self._shacl is None:
            fails: dict[str, list] = {}
            meta = {"scope": "confirmed + proposed"}
            try:
                from .export import shacl
                from .export.brick import export_project
                keep, shacl.FIRST_FAILING = shacl.FIRST_FAILING, 10 ** 6
                try:
                    rep = shacl.validate(export_project(self.store, self.project, self.km, include_proposed=True),
                                         self.km)
                finally:
                    shacl.FIRST_FAILING = keep
                meta["rules"] = len([r for r in rep["rules"] if r["origin"] == "building"])
            except Exception as e:  # noqa: BLE001 - no engine here: the saved report (first failing nodes only)
                from .export.run import load_reports
                rep = next((s.get("with_proposed") or s.get("confirmed") for d in load_reports().values()
                            if d.get("project") == self.project for s in [d["scopes"]]), None)
                meta = {"scope": "saved report (first 25 failing nodes per rule)", "why": str(e)[:200]}
                if rep is None:
                    self._shacl = {"meta": meta | {"none": True}, "fails": {}}
                    return self._shacl
            for r in rep["rules"]:
                if r["origin"] != "building" and r["severity"] != "violation":
                    continue
                for f in r["failing"]:
                    fails.setdefault(f["id"], []).append({"rule": r["id"].split(":", 1)[-1], "label": r["label"],
                                                          "severity": r["severity"], "messages": f["messages"][:2]})
            self._shacl = {"meta": meta, "fails": fails}
        return self._shacl

    def _binding(self, pid: str) -> dict:
        """Is the point bound: on an equipment, hosted by a controller, a BACnet object of the BMS."""
        r = self.rows[pid]
        attrs = json.loads(r["attrs"])
        on = [e["src"] for e in self.live_edges if e["rel"] == "hasPoint" and e["dst"] == pid]
        host = [e["dst"] for e in self.live_edges if e["rel"] == "isHostedBy" and e["src"] == pid]
        bac = attrs.get("bacnet") or {}
        missing = ([] if on else ["no equipment"]) + ([] if host else ["no controller"]) + \
                  ([] if bac or "setup:bms" in (attrs.get("sources") or []) else ["no BMS object"])
        return {"equipment": on[0] if on else None, "controller": host[0] if host else None,
                "object": f"{bac.get('object_type')} {bac.get('object_instance')} on device {bac.get('device_instance')}"
                if bac else None, "missing": missing}

    def _class_fit(self, pid: str) -> str | None:
        """Why the point's class does not fit what it is (an output classed as a sensor), or None."""
        r = self.rows[pid]
        attrs = json.loads(r["attrs"])
        io, cls = (attrs.get("io") or "").upper(), r["class"] or ""
        if io in OUTPUT_IO and (cls.endswith("Sensor") or cls.endswith("Status") or cls == "Sensor"):
            return f"an output ({io}) classed as {cls}"
        if io in INPUT_IO and (cls.endswith("Command") or cls.endswith("Setpoint")):
            return f"an input ({io}) classed as {cls}"
        return None

    def _loose_points(self, eq: TreeNode) -> list[str]:
        """Points of the unit's own BMS device that sit on no equipment (EF-LAB-1-S for EF-LAB)."""
        tag = _norm(eq.attrs.get("tag") or eq.label)
        dev = _norm(eq.attrs.get("bms_device") or "")
        on = {e["dst"] for e in self.live_edges if e["rel"] == "hasPoint"}
        out = []
        for pid, r in self.rows.items():
            if r["kind"] != "point" or pid in on or r["status"] == "rejected":
                continue
            d = _norm(json.loads(r["attrs"]).get("device") or "")
            if d and (d == dev or (tag and d.startswith(tag) and d[len(tag):].isdigit())):
                out.append(pid)
        return out

    def run_check(self, node_id: str, checks: list[str] | None = None) -> dict:
        """Check results for the unit (or point) and its points. checks: shacl, template, binding, class, conflicts."""
        want = set(checks or ["shacl", "template", "binding", "class", "conflicts"])
        n = self._get(node_id)
        eq = n if n.kind == "equipment" else None
        pts = [p.id for p, _ in self._points(eq)] if eq else [n.id]
        loose = self._loose_points(eq) if eq else []
        results, summary = [], {}

        def add(kind: str, node: str, ok: bool, message: str, **extra) -> None:
            c = self._issue(check_cite(kind, node), kind="check", status="pass" if ok else "fail", text=message,
                            label=self._label(node))
            summary.setdefault(kind.split(".")[0], {"pass": 0, "fail": 0})["pass" if ok else "fail"] += 1
            if not ok or node == (eq.id if eq else n.id):
                results.append({"cite": c, "check": kind, "node": {"id": node, "name": self._label(node)},
                                "status": "pass" if ok else "fail", "message": message, **extra})

        if "shacl" in want:
            sh = self._shacl_failures()
            for node in [n.id, *([p for p in pts if p != n.id]), *loose]:
                for f in sh["fails"].get(node, []):
                    add(f"shacl.{f['rule']}", node, False, f"{f['label']}: {'; '.join(f['messages'])}"[:300],
                        severity=f["severity"])
            if not any(r["check"].startswith("shacl") for r in results):
                add("shacl", n.id, True, f"No SHACL building rule fails on {n.label} or its points "
                                         f"({sh['meta']['scope']}).")
        if "template" in want and eq:
            roles, missing = self._slot_roles(eq)
            t = eq.attrs.get("template")
            add("template", eq.id, not missing,
                f"Every required point of the {t} template is there." if t and not missing else
                f"Required points of the {t} template with no point: {', '.join(missing)}." if t else
                "No template for this unit: required points are not checked.")
        if "binding" in want:
            bad = []
            for pid in pts:
                b = self._binding(pid)
                if b["missing"]:
                    bad.append(pid)
                    add("binding", pid, False, f"{self._label(pid)} is not bound: {', '.join(b['missing'])}.")
            for pid in loose:
                add("binding", pid, False, f"{self._label(pid)} is a point of {eq.label}'s BMS device "
                                           f"({json.loads(self.rows[pid]['attrs']).get('device')}) but on no equipment.")
            if eq:
                hosts = sorted({b for p in pts if (b := self._binding(p)["controller"])})
                add("binding", eq.id, not bad and not loose,
                    f"{len(pts) - len(bad)} of {len(pts)} points are on {eq.label}, hosted by a controller "
                    f"({', '.join(self._label(h) for h in hosts) or 'none'}) and are BMS objects"
                    + (f"; {len(loose)} points of its BMS device are on no equipment." if loose else "."),
                    controllers=hosts)
        if "class" in want:
            for pid in pts:
                if why := self._class_fit(pid):
                    r = self.rows[pid]
                    add("class", pid, False, f"{r['label']} is {why} (confidence {r['confidence']:.2f}, "
                                             f"{trust(provenance(r))}).")
            if eq and not any(r["check"] == "class" for r in results):
                add("class", eq.id, True, "Every point's class fits its input or output type.")
        if "conflicts" in want:
            ids = {n.id, *pts}
            found = False
            for node in ids:
                c = json.loads(self.rows[node]["attrs"]).get("conflict")
                if c:
                    found = True
                    add("conflict", node, False, f"Sources disagree on {self._label(node)}'s class: "
                        + "; ".join(f"{x['source']} says {x.get('class')}" for x in c))
            for e in self.live_edges:
                if (e["src"] in ids or e["dst"] in ids) and (c := json.loads(e["attrs"]).get("conflict")):
                    found = True
                    other = "; ".join(f"{x['source']} ({x.get('source_file')}, {x.get('source_ref')}) says "
                                      f"{self._label(x.get('dst') or '')}" for x in c)
                    add("conflict", e["src"] if e["src"] in ids else e["dst"], False,
                        f"{e['source']} ({e['source_file']}, {e['source_ref']}) says {self._label(e['src'])} "
                        f"{e['rel']} {self._label(e['dst'])}; {other}. The link stays {e['status']} for a person to "
                        "decide.", relation=rel_cite(e["src"], e["rel"], e["dst"]))
            if not found:
                add("conflict", n.id, True, "No two sources disagree about this unit or its points.")
        return {"node": {"id": n.id, "name": n.label}, "points_checked": len(pts) + len(loose), "summary": summary,
                "results": results[:60], "more": max(0, len(results) - 60)}

    # tools: graphics -----------------------------------------------------------------------------------------

    def show_graphic(self, node_id: str) -> dict:
        n = self._get(node_id)
        eq = self._equipment_of(n) or n
        for provider in [*GRAPHIC_PROVIDERS, _equipment_3d]:
            g = provider(self, eq)
            if g:
                cite = self._issue(f"graphic:{eq.id}", kind="graphic", label=f"{eq.label} graphic",
                                   page=g.get("page"), query=g.get("query"))
                return {"cite": cite, "unit": {"id": eq.id, "name": eq.label}, **g}
        return {"cite": None, "unit": {"id": eq.id, "name": eq.label}, "available": False,
                "note": f"No graphic for {eq.label}: its type has no template drawn yet."}

    # the "runs as designed" recipe ----------------------------------------------------------------------------

    def diagnose(self, node_id: str) -> dict:
        """Evidence, gathered by rules, for "does this unit run as designed?". Each step has a status (ok, problem,
        unknown) and the citations a sentence about it must carry."""
        eq, ids = self._unit_and_ids(node_id)
        seq = self.read_sequence(eq.id)
        mine = [s for s in seq["sequences"] if s["applies_to_unit"]]
        steps = []
        steps.append({"step": "sequence", "status": "ok" if mine else "unknown",
                      "says": (f"{eq.label} follows {', '.join(repr(s['title']) for s in mine)} "
                               f"(sheet {', '.join(str(s['sheet']) for s in mine)})") if mine else
                      "No sequence of operations names this unit.",
                      "cite": [c for s in mine for c in (s["cite"], s["source"])],
                      "related": [{"cite": s["cite"], "title": s["title"]} for s in seq["sequences"]
                                  if not s["applies_to_unit"]]})
        rels = [e for e in self.control_edges if e["src"] in ids or e["dst"] in ids]
        own = {e for e in ids}
        bindings = {p: self._binding(p) for p in ids if p in self.rows and self.rows[p]["kind"] == "point"}

        def pt(pid: str, role: str) -> dict:
            r = self.rows.get(pid)
            if r is None:
                return {"id": pid, "role": role, "exists": False}
            b = bindings.get(pid) or self._binding(pid) if r["kind"] == "point" else None
            out = {"id": pid, "name": r["label"], "role": role, "trust": trust(provenance(r))}
            if pid not in own:
                out["on"] = self._label((b or {}).get("equipment") or "") if b else None
            if b is not None and b["missing"]:
                out["not_bound"] = b["missing"]
            if r["kind"] == "point" and (why := self._class_fit(pid)):
                out["class"], out["class_problem"] = r["class"], why
                out["class_cite"] = self._issue(check_cite("class", pid), kind="check", status="fail",
                                                text=f"{r['label']} is {why}", label=r["label"])
            return out

        # loops: grouped by section and loop name
        loops: dict[tuple, dict] = {}
        for e in rels:
            a = json.loads(e["attrs"])
            if a.get("kind") != "loop":
                continue
            key = (a.get("section") or "", a.get("loop") or e["dst"])
            lp = loops.setdefault(key, {"loop": a.get("loop") or "", "section": a.get("section"),
                                        "section_cite": f"seq:{(a.get('sequence') or '').split(':', 1)[-1]}/"
                                                        f"{a.get('section')}" if a.get("section") else None,
                                        "relations": [], "ends": {}})
            lp["relations"].append(rel_cite(e["src"], e["rel"], e["dst"]))
            role = "setpoint" if e["rel"] == "drives" else "measured" if e["rel"] == "feedback" else "input"
            lp["ends"].setdefault(e["src"], role)
            lp["ends"].setdefault(e["dst"], "output")
        loop_items = []
        for lp in loops.values():
            ends = [pt(pid, role) for pid, role in lp.pop("ends").items()]
            problems = [f"{x.get('name', x['id'])}: {x['class_problem']}" for x in ends if x.get("class_problem")]
            problems += [f"{x.get('name', x['id'])}: {', '.join(x['not_bound'])}" for x in ends if x.get("not_bound")]
            if not any(x["role"] == "setpoint" for x in ends):
                problems.append("no setpoint point drives this loop")
            loop_items.append(lp | {"points": ends, "status": "problem" if problems else "ok", "problems": problems})
        loop_items.sort(key=lambda x: (x["section"] or "", x["loop"]))
        steps.append({"step": "loops", "status": ("unknown" if not loop_items else
                                                  "problem" if any(x["status"] == "problem" for x in loop_items)
                                                  else "ok"),
                      "says": (f"{len(loop_items)} control loops published for {eq.label}; "
                               f"{sum(x['status'] == 'ok' for x in loop_items)} have every point on the BMS with a "
                               "class that fits") if loop_items else
                      "No control loops are published for this unit (sequence logic not read).",
                      "loops": loop_items})
        # interlocks, safeties, modes and requests: by section
        other: dict[str, dict] = {}
        for e in rels:
            a = json.loads(e["attrs"])
            if a.get("kind") == "loop":
                continue
            sec = a.get("section") or "?"
            sid = (a.get("sequence") or "").split(":", 1)[-1]
            g = other.setdefault(f"{sid}/{sec}", {"section_cite": f"seq:{sid}/{sec}" if sid else None,
                                                  "relations": [], "problems": []})
            g["relations"].append(rel_cite(e["src"], e["rel"], e["dst"]))
            for end in (e["src"], e["dst"]):
                r = self.rows.get(end)
                if r is not None and r["kind"] == "point" and (b := self._binding(end))["missing"]:
                    g["problems"].append(f"{r['label']}: {', '.join(b['missing'])}")
        for g in other.values():
            g["count"] = len(g["relations"])
            g["relations"] = g["relations"][:6]
            g["problems"] = sorted(set(g["problems"]))
        steps.append({"step": "interlocks", "status": ("unknown" if not other else "problem"
                                                       if any(g["problems"] for g in other.values()) else "ok"),
                      "says": f"{sum(len(g['relations']) for g in other.values())} interlocks, safeties, modes and "
                              "requests touch this unit", "groups": list(other.values())})
        steps.append(self._setpoints(eq, mine, loop_items))
        chk = self.run_check(eq.id)
        fails = [r for r in chk["results"] if r["status"] == "fail"]
        steps.append({"step": "checks", "status": "problem" if fails else "ok", "summary": chk["summary"],
                      "says": (f"{len(fails)} checks fail on {eq.label} or its points" if fails else
                               f"Every check passes on {eq.label} and its points"),
                      "failing": [{k: r[k] for k in ("cite", "check", "message")} | {"node": r["node"]["name"]}
                                  for r in fails[:20]]})
        issues = [i for s in mine for i in s.get("issues", [])]
        steps.append({"step": "gaps_and_conflicts", "status": "problem" if issues else "ok", "issues": issues,
                      "says": f"{len(issues)} gaps or conflicts raised on the sequence" if issues else
                      "No gap or conflict raised on the sequence."})
        live = self._issue(check_cite("live", eq.id), kind="check", status="unknown", label=eq.label,
                           text="No live or trended BMS values in the graph.")
        steps.append({"step": "operation", "status": "unknown", "cite": [live],
                      "says": "Whether the unit actually runs this way is unknown: the graph holds no live or trended "
                              "BMS values. Check on site or from trends."})
        count = {s: sum(x["status"] == s for x in steps) for s in ("ok", "problem", "unknown")}
        return {"unit": {"id": eq.id, "name": eq.label, "class": eq.cls, "trust": trust(eq.prov)},
                "verdict": (f"On paper: {count['ok']} steps ok, {count['problem']} with problems, {count['unknown']} "
                            "unknown. In operation: unknown (no live data)."),
                "steps": steps}

    def _setpoints(self, eq: TreeNode, seqs: list[dict], loops: list[dict]) -> dict:
        """The sequence's values against the BMS setpoint points (their descriptions) and the schedule."""
        items, seen = [], set()
        for s_entry in seqs:
            seq = self.docs.sequence(s_entry["cite"][4:])
            if seq is None:
                continue
            for sp in seq.setpoints:
                key = (sp["section"], sp["value"], sp["unit"])
                if key in seen:
                    continue
                seen.add(key)
                maintain = re.search(r"\bmaintain|setpoint|positive pressurization", sp["text"], re.I)
                sec_cite = f"{seq.cite}/{sp['section']}"
                in_sec = [lp for lp in loops if lp["section"] == sp["section"]]
                sps = [x for lp in in_sec for x in lp["points"] if x["role"] == "setpoint" and x.get("name")]
                item = {"section_cite": sec_cite, "value": f"{sp['value']:g} {sp['unit']}", "text": sp["text"][:110]}
                matched = None
                for x in (sps if maintain else []):  # a threshold ("enable below 55 °F outdoor") is not a setpoint
                    desc = json.loads(self.rows[x["id"]]["attrs"]).get("description") or ""
                    vals = [v for v, u in values_in(desc) if u == sp["unit"]]
                    if vals:
                        ok = any(abs(v - sp["value"]) <= TOLERANCE.get(sp["unit"], 0.01) for v in vals)
                        if ok or matched is None:
                            matched = (x, desc, vals, ok)
                if matched:
                    x, desc, vals, ok = matched
                    c = check_cite(f"setpoint.{sp['section']}", x["id"])
                    text = (f"{x['name']} '{desc}' {'agrees with' if ok else 'differs from'} the sequence's "
                            f"{sp['value']:g} {sp['unit']}" if vals else
                            f"{x['name']} '{desc}' gives no value; the sequence says {sp['value']:g} {sp['unit']}")
                    status = "agree" if ok else "differ" if vals else "no value in the BMS"
                    item |= {"status": status, "point": x["id"], "says": text,
                             "cite": self._issue(c, kind="check", status=status, text=text, label=x["name"])}
                elif maintain:
                    c = check_cite(f"setpoint.{sp['section']}", eq.id)
                    text = (f"The sequence holds {sp['value']:g} {sp['unit']} (section {sp['section']}) but no setpoint "
                            f"point of {eq.label} carries it"
                            + (f" (the section's setpoints: {', '.join(x['name'] for x in sps)})" if sps else ""))
                    item |= {"status": "no setpoint point", "says": text,
                             "cite": self._issue(c, kind="check", status="no setpoint point", text=text,
                                                 label=eq.label)}
                else:
                    item |= {"status": "threshold", "says": "a fixed threshold in the program (adj), not a point"}
                sched = self._schedule_value(eq, sp, in_sec) if maintain else None
                if sched:
                    item["schedule"] = sched
                items.append(item)
        # one sentence, two values ("below 40 %RH ... maintain 45 %RH"): a point that agrees with one of them is not
        # wrong about the other, which is a threshold
        agreed = {(i["section_cite"], i["point"]) for i in items if i.get("status") == "agree"}
        for i in items:
            if i.get("status") == "differ" and (i["section_cite"], i["point"]) in agreed:
                self.issued.pop(i.pop("cite"), None)
                i.pop("point")
                i |= {"status": "threshold", "says": "a fixed threshold in the program (adj), not a point"}
        for i in items:  # the demoted item shared its check id with the one that agrees: that one keeps it
            if i.get("status") == "agree":
                self._issue(i["cite"], kind="check", status="agree", text=i["says"],
                            label=self.rows[i["point"]]["label"])
        # loops whose setpoint point has no value in the sequence (DAP-SP: "set by TAB")
        for lp in loops:
            for x in lp["points"]:
                if x["role"] != "setpoint" or not x.get("name") or any(i.get("point") == x["id"] for i in items):
                    continue
                desc = json.loads(self.rows[x["id"]]["attrs"]).get("description") or ""
                if not values_in(desc):
                    c = check_cite(f"setpoint.{lp['section']}", x["id"])
                    text = f"{x['name']} '{desc}' has no value in the BMS description, and the sequence gives none"
                    items.append({"section_cite": lp["section_cite"], "point": x["id"], "status": "no value",
                                  "says": text, "cite": self._issue(c, kind="check", status="no value", text=text,
                                                                    label=x["name"])})
        bad = [i for i in items if i["status"] in ("differ", "no setpoint point", "no value", "no value in the BMS")]
        return {"step": "setpoints", "status": "unknown" if not items else "problem" if bad else "ok",
                "says": (f"{sum(i['status'] == 'agree' for i in items)} sequence values agree with the BMS setpoint, "
                         f"{len(bad)} have no matching point or value") if items else
                "The sequence states no values for this unit.", "values": items}

    def _schedule_value(self, eq: TreeNode, sp: dict, loops: list[dict]) -> dict | None:
        measured = " ".join((x.get("name") or "") + " " + (json.loads(self.rows[x["id"]]["attrs"]).get("description") or "")
                            for lp in loops for x in lp["points"] if x["role"] == "measured" and x["id"] in self.rows)
        for words, unit, fields in SCHEDULE_FIELDS:
            if unit != sp["unit"] or not any(w in measured.lower() for w in words):
                continue
            for f in fields:
                if (v := eq.attrs.get(f)) is not None:
                    num = float(str(v).split("/")[0]) if re.match(r"^[-\d.]+", str(v)) else None
                    if num is None:
                        continue
                    ok = abs(num - sp["value"]) <= max(TOLERANCE.get(unit, 0.01), 0.6)
                    src = self._source_of_row(eq.prov, eq.id, eq.attrs)
                    return {"field": f, "value": v, "status": "agree" if ok else "differ",
                            "cite": [eq.id] + ([src["cite"]] if src else [])}
        return None

    # citations -----------------------------------------------------------------------------------------------

    def resolve(self, cite: str) -> dict | None:
        """What a citation id points at (for the dock and the scorer), or None when nothing in this project has it."""
        if cite in self.issued:
            return {"id": cite} | self.issued[cite]
        if cite in self.rows:
            r = self.rows[cite]
            return {"id": cite, "kind": r["kind"], "label": r["label"], "trust": trust(provenance(r))}
        if cite.startswith("rel:"):
            parts = cite[4:].split("|")
            e = self.edge_by_key.get(tuple(parts)) if len(parts) == 3 else None
            return None if e is None else {"id": cite, "kind": "relation", "label": self._relation(e)["says"],
                                           "trust": self._relation(e)["trust"]}
        if cite.startswith("seq:"):
            sid, _, letter = cite[4:].partition("/")
            s = self.docs.sequence(sid)
            if s is None or (letter and s.section(letter) is None):
                return None
            return {"id": cite, "kind": "section" if letter else "sequence", "label": s.title + (f" {letter}" if letter
                                                                                                 else "")}
        if cite.startswith("src:"):
            from .agent.documents import parse_src_cite
            p = parse_src_cite(cite)
            return None if p is None or not self.docs.path(p["file"]) else {"id": cite, "kind": "page", **p}
        if cite.startswith("issue:"):
            i = self.docs.issue(cite)
            return None if i is None else {"id": cite, "kind": "issue", "text": i["text"]}
        return None


def _equipment_3d(tools: GraphTools, eq: TreeNode) -> dict | None:
    """Equipment 3D (equipment_view.py): a parametric model of the unit's template with its points on anchors."""
    from .equipment_view import load_anchors
    t = eq.attrs.get("template")
    anchors = load_anchors()
    if not t or t not in anchors:
        return None
    roles, _ = tools._slot_roles(eq)
    placed = anchors[t].get("anchors", {})
    on = [pid for pid, role in roles.items() if role in placed]
    return {"available": True, "kind": "equipment_3d", "template": t, "page": "Equipment_3D",
            "query": {"project": tools.project, "equip": eq.id},
            "points_on_model": len(on), "points_off_model": len(tools._points(eq)) - len(on),
            "note": "Parametric 3D model of the template, values simulated (not live)."}


def _w9_graphics(tools: GraphTools, eq: TreeNode) -> dict | None:
    """W9's 2D/3D graphics, when its module is in this checkout and offers `graphic_ref(store, project, equip_id, km)`."""
    try:
        from . import graphics  # type: ignore[attr-defined]
    except ImportError:
        return None
    fn = getattr(graphics, "graphic_ref", None)
    if fn is None:
        return None
    try:
        g = fn(tools.store, tools.project, eq.id, tools.km)
    except Exception:  # noqa: BLE001 - a graphic that fails to build: fall back to Equipment 3D
        return None
    return ({"available": True} | dict(g)) if g else None


GRAPHIC_PROVIDERS.append(_w9_graphics)


_ID = {"type": "string", "description": "Node id, as returned by find_nodes (e.g. 'eq:Airside AHU-2', 'unit:AHU1')."}
_MEDIUM = {"type": "string", "enum": ["", "air", "chilled_water", "hot_water"],
           "description": "Follow only links carrying this medium. Empty for all."}
TOOLS = [
    {"name": "find_nodes",
     "description": "Search the building's equipment and points by name words and Brick class. Start here to get ids.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words that must all appear in the name or its equipment's name."},
         "cls": {"type": "string", "description": "Brick class or parent class, e.g. 'VAV', 'Temperature_Sensor'."},
         "kind": {"type": "string", "enum": ["", "equipment", "point"]},
         "limit": {"type": "integer", "default": 20}}}},
    {"name": "describe",
     "description": "One equipment or point with its class, parts, points (with their role on the equipment), what "
                    "feeds it, required points that are missing, the schedule data, and where each fact comes from.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID}, "required": ["node_id"]}},
    {"name": "upstream",
     "description": "Everything a node depends on, following feeds links backwards (a VAV's AHU, then its plants).",
     "input_schema": {"type": "object", "properties": {"node_id": _ID, "medium": _MEDIUM}, "required": ["node_id"]}},
    {"name": "downstream",
     "description": "Everything a node affects, following feeds links forwards (the VAVs an AHU supplies).",
     "input_schema": {"type": "object", "properties": {"node_id": _ID, "medium": _MEDIUM}, "required": ["node_id"]}},
    {"name": "behaviour",
     "description": "Control loops, interlocks, resets and requests the sequences of operation state for a node. "
                    "Intent from a document, not confirmed as built.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID}, "required": ["node_id"]}},
    {"name": "source_page",
     "description": "Where a fact was read: the document's file, page, sheet and the box on the page, and the other "
                    "sources that state it. Returns a src: citation; citing it shows the page in the chat.",
     "input_schema": {"type": "object", "properties": {"ref": {
         "type": "string", "description": "A node id, or a rel:, seq:, issue: or src: citation id."}},
         "required": ["ref"]}},
    {"name": "read_sequence",
     "description": "The sequences of operation that apply to a unit (sections with their setpoints, gaps and "
                    "conflicts) and the control relations published from them, with their status. Give `section` "
                    "(a letter) for that section's full text.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID, "section": {"type": "string"}},
                      "required": ["node_id"]}},
    {"name": "run_check",
     "description": "Check results for a unit and its points: SHACL building rules, missing template points, points "
                    "not bound to the BMS or on no equipment, a class that does not fit the point's input or output, "
                    "sources that disagree.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID, "checks": {
         "type": "array", "items": {"type": "string", "enum": ["shacl", "template", "binding", "class", "conflicts"]},
         "description": "Only these checks (default: all)."}}, "required": ["node_id"]}},
    {"name": "show_graphic",
     "description": "The unit's graphic (its 3D model and 2D schematic with points on their anchors, and the "
                    "graphic's QA result), as a link the chat shows.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID}, "required": ["node_id"]}},
    {"name": "diagnose",
     "description": "Does a unit run as designed? Gathers the evidence step by step: its sequence, each control loop's "
                    "points (on the BMS, class fits), interlocks, the sequence's setpoints against the BMS and the "
                    "schedule, the checks, the gaps, and what is unknown. Use it first for 'does X work / run as "
                    "designed / is X set up right'.",
     "input_schema": {"type": "object", "properties": {"node_id": _ID}, "required": ["node_id"]}},
]


def call(tools: GraphTools, name: str, args: dict | None = None) -> dict:
    """Run one tool by name. Errors come back as {"error": ...} so an agent can correct itself."""
    if name not in {t["name"] for t in TOOLS}:
        return {"error": f"unknown tool {name!r}; available: {[t['name'] for t in TOOLS]}"}
    try:
        return getattr(tools, name)(**(args or {}))
    except (KeyError, TypeError, ValueError) as e:
        return {"error": str(e.args[0]) if e.args else str(e)}
