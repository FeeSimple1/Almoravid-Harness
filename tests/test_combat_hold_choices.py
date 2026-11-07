"""Owner-ordered combat Event choices before any combat dice or effects."""

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import GameState
from almoravid.views import redacted_view
from tests.test_cross_game_avoid_retreat_surrender import place, position
from tests.test_cross_game_reaction_privacy import hold


def _battle(attacker="christian"):
    state = position()
    place(state, "alfonso", "transduero", coin=5)
    place(state, "al_mutamid", "transduero", coin=5)
    state.meta.active_player = attacker
    state.meta.active_lord_id = "alfonso" if attacker == "christian" else "al_mutamid"
    state.meta.hidden_mats = True
    hold(state, "christian", "C8")
    hold(state, "muslim", "M6")
    return state


def _choose(state, card=None):
    action = {"type": "combat_holds", "side": state.pending.waiting_on}
    if card is not None:
        action["card_id"] = card
    return apply_action(state, action)


@pytest.mark.parametrize("attacker", ["christian", "muslim"])
def test_both_owners_can_keep_their_combat_holds(attacker):
    state = _battle(attacker)
    place(state, "sancho", "toledo")
    place(state, "yusuf", "toledo")
    rng = state.meta.rng_state
    held = {side: list(cards) for side, cards in state.decks.held.items()}
    apply_action(state, {"type": "cmd_battle", "side": attacker, "interactive_concede": True})
    assert state.pending.kind == "combat_holds" and state.pending.waiting_on == attacker
    assert state.meta.rng_state == rng and state.decks.held == held
    for side in (attacker, "muslim" if attacker == "christian" else "christian"):
        assert state.pending.waiting_on == side
        state = GameState.model_validate_json(state.model_dump_json())
        view = redacted_view(state, side)
        assert "_combat_hold_resume" not in view["pending"]["payload"]
        opponent = "muslim" if side == "christian" else "christian"
        assert view["decks"]["held"][opponent] is None
        assert all(not view["lords"][lid].get("hidden_mat") for lid in ("alfonso", "al_mutamid"))
        assert view["lords"]["sancho" if side == "muslim" else "yusuf"]["hidden_mat"]
        _choose(state)
    assert state.pending.kind == "battle_concede"
    assert state.meta.rng_state == rng and state.decks.held == held
    apply_action(state, {"type": "battle_concede", "side": attacker, "attacker_concede": True})
    assert state.decks.held == held


def test_selected_subset_is_public_and_invalid_plays_are_atomic():
    state = _battle()
    state.decks.held["christian"].extend(["C1", "C2"])
    apply_action(state, {"type": "cmd_battle", "side": "christian", "interactive_concede": True})
    for bad in (
        {"type": "combat_holds", "side": "muslim", "card_id": "M6"},
        {"type": "combat_holds", "side": "christian", "card_id": "C1"},
        {"type": "combat_holds", "side": "christian", "card_id": "M6"},
        {"type": "cmd_pass", "side": "christian"},
    ):
        before = state.model_dump_json()
        with pytest.raises(IllegalAction):
            apply_action(state, bad)
        assert state.model_dump_json() == before
    _choose(state, "C2")
    before = state.model_dump_json()
    with pytest.raises(IllegalAction):
        _choose(state, "C2")
    assert state.model_dump_json() == before
    state = GameState.model_validate_json(before)
    _choose(state)
    assert state.pending.waiting_on == "muslim"
    assert "C2" in redacted_view(state, "muslim")["decks"]["this_campaign_events"]["christian"]
    assert state.lords["al_mutamid"].assets["coin"] == 5
    _choose(state)
    assert state.pending.kind == "battle_concede"
    assert state.lords["al_mutamid"].assets["coin"] == 1
    assert state.decks.discard.count("C2") == 1
    assert state.decks.held["christian"] == ["C8", "C1"]
    assert state.decks.held["muslim"] == ["M6"]


def test_defender_can_retain_m2_after_attacker_plays_baggage_parapet():
    state = _battle()
    hold(state, "christian", "C7")
    hold(state, "muslim", "M2")
    apply_action(state, {"type": "cmd_battle", "side": "christian", "interactive_concede": True})
    _choose(state, "C7")
    _choose(state)
    assert state.pending.waiting_on == "muslim"
    assert "C7" in redacted_view(state, "muslim")["decks"]["this_levy_events"]["christian"]
    _choose(state)
    assert state.decks.held["muslim"] == ["M2"]
    assert state.lords["alfonso"].assets["coin"] == 5
    assert state.lords["al_mutamid"].assets["coin"] == 5


def test_hills_is_available_only_to_the_defender():
    state = _battle()
    hold(state, "christian", "C1")
    hold(state, "muslim", "M1")
    apply_action(state, {"type": "cmd_battle", "side": "christian", "interactive_concede": True})
    assert [move for move in legal_moves(state) if move["type"] == "combat_holds"] == [
        {"type": "combat_holds", "side": "christian"}]
    _choose(state)
    _choose(state, "M1")
    _choose(state)
    assert state.decks.held["christian"] == ["C1"]
    assert "M1" in state.decks.this_levy_events["muslim"]


@pytest.mark.parametrize("kind", ["cmd_sally", "cmd_storm"])
def test_siege_combat_offers_c8_without_spending_unrelated_holds(kind):
    state = position()
    place(state, "alfonso", "zamora")
    place(state, "al_mutamid", "zamora")
    state.lords["alfonso" if kind == "cmd_sally" else "al_mutamid"].in_stronghold = True
    if kind == "cmd_sally":
        state.locales["zamora"].siege_green = 2
    else:
        state.locales["zamora"].siege_yellow = 2
        state.locales["zamora"].conquered_markers = 1
    hold(state, "christian", "C8")
    hold(state, "muslim", "M2")
    apply_action(state, {"type": kind, "side": "christian", "interactive_concede": True})
    _choose(state, "C8")
    _choose(state)
    if kind == "cmd_storm":
        assert all(move.get("card_id") != "M2" for move in legal_moves(state))
    _choose(state)
    assert state.decks.held["muslim"] == ["M2"]
    assert not state.pending or state.pending.kind != "combat_holds"


@pytest.mark.parametrize("key", ["attacker_concede_round", "defender_concede_round"])
def test_invalid_combat_args_are_rejected_before_the_event_window(key):
    state = _battle()
    before = state.model_dump_json()
    with pytest.raises(IllegalAction, match="positive int"):
        apply_action(state, {"type": "cmd_battle", "side": "christian", key: "invalid"})
    assert state.model_dump_json() == before
