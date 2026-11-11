import pytest

from almoravid.actions import apply_action
from almoravid.effective import lieutenant_for
from almoravid.legal_moves import legal_moves
from almoravid.state import GameState
from tests.test_cross_game_avoid_retreat_surrender import reject_unchanged
from tests.test_cross_game_battle_fates import fate_moves
from tests.test_cross_game_reaction_privacy import hold
from tests.test_round11_lieutenants import LOWER, UPPER, _act, _finish_plan, _plan, _put, _stack


PAIR = (UPPER, LOWER)


def _reload(state):
    return GameState.model_validate_json(state.model_dump_json())


def _finish_holds(state):
    while state.pending is not None and state.pending.kind == "combat_holds":
        _act(state, "combat_holds", state.pending.waiting_on)


def _approach(locale, *, paired=True, relief=False, independent=False):
    state = _plan(seed=1 if relief else 3)
    for lord_id in PAIR:
        _put(state, lord_id, locale, inside=relief)
    if paired:
        _stack(state)
    if relief:
        _put(state, "al_mustain", locale)
        _put(state, "alfonso", "sahagun")
        state.locales[locale].siege_green = 1
        _finish_plan(state, christian=("alfonso", LOWER))
        attacker = "christian"
    else:
        origin = "astorga" if locale == "leon" else "leon"
        _put(state, "al_mustain", origin)
        if independent:
            _put(state, "alfonso", locale)
        state.locales[origin].bypass_green = True
        _act(state, "plan_add_card", plan_kind="pass")
        _finish_plan(state, christian=(LOWER,), muslim=("al_mustain",))
        attacker = "muslim"
    _act(state, "command_reveal")
    if attacker == "muslim":
        _act(state, "command_reveal", attacker)
    _act(state, "cmd_march", attacker, target_locale_id=locale, way_type="road")
    assert state.pending.kind == "march_arrival_response"
    return state


def _defender_loses(state, *, interactive=True):
    if interactive:
        _act(state, "respond_stand_battle", interactive_concede=True, interactive_retreat=True)
    else:
        _act(state, "respond_stand_battle", defender_concede_round=1)
    _finish_holds(state)
    if interactive:
        _act(state, "battle_concede", "muslim")
        _act(state, "battle_concede", defender_concede=True)
        assert state.pending.kind == "battle_fate"


def _fate(lord_id, fate, **destination):
    return {"type": "battle_fate", "side": "christian", "lord_id": lord_id,
            "fate": fate, **destination}


def _assert_pair_at(state, locale, *, inside):
    for lord_id in PAIR:
        lord = state.lords[lord_id]
        assert lord.cylinder.locale_id == locale and lord.in_stronghold == inside
    assert lieutenant_for(state, state.lords[LOWER]) == UPPER


def test_castle_cannot_accept_half_a_surviving_pair_and_lower_card_passes():
    state = _approach("zamora")
    _defender_loses(state)
    state = _reload(state)
    for lord_id in PAIR:
        assert _fate(lord_id, "withdraw") not in fate_moves(state)
        reject_unchanged(state, _fate(lord_id, "withdraw"), "bad_arg")
    route = {"retreat_to": "simancas", "retreat_way": "road"}
    apply_action(state, _fate(UPPER, "retreat", **route))
    state = _reload(state)
    assert {move.get("retreat_to") for move in fate_moves(state, LOWER)} == {"simancas", None}
    apply_action(state, _fate(LOWER, "retreat", **route))
    _assert_pair_at(state, "simancas", inside=False)

    if state.pending and state.pending.kind == "severed_heads":
        _act(state, "decline_severed_heads", "muslim")
    if state.pending and state.pending.kind == "besiege_or_bypass":
        _act(state, "respond_bypass", "muslim")
    _act(state, "end_card", "muslim")
    revealed = _act(state, "command_reveal")
    assert revealed["revealed"]["lord_id"] == LOWER and revealed["auto_pass"]


