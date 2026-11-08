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
relations:                  # expected links to other equipment (template ids)
  - {rel: isFedBy, target: ahu, medium: air, required: false}
```

The loader validates: id matches file name, classes exist in the subset (or BA extension),
regexes compile, roles are unique, relation targets are known templates, and `rel` is a subset relation.
