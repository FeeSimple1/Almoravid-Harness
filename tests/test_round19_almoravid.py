"""Round 19 Almoravid regressions through the public action and view APIs."""

from itertools import combinations

import pytest

from almoravid.actions import apply_action
from almoravid.capabilities import side_has_capability
from almoravid.events import held_event_ids
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, GameState
from almoravid.views import redacted_view
from tests._plan_helpers import legal_pad, step_levy
from tests.test_cross_game_avoid_retreat_surrender import reject_unchanged
from tests.test_cross_game_logistics import cap, place, position, service
from tests.test_sortie_436 import _sortie_setup


def _later_levy(seed, side, scenario="scenario_a_toledo_beset"):
    state = load_scenario(scenario, seed=seed)
    state.calendar.current_box = 2
    state.meta.turn_index = 1
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.first_levy_done = True
    state.meta.active_player = side
    state.meta.levy_step_completed_christian = side == "muslim"
    state.meta.aow_draw_done = {"christian": side == "muslim"}
    return state


def _listed(state, action_type, **params):
    return [move for move in legal_moves(state) if move["type"] == action_type
            and all(move.get(key) == value for key, value in params.items())]


def _reload(state):
    return GameState.model_validate_json(state.model_dump_json())


def _replay(state, move):
    restored = _reload(state)
    result = apply_action(state, move)
    assert apply_action(restored, move) == result
    assert restored.model_dump_json() == state.model_dump_json()
    return result


def _advance_to(state, step, side):
    for _ in range(50):
        if (state.meta.levy_step, state.meta.active_player) == (step, side):
            return
        step_levy(state)
    raise AssertionError(f"did not reach {side} {step}")


@pytest.mark.parametrize(("side", "seed", "card", "lord", "held"), [
    ("christian", 17, "C19", "alfonso", "C21"),
    ("muslim", 7, "M16", "al_mustain", "M6"),
])
def test_levy_event_stays_unavailable_through_muster_and_expires(side, seed, card, lord, held):
    state = _later_levy(seed, side)
    assert apply_action(state, _listed(state, "aow_draw")[0])["drawn"] == [card, held]
    event = _listed(state, "aow_implement_event", card_id=card)[0]
    _replay(state, event)
    assert state.decks.this_levy_events[side] == [card]
    assert card not in state.decks.discard
    assert card not in held_event_ids(state, side)

    # An older save that sent the same Event to discard recovers its card.
    legacy = state.model_copy(deep=True)
    legacy.decks.this_levy_events.pop(side)
    legacy.decks.discard.append(card)
    assert _reload(legacy).model_dump() == state.model_dump()
    state = _reload(state)
    _advance_to(state, "muster", side)
    move = {"type": "levy_take_capability", "side": side, "lord_id": lord, "card_id": card}
    assert move not in legal_moves(state)
    reject_unchanged(state, move, "card_not_available")
    reject_unchanged(state, {**move, "card_id": held}, "card_not_available")
    assert _listed(state, "levy_take_capability", lord_id=lord)
    # Legacy unplayed Holds share the bucket and survive the Levy boundary.
    old_hold = "C4" if side == "christian" else "M4"
    state.decks.this_levy_events[side].append(old_hold)
    _advance_to(state, "call_to_arms", "muslim")
    assert card in state.decks.this_levy_events[side]
    _replay(state, _listed(state, "pass_step")[0])
    assert state.meta.phase == "campaign" and state.decks.discard.count(card) == 1
    assert not state.meta.muster_banned_this_levy_lord_ids
    assert old_hold in held_event_ids(state, side) and held in held_event_ids(state, side)

    # Stage the next Muster to isolate availability after expiration.
    state.meta.phase, state.meta.levy_step, state.meta.active_player = "levy", "muster", side
    state.meta.turn_index += 1
    assert move in legal_moves(_reload(state))
    _replay(state, move)
    assert side_has_capability(state, side, card) and card not in state.decks.discard


