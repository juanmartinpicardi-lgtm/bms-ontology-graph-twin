"""Check which models this machine can call on Vertex AI: one tiny call per model, each logged to llm_calls.

    .venv/bin/python scripts/ai_check.py                  # every model in ai/models.py
    .venv/bin/python scripts/ai_check.py haiku sonnet     # just these
    .venv/bin/python scripts/ai_check.py --job point_class  # one real run of a job

Needs Application Default Credentials (`gcloud auth application-default login`) and a GCP project (see
projectmodel/ai/config.py). Costs a fraction of a cent per model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.ai import MODELS, ModelError, ModelRequest, ModelUnavailable, Router, run_job  # noqa: E402
from projectmodel.ai.config import load_config  # noqa: E402
from projectmodel.db.store import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=list(MODELS))
    ap.add_argument("--job", help="run one job on a sample input instead")
    ap.add_argument("--model", help="with --job: run it on this model instead of the job's default (no escalation)")
    ap.add_argument("--db", default=str(ROOT / "data/kg.sqlite"))
    args = ap.parse_args()

    cfg = load_config()
    print(f"project={cfg.project} region={cfg.region} regions={cfg.regions} ready={cfg.ready} {cfg.why_off}")
    if not cfg.ready:
        return 1
    store, router = Store(args.db), Router(cfg)

    if args.job == "point_class":
        cands = ["Zone_Air_Temperature_Sensor", "Discharge_Air_Temperature_Sensor", "Zone_Air_Temperature_Setpoint"]
        res = run_job("point_class", {"name": "ZN-T", "path": "Floor 2/VAV-2-14", "equipment_class": "VAV",
                                      "candidates": "\n".join(f"- {c}" for c in cands), "candidate_list": cands},
                      router=router, store=store, project="ai_check", model=args.model)
        print(res.output, res.model, f"${res.cost_usd:.5f}", f"{res.latency_s:.2f}s", res.attempts)
        return 0

    failed = 0
    for key in args.models:
        m = MODELS[key]
        req = ModelRequest("Answer in one word.", [{"role": "user", "content": "What does HVAC's V stand for?"}],
                           max_tokens=200)
        try:
            r = router.call(key, req, job="health_check", store=store, project="ai_check")
            print(f"ok    {key:9} {m.id:24} {r.text.strip()[:30]!r:34} ${r.cost_usd:.6f} {r.latency_s:.2f}s")
        except (ModelError, ModelUnavailable) as e:
            failed += 1
            print(f"FAIL  {key:9} {m.id:24} {str(e)[:160]}")
    return 1 if failed == len(args.models) else 0


if __name__ == "__main__":
    raise SystemExit(main())
