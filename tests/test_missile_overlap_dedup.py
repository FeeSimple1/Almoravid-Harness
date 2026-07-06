"""4.4.2 TOTAL HITS — missile-capability overlap does not stack (Q-005).

B&S reference `capability_stacking`: "If different sources give the
same unit 'Missiles x½' and 'Missiles x1', the unit is x1 (highest
applicable rate); the ½ does not stack to 1½." C7 Tips: units with
both Javelins and Bowmen/Crossbows are x1 on the Javelin Round and
x½ on other Rounds. C2 Tips: Militia using both Crossbows and
Javelins get the benefits of each (x1, target selection, -1 Armor).
"""
from __future__ import annotations

from almoravid.battle import (
    BattleSide,
    StrikeRow,
    _dedupe_missile_overlap,
    _step_hits,
    build_strike_rows,
)
from almoravid.scenarios import load_scenario


def _missile_raw(state, caps, forces, *, context, javelin_round_active):
    side = BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                      forces=forces, capabilities_in_play=caps)
    rows = build_strike_rows(state, side, context=context)
    if not javelin_round_active:
        rows = [r for r in rows if not r.one_round_only]
    rows = _dedupe_missile_overlap(rows)
    raw, by_kind = _step_hits(rows, "missile", None)
    return raw, by_kind


def test_crossbows_plus_javelins_battle_javelin_round_x1_not_x15() -> None:
    """2 Militia with C2+C7 on the Javelin Round: x1 each = 2.0 raw
    (previously 2 x (0.5 + 1.0) = 3.0), and the Hits keep Crossbow
    benefits (kind 'crossbows') per C2 Tips."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    raw, by_kind = _missile_raw(s, ["C2", "C7"], {"militia": 2},
                                context="battle", javelin_round_active=True)
    assert raw == 2.0
    assert by_kind == {"crossbows": 2.0}


def test_crossbows_plus_javelins_other_round_is_half() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    raw, by_kind = _missile_raw(s, ["C2", "C7"], {"militia": 2},
                                context="battle", javelin_round_active=False)
    assert raw == 1.0
    assert by_kind == {"crossbows": 1.0}


def test_storm_tie_prefers_crossbows_serfs_still_throw() -> None:
    """Storm: Javelins are x1/2, tying Crossbows — the Militia fires
    once at x1/2 with Crossbow benefits; the Serf (Javelins only)
    contributes its own 1/2. Total 1.0, not 1.5 (Játiva: 'adding
    Javelins to the Militia and the single Serfs unit adds no Hits')."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    raw, by_kind = _missile_raw(s, ["C2", "C7"], {"militia": 1, "serfs": 1},
                                context="storm", javelin_round_active=True)
    assert raw == 1.0
    assert by_kind["crossbows"] == 0.5
    assert by_kind["javelins"] == 0.5


def test_javelin_budget_overflow_falls_back_to_crossbows() -> None:
    """5 Militia with C2+C7 on the Javelin Round: 4 fire Javelins x1
    (with Crossbow benefits), the 5th falls back to Crossbows x1/2 —
    raw 4.5."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    raw, by_kind = _missile_raw(s, ["C2", "C7"], {"militia": 5},
                                context="battle", javelin_round_active=True)
    assert raw == 4.5
    assert by_kind == {"crossbows": 4.5}


def test_bowmen_plus_javelins_no_crossbow_perk() -> None:
    """M4-style Bowmen + Javelins without any Crossbow source: x1 on
    the Javelin Round, kind stays 'javelins' (no -1 Armor)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    raw, by_kind = _missile_raw(s, ["C4", "C7"], {"militia": 2},
                                context="battle", javelin_round_active=True)
    assert raw == 2.0
    assert by_kind == {"javelins": 2.0}


def test_no_merge_across_lord_groups() -> None:
    """Different Lords' Militia never merge: group 0 Bowmen + group 1
    Javelins both fire."""
    rows = [
        StrikeRow(unit_type="militia", count=2, kind="bowmen",
                  rate="x1/2", group=0),
        StrikeRow(unit_type="militia", count=2, kind="javelins",
                  rate="x1", one_round_only=True, group=1),
    ]
    out = _dedupe_missile_overlap(rows)
    assert len(out) == 2
    raw, _ = _step_hits(out, "missile", None)
    assert raw == 3.0