@pytest.mark.parametrize(("card", "expected_bans"), [
    ("C22", {"al_mutawakkil", "abd_allah", "yusuf", "sir"}),
    ("C23", {"abu_bakr"}),
    ("C24", {"yusuf", "sir"}),
    ("M17", {"pedro_ansurez", "garcia_ordonez", "alvar_fanez", "rodrigo_campeador"}),
])
def test_related_this_levy_events_remain_in_play_even_without_service(card, expected_bans):
    side = "christian" if card.startswith("C") else "muslim"
    state = _later_levy(1, side, "scenario_f_reconquista")
    state.decks.pending_draw[side] = [card]
    choices = _listed(state, "aow_implement_event")
    if card == "C23":
        move = next(move for move in choices if move["payload"] ==
                    {"lord_id": "abu_bakr", "mode": "cylinder"})
    else:
        move = choices[0]
    _replay(state, move)
    assert set(state.meta.muster_banned_this_levy_lord_ids) == expected_bans
    assert state.decks.this_levy_events[side] == [card]
    assert card not in state.decks.discard


def test_fitna_can_select_calendar_taifas_and_blocks_call_upon_an_emir():
    state = _later_levy(20, "christian", "scenario_f_reconquista")
    assert apply_action(state, _listed(state, "aow_draw")[0])["drawn"] == ["C19", "C14"]
    eligible = sorted(lid for lid, lord in state.lords.items() if lord.is_taifa)
    offered = _listed(state, "aow_implement_event", card_id="C19")
    assert {tuple(move["payload"]["lord_ids"]) for move in offered} == set(combinations(eligible, 2))
    ids = ["abu_bakr", "al_mutamid"]
    move = next(move for move in offered if move["payload"]["lord_ids"] == ids)
    reject_unchanged(state, {**move, "payload": {"lord_ids": ["abu_bakr", "abu_bakr"]}},
                     "bad_target")
    reject_unchanged(state, {**move, "payload": {"lord_ids": ["yusuf", "al_mutamid"]}},
                     "bad_target")
    reject_unchanged(state, {key: value for key, value in move.items() if key != "payload"},
                     "choice_required")
    assert state.lords["abu_bakr"].cylinder.kind == "calendar"
    before = service(state, "al_mutamid")
    result = _replay(state, move)["event_result"]
    assert result["shifted"] == [{"lord_id": "al_mutamid", "new_service_box": before - 1}]
    assert set(result["muster_ban"]) == set(ids)
    assert state.lords["abu_bakr"].cylinder.kind == "calendar"

    # Stage Muster and then Call to Arms, keeping Fitna's live bans.
    state.meta.levy_step, state.meta.active_player = "muster", "muslim"
    place(state, "al_mustain", "zaragoza")
    reject_unchanged(state, {"type": "muster_lord", "side": "muslim", "lord_id": "abu_bakr",
                            "levying_lord_id": "al_mustain", "seat": "valencia"}, "muster_banned")
    reject_unchanged(state, {"type": "levy_transport", "side": "muslim",
                            "lord_id": "al_mutamid", "transport": "mule"}, "muster_banned")
    state.meta.levy_step = "call_to_arms"
    place(state, "yusuf", "valencia")
    state.taifas["valencia"].status = "independent"
    call = {"type": "cta_call_emir", "side": "muslim", "taifa_lord_id": "abu_bakr",
            "mode": "muster", "seat": "valencia"}
    assert call not in legal_moves(state)
    reject_unchanged(state, call, "muster_banned")


@pytest.mark.parametrize("remaining", [0, 1])
def test_fitna_chooses_as_many_taifas_as_available(remaining):
    state = _later_levy(17, "christian")
    state.decks.pending_draw["christian"] = ["C19"]
    for lord in state.lords.values():
        if lord.is_taifa and not (remaining and lord.id == "abu_bakr"):
            lord.cylinder = Cylinder(kind="removed")
    options = _listed(state, "aow_implement_event")
    ids = ["abu_bakr"] if remaining else []
    assert [move["payload"] for move in options] == [{"lord_ids": ids}]
    assert _replay(state, options[0])["event_result"]["muster_ban"] == ids


