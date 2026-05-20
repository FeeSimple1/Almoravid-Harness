"""FIX-C / B4 (rules 4.4.1 Array, 4.4.2 new-round check).

Two related fixes:

1. Defender placement (4.4.1): the Defender places exactly one Lord
   directly opposite each Attacking Front Lord; all extras go to
   Reserve. Previously the Defender always filled up to three Front
   positions regardless of the Attacker's Front count, leaving a
   permanently-unopposed Front Defender that never took Hits and could
   spin the Battle to its round cap.

2. _battle_over / winner (4.4.2): the Battle ends when ALL of a side's
   Lords have Routed -- Reserve Lords keep the side in the Battle and
   Advance to Front at the next Reposition, so a side that is reduced
   to Reserve-only is NOT yet defeated.
"""

from __future__ import annotations

from almoravid.battle import (
    BattleSide, LordPosition, _battle_over, _front_lord_count,
    _side_all_lords_routed, _sync_side_forces_from_array,
    battleside_for_lords, resolve_battle,
)
from almoravid.scenarios import load_scenario


def _side(side_name: str, role: str, arr: list[LordPosition]) -> BattleSide:
    bs = BattleSide(side=side_name, role=role,
                    lord_ids=[a.lord_id for a in arr], forces={})
    bs.array = arr
    _sync_side_forces_from_array(bs)
    return bs


# ---------------------------------------------------------------------------
# 4.4.1 Defender placement: Front count capped at Attacker's
# ---------------------------------------------------------------------------


def test_front_limit_two_sends_third_lord_to_reserve() -> None:
    """A 3-Lord side with front_limit=2 fills center + left only; the
    third Lord starts in Reserve (rule 4.4.1)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lords = [lid for lid, l in s.lords.items() if l.side == "muslim"][:3]
    side = battleside_for_lords(s, lords, "muslim", "defender",
                                front_limit=2)
    pos = {lp.position for lp in side.array}
    assert "front_center" in pos
    assert "front_left" in pos
    assert "front_right" not in pos
    assert sum(1 for lp in side.array if lp.position == "reserve") == 1


def test_attacker_default_keeps_three_fronts_plus_reserve() -> None:
    """The Attacker uses the default front_limit=3: 4 Lords -> 3 Front
    + 1 Reserve, Active Lord at center."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lords = [lid for lid, l in s.lords.items() if l.side == "christian"][:4]
    side = battleside_for_lords(s, lords, "christian", "attacker",
                                active_lord_id=lords[2])
    center = next(lp for lp in side.array if lp.position == "front_center")
    assert center.lord_id == lords[2]
    fronts = sum(1 for lp in side.array
                 if lp.position.startswith("front_"))
    assert fronts == 3
    assert sum(1 for lp in side.array if lp.position == "reserve") == 1


def test_front_lord_count_reflects_array() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    chr2 = [lid for lid, l in s.lords.items() if l.side == "christian"][:2]
    atk = battleside_for_lords(s, chr2, "christian", "attacker",
                               active_lord_id=chr2[0])
    assert _front_lord_count(atk) == 2
    # Single-Lord (pooled) side: exactly one Front Lord.
    one = battleside_for_lords(s, chr2[:1], "christian", "attacker")
    assert one.array is None
    assert _front_lord_count(one) == 1


# ---------------------------------------------------------------------------
# 4.4.2 termination: Reserve-only side is NOT defeated
# ---------------------------------------------------------------------------


def test_reserve_only_side_is_not_defeated() -> None:
    """A side whose Front Lords have all Routed but which still has a
    Reserve Lord with units is NOT considered all-Lords-routed."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = _side("christian", "attacker", [
        LordPosition(lord_id="alfonso", position="front_center",
                     forces={"knights": 3}),
    ])
    dfd = _side("muslim", "defender", [
        LordPosition(lord_id="al_mustain", position="front_center",
                     forces={}),                       # routed-empty Front
        LordPosition(lord_id="abu_bakr", position="reserve",
                     forces={"men_at_arms": 2}),       # Reserve survivor
    ])
    assert not _side_all_lords_routed(dfd)
    assert not _battle_over(atk, dfd)


def test_all_positions_empty_is_defeated() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = _side("christian", "attacker", [
        LordPosition(lord_id="alfonso", position="front_center",
                     forces={"knights": 3}),
    ])
    dfd = _side("muslim", "defender", [
        LordPosition(lord_id="al_mustain", position="front_center",
                     forces={}),
        LordPosition(lord_id="abu_bakr", position="reserve", forces={}),
    ])
    assert _side_all_lords_routed(dfd)
    assert _battle_over(atk, dfd)


def test_reserve_lord_advances_and_battle_terminates() -> None:
    """End-to-end: Attacker (2 strong Front Lords) vs Defender (2 weak
    Front + 1 Reserve). The Defender's Front routs Round 1; the Reserve
    Advances Round 2 and is then defeated -- the Battle terminates with
    a decided winner (not an inconclusive max-rounds spin)."""
    s = load_scenario("scenario_a_toledo_beset", seed=4)
    chr2 = [lid for lid, l in s.lords.items() if l.side == "christian"][:2]
    mus3 = [lid for lid, l in s.lords.items() if l.side == "muslim"][:3]
    for c in chr2:
        s.lords[c].forces = {"knights": 20}
    atk = battleside_for_lords(s, chr2, "christian", "attacker",
                               active_lord_id=chr2[0])
    # front_limit=2 -> defender gets 2 Front + 1 Reserve.
    dfd = battleside_for_lords(s, mus3, "muslim", "defender",
                               front_limit=_front_lord_count(atk))
    s.lords[mus3[0]].forces = {"serfs": 1}
    s.lords[mus3[1]].forces = {"serfs": 1}
    s.lords[mus3[2]].forces = {"men_at_arms": 4}
    # Re-sync per-Lord forces into the array (we just rewrote them).
    for lp in dfd.array:
        lp.forces = dict(s.lords[lp.lord_id].forces)
    _sync_side_forces_from_array(dfd)
    assert sum(1 for lp in dfd.array if lp.position == "reserve") == 1
    res = resolve_battle(s, atk, dfd, max_rounds=20)
    assert res.winner == "christian"
    assert "inconclusive" not in " ".join(res.notes)
