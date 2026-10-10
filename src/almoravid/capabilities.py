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

from typing import cast

from almoravid.state import GameState, Side
from almoravid.static_data import load_cards

# Eligible-Lord sets for This-Lord capabilities whose card text restricts
# WHO may hold them (Arts of War Reference "Lords." line; 3.4.4). The four
# Christian "captains" share one list across C8 Hueste, C15 Alferez, and
# C24 Garcia Jimenez (their card "Lords." lines are identical). Eligibility
# is a fixed set printed on the card, NOT a rule-derived predicate, so it
# does not recompute when Command ratings change (e.g. via Mesnada).
# Rodrigo eligibility binds to Rodrigo Campeador (the Christian/yellow
# cylinder), never Rodrigo al-Sayyid. [Q-001 resolution]
CHRISTIAN_CAPTAINS_FOUR = frozenset({
    "pedro_ansurez", "garcia_ordonez", "alvar_fanez", "rodrigo_campeador",
})
# M24 Al-Garada (Muslim long-range Ravage, the Cabalgadas twin) is held by
# "Taifa Muslim or Rodrigo al-Sayyid" (Arts of War ref M24). "Taifa Muslim" =
# the six Taifa Lords per the 1.5.1 design note (Yusuf/Sir/Rodrigo are NOT
# Taifa Lords); Rodrigo al-Sayyid (green cylinder) is named separately. Yusuf
# and Sir are NOT eligible. [Q-002 resolution]
MUSLIM_RAIDERS_SEVEN = frozenset({
    "abd_allah", "abu_bakr", "al_mundir", "al_mustain", "al_mutamid",
    "al_mutawakkil",          # the six Taifa Muslim Lords
    "rodrigo_al_sayyid",      # named separately on the card
})
# M14 & M18 Ribat Monks are held by "Taifa Muslim" only (Arts of War ref
# M14&M18 "Lords." line) — the six Taifa Lords, NOT Yusuf/Sir/Rodrigo.
MUSLIM_TAIFA_SIX = frozenset({
    "abd_allah", "abu_bakr", "al_mundir", "al_mustain", "al_mutamid",
    "al_mutawakkil",
})
# "Not Eudes" Christian this_lord caps (C3/C10 Adalides, C11/C12 Mesnada).
CHRISTIAN_NOT_EUDES = frozenset({
    "alfonso", "sancho", "pedro_ansurez", "garcia_ordonez",
    "alvar_fanez", "rodrigo_campeador",
})
_CAPABILITY_ELIGIBLE_LORDS: dict[str, frozenset[str]] = {
    "C13": frozenset({"sancho", "eudes"}),
    "M23": frozenset({"al_mustain", "al_mundir"}),
    "C16": frozenset({"alfonso"}),
    "C20": frozenset({"alfonso"}),  # Fueros (board edge)
    "M15": MUSLIM_TAIFA_SIX,          # Saqalibah (This Lord)
    "M20": MUSLIM_TAIFA_SIX,          # Al-Rum (This Lord)
    "C21": frozenset({"alfonso"}),  # Sisnando Davidez (board edge)
    "C8": CHRISTIAN_CAPTAINS_FOUR,    # Hueste
    "C15": CHRISTIAN_CAPTAINS_FOUR,   # Alferez
    "C24": CHRISTIAN_CAPTAINS_FOUR,   # Garcia Jimenez
    "M24": MUSLIM_RAIDERS_SEVEN,      # Al-Garada (Muslim Cabalgadas) [Q-002]
    "M14": MUSLIM_TAIFA_SIX,          # Ribat Monks (Taifa Muslim only)
    "M18": MUSLIM_TAIFA_SIX,          # Ribat Monks (Taifa Muslim only)
    # Combat caps restricted to "Taifa Muslim or Rodrigo al-Sayyid".
    "M1": MUSLIM_RAIDERS_SEVEN, "M2": MUSLIM_RAIDERS_SEVEN,
    "M3": MUSLIM_RAIDERS_SEVEN, "M4": MUSLIM_RAIDERS_SEVEN,
    "M5": MUSLIM_RAIDERS_SEVEN, "M6": MUSLIM_RAIDERS_SEVEN,
    "M7": MUSLIM_RAIDERS_SEVEN, "M13": MUSLIM_RAIDERS_SEVEN,
    "M17": MUSLIM_RAIDERS_SEVEN,
    "M8": frozenset({"yusuf", "sir"}),         # Dawud ibn Aisha
    "M9": frozenset({"yusuf"}),                # Emir al-Muslimin
    "M25": frozenset({"rodrigo_al_sayyid"}),   # El Cid
    "M26": frozenset({"rodrigo_al_sayyid"}),   # Al-Faraj
    "C25": frozenset({"rodrigo_campeador"}),   # El Cid
    "C26": frozenset({"rodrigo_campeador"}),   # Al-Faraj
    "C3": CHRISTIAN_NOT_EUDES, "C10": CHRISTIAN_NOT_EUDES,   # Adalides
    "C11": CHRISTIAN_NOT_EUDES, "C12": CHRISTIAN_NOT_EUDES,  # Mesnada
}


