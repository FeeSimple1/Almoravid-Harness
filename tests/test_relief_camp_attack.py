"""Camp Attack applies once across the full Relief Sally force (4.4.1)."""

import pytest

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import GameState
from tests.test_cross_game_avoid_retreat_surrender import place, position
from tests.test_cross_game_reaction_privacy import hold


@pytest.mark.parametrize(("card", "besiegers", "parapet"), [
    ("C2", 1, False),  # the same Defender faces Marchers and Sallyers
    ("C2", 2, False),
    ("C2", 5, False),  # one Defender starts in excess Reserve
    ("M2", 2, False),
    ("M2", 2, True),
])
def test_relief_camp_attack_targets_all_lords_once(card, besiegers, parapet):
    state = position()
    christians = ["alfonso", "alvar_fanez"]
    muslims = ["al_mutamid", "al_mundir", "al_mustain", "abu_bakr", "yusuf"][:besiegers]
    recipients, victims = (christians, muslims) if card == "C2" else (muslims, christians)
    place(state, "alfonso", "leon")
    for lid in [*christians[1:], *muslims]:
        place(state, lid, "zamora")
    for lid in victims:
        state.lords[lid].assets["coin"] = 5
    state.lords["alvar_fanez"].in_stronghold = True
    state.locales["zamora"].siege_green = 3
    hold(state, "christian" if card == "C2" else "muslim", card)
    if parapet:
        hold(state, "christian", "C7")

    apply_action(state, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "zamora", "way_type": "road"})
    stand = next(move for move in legal_moves(state) if move["type"] == "respond_stand_battle")
    synchronous = state.model_copy(deep=True)
    for current, command in (
        (state, {**stand, "interactive_concede": True}),
        (synchronous, {**stand, "attacker_concede_round": 1}),
    ):
        apply_action(current, command)
        result = apply_action(current, {"type": "relief_sally", "side": "christian",
                                        "lord_ids": ["alvar_fanez"]})
        while current.pending is not None and current.pending.kind == "combat_holds":
            move = next(move for move in legal_moves(current) if move["type"] == "combat_holds")
            result = apply_action(current, move)
    assert state.pending.kind == "relief_concede"
    relief = state.pending.payload["rs"]
    assert relief["shared"] == (besiegers == 1)
    assert len(relief["excess_ids"]) == max(0, besiegers - 4)
    assert state.decks.discard.count(card) == int(parapet)
    assert all(state.lords[lid].assets["coin"] == 5 for lid in victims)

    state = GameState.model_validate_json(state.model_dump_json())
    stepped = apply_action(state, {"type": "relief_concede", "side": "christian",
                                  "attacker_concede": True})
    if not parapet:
        owner = "christian" if card == "C2" else "muslim"
        assert state.pending.kind == "camp_attack" and state.pending.waiting_on == owner
        if card == "C2" and besiegers == 2:
            waited = []
            while delay := next((m for m in legal_moves(state) if m.get("mode") == "wait"), None):
                waited.append(apply_action(state, delay)["after"])
                state = GameState.model_validate_json(state.model_dump_json())
            assert waited[0] == "1.a" and len(waited) > 1
            assert state.pending.payload["camp_attack_round"]["finished"]
        stepped = apply_action(state, {"type": "camp_attack", "side": owner, "mode": "auto"})
        camp = stepped["camp_attack"]
        assert camp["taken"] == camp["removed"] == {lid: {"coin": 2} for lid in victims}
        assert set(camp["spoils_awarded"]) == set(recipients[:2 * len(victims)])
        assert sum(award["coin"] for award in camp["spoils_awarded"].values()) == 2 * len(victims)
    assert state.decks.discard.count(card) == 1
    resolved = result
    assert (stepped["winner"], stepped["rounds"]) == (resolved["winner"], resolved["rounds"])
    assert state.lords == synchronous.lords
    assert state.decks == synchronous.decks
    assert state.meta.rng_state == synchronous.meta.rng_state
