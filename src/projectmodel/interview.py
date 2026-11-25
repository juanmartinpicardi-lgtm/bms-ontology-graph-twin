"""Interview mode (plan-workflow-ai §6.2 row 9, W10): a short scripted interview with a site person. Every answer
becomes a note (source interview); answers that state a naming rule in the shape the question asks for also become
proposed conventions, which wait for a person's approval like any other (curator.py).

    QUESTIONS                                    the script: id, note topic, question
    capture(store, km, project, answers, person) -> {"notes": [...], "proposals": [...], "unread": [...]}

Rules only, no model: an abbreviation ("CC means chiller condenser") is proposed only when every word is in the
knowledge model's vocabulary; a class statement ("Occupied status points are Occupancy_Command") only when the class is
a point class of the knowledge model and the pattern contradicts no person's decision. Anything else stays a note and
is listed as unread, with why. The voice dock can feed the same function with its transcripts (agent/voice.py).
"""

from __future__ import annotations

import re
import time

from . import curator, notes
from .db.store import Store
from .knowledge_model import KnowledgeModel
from .review import name_words

QUESTIONS = [
    ("contractor", "naming", "Who installed the controls here, and is there anything special about how they name "
                             "points?"),
    ("abbreviations", "naming", "Do the point names use an abbreviation that means something particular in this "
                                "building? Say it like: “CC means chiller condenser”, one per sentence."),
    ("classes", "naming", "Is any kind of point named in a way that hides what it really is? Say it like: “Occupied "
                          "status points are Occupancy_Command”, one per sentence."),
    ("history", "history", "Was any equipment replaced, removed or added since the drawings were made?"),
    ("unused", "maintenance", "Are there points or equipment that are dead, unused or always wrong?"),
    ("operations", "operations", "Which areas or units cause the most complaints (too hot, too cold, noisy), and why?"),
]
ABBR = re.compile(r"^\s*[“\"']?([A-Za-z][A-Za-z0-9]{0,7})[”\"']?\s+(?:means|stands for|is short for|=)\s+(.+?)\s*$",
                  re.I)
CLASS = re.compile(r"^\s*[“\"']?(?:the\s+)?(.+?)[”\"']?(?:\s+points?)?\s+(?:are|is)\s+(?:an?\s+)?([A-Za-z_ ]+?)\s*$",
                   re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip(" .") for s in re.split(r"[.;\n]+", text or "") if s.strip(" .")]


def _point_class(km: KnowledgeModel, text: str) -> str | None:
    want = re.sub(r"[\s_]+", "_", text.strip()).lower()
    return next((c for c in km.by_kind("point") if c.lower() == want), None)


def capture(store: Store, km: KnowledgeModel, project: str, answers: dict[str, str], person: str,
            interview_id: str | None = None) -> dict:
    """File each answer as a note and propose the naming rules the answers state (see the module docstring)."""
    if not person.strip():
        raise ValueError("an interview needs the name of the person interviewed")
    iid = interview_id or f"i-{int(time.time())}"
    topics = {q: t for q, t, _ in QUESTIONS}
    asked = {q: text for q, _, text in QUESTIONS}
    out = {"interview": iid, "notes": [], "proposals": [], "unread": []}
    for qid, answer in answers.items():
        if qid not in topics or not (answer or "").strip():
            continue
        out["notes"].append(notes.add_note(store, project, "project", "", "", topics[qid],
                                           f"{asked[qid]}\n\n{answer.strip()}", person, source="interview",
                                           source_ref=f"{iid}:{qid}"))
    graph = curator._graph(store, project)
    nr = km.name_rules
    with store.conn:
        for s in _sentences(answers.get("abbreviations", "")):
            m = ABBR.match(s)
            if not m:
                out["unread"].append({"answer": s, "why": "not in the shape “X means …”"})
                continue
            token, words = m.group(1).lower(), [w.lower() for w in re.split(r"[\s,]+", m.group(2)) if w]
            words = [w for w in words if w not in ("a", "an", "the")]
            missing = [w for w in words if w not in nr.vocabulary]
            if missing or nr.separators.search(token):
                out["unread"].append({"answer": s, "why": f"not in the vocabulary: {', '.join(missing)}" if missing
                                      else "the abbreviation has a separator in it"})
                continue
            hits = [p["name"] for p in graph.values() if token in nr.tokenize(p["name"])]
            pid = curator.record(
                store, project, "abbreviations", {"token": token, "words": words},
                f"“{token.upper()}” means {' '.join(words)} in this building's names",
                f"{person} said so in an interview: “{s}”. {len(hits)} point names here have the token.",
                [{"node": "", "name": s, "before": None, "after": " ".join(words), "by": person, "source": "interview",
                  "at": iid}],
                {"knowledge_model": "ok", "would_change": len(hits), "examples": hits[:curator.EXAMPLES],
                 "phrased_by": "rules"}, extra={"interview": iid})
            if pid:
                out["proposals"].append(pid)
        for s in _sentences(answers.get("classes", "")):
            m = CLASS.match(s)
            cls = _point_class(km, m.group(2)) if m else None
            if not m or not cls:
                out["unread"].append({"answer": s, "why": "no point class of the knowledge model named" if m
                                      else "not in the shape “… points are <class>”"})
                continue
            words = [w for w in name_words(m.group(1)) if w not in ("the", "points", "point")]
            if not words:
                out["unread"].append({"answer": s, "why": "no name words to recognise the points by"})
                continue
            pattern = "(?i)^" + "".join(f"(?=.*{curator._w(w)})" for w in words)
            rx = re.compile(pattern)
            match = [pid for pid, p in graph.items() if rx.search(p["name"])]
            contra = [p for p in match if graph[p]["human"] and graph[p]["class"] != cls]
            if contra:
                out["unread"].append({"answer": s, "why": f"contradicts {len(contra)} decisions people made"})
                continue
            change = [p for p in match if graph[p]["class"] != cls]
            pid = curator.record(
                store, project, "class_hints", {"pattern": pattern, "class": cls},
                f"Points whose name has {' and '.join(f'“{w}”' for w in words)} are {cls}",
                f"{person} said so in an interview: “{s}”. It would change {len(change)} points here now.",
                [{"node": "", "name": s, "before": None, "after": cls, "by": person, "source": "interview",
                  "at": iid}],
                {"knowledge_model": "ok", "would_change": len(change),
                 "examples": [graph[p]["name"] for p in change[:curator.EXAMPLES]], "phrased_by": "rules"},
                extra={"interview": iid})
            if pid:
                out["proposals"].append(pid)
    return out
