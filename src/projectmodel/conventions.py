"""Conventions: naming rules for one contractor, customer or site, layered on top of the knowledge model.

    layers = load_layers(["contractor/acme", "site/alpha"])   # reads conventions/<scope>.yaml
    km2 = apply_conventions(km, layers)                        # new model; km and the files are untouched
    scopes_for("alpha/names_paths")                            # from conventions/projects.yaml

Layering: knowledge model <- contractor <- customer <- site (layers are sorted into that order).
  abbreviations       a later layer overrides a token or adds a new one
  equipment_patterns  extend the template's name patterns
  class_hints         extend; a later layer's hints are tried first; the same pattern text replaces an earlier one
  ignore              extend, same rule as class_hints
Every entry keeps its origin ("site/alpha:abbreviations.cc") so the mapper can record it as provenance.
A problem raises ConventionError naming the file and the key.

Skills' rules (spec-memory-skills §5.3, the M3 read path): an active skill under knowledge/skills/<scope>/ whose
SKILL.md lists rules/conventions.yaml adds one more layer for that scope, after the scope's own conventions file.
That is where approved learned conventions live (curator.py, skill learned-conventions-<name>). A learned class hint
names itself ({pattern, class, id, template?, instead_of?, ...}): its origin is "<scope>:<id>", e.g.
"site/alpha:lc-3f2a1b". `template` keeps it to points on equipment of that template; `instead_of` to points the rules
would otherwise give that class. A skill's rules/terms.yaml (phrase -> class) is read by the guided setup
(learned_terms, hooked in intake/knowledge.apply).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .knowledge_model import ROOT, ClassHint, IgnoreRule, KnowledgeModel, KnowledgeModelError

CONV_DIR = ROOT / "conventions"
LAYER_ORDER = ("contractor", "customer", "site")
# provenance: who approved which learned entry (curator.py), keyed by entry; read by people, not by the mapper
FILE_KEYS = {"scope", "description", "author", "abbreviations", "equipment_patterns", "class_hints", "ignore",
             "provenance"}
# A class hint is {pattern, class}; a learned one also says who approved it and why, and may be scoped.
HINT_KEYS = {"pattern", "class"}
HINT_OPTIONAL = {"id", "template", "instead_of", "why", "approved_by", "approved_at", "evidence"}


class ConventionError(KnowledgeModelError):
    def __init__(self, problems: list[str]):
        ValueError.__init__(self, "conventions are invalid:\n  - " + "\n  - ".join(problems))
        self.problems = problems


@dataclass
class Layer:
    scope: str  # "site/alpha"
    path: Path
    data: dict
    skill: str = ""  # the skill whose rules/conventions.yaml this is; "" for a conventions/ file

    @property
    def where(self) -> str:
        try:
            return str(self.path.resolve().relative_to(ROOT))
        except ValueError:
            return str(self.path)


def _knowledge_root(knowledge: Path | None) -> Path:
    from .memory import knowledge_dir
    return Path(knowledge) if knowledge is not None else knowledge_dir()


def _skill_front(md: Path) -> dict:
    text = md.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}
    return yaml.safe_load(text[4:].split("\n---\n", 1)[0]) or {}


def skill_rule_files(scope: str, filename: str, knowledge: Path | None = None) -> list[tuple[str, Path]]:
    """(skill name, path) of the active skills of `scope` whose SKILL.md lists rules/<filename>, by skill name."""
    out = []
    base = _knowledge_root(knowledge) / "skills" / scope
    for md in sorted(base.glob("*/SKILL.md")) if base.is_dir() else []:
        front = _skill_front(md)
        pm = ((front.get("metadata") or {}).get("projectmodel")) or {}
        if pm.get("status", "active") == "active" and f"rules/{filename}" in (pm.get("rules") or []) \
                and (md.parent / "rules" / filename).exists():
            out.append((str(front.get("name") or md.parent.name), md.parent / "rules" / filename))
    return out


def _has_rules(scope: str, conv_dir: Path, knowledge: Path | None) -> bool:
    return (Path(conv_dir) / f"{scope}.yaml").exists() or bool(skill_rule_files(scope, "conventions.yaml", knowledge))


def _listed(project: str, conv_dir: Path) -> list[str]:
    path = Path(conv_dir) / "projects.yaml"
    data = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    scopes = data.get(project) or []
    if not isinstance(scopes, list):
        raise ConventionError([f"{path.name}: {project}: must be a list of scopes"])
    return [str(s) for s in scopes]


def scopes_for(project: str, conv_dir: Path = CONV_DIR, knowledge: Path | None = None) -> list[str]:
    """Convention scopes that apply to a project ("alpha/names_paths"), in layer order. Unlisted project: none, unless
    its site has rules of its own (a site/<site> conventions file or skill, such as a learned convention a person
    approved for that site).

    projects.yaml also lists scopes that only hold memory and skills (designer/*, or a contractor with no naming
    rules yet); those have no rules here and are skipped. The memory loader (memory.py) checks that every listed
    scope exists somewhere, so a misspelt scope still fails."""
    scopes = _listed(project, conv_dir)
    site = f"site/{project.split('/')[0]}"
    if site not in scopes and _has_rules(site, conv_dir, knowledge):
        scopes = [*scopes, site]
    return [s for s in scopes if s.split("/")[0] in LAYER_ORDER and _has_rules(s, conv_dir, knowledge)]


def load_layers(scopes: list[str], conv_dir: Path = CONV_DIR, knowledge: Path | None = None) -> list[Layer]:
    """Each scope's conventions file, then its skills' rules/conventions.yaml (knowledge/skills/<scope>/), in layer
    order. A scope with neither is an error."""
    problems, layers = [], []
    for scope in scopes:
        kind = scope.split("/")[0]
        path = Path(conv_dir) / f"{scope}.yaml"
        if kind not in LAYER_ORDER or scope.count("/") != 1:
            problems.append(f"{scope}: scope must be <{'|'.join(LAYER_ORDER)}>/<name>")
            continue
        skills = skill_rule_files(scope, "conventions.yaml", knowledge)
        if not path.exists() and not skills:
            problems.append(f"{scope}: no file {path.name} in {Path(conv_dir).name}/{kind}/")
            continue
        for name, p in ([("", path)] if path.exists() else []) + skills:
            try:
                data = yaml.safe_load(p.read_text()) or {}
            except yaml.YAMLError as e:
                problems.append(f"{f'{name}/rules/' if name else ''}{p.name}: does not parse: {e}")
                continue
            if name and isinstance(data, dict):
                data = {"scope": scope, **data}  # a skill's rules take the skill's scope
            layers.append(Layer(scope, p, data, name))
    if problems:
        raise ConventionError(problems)
    return sorted(layers, key=lambda layer: LAYER_ORDER.index(layer.scope.split("/")[0]))


def learned_terms(project: str, conv_dir: Path = CONV_DIR, knowledge: Path | None = None) -> list[tuple[str, str]]:
    """(phrase, class) from the rules/terms.yaml of the active skills in the project's scopes (designer included) and
    its site's, for the guided setup's readers. Approved learned conventions for a setup project land there."""
    scopes = _listed(project, conv_dir)
    if (site := f"site/{project.split('/')[0]}") not in scopes:
        scopes.append(site)
    out = []
    for scope in scopes:
        for _, p in skill_rule_files(scope, "terms.yaml", knowledge):
            terms = (yaml.safe_load(p.read_text()) or {}).get("terms") or {}
            out += [(str(k), str(v)) for k, v in terms.items()]
    return out


def _compile(pattern, flags=0) -> tuple[re.Pattern | None, str | None]:
    try:
        return re.compile(str(pattern), flags), None
    except re.error as e:
        return None, str(e)


def apply_conventions(km: KnowledgeModel, layers: list[Layer]) -> KnowledgeModel:
    """A copy of `km` with the layers merged in order, checked with the knowledge model's own rules."""
    problems: list[str] = []
    nr = km.name_rules
    abbreviations = dict(nr.abbreviations)
    abbr_origin = dict(km.abbreviation_origin)
    templates = {tid: dataclasses.replace(t, name_patterns=list(t.name_patterns), pattern_origin=dict(t.pattern_origin))
                 for tid, t in km.templates.items()}
    hints: list[ClassHint] = list(km.class_hints)
    ignore: list[IgnoreRule] = list(km.ignore)
    point_classes = set(km.by_kind("point"))

    for layer in layers:
        d, f = layer.data, layer.where
        if not isinstance(d, dict):
            problems.append(f"{f}: must be a mapping")
            continue
        for key in sorted(set(d) - FILE_KEYS):
            problems.append(f"{f}: unknown key {key!r} (allowed: {', '.join(sorted(FILE_KEYS))})")
        if d.get("scope") != layer.scope:
            problems.append(f"{f}: scope: must be {layer.scope!r}, found {d.get('scope')!r}")

        for key, val in (d.get("abbreviations") or {}).items():
            key, where = str(key).lower(), f"{f}: abbreviations.{key}"
            if val is None or not isinstance(val, list):
                problems.append(f"{where}: must be a list of words, or a list of alternatives")
                continue
            # [] means the token carries no meaning for the class (read and dropped).
            alts = val if val and isinstance(val[0], list) else [val]
            alts = [[str(w) for w in a] for a in alts]
            bad = [w for a in alts for w in a if w not in nr.vocabulary]
            for w in bad:
                problems.append(f"{where}: expands to {w!r}, which is not in the vocabulary")
            if nr.separators.search(key):
                problems.append(f"{where}: key contains a separator, so the tokenizer can never produce it")
            if not bad:
                abbreviations[key] = alts
                abbr_origin[key] = f"{layer.scope}:abbreviations.{key}"

        for tid, patterns in (d.get("equipment_patterns") or {}).items():
            where = f"{f}: equipment_patterns.{tid}"
            if tid not in templates:
                problems.append(f"{where}: {tid!r} is not a template ({', '.join(sorted(templates))})")
                continue
            for i, p in enumerate(patterns or []):
                rx, err = _compile(p, re.I)
                if err:
                    problems.append(f"{where}[{i}]: bad regex {p!r}: {err}")
                elif rx.pattern not in templates[tid].pattern_origin:
                    templates[tid].name_patterns.append(rx)
                    templates[tid].pattern_origin[rx.pattern] = f"{layer.scope}:equipment_patterns.{tid}[{i}]"

        new_hints = []
        for i, h in enumerate(d.get("class_hints") or []):
            where = f"{f}: class_hints[{i}]"
            if not isinstance(h, dict) or not HINT_KEYS <= set(h) or set(h) - HINT_KEYS - HINT_OPTIONAL:
                problems.append(f"{where}: must be {{pattern: <regex>, class: <point class>}}, optionally with "
                                f"{', '.join(sorted(HINT_OPTIONAL))}")
                continue
            rx, err = _compile(h["pattern"])
            if err:
                problems.append(f"{where}: bad regex {h['pattern']!r}: {err}")
            elif h["class"] not in point_classes:
                problems.append(f"{where}: class {h['class']!r} is not a point class in the knowledge model")
            elif h.get("template") and h["template"] not in templates:
                problems.append(f"{where}: template {h['template']!r} is not a template "
                                f"({', '.join(sorted(templates))})")
            elif h.get("instead_of") and h["instead_of"] not in point_classes:
                problems.append(f"{where}: instead_of {h['instead_of']!r} is not a point class in the knowledge model")
            else:
                origin = f"{layer.scope}:{h['id']}" if h.get("id") else f"{layer.scope}:class_hints[{i}]"
                new_hints.append(ClassHint(rx, h["class"], origin, h.get("template") or None,
                                           h.get("instead_of") or None))
        replaced = {(h.pattern.pattern, h.template, h.instead_of) for h in new_hints}
        hints = new_hints + [h for h in hints if (h.pattern.pattern, h.template, h.instead_of) not in replaced]

        new_ignore = []
        for i, g in enumerate(d.get("ignore") or []):
            where = f"{f}: ignore[{i}]"
            if not isinstance(g, dict) or set(g) != {"pattern", "reason"} or not str(g.get("reason") or "").strip():
                problems.append(f"{where}: must be {{pattern: <regex>, reason: <why>}} with a reason")
                continue
            rx, err = _compile(g["pattern"])
            if err:
                problems.append(f"{where}: bad regex {g['pattern']!r}: {err}")
            else:
                new_ignore.append(IgnoreRule(rx, str(g["reason"]), f"{layer.scope}:ignore[{i}]"))
        replaced = {g.pattern.pattern for g in new_ignore}
        ignore = new_ignore + [g for g in ignore if g.pattern.pattern not in replaced]

    if problems:
        raise ConventionError(problems)
    return dataclasses.replace(
        km, name_rules=dataclasses.replace(nr, abbreviations=abbreviations), templates=templates,
        conventions=km.conventions + [f"{layer.scope}/{layer.skill}" if layer.skill else layer.scope
                                      for layer in layers], class_hints=hints, ignore=ignore,
        abbreviation_origin=abbr_origin)


def layer_entries(layers: list[Layer]) -> list[dict]:
    """Flat rows (scope, kind, key, value) for showing which entry comes from which layer."""
    rows = []
    for layer in layers:
        d = layer.data or {}
        for k, v in (d.get("abbreviations") or {}).items():
            rows.append({"scope": layer.scope, "kind": "abbreviations", "key": str(k), "value": v})
        for tid, ps in (d.get("equipment_patterns") or {}).items():
            rows += [{"scope": layer.scope, "kind": "equipment_patterns", "key": tid, "value": p} for p in ps or []]
        for h in d.get("class_hints") or []:
            value = " ".join([str(h.get("class")), *([f"on {h['template']}"] if h.get("template") else []),
                              *([f"instead of {h['instead_of']}"] if h.get("instead_of") else [])])
            rows.append({"scope": layer.scope, "kind": "class_hints", "key": h.get("pattern"), "value": value,
                         "convention": h.get("id") or "", "approved_by": h.get("approved_by") or ""})
        for g in d.get("ignore") or []:
            rows.append({"scope": layer.scope, "kind": "ignore", "key": g.get("pattern"), "value": g.get("reason")})
    return rows


def entry_text(value) -> str:
    """An entry's value as text: an abbreviation's expansion is a list of words, or a list of alternatives (lists),
    or empty for a token that carries no meaning."""
    if isinstance(value, list):
        if not value:
            return "(no meaning)"
        if all(isinstance(v, list) for v in value):
            return " | ".join(" ".join(map(str, v)) for v in value)
        return " ".join(map(str, value))
    return "" if value is None else str(value)


def layer_table(layers: list[Layer]) -> list[dict]:
    """layer_entries for display: every value as text, so a table of them has one type per column."""
    return [{**e, "value": entry_text(e["value"])} for e in layer_entries(layers)]
