"""Replay older non-Reset regressions with explicit keep-card elections."""
from __future__ import annotations

from almoravid.actions import apply_action


def apply_action_keeping_reset_cards(state, action):
    """Complete newly introduced Reset windows in pre-existing game traces.

    These tests exercise Wastage, Winter and other rules. Dedicated Reset
    regressions call the engine directly and test both players' elections.
    """
    result = apply_action(state, action)
    final = None
    while state.pending is not None and state.pending.kind == "reset_discard":
        response = apply_action(state, {"type": "reset_discard",
                                        "side": state.pending.waiting_on, "card_ids": []})
        final = response.get("advance", final)
    if final is not None:
        cursor = result
        while isinstance(cursor.get("advance"), dict):
            cursor = cursor["advance"]
        if cursor.get("pending") == "reset_discard":
            cursor.clear()
            cursor.update(final)
    return result