def test_c10_can_spare_a_remote_pay_source_or_spend_the_public_taifas_box():
    state = _later_levy(38, "christian")
    state.taifas_box_coin = 2
    assert apply_action(state, _listed(state, "aow_draw")[0])["drawn"] == ["C10", "C18"]
    event = _listed(state, "aow_implement_event")[0]
    choice = {"type": "devaluation_choice", "side": "muslim"}
    reject_unchanged(state, {**event, "payload": {"coin_by_source": {"abu_bakr": 3}}},
                     "bad_devaluation_choice")
    _replay(state, event)
    assert state.pending.waiting_on == state.meta.active_player == "muslim"
    assert [move["coin"] for move in _listed(state, choice["type"], source="taifa_box")] == [0, 1, 2]
    reject_unchanged(state, {**choice, "coin_by_source": {"taifa_box": 3}},
                     "bad_devaluation_choice")
    reject_unchanged(state, {"type": "pass_step", "side": "muslim"}, "pending_decision")
    outcome = []
    for amount_from_box, amount_from_abu in ((0, 2), (2, 0)):
        branch = _reload(state)
        apply_action(branch, {**choice, "source": "taifa_box", "coin": amount_from_box})
        wrong_box = 2 - amount_from_box
        reject_unchanged(branch, {**choice, "coin_by_source": {
            "taifa_box": wrong_box, "al_mutamid": 3 - wrong_box,
        }},
                         "bad_devaluation_choice")
        result = _replay(branch, {**choice, "coin_by_source": {
            "taifa_box": amount_from_box, "abu_bakr": amount_from_abu, "al_mutamid": 1,
        }})
        assert result["coin_after"] == 6 and result["removed"] == 3
        assert branch.decks.discard.count("C10") == 1
        assert branch.taifas_box_coin == 2 - amount_from_box
        assert branch.meta.active_player == "christian"
        apply_action(branch, _listed(branch, "aow_implement_event", card_id="C18")[0])
        branch.meta.levy_step, branch.meta.active_player = "pay", "muslim"
        outcome.append(branch)
    pay = {"type": "pay_lord", "side": "muslim", "payer_lord_id": "abu_bakr",
           "target_lord_id": "abu_bakr", "resource": "coin", "amount": 1}
    reject_unchanged(outcome[0], pay, "no_coin")
    assert pay in legal_moves(outcome[1])
    _replay(outcome[1], pay)


def test_m14_checks_each_locale_and_screens_private_allocations():
    state = _later_levy(11, "muslim")
    state.meta.hidden_mats = True
    state.lords["sancho"].assets["coin"] = 3  # A separate, forced loss at Jaca.
    assert apply_action(state, _listed(state, "aow_draw")[0])["drawn"] == ["M14", "M11"]
    _replay(state, _listed(state, "aow_implement_event")[0])
    choice = {"type": "devaluation_choice", "side": "christian"}
    assert redacted_view(state, "muslim")["pending"]["payload"] == {"card_id": "M14"}
    assert redacted_view(state, "christian")["pending"]["payload"]["groups"]["jaca"] == {"sancho": 3}
    reject_unchanged(state, {**choice, "coin_by_source": {"alfonso": 3}},
                     "bad_devaluation_choice")
    reject_unchanged(state, {**choice, "coin_by_source": {"alfonso": 2, "sancho": True}},
                     "bad_devaluation_choice")
    other = _reload(state)
    _replay(state, {**choice, "coin_by_source": {"garcia_ordonez": 1, "pedro_ansurez": 1, "sancho": 1}})
    while other.pending:
        apply_action(other, _listed(other, "devaluation_choice")[-1])
    assert other.lords["alfonso"].assets["coin"] == 1
    assert state.lords["alfonso"].assets["coin"] == 3
    assert state.lords["sancho"].assets["coin"] == other.lords["sancho"].assets["coin"] == 2
    assert redacted_view(state, "muslim") == redacted_view(other, "muslim")
    assert redacted_view(state, "christian") != redacted_view(other, "christian")