def test_scripted_battle_defaults_retreat_both_from_a_castle():
    state = _approach("zamora")
    _defender_loses(state, interactive=False)
    destination = state.lords[UPPER].cylinder.locale_id
    assert destination != "zamora"
    _assert_pair_at(state, destination, inside=False)


def test_town_reserves_the_partners_slot_until_the_election_resolves():
    state = _approach("leon", independent=True)
    _defender_loses(state)
    first = _fate(UPPER, "withdraw")
    assert first in fate_moves(state)
    assert _fate("alfonso", "withdraw") in fate_moves(state)
    apply_action(state, first)
    state = _reload(state)
    assert _fate(LOWER, "withdraw") in fate_moves(state)
    assert _fate("alfonso", "withdraw") not in fate_moves(state)
    reject_unchanged(state, _fate("alfonso", "withdraw"), "bad_arg")
    assert {move["fate"] for move in fate_moves(state, LOWER)} == {"withdraw", "removed"}
    apply_action(state, _fate(LOWER, "withdraw"))
    alfonso_retreat = next(move for move in fate_moves(state, "alfonso") if move["fate"] == "retreat")
    apply_action(state, alfonso_retreat)
    _assert_pair_at(state, "leon", inside=True)


@pytest.mark.parametrize("departing, survivor", [(UPPER, LOWER), (LOWER, UPPER)])
def test_removal_releases_the_partner_to_use_a_single_castle_slot(departing, survivor):
    state = _approach("zamora")
    _defender_loses(state)
    apply_action(state, _fate(departing, "removed"))
    state = _reload(state)
    apply_action(state, _fate(survivor, "withdraw"))
    assert state.lords[departing].cylinder.kind == "removed"
    assert state.lords[survivor].cylinder.locale_id == "zamora"
    assert state.lords[survivor].in_stronghold
    assert state.lords[survivor].lieutenant_of is None


def test_legacy_incompatible_withdrawal_is_available_for_reselection():
    state = _approach("zamora")
    _defender_loses(state)
    expected = fate_moves(state)
    saved = state.model_dump(mode="json")
    pending = saved["pending"]["payload"]
    del pending["options"][UPPER]
    pending["options"][LOWER].remove({"fate": "withdraw"})
    pending["withdraw_slots"] = 0
    pending["fates"][UPPER] = {"fate": "withdraw"}
    restored = GameState.model_validate(saved)
    assert fate_moves(restored) == expected
    assert restored.pending.payload["fates"] == {}
    _assert_pair_at(restored, "zamora", inside=False)


@pytest.mark.parametrize("legacy_hold", [False, True])
def test_relief_sally_moves_and_returns_the_entire_pair(legacy_hold):
    state = _approach("leon", relief=True)
    if legacy_hold:
        hold(state, "muslim", "M2")
    _act(state, "respond_stand_battle", "muslim", interactive_concede=True)
    assert state.pending.waiting_on == "christian"
    assert {frozenset(move["lord_ids"]) for move in legal_moves(state)
            if move["type"] == "relief_sally"} == {frozenset(), frozenset(PAIR)}
    for lord_id in PAIR:
        reject_unchanged(state, {"type": "relief_sally", "side": "christian", "lord_ids": [lord_id]},
                         "lt_pair_split")
    _act(state, "relief_sally", lord_ids=list(PAIR))
    if legacy_hold:
        pending = state.pending.payload
        pending["attacker_ids"].remove(UPPER)
        pending["_combat_hold_resume"]["pending"]["payload"]["sallyer_ids"] = [LOWER]
    state = _reload(state)
    _finish_holds(state)
    assert state.pending.payload["rs"]["sallyers"]["lord_ids"] == list(PAIR)
    _assert_pair_at(state, "leon", inside=False)
    result = _act(state, "relief_concede", attacker_concede=True)
    fates = {entry["lord_id"]: entry["fate"] for entry in result["retreat_summary"]["losers"]}
    assert all(fates[lord_id] == "withdraw" for lord_id in PAIR)
    _assert_pair_at(state, "leon", inside=True)
