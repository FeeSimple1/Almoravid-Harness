"""Audit 04/05: a Hold is drawn now, used later, and consumed once."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import BattleResult, BattleSide, apply_aftermath, resolve_battle
from almoravid.events import has_held_event
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.static_data import load_cards
from almoravid.state import Cylinder


HOLD_CARDS = [cid for cid, rec in load_cards()["cards"].items()
              if rec.get("event_persistence") == "hold"]


@pytest.mark.parametrize("card_id", HOLD_CARDS)
def test_every_hold_draw_preserves_board_until_played(card_id: str) -> None:
    state = load_scenario("scenario_a_toledo_beset", seed=9)
    side = load_cards()["cards"][card_id]["side"]
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.first_levy_done = True
    state.meta.active_player = side
    state.decks.held = {}
    state.decks.pending_draw = {side: [card_id]}
    board_before = state.model_dump(exclude={"decks", "history"})
    result = apply_action(state, {"type": "aow_implement_event", "side": side})
    assert result["event_result"]["held"] == "held"
    assert state.decks.held[side] == [card_id]
    assert state.decks.pending_draw[side] == []
    assert card_id not in state.decks.discard
    assert state.model_dump(exclude={"decks", "history"}) == board_before


def test_printed_hold_classification() -> None:
    cards = load_cards()["cards"]
    for card in ("C25", "M8", "M10", "M12", "M15", "M21"):
        assert cards[card]["event_persistence"] == "hold"
    assert cards["M5"]["event_persistence"] == "immediate"


def test_count_event_menu_offers_paid_levy_and_decline() -> None:
    state = load_scenario("scenario_a_toledo_beset", seed=9)
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.first_levy_done = True
    state.meta.active_player = "christian"
    state.decks.pending_draw = {"christian": ["C13"]}
    sancho = state.lords["sancho"]
    sancho.cylinder = Cylinder(kind="locale", locale_id="jaca")
    sancho.assets = {"prov": 1}
    moves = [m for m in legal_moves(state) if m["type"] == "aow_implement_event"]
    assert any(not m.get("payload") for m in moves)
    assert any(m.get("payload", {}).get("asset") == "prov" for m in moves)
    for move in moves:
        copy = state.model_copy(deep=True)
        result = apply_action(copy, move)
        if move.get("payload"):
            assert result["event_result"]["capability_levied"]
            assert copy.lords["sancho"].assets.get("prov", 0) == 0
            assert "C13" in copy.lords["sancho"].capabilities


def test_scenario_marriage_is_offered_and_consumed_once() -> None:
    state = load_scenario("scenario_a_toledo_beset", seed=9)
    state.meta.phase = "levy"
    state.meta.levy_step = "muster"
    state.meta.active_player = "muslim"
    move = next(m for m in legal_moves(state)
                if m["type"] == "play_event" and m["card_id"] == "M12"
                and m["payload"].get("lord_ids") == ["al_mutamid"])
    marker = next(s for s in state.calendar.service_markers
                  if s.lord_id == "al_mutamid" and s.vassal_id is None)
    before = marker.box
    apply_action(state, move)
    assert marker.box == before + 1
    assert not has_held_event(state, "muslim", "M12")
    assert state.decks.discard.count("M12") == 1
    with pytest.raises(IllegalAction, match="not held"):
        apply_action(state, move)


@pytest.mark.parametrize("card_id,side,lord_id", [
    ("C18", "christian", "alfonso"), ("M18", "muslim", "al_mutamid"),
])
def test_restoration_holds_wait_for_muster_and_allow_transport_choice(
    card_id: str, side: str, lord_id: str,
) -> None:
    state = load_scenario("scenario_a_toledo_beset", seed=9)
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.active_player = side
    state.decks.held = {side: [card_id]}
    lord = state.lords[lord_id]
    lord.forces["men_at_arms" if side == "christian" else "militia"] = 0
    before = state.model_dump()
    move = {"type": "play_event", "side": side, "card_id": card_id,
            "payload": {"transport": "cart"}}
    with pytest.raises(IllegalAction) as exc:
        apply_action(state, move)
    assert exc.value.code == "bad_levy_step"
    assert state.model_dump() == before
    assert not any(m["type"] == "play_event" and m.get("card_id") == card_id
                   for m in legal_moves(state))
    state.meta.levy_step = "muster"
    carts_before = lord.assets.get("cart", 0)
    apply_action(state, move)
    assert lord.assets["cart"] == carts_before + 1
    assert not has_held_event(state, side, card_id)
    assert state.decks.discard.count(card_id) == 1


def test_battle_preserves_unrelated_held_events_including_legacy_bucket() -> None:
    state = load_scenario("scenario_a_toledo_beset", seed=9)
    state.decks.held = {"christian": ["C18"], "muslim": ["M12"]}
    state.decks.this_levy_events = {"christian": ["C14", "C7"]}
    result = BattleResult(
        engagement="battle",
        attacker=BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                            forces={"knights": 1}),
        defender=BattleSide(side="muslim", role="defender", lord_ids=["al_mutamid"],
                            forces={"militia": 1}),
    )
    apply_aftermath(state, result)
    assert has_held_event(state, "christian", "C18")
    assert has_held_event(state, "christian", "C14")
    assert has_held_event(state, "muslim", "M12")
    assert not has_held_event(state, "christian", "C7")
    assert state.decks.discard.count("C7") == 1


def test_canonical_combat_hold_activates_only_for_eligible_side() -> None:
    state = load_scenario("scenario_a_toledo_beset", seed=9)
    state.decks.held = {"christian": ["C1", "C8"], "muslim": ["M1", "M12"]}
    result = resolve_battle(
        state,
        BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                   forces={"knights": 3}),
        BattleSide(side="muslim", role="defender", lord_ids=["al_mutamid"],
                   forces={"militia": 1}),
    )
    apply_aftermath(state, result)
    assert has_held_event(state, "christian", "C1")  # Hills only Defending
    assert has_held_event(state, "muslim", "M12")
    assert not has_held_event(state, "christian", "C8")
    assert not has_held_event(state, "muslim", "M1")
