"""Load and validate the knowledge model in /knowledge_model.

    km = load_knowledge_model()          # raises KnowledgeModelError listing every problem
    km.is_a("VAV", "Terminal_Unit")      # class reasoning over Brick 1.4.4 + BA extension
    km.name_rules.words("Clg_Valve_Cmd") # ['cooling', 'valve', 'command']
    km.templates["vav"].slots            # point slots for template matching
    load_knowledge_model(conventions=["site/alpha"])  # same, with convention layers merged (see conventions.py)

Brick is pinned to 1.4.4, the version the ground truth was built with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import brickschema
import rdflib
import yaml
from rdflib.namespace import OWL, RDF, RDFS, SKOS

ROOT = Path(__file__).resolve().parents[2]
KM_DIR = ROOT / "knowledge_model"
BRICK_VERSION = "1.4"
BRICK = rdflib.Namespace("https://brickschema.org/schema/Brick#")
BA = rdflib.Namespace("urn:projectmodel:ba#")
REC = rdflib.Namespace("https://w3id.org/rec#")  # RealEstateCore, which replaces Brick 1.4's location classes

# Relations the app writes that are not Brick's own. The sequences loader writes the control relations
# (sequences.py reads CONTROL from here) and the guided setup writes `serves` (floor plans) and the controls riser
# (`isHostedBy`, `isOnNetwork`, `controls`: intake/publish.py). The loader fails unless every one is declared in
# ba_extension.ttl or listed in the Brick subset.
CONTROL_RELATIONS = ("drives", "feedback", "requires", "resets", "requests", "switches")
HARDWARE_RELATIONS = ("isHostedBy", "isOnNetwork", "controls")
WRITTEN_RELATIONS = (*CONTROL_RELATIONS, "serves", *HARDWARE_RELATIONS)


class KnowledgeModelError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("knowledge model is invalid:\n  - " + "\n  - ".join(problems))
        self.problems = problems


# --- Name rules -------------------------------------------------------------------------------

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_LETTER_DIGIT = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")


@dataclass
class NameRules:
    separators: re.Pattern
    split_camel_case: bool
    split_letter_digit: bool
    lowercase: bool
    vocabulary: set[str]
    abbreviations: dict[str, list[list[str]]]  # token -> alternatives, most likely first
    examples: dict[str, list[str]]
    phrases: dict[str, str] = field(default_factory=dict)  # "s/s" -> "ss", applied before splitting

    def _apply_phrases(self, name: str) -> str:
        for text, token in self.phrases.items():
            name = re.sub(rf"(?<![A-Za-z0-9]){re.escape(text)}(?![A-Za-z0-9])", f" {token} ", name, flags=re.I)
        return name

    def tokenize(self, name: str) -> list[str]:
        tokens = []
        for chunk in self.separators.split(self._apply_phrases(name)):
            if not chunk:
                continue
            parts = _CAMEL.split(chunk) if self.split_camel_case else [chunk]
            for part in parts:
                tokens.extend(p for p in (_LETTER_DIGIT.split(part) if self.split_letter_digit else [part]) if p)
        return [t.lower() for t in tokens] if self.lowercase else tokens

    def expand(self, token: str) -> list[list[str]] | None:
        """Alternatives for one token, or None if unknown. Abbreviations win over vocabulary
        so that ambiguous words ("current") can list their meanings."""
        if token in self.abbreviations:
            return self.abbreviations[token]
        if token in self.vocabulary:
            return [[token]]
        return None

    def words(self, name: str) -> list[str]:
        """Canonical words using the first alternative; unknown tokens pass through unchanged."""
        out = []
        for t in self.tokenize(name):
            alts = self.expand(t)
            out.extend(alts[0] if alts else [t])
        return out

    def unknown_tokens(self, name: str) -> list[str]:
        return [t for t in self.tokenize(name) if self.expand(t) is None and not t.isdigit()]


# --- Templates --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    role: str
    classes: tuple[str, ...]
    required: bool
    medium: str = ""  # a filled slot is evidence the equipment uses this medium (e.g. a heating valve -> hot_water)
    words: tuple[str, ...] = ()  # name words that pick this slot over an earlier one with the same class


@dataclass(frozen=True)
class Relation:
    rel: str
    target: str
    medium: str
    required: bool
    system: str = ""  # system class that supplies the medium site-wide (e.g. Hot_Water_System), if any


@dataclass
class Template:
    id: str
    brick_class: str
    description: str
    name_patterns: list[re.Pattern]
    point_count: tuple[int, int]
    slots: list[Slot]
    relations: list[Relation]
    pattern_origin: dict[str, str] = field(default_factory=dict)  # pattern text -> convention that added it

    def matches_name(self, name: str) -> bool:
        return any(p.search(name) for p in self.name_patterns)


# --- Convention entries (merged in by conventions.py; empty for the bare knowledge model) -----------

@dataclass(frozen=True)
class ClassHint:
    pattern: re.Pattern  # matched against the whole point name
    cls: str
    origin: str  # e.g. "site/alpha:class_hints[0]"


@dataclass(frozen=True)
class IgnoreRule:
    pattern: re.Pattern
    reason: str
    origin: str


# --- Knowledge model --------------------------------------------------------------------------

@dataclass
class ClassInfo:
    name: str
    kind: str  # "equipment" | "point" | "system" | "location" | "other"
    group: str  # section in brick_subset.yaml, or "ba_extension"
    source: str  # "brick" | "ba"
    subset_parent: str | None = None  # nearest ancestor that is also in the model
    replaced_by: str = ""  # a deprecated Brick class kept on purpose: the rec: class that replaces it, e.g. "rec:Level"


@dataclass
class ClassMatching:
    """Settings for matching name words to class-name words (name_rules/class_matching.yaml)."""
    name_synonyms: dict[str, str]  # "" means drop the word
    class_word_synonyms: dict[tuple[str, ...], str]
    functions: list[str]
    default_function: str
    quantities: set[str]
    command_cues: set[str]
    point_implies: dict[str, list[str]] = field(default_factory=dict)

    def name_words(self, words: list[str]) -> list[str]:
        out = []
        for w in words:
            w = self.name_synonyms.get(w, w)
            if w:
                out.append(w)
        return out

    def class_words(self, cls: str) -> list[str]:
        words = cls.lower().split("_")
        out, i = [], 0
        phrases = sorted(self.class_word_synonyms, key=len, reverse=True)
        while i < len(words):
            for p in phrases:
                if tuple(words[i:i + len(p)]) == p:
                    out.append(self.class_word_synonyms[p])
                    i += len(p)
                    break
            else:
                out.append(words[i])
                i += 1
        return [w for w in out if w]


@dataclass
class KnowledgeModel:
    brick_version: str
    classes: dict[str, ClassInfo]
    relations: list[str]
    ba_relations: list[str]
    templates: dict[str, Template]
    name_rules: NameRules
    class_matching: ClassMatching
    graph: rdflib.Graph = field(repr=False)  # Brick 1.4.4 + BA extension
    # Convention layers merged on top (conventions.py). Hints and ignore rules: highest priority first.
    conventions: list[str] = field(default_factory=list)  # scopes, e.g. ["site/alpha"]
    class_hints: list[ClassHint] = field(default_factory=list)
    ignore: list[IgnoreRule] = field(default_factory=list)
    abbreviation_origin: dict[str, str] = field(default_factory=dict)  # token -> convention that set it

    def uri(self, cls: str) -> rdflib.URIRef:
        return BA[cls] if self.classes.get(cls, None) and self.classes[cls].source == "ba" else BRICK[cls]

    def is_a(self, cls: str, ancestor: str) -> bool:
        return cls == ancestor or _is_subclass(self.graph, self.uri(cls), self.uri(ancestor))

    def by_kind(self, kind: str) -> list[str]:
        return sorted(c for c, i in self.classes.items() if i.kind == kind)


_ANCESTORS: dict[tuple[int, rdflib.URIRef], frozenset] = {}


def _is_subclass(graph: rdflib.Graph, sub: rdflib.URIRef, sup: rdflib.URIRef) -> bool:
    """Strict rdfs:subClassOf+ test, with each class's ancestor set computed once per graph."""
    key = (id(graph), sub)
    if key not in _ANCESTORS:
        _ANCESTORS[key] = frozenset(a for a in graph.transitive_objects(sub, RDFS.subClassOf) if a != sub)
    return sup in _ANCESTORS[key]


