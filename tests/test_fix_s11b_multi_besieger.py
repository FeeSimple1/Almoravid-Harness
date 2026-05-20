"""S11b: multi-besieger Storms (per-Lord Attacker Front/Reserve) and
per-Lord Defender survivor write-back (rule 4.5.2)."""

from __future__ import annotations

from almoravid.battle import BattleSide, resolve_storm
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _besiege(s, locale, defenders, siege, side="christian"):
    for did in defenders:
        s.lords[did].cylinder = Cylinder(kind="locale", locale_id=locale)
        s.lords[did].in_stronghold = True
    fld = "siege_yellow" if side == "christian" else "siege_green"
    setattr(s.locales[locale], fld, siege)


def _atk(s, lord_ids):
    forces = {}
    caps = []
    for lid in lord_ids:
        for ut, n in s.lords[lid].forces.items():
            forces[ut] = forces.get(ut, 0) + n
        caps.extend(s.lords[lid].capabilities)
    return BattleSide(side="christian", role="attacker", lord_ids=lord_ids,
                      forces=forces, capabilities_in_play=caps)


def test_multi_besieger_storm_tracks_both_lords() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    a1, a2 = "alfonso", "alvar_fanez"
    for lid in (a1, a2):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zamora")
        s.lords[lid].in_stronghold = False
    s.lords[a1].forces = {"knights": 4}
    s.lords[a2].forces = {"sergeants": 3}
    _besiege(s, "zamora", ["al_mustain"], siege=3)
    s.lords["al_mustain"].forces = {"serfs": 1}
    dfd = BattleSide(side="muslim", role="defender", lord_ids=["al_mustain"],
                     forces={"serfs": 1})
    r = resolve_storm(s, _atk(s, [a1, a2]), dfd)
    assert set(r.attacker_lord_forces.keys()) == {a1, a2}
    assert r.winner in ("christian", "muslim")


def test_attacker_reserve_untouched_when_front_wins_round_one() -> None:
    """Capacity-1 Castle, 1-round Storm: only the Active (Front) Lord
    strikes; the Reserve besieger never engages and is untouched."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    a1, a2 = "alfonso", "alvar_fanez"
    for lid in (a1, a2):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zamora")
        s.lords[lid].in_stronghold = False
    s.lords[a1].forces = {"knights": 8}     # Active: wipes the Garrison/serf
    s.lords[a2].forces = {"sergeants": 3}   # Reserve
    _besiege(s, "zamora", ["al_mustain"], siege=1)   # 1 round
    s.lords["al_mustain"].forces = {"serfs": 1}
    dfd = BattleSide(side="muslim", role="defender", lord_ids=["al_mustain"],
                     forces={"serfs": 1})
    r = resolve_storm(s, _atk(s, [a1, a2]), dfd)
    # Reserve Lord never engaged -> its forces are intact.
    assert r.attacker_lord_forces[a2] == {"sergeants": 3}


def test_defender_survivors_written_back_per_lord_on_attacker_loss() -> None:
    """When the attacker loses, surviving Defenders are written back
    per-Lord (exact), not pooled/proportional."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    a1 = "alfonso"
    s.lords[a1].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[a1].in_stronghold = False
    s.lords[a1].forces = {"serfs": 1}        # weak attacker -> loses
    d1, d2 = "al_mustain", "abu_bakr"
    _besiege(s, "zamora", [d1, d2], siege=1)
    s.lords[d1].forces = {"men_at_arms": 4}
    s.lords[d2].forces = {"men_at_arms": 4}
    dfd = BattleSide(side="muslim", role="defender", lord_ids=[d1, d2],
                     forces={"men_at_arms": 8})
    r = resolve_storm(s, _atk(s, [a1]), dfd)
    assert r.winner == "muslim"
    # Both defenders tracked per-Lord (only the Front one could take Hits;
    # the Reserve one is fully intact).
    assert set(r.defender_lord_forces.keys()) == {d1, d2}
    assert r.defender_lord_forces[d2] == {"men_at_arms": 4}
