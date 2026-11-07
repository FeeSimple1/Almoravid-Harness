"""Explicit Event policy for tests that exercise later combat decisions."""

from almoravid.actions import apply_action


def apply_combat_choices(state, action, *, cards=()):
    """Play the requested cards and decline every other combat Hold."""
    result = apply_action(state, action)
    played = set()
    while state.pending is not None and state.pending.kind == "combat_holds":
        side = state.pending.waiting_on
        for card in cards:
            if card in state.decks.held.get(side, []):
                apply_action(state, {"type": "combat_holds", "side": side, "card_id": card})
                played.add(card)
        result = apply_action(state, {"type": "combat_holds", "side": side})
    assert played == set(cards)
    return result
