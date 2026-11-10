"""A5-04. The Approaching player selects the Relief Sally participants."""

import pytest

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import GameState
from almoravid.views import redacted_view
from tests.combat_choices import apply_combat_choices
from tests.test_cross_game_avoid_retreat_surrender import place, position, reject_unchanged
from tests.test_cross_game_reaction_privacy import hold

INSIDE = ("alvar_fanez", "pedro_ansurez")
STAND = {"type": "respond_stand_battle", "side": "muslim"}


def _approach():
    state = position()
    state.meta.hidden_mats = True
    place(state, "alfonso", "sahagun", coin=5)
    place(state, "al_mutamid", "leon", coin=5)
    for lord_id in INSIDE:
        place(state, lord_id, "leon", coin=5)
        state.lords[lord_id].in_stronghold = True
    state.locales["leon"].siege_green = 3
    apply_action(state, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "road"})
    assert state.pending.kind == "march_arrival_response"
    return state


def _relief_choice(*lords):
    return {"type": "relief_sally", "side": "christian", "lord_ids": list(lords)}


def test_the_relieving_side_owns_every_subset_and_invalid_actions_are_atomic():
    state = _approach()
    reject_unchanged(state, {**STAND, "attacker_concede_round": "invalid"}, "bad_arg")
    rng = state.meta.rng_state
    # The defender's extra fields cannot choose the attackers' Sallyers.
    apply_action(state, {**STAND, "lord_ids": list(INSIDE), "interactive_concede": True})
    assert state.pending.kind == "relief_sally"
    assert state.pending.waiting_on == state.meta.active_player == "christian"
    assert state.meta.rng_state == rng
    assert all(state.lords[lid].in_stronghold for lid in INSIDE)
    options = [move for move in legal_moves(state) if move["type"] == "relief_sally"]
    assert len(options) == 4
    assert {frozenset(move["lord_ids"]) for move in options} == {
        frozenset(), frozenset(INSIDE[:1]), frozenset(INSIDE[1:]), frozenset(INSIDE),
    }
    for bad, code in (
        ({**_relief_choice(*INSIDE), "side": "muslim"}, "not_responder"),
        (_relief_choice("alvar_fanez", "alvar_fanez"), "bad_arg"),
        (_relief_choice("al_mutamid"), "bad_arg"),
        (_relief_choice("alfonso"), "bad_arg"),
        ({**_relief_choice(), "lord_ids": None}, "bad_arg"),
        (STAND, "pending_decision"),
    ):
        reject_unchanged(state, bad, code)
    defender_view = redacted_view(state, "muslim")
    assert "_relief_sally_resume" not in defender_view["pending"]["payload"]
    assert all(defender_view["lords"][lid]["forces"] is None for lid in INSIDE)
    assert redacted_view(state, "christian")["lords"]["al_mutamid"]["forces"] is not None


@pytest.mark.parametrize("chosen", [(), INSIDE[:1], INSIDE])
@pytest.mark.parametrize("interactive", [False, True])
def test_selected_lords_join_after_reload_and_only_they_withdraw(chosen, interactive):
    state = _approach()
    apply_action(state, {**STAND, "interactive_concede": True} if interactive
                 else {**STAND, "attacker_concede_round": 1})
    state = GameState.model_validate_json(state.model_dump_json())
    stay = {lid: state.lords[lid].model_copy(deep=True) for lid in INSIDE if lid not in chosen}
    result = apply_action(state, _relief_choice(*chosen))
    if interactive:
        kind = "relief_concede" if chosen else "battle_concede"
        assert state.pending.kind == kind
        assert all(not state.lords[lid].in_stronghold for lid in chosen)
        result = apply_action(state, {"type": kind, "side": "christian", "attacker_concede": True})
    assert (result["winner"], result["rounds"]) == ("muslim", 1)
    losers = {entry["lord_id"]: entry["fate"] for entry in result["retreat_summary"]["losers"]}
    assert set(losers) == {"alfonso", *chosen}
    assert all(losers[lid] == "withdraw" and state.lords[lid].in_stronghold for lid in chosen)
    assert all(state.lords[lid] == before for lid, before in stay.items())
    assert state.locales["leon"].siege_green == (1 if chosen else 3)


