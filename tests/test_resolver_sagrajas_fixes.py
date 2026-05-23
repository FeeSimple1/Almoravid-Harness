"""Battle-resolver fixes exposed by the Sagrajas minigame.

(a) one_round_only Javelin rows fire on ONE Round only (Round 1 default),
    not every Round (Arts of War ref C7/M3: "on any 1 Battle Round (mark)").
(b) Jabalinas (C7) / Harbah (M3,M6): "Up to 4 of this Lord's Unarmored
    units" -> the Javelin-granting count caps at 4 across the Lord's
    Unarmored types, not every eligible unit.
(c) Cantador (C8): "up to 4 of that Lord's Knights AND Sergeants" -> at most
    +4 Melee Hits to ONE Christian Lord in Round 1, not +4 per Lord.
(d) StepResolution distinguishes rounded_hits (Hits dealt, pre-Protection)
    from units_routed (post-Protection routs).
"""
from __future__ import annotations

from almoravid.battle import (BattleSide, LordPosition, StepResolution,
                              build_strike_rows, _resolve_step)
from almoravid.scenarios import load_scenario


def _state():
    return load_scenario("scenario_a_toledo_beset", seed=1)


# --- (b) Javelin cap of 4 -------------------------------------------------
def test_javelin_units_capped_at_four_single_type():
    s = _state()
    side = BattleSide(side="christian", role="attacker", lord_ids=["x"],
                      forces={"militia": 6}, capabilities_in_play=["C7"])
    jav = [r for r in build_strike_rows(s, side) if r.kind == "javelins"]
    assert sum(r.count for r in jav) == 4, jav


def test_javelin_units_capped_at_four_across_unarmored_types():
    s = _state()
    side = BattleSide(side="christian", role="attacker", lord_ids=["x"],
                      forces={"light_horse": 3, "militia": 3},
                      capabilities_in_play=["C7"])
    jav = [r for r in build_strike_rows(s, side) if r.kind == "javelins"]
    assert sum(r.count for r in jav) == 4, jav


def test_no_javelins_without_capability():
    s = _state()
    side = BattleSide(side="christian", role="attacker", lord_ids=["x"],
                      forces={"militia": 6}, capabilities_in_play=[])
    assert not [r for r in build_strike_rows(s, side) if r.kind == "javelins"]


# --- (a) one_round_only fires Round 1 only --------------------------------
def test_javelin_rows_marked_one_round_only():
    s = _state()
    side = BattleSide(side="christian", role="attacker", lord_ids=["x"],
                      forces={"militia": 4}, capabilities_in_play=["C7"])
    jav = [r for r in build_strike_rows(s, side) if r.kind == "javelins"]
    assert jav and all(r.one_round_only for r in jav)


def test_one_round_only_missiles_fire_round1_not_round2():
    """A pure-Javelin missile attacker deals missile Hits in Round 1 but
    NOT in a later Round (the one_round_only rows are dropped)."""
    s = _state()
    atk = BattleSide(side="christian", role="attacker", lord_ids=["x"],
                     forces={"militia": 4}, capabilities_in_play=["C7"])
    dfd = BattleSide(side="muslim", role="defender", lord_ids=["y"],
                     forces={"men_at_arms": 8})
    r1 = _resolve_step(s, "1.b", "attacker", "missile", None, atk, dfd,
                       round_index=1)
    # rebuild fresh sides (the step mutates the target) for round 2 compare
    atk2 = BattleSide(side="christian", role="attacker", lord_ids=["x"],
                      forces={"militia": 4}, capabilities_in_play=["C7"])
    dfd2 = BattleSide(side="muslim", role="defender", lord_ids=["y"],
                      forces={"men_at_arms": 8})
    r2 = _resolve_step(s, "1.b", "attacker", "missile", None, atk2, dfd2,
                       round_index=2)
    assert r1.rounded_hits > 0, "Javelins should fire in Round 1"
    assert r2.rounded_hits == 0, "Javelins must NOT fire in Round 2"


# --- (d) rounded_hits vs units_routed -------------------------------------
def test_stepresolution_has_distinct_units_routed_field():
    sr = StepResolution(step="2.a", actor="attacker")
    assert sr.rounded_hits == 0 and sr.units_routed == 0
    sr.rounded_hits = 5
    sr.units_routed = 2
    assert sr.rounded_hits != sr.units_routed   # distinct meanings


# --- (c) Cantador +4 to ONE lord, not per-lord (per-pair path) ------------
def test_cantador_caps_at_four_across_multiple_christian_lords():
    s = _state()
    s.decks.this_levy_events["christian"] = ["C8"]
    # Two Christian Front Lords, each with 4 Knights (8 K+S total). Cantador
    # must add at most +4 Melee Hits this step, not +4 to each Lord (+8).
    a1 = LordPosition(lord_id="alfonso", position="front_center",
                      forces={"knights": 4})
    a2 = LordPosition(lord_id="garcia_ordonez", position="front_left",
                      forces={"knights": 4})
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso", "garcia_ordonez"],
                     forces={"knights": 8}, array=[a1, a2])
    d1 = LordPosition(lord_id="al_mustain", position="front_center",
                      forces={"men_at_arms": 40})
    d2 = LordPosition(lord_id="abu_bakr", position="front_left",
                      forces={"men_at_arms": 40})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mustain", "abu_bakr"],
                     forces={"men_at_arms": 80}, array=[d1, d2])
    # Knights are horse; melee horse step. Knights x2 = 2 Hits each -> 8
    # Knights = 16 raw; Cantador adds eligible (<=4) more. With the shared
    # cap, the Cantador contribution is +4, not +8.
    res = _resolve_step(s, "2.a", "attacker", "melee", "horse", atk, dfd,
                        round_index=1)
    # 8 Knights x2 = 16 base; +4 Cantador (shared cap) = 20 (NOT 24).
    assert res.rounded_hits == 20, (
        f"expected 16 base + 4 Cantador (shared cap) = 20, got "
        f"{res.rounded_hits}")
