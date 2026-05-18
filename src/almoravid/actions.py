"""Action dispatcher and Levy-phase handlers.

Architecture:

- `apply_action(state, action)` is the single entry point. Every state
  mutation goes through it. It validates, mutates, appends a
  HistoryEntry, and returns a result dict. Validation errors raise
  `IllegalAction` with a machine-readable `code` attribute.

- Handlers are named `_h_<action_name>`. Each handler:
    1. Validates side, phase, levy_step, and any action-specific
       preconditions. Cites the rule (Pattern 9 — every cited rule must
       actually validate).
    2. Mutates state in place.
    3. If it advances the step / passes the baton, calls
       `_advance_step_if_both_done` to keep active_player consistent
       (Pattern 11).
    4. Returns a result dict for the caller / history log.

Phase 2b scope: structural backbone + enough Levy handlers to drive a
scenario from setup through one Levy round end-to-end. Later phases
flesh out the per-card resolution, Call to Arms cascades, etc.
"""

from __future__ import annotations

from typing import Any, cast

from almoravid.rng import roll_d6, shuffle
from almoravid.state import (
    GameState,
    HistoryEntry,
    LevyStep,
    Side,
)
from almoravid.static_data import load_cards, load_lords


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IllegalAction(ValueError):
    """Raised when an action is rejected by validation.

    `code` is a machine-readable tag agents can branch on without
    parsing the message.
    """

    def __init__(self, message: str, *, code: str = "illegal") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------


# Default actor order per Sequence of Play §2 (Christian, then Muslim).
ACTOR_ORDER: tuple[Side, ...] = ("christian", "muslim")

# Sequence of Levy steps per SoP §3.1-3.5.
LEVY_STEPS: tuple[LevyStep, ...] = (
    "arts_of_war",
    "pay",
    "service_disband",
    "muster",
    "call_to_arms",
)


def _other(side: Side) -> Side:
    return "muslim" if side == "christian" else "christian"


def _require(condition: bool, message: str, code: str) -> None:
    if not condition:
        raise IllegalAction(message, code=code)


def _require_side(action: dict[str, Any]) -> Side:
    side = action.get("side")
    _require(side in ("christian", "muslim"),
             f"action missing or invalid 'side': {side!r}",
             code="bad_side")
    return cast(Side, side)


def _require_active(state: GameState, side: Side) -> None:
    _require(state.meta.active_player == side,
             f"not {side}'s turn — active_player is {state.meta.active_player}",
             code="not_active")


def _require_phase(state: GameState, phase: str) -> None:
    _require(state.meta.phase == phase,
             f"phase is {state.meta.phase}, expected {phase}",
             code="bad_phase")


def _require_levy_step(state: GameState, step: LevyStep) -> None:
    _require_phase(state, "levy")
    _require(state.meta.levy_step == step,
             f"levy_step is {state.meta.levy_step}, expected {step}",
             code="bad_levy_step")


def _set_step_completed(state: GameState, side: Side) -> None:
    if side == "christian":
        state.meta.levy_step_completed_christian = True
    else:
        state.meta.levy_step_completed_muslim = True


def _advance_step_if_both_done(state: GameState) -> None:
    """Pattern 11 (active-player desync): central baton-pass logic.

    If both sides have ratified the current step, advance to the next
    step (or finish the Levy phase) and reset per-side flags. Otherwise
    pass the baton to the other side.
    """
    if not (state.meta.levy_step_completed_christian
            and state.meta.levy_step_completed_muslim):
        # The side that just ratified hands the baton to the other side.
        state.meta.active_player = _other(state.meta.active_player)
        return

    # Both sides done with current step. Advance.
    current = state.meta.levy_step
    state.meta.levy_step_completed_christian = False
    state.meta.levy_step_completed_muslim = False
    if current is None or current == "done":
        state.meta.levy_step = "done"
        state.meta.phase = "campaign"  # Phase 3 hook
        state.meta.active_player = ACTOR_ORDER[0]
        return
    idx = LEVY_STEPS.index(current)
    if idx + 1 < len(LEVY_STEPS):
        state.meta.levy_step = LEVY_STEPS[idx + 1]
    else:
        state.meta.levy_step = "done"
        state.meta.phase = "campaign"
        state.meta.first_levy_done = True
    state.meta.active_player = ACTOR_ORDER[0]


