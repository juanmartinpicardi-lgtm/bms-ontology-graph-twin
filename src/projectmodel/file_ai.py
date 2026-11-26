"""Model readers for any file (fileread.py gives the text or images):

    propose_knowledge(...)  the guided setup's Knowledge step: rules (tag prefixes, point terms) and notes a file teaches,
                            each quoting the file, for the person to confirm one by one (job knowledge_extract)
    digest(...)             the Documentation page: what a document is, its category, the equipment it names
                            (job document_digest)

Candidates in, choices out: a class must be one the knowledge model lists, and a quote must be found in the file's
text, else the output fails its check and the next model in the chain is tried. Every call is logged by the router.
Nothing is written until a person confirms it.
"""
from __future__ import annotations

import base64
import re
from typing import Any

from .fileread import Content

MAX_CHARS = 60_000


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


_S = {"type": "string"}
KNOWLEDGE_SCHEMA = _obj({
    "tags": {"type": "array", "items": _obj({"prefix": _S, "class": _S, "family": _S, "terminal": {"type": "boolean"},
                                             "quote": _S})},
    "terms": {"type": "array", "items": _obj({"phrase": _S, "class": _S, "quote": _S})},
    "notes": {"type": "array", "items": _obj({"target_label": _S, "topic": _S, "body": _S, "quote": _S})},
})
DIGEST_SCHEMA = _obj({
    "category": _S, "title": _S, "summary": _S,
    "equipment": {"type": "array", "items": _S},
    "useful_for": {"type": "array", "items": _S},
    "quote": {"type": "array", "items": _S},
})


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _quoted(quote: str, text: str) -> bool:
    """The quote is in the text, ignoring spacing and case; an empty text (an image) cannot be checked."""
    return not text.strip() or _norm(quote)[:120] in _norm(text)


def check_knowledge(out: Any, values: dict) -> str | None:
    eq, pt = set(values["_equipment"]), set(values["_point"])
    text = values.get("_text", "")
    for t in out["tags"]:
        if t["class"] not in eq:
            return f"tag {t['prefix']}: {t['class']} is not an equipment class in the list"
        if t["family"] not in values["_families"]:
            return f"tag {t['prefix']}: unknown family {t['family']}"
        if not re.fullmatch(r"[A-Za-z]{1,6}", t["prefix"]):
            return f"tag prefix {t['prefix']!r} is not letters only"
    for t in out["terms"]:
        if t["class"] not in pt:
            return f"term {t['phrase']}: {t['class']} is not a point class in the list"
    for n in out["notes"]:
        if n["topic"] not in values["_topics"]:
            return f"note: unknown topic {n['topic']}"
    for item in out["tags"] + out["terms"] + out["notes"]:
        if not _quoted(item["quote"], text):
            return f"quote not found in the file: {item['quote'][:60]!r}"
    return None


def check_digest(out: Any, values: dict) -> str | None:
    if out["category"] not in values["_categories"]:
        return f"{out['category']} is not one of the categories"
    for q in out["quote"]:
        if not _quoted(q, values.get("_text", "")):
            return f"quote not found in the file: {q[:60]!r}"
    return None


def _images(content: Content) -> list[dict]:
    return [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(b).decode()}}
            for mt, b in content.images[:3]]


def _text(content: Content) -> str:
    t = content.text
    if len(t) > MAX_CHARS:
        t = t[:MAX_CHARS] + f"\n[… {len(content.text) - MAX_CHARS:,} more characters not shown]"
    return t or "(no text: see the image)"


def propose_knowledge(content: Content, file_name: str, building: str, equipment_classes: list[str],
                      point_classes: list[str], *, store=None, project: str = "", router=None) -> dict:
    """{"tags", "terms", "notes", "model", "cost_usd"}: what the file teaches, unconfirmed. Raises ModelUnavailable
    when AI is off and ModelError when no model produced a valid answer."""
    from .ai.jobs import run_job
    from .intake.knowledge import FAMILIES
    from .notes import TOPICS
    values = {"building": building, "file_name": file_name, "kind": content.kind, "text": _text(content),
              "families": ", ".join(FAMILIES), "topics": ", ".join(TOPICS),
              "equipment_classes": ", ".join(equipment_classes), "point_classes": ", ".join(point_classes),
              "_equipment": equipment_classes, "_point": point_classes, "_families": FAMILIES, "_topics": TOPICS,
              "_text": content.text}
    res = run_job("knowledge_extract", values, router=router, store=store, project=project,
                  user_content=_images(content) or None)
    return {**res.output, "model": res.model, "cost_usd": res.cost_usd}


def digest(content: Content, file_name: str, project: str, categories: list[str], *, store=None,
           router=None) -> dict:
    from .ai.jobs import run_job
    values = {"project": project, "file_name": file_name, "kind": content.kind, "text": _text(content),
              "categories": ", ".join(categories), "_categories": categories, "_text": content.text}
    res = run_job("document_digest", values, router=router, store=store, project=project,
                  user_content=_images(content) or None)
    return {**res.output, "model": res.model, "cost_usd": res.cost_usd}
