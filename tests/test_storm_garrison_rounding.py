"""4.5.2 GARRISON FORCES DURING STORM — pooled rounding + cap (Q-004).

"Garrisons add their Strikes to those of the Defending Lord (rounding
up), if any" — per the Battle & Storm reference (garrison_in_storm)
that is a SINGLE round-up of the combined Lord+Garrison raw total, not
separate ceils. Anchored by the Background Book Játiva example, where
the Garrison pools with Abu Bakr's units for "a total of five dice".
"""
from __future__ import annotations

from almoravid.battle import _storm_melee_hits
from almoravid.scenarios import load_scenario


def _ss(garrison):
    # Minimal ss dict: _storm_melee_hits only reads nothing from ss
    # beyond what the caller passes explicitly.
    return {}


def test_garrison_pools_with_lord_before_single_ceil() -> None:
    """Lord Militia (0.5 raw) + Castle Garrison (MaA 1 + Militia 1 =
    1.5 raw) = 2.0 combined -> 2 Hits. Separate ceils would give
    1 + 2 = 3."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    hits = _storm_melee_hits(
        s, {}, [{"militia": 1}], [], side_is_christian=False,
        round_idx=1, garrison={"men_at_arms": 1, "militia": 1})
    assert hits == 2


def test_bgbook_jativa_pool_is_five_dice() -> None:
    """Background Book p.16: Abu Bakr (Sergeant, Light Horse, MaA,
    2 Militia = 3.5 raw) + Town Garrison after one MaA loss (MaA 1 +
    Militia 1 = 1.5 raw) = 5.0 -> exactly five dice, as printed."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    abu = {"sergeants": 1, "light_horse": 1, "men_at_arms": 1,
           "militia": 2}
    hits = _storm_melee_hits(
        s, {}, [abu], [], side_is_christian=False, round_idx=1,
        garrison={"men_at_arms": 1, "militia": 1})
    assert hits == 5


def test_combined_lane_subject_to_six_cap() -> None:
    """Q-004 default: Lord raw 6.0 + Garrison raw 1.5 = 7.5 combined
    -> capped at 6 (previously 6 + 2 = 8)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    hits = _storm_melee_hits(
        s, {}, [{"men_at_arms": 6}], [], side_is_christian=False,
        round_idx=1, garrison={"men_at_arms": 1, "militia": 1})
    assert hits == 6


def test_garrison_alone_uncapped_single_ceil() -> None:
    """No Defending Lord in Front: City Garrison alone (3 MaA + 3
    Militia = 4.5 raw) -> 5 Hits."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    hits = _storm_melee_hits(
        s, {}, [], [], side_is_christian=False, round_idx=1,
        garrison={"men_at_arms": 3, "militia": 3})
    assert hits == 5


def test_second_front_lord_not_pooled_with_garrison() -> None:
    """Garrison pools with the FIRST Front Lord only: [Militia 1,
    Militia 1] + Castle Garrison = ceil(0.5+1.5) + ceil(0.5)
    = 2 + 1 = 3."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    hits = _storm_melee_hits(
        s, {}, [{"militia": 1}, {"militia": 1}], [],
        side_is_christian=False, round_idx=1,
        garrison={"men_at_arms": 1, "militia": 1})
    assert hits == 3
