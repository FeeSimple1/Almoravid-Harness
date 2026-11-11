"""Round 11: use public actions to exercise the life of a Lieutenant pair."""

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, GameState
from tests._plan_helpers import legal_pad

UPPER = "alvar_fanez"
LOWER = "pedro_ansurez"


def _act(state, kind, side="christian", **args):
    return apply_action(state, {"type": kind, "side": side, **args})


def _put(state, lord_id, locale, *, inside=False):
    lord = state.lords[lord_id]
    lord.cylinder = Cylinder(kind="locale", locale_id=locale)
    lord.in_stronghold = inside
    return lord


def _plan(seed=1):
    state = load_scenario("scenario_a_toledo_beset", seed=seed)
    state.meta.phase = "campaign"
    state.meta.campaign_step = "plan"
    return state


def _stack(state, upper=UPPER, lower=LOWER, side="christian"):
    move = {"type": "designate_lieutenant", "side": side,
            "lord_id": lower, "commander_id": upper}
    assert move in legal_moves(state)
    assert apply_action(state, move) == {"lieutenant": upper, "lower_lord": lower}


def _finish_plan(state, christian=(), muslim=()):
    for side, cards in (("christian", christian), ("muslim", muslim)):
        for lord_id in cards:
            _act(state, "plan_add_card", side, plan_kind="command", lord_id=lord_id)
        legal_pad(state, side)
        _act(state, "finalize_plan", side)


@pytest.mark.parametrize("departing", [UPPER, LOWER])
def test_survivor_activates_after_either_partner_disbands_at_feed(departing):
    state = _plan()
    for lid in (UPPER, LOWER):
        _put(state, lid, "leon").assets.pop("prov")
    _stack(state)
    marker = next(m for m in state.calendar.service_markers if m.lord_id == departing)
    marker.box = state.calendar.current_box + 1
    survivor = LOWER if departing == UPPER else UPPER
    _finish_plan(state, christian=(UPPER, survivor))

    assert not _act(state, "command_reveal")["auto_pass"]
    _act(state, "cmd_march", target_locale_id="astorga", way_type="road")
    assert all(state.lords[lid].cylinder.locale_id == "astorga" for lid in (UPPER, LOWER))
    _act(state, "end_card")

    assert state.lords[departing].cylinder.kind == "calendar"
    assert state.lords[survivor].cylinder.locale_id == "astorga"
    assert state.lords[survivor].lieutenant_of is None
    assert not state.lords[survivor].is_lieutenant
    _act(state, "command_reveal", "muslim")
    assert not _act(state, "command_reveal")["auto_pass"]
    assert state.meta.active_lord_id == survivor


def _approach(*, independent=False):
    state = _plan()
    for lid in (UPPER, LOWER):
        _put(state, lid, "leon")
    if independent:
        _put(state, "garcia_ordonez", "leon")
    _put(state, "al_mustain", "astorga")
    state.locales["astorga"].bypass_green = True
    _stack(state)
    _finish_plan(state, muslim=("al_mustain",))
    assert _act(state, "command_reveal")["auto_pass"]
    _act(state, "command_reveal", "muslim")
    _act(state, "cmd_march", "muslim", target_locale_id="leon", way_type="road")
    assert state.pending.kind == "march_arrival_response"
    return state


@pytest.mark.parametrize("response", ["respond_withdraw", "respond_avoid_battle"])
def test_approach_accepts_the_pair_and_rejects_either_lord_alone(response):
    state = _approach()
    action = next(m for m in legal_moves(state) if m["type"] == response)
    before = state.model_dump()
    for lid in (UPPER, LOWER):
        with pytest.raises(IllegalAction) as rejected:
            apply_action(state, {**action, "lord_ids": [lid]})
        assert rejected.value.code == "lt_pair_split"
        assert state.model_dump() == before

    apply_action(state, {**action, "lord_ids": [UPPER, LOWER]})
    if response == "respond_avoid_battle":
        _act(state, "respond_swollen_river_block", "muslim", play=False)
        assert all(state.lords[lid].cylinder.locale_id == action["target_locale_id"]
                   for lid in (UPPER, LOWER))
    else:
        assert all(state.lords[lid].in_stronghold for lid in (UPPER, LOWER))
    assert state.lords[LOWER].lieutenant_of == UPPER


def test_independent_lord_can_withdraw_while_pair_stands():
    state = _approach(independent=True)
    _act(state, "respond_withdraw", lord_ids=["garcia_ordonez"])
    assert state.lords["garcia_ordonez"].in_stronghold
    assert set(state.pending.payload["defender_lord_ids"]) == {UPPER, LOWER}
    assert all(not state.lords[lid].in_stronghold for lid in (UPPER, LOWER))