def capability_eligible_lords(card_id: str) -> frozenset[str] | None:
    """Printed Lords who may Levy a capability, or hold a This-Lord card.

    None means any Lord of the card's side (3.4.4). Board-edge cards drawn
    during Arts of War deploy without assignment to a Lord (3.1.2).
    """
    return _CAPABILITY_ELIGIBLE_LORDS.get(card_id)


def _scope_of(card_id: str) -> str | None:
    """Return 'this_lord' or 'side_wide' for the named card; None if no capability half."""
    cards = load_cards()["cards"]
    rec = cards.get(card_id)
    if rec is None or rec["no_capability"]:
        return None
    return cast("str | None", rec["capability_scope"])


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
        lid for lid, lord in state.lords.items()
        if lord.side == side and card_id in lord.capabilities
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


def discard_capability(state: GameState, card_id: str) -> None:
    """Remove a Capability and its printed discard effects exactly once.

    Called for Campaign excess (4.0), Winter (6.3.1), Disband/removal
    (3.3), and Wastage (4.9.4). This is not an Event-discard operation:
    C18's permanent removal applies to *Milites*, not Runaway Slaves.
    M15/M20 and the Count lose their tracked contingent and once-per-card
    usage, while Milites explicitly leaves its recruited units in place.
    """
    if card_id in ("M15", "M20"):
        rec = state.meta.aow_cap_state.pop(f"{card_id}_units", {})
        state.meta.aow_cap_state.pop(f"{card_id}_used", None)
        lord = state.lords.get(rec.get("lord"))
        unit = "men_at_arms" if card_id == "M15" else "knights"
        if lord is not None and rec.get(unit, 0):
            lord.forces[unit] = max(0, lord.forces.get(unit, 0) - rec[unit])
    elif card_id in ("C13", "M23"):
        from almoravid.events import _remove_count_units
        _remove_count_units(state, card_id)
    elif card_id == "C22":
        from almoravid.campaign import _remove_bishops
        _remove_bishops(state)
    elif card_id == "C18":
        # Printed C18: discard leaves the units, but removes both card halves.
        state.meta.aow_cap_state.pop("C18_pool", None)
        state.meta.aow_cap_state.pop("C18_lords", None)
        if card_id not in state.decks.removed_from_game:
            state.decks.removed_from_game.append(card_id)

    for lord in state.lords.values():
        if card_id in lord.capabilities:
            lord.capabilities = [c for c in lord.capabilities if c != card_id]
    for side, edge in state.decks.board_edge.items():
        state.decks.board_edge[side] = [c for c in edge if c != card_id]
    state.decks.capabilities_in_play = [
        c for c in state.decks.capabilities_in_play if c.card_id != card_id]
    state.decks.draw = [c for c in state.decks.draw if c != card_id]
    if card_id in state.decks.removed_from_game:
        state.decks.discard = [c for c in state.decks.discard if c != card_id]
    elif card_id not in state.decks.discard:
        state.decks.discard.append(card_id)


# ---------------------------------------------------------------------------
# Phase 7a: Capability-derived stat helpers.
# ---------------------------------------------------------------------------


def _lord_has_horse(state: GameState, lord_id: str) -> bool:
    """Does the Lord have at least one Horse unit on his mat?"""
    from almoravid.static_data import load_forces
    horse = set(load_forces()["horse"].keys())
    lord = state.lords.get(lord_id)
    if lord is None:
        return False
    return any(lord.forces.get(ut, 0) > 0 for ut in horse)


def effective_command(state: GameState, lord_id: str) -> int:
    """Lord's Command rating including capability bonuses (rule 1.5.3).

    Mesnada (C11/C12, this_lord): +1 Command if the Lord has any
    Knights unit. Hasham (M11/M21, this_lord): +1 Command if the Lord
    has any Horse unit. A Lord may hold only one Mesnada and one
    Hasham (3.4.4), so each contributes at most +1.
    """
    lord = state.lords.get(lord_id)
    if lord is None:
        return 0
    cmd = lord.command_rating
    caps = set(capabilities_for_lord(state, lord_id))
    # Mesnada: +1 with Knights.
    if (caps & {"C11", "C12"}) and lord.forces.get("knights", 0) > 0:
        cmd += 1
    # Hasham: +1 with any Horse.
    if (caps & {"M11", "M21"}) and _lord_has_horse(state, lord_id):
        cmd += 1
    return cmd
