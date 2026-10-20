"""Rules 4.4.1-.2: missile ownership and independent Lord javelin timing."""
from almoravid.battle import (
    _build_strike_rows_for_position,
    _resolve_step,
    battle_side_from_snapshot,
    battle_side_to_snapshot,
    battleside_for_lords,
)
from almoravid.scenarios import load_scenario


def test_array_capability_does_not_arm_another_lord():
    s = load_scenario("sagrajas")
    side = battleside_for_lords(s, ["alfonso", "pedro_ansurez"],
                               "christian", "attacker")
    pedro = side.array[1]
    assert not pedro.capabilities_in_play
    rows = _build_strike_rows_for_position(s, side, pedro)
    assert all(r.kind == "melee" for r in rows)
    assert any(r.kind != "melee" for r in
               _build_strike_rows_for_position(s, side, side.array[0]))


def test_african_horse_have_native_javelins():
    s = load_scenario("sagrajas")
    side = battleside_for_lords(s, ["yusuf", "sir"], "muslim", "defender")
    for lp in side.array:
        rows = _build_strike_rows_for_position(s, side, lp)
        jav = [r for r in rows if r.kind == "javelins"]
        assert sum(r.count for r in jav) == lp.forces["african_horse"]
        assert all(r.one_round_only for r in jav)


def test_each_lord_can_choose_a_different_javelin_round():
    s = load_scenario("sagrajas", seed=3)
    for lid in ("yusuf", "sir"):
        s.lords[lid].forces = {"african_horse": 2}
    for lid in ("alfonso", "pedro_ansurez"):
        s.lords[lid].forces = {"knights": 20}
        s.lords[lid].capabilities = []
    mus = battleside_for_lords(s, ["yusuf", "sir"], "muslim", "attacker")
    chr_ = battleside_for_lords(s, ["alfonso", "pedro_ansurez"],
                               "christian", "defender")
    mus.array[0].javelin_round = 1
    mus.array[1].javelin_round = 2
    mus = battle_side_from_snapshot(battle_side_to_snapshot(mus))
    for rnd, hits in [(1, 2), (2, 2), (3, 0)]:
        step = _resolve_step(s, "1.b", "attacker", "missile", None,
                             mus, chr_, round_index=rnd)
        assert step.rounded_hits == hits
