"""Calibration per job (plan-workflow-ai §6.1 principle 6, §6.3): a job's raw confidence mapped to measured accuracy.

A raw confidence says how well a rule or a model *thinks* it did. A calibrated confidence says how often answers like
this one were right on the dev sets: 0.8 means about 8 in 10 were right. Only a calibrated confidence is compared
with auto-accept.

How:
- **Isotonic regression** (pool adjacent violators, PAV): the best non-decreasing step function from raw confidence
  to accuracy. Between fitted points the curve is interpolated linearly, as scikit-learn does. No dependency.
- **Strata.** A job may fit one curve per stratum (the mapper: per point function and whether the point sits on an
  equipment; point_class: per model). A stratum is tried from the most specific key to the least ("*", all items);
  a key with fewer than `min_n` fitting items falls back to the next one.
- **Stored per job** in `knowledge_model/calibration/<job>.json`, versioned (a `version` that grows with every refit,
  the sets it was fitted on, and the held-out check), and loaded at run time. A job with no file is not calibrated.
- **Never fit and score on the same items.** `cross_validate` fits on k-1 folds and applies to the held-out fold,
  folds split by equipment, so typicals of one unit never sit on both sides. The stored curve is then fit on all of
  the dev items; the numbers the reports print are the held-out ones.

`PM_CALIBRATION=off` turns calibration off everywhere (raw confidences, as before): fitting runs that way, and so does
the test suite, which checks the calibrated path in its own tests.
"""

from __future__ import annotations

import bisect
import contextlib
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAL_DIR = ROOT / "knowledge_model/calibration"
BAND_N = 30  # a band counts toward the bake-off's calibration rule from this many items (§6.4)
# Items a stratum needs to get its own curve. Chosen by held-out folds on the dev sets: at 25+, the 28 Alpha points the
# rules put in a BA-extension class (all wrong against a Brick answer key) fall back to the pooled curve, which calls
# them 75% right; at 20 they get their own. Slightly optimistic for that reason (picked on the same folds).
MIN_N = 20
TOLERANCE = 5.0  # points: a band's mean confidence must be this close to its measured accuracy (§6.4)
BANDS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0))
FUNCTIONS = ("Sensor", "Setpoint", "Command", "Status", "Alarm")
# Provisional cost budget for the bake-off, USD per 1,000 items: §8.4 (budget per building) is still undecided.
# Override with PM_BUDGET_USD_PER_1000 or `scripts/eval.py --budget`.
DEFAULT_BUDGET_USD_PER_1000 = 1.0


# isotonic regression ---------------------------------------------------------------------------------------------

def pav(xs: list[float], ys: list[float], ws: list[float] | None = None) -> list[tuple[float, float, float, float]]:
    """Pool adjacent violators. Returns blocks (x_lo, x_hi, y, weight), x increasing, y non-decreasing."""
    ws = ws or [1.0] * len(xs)
    pts: dict[float, list[float]] = {}
    for x, y, w in zip(xs, ys, ws):
        p = pts.setdefault(round(float(x), 6), [0.0, 0.0])
        p[0] += y * w
        p[1] += w
    blocks: list[list[float]] = []  # [x_lo, x_hi, sum_wy, sum_w]
    for x in sorted(pts):
        blocks.append([x, x, pts[x][0], pts[x][1]])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] >= blocks[-1][2] / blocks[-1][3]:
            last = blocks.pop()
            b = blocks[-1]
            b[1], b[2], b[3] = last[1], b[2] + last[2], b[3] + last[3]
    return [(b[0], b[1], b[2] / b[3], b[3]) for b in blocks]


@dataclass
class Curve:
    """A fitted isotonic curve: knots (x, y), interpolated linearly in between, flat outside."""
    x: list[float]
    y: list[float]
    n: int = 0

    @classmethod
    def fit(cls, xs: list[float], ys: list[float]) -> Curve:
        kx, ky = [], []
        for lo, hi, y, _ in pav(xs, ys):
            kx.append(lo)
            ky.append(y)
            if hi != lo:
                kx.append(hi)
                ky.append(y)
        return cls([round(v, 6) for v in kx], [round(v, 4) for v in ky], len(xs))

    def __call__(self, c: float) -> float:
        if not self.x:
            return c
        if c <= self.x[0]:
            return self.y[0]
        if c >= self.x[-1]:
            return self.y[-1]
        i = bisect.bisect_right(self.x, c)
        x0, x1, y0, y1 = self.x[i - 1], self.x[i], self.y[i - 1], self.y[i]
        return y0 if x1 == x0 else y0 + (y1 - y0) * (c - x0) / (x1 - x0)

    def to_json(self) -> dict:
        return {"x": self.x, "y": self.y, "n": self.n}