def _record(state: GameState, action: dict[str, Any], summary: str) -> None:
    state.history.append(HistoryEntry(
        turn_index=state.meta.turn_index,
        actor=cast(Any, action.get("side", "system")),
        action=action.get("type", "?"),
        args={k: v for k, v in action.items() if k not in ("type", "side")},
        summary=summary,
    ))


# ---------------------------------------------------------------------------
# Lifecycle: begin_levy
# ---------------------------------------------------------------------------


def _h_begin_levy(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Transition from setup (or campaign) into the Levy phase (SoP §3).

    Anyone can call this once the game is in a state ready for Levy.
    """
    _require(state.meta.phase in ("setup", "campaign"),
             f"cannot begin Levy from phase {state.meta.phase}",
             code="bad_phase")
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.levy_step_completed_christian = False
    state.meta.levy_step_completed_muslim = False
    state.meta.active_player = ACTOR_ORDER[0]
    _record(state, action, "Begin Levy phase (3.1 arts_of_war)")
    return {"phase": "levy", "levy_step": "arts_of_war"}


def _h_pass_step(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Generic 'I'm done with this Levy step' ratification (SoP §3).

    Each side passes once per step. When both have passed, the step
    advances. This handler is the single source of step-transition
    logic — Pattern 1 (state-set-but-unreachable) is preempted by
    making every step transition reachable through this one action.
    """
    side = _require_side(action)
    _require_phase(state, "levy")
    _require_active(state, side)
    _set_step_completed(state, side)
    prev_step = state.meta.levy_step
    _advance_step_if_both_done(state)
    summary = f"{side} passes {prev_step}"
    if state.meta.levy_step != prev_step:
        summary += f"; step advances to {state.meta.levy_step}"
    _record(state, action, summary)
    return {"levy_step": state.meta.levy_step,
            "active_player": state.meta.active_player,
            "phase": state.meta.phase}


# ---------------------------------------------------------------------------
# 3.1 Arts of War
# ---------------------------------------------------------------------------


def _h_aow_shuffle(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Shuffle the Arts of War deck for the acting side (SoP §3.1)."""
    side = _require_side(action)
    _require_levy_step(state, "arts_of_war")
    _require_active(state, side)
    # Build a deck-by-side from cards.json if empty (first Levy bootstrap).
    cards = load_cards()["cards"]
    if not state.decks.draw:
        state.decks.draw = [cid for cid, c in cards.items() if c["side"] == side]
    state.decks.draw = shuffle(state, state.decks.draw)
    _record(state, action, f"{side} shuffles AoW deck ({len(state.decks.draw)} cards)")
    return {"deck_size": len(state.decks.draw)}


def _h_aow_draw(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Draw `n` cards from the AoW deck into `pending_draw` (SoP §3.1).

    The Lordship-of-each-Lord total dictates how many cards are drawn
    in normal play; for Phase 2b we accept an explicit `n` and trust
    legal_moves to constrain it later.
    """
    side = _require_side(action)
    _require_levy_step(state, "arts_of_war")
    _require_active(state, side)
    n = int(action.get("n", 1))
    _require(n >= 0, f"draw count must be >= 0, got {n}", code="bad_arg")
    _require(len(state.decks.draw) >= n,
             f"deck has {len(state.decks.draw)}, cannot draw {n}",
             code="deck_underflow")
    drawn = state.decks.draw[:n]
    state.decks.draw = state.decks.draw[n:]
    state.decks.pending_draw.setdefault(side, []).extend(drawn)
    _record(state, action, f"{side} draws {n}: {drawn}")
    return {"drawn": drawn, "deck_remaining": len(state.decks.draw)}


# ---------------------------------------------------------------------------
# 3.4 Muster (minimal viable implementation)
# ---------------------------------------------------------------------------


def _free_seats_for(state: GameState, lord_id: str) -> list[str]:
    """Seats that are neither Enemy nor have any Enemy Lord present
    (per Errata p.12 PROCEDURE bullet 1). Phase 2b applies a simplified
    'no enemy Lord present' check — territory-side enemy check is in
    Phase 3 once friendly_locale logic is wired.
    """
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


def _h_muster_lord(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Muster a Lord at one of his Seats (SoP §3.4).

    Phase 2b simplification: the Fealty die-roll is rolled here for
    Lords with a Fealty rating; Call-to-Arms-only Lords (Yusuf, Sir,
    Eudes, both Rodrigos — Fealty None) cannot be Mustered via this
    handler and must use the Call to Arms step in Phase 2b extended
    or Phase 4. Q-NNN candidate: Beyond-Service-only Lords and Fealty
    re-rolls (TBD).
    """
    side = _require_side(action)
    _require_levy_step(state, "muster")
    _require_active(state, side)
    lord_id = action.get("lord_id")
    _require(isinstance(lord_id, str), "lord_id required (str)", code="bad_arg")
    lord_id = cast(str, lord_id)
    _require(lord_id in state.lords, f"unknown lord {lord_id}", code="unknown_lord")
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} is not on {side}'s side", code="wrong_side")
    _require(lord.fealty is not None,
             f"{lord_id} has no Fealty — must use Call to Arms",
             code="cta_only_lord")
    _require(lord.cylinder.kind == "calendar",
             f"{lord_id} is not on the Calendar (cylinder.kind={lord.cylinder.kind})",
             code="not_on_calendar")
    free = _free_seats_for(state, lord_id)
    _require(free, f"{lord_id} has no free Seat to Muster at", code="no_free_seat")
    # Roll vs Fealty (rule 3.4)
    roll = roll_d6(state)
    success = roll <= cast(int, lord.fealty)
    if not success:
        _record(state, action,
                f"{lord_id} Muster failed: rolled {roll} > Fealty {lord.fealty}")
        return {"success": False, "roll": roll, "fealty": lord.fealty}

    # Success: place at chosen Seat (or default to first free Seat),
    # set starting forces / assets from static data, advance Service.
    seat = action.get("seat", free[0])
    _require(seat in free, f"{seat} is not a free Seat for {lord_id}", code="bad_seat")
    from almoravid.state import Cylinder
    lord.cylinder = Cylinder(kind="locale", locale_id=seat)
    static = load_lords()["lords"][lord_id]
    lord.forces = dict(static["forces"])
    lord.assets = dict(static["assets"])
    # Advance lord's Service marker: Service-rating boxes ahead from
    # current Levy/Campaign marker (rule 3.4.1). Implementation deferred
    # to Phase 3 alongside Calendar mutators.
    lord.just_arrived_this_levy = True
    _record(state, action,
            f"{lord_id} Mustered at {seat}: rolled {roll} <= Fealty {lord.fealty}")
    return {"success": True, "roll": roll, "seat": seat,
            "fealty": lord.fealty}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


_HANDLERS = {
    "begin_levy": _h_begin_levy,
    "pass_step": _h_pass_step,
    "aow_shuffle": _h_aow_shuffle,
    "aow_draw": _h_aow_draw,
    "muster_lord": _h_muster_lord,
}


def apply_action(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Single entry point for state mutation.

    Routes by `action["type"]` to a handler. Returns the handler's
    result dict. Raises IllegalAction on validation failure.
    """
    action_type = action.get("type")
    if action_type not in _HANDLERS:
        raise IllegalAction(
            f"unknown action type {action_type!r}. "
            f"Known: {sorted(_HANDLERS)}",
            code="unknown_action",
        )
    return _HANDLERS[action_type](state, action)
