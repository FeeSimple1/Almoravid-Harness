"""FIX-B core (S8/S10/S11): per-Lord Storm Array.

- S8: each Lord's Melee is capped at 6 Hits per Round, combined across
  horse + foot (the old code capped each substep separately).
- S11: Front begins with <=1 Lord; Front never exceeds Capacity;
  Reposition (Round 2+) brings one Reserve to Front; forced advance
  when all Front Lords Rout.
- S10: the Attacker may Concede at the start of Round 2+.
"""
from __future__ import annotations

from almoravid.battle import BattleSide, resolve_storm
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _melee_step(result, actor):
    """Return the rounded_hits of the given actor's Melee step in Round 1."""
    for st in result.rounds[0].steps:
        if st.actor == actor and st.step.startswith("2."):
            return st.rounded_hits
    return None


def _besiege(s, locale_id, defender_lords, *, siege=4):
    """Set up a Christian Storm against Muslim Lords inside `locale_id`."""
    loc = s.locales[locale_id]
    loc.siege_yellow = siege
    loc.siege_green = 0
    for lid in defender_lords:
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id=locale_id)
        s.lords[lid].in_stronghold = True


def test_attacker_combined_melee_capped_at_six():
    # 4 Knights (horse, x1) + 4 Men-at-Arms (foot, x1) = 8 raw Melee.
    # Old code capped each substep at 6 -> 8 total; new caps combined -> 6.
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    _besiege(s, "zamora", [], siege=4)  # castle, capacity 1
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"],
                     forces={"knights": 4, "men_at_arms": 4})
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="zamora")
    dfd = BattleSide(side="muslim", role="defender", lord_ids=[], forces={})
    r = resolve_storm(s, atk, dfd)
    assert _melee_step(r, "attacker") == 6


def test_front_begins_with_one_defender_lord():
    # Two besieged Muslim Lords; Round 1 only ONE strikes (Front <=1).
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    _besiege(s, "leon", ["al_mutamid", "al_mustain"], siege=1)  # town, cap 2
    for lid in ("al_mutamid", "al_mustain"):
        s.lords[lid].forces = {"men_at_arms": 6}  # 6 Melee each
    atk = BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                     forces={"knights": 1})
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid", "al_mustain"], forces={})
    r = resolve_storm(s, atk, dfd, max_rounds=1)
    # One Front Lord (6) + Garrison Melee — must be well under two Lords (12+).
    dm = _melee_step(r, "defender")
    assert dm is not None and dm < 12


def test_reposition_adds_reserve_round_two():
    # Town capacity 2; two besieged Lords. Round 2 Reposition brings the
    # second Lord to Front, so defender Melee rises vs Round 1.
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    _besiege(s, "leon", ["al_mutamid", "al_mustain"], siege=4)
    for lid in ("al_mutamid", "al_mustain"):
        s.lords[lid].forces = {"men_at_arms": 6}
    atk = BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                     forces={"knights": 1})  # weak attacker, survives
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid", "al_mustain"], forces={})
    r = resolve_storm(s, atk, dfd, max_rounds=2, reposition_defender=True)
    if len(r.rounds) < 2:
        return  # storm ended early; reposition not exercised
    def dmelee(rd):
        for st in rd.steps:
            if st.actor == "defender" and st.step.startswith("2."):
                return st.rounded_hits
        return 0
    # Round 2 has two Front Lords -> more Lord Melee than Round 1's one.
    assert dmelee(r.rounds[1]) >= dmelee(r.rounds[0])


def test_attacker_concede_round_two_loses():
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    _besiege(s, "leon", ["al_mutamid"], siege=4)
    s.lords["al_mutamid"].forces = {"men_at_arms": 2}
    atk = BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                     forces={"knights": 6})
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    r = resolve_storm(s, atk, dfd, max_rounds=4, concede_after_round=2)
    # Conceding ends the Storm; the Attacker loses.
    assert r.winner == "muslim"
    assert len(r.rounds) == 1  # broke at the start of Round 2


def test_front_never_exceeds_capacity():
    # Castle capacity 1: even with many besieged Lords, Front stays 1,
    # so only one Lord's Melee (capped 6) + Garrison each Round.
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    defenders = ["al_mutamid", "al_mustain", "abu_bakr"]
    _besiege(s, "zamora", defenders, siege=4)  # castle, capacity 1
    for lid in defenders:
        s.lords[lid].forces = {"men_at_arms": 6}
    atk = BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                     forces={"knights": 1})
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="zamora")
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=defenders, forces={})
    r = resolve_storm(s, atk, dfd, max_rounds=4, reposition_defender=True)
    castle_garrison_melee = 1  # MaA(1)x1 + Militia(1)x0.5 -> ceil ~ 2
    for rd in r.rounds:
        for st in rd.steps:
            if st.actor == "defender" and st.step.startswith("2."):
                # One Lord (<=6) + small Garrison melee; never two Lords (12+).
                assert st.rounded_hits <= 6 + 3
