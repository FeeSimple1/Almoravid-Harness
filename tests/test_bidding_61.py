"""6.1 Bidding for Sides (optional setup action)."""
from __future__ import annotations
import pytest
from almoravid.actions import apply_action, IllegalAction
from almoravid.scenarios import load_scenario


def test_lower_bid_takes_muslim_and_resets_taifas_vp() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    r = apply_action(s, {"type": "bid_for_sides", "bid1": 3, "bid2": 5})
    assert r["muslim_player"] == "player1"   # lower bid
    assert r["winning_bid"] == 3
    assert s.taifas_box_vp == 3.0
    assert r["tie"] is False


def test_tie_resets_and_assigns_randomly() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    r = apply_action(s, {"type": "bid_for_sides", "bid1": 4, "bid2": 4})
    assert r["tie"] is True
    assert s.taifas_box_vp == 4.0
    assert r["muslim_player"] in ("player1", "player2")


def test_scenario_f_min_bid_2_enforced() -> None:
    s = load_scenario("scenario_f_reconquista")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "bid_for_sides", "bid1": 1, "bid2": 3})
    assert ei.value.code == "bid_too_low"
    # 2 is allowed in Scenario F.
    r = apply_action(s, {"type": "bid_for_sides", "bid1": 2, "bid2": 6})
    assert r["winning_bid"] == 2 and s.taifas_box_vp == 2.0


def test_bidding_only_at_setup() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    apply_action(s, {"type": "begin_levy"})   # leaves setup
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "bid_for_sides", "bid1": 2, "bid2": 3})
    assert ei.value.code == "wrong_phase"


def test_bidding_is_callable_but_not_in_default_move_stream() -> None:
    """Bidding is a pre-game agreement: callable via apply_action at
    setup, but intentionally not enumerated (so auto-drivers don't bid)."""
    s = load_scenario("scenario_a_toledo_beset")
    from almoravid.legal_moves import legal_moves
    assert not any(m["type"] == "bid_for_sides" for m in legal_moves(s))
    r = apply_action(s, {"type": "bid_for_sides", "bid1": 2, "bid2": 5})
    assert r["winning_bid"] == 2 and s.taifas_box_vp == 2.0
