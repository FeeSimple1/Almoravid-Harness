"""Capability lookup helpers (Arts of War cards in play).

Per Pattern 14 from FUTURE_PROJECTS_LESSONS.md (SMOKE-016 in Nevsky):
every Capability has an explicit scope — `this_lord` (tucked under one
Lord on his mat) or `side_wide` (in decks.capabilities_in_play). Lookup
helpers MUST filter by scope. A side-wide cap accidentally checked via
a this-lord helper, or vice versa, was a bug source in Nevsky.

This module is the only place capability lookups should happen. Direct
reads of `lord.capabilities` or `state.decks.capabilities_in_play` are
audit smells — go through these helpers so the scope filter stays
enforceable.
"""

from __future__ import annotations

from almoravid.state import GameState, Side
from almoravid.static_data import load_cards


def _scope_of(card_id: str) -> str | None:
    """Return 'this_lord' or 'side_wide' for the named card; None if no capability half."""
    cards = load_cards()["cards"]
    rec = cards.get(card_id)
    if rec is None or rec["no_capability"]:
        return None
    return rec["capability_scope"]


def lord_has_capability(state: GameState, lord_id: str, card_id: str) -> bool:
    """Does this Lord have the named capability on his mat (this_lord scope)?

    Returns False if the card is side_wide — wrong helper for that.
    """
    if _scope_of(card_id) != "this_lord":
        return False
    lord = state.lords.get(lord_id)
    if lord is None:
        return False
    return card_id in lord.capabilities


def any_lord_with_capability(
    state: GameState, side: Side, card_id: str,
) -> list[str]:
    """Return lord_ids on `side` whose mat has the this_lord capability.

    Pattern 14: returns [] for side_wide cards (use side_has_capability).
    """
    if _scope_of(card_id) != "this_lord":
        return []
    return [
        lid for lid, l in state.lords.items()
        if l.side == side and card_id in l.capabilities
    ]


def side_has_capability(state: GameState, side: Side, card_id: str) -> bool:
    """Is the side-wide capability in play for this side?

    Pattern 14: returns False for this_lord cards (wrong scope).
    """
    if _scope_of(card_id) != "side_wide":
        return False
    return any(
        c.card_id == card_id and c.owner_side == side and c.scope == "side_wide"
        for c in state.decks.capabilities_in_play
    )


def capabilities_for_lord(state: GameState, lord_id: str) -> list[str]:
    """All this_lord-scope capability card_ids on this Lord's mat."""
    lord = state.lords.get(lord_id)
    if lord is None:
        return []
    # Pattern 14: every entry in lord.capabilities should resolve to a
    # this_lord card. Defensive filter so a corrupt state doesn't lie.
    return [cid for cid in lord.capabilities if _scope_of(cid) == "this_lord"]


def capabilities_for_side(state: GameState, side: Side) -> list[str]:
    """All side-wide capability card_ids in play for this side."""
    return [
        c.card_id for c in state.decks.capabilities_in_play
        if c.owner_side == side and c.scope == "side_wide"
    ]


def any_capability(
    state: GameState, side: Side, card_id: str,
    lord_id: str | None = None,
) -> bool:
    """Scope-correct generic check: does the named capability apply?

    For this_lord cards, requires a matching lord_id (or any Lord on
    `side` if lord_id is None). For side_wide cards, ignores lord_id.

    This is the helper most resolvers should call when they only care
    'is this capability active for this side / Lord?' without knowing
    the card's scope ahead of time.
    """
    scope = _scope_of(card_id)
    if scope == "side_wide":
        return side_has_capability(state, side, card_id)
    if scope == "this_lord":
        if lord_id is not None:
            return lord_has_capability(state, lord_id, card_id)
        return bool(any_lord_with_capability(state, side, card_id))
    return False
