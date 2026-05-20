"""FIX-B S9: in a Sally (4.5.3) the Sallying Lords get no Walls/Garrison,
but the DEFENDERS (besiegers) receive Siegeworks as Walls. Verified
statistically: across many seeds, the besieger keeps strictly more
units when it has full Siegeworks (4) than with none (0)."""
from __future__ import annotations

from almoravid.battle import BattleSide, resolve_sally
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _run_sally(seed, siege_markers):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    loc = s.locales["toledo"]
    loc.siege_yellow = siege_markers  # Christian besieger's Siegeworks
    loc.siege_green = 0
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="toledo")
    s.lords["al_mutamid"].in_stronghold = True
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={"light_horse": 6})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alvar_fanez"], forces={"men_at_arms": 6})
    resolve_sally(s, atk, dfd)
    return dfd.forces.get("men_at_arms", 0)  # besieger survivors


def test_siegeworks_protect_besieger_in_sally():
    survivors_no_walls = sum(_run_sally(seed, 0) for seed in range(40))
    survivors_full_walls = sum(_run_sally(seed, 4) for seed in range(40))
    # Walls 1-4 cancel many of the Sallying attacker's Hits, so the
    # besieger should survive strictly better with full Siegeworks.
    assert survivors_full_walls > survivors_no_walls


def test_sally_engagement_tag():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.locales["toledo"].siege_yellow = 2
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="toledo")
    s.lords["al_mutamid"].in_stronghold = True
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={"light_horse": 3})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alvar_fanez"], forces={"men_at_arms": 3})
    r = resolve_sally(s, atk, dfd)
    assert r.engagement == "sally"
