"""A2-03: voluntary Reset elections use each card's full discard rules."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, _rebuild_aow_deck, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import CardInPlay, Cylinder, GameState
from almoravid.views import redacted_view
from tests.test_cross_game_empty_lord import attach
from tests.test_cross_game_end_campaign_order import position


def _position(box=1):
    state = position(box=box)
    state.decks.held = {"christian": [], "muslim": []}
    state.decks.board_edge = {"christian": [], "muslim": []}
    state.decks.this_levy_events = {}
    state.decks.this_campaign_events = {}
    state.decks.discard = []
    state.meta.aow_cap_state = {}
    return state


def _edge(state, side, card):
    state.decks.board_edge[side].append(card)
    state.decks.capabilities_in_play.append(
        CardInPlay(card_id=card, scope="side_wide", owner_side=side))


def _begin(state, **args):
    return apply_action(state, {"type": "end_campaign", **args})


def _choose(state, cards=(), *, side=None, done=True):
    return apply_action(state, {"type": "reset_discard",
                                "side": side or state.meta.active_player,
                                "card_ids": list(cards), "done": done})


def _reject(state, action):
    before = state.model_dump_json()
    with pytest.raises(IllegalAction):
        apply_action(state, action)
    assert state.model_dump_json() == before


@pytest.mark.parametrize("with_cards", [False, True])
def test_normal_end_campaign_offers_both_sides_before_calendar_advance(with_cards):
    state = _position()
    if with_cards:
        state.decks.held = {"christian": ["C14"], "muslim": ["M13"]}
    result = _begin(state)
    assert result["pending"] == "reset_discard"
    assert state.pending.waiting_on == state.meta.active_player == "christian"
    assert state.calendar.current_box == 1 and state.meta.turn_index == 0
    _choose(state)
    assert state.pending.waiting_on == state.meta.active_player == "muslim"
    assert state.calendar.current_box == 1 and state.meta.turn_index == 0
    result = _choose(state)
    assert state.pending is None and state.meta.phase == "levy"
    assert state.calendar.current_box == 2 and state.meta.turn_index == 1
    assert result["advance"]["current_box"] == 2
    assert state.decks.held == ({"christian": ["C14"], "muslim": ["M13"]}
                                if with_cards else {"christian": [], "muslim": []})


@pytest.mark.parametrize("side,hold,personal,edge,lord_id", [
    ("christian", "C14", "C3", "C19", "alfonso"),
    ("muslim", "M13", "M14", "M22", "al_mutamid")])
def test_any_owned_hold_personal_or_side_capability_is_selectable(
        side, hold, personal, edge, lord_id):
    state = _position()
    state.decks.held[side] = [hold]
    attach(state, lord_id, personal, {})
    _edge(state, side, edge)
    assert state.lords[lord_id].assets == {}  # No Wastage obligation.
    _begin(state)
    if side == "muslim":
        _choose(state)
    choices = legal_moves(state)
    assert {m["card_ids"][0] for m in choices if m["card_ids"]} == {hold, personal, edge}
    result = _choose(state, [hold, personal, edge])
    assert result["discarded"] == [hold, personal, edge]
    assert state.decks.held[side] == [] and state.lords[lord_id].capabilities == []
    assert state.decks.board_edge[side] == []
    assert not any(c.owner_side == side for c in state.decks.capabilities_in_play)
    assert all(state.decks.discard.count(cid) == 1 for cid in (hold, personal, edge))
    if side == "christian":
        _choose(state)
    _rebuild_aow_deck(state, side)
    assert all(cid in state.decks.draw for cid in (hold, personal, edge))


def test_menu_supports_any_subset_without_enumerating_all_subsets():
    state = _position()
    state.decks.held["christian"] = ["C14", "C15", "C18"]
    _begin(state)
    for cid in ("C14", "C18"):
        move = next(m for m in legal_moves(state) if m["card_ids"] == [cid])
        assert move["done"] is False
        apply_action(state, move)
        assert state.meta.active_player == "christian"
    assert state.decks.held["christian"] == ["C15"]
    _choose(state)
    _choose(state)
    assert state.decks.held["christian"] == ["C15"]
    assert "C18" in state.decks.discard and "C18" not in state.decks.removed_from_game


@pytest.mark.parametrize("bucket", ["this_levy_events", "this_campaign_events"])
def test_legacy_unplayed_holds_can_be_discarded_without_playing(bucket):
    state = _position()
    getattr(state.decks, bucket)["muslim"] = ["M13"]
    before = sum(loc.jihad_markers for loc in state.locales.values())
    _begin(state)
    _choose(state)
    assert any(m["card_ids"] == ["M13"] for m in legal_moves(state))
    _choose(state, ["M13"])
    assert state.decks.discard.count("M13") == 1
    assert not state.decks.held["muslim"]
    assert "M13" not in getattr(state.decks, bucket).get("muslim", [])
    assert sum(loc.jihad_markers for loc in state.locales.values()) == before


def test_milites_capability_is_removed_permanently_but_its_units_stay():
    state = _position()
    _edge(state, "christian", "C18")
    before = dict(state.lords["alfonso"].forces)
    _begin(state)
    _choose(state, ["C18"])
    assert state.lords["alfonso"].forces == before
    assert "C18" in state.decks.removed_from_game
    assert "C18" not in state.decks.discard
    _choose(state)
    _rebuild_aow_deck(state, "christian")
    assert "C18" not in state.decks.draw


@pytest.mark.parametrize("card,unit", [("M15", "men_at_arms"), ("M20", "knights")])
@pytest.mark.parametrize("survives", [False, True])
def test_personal_contingent_cleanup_and_calendar_disband(card, unit, survives):
    state = _position()
    lord = state.lords["al_mutamid"]
    lord.forces = {unit: 2, **({"militia": 1} if survives else {})}
    attach(state, lord.id, card, {unit: 2})
    state.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id="tangier")
    state.lords["yusuf"].forces = {"men_at_arms": 1}
    _begin(state)
    _choose(state)
    _choose(state, [card])
    assert card + "_units" not in state.meta.aow_cap_state
    assert card + "_used" not in state.meta.aow_cap_state
    assert lord.cylinder.kind == ("locale" if survives else "calendar")
    if survives:
        assert sum(lord.forces.values()) == 1
    else:
        # Almoravid 3.3.2 counts from the next Levy during Campaign.
        assert lord.cylinder.box == 2 + lord.service_rating
    assert state.calendar.current_box == 2
    assert state.decks.discard.count(card) == 1


def test_disband_cascade_does_not_discard_selected_personal_card_twice():
    state = _position()
    lord = state.lords["al_mutamid"]
    lord.forces = {"men_at_arms": 2}
    lord.assets = {"coin": 2}  # Wastage takes Coin, leaving both cards for Reset.
    attach(state, lord.id, "M15", {"men_at_arms": 2})
    attach(state, lord.id, "M14", {})
    state.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id="tangier")
    state.lords["yusuf"].forces = {"men_at_arms": 1}
    _begin(state)
    _choose(state)
    _choose(state, ["M15", "M14"])
    assert lord.cylinder.kind == "calendar"
    assert state.decks.discard.count("M15") == state.decks.discard.count("M14") == 1
    assert sum(h.action == "disband_lord" for h in state.history) == 1


def test_final_mustered_lord_disband_ends_game_before_remaining_selections_or_advance():
    state = _position()
    lord = state.lords["al_mutamid"]
    lord.forces = {"men_at_arms": 2}
    attach(state, lord.id, "M15", {"men_at_arms": 2})
    state.decks.held["muslim"] = ["M13"]
    _begin(state)
    _choose(state)
    result = _choose(state, ["M15", "M13"])
    assert result["victory"]["winner"] == "christian"
    assert state.meta.phase == "ended" and state.pending is None
    assert state.calendar.current_box == 1
    assert state.decks.held["muslim"] == ["M13"]


@pytest.mark.parametrize("choice", ["remove", "add"])
def test_neutrality_pause_preserves_remaining_selections_and_actor_after_reload(choice):
    state = _position()
    lord = state.lords["al_mutamid"]
    lord.forces = {"men_at_arms": 2}
    lord.in_stronghold = True
    attach(state, lord.id, "M15", {"men_at_arms": 2})
    state.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id="tangier")
    state.lords["yusuf"].forces = {"men_at_arms": 1}
    state.lords["alfonso"].cylinder.locale_id = "sevilla"
    state.locales["sevilla"].siege_yellow = 1
    state.locales["sevilla"].jihad_markers = state.locales["sevilla"].conquered_markers = 0
    state.decks.held["muslim"] = ["M13"]
    _begin(state)
    _choose(state)
    result = _choose(state, ["M15", "M13"], done=False)
    assert result["pending"] == "neutrality_choice"
    assert state.meta.active_player == state.pending.waiting_on == "christian"
    assert state.decks.held["muslim"] == ["M13"]
    assert state.calendar.current_box == 1
    for side in ("christian", "muslim"):
        view = redacted_view(state, side)
        assert "_reset_discard_resume" not in view["pending"]["payload"]
    assert all("M13" not in h.summary and "M13" not in str(h.args)
               for h in state.history if h.action == "reset_discard")
    state = GameState.model_validate_json(state.model_dump_json())
    apply_action(state, {"type": "respond_neutrality_choice", "side": "christian",
                         "choices": {"sevilla": choice}})
    assert state.pending.kind == "reset_discard"
    assert state.meta.active_player == state.pending.waiting_on == "muslim"
    assert state.decks.held["muslim"] == [] and state.decks.discard.count("M13") == 1
    assert state.decks.discard.count("M15") == 1
    assert sum(h.action == "disband_lord" for h in state.history) == 1
    assert state.calendar.current_box == 1
    _choose(state)
    assert state.calendar.current_box == 2 and state.meta.phase == "levy"


def test_reset_save_load_retains_choices_and_kept_private_holds():
    state = _position()
    state.meta.hidden_mats = True
    state.decks.held = {"christian": ["C14"], "muslim": ["M13"]}
    _begin(state)
    state = GameState.model_validate_json(state.model_dump_json())
    assert redacted_view(state, "muslim")["decks"]["held"]["christian"] is None
    _choose(state, ["C14"])
    state = GameState.model_validate_json(state.model_dump_json())
    _choose(state)
    assert state.decks.held["muslim"] == ["M13"]
    assert state.decks.discard.count("C14") == 1
    assert state.meta.turn_index == 1


def test_public_reset_window_does_not_reveal_held_card_ownership():
    held, empty = _position(), _position()
    held.decks.held["christian"] = ["C14"]
    assert _begin(held) == _begin(empty)
    assert redacted_view(held, "muslim") == redacted_view(empty, "muslim")
    assert legal_moves(empty) == [{"type": "reset_discard", "side": "christian",
                                   "card_ids": []}]


def test_unstacking_precedes_the_first_reset_discard_election():
    state = _position()
    state.lords["alfonso"].is_lieutenant = True
    state.lords["al_mutamid"].lieutenant_of = "alfonso"
    _begin(state)
    assert state.pending.kind == "reset_discard"
    assert not state.lords["alfonso"].is_lieutenant
    assert state.lords["al_mutamid"].lieutenant_of is None


@pytest.mark.parametrize("bad", [
    {"card_ids": ["M13"]}, {"card_ids": ["C14", "C14"]},
    {"card_ids": ["C14", "unknown"]}, {"card_ids": "C14"},
    {"card_ids": [1]}, {"card_ids": None}, {"card_ids": [], "done": False},
    {"card_ids": ["C14"], "done": "yes"}, {"side": "muslim", "card_ids": ["M13"]},
])
def test_invalid_selections_reject_without_board_rng_or_history_mutation(bad):
    state = _position()
    state.decks.held = {"christian": ["C14"], "muslim": ["M13"]}
    _begin(state)
    _reject(state, {"type": "reset_discard", "side": "christian", **bad})


@pytest.mark.parametrize("action", [
    {"type": "end_campaign"}, {"type": "begin_levy"}, {"type": "begin_campaign"},
    {"type": "cmd_pass", "side": "christian"},
    {"type": "play_event", "side": "christian", "card_id": "C14"},
])
def test_pending_reset_cannot_be_bypassed(action):
    state = _position()
    _begin(state)
    _reject(state, action)


def test_reset_discard_is_illegal_outside_its_window():
    state = _position()
    state.decks.held["christian"] = ["C14"]
    _reject(state, {"type": "reset_discard", "side": "christian", "card_ids": ["C14"]})


def test_preceding_wastage_and_repairs_only_run_once_before_reset():
    state = _position(box=3)
    state.lords["alfonso"].assets = {"coin": 3}
    state.lords["al_mutamid"].assets = {"coin": 3}
    state.locales["leon"].siege_yellow = 4
    state.decks.held["christian"] = ["C14"]
    _begin(state, interactive_wastage=True)
    assert state.pending.kind == "wastage_choice"
    for side in ("christian", "muslim"):
        apply_action(state, {"type": "wastage_choice", "side": side})
    assert state.pending.kind == "reset_discard"
    assert state.locales["leon"].siege_yellow == 3
    _choose(state, ["C14"], done=False)
    state = GameState.model_validate_json(state.model_dump_json())
    _choose(state)
    _choose(state)
    assert all(state.lords[lid].assets["coin"] == 2 for lid in ("alfonso", "al_mutamid"))
    assert state.calendar.current_box == 4 and state.locales["leon"].siege_yellow == 3


def test_final_campaign_scores_before_unstacking_or_optional_discards():
    state = _position()
    state.calendar.boxes[1].decorations.append("scenario_end")
    state.decks.held["christian"] = ["C14"]
    state.lords["alfonso"].is_lieutenant = True
    result = _begin(state)
    assert result["phase"] == "ended" and state.pending is None
    assert state.decks.held["christian"] == ["C14"]
    assert state.lords["alfonso"].is_lieutenant is True
    assert state.calendar.current_box == 1
