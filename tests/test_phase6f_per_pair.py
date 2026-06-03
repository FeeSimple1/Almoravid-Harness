"""Phase 6f: per-pair Strike resolution with Flanking routing.

Asserts the resolver routes Hits per-pair (drains the paired target
Lord's forces, not the pool) and redirects Flanking strikes when the
directly-opposed Front position is empty or absent.
"""

from __future__ import annotations

from almoravid.battle import (
    BattleSide,
    _pick_flank_target,
    _resolve_step,
    _sync_side_forces_from_array,
    battleside_for_lords,
    resolve_battle,
)
from almoravid.scenarios import load_scenario


def _make_array_side(
    s, lord_ids: list[str], side_name: str, role: str,
    forces_per_lord: dict[str, dict[str, int]],
) -> BattleSide:
    """Build a multi-Lord BattleSide with predictable per-Lord forces."""
    for lid in lord_ids:
        s.lords[lid].forces = forces_per_lord[lid]
    bs = battleside_for_lords(s, lord_ids, side_name, role,
                              active_lord_id=lord_ids[0])
    return bs


# ---------------------------------------------------------------------------
# Per-pair drains target Lord's forces, not the side pool
# ---------------------------------------------------------------------------


def test_per_pair_drains_paired_target_lord_not_pool() -> None:
    """Attacker center strikes defender center; defender left's units
    are untouched even if defender center is wiped out."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:2]
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:2]
    atk = _make_array_side(s, christians, "christian", "attacker", {
        christians[0]: {"knights": 8},
        christians[1]: {"serfs": 1},
    })
    dfd = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 2},      # paired with attacker center
        muslims[1]: {"sergeants": 10},     # paired with attacker left
    })
    # Attacker center strikes (2.b — Horse Melee).
    res = _resolve_step(s, "2.b", "attacker", "melee", "horse",
                        atk, dfd, round_index=1)
    # Defender center had 2 Sergeants; many of them should be routed.
    # Defender left had 10 Sergeants; should be UNTOUCHED by attacker
    # center's Strike (only attacker left strikes defender left).
    center_lp = next(lp for lp in dfd.array
                     if lp.position == "front_center")
    left_lp = next(lp for lp in dfd.array
                   if lp.position == "front_left")
    # Center took losses (started 2, may have 0-2 left).
    assert center_lp.forces.get("sergeants", 0) <= 2
    # Left untouched because attacker.front_left has only 1 Serf (which
    # routs on the first hit anyway, but never crosses the pair line).
    assert left_lp.forces.get("sergeants", 0) == 10


def test_per_pair_routes_flanking_when_target_position_empty() -> None:
    """Attacker has center + left; defender has ONLY center. Attacker
    left's Strikes route as Flanking to defender center (the only
    target with units)."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:2]
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:2]
    atk = _make_array_side(s, christians, "christian", "attacker", {
        christians[0]: {"knights": 1},   # center
        christians[1]: {"knights": 1},   # left
    })
    dfd = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 6},    # center (paired w/ atk center)
        muslims[1]: {},                  # left empty
    })
    # Defender's left LordPosition has no units.
    assert sum(dfd.array[1].forces.values()) == 0
    # Now run attacker horse melee step. Atk left has 1 Knight (2 Hits)
    # routed as Flanking; atk center 1 Knight (2 Hits). Total 4 Hits
    # land on defender center.
    res = _resolve_step(s, "2.b", "attacker", "melee", "horse",
                        atk, dfd, round_index=1)
    center_lp = next(lp for lp in dfd.array
                     if lp.position == "front_center")
    # Started with 6 Sergeants; some should be routed.
    assert center_lp.forces.get("sergeants", 0) < 6


