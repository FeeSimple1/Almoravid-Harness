"""CI gate: self-play sweep across all scenarios × a small seed set.

Per CROSS_PROJECT_LESSONS §4 (Nevsky retrospective): the sweep is the
single most productive bug-discovery technique. This CI version runs
6 scenarios × 2 seeds (12 sessions) — small enough to stay under a
few seconds, large enough to catch driver exceptions and harness bugs
that the static probing test suite missed.

Local: run the bigger sweep manually via
  python scripts/self_play_sweep.py --seeds 50
"""

from __future__ import annotations

import sys
from importlib import util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_sp_path = REPO_ROOT / "scripts" / "self_play.py"
_spec = util.spec_from_file_location("sp", _sp_path)
sp = util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

from almoravid.scenarios import list_scenarios  # noqa: E402


@pytest.mark.parametrize("name", list_scenarios())
@pytest.mark.parametrize("seed", [1, 2])
def test_self_play_completes_without_driver_exception(name: str, seed: int) -> None:
    """Pattern 1 + CROSS_PROJECT_LESSONS §4: greedy agent must drive
    every scenario × seed to phase=ended without zero-moves stalls,
    enumerator/handler mismatches, runaway loops, or harness crashes.
    """
    r = sp.step_self_play(name, seed=seed, max_steps=5000, verbose=False)
    status = r.get("status")
    assert status == "completed", (
        f"{name} seed={seed}: status={status}; details={r.get('details')}"
    )
    # Sanity on the run shape
    assert r["final_phase"] == "ended"
    assert r["steps"] > 0


def test_no_driver_exceptions_across_sweep() -> None:
    """Sample sweep: 6 scenarios × seed 1 ; surface any
    harness exceptions immediately (these are real bugs)."""
    exceptions = []
    for name in list_scenarios():
        try:
            r = sp.step_self_play(name, seed=1, max_steps=3000)
        except Exception as e:
            exceptions.append((name, e))
            continue
        if r.get("status") == "driver_exception":
            exceptions.append((name, r))
    assert not exceptions, f"driver exceptions during sweep: {exceptions}"
