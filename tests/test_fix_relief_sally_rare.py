"""Relief Sally rare edges: M6 Feigned Retreat round-2 reorder applied
within a Relief Sally (4.4.2), and excess Reserve Defenders advance via
Reposition (4.4.1-.2) instead of sitting out."""

from __future__ import annotations

from almoravid.battle import resolve_relief_sally
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_m6_consumed_after_relief_sally_round_two() -> None:
    """M6 (Muslim, held) is applied (round-2 melee reorder) and discarded
    after Round 2 of a Relief Sally."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    s.decks.this_levy_events["muslim"] = ["M6"]
    s.decks.discard = []
    # A multi-round sally so Round 2 is reached: weakish forces.
    sal = "alfonso"
    s.lords[sal].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[sal].in_stronghold = False
    s.lords[sal].forces = {"men_at_arms": 3}
    d = "al_mustain"
    s.lords[d].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[d].in_stronghold = False
    s.lords[d].forces = {"men_at_arms": 3}
    s.locales["zamora"].siege_green = 4   # up to 4 rounds
    result, lanes = resolve_relief_sally(
        s, [], [sal], [d], besieger_side="muslim", locale_id="zamora",
        max_rounds=4)
    assert len(result.rounds) >= 2          # reached Round 2
    assert "M6" in s.decks.discard          # consumed/discarded
    assert "M6" not in s.decks.this_levy_events.get("muslim", [])


def test_excess_reserve_defenders_advance_and_fight() -> None:
    """A Relief Sally with more Defenders than Front + three Reserve:
    the excess advance via Reposition when front/rear Lords Rout, instead
    of sitting out and stalemating the battle."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    marcher, sal = "alfonso", "alvar_fanez"
    for lid in (marcher, sal):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zamora")
        s.lords[lid].in_stronghold = False
        s.lords[lid].forces = {"knights": 20}   # overwhelming
    # Six Muslim besiegers: 1 Front (faces marcher), 3 Rear (face sallyer),
    # 2 excess Reserve. All weak Serfs so they Rout immediately.
    defs = ["al_mustain", "abu_bakr", "abd_allah", "al_mutawakkil",
            "al_mutamid", "al_mundir"]
    for lid in defs:
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zamora")
        s.lords[lid].in_stronghold = False
        s.lords[lid].forces = {"serfs": 1}
    s.locales["zamora"].siege_green = 4   # 4 rounds; Front lane has no Walls
    result, lanes = resolve_relief_sally(
        s, [marcher], [sal], defs, besieger_side="muslim",
        locale_id="zamora", max_rounds=4)
    marchers, sallyers, def_front, def_rear, shared = lanes
    engaged = set(def_front.lord_ids) | set(def_rear.lord_ids)
    # Reposition advanced BOTH excess Reserve Defenders into a lane
    # (Front facing the Marcher, or Reserve facing the Sallyer) instead
    # of leaving them sidelined.
    assert defs[4] in engaged and defs[5] in engaged
    # At least one excess Lord was actually engaged and Routed (the
    # Front-lane advance, which has no Walls protection).
    assert any(not s.lords[lid].forces for lid in (defs[4], defs[5]))
