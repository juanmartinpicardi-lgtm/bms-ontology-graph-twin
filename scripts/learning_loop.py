"""The learning loop, measured (W10): a simulated reviewer fixes 2 points of each repeated error pattern on Alpha, the
curator proposes conventions, they are approved, the mapper runs again, and the points each convention touched are
scored (never the fixed ones). Everything runs in a temporary database and a temporary copy of knowledge/: the repo's
files and Alpha's default scores do not change.

    .venv/bin/python scripts/learning_loop.py                     # alpha/names_paths, rules only unless PM_AI is on
    .venv/bin/python scripts/learning_loop.py --fixes 3 --json
    PM_AI=off .venv/bin/python scripts/learning_loop.py           # the curator phrases with rules alone

Writes reports/learning_loop.json. Dev sets only: the held-out real set is refused.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectmodel.scoring import learning  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default="alpha/names_paths")
    ap.add_argument("--fixes", type=int, default=2, help="points the reviewer fixes per error pattern")
    ap.add_argument("--max-patterns", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "reports/learning_loop.json"))
    args = ap.parse_args()
    report = learning.simulate(args.project, fixes=args.fixes, max_patterns=args.max_patterns,
                               log=(lambda *a: None) if args.json else print)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        learning.print_report(report)
