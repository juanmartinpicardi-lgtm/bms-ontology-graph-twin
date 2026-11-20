# Knowledge: memory and skills

How our engineers work, kept per scope, used by the readers, the mapper and the agent.
Spec: `docs/spec-memory-skills.md`. Loader and checks: `src/projectmodel/memory.py`.

```
memory/global.yaml                       principles and methods for every project (cap 4,000 characters)
memory/designer/<firm>.yaml              the engineering firm that drew the plans and schedules (2,500)
memory/contractor/<name>.yaml            the controls contractor (2,500)
memory/customer/<name>.yaml              the owner's standards (2,500)
memory/site/<slug>.yaml                  one building (2,500)
people/<name>.yaml                       one person's profile (1,200; never changes outputs)
skills/<scope path>/<skill-name>/        SKILL.md, optional rules/*.yaml and references/*.md
```

Which scopes apply to a project: `conventions/projects.yaml`. The more specific scope wins; a conflict between
scopes is shown, never silently resolved.

| Kind | Example | Changes outputs? |
|---|---|---|
| Memory entry | "Design documents state intent; the submittal and BMS state what is installed." | No |
| Skill | "Read a Metasys controls submittal" | Only through its `rules/` |
| Skill rules | Schedule column layouts of one firm | Yes, and must not lower the dev-set score |

Rule of thumb: if it changes how a document or name is read, it is a skill rule; if it says how we work or what is
true about a party, it is memory; if it describes one building, it stays a note.

Check every file: `.venv/bin/python -m pytest tests/test_memory.py`.