def _arid_position():
    state = _later_levy(35, "muslim")
    assert apply_action(state, _listed(state, "aow_draw")[0])["drawn"] == ["M4", "M18"]
    for card in ("M4", "M18"):
        apply_action(state, _listed(state, "aow_implement_event", card_id=card)[0])
    # As in the audit, stage past Levy to keep the native marching mat.
    state.meta.phase, state.meta.levy_step = "campaign", None
    apply_action(state, {"type": "begin_campaign"})
    apply_action(state, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": "alfonso"})
    for side in ("christian", "muslim"):
        legal_pad(state, side)
        apply_action(state, {"type": "finalize_plan", "side": side})
    apply_action(state, {"type": "command_reveal", "side": "christian"})
    return state


def test_arid_reaction_keeps_hold_private_and_resumes_the_original_command():
    state = _arid_position()
    move = _listed(state, "cmd_march", target_locale_id="leon", way_type="road")[0]
    played = _reload(state)
    # Clear the earlier draw sequence in both controls to isolate the March.
    state.history.clear()
    empty = _reload(state)
    empty.decks.held["muslim"].remove("M4")
    alfonso = state.lords["alfonso"]
    remaining, food = state.meta.actions_remaining, alfonso.assets["prov"]
    assert _replay(state, move) == _replay(empty, move)
    assert state.meta.actions_remaining == remaining - 1 and alfonso.assets["prov"] == food
    assert state.pending.waiting_on == "muslim"
    assert redacted_view(state, "christian") == redacted_view(empty, "christian")
    reject_unchanged(empty, {"type": "arid_terrain_choice", "side": "muslim", "play": True},
                     "card_not_held")
    decline = _listed(state, "arid_terrain_choice", play=False)[0]
    _replay(played, move)
    _replay(state, decline)
    _replay(empty, decline)
    assert redacted_view(state, "christian") == redacted_view(empty, "christian")
    assert "M4" in held_event_ids(state, "muslim") and alfonso.assets["prov"] == food
    assert state.meta.active_player == "christian"
    result = _replay(played, _listed(played, "arid_terrain_choice", play=True)[0])
    assert played.decks.discard.count("M4") == 1 and result["forced_feed"][0]["lord_id"] == "alfonso"
    assert played.lords["alfonso"].assets["prov"] == food - 1
    assert played.meta.actions_remaining == state.meta.actions_remaining


def test_arid_camels_owners_elect_after_march_and_resume_approach():
    state = position("al_mutamid", "sevilla")
    place(state, "al_mutamid", "sevilla", prov=1, mule=1)
    state.lords["al_mutamid"].forces = {"militia": 5}
    place(state, "alfonso", "jerez")
    state.decks.held["christian"] = ["C4"]
    cap(state, "M16")
    apply_action(state, _listed(state, "cmd_march", target_locale_id="jerez")[0])
    reject_unchanged(state, {"type": "cmd_forage", "side": "muslim"}, "pending_decision")
    _replay(state, _listed(state, "arid_terrain_choice", play=True)[0])
    assert state.pending.waiting_on == "muslim" and state.pending.payload["step"] == "camels"
    cancelled = _reload(state)
    _replay(state, _listed(state, "arid_terrain_choice", discard_camels=False)[0])
    assert _replay(cancelled, _listed(cancelled, "arid_terrain_choice", discard_camels=True)[0])[
        "camels_negated"]
    for branch in (state, cancelled):
        assert branch.pending.kind == "march_arrival_response"
        assert branch.pending.waiting_on == "christian"
        assert branch.lords["al_mutamid"].cylinder.locale_id == "jerez"
        assert branch.meta.actions_remaining == 1
        assert branch.decks.discard.count("C4") == 1
    assert side_has_capability(state, "muslim", "M16") and state.lords["al_mutamid"].assets["prov"] == 0
    assert not side_has_capability(cancelled, "muslim", "M16")
    assert cancelled.decks.discard.count("M16") == cancelled.lords["al_mutamid"].assets["prov"] == 1


def test_arid_group_can_feed_the_non_leaders_and_choose_greed_and_food():
    state = position()
    state.meta.hidden_mats = True
    state.decks.held["muslim"] = ["M4"]
    place(state, "alfonso", "sahagun", cart=1, prov=1)
    place(state, "pedro_ansurez", "sahagun", mule=1, prov=1)
    place(state, "garcia_ordonez", "sahagun", cart=1, prov=1, loot=1)
    state.lords["pedro_ansurez"].forces = {"militia": 6}
    move = {"type": "cmd_march", "side": "christian", "target_locale_id": "leon",
            "way_type": "road", "group_lord_ids": ["pedro_ansurez", "garcia_ordonez"]}
    _replay(state, move)
    choices = _listed(state, "arid_terrain_choice", play=True)
    assert len(choices) == 3
    _replay(state, next(move for move in choices if "alfonso" not in move["lord_ids"]))
    assert state.pending.payload["step"] == "greed"
    assert "eligible" not in redacted_view(state, "muslim")["pending"]["payload"]
    _replay(state, _listed(state, "arid_terrain_choice", discard_lords=["pedro_ansurez"])[0])
    assert state.pending.payload["step"] == "feed"
    assert "feed_options" not in redacted_view(state, "muslim")["pending"]["payload"]
    result = _replay(state, _listed(state, "arid_terrain_choice", feed_loot={"garcia_ordonez": 1})[0])
    fed = {row["lord_id"]: row for row in result["forced_feed"]}
    assert set(fed) == {"pedro_ansurez", "garcia_ordonez"}
    assert fed["pedro_ansurez"]["mules_discarded"] == fed["garcia_ordonez"]["use_loot"] == 1
    assert state.lords["alfonso"].assets["prov"] == 1
    assert state.meta.active_player == "christian" and state.pending is None


def test_arid_after_sortie_restores_the_in_place_approach():
    state, here = _sortie_setup()
    state.decks.held["muslim"] = ["M4"]
    apply_action(state, _listed(state, "cmd_sortie")[0])
    _replay(state, _listed(state, "arid_terrain_choice", play=False)[0])
    assert state.pending.kind == "march_arrival_response"
    assert state.pending.payload["sortie"] and state.pending.payload["locale_id"] == here
    assert state.meta.actions_remaining == 2


@pytest.mark.parametrize("hidden", [True, False])
def test_capability_muster_views_preserve_only_public_details(hidden):
    state = load_scenario("scenario_a_toledo_beset", seed=1)
    state.meta.hidden_mats = hidden
    apply_action(state, {"type": "begin_levy"})
    _advance_to(state, "muster", "christian")
    apply_action(state, _listed(state, "levy_take_capability", lord_id="alfonso", card_id="C23")[0])
    transport = {"type": "cap_fonsadera", "side": "christian", "lord_id": "alfonso",
                 "vassal_index": 0, "mode": "transport"}
    branches = []
    for asset in ("cart", "mule"):
        branch = _reload(state)
        _replay(branch, {**transport, "transport_type": asset})
        branches.append(branch)
    views = [redacted_view(branch, "muslim") for branch in branches]
    assert (views[0] == views[1]) is hidden
    assert all("C23" in view["decks"]["board_edge"]["christian"] for view in views)
    assert redacted_view(branches[0], "christian") != redacted_view(branches[1], "christian")

    _advance_to(state, "muster", "muslim")
    branches = []
    for card, action in (("M15", "cap_saqalibah"), ("M20", "cap_al_rum")):
        branch = _reload(state)
        apply_action(branch, _listed(branch, "levy_take_capability", lord_id="al_mustain", card_id=card)[0])
        _replay(branch, _listed(branch, action, lord_id="al_mustain")[0])
        branches.append(_reload(branch))
    assert (redacted_view(branches[0], "christian") == redacted_view(branches[1], "christian")) is hidden
    assert redacted_view(branches[0], "muslim") != redacted_view(branches[1], "muslim")
