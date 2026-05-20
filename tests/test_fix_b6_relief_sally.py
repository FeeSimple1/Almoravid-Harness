"""FIX-C / B6 (rule 4.4.1 RELIEF SALLY, 4.5.3).

Relief Sally array geometry: the relieving Marchers and the Sallying
(Besieged) Lords form two separate lanes against the besiegers.
  - Marchers Strike / are Struck by the Front Defenders (open field).
  - Sallying Attackers Strike up to three Reserve Defenders (or the
    Front Defenders if no Reserve) "as if Flanking all of them equally".
  - The besieging DEFENDER cancels the Sallying Attackers' Hits via
    Siegeworks-as-Walls -- but NOT the Marchers' Hits.
  - If the Attackers lose, the Sallying Lords Withdraw back into the
    Stronghold and the besieger's Siege markers reduce to one.
"""

from __future__ import annotations

from almoravid.battle import (
    BattleResult, BattleSide,
    apply_relief_sally_aftermath, resolve_relief_sally,
)
from almoravid.scenarios import load_scenario


def test_siegeworks_cancels_sallyer_hits_only() -> None:
    """With Siege markers covering the whole die (Walls 1-6) every
    Sallying-attacker Hit is cancelled, so the besieger takes NO Sally
    losses; with no Siege markers the same Sallyers wipe the besieger."""
    # No Siegeworks -> Sallyer Hits land, besieger Serfs removed.
    s0 = load_scenario("scenario_a_toledo_beset", seed=3)
    s0.lords["alfonso"].forces = {"knights": 8}     # Sallyer
    s0.lords["al_mustain"].forces = {"serfs": 3}    # besieger (Defender)
    s0.locales["coria"].siege_green = 0
    res0, lanes0 = resolve_relief_sally(
        s0, [], ["alfonso"], ["al_mustain"],
        besieger_side="muslim", locale_id="coria", max_rounds=2)
    _, _, def_front0, def_rear0, _ = lanes0
    assert def_rear0.forces.get("serfs", 0) == 0   # all Serfs removed

    # Full Siegeworks (Walls 1-6) -> every Sallyer Hit cancelled.
    s6 = load_scenario("scenario_a_toledo_beset", seed=3)
    s6.lords["alfonso"].forces = {"knights": 8}
    s6.lords["al_mustain"].forces = {"serfs": 3}
    s6.locales["coria"].siege_green = 6
    res6, lanes6 = resolve_relief_sally(
        s6, [], ["alfonso"], ["al_mustain"],
        besieger_side="muslim", locale_id="coria", max_rounds=2)
    _, _, _, def_rear6, _ = lanes6
    assert def_rear6.forces.get("serfs", 0) == 3   # untouched by Sallyers


def test_marchers_and_sallyers_hit_disjoint_defender_groups() -> None:
    """Marchers Strike the Front Defenders; Sallyers Strike the Reserve
    Defenders. With max_rounds=1, the Marchers clear the Front-Defender
    Serfs while the Reserve Defenders (Men-at-Arms) are essentially
    untouched by the Marchers -- proving the lanes are disjoint."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    s.lords["alfonso"].forces = {"knights": 12}      # Marcher
    s.lords["alvar_fanez"].forces = {"serfs": 1}     # Sallyer (negligible)
    s.lords["al_mustain"].forces = {"serfs": 1}      # Front Defender
    s.lords["abu_bakr"].forces = {"men_at_arms": 6}  # Reserve Defender
    s.locales["coria"].siege_green = 0
    res, lanes = resolve_relief_sally(
        s, ["alfonso"], ["alvar_fanez"], ["al_mustain", "abu_bakr"],
        besieger_side="muslim", locale_id="coria", max_rounds=1)
    marchers, sallyers, def_front, def_rear, shared = lanes
    assert def_front is not None and def_rear is not None
    assert def_front is not def_rear           # separate Reserve lane
    assert not shared
    # Marchers cleared the Front Defender Serf.
    assert def_front.forces.get("serfs", 0) == 0
    # Reserve Defender Men-at-Arms only faced the 1 Sallyer Serf, so are
    # essentially intact (at most one routed by a single 1/2-Hit serf).
    assert def_rear.forces.get("men_at_arms", 0) >= 5


def test_no_reserve_defender_shared_front_lane() -> None:
    """When the Defender has no Reserve beyond its Front, the Sallyers
    Flank the Front Defenders (shared lane)."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    s.lords["alfonso"].forces = {"knights": 4}    # Marcher
    s.lords["alvar_fanez"].forces = {"knights": 4}  # Sallyer
    s.lords["al_mustain"].forces = {"serfs": 2}   # only Defender
    s.locales["coria"].siege_green = 0
    res, lanes = resolve_relief_sally(
        s, ["alfonso"], ["alvar_fanez"], ["al_mustain"],
        besieger_side="muslim", locale_id="coria", max_rounds=2)
    marchers, sallyers, def_front, def_rear, shared = lanes
    assert shared is True
    assert def_rear is def_front


def test_attacker_loss_reduces_siege_to_one() -> None:
    """4.5.3 aftermath: when the Attackers lose a Relief Sally, the
    besieger's Siege markers at the Locale reduce to one and the
    Sallying Lord Withdraws back into the (Friendly) Stronghold."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    # Christian Seat marker at coria makes it Friendly to Christians so
    # the Sallying Lord can Withdraw back inside.
    s.locales["coria"].seat_marker_lord_ids = ["alfonso"]
    s.locales["coria"].siege_green = 3
    from almoravid.state import Cylinder
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="coria")
    s.lords["alfonso"].in_stronghold = False     # sallied out
    s.lords["alfonso"].forces = {"knights": 2}   # survives Losses
    s.lords["alfonso"].routed_units = {}
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale",
                                              locale_id="coria")
    s.lords["al_mustain"].in_stronghold = False
    result = BattleResult(
        engagement="battle",
        attacker=BattleSide(side="christian", role="attacker",
                            lord_ids=["alfonso"], forces={"knights": 2}),
        defender=BattleSide(side="muslim", role="defender",
                            lord_ids=["al_mustain"],
                            forces={"knights": 5}),
        winner="muslim",
    )
    apply_relief_sally_aftermath(
        s, result, locale_id="coria", besieger_side="muslim")
    assert s.locales["coria"].siege_green == 1
    assert s.lords["alfonso"].in_stronghold is True
    assert any("reduced to 1" in n for n in result.notes)