def test_legacy_parked_avoid_that_would_split_the_pair_can_be_reselected():
    state = _approach()
    action = next(m for m in legal_moves(state) if m["type"] == "respond_avoid_battle")
    apply_action(state, action)
    state.pending.payload["avoid_action"]["lord_ids"] = [UPPER]
    state = GameState.model_validate_json(state.model_dump_json())
    _act(state, "respond_swollen_river_block", "muslim", play=False)
    assert state.meta.active_player == "christian"
    assert state.pending.kind == "march_arrival_response"
    assert all(state.lords[lid].cylinder.locale_id == "leon" for lid in (UPPER, LOWER))
    apply_action(state, action)
    _act(state, "respond_swollen_river_block", "muslim", play=False)
    assert all(state.lords[lid].cylinder.locale_id == action["target_locale_id"]
               for lid in (UPPER, LOWER))


def test_generated_sortie_brings_both_lords_outside_for_approach_and_feed():
    state = _plan()
    for lid in (UPPER, LOWER):
        _put(state, lid, "leon", inside=True)
    _put(state, "al_mustain", "leon")
    state.locales["leon"].bypass_green = True
    _stack(state)
    _finish_plan(state, christian=(UPPER,))
    _act(state, "command_reveal")

    move = next(m for m in legal_moves(state) if m["type"] == "cmd_sortie")
    result = apply_action(state, move)
    assert set(result["sortie_lords"]) == {UPPER, LOWER}
    assert set(state.pending.payload["approaching_lord_ids"]) == {UPPER, LOWER}
    for lid in (UPPER, LOWER):
        assert not state.lords[lid].in_stronghold
        assert state.lords[lid].moved_fought


def test_alferez_bearer_can_unstack_a_plan_pair_and_march_alone():
    state = _plan()
    for lid in (UPPER, LOWER):
        _put(state, lid, "leon")
    state.meta.phase = "levy"
    state.meta.levy_step = "muster"
    _act(state, "levy_take_capability", lord_id=UPPER, card_id="C15")
    state.meta.phase = "campaign"
    _stack(state)
    _finish_plan(state, christian=(UPPER,))
    _act(state, "command_reveal")

    move = next(m for m in legal_moves(state) if m["type"] == "toggle_lieutenant")
    assert move["mode"] == "unstack"
    apply_action(state, move)
    _act(state, "cmd_march", target_locale_id="astorga", way_type="road")
    assert state.lords[UPPER].cylinder.locale_id == "astorga"
    assert state.lords[LOWER].cylinder.locale_id == "leon"
    assert state.lords[LOWER].lieutenant_of is None


@pytest.mark.parametrize("upper_location", ["calendar", "astorga", "inside_leon"])
def test_older_save_with_broken_stack_keeps_positions_and_releases_lower(upper_location):
    state = _plan()
    for lid in (UPPER, LOWER):
        _put(state, lid, "leon")
    _stack(state)
    _finish_plan(state, christian=(LOWER,))
    upper = state.lords[UPPER]
    if upper_location == "calendar":
        upper.cylinder = Cylinder(kind="calendar", box=4)
    elif upper_location == "inside_leon":
        upper.in_stronghold = True
    else:
        _put(state, UPPER, upper_location)
    positions = {lid: (lord.cylinder, lord.in_stronghold) for lid, lord in state.lords.items()}
    state = GameState.model_validate_json(state.model_dump_json())
    assert positions == {lid: (lord.cylinder, lord.in_stronghold)
                         for lid, lord in state.lords.items()}
    assert state.lords[LOWER].lieutenant_of is None
    assert not _act(state, "command_reveal")["auto_pass"]
    assert state.meta.active_lord_id == LOWER


@pytest.mark.parametrize("paired", [True, False])
def test_war_drums_adds_provender_only_for_ravaging_lieutenant(paired):
    state = _plan()
    leader = _put(state, "al_mutamid", "coria")
    _put(state, "abu_bakr", "coria")
    state.locales["coria"].bypass_green = True
    state.decks.board_edge["muslim"] = ["M22"]
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id="M22", scope="side_wide", owner_side="muslim"))
    if paired:
        state.meta.active_player = "muslim"
        _stack(state, "al_mutamid", "abu_bakr", "muslim")
        state.meta.active_player = "christian"
    _finish_plan(state, muslim=("al_mutamid",))
    _act(state, "command_reveal")
    _act(state, "command_reveal", "muslim")
    move = next(m for m in legal_moves(state) if m["type"] == "cmd_ravage")
    apply_action(state, move)
    assert leader.assets["loot"] == 1
    assert leader.assets["prov"] == 1 + paired
