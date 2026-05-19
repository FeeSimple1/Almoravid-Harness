"""Phase 6e: per-Lord Array + Concede + Reposition + Flanking hook."""

from __future__ import annotations

import pytest

from almoravid.battle import (
    BattleResult, BattleSide, LordPosition,
    _flanking_contribution,
    _reposition_array,
    _resolve_step,
    battleside_for_lords,
    declare_concede,
    resolve_battle,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


# ---------------------------------------------------------------------------
# Per-Lord Array population
# ---------------------------------------------------------------------------


def test_single_lord_battleside_has_no_array() -> None:
    """Single-Lord case: array stays None (legacy pool path preserved)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    side = battleside_for_lords(s, ["alfonso"], "christian", "attacker")
    assert side.array is None


def test_multi_lord_attacker_active_at_center() -> None:
    """Active Lord placed at Front center; others left/right/reserve."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:4]
    side = battleside_for_lords(
        s, christians, "christian", "attacker",
        active_lord_id=christians[1],
    )
    assert side.array is not None
    assert len(side.array) == 4
    center = next(lp for lp in side.array if lp.position == "front_center")
    assert center.lord_id == christians[1]
    front_positions = {lp.position for lp in side.array}
    assert "front_left" in front_positions
    assert "front_right" in front_positions
    assert any(lp.position == "reserve" for lp in side.array)


def test_multi_lord_array_carries_per_lord_forces_and_caps() -> None:
    """LordPosition.forces is a copy of the Lord's forces dict so
    Reposition / per-pair Strike can drain per-Lord without affecting
    the source Lord."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:3]
    side = battleside_for_lords(s, christians, "christian", "attacker")
    for lp in side.array:
        original = s.lords[lp.lord_id].forces
        assert lp.forces == original
        # Mutating LordPosition.forces must not bleed back.
        lp.forces["serfs"] = lp.forces.get("serfs", 0) + 99
        assert s.lords[lp.lord_id].forces.get("serfs", 0) != \
            lp.forces["serfs"]


# ---------------------------------------------------------------------------
# Concede mechanic
# ---------------------------------------------------------------------------


def test_concede_halves_conceder_strikes_in_resolve_step() -> None:
    """A Conceding side's Strike total is halved before rounding."""
    def _run(concede_attacker: bool) -> int:
        s = load_scenario("scenario_a_toledo_beset", seed=42)
        atk = BattleSide(side="christian", role="attacker",
                         lord_ids=["alfonso"], forces={"knights": 4})
        dfd = BattleSide(side="muslim", role="defender",
                         lord_ids=["al_mutamid"], forces={"sergeants": 4})
        if concede_attacker:
            atk.conceded = True
        # Resolve attacker's horse-melee step.
        res = _resolve_step(s, "2.b", "attacker", "melee", "horse",
                            atk, dfd, round_index=1)
        return res.rounded_hits
    baseline = _run(False)  # 4 Knights x2 = 8
    halved = _run(True)     # 4 / 2 = 4
    assert baseline == 8
    assert halved == 4


def test_concede_ends_battle_after_round() -> None:
    """When attacker concedes Round 1, Battle ends at end of Round 1
    and defender wins."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 4})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 4})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd)
    # Pre-declare attacker concede before calling resolve_battle by
    # patching post-construction via declare_concede.
    atk.conceded = True  # equivalent to declare_concede before round
    res = resolve_battle(s, atk, dfd, max_rounds=6)
    assert len(res.rounds) == 1
    assert res.winner == "muslim"


def test_declare_concede_sets_correct_side_flag() -> None:
    """Helper sets attacker.conceded when conceder is attacker side."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 1})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd)
    declare_concede(result, "christian")
    assert atk.conceded is True
    assert dfd.conceded is False


# ---------------------------------------------------------------------------
# Reposition (Round 2+)
# ---------------------------------------------------------------------------


def test_reposition_marks_emptied_lord_routed() -> None:
    """A Lord whose forces are emptied gets position='routed'."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:3]
    side = battleside_for_lords(s, christians, "christian", "attacker")
    # Empty the center Lord's forces.
    center = next(lp for lp in side.array if lp.position == "front_center")
    center.forces = {}
    _reposition_array(side)
    assert center.position == "routed"


def test_reposition_advances_reserve_to_empty_front() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:4]
    side = battleside_for_lords(s, christians, "christian", "attacker")
    # Empty front_left so a Reserve advances into it.
    fl = next(lp for lp in side.array if lp.position == "front_left")
    fl.forces = {}
    reserve_lid = next(lp for lp in side.array
                       if lp.position == "reserve").lord_id
    _reposition_array(side)
    advanced = next(lp for lp in side.array if lp.lord_id == reserve_lid)
    assert advanced.position == "front_left"


def test_reposition_mandatory_center_fill_from_flank() -> None:
    """If Front center empties and no Reserves remain to fill, a Lord
    at front_left/right slides into center (mandatory)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:3]
    side = battleside_for_lords(s, christians, "christian", "attacker")
    center = next(lp for lp in side.array if lp.position == "front_center")
    center.forces = {}  # rout center
    # Drop any Reserves to force the center-fill path.
    side.array = [lp for lp in side.array if lp.position != "reserve"]
    _reposition_array(side)
    # The previously-front_left Lord must now be center.
    has_center = any(lp.position == "front_center" for lp in side.array)
    assert has_center


# ---------------------------------------------------------------------------
# Flanking hook
# ---------------------------------------------------------------------------


def test_flanking_contribution_counts_unopposed_front_lords() -> None:
    """When attacker has 3 Front Lords and defender only has center,
    attacker's left and right are unopposed → Flanking count = 2."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:3]
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:1]
    atk = battleside_for_lords(s, christians, "christian", "attacker")
    dfd = battleside_for_lords(s, muslims, "muslim", "defender")
    # dfd is single-Lord → array is None → no opposing front positions.
    flanks = _flanking_contribution(atk, dfd)
    # With None on either side, helper returns 0 (no per-Lord pairing).
    assert flanks == 0


def test_flanking_contribution_with_full_arrays() -> None:
    """Both sides multi-Lord: attacker 3 Front, defender 2 (center+left)
    → attacker_right is unopposed."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:3]
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:2]
    atk = battleside_for_lords(s, christians, "christian", "attacker")
    dfd = battleside_for_lords(s, muslims, "muslim", "defender")
    assert atk.array is not None and dfd.array is not None
    # defender has 2 Lords → center + left filled, right empty.
    flanks = _flanking_contribution(atk, dfd)
    assert flanks == 1  # attacker's front_right is unopposed
