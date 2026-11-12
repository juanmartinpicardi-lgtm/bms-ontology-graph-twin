# Conventions

Naming rules for one contractor, customer or site, layered on top of the knowledge model.
Spec: `docs/spec-tribal-knowledge.md` §4. Loader: `src/projectmodel/conventions.py`.

| Belongs here | Belongs elsewhere |
|---|---|
| Knowledge that **changes how a name is read** on this contractor/customer/site: "CC means …", "ZN-3 is a VAV" | Reusable for every project → `knowledge_model/`. Describes the building or how it behaves → a note (T1). |

## Files

```
projects.yaml               which scopes apply to which project
contractor/<name>.yaml      e.g. contractor/acme-controls.yaml
customer/<name>.yaml
site/<name>.yaml            e.g. site/alpha.yaml
```

A file holds any of these (same shapes as the knowledge model, checked with the same rules):

```yaml
scope: site/alpha              # must match the file's path
description: ...
author: ana
abbreviations:                 # as knowledge_model/name_rules/abbreviations.yaml; [] = token with no class meaning
  cc: [chiller, condenser]
equipment_patterns:            # extra name patterns per template id
  vav: ['\bZN[-_ ]?\d']
class_hints:                   # whole-name regex -> point class; decides the class, templates don't refine it
  - {pattern: '(?i)^occupied status$', class: Occupancy_Status}
ignore:                        # dead/unused points: still mapped and scored, but always sent to review
  - {pattern: '^RF VFD', reason: 'Return fan removed 2022'}
```

## Layering

knowledge model ← contractor ← customer ← site. Abbreviations: a later layer overrides a token.
Equipment patterns extend. Class hints and ignore rules extend, a later layer's are tried first, and
the same pattern text replaces an earlier layer's entry. The base model files are never changed.

## Provenance and checks

- Anything a convention decides is recorded on the node: `attrs.convention = ["site/alpha:abbreviations.cc", …]`
  (class hints also make the point `method=rule`). The review Tree and the 3D details panel show it.
- `.venv/bin/python scripts/validate_km.py --project alpha/names_paths` validates the merged model.
  A problem names the file and the key.
- The score report says which conventions every column used.

## Honest measurement

Write and tune conventions on **Alpha** only. A held-out test site's conventions may only contain what a site
engineer would tell us before seeing our output; it is reported twice, blind and with conventions.
