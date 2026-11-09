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
FILE_KEYS = {"scope", "description", "author", "abbreviations", "equipment_patterns", "class_hints", "ignore"}


class ConventionError(KnowledgeModelError):
    def __init__(self, problems: list[str]):
        ValueError.__init__(self, "conventions are invalid:\n  - " + "\n  - ".join(problems))
        self.problems = problems


@dataclass
class Layer:
    scope: str  # "site/alpha"
    path: Path
    data: dict

    @property
    def where(self) -> str:
        try:
            return str(self.path.resolve().relative_to(ROOT))
        except ValueError:
            return str(self.path)


def scopes_for(project: str, conv_dir: Path = CONV_DIR) -> list[str]:
    """Scopes that apply to a project ("alpha/names_paths"), in layer order. Unlisted project: none."""
    path = Path(conv_dir) / "projects.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    scopes = data.get(project) or []
    if not isinstance(scopes, list):
        raise ConventionError([f"{path.name}: {project}: must be a list of scopes"])
    return [str(s) for s in scopes]


def load_layers(scopes: list[str], conv_dir: Path = CONV_DIR) -> list[Layer]:
    problems, layers = [], []
    for scope in scopes:
        kind = scope.split("/")[0]
        path = Path(conv_dir) / f"{scope}.yaml"
        if kind not in LAYER_ORDER or scope.count("/") != 1:
            problems.append(f"{scope}: scope must be <{'|'.join(LAYER_ORDER)}>/<name>")
            continue
        if not path.exists():
            problems.append(f"{scope}: no file {path.name} in {Path(conv_dir).name}/{kind}/")
            continue
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as e:
            problems.append(f"{scope}.yaml: does not parse: {e}")
            continue
        layers.append(Layer(scope, path, data))
    if problems:
        raise ConventionError(problems)
    return sorted(layers, key=lambda layer: LAYER_ORDER.index(layer.scope.split("/")[0]))


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
            if not isinstance(h, dict) or set(h) != {"pattern", "class"}:
                problems.append(f"{where}: must be {{pattern: <regex>, class: <point class>}}")
                continue
            rx, err = _compile(h["pattern"])
            if err:
                problems.append(f"{where}: bad regex {h['pattern']!r}: {err}")
            elif h["class"] not in point_classes:
                problems.append(f"{where}: class {h['class']!r} is not a point class in the knowledge model")
            else:
                new_hints.append(ClassHint(rx, h["class"], f"{layer.scope}:class_hints[{i}]"))
        replaced = {h.pattern.pattern for h in new_hints}
        hints = new_hints + [h for h in hints if h.pattern.pattern not in replaced]

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
        conventions=km.conventions + [layer.scope for layer in layers], class_hints=hints, ignore=ignore,
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
            rows.append({"scope": layer.scope, "kind": "class_hints", "key": h.get("pattern"), "value": h.get("class")})
        for g in d.get("ignore") or []:
            rows.append({"scope": layer.scope, "kind": "ignore", "key": g.get("pattern"), "value": g.get("reason")})
    return rows
