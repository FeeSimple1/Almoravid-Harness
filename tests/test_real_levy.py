"""Phase 5g Real Levy mechanics tests."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import ServiceMarker


def _drive_to_levy_step(s, step: str) -> None:
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            return
        if s.meta.levy_step == step:
            return
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})


# ---- 3.2 Pay -------------------------------------------------------

def test_pay_lord_consumes_coin_and_shifts_service() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Al-Mutamid has 3 Coin and a Service marker at box 6 in Scenario A
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="al_mutamid", box=6))
    _drive_to_levy_step(s, "pay")
    # Drive to Muslim's turn
    while s.meta.active_player != "muslim":
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    coin_before = s.lords["al_mutamid"].assets["coin"]
    apply_action(s, {"type": "pay_lord", "side": "muslim",
                     "lord_id": "al_mutamid"})
    assert s.lords["al_mutamid"].assets["coin"] == coin_before - 1
    sm = next(s for s in s.calendar.service_markers if s.lord_id == "al_mutamid")
    assert sm.box == 5


def test_pay_lord_rejects_no_coin() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.lords["alfonso"].assets["coin"] = 0
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=4))
    _drive_to_levy_step(s, "pay")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "pay_lord", "side": "christian",
                          "lord_id": "alfonso"})
    assert ei.value.code == "no_coin"


# ---- 3.3 Disband ---------------------------------------------------

def test_disband_lord_clears_state_and_places_on_calendar() -> None:
    """Pattern 8 (lifecycle leaks): all cleanup fields must clear on Disband."""
    s = load_scenario("scenario_a_toledo_beset")
    # Pre-flag Alfonso with non-default state
    s.lords["alfonso"].moved_fought = True
    s.lords["alfonso"].lordship_used = 2
    s.lords["alfonso"].first_march_used_this_card = True
    _drive_to_levy_step(s, "service_disband")
    apply_action(s, {"type": "disband_lord", "side": "christian",
                     "lord_id": "alfonso"})
    assert s.lords["alfonso"].cylinder.kind == "calendar"
    # All cleanup fields cleared
    assert s.lords["alfonso"].forces == {}
    assert s.lords["alfonso"].assets == {}
    assert s.lords["alfonso"].vassals == []
    assert s.lords["alfonso"].in_stronghold is False
    assert s.lords["alfonso"].moved_fought is False
    assert s.lords["alfonso"].lordship_used == 0
    assert s.lords["alfonso"].first_march_used_this_card is False


# ---- 3.4 Lordship spending ---------------------------------------

def test_levy_take_vassal_adds_forces_and_spends_lordship() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "muster")
    alf = s.lords["alfonso"]
    assert alf.lordship_used == 0
    knights_before = alf.forces.get("knights", 0)
    # Vassal index 0 is Froila Bermudez (1K + 1S + 1MA)
    r = apply_action(s, {"type": "levy_take_vassal", "side": "christian",
                         "lord_id": "alfonso", "vassal_index": 0})
    assert alf.lordship_used == 1
    assert alf.forces["knights"] == knights_before + 1
    assert alf.vassals[0].ready is False


def test_levy_take_vassal_rejects_when_lordship_exhausted() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "muster")
    s.lords["alfonso"].lordship_used = s.lords["alfonso"].lordship_rating
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "levy_take_vassal", "side": "christian",
                         "lord_id": "alfonso", "vassal_index": 0})
    assert ei.value.code == "lordship_exhausted"


def test_levy_take_capability_from_board_edge() -> None:
    """Move a this_lord-scope board-edge Capability onto a Lord's mat.

    Rather than depend on whichever cards a scenario happens to seed in
    the board-edge (Scenario D's Muslim edge is all side-wide), we
    inject a known this_lord-scope Capability (M8 Dawud ibn Aisha,
    "Lords: Yusuf or Sir") so the handler path is exercised
    deterministically and the test never has to skip.
    """
    s = load_scenario("scenario_d_arrival")
    cards = load_cards_local()["cards"]
    # M8 is a this_lord-scope Muslim Capability for Yusuf/Sir.
    target_card = "M8"
    assert not cards[target_card]["no_capability"]
    assert cards[target_card]["capability_scope"] == "this_lord"
    s.decks.board_edge.setdefault("muslim", [])
    if target_card not in s.decks.board_edge["muslim"]:
        s.decks.board_edge["muslim"].append(target_card)
    _drive_to_levy_step(s, "muster")
    while s.meta.active_player != "muslim":
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    # Yusuf is mustered at Algeciras in Scenario D; ensure he can spend
    # Lordship (reset the per-card counter for a clean assertion).
    assert s.lords["yusuf"].cylinder.kind == "locale"
    s.lords["yusuf"].lordship_used = 0
    r = apply_action(s, {"type": "levy_take_capability", "side": "muslim",
                         "lord_id": "yusuf", "card_id": target_card})
    assert r["scope"] == "this_lord"
    assert target_card in s.lords["yusuf"].capabilities
    assert target_card not in s.decks.board_edge["muslim"]


def load_cards_local():
    from almoravid.static_data import load_cards
    return load_cards()


# ---- legal_moves -------------------------------------------------

def test_legal_moves_offers_pay_when_coin_and_service() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=4))
    _drive_to_levy_step(s, "pay")
    moves = legal_moves(s)
    assert any(m["type"] == "pay_lord" and m["lord_id"] == "alfonso"
               for m in moves)


def test_legal_moves_offers_disband_during_disband_step() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "service_disband")
    moves = legal_moves(s)
    disband_moves = [m for m in moves if m["type"] == "disband_lord"]
    assert disband_moves


def test_legal_moves_offers_take_vassal_during_muster() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "muster")
    moves = legal_moves(s)
    assert any(m["type"] == "levy_take_vassal" for m in moves)
