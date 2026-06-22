"""Invariant-checked self-play with the Advanced Vassal Service rule
(3.4.2) ENABLED — guards the optional rule that gets no exercise in the
default (flag-off) self-play sweeps."""
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


@pytest.mark.parametrize("scenario,seed,profile", [
    ("scenario_f_reconquista", 1, "survival"),
    ("scenario_f_reconquista", 2, "siege"),
    ("scenario_d_arrival", 1, "combat"),
])
def test_advanced_vassal_service_playthrough_is_clean(scenario, seed,
                                                      profile) -> None:
    r = stress.run_playthrough(scenario, seed=seed, profile=profile,
                               max_steps=6000,
                               meta_opts={"advanced_vassal_service": True})
    assert r["status"] in _OK, (
        f"{scenario}/{seed}/{profile} ended {r['status']}: "
        f"{r.get('violations') or r.get('rejected') or r.get('error')}")
    assert not r.get("violations")
