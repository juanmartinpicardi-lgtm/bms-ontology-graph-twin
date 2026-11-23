"""Prompts: one Markdown file per prompt in `ai/prompts/`, versioned in its frontmatter.

    ---
    id: point_class
    version: 1
    description: ...
    ---
    # System
    ...instructions...
    # User
    ...the per-call part, with $placeholders...

Placeholders use `string.Template` ($name), so JSON braces in a prompt need no escaping. A change to a prompt's
wording bumps its version; every call logs `id@version`, so a score change can be traced to the prompt that caused it.
"""

from __future__ import annotations

import functools
import string
from dataclasses import dataclass
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    description: str
    system: str
    user: str

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    def render(self, **values: object) -> tuple[str, str]:
        """(system, user) with the placeholders filled. A missing value is an error, not a silent gap."""
        vals = {k: str(v) for k, v in values.items()}
        return string.Template(self.system).substitute(vals), string.Template(self.user).substitute(vals)


def _section(body: str, title: str) -> str:
    marker = f"# {title}\n"
    if marker not in body:
        return ""
    rest = body.split(marker, 1)[1]
    for other in ("\n# System\n", "\n# User\n"):
        rest = rest.split(other, 1)[0]
    return rest.strip()


@functools.cache
def load_prompt(prompt_id: str) -> Prompt:
    path = PROMPTS_DIR / f"{prompt_id}.md"
    if not path.exists():
        raise KeyError(f"no prompt {prompt_id!r} in {PROMPTS_DIR}")
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: missing frontmatter")
    _, front, body = text.split("---\n", 2)
    meta = yaml.safe_load(front) or {}
    if meta.get("id") != prompt_id or not isinstance(meta.get("version"), int):
        raise ValueError(f"{path.name}: frontmatter needs id: {prompt_id} and an integer version")
    body = "\n" + body
    system = _section(body, "System")
    if not system:
        raise ValueError(f"{path.name}: needs a '# System' section")
    return Prompt(prompt_id, meta["version"], meta.get("description", ""), system, _section(body, "User"))


def all_prompts() -> list[Prompt]:
    return [load_prompt(p.stem) for p in sorted(PROMPTS_DIR.glob("*.md"))]