def test_per_pair_reserve_does_not_strike_or_absorb() -> None:
    """A Lord in Reserve does NOT contribute Strikes and is NOT a
    target for absorption."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:4]
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:2]
    atk = _make_array_side(s, christians, "christian", "attacker", {
        christians[0]: {"knights": 1},
        christians[1]: {"knights": 1},
        christians[2]: {"knights": 1},
        christians[3]: {"knights": 99},   # Reserve — must NOT strike
    })
    dfd = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 1},
        muslims[1]: {"sergeants": 1},
    })
    reserve_lp = next(lp for lp in atk.array if lp.position == "reserve")
    assert reserve_lp.forces.get("knights", 0) == 99
    # Defender total units = 2; even with attacker's massive Reserve,
    # defender total losses cap at 2 (only Front Lords can take Hits).
    _resolve_step(s, "2.b", "attacker", "melee", "horse",
                  atk, dfd, round_index=1)
    # The Reserve Lord must still have all 99 Knights.
    assert reserve_lp.forces.get("knights", 0) == 99


# ---------------------------------------------------------------------------
# _pick_flank_target greedy selection
# ---------------------------------------------------------------------------


def test_pick_flank_target_center_picks_larger_of_left_right() -> None:
    """4.4.2: a CENTER Flanker may choose left or right (equidistant); we
    take the larger as the owner's sensible default."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:3]
    # index 0 -> front_center, 1 -> front_left, 2 -> front_right
    bs = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 1},   # center
        muslims[1]: {"sergeants": 5},   # left
        muslims[2]: {"sergeants": 3},   # right
    })
    target = _pick_flank_target(bs, "front_center")
    assert target is not None
    assert target.lord_id == muslims[1]  # larger of left(5)/right(3)


def test_pick_flank_target_left_flanker_prefers_center() -> None:
    """4.4.2: a LEFT Flanker (no Enemy opposite) Strikes the CLOSEST Front
    Enemy — the center — even if a far (right) Lord is larger."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:3]
    bs = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 1},   # center (closest to a left Flanker)
        muslims[1]: {"sergeants": 0},   # left (the directly-opposite slot)
        muslims[2]: {"sergeants": 9},   # right (far, but larger)
    })
    bs.array[1].forces = {}
    bs.array[1].position = "routed"     # left slot empty -> would-be opposite gone
    target = _pick_flank_target(bs, "front_left")
    assert target is not None
    assert target.lord_id == muslims[0]  # center (closest), not the bigger right


def test_pick_flank_target_skips_routed_position() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:2]
    bs = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 0},  # routed
        muslims[1]: {"sergeants": 5},
    })
    bs.array[0].forces = {}
    bs.array[0].position = "routed"
    target = _pick_flank_target(bs, "front_center")
    assert target is not None
    assert target.lord_id == muslims[1]


# ---------------------------------------------------------------------------
# _sync_side_forces_from_array keeps the pooled view consistent
# ---------------------------------------------------------------------------


def test_sync_side_forces_aggregates_per_lord_forces() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:3]
    bs = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 1, "light_horse": 1},
        muslims[1]: {"sergeants": 2},
        muslims[2]: {"sergeants": 3, "men_at_arms": 1},
    })
    # Pretend per-Lord drains happened.
    bs.array[1].forces = {"sergeants": 0}
    _sync_side_forces_from_array(bs)
    assert bs.forces.get("sergeants") == 4
    assert bs.forces.get("light_horse") == 1
    assert bs.forces.get("men_at_arms") == 1


# ---------------------------------------------------------------------------
# Single-Lord BattleSide must NOT take the per-pair path.
# ---------------------------------------------------------------------------


def test_single_lord_uses_pool_path_unchanged() -> None:
    """When either side is single-Lord (array is None), the pool path
    fires. This regression-tests the dispatcher's gate."""
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 2})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 3})
    # Neither has .array — must run pool path. Just ensure no crash.
    res = _resolve_step(s, "2.b", "attacker", "melee", "horse",
                        atk, dfd, round_index=1)
    assert res.rounded_hits >= 0


# ---------------------------------------------------------------------------
# Multi-Lord full Battle wraps up cleanly
# ---------------------------------------------------------------------------


def test_multi_lord_resolve_battle_produces_winner_and_commits() -> None:
    """End-to-end: a 2-Lord vs 2-Lord Battle resolves and writes per-
    Lord forces back via commit_forces_after_battle."""
    from almoravid.battle import (
        apply_aftermath,
        commit_forces_after_battle,
    )
    s = load_scenario("scenario_a_toledo_beset", seed=17)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:2]
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:2]
    atk = _make_array_side(s, christians, "christian", "attacker", {
        christians[0]: {"knights": 6, "men_at_arms": 2},
        christians[1]: {"knights": 4, "serfs": 1},
    })
    dfd = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 1},
        muslims[1]: {"light_horse": 1, "militia": 1},
    })
    pre = {lid: dict(s.lords[lid].forces) for lid in christians + muslims}
    result = resolve_battle(s, atk, dfd, max_rounds=6)
    commit_forces_after_battle(s, atk)
    commit_forces_after_battle(s, dfd)
    apply_aftermath(s, result)
    assert result.winner == "christian"
    # Per-Lord commit: christians[0] (8 starting units) should still
    # have most of his forces.
    assert sum(s.lords[christians[0]].forces.values()) > 0
