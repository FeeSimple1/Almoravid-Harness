"""FIX-C / B2 (rule 4.4.2 TOTAL HITS, Flanking).

All Hits landing on a given target Lord in a Strike step -- from the
directly-opposed actor Lord PLUS any Flanking actor Lords -- are SUMMED
in halves and rounded UP ONCE, not rounded per striking Lord.

These tests pin down the difference: two Lords each contributing 1/2 Hit
to the same target yield ONE Hit (0.5 + 0.5 = 1.0), whereas the prior
per-position rounding would have produced TWO Hits (ceil(0.5) twice).

Serf targets are used so each landed Hit is deterministic (Serfs
auto-remove with no Protection roll), making the Hit COUNT directly
observable as units removed regardless of RNG seed.
"""

from __future__ import annotations

from almoravid.battle import (
    BattleSide, LordPosition, _resolve_step, _sync_side_forces_from_array,
)
from almoravid.scenarios import load_scenario


def _side(side_name: str, role: str, arr: list[LordPosition]) -> BattleSide:
    bs = BattleSide(side=side_name, role=role,
                    lord_ids=[a.lord_id for a in arr], forces={})
    bs.array = arr
    _sync_side_forces_from_array(bs)
    return bs


def test_flanking_plus_opposed_sum_then_round_once() -> None:
    """Light Horse Melee is x1/2. One opposed Lord (0.5) + one Flanking
    Lord (0.5) on the same target = 1.0 -> ONE Hit (not two)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = _side("christian", "attacker", [
        LordPosition(lord_id="alfonso", position="front_center",
                     forces={"light_horse": 1}),
        LordPosition(lord_id="alvar_fanez", position="front_left",
                     forces={"light_horse": 1}),
    ])
    # Defender center is the only Front Lord with units, so attacker
    # left (its opposite empty) Flanks onto defender center.
    dfd = _side("muslim", "defender", [
        LordPosition(lord_id="al_mustain", position="front_center",
                     forces={"serfs": 5}),
        LordPosition(lord_id="abu_bakr", position="front_left",
                     forces={}),
    ])
    _resolve_step(s, "2.b", "attacker", "melee", "horse",
                  atk, dfd, round_index=1)
    center = next(lp for lp in dfd.array if lp.position == "front_center")
    # 0.5 + 0.5 = 1.0 -> 1 Hit -> 1 Serf removed (5 -> 4).
    assert center.forces.get("serfs", 0) == 4


def test_two_flanking_halves_plus_opposed_round_once() -> None:
    """Three Lords each contributing 1/2 Hit onto a single target
    (one opposed + two Flanking) = 1.5 -> 2 Hits (one rounding), not
    3 Hits (three separate ceilings)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = _side("christian", "attacker", [
        LordPosition(lord_id="alfonso", position="front_center",
                     forces={"light_horse": 1}),
        LordPosition(lord_id="alvar_fanez", position="front_left",
                     forces={"light_horse": 1}),
        LordPosition(lord_id="garcia", position="front_right",
                     forces={"light_horse": 1}),
    ])
    dfd = _side("muslim", "defender", [
        LordPosition(lord_id="al_mustain", position="front_center",
                     forces={"serfs": 6}),
        LordPosition(lord_id="abu_bakr", position="front_left",
                     forces={}),
        LordPosition(lord_id="abd_allah", position="front_right",
                     forces={}),
    ])
    _resolve_step(s, "2.b", "attacker", "melee", "horse",
                  atk, dfd, round_index=1)
    center = next(lp for lp in dfd.array if lp.position == "front_center")
    # 0.5 * 3 = 1.5 -> ceil = 2 Hits -> 2 Serfs removed (6 -> 4).
    assert center.forces.get("serfs", 0) == 4


def test_separate_opposed_targets_round_independently() -> None:
    """Two attacker Lords each opposed to their OWN target each deal
    1/2 Hit -> each rounds to 1 -> each target loses one Serf. Rounding
    is per-target, so distinct targets do NOT pool together."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = _side("christian", "attacker", [
        LordPosition(lord_id="alfonso", position="front_center",
                     forces={"light_horse": 1}),
        LordPosition(lord_id="alvar_fanez", position="front_left",
                     forces={"light_horse": 1}),
    ])
    dfd = _side("muslim", "defender", [
        LordPosition(lord_id="al_mustain", position="front_center",
                     forces={"serfs": 5}),
        LordPosition(lord_id="abu_bakr", position="front_left",
                     forces={"serfs": 5}),
    ])
    _resolve_step(s, "2.b", "attacker", "melee", "horse",
                  atk, dfd, round_index=1)
    center = next(lp for lp in dfd.array if lp.position == "front_center")
    left = next(lp for lp in dfd.array if lp.position == "front_left")
    # Each target separately: 0.5 -> 1 Hit -> 1 Serf removed.
    assert center.forces.get("serfs", 0) == 4
    assert left.forces.get("serfs", 0) == 4
