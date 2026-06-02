"""Crossbows are -1 vs Armor (Quick Ref Table 1 / Errata): a Crossbow Hit
resolves against the Armored target's Protection range reduced by 1."""
from __future__ import annotations

from almoravid.battle import BattleSide, _resolve_protection_roll
from almoravid.scenarios import load_scenario


def _knight_target(seed):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    # Knights are Armored 1-4; with -1 vs Armor the cancel range is 1-3.
    t = BattleSide(side="christian", role="defender", lord_ids=["alfonso"],
                   forces={"knights": 1})
    return s, t


def test_crossbow_minus_one_vs_armor_can_only_reduce_cancels() -> None:
    distinguishing = 0
    for seed in range(80):
        s0, t0 = _knight_target(seed)
        c0, _ = _resolve_protection_roll(s0, t0, "missiles",
                                         striker_selects=True,
                                         striker_minus_armor=0)
        s1, t1 = _knight_target(seed)
        c1, _ = _resolve_protection_roll(s1, t1, "missiles",
                                         striker_selects=True,
                                         striker_minus_armor=1)
        # Reducing the Armor range can never turn a non-cancel INTO a cancel.
        assert not (c1 and not c0), f"seed {seed}: -1 armor created a cancel"
        # A Protection roll of exactly 4 cancels at 1-4 but not at 1-3.
        if c0 and not c1:
            distinguishing += 1
    assert distinguishing > 0   # the -1 demonstrably matters (roll of 4)
