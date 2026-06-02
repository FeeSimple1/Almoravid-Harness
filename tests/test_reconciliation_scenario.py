"""Rulebook reconciliation: Curias threshold (6.2.2), Ruined Land Parias
Coin (Scenarios E/F), and Scenario D start-Bypass."""
from __future__ import annotations

from almoravid.campaign import (
    _parias_coin_amount,
    _taifa_ravaged_count,
    apply_curias,
)
from almoravid.scenarios import load_scenario


def test_curias_shifts_box6_marker_when_firing_at_box5() -> None:
    """6.2.2: Lords 'Beyond Service (in box 6 or lower)' shift to box 7 —
    a FIXED threshold of 6, even when Curias fires at box 5."""
    s = load_scenario("scenario_f_reconquista")
    sm = s.calendar.service_markers[0]
    sm.box = 6
    lord_at_6 = sm.lord_id
    apply_curias(s, 5)   # Curias fires at box 5
    shifted = next(m for m in s.calendar.service_markers
                   if m.lord_id == lord_at_6)
    assert shifted.box == 7   # box-6 marker WAS shifted (was buggy: stayed 6)


def test_ruined_land_reduces_parias_coin_by_ravaged() -> None:
    """Scenario E/F Ruined Land: Parias Coin = Service less Ravaged markers
    (either side) in the Taifa."""
    s = load_scenario("scenario_f_reconquista")
    assert s.meta.ruined_land is True
    tid = next(iter(s.taifas))
    base_ravaged = _taifa_ravaged_count(s, tid)
    # Ravage two currently-UNravaged Locales in this Taifa (one per color).
    fresh = [lid for lid in s.taifas[tid].locale_ids
             if s.locales[lid].ravaged == "none"][:2]
    assert len(fresh) == 2
    s.locales[fresh[0]].ravaged = "yellow"
    s.locales[fresh[1]].ravaged = "green"   # either side counts
    n = _taifa_ravaged_count(s, tid)
    assert n == base_ravaged + 2
    # Parias Coin = Service (e.g. 9) less Ravaged markers in the Taifa.
    assert _parias_coin_amount(s, tid, 9) == max(0, 9 - n)
    # And a side at >= Ravaged count floors at 0.
    assert _parias_coin_amount(s, tid, n) == 0


def test_non_ruined_land_parias_coin_unreduced() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert s.meta.ruined_land is False
    tid = next(iter(s.taifas))
    s.locales[s.taifas[tid].locale_ids[0]].ravaged = "yellow"
    assert _parias_coin_amount(s, tid, 4) == 4   # full Service, unaffected


def test_scenario_d_garcia_starts_bypassing_tudela() -> None:
    s = load_scenario("scenario_d_arrival")
    assert s.lords["garcia_ordonez"].cylinder.locale_id == "tudela"
    assert s.locales["tudela"].bypass_yellow is True
