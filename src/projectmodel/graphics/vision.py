"""Optional vision QA of a generated equipment graphic, after the rule QA (qa.py): the PNG plus the list of cards
drawn on it go to the `graphic_qa` job through the ai/ router, candidates in, ids out. The model can only flag cards
we drew; its findings are added to the QA result as warnings, never as passes. Every call is logged by the router
(input, output, cost, latency) like any other.
"""

from __future__ import annotations

import base64

from .drawing import Drawing


def cards(d: Drawing) -> list[dict]:
    """The drawing's point cards with ids C1, C2... and the point labels inside each."""
    out = []
    labels = d.of_kind("label")
    for k, c in enumerate(d.of_kind("card"), 1):
        x0, y0, x1, y1 = c.bbox()
        names = [s.geo["text"] for s in labels if x0 <= s.geo["x"] <= x1 and y0 <= s.geo["y"] <= y1]
        out.append({"id": f"C{k}", "part": c.ref, "points": names})
    return out


def vision_check(payload: dict, graphic, *, router=None, store=None, project: str = "", model: str | None = None
                 ) -> dict:
    """{"rule": "vision", ...} for the QA list, with the model, cost and the issues. Raises ModelUnavailable when AI
    is off, like every job."""
    from ..ai.jobs import run_job

    cs = cards(graphic.drawing)
    png = graphic.png("light", 1.5)
    values = {"equipment": payload["equipment"]["label"], "template": graphic.template,
              "cards": "\n".join(f"{c['id']}: {', '.join(c['points']) or '(expected, not found)'} -> {c['part']}"
                                 for c in cs),
              "card_ids": [c["id"] for c in cs]}
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                       "data": base64.b64encode(png).decode()}}
    res = run_job("graphic_qa", values, router=router, store=store, project=project, model=model, user_content=[img])
    by_id = {c["id"]: c for c in cs}
    issues = [{**i, "part": by_id[i["card"]]["part"], "points": by_id[i["card"]]["points"]}
              for i in res.output["issues"]]
    return {"rule": "vision", "ok": not issues, "level": "warn" if issues else "ok",
            "detail": (f"{res.model}: no issue" if not issues else
                       f"{res.model}: {len(issues)} card{'s' * (len(issues) != 1)} flagged"),
            "refs": [i["card"] for i in issues], "issues": issues, "model": res.model,
            "cost_usd": round(res.cost_usd, 4), "latency_s": round(res.latency_s, 1)}
