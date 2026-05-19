"""Phase 6g: round-robin Spoils distribution + per-LordPosition M7."""

from __future__ import annotations

from almoravid.battle import (
    BattleResult, BattleSide,
    _consume_camp_attack,
    battleside_for_lords,
    distribute_spoils_round_robin,
    init_m7_cap,
)
from almoravid.scenarios import load_scenario


def test_distribute_spoils_round_robin_basic() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:3]
    for lid in christians:
        s.lords[lid].assets = {}
    spoils = {"coin": 5, "loot": 2}
    out = distribute_spoils_round_robin(s, christians, spoils)
    # 5 coin -> 2/2/1 across 3 Lords; 2 loot -> 1/1/0
    counts = {lid: sum(s.lords[lid].assets.values()) for lid in christians}
    assert sum(counts.values()) == 7
    # First Lord gets first dibs on each Asset kind round.
    assert s.lords[christians[0]].assets.get("coin", 0) == 2
    assert s.lords[christians[1]].assets.get("coin", 0) == 2
    assert s.lords[christians[2]].assets.get("coin", 0) == 1
    assert s.lords[christians[0]].assets.get("loot", 0) == 1


def test_distribute_spoils_empty_friendly_list_no_op() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    out = distribute_spoils_round_robin(s, [], {"coin": 5})
    assert out == {}


def test_camp_attack_now_distributes_spoils_round_robin() -> None:
    """C2 fired by Christian side: enemy al_mutamid gives 2 coin as
    Spoils; with 3 Christian Lords at Battle, distributed round-robin
    (Lord0 gets the 1st, Lord1 gets the 2nd, Lord2 gets 0)."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    s.decks.this_campaign_events["christian"] = ["C2"]
    s.lords["al_mutamid"].assets = {"coin": 10}
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian"][:3]
    for lid in christians:
        s.lords[lid].assets = {}
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=list(christians), forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 1})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd)
    _consume_camp_attack(s, atk, dfd, result)
    coin_total = sum(s.lords[lid].assets.get("coin", 0) for lid in christians)
    assert coin_total == 2  # 2 spoils distributed
    assert s.lords[christians[0]].assets.get("coin", 0) == 1
    assert s.lords[christians[1]].assets.get("coin", 0) == 1
    assert s.lords[christians[2]].assets.get("coin", 0) == 0


# ---------------------------------------------------------------------------
# Per-LordPosition M7 markers
# ---------------------------------------------------------------------------


def test_init_m7_marks_top_two_lords() -> None:
    """With M7 held, the two Muslim Lords with the highest MaA+AF get
    m7_marked=True; the rest don't."""
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    s.decks.this_levy_events["muslim"] = ["M7"]
    muslims = [lid for lid, l in s.lords.items()
               if l.side == "muslim"][:3]
    # Give them MaA counts 5/3/1.
    for lid, n in zip(muslims, [5, 3, 1]):
        s.lords[lid].forces = {"men_at_arms": n}
    bs = battleside_for_lords(s, muslims, "muslim", "defender",
                              active_lord_id=muslims[0])
    init_m7_cap(s, bs)
    marked = {lp.lord_id for lp in bs.array if lp.m7_marked}
    assert marked == {muslims[0], muslims[1]}  # top 2 by MaA


def test_init_m7_no_array_falls_back_to_cap() -> None:
    """Single-Lord BattleSide (array None) still gets the side-level
    cap so the pool-path M7 hook works."""
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    s.decks.this_levy_events["muslim"] = ["M7"]
    s.lords["al_mutamid"].forces = {"men_at_arms": 4}
    bs = BattleSide(side="muslim", role="defender",
                    lord_ids=["al_mutamid"],
                    forces={"men_at_arms": 4})
    init_m7_cap(s, bs)
    assert bs.m7_boosts_remaining == 4


def test_init_m7_skips_unmarked_lord_in_per_pair() -> None:
    """Verify per-Lord M7 marker actually fires in the per-pair path:
    a marked vs unmarked LordPosition with identical units should see
    different survival rates."""
    from almoravid.battle import _resolve_step
    survivors_marked = 0
    survivors_unmarked = 0
    trials = 30
    for seed in range(trials):
        for marked in (True, False):
            s = load_scenario("scenario_a_toledo_beset", seed=seed)
            christians = [lid for lid, l in s.lords.items()
                          if l.side == "christian"][:2]
            muslims = [lid for lid, l in s.lords.items()
                       if l.side == "muslim"][:2]
            for lid in christians:
                s.lords[lid].forces = {"knights": 2}
            for lid in muslims:
                s.lords[lid].forces = {"men_at_arms": 4}
            s.decks.this_levy_events["muslim"] = ["M7"]
            atk = battleside_for_lords(s, christians, "christian",
                                        "attacker",
                                        active_lord_id=christians[0])
            dfd = battleside_for_lords(s, muslims, "muslim", "defender",
                                        active_lord_id=muslims[0])
            init_m7_cap(s, dfd)
            # Force only `marked` outcome on the defender front_center.
            for lp in dfd.array:
                if lp.position == "front_center":
                    lp.m7_marked = marked
                else:
                    lp.m7_marked = False
            _resolve_step(s, "2.b", "attacker", "melee", "horse",
                          atk, dfd, round_index=1)
            center_lp = next(lp for lp in dfd.array
                             if lp.position == "front_center")
            survivors = center_lp.forces.get("men_at_arms", 0)
            if marked:
                survivors_marked += survivors
            else:
                survivors_unmarked += survivors
    # Marked center should survive better on average.
    assert survivors_marked > survivors_unmarked
