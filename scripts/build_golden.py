"""Build ground truth for the Haystack example sites.

Usage: .venv/bin/python scripts/build_golden.py [alpha bravo]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.golden.export import build_site  # noqa: E402

if __name__ == "__main__":
    for site in sys.argv[1:] or ["alpha", "bravo"]:
        summary = build_site(
            site, ROOT / "data/raw/haystack" / f"{site}.json", ROOT / "data/ground_truth" / site,
            overrides_path=ROOT / "data/ground_truth/overrides.json",
        )
        print(json.dumps(summary, indent=2))
