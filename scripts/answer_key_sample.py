"""Make (or remake) the fixed sample the Answer keys page works through: data/ground_truth/answer_key_sample.yaml.

    .venv/bin/python scripts/answer_key_sample.py            # every offered set (needs the drawing PDFs in data/raw/)
    .venv/bin/python scripts/answer_key_sample.py troop_d    # one set

The sample comes from the documents (the plan reader's tag candidates per keyed sheet, the sequence sections the rules
read) and a fixed seed, never from an answer key. Commit the result: engineers on different machines work the same
items. Remaking it after the readers' candidate code changed would change the sample and orphan saved answers, so
don't, unless you start the keys again. The held-out set (liberty_boe) is refused.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel import answer_keys as ak  # noqa: E402


def main() -> int:
    sites = sys.argv[1:] or None
    for s in sites or []:
        ak.check_set(ak.job_of(s), s)
    p = ak.write_manifest(sites)
    m = ak.load_manifest()["sets"]
    for s, x in m.items():
        pr = ak.progress(x["job"], s, {"items": []})
        print(f"{s}: {len(x['items'])} of {x['universe']} items, about {pr['est_total_min']:.0f} minutes")
    print(f"-> {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
