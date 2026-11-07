"""A5-03. The M7 owner assigns the markers before combat."""

import pytest

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import GameState
from tests.test_cross_game_avoid_retreat_surrender import place, position, reject_unchanged
from tests.test_cross_game_reaction_privacy import hold


def _pass_holds(state):
    return apply_action(state, {"type": "combat_holds", "side": state.pending.waiting_on})


def _spear_wall_moves(state):
    return [move for move in legal_moves(state)
            if move["type"] == "combat_holds" and move.get("card_id") == "M7"]


@pytest.mark.parametrize("attacker", ["christian", "muslim"])
def test_owner_selects_two_lords_and_can_choose_the_round_after_reload(attacker):
    state = position()
    place(state, "alfonso", "transduero")
    muslims = ["al_mutamid", "al_mundir", "al_mustain"]
    for lord_id, count in zip(muslims, (4, 3, 2), strict=True):
        place(state, lord_id, "transduero")
        state.lords[lord_id].forces = {"men_at_arms": count}
    place(state, "yusuf", "toledo")
    hold(state, "muslim", "M7")
    state.meta.active_player = attacker
    state.meta.active_lord_id = "alfonso" if attacker == "christian" else "al_mutamid"
    apply_action(state, {"type": "cmd_battle", "side": attacker,
                         "interactive_concede": True, "interactive_timing": True})
    if attacker == "christian":
        assert _spear_wall_moves(state) == []
        _pass_holds(state)
    assert state.pending.waiting_on == "muslim"
    options = _spear_wall_moves(state)
    assert {frozenset(move["lord_ids"]) for move in options} == {
        frozenset(muslims[:2]), frozenset(muslims[::2]), frozenset(muslims[1:]),
    }
    play = {"type": "combat_holds", "side": "muslim", "card_id": "M7"}
    reject_unchanged(state, play, "bad_arg")
    for invalid in (muslims, [], muslims[:1], ["al_mundir", "al_mundir"],
                    ["al_mundir", "alfonso"], ["al_mundir", "yusuf"], ["al_mundir", []]):
        reject_unchanged(state, {**play, "lord_ids": invalid}, "bad_arg")
    apply_action(state, {**play, "lord_ids": muslims[1:]})
    assert state.decks.held["muslim"] == []
    state = GameState.model_validate_json(state.model_dump_json())
    _pass_holds(state)
    if attacker == "muslim":
        _pass_holds(state)
    assert state.pending.kind == "oneround_timing"
    state = GameState.model_validate_json(state.model_dump_json())
    apply_action(state, {"type": "oneround_timing", "side": "muslim", "m7_round": 2})
    assert state.pending.kind == "battle_concede"
    snapshot = state.pending.payload["attacker" if attacker == "muslim" else "defender"]
    assert snapshot["m7_round"] == 2
    assert {lord["lord_id"] for lord in snapshot["array"] if lord["m7_marked"]} == set(muslims[1:])
    apply_action(state, {"type": "battle_concede", "side": attacker, "attacker_concede": True})
    assert state.meta.spear_wall_lord_ids is None
    assert state.decks.discard.count("M7") == 1


def test_sole_selected_lord_gets_the_bonus_on_repeated_protection_rolls(monkeypatch):
    state = position()
    place(state, "alfonso", "transduero")
    state.lords["alfonso"].forces = {"knights": 2}
    place(state, "al_mutamid", "transduero")
    state.lords["al_mutamid"].forces = {"men_at_arms": 1}
    hold(state, "muslim", "M7")
    apply_action(state, {"type": "cmd_battle", "side": "christian", "interactive_concede": True})
    _pass_holds(state)
    options = _spear_wall_moves(state)
    assert len(options) == 1 and options[0]["lord_ids"] == ["al_mutamid"]
    apply_action(state, options[0])
    _pass_holds(state)
    monkeypatch.setattr("almoravid.battle.roll_d6", lambda _: 4)
    apply_action(state, {"type": "battle_concede", "side": "christian"})
    apply_action(state, {"type": "battle_concede", "side": "muslim"})
    assert state.pending.payload["defender"]["forces"] == {"men_at_arms": 1}
    assert state.decks.discard.count("M7") == 1


def test_relief_sally_scopes_the_bonus_to_the_owner_of_each_unit(monkeypatch):
    state = position()
    place(state, "alfonso", "leon")
    state.lords["alfonso"].forces = {"knights": 2}
    place(state, "sancho", "zamora")
    state.lords["sancho"].forces = {"knights": 2}
    place(state, "alvar_fanez", "zamora")
    state.lords["alvar_fanez"].in_stronghold = True
    state.locales["zamora"].siege_green = 3
    for lord_id in ("al_mutamid", "al_mundir", "al_mustain"):
        place(state, lord_id, "zamora")
        state.lords[lord_id].forces = {"men_at_arms": 1}
    hold(state, "muslim", "M7")
    apply_action(state, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "zamora", "way_type": "road"})
    apply_action(state, {"type": "respond_stand_battle", "side": "muslim",
                         "interactive_concede": True})
    _pass_holds(state)
    apply_action(state, {"type": "combat_holds", "side": "muslim", "card_id": "M7",
                         "lord_ids": ["al_mutamid", "al_mundir"]})
    _pass_holds(state)
    state = GameState.model_validate_json(state.model_dump_json())
    assert state.pending.kind == "relief_concede"
    monkeypatch.setattr("almoravid.battle.roll_d6", lambda _: 4)
    apply_action(state, {"type": "relief_concede", "side": "christian"})
    apply_action(state, {"type": "relief_concede", "side": "muslim"})
    relief = state.pending.payload["rs"]
    assert relief["lf"]["DF"] == {"al_mustain": {}, "al_mutamid": {"men_at_arms": 1}}
    assert relief["lr"]["DF"] == {"al_mustain": {"men_at_arms": 1}, "al_mutamid": {}}
    assert state.decks.discard.count("M7") == 1