def _load_brick() -> rdflib.Graph:
    return brickschema.Graph(load_brick=True, brick_version=BRICK_VERSION)


def load_knowledge_model(km_dir: Path = KM_DIR, brick: rdflib.Graph | None = None,
                         conventions: list[str] | None = None, conventions_dir: Path | None = None) -> KnowledgeModel:
    """`conventions`: scopes such as ["contractor/acme", "site/alpha"], merged on top of the model
    (raises ConventionError naming the file and key of any problem). The files on disk are untouched."""
    km_dir = Path(km_dir)
    problems: list[str] = []
    g = brick if brick is not None else _load_brick()

    def brick_has(uri: rdflib.URIRef, rdf_type: rdflib.URIRef) -> bool:
        return (uri, RDF.type, rdf_type) in g

    def deprecated(uri: rdflib.URIRef) -> bool:
        return (uri, OWL.deprecated, rdflib.Literal(True)) in g

    # Brick subset
    subset = yaml.safe_load((km_dir / "brick_subset.yaml").read_text())
    version = str(subset.get("brick_version"))
    loaded = {str(v) for v in g.objects(None, OWL.versionInfo)}
    if version not in loaded:
        problems.append(f"brick_subset.yaml says Brick {version}, loaded Brick is {sorted(loaded)}")
    classes: dict[str, ClassInfo] = {}
    roots = {"equipment": (BRICK.Equipment, "equipment"), "points": (BRICK.Point, "point"),
             "systems": (BRICK.System, "system")}
    for kind in ("equipment", "points", "systems"):
        for group, names in subset.get(kind, {}).items():
            for name in names:
                uri = BRICK[name]
                if name in classes:
                    problems.append(f"brick_subset: {name} listed twice")
                elif not brick_has(uri, OWL.Class):
                    problems.append(f"brick_subset: {name} is not a Brick {version} class")
                elif deprecated(uri):
                    problems.append(f"brick_subset: {name} is deprecated in Brick {version}")
                else:
                    root, class_kind = roots[kind]
                    if uri != root and not _is_subclass(g, uri, root):
                        problems.append(f"brick_subset: {name} is listed under {kind} but is not a {root.split('#')[1]}")
                    classes[name] = ClassInfo(name, class_kind, group, "brick")
    # Locations: Brick 1.4 deprecated these in favour of RealEstateCore. They are accepted here, and only here,
    # while Brick still names the rec: class the file says replaces them.
    for group, entries in (subset.get("locations") or {}).items():
        for name, replacement in entries.items():
            uri = BRICK[name]
            if name in classes:
                problems.append(f"brick_subset: {name} listed twice")
            elif not brick_has(uri, OWL.Class):
                problems.append(f"brick_subset: location {name} is not a Brick {version} class")
            elif not str(replacement).startswith("rec:"):
                problems.append(f"brick_subset: location {name} must name the rec: class that replaces it, "
                                f"got {replacement!r}")
            else:
                if not _is_subclass(g, uri, BRICK.Location):
                    problems.append(f"brick_subset: {name} is listed under locations but is not a Location")
                if deprecated(uri):
                    said = g.value(uri, BRICK.isReplacedBy)
                    if said != REC[str(replacement)[4:]]:
                        problems.append(f"brick_subset: {name} is replaced by {said} in Brick {version}, "
                                        f"not {replacement}: update brick_subset.yaml")
                classes[name] = ClassInfo(name, "location", group, "brick", replaced_by=str(replacement))
    relations = list(subset.get("relations", []))
    for rel in relations:
        if not any(g.triples((BRICK[rel], RDF.type, None))):
            problems.append(f"brick_subset: relation {rel} is not in Brick {version}")

    # BA extension: parse into its own graph first to validate, then merge
    ext = rdflib.Graph()
    try:
        ext.parse(km_dir / "ba_extension.ttl", format="turtle")
    except Exception as e:  # noqa: BLE001 - report any parse failure as a problem
        problems.append(f"ba_extension.ttl does not parse: {e}")
    ba_relations = []
    for s in sorted(ext.subjects(RDF.type, OWL.Class)):
        name = str(s).split("#")[-1]
        if not str(s).startswith(str(BA)):
            problems.append(f"ba_extension: {s} is outside the ba: namespace")
            continue
        if brick_has(BRICK[name], OWL.Class):
            problems.append(f"ba_extension: {name} clashes with Brick class of the same name")
        if not ext.value(s, RDFS.label) or not ext.value(s, SKOS.definition):
            problems.append(f"ba_extension: {name} needs rdfs:label and skos:definition")
        for parent in ext.objects(s, RDFS.subClassOf):
            if not ((parent, RDF.type, OWL.Class) in ext or brick_has(parent, OWL.Class)):
                problems.append(f"ba_extension: parent {parent} of {name} is unknown")
            elif deprecated(parent):
                problems.append(f"ba_extension: parent {parent} of {name} is deprecated")
        if name in classes:
            problems.append(f"ba_extension: {name} defined twice")
        classes[name] = ClassInfo(name, "other", "ba_extension", "ba")
    for p in sorted(ext.subjects(RDF.type, OWL.ObjectProperty)):
        ba_relations.append(str(p).split("#")[-1])
        rname = ba_relations[-1]
        if not str(p).startswith(str(BA)):
            problems.append(f"ba_extension: relation {p} is outside the ba: namespace")
        if any(g.triples((BRICK[rname], RDF.type, None))):
            problems.append(f"ba_extension: relation {rname} clashes with Brick relation of the same name")
        if not ext.value(p, RDFS.label) or not (ext.value(p, RDFS.comment) or ext.value(p, SKOS.definition)):
            problems.append(f"ba_extension: relation {rname} needs rdfs:label and rdfs:comment")
        for sup in ext.objects(p, RDFS.subPropertyOf):
            if not (any(g.triples((sup, RDF.type, OWL.ObjectProperty))) or (sup, RDF.type, OWL.ObjectProperty) in ext):
                problems.append(f"ba_extension: parent relation {sup} of {rname} is unknown")
        for rng in list(ext.objects(p, RDFS.range)) + list(ext.objects(p, RDFS.domain)):
            if not ((rng, RDF.type, OWL.Class) in ext or brick_has(rng, OWL.Class)):
                problems.append(f"ba_extension: domain/range {rng} of {p} is unknown")
    merged = g + ext

    def km_uri(name: str) -> rdflib.URIRef:
        return BA[name] if classes.get(name) and classes[name].source == "ba" else BRICK[name]

    for name, info in classes.items():
        if info.source == "ba":
            if _is_subclass(merged, km_uri(name), BRICK.Point):
                info.kind = "point"
            elif _is_subclass(merged, km_uri(name), BRICK.Equipment):
                info.kind = "equipment"
        ancestors = [o for o in classes if o != name and _is_subclass(merged, km_uri(name), km_uri(o))]
        # nearest = the ancestor that is a subclass of every other ancestor
        nearest = [a for a in ancestors if all(a == b or _is_subclass(merged, km_uri(a), km_uri(b)) for b in ancestors)]
        info.subset_parent = nearest[0] if nearest else None

    # Terms the app writes must be declared (see WRITTEN_RELATIONS), so none is silently "off-standard".
    for rel in WRITTEN_RELATIONS:
        if rel not in ba_relations and rel not in relations:
            problems.append(f"the app writes relation {rel!r}, which is neither in brick_subset.yaml nor declared "
                            f"in ba_extension.ttl")
    tags_path = km_dir / "name_rules" / "equipment_tags.yaml"
    if tags_path.exists():
        for prefix, tag in (yaml.safe_load(tags_path.read_text()).get("prefixes") or {}).items():
            cls = tag.get("class")
            if cls and classes.get(cls, ClassInfo("", "", "", "")).kind != "equipment":
                problems.append(f"name_rules/equipment_tags.yaml: prefix {prefix} proposes class {cls!r}, "
                                f"which is not an equipment class in the model")

    # Templates
    templates: dict[str, Template] = {}
    raw_templates = {}
    for path in sorted((km_dir / "templates").glob("*.yaml")):
        if path.name == "anchors.yaml":  # 3D anchor map, checked by scripts/validate_km.py
            continue
        t = yaml.safe_load(path.read_text())
        where = f"templates/{path.name}"
        if t.get("id") != path.stem:
            problems.append(f"{where}: id {t.get('id')!r} must equal the file name")
        raw_templates[path.stem] = (t, where)
    for tid, (t, where) in raw_templates.items():
        if classes.get(t.get("brick_class"), ClassInfo("", "", "", "")).kind != "equipment":
            problems.append(f"{where}: brick_class {t.get('brick_class')} is not an equipment class in the model")
        patterns = []
        for p in t.get("name_patterns", []):
            try:
                patterns.append(re.compile(p, re.I))
            except re.error as e:
                problems.append(f"{where}: bad name pattern {p!r}: {e}")
        lo, hi = t.get("point_count", [0, 0])
        if not (0 < lo <= hi):
            problems.append(f"{where}: point_count must be [min, max] with 0 < min <= max")
        slots, roles = [], set()
        for s in t.get("points", []):
            if s["role"] in roles:
                problems.append(f"{where}: role {s['role']} repeated")
            roles.add(s["role"])
            for c in s["classes"]:
                if classes.get(c, ClassInfo("", "", "", "")).kind != "point":
                    problems.append(f"{where}: slot {s['role']} uses {c}, which is not a point class in the model")
            slots.append(Slot(s["role"], tuple(s["classes"]), bool(s.get("required", False)), s.get("medium", ""),
                              tuple(str(w) for w in s.get("words", []))))
        if not any(s.required for s in slots):
            problems.append(f"{where}: needs at least one required point slot")
        rels = []
        for r in t.get("relations", []):
            if r["rel"] not in relations:
                problems.append(f"{where}: relation {r['rel']} is not in the subset")
            if r["target"] not in raw_templates:
                problems.append(f"{where}: relation target {r['target']} is not a template")
            if r.get("system") and classes.get(r["system"], ClassInfo("", "", "", "")).kind != "system":
                problems.append(f"{where}: relation system {r['system']} is not a system class in the model")
            rels.append(Relation(r["rel"], r["target"], r.get("medium", ""), bool(r.get("required", False)),
                                 r.get("system", "")))
        templates[tid] = Template(tid, t.get("brick_class", ""), t.get("description", ""), patterns,
                                  (lo, hi), slots, rels)

    # Name rules
    nr = yaml.safe_load((km_dir / "name_rules" / "abbreviations.yaml").read_text())
    tok = nr["tokenizer"]
    vocabulary = {str(w) for w in nr["vocabulary"]}
    if len(vocabulary) != len(nr["vocabulary"]):
        problems.append("abbreviations.yaml: vocabulary has duplicates")
    abbreviations: dict[str, list[list[str]]] = {}
    sep = re.compile(tok["separators"])
    for key, val in nr["abbreviations"].items():
        key = str(key)
        alts = val if val and isinstance(val[0], list) else [val]
        alts = [[str(w) for w in a] for a in alts]
        for a in alts:
            for w in a:
                if w not in vocabulary:
                    problems.append(f"abbreviations: {key} expands to {w!r}, which is not in the vocabulary")
        if sep.search(key):
            problems.append(f"abbreviations: key {key!r} contains a separator, so the tokenizer can never produce it")
        abbreviations[key.lower()] = alts
    name_rules = NameRules(sep, bool(tok["split_camel_case"]), bool(tok["split_letter_digit"]),
                           bool(tok["lowercase"]), vocabulary, abbreviations,
                           {str(k): [str(w) for w in v] for k, v in (nr.get("examples") or {}).items()},
                           {str(k).lower(): str(v).lower() for k, v in (tok.get("phrases") or {}).items()})
    for text, token in name_rules.phrases.items():
        if sep.search(token) or name_rules.expand(token) is None:
            problems.append(f"abbreviations: phrase {text!r} -> {token!r} must be a single known token")
    for t in templates.values():
        for slot in t.slots:
            for w in slot.words:
                if w not in vocabulary:
                    problems.append(f"templates/{t.id}.yaml: slot {slot.role} word {w!r} is not in the vocabulary")
    for name, expected in name_rules.examples.items():
        got = name_rules.words(name)
        if got != expected:
            problems.append(f"abbreviations: example {name!r} parses to {got}, expected {expected}")

    # Class matching
    cm = yaml.safe_load((km_dir / "name_rules" / "class_matching.yaml").read_text())
    class_matching = ClassMatching(
        name_synonyms={str(k): str(v or "") for k, v in cm["name_synonyms"].items()},
        class_word_synonyms={tuple(str(k).lower().split()): str(v or "") for k, v in cm["class_word_synonyms"].items()},
        functions=[str(f) for f in cm["functions"]],
        default_function=str(cm["default_function"]),
        quantities={str(q) for q in cm["quantities"]},
        command_cues={str(c) for c in cm["command_cues"]},
        point_implies={str(k): [str(w) for w in v] for k, v in (cm.get("point_implies") or {}).items()},
    )
    for k, ws in class_matching.point_implies.items():
        for w in ws:
            if w not in vocabulary:
                problems.append(f"class_matching: point_implies {k} -> {w!r} is not in the vocabulary")
    for group in ("functions", "quantities", "command_cues"):
        for w in cm[group]:
            if str(w) not in vocabulary:
                problems.append(f"class_matching: {group} word {w!r} is not in the vocabulary")
    if class_matching.default_function not in class_matching.functions:
        problems.append("class_matching: default_function must be one of functions")
    for k, v in class_matching.name_synonyms.items():
        if v and v not in vocabulary and v not in {w for c in classes for w in class_matching.class_words(c)}:
            problems.append(f"class_matching: name synonym {k} -> {v!r} is neither a vocabulary word nor a class word")

    if problems:
        raise KnowledgeModelError(problems)
    km = KnowledgeModel(version, classes, relations, ba_relations, templates, name_rules, class_matching, merged)
    if conventions:
        from .conventions import CONV_DIR, apply_conventions, load_layers
        km = apply_conventions(km, load_layers(conventions, conventions_dir or CONV_DIR))
    return km
