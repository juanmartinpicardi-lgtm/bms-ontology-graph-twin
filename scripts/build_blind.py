"""Build blind exports (names only; names + equipment folder path) for the Haystack example sites.

Usage: .venv/bin/python scripts/build_blind.py [alpha]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.blind.export import build_blind  # noqa: E402

if __name__ == "__main__":
    for site in sys.argv[1:] or ["alpha"]:
        summary = build_blind(
            site, ROOT / "data/raw/haystack" / f"{site}.json", ROOT / "data/blind" / site,
            ROOT / "data/ground_truth" / site / "blind_key.csv",
        )
        print(json.dumps(summary))
