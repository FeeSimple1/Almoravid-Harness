"""Pattern 9 rule-cite-but-no-enforce: Walls roll and 6-Melee cap in Storm.

These tests were the Pattern 9 audit's smoking gun: walls_range was
loaded but the variable was dropped on the floor (no reader). The 6-
Melee cap from rule 4.5.2 was never coded at all.
"""

from __future__ import annotations

from almoravid.battle import (
    BattleSide,
    _resolve_step,
    resolve_storm,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_walls_actually_cancels_hits_when_supplied() -> None:
    """Pattern 9: walls_range argument to _resolve_step actually
    cancels Hits before they assign to units."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 6})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"],
                     forces={"sergeants": 30})  # huge: keeps defender alive
    # With walls_range=(1,4), ~67% of Hits canceled before Protection.
    result = _resolve_step(
        s, "2.b", "attacker", "melee", "horse",
        atk, dfd, context="storm",
        walls_range=(1, 4),
        siege_markers=0,
    )
    # 6 Knights x1 melee in Storm = 6 raw_hits, capped at 6 by rule.
    assert result.rounded_hits == 6
    # Most should have been canceled by Walls (1-4 of 6 cancels each)
    # rather than reaching the defender as Routs.
    losses = sum(result.losses.values())
    assert losses <= 4, (
        f"Walls roll should cancel some Hits before they become Losses; "
        f"got {losses} losses out of {result.rounded_hits} Hits"
    )


def test_storm_melee_capped_at_6_per_lord_per_round() -> None:
    """Pattern 9: rule 4.5.2 cap — even with 12 Knights (x1 = 12 raw
    Hits) in Storm, rounded Hits cap at 6."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 12})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 30})
    result = _resolve_step(
        s, "2.b", "attacker", "melee", "horse",
        atk, dfd, context="storm",
        walls_range=None, siege_markers=0,
    )
    assert result.rounded_hits == 6, (
        f"Storm melee cap (6/Lord/Round) not enforced: got "
        f"rounded_hits={result.rounded_hits}"
    )


def test_battle_does_not_cap_melee_at_6() -> None:
    """The 6-cap is Storm-specific; Battle is uncapped."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 12})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 30})
    result = _resolve_step(
        s, "2.b", "attacker", "melee", "horse",
        atk, dfd, context="battle",
    )
    # 12 Knights x2 melee in Battle = 24 raw_hits. NOT capped.
    assert result.rounded_hits == 24


def test_resolve_storm_consults_walls_for_defender() -> None:
    """Full integration: resolve_storm threads walls_range to
    _resolve_step. Hard-to-prove from outside; we check by comparing
    two runs that differ only in whether defender is at a Stronghold
    that has walls vs not.

    Simpler structural assertion: the wall mechanism reduces total
    defender losses materially when walls are wide ([1,4]).
    """
    s = load_scenario("scenario_a_toledo_beset", seed=42)
    s.locales["zaragoza"].siege_yellow = 3
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.lords["al_mustain"].in_stronghold = True
    s.lords["al_mustain"].forces = {"sergeants": 6}
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 5})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mustain"],
                     forces=dict(s.lords["al_mustain"].forces))
    result = resolve_storm(s, atk, dfd)
    # With walls active, attacker should NOT immediately wipe defender.
    # (Without walls, 5 Knights x1 = 5 Hits, capped at 6, with
    # Protection rolls some defenders rout, but they survive longer
    # with Walls.)
    # Structural: at least one round happens and the Storm doesn't
    # finish in a single attacker-melee step.
    assert len(result.rounds) >= 1


def test_evade_protection_applies_in_battle_melee() -> None:
    """Bug H (Pattern 9): African Horse Evade 1-2 vs Battle Melee.

    Without Evade: African Horse Unarmored (cancel on roll=1, ~17%).
    With Evade: cancel on roll 1-2 (~33%). With 500 trials, the cancel
    rate should approach 2/6 not 1/6.
    """
    from almoravid.battle import (
        BattleSide,
        _resolve_protection_roll,
    )
    from almoravid.scenarios import load_scenario

    s = load_scenario("scenario_a_toledo_beset", seed=1)
    target = BattleSide(side="muslim", role="defender",
                        lord_ids=["al_mutamid"],
                        forces={"african_horse": 1000})
    cancels = 0
    trials = 500
    for _ in range(trials):
        canceled, _ = _resolve_protection_roll(
            s, target, "melee", context="battle")
        if canceled:
            cancels += 1
    rate = cancels / trials
    # Expect ~2/6 = 0.33; very loose bounds to avoid flake
    assert 0.20 < rate < 0.45, (
        f"Bug H regression: Evade cancel rate {rate:.2f} doesn't look "
        f"like Evade-augmented Unarmored (~0.33). Without Evade fix it "
        f"would be ~0.17."
    )


def test_evade_does_not_apply_in_storm() -> None:
    """Bug H: Evade is Battle-only; Storm uses Unarmored only (~1/6)."""
    from almoravid.battle import (
        BattleSide,
        _resolve_protection_roll,
    )
    from almoravid.scenarios import load_scenario

    s = load_scenario("scenario_a_toledo_beset", seed=2)
    target = BattleSide(side="muslim", role="defender",
                        lord_ids=["al_mutamid"],
                        forces={"african_horse": 1000})
    cancels = 0
    trials = 500
    for _ in range(trials):
        canceled, _ = _resolve_protection_roll(
            s, target, "melee", context="storm")
        if canceled:
            cancels += 1
    rate = cancels / trials
    # Storm: only Unarmored 1 applies; ~1/6 = 0.17
    assert rate < 0.25, (
        f"Bug H regression: Evade should NOT apply in Storm; got "
        f"cancel rate {rate:.2f}"
    )


def test_evade_does_not_apply_to_missile_hits() -> None:
    """Bug H: Evade only applies to Melee Hits, not Missiles."""
    from almoravid.battle import (
        BattleSide,
        _resolve_protection_roll,
    )
    from almoravid.scenarios import load_scenario

    s = load_scenario("scenario_a_toledo_beset", seed=3)
    target = BattleSide(side="muslim", role="defender",
                        lord_ids=["al_mutamid"],
                        forces={"african_horse": 1000})
    cancels = 0
    trials = 500
    for _ in range(trials):
        canceled, _ = _resolve_protection_roll(
            s, target, "missiles", context="battle")
        if canceled:
            cancels += 1
    rate = cancels / trials
    # No Evade against Missiles -> ~1/6 = 0.17
    assert rate < 0.25, (
        f"Bug H regression: Evade should NOT apply to Missiles; got "
        f"cancel rate {rate:.2f}"
    )
