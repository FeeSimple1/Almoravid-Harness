"""Legal-moves enumeration.

`legal_moves(state)` returns a list of action dicts that `apply_action`
would currently accept for the active player.

Bug-pattern invariant (Pattern 1 — state-set-but-unreachable):
  For any non-terminal state, legal_moves(state) is non-empty. The
  self-play smoke test in tests/test_legal_moves.py drives this:
  it walks through scenarios picking the first legal move each turn
  and asserts the loop terminates only at a terminal phase, never at
  zero-moves-mid-game.

Phase 2c scope mirrors Phase 2b: enumerates the actions that have
handlers in actions.py today. New handlers must add a corresponding
enumerator here in the same PR (otherwise the agent can't reach them).
"""

from __future__ import annotations

from typing import Any

from almoravid.state import GameState, Side


def legal_moves(state: GameState) -> list[dict[str, Any]]:
    """Return the list of currently-legal action dicts."""
    moves: list[dict[str, Any]] = []

    # Lifecycle: begin_levy when in setup or campaign.
    if state.meta.phase in ("setup", "campaign"):
        moves.append({"type": "begin_levy"})
        return moves

    if state.meta.phase != "levy":
        return moves  # ended / curias / winter — Phase 3+

    active: Side = state.meta.active_player
    step = state.meta.levy_step

    if step == "arts_of_war":
        moves.extend(_aow_moves(state, active))
    elif step == "pay":
        moves.extend(_pay_moves(state, active))
    elif step == "service_disband":
        moves.extend(_service_disband_moves(state, active))
    elif step == "muster":
        moves.extend(_muster_moves(state, active))
    elif step == "call_to_arms":
        moves.extend(_call_to_arms_moves(state, active))

    # pass_step is always legal for the active side during a Levy step.
    if step in ("arts_of_war", "pay", "service_disband", "muster", "call_to_arms"):
        moves.append({"type": "pass_step", "side": active})

    return moves


def _aow_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.1 Arts of War: shuffle the deck and/or draw cards."""
    out: list[dict[str, Any]] = []
    # Shuffle is always available (re-shuffle costs nothing structurally;
    # in real play a side shuffles before drawing once per Levy).
    out.append({"type": "aow_shuffle", "side": side})
    if state.decks.draw:
        # Allow draws of 1..min(deck, total_lordship). For Phase 2c we
        # expose draw counts 1..min(3, deck) so legal_moves stays small.
        max_n = min(3, len(state.decks.draw))
        for n in range(1, max_n + 1):
            out.append({"type": "aow_draw", "side": side, "n": n})
    return out


def _pay_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.2 Pay. Phase 2b has no payment handlers yet; pass_step only."""
    return []


def _service_disband_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.3 Service / Disband. Phase 2b: pass_step only (Disband logic
    lands in Phase 3 alongside Calendar shift mechanics)."""
    return []


def _muster_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.4 Muster: enumerate Lords with Fealty on Calendar with free Seats."""
    out: list[dict[str, Any]] = []
    for lid, lord in state.lords.items():
        if lord.side != side:
            continue
        if lord.fealty is None:
            continue  # CtA-only Lord
        if lord.cylinder.kind != "calendar":
            continue
        free = _free_seats_for(state, lid)
        if not free:
            continue
        for seat in free:
            out.append({
                "type": "muster_lord",
                "side": side,
                "lord_id": lid,
                "seat": seat,
            })
    return out


def _call_to_arms_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.5 Call to Arms. Phase 4 will populate (Yusuf/Sir/Eudes/Rodrigo)."""
    return []


def _free_seats_for(state: GameState, lord_id: str) -> list[str]:
    """Mirror of the Phase 2b helper. Kept private to avoid coupling."""
    lord = state.lords[lord_id]
    out = []
    for seat in lord.seats:
        enemy_present = any(
            other.cylinder.kind == "locale"
            and other.cylinder.locale_id == seat
            and other.side != lord.side
            for other in state.lords.values()
        )
        if not enemy_present:
            out.append(seat)
    return out
