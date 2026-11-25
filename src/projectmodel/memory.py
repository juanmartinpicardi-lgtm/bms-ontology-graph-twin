"""Memory and skills (spec-memory-skills.md, phase M1): files under `knowledge/`, loaded by scope and checked.

    kb = load_knowledge(km=km)                        # every file, validated; KnowledgeError lists every problem
    kb.scopes_for("alpha/names_paths")               # ["global", "site/alpha"]
    kb.memory_text(scopes, person="ana")             # memory for a prompt, general first, within the caps
    kb.skills_index(scopes)                          # name, description, scope of the active skills
    kb.skill_view("troubleshoot-warm-zone")          # SKILL.md body; skill_view(name, "references/x.md")

Layout:
    knowledge/memory/global.yaml                     principles and methods for every project
    knowledge/memory/<designer|contractor|customer|site>/<name>.yaml
    knowledge/people/<name>.yaml                     one person's profile (never changes outputs)
    knowledge/skills/<scope path>/<skill-name>/SKILL.md, rules/*.yaml, references/*.md

Scopes layer from general to specific: global, designer, contractor, customer, site. Memory is capped per scope (the
sum of the active entries' text); a file over its cap fails to load, so memory is merged rather than appended. Skill
rules name knowledge-model classes, which are checked against the model the same way conventions are. Nothing here
writes the files: changes arrive through the Memory page (M2) and the curator's approved proposals (M5).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .knowledge_model import ROOT, KnowledgeModel, KnowledgeModelError

KNOWLEDGE_DIR = ROOT / "knowledge"


def knowledge_dir() -> Path:
    """The knowledge/ folder in use: `PM_KNOWLEDGE_DIR` when set (a copy, e.g. for the learning-loop simulation, so
    approving a convention there never changes the repo's files), else the repo's own."""
    return Path(os.environ.get("PM_KNOWLEDGE_DIR") or KNOWLEDGE_DIR)


LAYERS = ("global", "designer", "contractor", "customer", "site")
CAPS = {"global": 4000, "designer": 2500, "contractor": 2500, "customer": 2500, "site": 2500, "person": 1200}
ENTRY_KINDS = ("principle", "fact", "preference", "warning")
ENTRY_METHODS = ("human", "curator", "import")
ENTRY_STATUS = ("active", "retired")
SKILL_STATUS = ("active", "draft", "retired")
RULE_FILES = ("conventions.yaml", "tags.yaml", "layouts.yaml", "terms.yaml", "variants.yaml")
SECTIONS = ("When to use", "Procedure", "Pitfalls", "Verification")
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SCOPE = re.compile(r"^(global|(designer|contractor|customer|site|person)/[a-z0-9]+(-[a-z0-9]+)*)$")
ENTRY_KEYS = {"id", "kind", "text", "source", "method", "author", "status", "locked", "created", "used"}


class KnowledgeError(KnowledgeModelError):
    def __init__(self, problems: list[str]):
        ValueError.__init__(self, "knowledge files are invalid:\n  - " + "\n  - ".join(problems))
        self.problems = problems


def scope_kind(scope: str) -> str:
    return scope.split("/", 1)[0]


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.parent))
    except ValueError:
        return str(path)


# memory ----------------------------------------------------------------------------------------------------------

@dataclass
class Entry:
    id: str
    kind: str
    text: str
    method: str
    author: str
    created: str
    source: dict = field(default_factory=dict)
    status: str = "active"
    locked: bool = False
    used: int = 0


@dataclass
class MemoryFile:
    scope: str
    path: Path
    cap: int
    entries: list[Entry]
    description: str = ""

    @property
    def active(self) -> list[Entry]:
        return [e for e in self.entries if e.status == "active"]

    @property
    def chars(self) -> int:
        return sum(len(e.text) for e in self.active)


def _load_memory(path: Path, root: Path, expected_scope: str, problems: list[str]) -> MemoryFile | None:
    where = _rel(path, root)
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        problems.append(f"{where}: not valid YAML: {e}")
        return None
    scope = data.get("scope")
    if scope != expected_scope:
        problems.append(f"{where}: scope is {scope!r}, the file's place says {expected_scope!r}")
        return None
    limit = CAPS[scope_kind(scope)]
    cap = data.get("cap", limit)
    if not isinstance(cap, int) or cap > limit:
        problems.append(f"{where}: cap {cap!r} is above the {scope_kind(scope)} limit of {limit} characters")
        cap = limit
    entries = []
    for i, raw in enumerate(data.get("entries") or []):
        at = f"{where}: entries[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{at}: must be a mapping")
            continue
        if extra := set(raw) - ENTRY_KEYS:
            problems.append(f"{at}: unknown keys {sorted(extra)}")
        missing = [k for k in ("id", "kind", "text", "method", "author", "created") if not raw.get(k)]
        if missing:
            problems.append(f"{at}: missing {missing}")
            continue
        e = Entry(id=str(raw["id"]), kind=raw["kind"], text=" ".join(str(raw["text"]).split()), method=raw["method"],
                  author=str(raw["author"]), created=str(raw["created"]), source=raw.get("source") or {},
                  status=raw.get("status", "active"), locked=bool(raw.get("locked", False)),
                  used=int(raw.get("used", 0)))
        at = f"{where}: {e.id}"
        if e.kind not in ENTRY_KINDS:
            problems.append(f"{at}: kind {e.kind!r} is not one of {ENTRY_KINDS}")
        if e.method not in ENTRY_METHODS:
            problems.append(f"{at}: method {e.method!r} is not one of {ENTRY_METHODS}")
        if e.status not in ENTRY_STATUS:
            problems.append(f"{at}: status {e.status!r} is not one of {ENTRY_STATUS}")
        if scope_kind(scope) == "person" and e.kind in ("principle", "warning"):
            problems.append(f"{at}: a person's profile holds preferences and facts, not {e.kind}s")
        try:
            date.fromisoformat(e.created)
        except ValueError:
            problems.append(f"{at}: created {e.created!r} is not a date (YYYY-MM-DD)")
        entries.append(e)
    mf = MemoryFile(scope, path, cap, entries, str(data.get("description", "")))
    if mf.chars > cap:
        problems.append(f"{where}: {mf.chars} characters of active memory, over the cap of {cap}: merge or retire "
                        "entries")
    return mf


# skills ----------------------------------------------------------------------------------------------------------

@dataclass
class Skill:
    name: str
    description: str
    version: int
    scope: str
    path: Path            # the skill's folder
    body: str             # SKILL.md without the frontmatter
    status: str = "active"
    locked: bool = False
    method: str = "human"
    approved_by: str = ""
    applies_to: dict = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)
    evidence: list = field(default_factory=list)
    dev_score: dict | None = None

    def rule_data(self, filename: str) -> dict | None:
        p = self.path / "rules" / filename
        return yaml.safe_load(p.read_text()) if f"rules/{filename}" in self.rules and p.exists() else None

    def references(self) -> list[str]:
        d = self.path / "references"
        return sorted(f"references/{p.name}" for p in d.glob("*.md")) if d.is_dir() else []


def _frontmatter(text: str) -> tuple[dict, str] | None:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return None
    front, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(front) or {}, body.strip()


def _check_rules(skill: Skill, km: KnowledgeModel | None, where: str, problems: list[str]) -> None:
    for rel in skill.rules:
        p = skill.path / rel
        if not rel.startswith("rules/") or p.name not in RULE_FILES:
            problems.append(f"{where}: rules entry {rel!r} must be rules/<one of {', '.join(RULE_FILES)}>")
            continue
        if not p.exists():
            problems.append(f"{where}: {rel} is listed but missing")
            continue
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            problems.append(f"{where}/{rel}: not valid YAML: {e}")
            continue
        at = f"{where}/{rel}"
        if p.name == "layouts.yaml":
            for i, lay in enumerate(data.get("layouts") or []):
                if not lay.get("title") or not isinstance(lay.get("columns"), list) or not lay["columns"]:
                    problems.append(f"{at}: layouts[{i}] needs a title and a non-empty list of columns")
                elif len(set(lay["columns"])) != len(lay["columns"]):
                    problems.append(f"{at}: layouts[{i}] ({lay['title']}) repeats a column")
            continue
        if km is None:
            continue
        if p.name == "conventions.yaml":
            from .conventions import ConventionError, Layer, apply_conventions

            try:
                apply_conventions(km, [Layer(skill.scope, p, data | {"scope": skill.scope})])
            except ConventionError as e:
                problems += [f"{at}: {x}" for x in e.problems]
            continue
        classes = []
        if p.name == "tags.yaml":
            classes = [(f"tags.{k}", (v or {}).get("class")) for k, v in (data.get("tags") or {}).items()]
        elif p.name == "terms.yaml":
            classes = [(f"terms.{k}", v) for k, v in (data.get("terms") or {}).items()]
        elif p.name == "variants.yaml":
            classes = [(f"variants[{i}]", v.get("class")) for i, v in enumerate(data.get("variants") or [])]
        for key, cls in classes:
            if cls not in km.classes:
                problems.append(f"{at}: {key}: class {cls!r} is not in the knowledge model")


def _load_skill(md: Path, root: Path, km: KnowledgeModel | None, problems: list[str]) -> Skill | None:
    folder = md.parent
    where = _rel(folder, root)
    parsed = _frontmatter(md.read_text())
    if parsed is None:
        problems.append(f"{where}/SKILL.md: needs YAML frontmatter between --- lines")
        return None
    front, body = parsed
    pm = ((front.get("metadata") or {}).get("projectmodel")) or {}
    name, scope = front.get("name"), pm.get("scope")
    expected_scope = "/".join(folder.relative_to(root / "skills").parts[:-1]) or None
    s = Skill(name=str(name), description=str(front.get("description", "")).strip(), version=front.get("version", 1),
              scope=str(scope), path=folder, body=body, status=pm.get("status", "active"),
              locked=bool(pm.get("locked", False)), method=pm.get("method", "human"),
              approved_by=str(pm.get("approved_by", "")), applies_to=pm.get("applies_to") or {},
              rules=list(pm.get("rules") or []), evidence=list(pm.get("evidence") or []), dev_score=pm.get("dev_score"))
    if not name or not NAME.match(str(name)) or len(str(name)) > 64:
        problems.append(f"{where}: name {name!r} must be lowercase words joined by hyphens, at most 64 characters")
    elif name != folder.name:
        problems.append(f"{where}: name {name!r} must match its folder {folder.name!r}")
    if not s.description or len(s.description) > 1024:
        problems.append(f"{where}: description must be 1 to 1024 characters")
    if not isinstance(s.version, int) or s.version < 1:
        problems.append(f"{where}: version must be a positive integer")
    if scope != expected_scope:
        problems.append(f"{where}: metadata.projectmodel.scope is {scope!r}, the folder says {expected_scope!r}")
    elif not SCOPE.match(scope) or scope_kind(scope) == "person":
        problems.append(f"{where}: scope {scope!r} is not a skill scope ({', '.join(LAYERS)})")
    if s.status not in SKILL_STATUS:
        problems.append(f"{where}: status {s.status!r} is not one of {SKILL_STATUS}")
    if s.method not in ENTRY_METHODS:
        problems.append(f"{where}: method {s.method!r} is not one of {ENTRY_METHODS}")
    for section in SECTIONS[:2]:
        if f"## {section}" not in body:
            problems.append(f"{where}/SKILL.md: needs a '## {section}' section")
    _check_rules(s, km, where, problems)
    return s


# the whole layer -------------------------------------------------------------------------------------------------

@dataclass
class Knowledge:
    root: Path
    memory: dict[str, MemoryFile]   # scope -> file (people included, as person/<name>)
    skills: dict[str, Skill]        # name -> skill
    projects: dict[str, list[str]]  # project -> scopes, from conventions/projects.yaml

    def scopes_for(self, project: str | None) -> list[str]:
        """global first, then the project's scopes in layer order (designer, contractor, customer, site)."""
        extra = self.projects.get(project or "", []) if project else []
        site = (project or "").split("/")[0]
        if site and f"site/{site}" not in extra and f"site/{site}" in self.memory:
            extra = [*extra, f"site/{site}"]
        return ["global", *sorted(dict.fromkeys(extra), key=lambda s: LAYERS.index(scope_kind(s)))]

    def memory_for(self, scopes: list[str], person: str | None = None) -> list[MemoryFile]:
        out = [self.memory[s] for s in scopes if s in self.memory]
        if person and (p := self.memory.get(f"person/{_slug(person)}")):
            out.append(p)
        return out

    def memory_text(self, scopes: list[str], person: str | None = None) -> str:
        """Memory for a prompt, general first, each entry with its id so an answer can cite it. Bounded by the caps
        (at most ~4,000 + 2,500 per scope + 1,200 characters)."""
        blocks = []
        for mf in self.memory_for(scopes, person):
            lines = [f"- [{e.id}] ({e.kind}) {e.text}" for e in mf.active]
            if lines:
                blocks.append(f"## {mf.scope}\n" + "\n".join(lines))
        return "\n\n".join(blocks)

    def skills_index(self, scopes: list[str] | None = None) -> list[dict]:
        return [{"name": s.name, "description": s.description, "scope": s.scope, "version": s.version}
                for s in sorted(self.skills.values(), key=lambda s: (LAYERS.index(scope_kind(s.scope)), s.name))
                if s.status == "active" and (scopes is None or s.scope in scopes)]

    def skill_view(self, name: str, path: str | None = None) -> str:
        if name not in self.skills:
            raise KeyError(f"no skill {name!r}; known: {sorted(self.skills)}")
        s = self.skills[name]
        if not path:
            return s.body
        target = (s.path / path).resolve()
        if not target.is_relative_to(s.path.resolve()) or not target.is_file():
            raise KeyError(f"skill {name!r} has no file {path!r}; it has {s.rules + s.references()}")
        return target.read_text()

    def entry(self, entry_id: str) -> tuple[MemoryFile, Entry] | None:
        for mf in self.memory.values():
            for e in mf.entries:
                if e.id == entry_id:
                    return mf, e
        return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _projects(conv_dir: Path) -> dict[str, list[str]]:
    p = conv_dir / "projects.yaml"
    data = yaml.safe_load(p.read_text()) if p.exists() else {}
    return {k: list(v or []) for k, v in (data or {}).items()}


def load_knowledge(root: Path | None = None, km: KnowledgeModel | None = None,
                   conv_dir: Path = ROOT / "conventions") -> Knowledge:
    """Load and check every memory file, profile and skill under `root` (default: knowledge_dir()). With `km`, skill
    rules are checked against the knowledge model too. Raises KnowledgeError listing every problem found."""
    root = Path(root) if root is not None else knowledge_dir()
    problems: list[str] = []
    memory: dict[str, MemoryFile] = {}
    mem_dir = root / "memory"
    if (g := mem_dir / "global.yaml").exists():
        if mf := _load_memory(g, root, "global", problems):
            memory["global"] = mf
    for kind in LAYERS[1:]:
        for p in sorted((mem_dir / kind).glob("*.yaml")):
            if mf := _load_memory(p, root, f"{kind}/{p.stem}", problems):
                memory[mf.scope] = mf
    for p in sorted((root / "people").glob("*.yaml")):
        if mf := _load_memory(p, root, f"person/{p.stem}", problems):
            memory[mf.scope] = mf
    for p in sorted(mem_dir.glob("*.yaml")):
        if p.name != "global.yaml":
            problems.append(f"{_rel(p, root)}: only global.yaml sits in memory/; others go in memory/<kind>/")
    for p in sorted(mem_dir.glob("*/")):
        if p.name not in LAYERS[1:]:
            problems.append(f"{_rel(p, root)}: unknown scope kind; use one of {LAYERS[1:]}")

    seen: dict[str, str] = {}
    for mf in memory.values():
        for e in mf.entries:
            if e.id in seen:
                problems.append(f"{_rel(mf.path, root)}: id {e.id} is also used in {seen[e.id]}")
            seen[e.id] = _rel(mf.path, root)

    skills: dict[str, Skill] = {}
    for md in sorted((root / "skills").rglob("SKILL.md")):
        if s := _load_skill(md, root, km, problems):
            if s.name in skills:
                problems.append(f"{_rel(s.path, root)}: skill name {s.name!r} is also used by "
                                f"{_rel(skills[s.name].path, root)}")
            skills[s.name] = s

    projects = _projects(conv_dir)
    skill_scopes = {s.scope for s in skills.values()}
    for project, scopes in projects.items():
        for sc in scopes:
            if not SCOPE.match(sc) or scope_kind(sc) not in LAYERS[1:]:
                problems.append(f"conventions/projects.yaml: {project}: {sc!r} is not a project scope")
            elif sc not in memory and sc not in skill_scopes and not (conv_dir / f"{sc}.yaml").exists():
                problems.append(f"conventions/projects.yaml: {project}: scope {sc!r} has no memory, skill or "
                                "conventions file")
    if problems:
        raise KnowledgeError(problems)
    return Knowledge(root, memory, skills, projects)
