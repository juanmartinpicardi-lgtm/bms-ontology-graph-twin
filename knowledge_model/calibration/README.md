# Calibration per job

One file per job: the isotonic curves that turn the job's raw confidence into the accuracy measured on the dev sets
(`src/projectmodel/calibration.py`, plan-workflow-ai §6.1 principle 6). Loaded at run time; `PM_CALIBRATION=off`
gives raw confidences.

| File | Where it is applied | Strata (most specific first, then `*`) | Fitted on |
|---|---|---|---|
| `mapper.json` | `mapper/pipeline.py`, after the templates, before the model step: rule and template point classes (a convention's class hint is left as it is) | `<method>\|<function>\|<path or name>`, `<method>\|<function>`, `<function>` | Alpha `names_paths` + `names_only` |
| `intake.json` | `intake/submittal.py` and `intake/bms.py`, where a point's class confidence is made (a person's term is left as it is) | `<step>\|<function>`, `<function>` | Troop D |
| `point_class.json` | `mapper/llm.py` and `intake/point_ai.py`, on the model's own confidence, before the cap below auto-accept | `<model>\|<caller>` (`intake` or `mapper`), `<model>` | Troop D + Alpha points below auto-accept |
| `sequence_read.json` | `intake/sequence_ai.py`, on the model's confidence in each control relation, before the cap (0.85) | `<model>\|intake`, `<model>` | Troop D's 5 sequences vs `data/ground_truth/troop_d/sequences.yaml` (folds by sequence section) |

`function` is the point function the class names (Sensor, Setpoint, Command, Status, Alarm, other); `path or name`
is whether the point came with an equipment folder path. A stratum with fewer than 20 fitting items (`MIN_N`) falls
back to the next key; a band counts toward the 5-point rule from 30 items (`BAND_N`).

## How calibrated confidence meets auto-accept

The curves only change confidence values. What confirms a row with no person is the store's rule, `db.store.AutoAccept`
(`PM_AUTO_ACCEPT`, 0.9 by default), applied by `settle()`; the setup's in-session `intake.state.AUTO_ACCEPT` is the same
0.9. `scripts/eval.py` reports auto-accepted points at that same threshold (`scoring.eval.auto_accept`). A model's answer
is calibrated, then capped below it (`mapper.pipeline.LLM_CAP` = 0.75, `intake.point_ai.AI_CAP` = 0.85), so it is always
reviewed. `scoring.score.DEFAULT_ACCEPT` (0.8) is not a confirm rule: it is the H2 cut `scripts/score.py` reports.

Recompute every job, in order (the point_class questions depend on the other two):

```bash
.venv/bin/python scripts/eval.py all --fit
```

`version` grows by one each time a refit changes the curves; `heldout_worst_gap` is the largest gap between mean
confidence and measured accuracy in any band of 30+ items, on held-out folds (5-fold by equipment). Dev sets only:
never fit on a held-out set (`liberty_boe`).
