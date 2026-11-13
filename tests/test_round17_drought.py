"""Drought uses the affected owner's choices during the Arts of War draw."""

from itertools import combinations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.capabilities import side_has_capability
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, GameState
from almoravid.views import redacted_view

DROUGHT = {"type": "drought_choice", "side": "christian"}
PAIR = ["garcia_ordonez", "pedro_ansurez"]


def _second_levy(seed, drawer):
    state = load_scenario("scenario_a_toledo_beset", seed=seed)
    state.calendar.current_box = 2
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.first_levy_done = True
    state.meta.active_player = drawer
    state.meta.aow_draw_done = {"christian": drawer == "muslim", "muslim": False}
    state.meta.levy_step_completed_christian = drawer == "muslim"
    return state


def _place(state, lid, locale, **assets):
    lord = state.lords[lid]
    lord.cylinder = Cylinder(kind="locale", locale_id=locale)
    lord.assets.update(assets)
    return lord


def _service(state, lid):
    return next(m for m in state.calendar.service_markers
                if m.lord_id == lid and m.vassal_id is None)


def _play(state, move):
    assert move in legal_moves(state)
    return apply_action(state, move)


def _draw_drought(state, side, expected):
    assert _play(state, {"type": "aow_draw", "side": side})["drawn"] == expected
    return _play(state, {"type": "aow_implement_event", "side": side,
                         "card_id": expected[0]})["event_result"]


def _reject(state, move, code):
    before = state.model_dump_json()
    with pytest.raises(IllegalAction) as error:
        apply_action(state, move)
    assert error.value.code == code
    assert state.model_dump_json() == before


def test_drought_owner_can_spare_alfonso_and_resume_the_draw_queue():
    state = _second_levy(112, "muslim")
    # Audit position after earlier travel, food expenditure and Service loss.
    _place(state, "alfonso", "palencia", prov=0, loot=0, coin=0)
    _place(state, "alvar_fanez", "burgos")
    _service(state, "alfonso").box = 3

    assert _play(state, {"type": "aow_draw", "side": "muslim"})["drawn"] == ["M5", "M2"]
    event = {"type": "aow_implement_event", "side": "muslim", "card_id": "M5"}
    _reject(state, {**event, "payload": {"lord_ids": PAIR}}, "bad_drought_choice")
    assert _play(state, event)["event_result"]["pending"] == "drought_choice"
    assert state.pending.waiting_on == state.meta.active_player == "christian"
    assert state.decks.pending_draw["muslim"] == ["M2"]
    assert "M5" not in state.decks.discard
    expected = list(combinations(["alfonso", *PAIR], 2))
    assert [tuple(move["lord_ids"]) for move in legal_moves(state)] == expected
    move = {**DROUGHT, "lord_ids": PAIR}
    for invalid, code in [
        ({**move, "side": "muslim"}, "not_responder"),
        ({**move, "lord_ids": [PAIR[0]]}, "bad_drought_choice"),
        ({**move, "lord_ids": [PAIR[0], PAIR[0]]}, "bad_drought_choice"),
        ({**move, "lord_ids": ["alvar_fanez", PAIR[0]]}, "bad_drought_choice"),
        ({**move, "lord_ids": ["al_mutamid", PAIR[0]]}, "bad_drought_choice"),
        ({**DROUGHT, "discard_camels": True}, "bad_drought_choice"),
        ({"type": "aow_implement_event", "side": "muslim", "card_id": "M2"}, "pending_decision"),
        ({"type": "pass_step", "side": "christian"}, "pending_decision"),
    ]:
        _reject(state, invalid, code)

    resumed = GameState.model_validate_json(state.model_dump_json())
    result = _play(state, move)
    assert _play(resumed, move) == result
    assert resumed.model_dump_json() == state.model_dump_json()
    assert {row["lord_id"] for row in result["fed_lords"]} == set(PAIR)
    assert all(row["consumed"] == 1 and not row["unfed_penalty"] for row in result["fed_lords"])
    assert state.pending is None and state.meta.active_player == "muslim"
    assert state.decks.discard.count("M5") == 1
    _reject(state, move, "no_pending")
    _play(state, {"type": "aow_implement_event", "side": "muslim", "card_id": "M2"})
    for side in ("muslim", "christian", "muslim"):
        _play(state, {"type": "pass_step", "side": side})
    assert state.meta.levy_step == "service_disband"
    assert _service(state, "alfonso").box == 3
    assert state.lords["alfonso"].cylinder.locale_id == "palencia"
    assert not any(m["type"] == "disband_lord" and m.get("lord_id") == "alfonso"
                   for m in legal_moves(state))


def _with_camels():
    state = _second_levy(45, "christian")
    state.meta.first_levy_done = False
    state.meta.active_player = "muslim"
    state.decks.pending_draw["muslim"] = ["M16"]
    _play(state, {"type": "aow_deploy_capability", "side": "muslim", "card_id": "M16"})
    state.meta.first_levy_done = True
    state.meta.active_player = "christian"
    return state