@dataclass
class Calibration:
    job: str
    curves: dict[str, Curve] = field(default_factory=dict)  # stratum key -> curve; "*" is all items
    version: int = 0
    meta: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.curves)

    def apply(self, raw: float, keys: tuple[str, ...] = ()) -> float:
        """Calibrated confidence of a raw one. `keys`: stratum keys, most specific first ("*" is always tried last)."""
        for k in (*keys, "*"):
            if k in self.curves:
                return round(self.curves[k](raw), 4)
        return raw

    def to_json(self) -> dict:
        return {"job": self.job, "version": self.version, **self.meta,
                "curves": {k: c.to_json() for k, c in sorted(self.curves.items())}}

    @property
    def ref(self) -> str:
        """`<job>@<version>`, recorded where calibrated confidences are written."""
        return f"{self.job}@{self.version}" if self else ""


def fit(job: str, items: list[dict], min_n: int = MIN_N) -> Calibration:
    """Fit a calibration. Each item has `raw` (confidence), `ok` (bool) and `keys` (its stratum keys)."""
    by_key: dict[str, list[dict]] = {"*": list(items)}
    for it in items:
        for k in it.get("keys", ()):
            by_key.setdefault(k, []).append(it)
    curves = {k: Curve.fit([i["raw"] for i in its], [float(i["ok"]) for i in its])
              for k, its in by_key.items() if len(its) >= min_n or k == "*"}
    return Calibration(job, curves)


def cross_validate(job: str, items: list[dict], k: int = 5, min_n: int = MIN_N) -> list[float]:
    """Held-out calibrated confidence of every item: fit on the other folds, apply to its fold. Folds split by
    `group` (equipment), assigned by a stable hash so runs repeat."""
    fold = [int(hashlib.sha1(str(i.get("group", n)).encode()).hexdigest(), 16) % k for n, i in enumerate(items)]
    out = [0.0] * len(items)
    for f in range(k):
        train = [i for i, g in zip(items, fold) if g != f]
        cal = fit(job, train, min_n)
        for n, (i, g) in enumerate(zip(items, fold)):
            if g == f:
                out[n] = cal.apply(i["raw"], tuple(i.get("keys", ())))
    return out


# reading and writing ---------------------------------------------------------------------------------------------

def enabled() -> bool:
    return os.environ.get("PM_CALIBRATION", "on").lower() not in ("off", "0", "false", "no")


@contextlib.contextmanager
def disabled():
    """Raw confidences inside the block (for fitting)."""
    old = os.environ.get("PM_CALIBRATION")
    os.environ["PM_CALIBRATION"] = "off"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("PM_CALIBRATION", None)
        else:
            os.environ["PM_CALIBRATION"] = old


def path(job: str, cal_dir: Path | None = None) -> Path:
    return Path(cal_dir or CAL_DIR) / f"{job}.json"


@lru_cache
def _load(p: str, mtime: float) -> Calibration:
    d = json.loads(Path(p).read_text())
    return Calibration(d["job"], {k: Curve(c["x"], c["y"], c.get("n", 0)) for k, c in d["curves"].items()},
                       d.get("version", 0), {k: v for k, v in d.items() if k not in ("job", "version", "curves")})


def load(job: str, cal_dir: Path | None = None) -> Calibration:
    """The job's stored calibration; an empty one (no change) when there is none or calibration is off."""
    p = path(job, cal_dir)
    if not enabled() or not p.exists():
        return Calibration(job)
    return _load(str(p), p.stat().st_mtime)


def save(cal: Calibration, meta: dict, cal_dir: Path | None = None) -> Path:
    """Write a refit: the version grows by one when the curves changed."""
    p = path(cal.job, cal_dir)
    old = json.loads(p.read_text()) if p.exists() else {}
    curves = {k: c.to_json() for k, c in sorted(cal.curves.items())}
    cal.version = old.get("version", 0) + (old.get("curves") != curves)
    cal.meta = {"fitted": old.get("fitted") if old.get("curves") == curves else date.today().isoformat(), **meta}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cal.to_json(), indent=1) + "\n")
    _load.cache_clear()
    return p


# keys --------------------------------------------------------------------------------------------------------------

def function_of(cls: str | None) -> str:
    """The function a point class names (Sensor, Setpoint, Command, Status, Alarm), or "other"."""
    if not cls:
        return "none"
    return next((f for f in FUNCTIONS if cls == f or cls.endswith("_" + f)), "other")


