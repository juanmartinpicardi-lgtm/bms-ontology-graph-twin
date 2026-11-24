"""Page sorting for any upload (plan-workflow-ai W6): what each page of a PDF is, before a reader sees it.

Kinds: plan, schedule, sequence, riser, submittal, other. Rules first, from the words on the page:
1. The sheet number (pdfdoc.sheet_id: M-101, M201, M.201, M1.0) gives the discipline (M, A, E, P, FP...).
2. Title-like lines (short lines, any case) name the kind: "... PLAN", "... SCHEDULE(S)", "SEQUENCE OF OPERATION(S)",
   "RISER", "POINTS LIST", "COVER", "DETAILS"... A note that only mentions one ("SEE ROOF PLAN FOR CONTINUATION") is
   not a title.
3. One kind clearly ahead of the others sorts the page (by "rule"). A page with no text layer, no title-like line, or
   two kinds about as strong is left `unsorted`: the model sorts it (`plan_meaning` answers the page kind with the
   rest of its reading, `plan_ai.py`), so only those pages cost a model call.

The sort never changes what the rules-only readers read: the plans step logs it, and the AI plan reader uses it to
pick the pages worth a model call.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import pdfdoc

KINDS = ("plan", "schedule", "sequence", "riser", "submittal", "other")
# A title-like line: short, and not a note pointing somewhere else
NOT_TITLE = re.compile(r"^TO\b|\bPRIOR TO\b|\b(SEE|REFER|FOR CONTINUATION|ON PLANS?|PER PLAN|SHOWN|PROVIDE|ROUTE|INSTALL|CONNECT|"
                       r"COORDINATE|IN ACCORDANCE|AS INDICATED|WHERE|FURTHER|ADDITIONAL|REQUIREMENTS)\b")
SIGNALS: dict[str, re.Pattern] = {
    "sequence": re.compile(r"SEQUENCES? OF (?:OPERATIONS?|CONTROLS?)|CONTROL SEQUENCES?|\bSEQUENCES?\b$"),
    "schedule": re.compile(r"(?:^|\s)SCHEDULES?$|(?:^|\s)SCHEDULES\b"),
    "riser": re.compile(r"\b(?:NETWORK|CONTROLS?|BAS|BMS|COMMUNICATIONS?|SYSTEM|TRUNK)\s+RISER\b|\bRISER DIAGRAM\b|"
                       r"NETWORK (?:ARCHITECTURE|DIAGRAM)|SYSTEM ARCHITECTURE"),
    "submittal": re.compile(r"\bSUBMITTAL\b|\bPOINTS? LISTS?\b|\bPOINT SCHEDULES?\b|\bPOINTS? SCHEDULE\b"),
    "plan": re.compile(r"\bPLANS?\b"),
    "other": re.compile(r"\bCOVER SHEET\b|\bTITLE SHEET\b|\bSHEET INDEX\b|\bDRAWING INDEX\b|\bDETAILS\b$|"
                        r"\bABBREVIATIONS\b|\bCOMCHECK\b|\bSPECIFICATIONS?\b$|\bDIAGRAMS?\b$"),
}
NOT_PLAN = re.compile(r"\bSITE PLAN\b|\bKEY PLAN\b|\bPLAN NOTES?\b|\bPLAN REVIEW\b|\bPLANS? AND SPEC")
DISCIPLINE = re.compile(r"^([A-Z]{1,2})[-.]?\d")


@dataclass
class PageSort:
    page: int
    kind: str                 # one of KINDS, or "unsorted"
    by: str                   # rule | llm | none
    sheet: str = ""
    discipline: str = ""
    titles: list[str] = field(default_factory=list)  # the title-like lines that decided it
    why: str = ""
    confidence: float = 0.0

    def to_json(self) -> dict:
        return {"page": self.page, "kind": self.kind, "by": self.by, "sheet": self.sheet,
                "discipline": self.discipline, "titles": self.titles[:4], "why": self.why,
                "confidence": self.confidence}


def _title_lines(ws) -> list[tuple[str, float]]:
    out = []
    for line in pdfdoc.lines(ws, gap=12):
        t = re.sub(r"\s+", " ", line.text.upper()).strip(" .:-")
        n = len(t.split())
        if not t or n > 9 or NOT_TITLE.search(t) or not re.search(r"[A-Z]{3}", t):
            continue
        out.append((t, max(w.size for w in line.words)))
    return out


def classify_words(ws, page: int = 0) -> PageSort:
    """Sort one page from its words (rules only)."""
    sheet = pdfdoc.sheet_id(ws)
    disc = (m.group(1) if (m := DISCIPLINE.match(sheet)) else "")
    if not ws:
        return PageSort(page, "unsorted", "none", sheet, disc, why="no text layer (a scan?)")
    score: Counter = Counter()
    hits: dict[str, list[str]] = {}
    for t, size in _title_lines(ws):
        for kind, rx in SIGNALS.items():
            if not rx.search(t):
                continue
            if kind == "plan" and NOT_PLAN.search(t):
                continue
            if kind == "schedule" and "POINT" in t:
                continue  # a point schedule is a points list
            score[kind] += 1 + (size >= 12)  # a large title counts double
            hits.setdefault(kind, []).append(t)
    if not score:
        return PageSort(page, "unsorted", "none", sheet, disc, why="no title-like line names a kind")
    (k1, s1), *rest = score.most_common()
    s2 = rest[0][1] if rest else 0
    # A plan sheet carries schedule-like lines too ("FAN COIL SCHEDULE" in a legend); a points list sits on a
    # sequence sheet: the stronger kind wins only when clearly ahead.
    if s1 >= 2 * s2 + 1 or (s1 >= 3 and s1 >= 1.5 * s2):
        conf = 0.95 if not s2 else 0.85
        return PageSort(page, k1, "rule", sheet, disc, hits[k1], f"{s1} title line(s) say {k1}"
                        + (f", {s2} say {rest[0][0]}" if s2 else ""), conf)
    return PageSort(page, "unsorted", "none", sheet, disc, hits.get(k1, []) + hits.get(rest[0][0], []),
                    f"{k1} ({s1}) and {rest[0][0]} ({s2}) are about as strong")


def sort(path: Path) -> list[PageSort]:
    """Every page of a PDF, sorted by the rules (pages the rules can't sort are `unsorted`)."""
    p = Path(path)
    return [classify_words(pdfdoc.words(p, i), i) for i in range(pdfdoc.page_count(p))]


def summary(sorted_pages: list[PageSort]) -> str:
    c = Counter(s.kind for s in sorted_pages)
    return ", ".join(f"{n} {k}" for k, n in c.most_common())