@pytest.mark.parametrize("cancel", [False, True])
def test_muslim_owner_chooses_whether_to_discard_camels(cancel):
    state = _with_camels()
    lord = _place(state, "al_mustain", "transduero", prov=1, loot=0)
    result = _draw_drought(state, "christian", ["C5", "C6"])
    assert result["waiting_on"] == "muslim"
    base = {"type": "drought_choice", "side": "muslim"}
    spend = {**base, "discard_camels": True}
    feed = {**base, "lord_ids": ["al_mustain"]}
    assert legal_moves(state) == [feed, spend]
    _reject(state, {**spend, "lord_ids": feed["lord_ids"]}, "bad_drought_choice")
    _reject(state, {**base, "discard_camels": 1}, "bad_drought_choice")
    resumed = GameState.model_validate_json(state.model_dump_json())
    choice = spend if cancel else feed
    result = _play(state, choice)
    assert _play(resumed, choice) == result
    assert state.model_dump_json() == resumed.model_dump_json()
    assert state.meta.active_player == "christian" and state.pending is None
    assert state.decks.pending_draw["christian"] == ["C6"]
    assert state.decks.discard.count("C5") == 1
    assert side_has_capability(state, "muslim", "M16") is not cancel
    assert ("M16" in state.decks.board_edge["muslim"]) is not cancel
    assert state.decks.discard.count("M16") == int(cancel)
    assert lord.assets["prov"] == int(cancel)
    assert [row["lord_id"] for row in result["fed_lords"]] == ([] if cancel else ["al_mustain"])


def test_no_eligible_lords_leaves_camels_in_play():
    state = _with_camels()
    assert _draw_drought(state, "christian", ["C5", "C6"])["no_op"]
    assert state.pending is None and state.meta.active_player == "christian"
    assert side_has_capability(state, "muslim", "M16")
    assert "M16" in state.decks.board_edge["muslim"]
    assert "M16" not in state.decks.discard and state.decks.discard.count("C5") == 1


def test_friendly_placed_seat_is_protected_even_for_a_visiting_lord():
    state = _second_levy(112, "muslim")
    _place(state, "alfonso", "leon")
    _place(state, "alvar_fanez", "burgos")
    _place(state, "garcia_ordonez", "palencia")
    state.locales["palencia"].seat_marker_lord_ids = ["alfonso"]
    result = _draw_drought(state, "muslim", ["M5", "M2"])
    assert [row["lord_id"] for row in result["fed_lords"]] == ["pedro_ansurez"]
    assert state.pending is None and state.meta.active_player == "muslim"


def test_drought_owner_chooses_greed_and_shared_food_after_reloading():
    state = _second_levy(112, "muslim")
    state.meta.hidden_mats = True
    _place(state, "alvar_fanez", "burgos")
    _place(state, "alfonso", "palencia", mule=2, prov=0, loot=0)
    _place(state, PAIR[0], "palencia", prov=1, loot=1)
    _place(state, PAIR[1], "palencia", prov=1, loot=1)
    # The selected ally spends both markers on his own Feed. The other
    # donor can choose which marker to Share with Alfonso.
    state.lords[PAIR[0]].forces["militia"] = 6
    _service(state, "alfonso").box = 3
    _draw_drought(state, "muslim", ["M5", "M2"])
    _play(state, {**DROUGHT, "lord_ids": ["alfonso", PAIR[0]]})
    assert state.pending.payload["step"] == "greed"
    assert redacted_view(state, "christian")["pending"]["payload"]["eligible"][0]["units"] == 3
    assert "eligible" not in redacted_view(state, "muslim")["pending"]["payload"]
    _reject(state, {**DROUGHT, "discard_lords": [PAIR[0]]}, "bad_drought_choice")
    _play(state, {**DROUGHT, "discard_lords": ["alfonso"]})
    assert state.pending.payload["step"] == "feed"
    assert state.pending.payload["feed_options"] == {PAIR[1]: [0, 1]}
    assert "eligible" not in state.pending.payload
    assert "feed_options" not in redacted_view(state, "muslim")["pending"]["payload"]
    assert state.lords["alfonso"].assets["mule"] == 2
    _reject(state, {**DROUGHT, "feed_loot": {PAIR[0]: True}}, "bad_feed_choice")
    _reject(state, {**DROUGHT, "feed_loot": {"al_mutamid": 1}}, "bad_feed_choice")
    resumed = GameState.model_validate_json(state.model_dump_json())
    choice = {**DROUGHT, "feed_loot": {PAIR[1]: 1}}
    result = apply_action(state, choice)
    assert apply_action(resumed, choice) == result
    assert resumed.model_dump_json() == state.model_dump_json()
    by_lord = {row["lord_id"]: row for row in result["fed_lords"]}
    assert by_lord["alfonso"]["mules_discarded"] == 2
    assert by_lord["alfonso"]["shared"] == [
        {"to": "alfonso", "from": PAIR[1], "asset": "loot", "amount": 1}]
    assert by_lord[PAIR[0]]["use_loot"] == by_lord[PAIR[0]]["use_prov"] == 1
    assert all(not row["unfed_penalty"] for row in by_lord.values())
    assert _service(state, "alfonso").box == 3
    assert state.lords[PAIR[1]].assets["loot"] == 0
    assert all(not state.lords[lid].moved_fought for lid in ["alfonso", *PAIR])
    assert "feed_loot" not in redacted_view(state, "muslim")["history"][-1]["args"]


def test_drought_feed_accepts_multiple_owner_elections():
    state = _second_levy(112, "muslim")
    _place(state, "alfonso", "leon")
    _place(state, "alvar_fanez", "burgos")
    for lid in PAIR:
        state.lords[lid].assets.update(prov=1, loot=1)
    assert _draw_drought(state, "muslim", ["M5", "M2"])["step"] == "feed"
    assert state.pending.payload["feed_options"] == dict.fromkeys(PAIR, [0, 1])
    choice = {**DROUGHT, "feed_loot": dict.fromkeys(PAIR, 1)}
    result = apply_action(state, choice)
    assert [row["use_loot"] for row in result["fed_lords"]] == [1, 1]
    assert all(state.lords[lid].assets["prov"] == 1 for lid in PAIR)
    assert state.pending is None and state.meta.active_player == "muslim"