def mapper_keys(cls: str | None, method: str, path: bool | None = None) -> tuple[str, ...]:
    """Mapper strata: the point's function as the rules (`rule`) or a template (`template`) decided it, and whether
    the point came with an equipment folder path; then without the path; then the function alone. On Alpha the
    function is what separates a trustworthy 1.0 (a temperature sensor) from an untrustworthy one (a "status" the
    answer key calls a command), the method separates names alone from names a template confirmed, and the path
    separates a name the folder explains ("DA flow" under an AHU) from the same name alone."""
    fn = function_of(cls)
    where = () if path is None else (f"{method}|{fn}|{'path' if path else 'name'}",)
    return (*where, f"{method}|{fn}", fn)


def calibrate_points(final: dict, guesses: dict, records=()) -> dict:
    """The mapper's hook: calibrate rule and template confidences of points, `final` pid -> (class, conf, method).
    `records`: the raw records, for whether each point has a folder path. A convention's class hint is a person's
    statement about the site's names and stays as it is."""
    cal = load("mapper")
    if not cal:
        return final
    path = {f"pt:{r.source_id}": bool(r.path) for r in records}
    return {pid: (c, conf if guesses[pid].hint or m not in ("rule", "template")
                  else cal.apply(conf, mapper_keys(c, m, path.get(pid))), m) for pid, (c, conf, m) in final.items()}


def intake_keys(cls: str | None, step: str) -> tuple[str, ...]:
    """Intake strata: the point's function as read from the submittal or the BMS export, then the function alone."""
    fn = function_of(cls)
    return (f"{step}|{fn}", fn)


def model_keys(model: str | None, caller: str | None) -> tuple[str, ...]:
    """Model strata: the model as one caller uses it, then the model. The same model's answers are right far more often
    on a submittal's point descriptions (the setup, `intake`) than on terse BMS names (the mapper, `mapper`)."""
    if not model:
        return ()
    return ((f"{model}|{caller}",) if caller else ()) + (model,)


def calibrate_model(job: str, raw: float, model: str | None, caller: str | None = None) -> float:
    """A model's own confidence, calibrated per job, model and caller (an uncalibrated model keeps its number)."""
    return load(job).apply(raw, model_keys(model, caller))


# measuring ---------------------------------------------------------------------------------------------------------

def band_table(conf: list[float], ok: list[bool], bands=BANDS) -> list[dict]:
    """Per confidence band: n, mean confidence, measured accuracy, and the gap between them (points)."""
    out = []
    for lo, hi in bands:
        idx = [i for i, c in enumerate(conf) if lo <= c < hi or (hi == 1.0 and c == 1.0)]
        n = len(idx)
        acc = 100 * sum(ok[i] for i in idx) / n if n else None
        mean = 100 * sum(conf[i] for i in idx) / n if n else None
        out.append({"band": f"{lo:.1f}-{hi:.1f}", "n": n, "mean_conf_pct": None if mean is None else round(mean, 1),
                    "accuracy_pct": None if acc is None else round(acc, 1),
                    "gap": None if acc is None else round(abs(mean - acc), 1)})
    return out


def worst_gap(table: list[dict], min_n: int = BAND_N) -> float | None:
    """The largest gap among bands holding at least `min_n` items (None when no band is that big)."""
    gaps = [b["gap"] for b in table if b["n"] >= min_n]
    return max(gaps) if gaps else None


def calibrated(table: list[dict], min_n: int = BAND_N, tol: float = TOLERANCE) -> bool:
    g = worst_gap(table, min_n)
    return g is not None and g <= tol


def verdict(*, metric: float | None, rules_metric: float | None, table: list[dict], usd_per_1000: float | None,
            budget: float | None) -> dict:
    """The bake-off rule (§6.4): beats rules alone, calibrated within 5 points per band of 30+, under the budget."""
    checks = {
        "beats rules alone": None if metric is None or rules_metric is None else metric > rules_metric,
        f"calibrated within {TOLERANCE:g} points (bands of {BAND_N}+)": calibrated(table),
        "under the cost budget": None if budget is None or usd_per_1000 is None else usd_per_1000 <= budget,
    }
    failed = [k if v is False else f"{k}: unknown" for k, v in checks.items() if v is not True]
    return {"default_ok": not failed, "checks": checks, "budget_usd_per_1000": budget,
            "says": "may be the default" if not failed else "not the default (" + "; ".join(failed) + ")"}


def budget_usd_per_1000() -> float | None:
    """The bake-off budget: PM_BUDGET_USD_PER_1000 ("none": no budget yet), else the provisional default."""
    v = os.environ.get("PM_BUDGET_USD_PER_1000")
    if v is None:
        return DEFAULT_BUDGET_USD_PER_1000
    return None if v.lower() in ("", "none") else float(v)