def test_relief_choice_sets_camp_attack_targets_and_hidden_mats():
    state = _approach()
    hold(state, "muslim", "M2")
    apply_action(state, {**STAND, "interactive_concede": True})
    apply_action(state, _relief_choice("alvar_fanez"))
    state = GameState.model_validate_json(state.model_dump_json())
    assert state.pending.kind == "combat_holds"
    assert all(state.lords[lid].in_stronghold for lid in INSIDE)
    view = redacted_view(state, "muslim")
    assert view["lords"]["alvar_fanez"]["forces"] is not None
    assert view["lords"]["pedro_ansurez"]["forces"] is None
    apply_action(state, {"type": "combat_holds", "side": "christian"})
    apply_action(state, {"type": "combat_holds", "side": "muslim", "card_id": "M2"})
    apply_action(state, {"type": "combat_holds", "side": "muslim"})
    assert state.pending.kind == "relief_concede"
    assert state.pending.payload["rs"]["sallyers"]["lord_ids"] == ["alvar_fanez"]
    assert state.lords["alfonso"].assets["coin"] == state.lords["alvar_fanez"].assets["coin"] == 1
    assert state.lords["pedro_ansurez"].assets["coin"] == 5
    assert state.lords["pedro_ansurez"].in_stronghold


def test_swollen_river_forces_stand_and_leaves_the_relief_choice_to_the_attacker():
    state = _approach()
    hold(state, "christian", "C3")
    avoid = next(move for move in legal_moves(state) if move["type"] == "respond_avoid_battle")
    apply_action(state, avoid)
    result = apply_action(state, {"type": "respond_swollen_river_block", "side": "christian",
                                  "play": True})
    assert result["swollen_river_played"] == "C3"
    assert state.pending.kind == "relief_sally"
    assert state.pending.waiting_on == "christian"
    assert state.lords["al_mutamid"].cylinder.locale_id == "leon"
    assert all(state.lords[lid].in_stronghold for lid in INSIDE)


def test_legacy_combat_hold_save_resumes_with_all_sallyers_already_committed():
    state = _approach()
    hold(state, "muslim", "M2")
    apply_action(state, {**STAND, "interactive_concede": True})
    apply_action(state, _relief_choice(*INSIDE))
    saved = state.model_dump(mode="json")
    saved["pending"]["payload"]["_combat_hold_resume"]["pending"]["payload"].pop("sallyer_ids")
    state = GameState.model_validate(saved)
    apply_action(state, {"type": "combat_holds", "side": "christian"})
    apply_action(state, {"type": "combat_holds", "side": "muslim"})
    assert state.pending.kind == "relief_concede"
    assert set(state.pending.payload["rs"]["sallyers"]["lord_ids"]) == set(INSIDE)


def test_relief_retargets_the_front_after_the_rear_defender_routes():
    def begin(interactive):
        state = position(seed=7)
        for lid, locale, forces in (
            ("alfonso", "leon", {"militia": 1}),
            ("alvar_fanez", "zamora", {"knights": 2}),
            ("al_mutamid", "zamora", {"sergeants": 2}),
            ("al_mundir", "zamora", {"militia": 1}),
        ):
            place(state, lid, locale)
            state.lords[lid].forces = forces
        state.lords["alvar_fanez"].in_stronghold = True
        state.locales["zamora"].siege_green = 1
        apply_action(state, {"type": "cmd_march", "side": "christian",
                             "target_locale_id": "zamora", "way_type": "road"})
        result = apply_combat_choices(
            state, {**STAND, "interactive_concede": interactive},
            sallyers=("alvar_fanez",))
        return state, result

    state, _ = begin(True)
    for round_index in range(1, 9):
        state = GameState.model_validate_json(state.model_dump_json())
        apply_action(state, {"type": "relief_concede", "side": "christian"})
        result = apply_action(state, {"type": "relief_concede", "side": "muslim"})
        if round_index == 1:
            forces = state.pending.payload["rs"]["lf"]
            assert not forces["M"]["alfonso"]
            assert not forces["DR"]["al_mundir"]
            assert forces["S"]["alvar_fanez"] == {"knights": 2}
            assert forces["DF"]["al_mutamid"] == {"sergeants": 2}
        if "winner" in result:
            break
    else:
        pytest.fail("Live opponents never finish the Relief Sally after the rear Rout")

    synchronous, direct = begin(False)
    assert result == direct
    assert result["rounds"] > 1
    assert state.meta.rng_state == synchronous.meta.rng_state
    assert state.lords == synchronous.lords
