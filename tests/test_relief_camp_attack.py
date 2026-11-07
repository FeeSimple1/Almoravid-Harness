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
    apply_action(state, {**stand, "interactive_concede": True})
    assert state.pending.kind == "relief_concede"
    relief = state.pending.payload["rs"]
    assert relief["shared"] == (besiegers == 1)
    assert len(relief["excess_ids"]) == max(0, besiegers - 4)
    assert state.decks.discard.count(card) == 1
    for lid in victims:
        assert state.lords[lid].assets["coin"] == (5 if parapet else 1)
    coins = [state.lords[lid].assets.get("coin", 0) for lid in recipients]
    assert sum(coins) == (0 if parapet else 2 * len(victims))
    if not parapet:
        assert all(coins)

    state = GameState.model_validate_json(state.model_dump_json())
    stepped = apply_action(state, {"type": "relief_concede", "side": "christian",
                                  "attacker_concede": True})
    resolved = apply_action(synchronous, {**stand, "attacker_concede_round": 1})
    assert (stepped["winner"], stepped["rounds"]) == (resolved["winner"], resolved["rounds"])
    assert state.lords == synchronous.lords
    assert state.decks == synchronous.decks
