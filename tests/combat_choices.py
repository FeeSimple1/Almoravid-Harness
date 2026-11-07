"""Explicit setup choices for tests that exercise later combat decisions."""

from almoravid.actions import apply_action


def apply_combat_choices(state, action, *, cards=(), spear_wall_lords=(), sallyers=()):
    """Select Relief Sally participants and play the requested combat Holds."""
    result = apply_action(state, action)
    if state.pending is not None and state.pending.kind == "relief_sally":
        result = apply_action(state, {"type": "relief_sally", "side": state.pending.waiting_on,
                                      "lord_ids": list(sallyers)})
    played = set()
    while state.pending is not None and state.pending.kind == "combat_holds":
        side = state.pending.waiting_on
        for card in cards:
            if card in state.decks.held.get(side, []):
                play = {"type": "combat_holds", "side": side, "card_id": card}
                if card == "M7":
                    play["lord_ids"] = list(spear_wall_lords)
                apply_action(state, play)
                played.add(card)
        result = apply_action(state, {"type": "combat_holds", "side": side})
    assert played == set(cards)
    return result
