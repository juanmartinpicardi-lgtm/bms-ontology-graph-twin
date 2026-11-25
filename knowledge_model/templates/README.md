# Equipment templates

One YAML file per equipment type. The mapper uses them to ask "does this group of points look
like a VAV?" and to check what is missing.

```yaml
id: vav                     # unique, = file name
brick_class: VAV            # must be in brick_subset.yaml
description: ...
name_patterns: ['\bVAV\b']  # regexes (case-insensitive) on the equipment / folder name
point_count: [4, 20]        # typical number of points; outside this is a hint, not a rule
points:                     # slots; a point fills a slot if its class is one of `classes` or a subclass
  - role: zone_temp
    classes: [Zone_Air_Temperature_Sensor]
    required: true          # a group without it is a weak match
    medium: hot_water       # optional: a filled slot shows the equipment uses this medium
    words: [heating, hot]   # optional: name words that pick this slot over an earlier slot with the same class
relations:                  # expected links to other equipment (template ids)
  - {rel: isFedBy, target: ahu, medium: air, required: false}
  - {rel: isFedBy, target: boiler, medium: hot_water, system: Hot_Water_System}
```

Feeds are inferred two ways:
- **Folder**: a parent folder feeds a child when one of their templates says so (AHU feeds VAV).
- **Medium**: equipment fed by a water medium (`isFedBy` with a `medium`) gets a feeds link only when
  one of its slots with that `medium` is filled (e.g. it has a reheat valve). The source is the site's
  single top-level system of class `system` (e.g. the one Hot_Water_System), else the single equipment
  of the `target` template; with several candidates nothing is inferred.

Where each slot sits on the 3D equipment model is in `anchors.yaml` (see below).

The loader validates: id matches file name, classes exist in the subset (or BA extension),
regexes compile, roles are unique, relation targets are known templates, and `rel` is a subset relation.

## anchors.yaml

Where each slot role sits on the 3D model of its equipment type (`docs/spec-equipment-3d.md` §3.2). Per type:
`parts` (the named objects the geometry code builds), `sub_equipment` (class of an untemplated part such as
`SF VFD` → the part its points attach to) and `anchors` (role → `{part, at}`, `at` is 0–1 along a duct).
`scripts/validate_km.py` checks that every slot role of a drawn type has an anchor, every anchor names a real role,
and every part is declared. Every template has a section: the 3D builders (`app/equipment3d/`) and the 2D graphics
(`src/projectmodel/graphics/layouts.py`) draw the same named parts, so a point lands on the same part in both.

Which template an equipment gets is resolved from the graph (`equipment_view.template_for`): the template of the most
specific class it is (an RVAV is a VAV, so `rvav` wins over `vav`); else, for a generic class (a mini-split typed
`HVAC_Equipment`), the template whose name pattern matches and whose class is a subclass of it; else the template the
mapper wrote on the node. `meter.yaml` has no name patterns on purpose: a meter's class from its name is more
specific than `Meter`, and matching by name would overwrite it.
