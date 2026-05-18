"""Sweep self_play.step_self_play across all scenarios × N seeds.

Reports a summary table and surfaces driver exceptions separately from
expected agent gaps. Per CROSS_PROJECT_LESSONS §4 / Nevsky retrospective:
the sweep is the single most productive bug-discovery technique.

Usage:
  python scripts/self_play_sweep.py [--seeds N] [--scenarios A,B,C]
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter, defaultdict
from importlib import util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Load self_play module by path
_spec = util.spec_from_file_location("sp", Path(__file__).parent / "self_play.py")
sp = util.module_from_spec(_spec)
_spec.loader.exec_module(sp)  # type: ignore[union-attr]

from almoravid.scenarios import list_scenarios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10,
                        help="Number of seeds per scenario (default 10).")
    parser.add_argument("--scenarios", default=None,
                        help="Comma-separated scenario ids; default = all.")
    parser.add_argument("--max-steps", type=int, default=10_000)
    parser.add_argument("--json", action="store_true",
                        help="Emit per-session JSON to stdout for piping.")
    args = parser.parse_args()

    scenarios = (args.scenarios.split(",") if args.scenarios
                 else list_scenarios())
    seeds = list(range(1, args.seeds + 1))

    rows = []
    driver_exceptions = []
    status_by_scenario: dict[str, Counter] = defaultdict(Counter)

    for sc in scenarios:
        for seed in seeds:
            try:
                r = sp.step_self_play(sc, seed=seed, max_steps=args.max_steps,
                                       verbose=False)
            except Exception as e:
                r = {"scenario": sc, "seed": seed,
                     "status": "driver_exception",
                     "exception_type": type(e).__name__,
                     "exception_msg": str(e)[:200],
                     "traceback": traceback.format_exc(limit=10)}
            rows.append(r)
            status = r.get("status", "unknown")
            status_by_scenario[sc][status] += 1
            if status == "driver_exception":
                driver_exceptions.append(r)
            if args.json:
                print(json.dumps(r))

    # Summary table
    if not args.json:
        print(f"\n=== Self-play sweep summary ({len(rows)} sessions) ===\n")
        print(f"  {'Scenario':<30} {'Status counts'}")
        for sc in scenarios:
            row = status_by_scenario[sc]
            parts = ", ".join(f"{k}={v}" for k, v in row.most_common())
            print(f"  {sc:<30} {parts}")
        print()
        if driver_exceptions:
            print(f"!!! {len(driver_exceptions)} DRIVER EXCEPTION(S) (harness bugs) !!!")
            for r in driver_exceptions[:5]:
                print(f"  {r['scenario']} seed={r['seed']}: "
                      f"{r['exception_type']}: {r['exception_msg']}")
            if len(driver_exceptions) > 5:
                print(f"  ... and {len(driver_exceptions) - 5} more")

    return 1 if driver_exceptions else 0


if __name__ == "__main__":
    sys.exit(main())
