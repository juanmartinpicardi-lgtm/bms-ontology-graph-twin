"""Print a reproducible random sample of ground-truth points for spot-checking.

Usage: .venv/bin/python scripts/sample_golden.py [site] [n] [seed]
"""

import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    site = sys.argv[1] if len(sys.argv) > 1 else "alpha"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42

    gt = ROOT / "data/ground_truth" / site
    points = list(csv.DictReader((gt / "points.csv").open()))
    equips = {r["equip_id"]: r for r in csv.DictReader((gt / "equipment.csv").open())}
    sample = sorted(random.Random(seed).sample(points, n), key=lambda p: p["point_id"])

    print(f"{site}: {n} of {len(points)} points, seed={seed}\n")
    for i, p in enumerate(sample, 1):
        q = equips.get(p["equip_id"], {})
        q_cls = q.get("brick_class") or f'? [{q.get("map_status", "")}: {q.get("candidates", "")}]'
        p_cls = p["brick_class"] or f'? [{p["map_status"]}: {p["candidates"]}]'
        print(f'{i:>2}. {p["point_id"]}  raw name: {p["raw_name"]}')
        print(f'    equipment : {p["equip_dis"]} ({p["equip_id"]}) -> {q_cls}')
        print(f'    tags      : {p["haystack_tags"]}' + (f'  unit={p["unit"]}' if p["unit"] else ""))
        print(f'    brick     : {p_cls}' + (f'  [{p["map_status"]}]' if p["map_status"] == "generic" else ""))
