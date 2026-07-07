"""this_lord missile-cap scoping on the Sally and Relief paths (4.4.2).

Mirror of d4f4ec3 (pooled Battle) and the Storm cap_groups fix: a
Crossbows/Bowmen/Javelins capability held by ONE Lord must not arm a
co-located same-side Lord's units. Also covers the pooled-staleness
clamp: capability rows never exceed the live pooled survivor counts.
"""
from __future__ import annotations

from almoravid.battle import BattleSide, LordPosition, build_strike_rows
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _missile_raw(rows):
    from almoravid.battle import _dedupe_missile_overlap, _step_hits
    rows = [r for r in rows if not r.one_round_only]
    rows = _dedupe_missile_overlap(rows)
    raw, by_kind = _step_hits(rows, "missile", None)
    return raw, by_kind


def test_cap_groups_scope_missiles_to_holder() -> None:
    """Two Lords pooled, only one holds C2: only HIS 2 MaA fire
    Crossbows (1.0 raw), not the pooled 4 MaA (2.0)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    side = BattleSide(side="christian", role="attacker",
                      lord_ids=["alfonso", "alvar_fanez"],
                      forces={"men_at_arms": 4},
                      capabilities_in_play=["C2"])
    side.cap_groups = [(["C2"], {"men_at_arms": 2}),
                       ([], {"men_at_arms": 2})]
    raw, by_kind = _missile_raw(build_strike_rows(s, side, context="battle"))
    assert raw == 1.0
    assert by_kind == {"crossbows": 1.0}


def test_cap_groups_clamped_to_live_pooled_survivors() -> None:
    """After pooled losses (side.forces drained), stale per-Lord group
    counts are clamped: 2 MaA left pooled -> at most 2 fire, even
    though the snapshot says 2+2."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    side = BattleSide(side="christian", role="attacker",
                      lord_ids=["alfonso", "alvar_fanez"],
                      forces={"men_at_arms": 2},   # 2 already Routed
                      capabilities_in_play=["C2"])
    side.cap_groups = [(["C2"], {"men_at_arms": 2}),
                       (["C2"], {"men_at_arms": 2})]
    raw, by_kind = _missile_raw(build_strike_rows(s, side, context="battle"))
    assert raw == 1.0            # 2 surviving MaA x 1/2, not 4 x 1/2


def test_array_groups_also_clamped() -> None:
    """The pooled path with a stale side.array gets the same clamp."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    side = BattleSide(side="christian", role="attacker",
                      lord_ids=["alfonso"],
                      forces={"men_at_arms": 1},
                      capabilities_in_play=[])
    side.array = [
        LordPosition(lord_id="alfonso", position="front_center",
                     forces={"men_at_arms": 3},
                     capabilities_in_play=["C2"]),
        LordPosition(lord_id="alvar_fanez", position="front_left",
                     forces={}, capabilities_in_play=[]),
    ]
    raw, _ = _missile_raw(build_strike_rows(s, side, context="battle"))
    assert raw == 0.5            # clamped to the 1 pooled survivor


def test_sally_multi_lord_sides_get_cap_groups() -> None:
    """cmd_sally wires per-Lord cap scoping for BOTH pooled sides."""
    from almoravid.actions import apply_action
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Two Besieged Muslim Lords inside Zaragoza (al_mustain holds M2),
    # two Christian besiegers outside (alvar holds C2).
    for lid, inside in (("al_mustain", True), ("al_mutamid", True),
                        ("alfonso", False), ("alvar_fanez", False)):
        s.lords[lid].cylinder = Cylinder(kind="locale",
                                         locale_id="zaragoza")
        s.lords[lid].in_stronghold = inside
    s.lords["al_mustain"].capabilities = ["M2"]
    s.lords["al_mutamid"].capabilities = []
    s.lords["alvar_fanez"].capabilities = ["C2"]
    s.lords["alfonso"].capabilities = []
    s.locales["zaragoza"].siege_yellow = 2
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "muslim"
    s.meta.active_lord_id = "al_mustain"
    s.meta.actions_remaining = 1

    captured = {}
    import almoravid.battle as B
    orig = B.resolve_sally

    def spy(state, atk, dfd, **kw):
        captured["atk"] = atk.cap_groups
        captured["dfd"] = dfd.cap_groups
        return orig(state, atk, dfd, **kw)

    B.resolve_sally = spy
    try:
        apply_action(s, {"type": "cmd_sally", "side": "muslim"})
    finally:
        B.resolve_sally = orig
    assert captured["atk"] is not None and len(captured["atk"]) == 2
    assert captured["dfd"] is not None and len(captured["dfd"]) == 2
    atk_caps = {tuple(c) for c, _f in captured["atk"]}
    assert ("M2",) in atk_caps and () in atk_caps
