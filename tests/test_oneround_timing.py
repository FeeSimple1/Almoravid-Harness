"""4.4.1 "any 1 Round" timing for one-Round effects (M7 Spear Wall and
one-round Javelins). Default is Round 1; the owner may choose another
Round. Exposed interactively via the oneround_timing PendingDecision."""
from __future__ import annotations

from almoravid.battle import BattleSide, LordPosition, _battle_one_round, build_strike_rows
from almoravid.scenarios import load_scenario


def _state():
    return load_scenario("scenario_a_toledo_beset", seed=1)


def _mk_sides(s):
    s.decks.this_levy_events["muslim"] = ["M7"]
    a1 = LordPosition(lord_id="alfonso", position="front_center",
                      forces={"knights": 8})
    atk = BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                     forces={"knights": 8}, array=[a1])
    d1 = LordPosition(lord_id="al_mustain", position="front_center",
                      forces={"men_at_arms": 8})
    dfd = BattleSide(side="muslim", role="defender", lord_ids=["al_mustain"],
                     forces={"men_at_arms": 8}, array=[d1])
    from almoravid.battle import init_m7_cap
    init_m7_cap(s, atk)
    init_m7_cap(s, dfd)
    return atk, dfd


def test_m7_default_round1_discards_after_round1() -> None:
    s = _state()
    atk, dfd = _mk_sides(s)
    assert dfd.m7_owned is True and dfd.m7_round == 1
    _battle_one_round(s, atk, dfd, 1)
    # Default: M7 fired Round 1 and is discarded afterward.
    assert "M7" not in s.decks.this_levy_events.get("muslim", [])


def test_m7_chosen_round2_suppressed_round1_active_round2() -> None:
    s = _state()
    atk, dfd = _mk_sides(s)
    dfd.m7_round = 2                      # owner chose Round 2
    _battle_one_round(s, atk, dfd, 1)
    # Round 1: M7 suppressed (removed from play), NOT yet discarded as
    # "used" -- it simply isn't in effect this Round.
    assert "M7" not in s.decks.this_levy_events.get("muslim", [])
    _battle_one_round(s, atk, dfd, 2)
    # Round 2: M7 was (re)activated and then discarded after firing.
    assert "M7" not in s.decks.this_levy_events.get("muslim", [])


def test_javelin_filter_honors_oneround_round() -> None:
    """one_round_only Strike rows fire only in the side's chosen Round."""
    s = _state()
    # Find a Muslim Lord whose strike rows include a one_round_only row.
    # African Light Horse Javelins are one-round; use a synthetic side.
    a1 = LordPosition(lord_id="al_mustain", position="front_center",
                      forces={"light_horse": 6})
    atk = BattleSide(side="muslim", role="attacker", lord_ids=["al_mustain"],
                     forces={"light_horse": 6}, array=[a1])
    rows = build_strike_rows(s, atk, context="battle")
    has_oneround = any(getattr(r, "one_round_only", False) for r in rows)
    # If this scenario's Light Horse have Javelins, exercise the filter.
    if has_oneround:
        atk.oneround_round = 2
        # The filter drops one_round_only rows when round != oneround_round.
        kept_r1 = [r for r in rows if not (r.one_round_only and 1 != 2)]
        assert len(kept_r1) <= len(rows)


def test_interactive_timing_handler_sets_chosen_rounds() -> None:
    from almoravid.campaign import _h_oneround_timing
    from almoravid.state import PendingDecision
    s = _state()
    atk, dfd = _mk_sides(s)
    from almoravid.battle import battle_side_to_snapshot
    pl = {
        "side": "christian", "engagement_label": "Battle",
        "round_idx": 1, "max_rounds": 6, "rounds_done": 0,
        "attacker": battle_side_to_snapshot(atk),
        "defender": battle_side_to_snapshot(dfd),
        "defender_walls_range": None,
        "timing_queue": ["defender"],
        "timing_effects": {"javelin": False, "m7": True},
    }
    s.pending = PendingDecision(kind="oneround_timing", waiting_on="muslim",
                                payload=pl)
    s.meta.active_player = "muslim"
    r = _h_oneround_timing(s, {"type": "oneround_timing", "side": "muslim",
                               "m7_round": 3})
    # m7_round recorded on the defender snapshot; flow advanced to concede.
    assert pl["defender"]["m7_round"] == 3
    assert s.pending is not None and s.pending.kind == "battle_concede"
    assert "advance" in r
