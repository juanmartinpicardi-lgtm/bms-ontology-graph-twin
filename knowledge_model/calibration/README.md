# Calibration per job

One file per job: the isotonic curves that turn the job's raw confidence into the accuracy measured on the dev sets
(`src/projectmodel/calibration.py`, plan-workflow-ai §6.1 principle 6). Loaded at run time; `PM_CALIBRATION=off`
gives raw confidences.

| File | Where it is applied | Strata (most specific first, then `*`) | Fitted on |
|---|---|---|---|
| `mapper.json` | `mapper/pipeline.py`, after the templates, before the model step: rule and template point classes (a convention's class hint is left as it is) | `<method>\|<function>`, `<function>` | Alpha `names_paths` + `names_only` |
| `intake.json` | `intake/submittal.py` and `intake/bms.py`, where a point's class confidence is made (a person's term is left as it is) | `<step>\|<function>`, `<function>` | Troop D |
| `point_class.json` | `mapper/llm.py` and `intake/point_ai.py`, on the model's own confidence, before the cap below auto-accept | `<model>` | Troop D + Alpha points below auto-accept |

`function` is the point function the class names (Sensor, Setpoint, Command, Status, Alarm, other). A stratum with
fewer than 30 fitting items falls back to the next key.

Recompute every job, in order (the point_class questions depend on the other two):

```bash
.venv/bin/python scripts/eval.py all --fit
```

`version` grows by one each time a refit changes the curves; `heldout_worst_gap` is the largest gap between mean
confidence and measured accuracy in any band of 30+ items, on held-out folds (5-fold by equipment). Dev sets only:
never fit on a held-out set (`liberty_boe`).
