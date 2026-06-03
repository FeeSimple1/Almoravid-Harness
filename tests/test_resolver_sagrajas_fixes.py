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


# --- C8 combined cap across Horse + Foot steps, confined to holder --------
def test_cantador_combined_cap_across_horse_and_foot_steps():
    """C8 is 'up to four of that Lord's Knights AND Sergeants'. Resolving
    Horse Melee (Knights) and Foot Melee (Sergeants) as two steps must
    share ONE budget of 4 -- not 4 per step (which would double to 8)."""
    s = _state()
    s.decks.this_levy_events["christian"] = ["C8"]
    a1 = LordPosition(lord_id="alfonso", position="front_center",
                      forces={"knights": 4, "sergeants": 4})
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 4,
                     "sergeants": 4}, array=[a1])
    d1 = LordPosition(lord_id="al_mustain", position="front_center",
                      forces={"men_at_arms": 200})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mustain"], forces={"men_at_arms": 200},
                     array=[d1])
    # Build the shared per-Round context the round loop would build.
    from almoravid.battle import _build_c8_ctx
    ctx = _build_c8_ctx(s, atk, dfd, 1)
    assert ctx is not None and ctx["budget"] == 4
    horse = _resolve_step(s, "2.b", "attacker", "melee", "horse", atk, dfd,
                          round_index=1, c8_ctx=ctx)
    foot = _resolve_step(s, "2.d", "attacker", "melee", "foot", atk, dfd,
                         round_index=1, c8_ctx=ctx)
    # Knights x2 = 2 Hits each -> 8 raw; Sergeants x1 = 1 Hit each -> 4 raw.
    # Total Cantador bonus across BOTH steps must be exactly +4 (combined),
    # spent on Knights first (Horse step): horse 8+4=12, foot 4+0=4.
    assert ctx["budget"] == 0
    assert horse.rounded_hits + foot.rounded_hits == 16, (
        f"combined base 12 + cap 4 = 16; got "
        f"{horse.rounded_hits}+{foot.rounded_hits}")


def test_cantador_confined_to_single_holder_lord():
    """C8 attaches to ONE Christian Lord's mat. A second Front Lord's
    Knights get no bonus even if the holder cannot spend the full 4."""
    from almoravid.battle import _build_c8_ctx
    s = _state()
    s.decks.this_levy_events["christian"] = ["C8"]
    # Each Front Lord has 3 Knights (holder = first, alfonso). Confinement
    # caps the bonus at the HOLDER's 3 eligible units; a side-wide budget
    # would spill the 4th point onto garcia. So total bonus is +3, NOT +4.
    a1 = LordPosition(lord_id="alfonso", position="front_center",
                      forces={"knights": 3})
    a2 = LordPosition(lord_id="garcia_ordonez", position="front_left",
                      forces={"knights": 3})
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso", "garcia_ordonez"],
                     forces={"knights": 6}, array=[a1, a2])
    d1 = LordPosition(lord_id="al_mustain", position="front_center",
                      forces={"men_at_arms": 99})
    d2 = LordPosition(lord_id="abu_bakr", position="front_left",
                      forces={"men_at_arms": 99})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mustain", "abu_bakr"],
                     forces={"men_at_arms": 198}, array=[d1, d2])
    ctx = _build_c8_ctx(s, atk, dfd, 1)
    res = _resolve_step(s, "2.b", "attacker", "melee", "horse", atk, dfd,
                        round_index=1, c8_ctx=ctx)
    # 6 Knights x2 = 12 base; holder alfonso's 3 Knights -> +3 (confined).
    # A side-wide budget would give +4 (=16); confinement gives +3 (=15).
    assert res.rounded_hits == 15
    assert ctx["budget"] == 1
