"""Storm 4.4.4 Losses per-Lord (4.5.2): routed units are tracked per
besieging/defending Lord and rolled for survival (storm attacker keeps
on a 1), instead of being silently removed."""

from __future__ import annotations

from almoravid.battle import (
    BattleSide, apply_battle_losses, resolve_storm,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_resolve_storm_tracks_routed_per_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    a = "alfonso"
    s.lords[a].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[a].in_stronghold = False
    s.lords[a].forces = {"men_at_arms": 6}
    d = "al_mustain"
    s.lords[d].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[d].in_stronghold = True
    s.locales["zamora"].siege_yellow = 2
    s.lords[d].forces = {"men_at_arms": 6}
    atk = BattleSide(side="christian", role="attacker", lord_ids=[a],
                     forces={"men_at_arms": 6})
    dfd = BattleSide(side="muslim", role="defender", lord_ids=[d],
                     forces={"men_at_arms": 6})
    r = resolve_storm(s, atk, dfd)
    # Conservation: surviving + routed == starting, per Lord.
    surv = r.attacker_lord_forces[a].get("men_at_arms", 0)
    routed = r.attacker_lord_routed[a].get("men_at_arms", 0)
    assert surv + routed == 6
    assert routed > 0          # the losing attacker routed some units


def test_storm_4_4_4_losses_applied_to_routed_units() -> None:
    """End-to-end: commit per-Lord routed units, then 4.4.4 Storm Losses
    (storm attacker keeps each routed unit only on a 1). Routed pile is
    consumed; kept units (if any) return to Forces."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    a = "alfonso"
    s.lords[a].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[a].in_stronghold = False
    s.lords[a].forces = {"men_at_arms": 6}
    d = "al_mustain"
    s.lords[d].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[d].in_stronghold = True
    s.locales["zamora"].siege_yellow = 2
    s.lords[d].forces = {"men_at_arms": 6}
    atk = BattleSide(side="christian", role="attacker", lord_ids=[a],
                     forces={"men_at_arms": 6})
    dfd = BattleSide(side="muslim", role="defender", lord_ids=[d],
                     forces={"men_at_arms": 6})
    r = resolve_storm(s, atk, dfd)
    # Commit per-Lord forces + routed (mirrors _h_cmd_storm).
    s.lords[a].forces = dict(r.attacker_lord_forces[a])
    s.lords[a].routed_units = dict(r.attacker_lord_routed[a])
    routed_before = sum(s.lords[a].routed_units.values())
    assert routed_before > 0
    apply_battle_losses(s, r, {"losers": []}, storm=True)
    # 4.4.4 consumed the routed pile (kept-or-removed); none linger.
    assert sum(s.lords[a].routed_units.values()) == 0
    # Kept survivors (storm attacker: only on a 1) are <= what routed.
    kept = s.lords[a].forces.get("men_at_arms", 0)
    assert kept <= routed_before
