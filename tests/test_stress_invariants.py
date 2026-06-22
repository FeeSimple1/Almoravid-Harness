"""Smoke regression over the invariant-checked stress harness.

Runs a couple of deep Scenario F playthroughs and asserts they complete
with no invariant violation / handler crash / phantom-move (enumerator vs
handler) mismatch. Kept small so it stays fast in CI; the full sweep is run
manually via scripts/stress_invariants.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "stress_invariants",
    Path(__file__).resolve().parent.parent / "scripts" / "stress_invariants.py",
)
assert _SPEC and _SPEC.loader
stress = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stress)

_OK = {"completed", "max_steps"}


@pytest.mark.parametrize("profile,seed", [("survival", 1), ("siege", 2)])
def test_scenario_f_playthrough_is_invariant_clean(profile: str,
                                                   seed: int) -> None:
    r = stress.run_playthrough("scenario_f_reconquista", seed=seed,
                               profile=profile)
    assert r["status"] in _OK, (
        f"{profile} seed {seed} ended {r['status']}: "
        f"{r.get('violations') or r.get('rejected') or r.get('error')}"
    )
    # These seeds reach deep into the campaign; a legitimate early
    # campaign victory (5.2) can end sooner, which is still a clean
    # completion (asserted above).
    if r["status"] == "completed" and r["steps"] > 800:
        assert r["max_box"] >= 7, f"only reached box {r['max_box']}"


def test_check_invariants_flags_a_corrupted_state() -> None:
    """The invariant battery must actually catch a planted violation."""
    from almoravid.scenarios import load_scenario
    s = load_scenario("scenario_f_reconquista", seed=1)
    assert stress.check_invariants(s) == []         # healthy at start
    next(iter(s.lords.values())).assets["coin"] = -5
    assert any("negative asset" in v for v in stress.check_invariants(s))
