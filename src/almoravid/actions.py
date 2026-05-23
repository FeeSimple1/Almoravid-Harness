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
    Lord,
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
        # Bug K (Pattern 13): when transitioning OUT of arts_of_war,
        # clear pending_draw — Phase 5j punted on per-card resolution
        # of drawn cards, so they accumulate forever unless we clear.
        # Treating Phase 5j leftover pending_draw cards as discard
        # is the conservative choice.
        if current == "arts_of_war":
            for side_key, cards in list(state.decks.pending_draw.items()):
                state.decks.discard.extend(cards)
            state.decks.pending_draw = {}
        state.meta.levy_step = LEVY_STEPS[idx + 1]
        # FIX-A (3.5): reset Call-to-Arms per-Levy bookkeeping on entry.
        if state.meta.levy_step == "call_to_arms":
            state.meta.cta_option_used_christian = False
            state.meta.cta_option_used_muslim = False
            state.meta.cta_crusade_jihad_pending = False
        state.meta.active_player = ACTOR_ORDER[0]
    else:
        # End of Levy -> enter Campaign / plan directly. Auto-initializing
        # campaign state here means legal_moves never sees the "campaign/
        # campaign_step=None" intermediate state that would otherwise need
        # begin_campaign to clean up — Pattern 1 (state-set-but-unreachable
        # at boundary).
        state.meta.levy_step = "done"
        state.meta.phase = "campaign"
        state.meta.campaign_step = "plan"
        state.meta.plan_finalized_christian = False
        state.meta.plan_finalized_muslim = False
        state.meta.plan_index_christian = 0
        state.meta.plan_index_muslim = 0
        state.meta.actions_remaining = 0
        state.meta.active_lord_id = None
        state.decks.plan = {"christian": [], "muslim": []}
        state.meta.first_levy_done = True
        state.meta.muster_banned_this_levy_lord_ids = []  # Phase 6d
        state.meta.active_player = ACTOR_ORDER[0]
        # Rule 5.2: entering the Campaign, a side with no Mustered Lords
        # on the map loses immediately (it also could not legally build a
        # Plan, 4.1.1/1.9.2). Check at this Levy->Campaign boundary.
        from almoravid.campaign import (check_campaign_victory,
                                          compute_victory,
                                          _apply_capability_discard)
        if check_campaign_victory(state) is not None:
            compute_victory(state)
            state.meta.phase = "ended"
        else:
            # 4.0 CAPABILITY DISCARD (Christian first, then Muslim).
            _apply_capability_discard(state)


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


def _h_bid_for_sides(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """6.1 Bidding for Sides (optional, setup only). Two players each bid
    (total pips of dice they hide); the LOWER bid takes the Muslim side
    and the number of 1VP markers in the Taifas box is reset to equal
    that bid. Ties reset to that number and assign sides randomly. The
    lowest allowed bid in Scenario F is 2.

    In this engine the two sides (Christian/Muslim) and their pieces are
    fixed; bidding's only mechanical effect on game state is resetting
    the Muslim Taifas-box VP (state.taifas_box_vp). The seat assignment
    (which player plays Muslim) is reported for the human players.

    Action args: bid1 (int>=0), bid2 (int>=0).
    """
    from almoravid.rng import roll_d6
    _require(state.meta.phase == "setup",
             "Bidding for Sides is a setup-time option (6.1)",
             code="wrong_phase")
    _require(not state.meta.bidding_done,
             "Bidding has already been done (6.1)", code="already_bid")
    b1 = action.get("bid1")
    b2 = action.get("bid2")
    _require(isinstance(b1, int) and isinstance(b2, int)
             and b1 >= 0 and b2 >= 0,
             "bid1 and bid2 must be non-negative ints", code="bad_arg")
    min_bid = 2 if state.meta.scenario_letter == "F" else 0
    _require(b1 >= min_bid and b2 >= min_bid,
             f"Scenario {state.meta.scenario_letter}: minimum bid is "
             f"{min_bid} (6.1)", code="bid_too_low")
    tie = (b1 == b2)
    if b1 < b2:
        muslim_player, winning = "player1", b1
    elif b2 < b1:
        muslim_player, winning = "player2", b2
    else:
        muslim_player = "player1" if roll_d6(state) <= 3 else "player2"
        winning = b1
    state.taifas_box_vp = float(winning)
    state.meta.bidding_done = True
    _record(state, action,
            f"Bidding (6.1): bids {b1}/{b2}; {muslim_player} plays Muslim; "
            f"Taifas-box VP reset to {winning}"
            + (" (tie, random sides)" if tie else ""))
    return {"muslim_player": muslim_player, "winning_bid": winning,
            "taifas_box_vp": state.taifas_box_vp, "tie": tie}


def _h_begin_levy(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Transition from setup (or campaign) into the Levy phase (SoP §3).

    Anyone can call this once the game is in a state ready for Levy.
    """
    _require(state.meta.phase == "setup",
             f"cannot begin Levy from phase {state.meta.phase}",
             code="bad_phase")
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.aow_draw_done = {}
    state.meta.levy_step_completed_christian = False
    state.meta.levy_step_completed_muslim = False
    state.meta.cta_option_used_christian = False
    state.meta.cta_option_used_muslim = False
    state.meta.cta_crusade_jihad_pending = False
    # Per-Levy reset (3.4.1): the "newly Mustered this segment" flag is
    # scoped to one Levy; clear it for all Lords at Levy start.
    for _l in state.lords.values():
        _l.just_arrived_this_levy = False
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
    # 3.3: Disband is mandatory for Lords at/beyond the Service limit —
    # a side may not pass the service_disband step while any of its
    # Lords still owe a Disband.
    if state.meta.levy_step == "service_disband":
        from almoravid.legal_moves import pending_mandatory_disbands
        pend = pending_mandatory_disbands(state, side)
        _require(not pend,
                 f"{side} must Disband {pend} before passing the "
                 f"service_disband step (3.3)", code="disband_pending")
    # 3.1.2/3.1.3: a side may not pass the Arts-of-War step until it has
    # drawn its two cards and processed (deployed/implemented) them.
    if state.meta.levy_step == "arts_of_war":
        _require(state.meta.aow_draw_done.get(side)
                 and not state.decks.pending_draw.get(side),
                 f"{side} must draw and process Arts of War before passing "
                 f"(3.1.2/3.1.3)", code="aow_draw_pending")
    # 3.4.2 advanced Vassal Service: the side's automatic Vassal Disband
    # happens as it completes the Disband step (3.3); Pennant flip-up
    # happens as it finishes its Muster segment (3.4).
    if state.meta.advanced_vassal_service:
        if state.meta.levy_step == "service_disband":
            _disband_vassals_for_side(state, side)
        elif state.meta.levy_step == "muster":
            _flip_up_pennants(state, side)
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


def aow_capability_phase(state: GameState) -> bool:
    """Whether the current Levy's Arts of War step draws/deploys
    Capabilities (3.1.2) rather than implementing Events (3.1.3).

    True on the very first Levy of the game, AND — per 6.3.5 — on the
    first Spring Levy after Winter (Calendar box 9) in Scenario F, when
    players draw Capabilities instead of Events to rebuild the loadout
    discarded during Winter Disband (6.3.1)."""
    if not state.meta.first_levy_done:
        return True
    if (state.meta.scenario_letter == "F"
            and state.calendar.current_box == 9):
        return True
    return False


def _h_aow_shuffle(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Shuffle the Arts of War deck for the acting side (SoP §3.1)."""
    side = _require_side(action)
    _require_levy_step(state, "arts_of_war")
    _require_active(state, side)
    n_excl = _rebuild_aow_deck(state, side)
    state.decks.draw = shuffle(state, state.decks.draw)
    _record(state, action,
            f"{side} shuffles AoW deck ({len(state.decks.draw)} cards; "
            f"{n_excl} excluded as held/in-play)")
    return {"deck_size": len(state.decks.draw)}


def _rebuild_aow_deck(state: GameState, side: str) -> int:
    """3.1.1: rebuild this side's draw deck = all of its cards EXCEPT
    Held Events, in-play Capabilities (board edge / mats), and cards
    pending implementation. Returns the excluded count. Recycles used
    immediate Events (in discard)."""
    cards = load_cards()["cards"]
    excluded: set[str] = set()
    for bucket in (state.decks.this_levy_events, state.decks.this_campaign_events,
                   state.decks.held):
        excluded.update(bucket.get(side, []))
    excluded.update(state.decks.board_edge.get(side, []))
    excluded.update(c.card_id for c in state.decks.capabilities_in_play
                    if c.owner_side == side)
    for l in state.lords.values():
        if l.side == side:
            excluded.update(l.capabilities)
    excluded.update(state.decks.pending_draw.get(side, []))
    state.decks.draw = [cid for cid, c in cards.items()
                        if c["side"] == side and cid not in excluded]
    return len(excluded)


def _h_aow_draw(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Draw `n` cards from the AoW deck into `pending_draw` (SoP §3.1).

    The Lordship-of-each-Lord total dictates how many cards are drawn
    in normal play; for Phase 2b we accept an explicit `n` and trust
    legal_moves to constrain it later.
    """
    side = _require_side(action)
    _require_levy_step(state, "arts_of_war")
    _require_active(state, side)
    _require(not state.meta.aow_draw_done.get(side),
             f"{side} has already drawn Arts of War this Levy (3.1.2/3.1.3)",
             code="already_drawn")
    # 3.1.1 + SoP (arts_of_war: shuffle THEN draw 2): each side draws from
    # ITS OWN deck (1.9.1 "Each side has its own deck"). decks.draw is a
    # single shared pile, so collect this side's unused cards and shuffle
    # before EVERY draw -- not only when the pile is empty. Otherwise, after
    # the Christian player draws, the Muslim player would draw the Christian
    # cards still sitting on the shared pile (3.1.1, 3.1.2/3.1.3). [P-1 playtest]
    _rebuild_aow_deck(state, side)
    state.decks.draw = shuffle(state, state.decks.draw)
    # Each side draws exactly TWO cards (or fewer only if the deck is
    # short). The count is fixed by rule, not chosen.
    n = min(2, len(state.decks.draw))
    drawn = state.decks.draw[:n]
    state.decks.draw = state.decks.draw[n:]
    state.decks.pending_draw.setdefault(side, []).extend(drawn)
    state.meta.aow_draw_done[side] = True
    _record(state, action, f"{side} draws {n}: {drawn}")
    return {"drawn": drawn, "deck_remaining": len(state.decks.draw)}


def _h_aow_deploy_capability(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.1.2 (first Levy): deploy a drawn Arts of War card as a
    Capability (lower half). side_wide -> tucked at the map edge
    (board_edge + capabilities_in_play); this_lord -> tucked under a
    chosen Mustered Lord's mat (lord.capabilities). A "This Lord" card
    that cannot be assigned to a Mustered Lord (or a card with no
    Capability half) adds no Capability and is discarded (3.1.2)."""
    from almoravid.state import CardInPlay
    side = _require_side(action)
    _require_levy_step(state, "arts_of_war")
    _require_active(state, side)
    _require(aow_capability_phase(state),
             "Capability deployment (3.1.2) is only for the first Levy "
             "(or the first Spring Levy after Winter, box 9, Scenario F, "
             "6.3.5); other Levies implement Events (3.1.3)",
             code="not_capability_phase")
    card_id = action.get("card_id")
    pend = state.decks.pending_draw.get(side, [])
    _require(card_id in pend, f"{card_id} not in {side} pending draw",
             code="not_pending")
    rec = load_cards()["cards"].get(card_id, {})
    scope = rec.get("capability_scope")
    deployed = None
    if rec.get("no_capability") or scope is None:
        state.decks.discard.append(card_id)        # no Capability half
    elif scope == "side_wide":
        state.decks.board_edge.setdefault(side, []).append(card_id)
        state.decks.capabilities_in_play.append(CardInPlay(
            card_id=card_id, scope="side_wide", owner_side=side,
            owner_lord_id=None))
        deployed = "side_wide"
    else:  # this_lord
        lord_id = action.get("lord_id")
        lord = state.lords.get(lord_id) if lord_id else None
        # 3.4.4 This-Lord limits also apply when deploying via 3.1.2:
        # a Lord at the cap (2) or already holding the same title cannot
        # receive it; such a card is discarded (no Capability assigned).
        _cap_ok = True
        if lord is not None:
            from almoravid.static_data import load_cards as _lc
            _nm = _lc()["cards"].get(card_id, {}).get("capability_name")
            _cap_ok = (_nm not in _this_lord_cap_titles(lord)
                       and len(lord.capabilities) < 2)
        if (lord is not None and lord.side == side
                and lord.cylinder.kind == "locale" and _cap_ok):
            lord.capabilities.append(card_id)
            state.decks.capabilities_in_play.append(CardInPlay(
                card_id=card_id, scope="this_lord", owner_side=side,
                owner_lord_id=lord_id))
            deployed = f"this_lord:{lord_id}"
        else:
            # Cannot assign to a Mustered Lord -> adds no Capability.
            state.decks.discard.append(card_id)
            deployed = "unassigned_discarded"
    state.decks.pending_draw[side] = [c for c in pend if c != card_id]
    _record(state, action,
            f"{side} deploys Capability {card_id} ({deployed}) (3.1.2)")
    return {"card_id": card_id, "deployed": deployed,
            "pending_remaining": list(state.decks.pending_draw[side])}


def _h_aow_implement_event(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.1.3 (second and later Levies): implement a drawn card's Event
    (upper half) in the order drawn. Immediate Events apply at once;
    "This Levy" and "Hold" Events are bucketed by their resolver. Cards
    must be implemented in draw order (FIFO)."""
    from almoravid.events import resolve_event
    side = _require_side(action)
    _require_levy_step(state, "arts_of_war")
    _require_active(state, side)
    _require(not aow_capability_phase(state),
             "Event implementation (3.1.3) applies on Levies that are not "
             "a Capability-draw phase (first Levy, or box-9 Spring after "
             "Winter in Scenario F, 6.3.5)",
             code="capability_phase_caps_only")
    pend = state.decks.pending_draw.get(side, [])
    _require(pend, f"no pending drawn cards for {side}", code="not_pending")
    card_id = action.get("card_id", pend[0])
    _require(card_id == pend[0],
             f"Events must be implemented in the order drawn (next: "
             f"{pend[0]})", code="out_of_order")
    res = resolve_event(state, side, card_id, action.get("payload"))
    # Remove from pending; the resolver routed the card (hold bucket,
    # this-levy bucket, or immediate apply+discard).
    state.decks.pending_draw[side] = pend[1:]
    _record(state, action, f"{side} implements Event {card_id} (3.1.3)")
    return {"card_id": card_id, "event_result": res,
            "pending_remaining": list(state.decks.pending_draw[side])}


# ---------------------------------------------------------------------------
# 3.4 Muster (minimal viable implementation)
# ---------------------------------------------------------------------------


def _free_seats_for(state: GameState, lord_id: str) -> list[str]:
    """Seats that are neither Enemy nor have any Enemy Lord present
    (Errata p.12, 3.4.1 PROCEDURE bullet 1: "one of his Seats that is
    neither Enemy nor has any Enemy Lord present").

    "Enemy" means the Seat's Locale is Friendly to the OTHER side
    (1.3.1); a Neutral Seat (e.g. a Parias Taifa) is NOT Enemy and so
    remains free for Muster.
    """
    from almoravid.effective import is_friendly_locale
    lord = state.lords[lord_id]
    other = "muslim" if lord.side == "christian" else "christian"
    out = []
    for seat in lord.seats:
        if seat not in state.locales:
            continue
        # Enemy Territory check (Errata): exclude Seats Friendly to the
        # enemy side (e.g. a Reconquista-Conquered Seat for a Muslim).
        if is_friendly_locale(state, seat, other):
            continue
        enemy_present = any(
            o.cylinder.kind == "locale"
            and o.cylinder.locale_id == seat
            and o.side != lord.side
            for o in state.lords.values()
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
    # Phase 6d: M16/M17 ban Muster of/by specified Lord for the Levy.
    _require(lord_id not in state.meta.muster_banned_this_levy_lord_ids,
             f"{lord_id} cannot Muster this Levy "
             f"(M16/M17 Revolt ban active)",
             code="muster_banned")
    # 3.4.1: a Levying Lord spends one point of his Lordship to enable
    # the roll (L9b). The Levying Lord must be on the map, eligible to
    # take Levy actions (Friendly + Unbesieged, 3.4), have spare
    # Lordship, and not have been newly Mustered this same segment
    # ("A Lord newly Mustered by another Lord cannot use his Lordship
    # that same segment"). Arts-of-War auto-Muster cards bypass this via
    # their own handlers, not muster_lord.
    levying_lord_id = action.get("levying_lord_id")
    _require(levying_lord_id in state.lords,
             "levying_lord_id required — a Lord must spend Lordship to "
             "Muster another (3.4.1)", code="bad_arg")
    levier = state.lords[levying_lord_id]
    _require(levier.side == side,
             f"{levying_lord_id} is not on {side}'s side", code="wrong_side")
    _require(not levier.just_arrived_this_levy,
             f"{levying_lord_id} was newly Mustered this segment and cannot "
             f"use Lordship now (3.4.1)", code="levier_just_arrived")
    _require_levy_actor_eligible(state, levier, levying_lord_id)
    _require(levier.lordship_used < levier.lordship_rating,
             f"{levying_lord_id} has no Lordship left "
             f"({levier.lordship_used}/{levier.lordship_rating})",
             code="lordship_exhausted")
    _require(lord.cylinder.kind == "calendar",
             f"{lord_id} is not on the Calendar (cylinder.kind={lord.cylinder.kind})",
             code="not_on_calendar")
    # 3.4.1: the rolling Lord must be Ready — cylinder in a 40-Days box
    # at or LEFT of the Levy marker (box <= current_box).
    cyl_box = lord.cylinder.box
    _require(cyl_box is None or cyl_box <= state.calendar.current_box,
             f"{lord_id} is not Ready (cylinder box {cyl_box} is right of "
             f"the Levy marker {state.calendar.current_box}, 3.4.1)",
             code="not_ready")
    free = _free_seats_for(state, lord_id)
    _require(free, f"{lord_id} has no free Seat to Muster at", code="no_free_seat")
    # 3.4.1: spend the Levying Lord's Lordship point for this attempt
    # (whether or not the roll succeeds; a failed roll may be retried by
    # spending more Lordship).
    levier.lordship_used += 1
    # Roll vs Fealty (rule 3.4)
    roll = roll_d6(state)
    success = roll <= cast(int, lord.fealty)
    if not success:
        _record(state, action,
                f"{lord_id} Muster failed: rolled {roll} > Fealty "
                f"{lord.fealty} ({levying_lord_id} spent 1 Lordship)")
        return {"success": False, "roll": roll, "fealty": lord.fealty,
                "levying_lord_id": levying_lord_id}

    # Success: place at chosen Seat (or default to first free Seat),
    # set starting forces / assets from static data, advance Service.
    seat = action.get("seat", free[0])
    _require(seat in free, f"{seat} is not a free Seat for {lord_id}", code="bad_seat")
    from almoravid.state import Cylinder
    lord.cylinder = Cylinder(kind="locale", locale_id=seat)
    static = load_lords()["lords"][lord_id]
    lord.forces = dict(static["forces"])
    lord.assets = dict(static["assets"])
    # 3.4.1: place the Lord's own Service marker service_rating boxes
    # RIGHT (ahead) of the current Levy marker; cap at the 17+ box.
    from almoravid.state import ServiceMarker
    state.calendar.service_markers = [
        s for s in state.calendar.service_markers
        if not (s.lord_id == lord_id and s.vassal_id is None)
    ]
    svc_box = min(17, state.calendar.current_box + lord.service_rating)
    state.calendar.service_markers.append(
        ServiceMarker(lord_id=lord_id, box=svc_box))
    lord.just_arrived_this_levy = True
    # 3.4.1 TAIFA POLITICS: Mustering a Taifa Lord adjusts his Taifa to
    # Independent (1.4.3).
    taifa_adjust = None
    if lord.is_taifa and lord.home_taifa:
        from almoravid.campaign import adjust_taifa_status
        taifa_adjust = adjust_taifa_status(state, lord.home_taifa, "independent")
    _record(state, action,
            f"{lord_id} Mustered at {seat}: rolled {roll} <= Fealty "
            f"{lord.fealty}; Service marker -> box {svc_box}")
    return {"success": True, "roll": roll, "seat": seat,
            "service_box": svc_box, "taifa_adjust": taifa_adjust,
            "fealty": lord.fealty, "levying_lord_id": levying_lord_id}


# ---------------------------------------------------------------------------
# 3.5 Call to Arms (FIX-A / finding L2)
#
# After Lords already in the field Muster, each side may call MORE Lords
# to war (3.5). The Christians act first (3.5.1), then the Muslims
# (3.5.2). Each side may "do nothing OR ONE of the following" options;
# `cta_option_used_{side}` enforces the one-option-per-side limit. The
# only way to put Yusuf, Sir, Eudes, or either Rodrigo into play is via
# this step (Rules p.14 "Important"). Per the absolute-faithfulness
# rule, every player choice (which Stronghold to Seat at, which Lords
# pay Coin, which Lord to Invite, Muster-vs-shift, Jihad target) is an
# explicit action parameter — no greedy defaults.
# ---------------------------------------------------------------------------

_STRONGHOLD_TYPES = ("city", "fortress", "town", "castle")


def _cta_is_ready(state: GameState, lord) -> bool:
    """3.4.1 Ready: cylinder on the Calendar at or LEFT of the Levy
    marker (box <= current_box). Off-left (box None) also counts."""
    return (lord.cylinder.kind == "calendar"
            and (lord.cylinder.box is None
                 or lord.cylinder.box <= state.calendar.current_box))


def _cta_require_turn(state: GameState, side: Side) -> None:
    _require_levy_step(state, "call_to_arms")
    _require_active(state, side)
    used = (state.meta.cta_option_used_christian if side == "christian"
            else state.meta.cta_option_used_muslim)
    _require(not used,
             f"{side} already took a Call to Arms option this Levy (3.5)",
             code="cta_used")


def _cta_finish_option(state: GameState, side: Side) -> None:
    """Record that `side` used its single 3.5 option, ratify the step
    for that side, and advance the baton. A side that takes ANY option
    is then done with Call to Arms (it may not take a second)."""
    if side == "christian":
        state.meta.cta_option_used_christian = True
    else:
        state.meta.cta_option_used_muslim = True
    _set_step_completed(state, side)
    _advance_step_if_both_done(state)


def _cta_locale_free_of_siege(state: GameState, locale_id: str) -> bool:
    loc = state.locales[locale_id]
    return loc.siege_yellow == 0 and loc.siege_green == 0


def _cta_seat_has_enemy_lord(state: GameState, locale_id: str,
                             side: Side) -> bool:
    """3.4.1: a Muster Seat must be "neither Enemy nor has any Enemy Lords
    present". Returns True if any Lord of the other side is at the Locale
    (same test as the normal-Muster _free_seats_for helper, so the CtA
    auto-Muster paths stay consistent with 3.4.1 Muster). [P-5 playtest]"""
    return any(
        l.cylinder.kind == "locale" and l.cylinder.locale_id == locale_id
        and l.side != side
        for l in state.lords.values()
    )


def _cta_auto_muster(state: GameState, lord_id: str, seat: str) -> dict[str, Any]:
    """Automatically Muster `lord_id` at `seat` (no Fealty roll) per the
    3.5 Call-to-Arms option that triggered it. Mirrors the success
    branch of _h_muster_lord: place forces/assets from static data,
    place the Service marker service_rating boxes ahead (cap 17), set
    just_arrived. Taifa Lords adjust their Taifa to Independent (3.4.1).
    """
    from almoravid.state import Cylinder, ServiceMarker
    lord = state.lords[lord_id]
    # 3.4.1: place the cylinder at a Seat "neither Enemy nor has any Enemy
    # Lords present". CtA auto-Muster must obey the usual Muster rule
    # (3.4.1 ARTS OF WAR "must otherwise still Muster by the usual rules"),
    # otherwise a Lord could Muster into an Enemy-occupied Locale and sit
    # there co-located -- an illegal, unresolvable board state. [P-5]
    _require(not _cta_seat_has_enemy_lord(state, seat, lord.side),
             f"{seat} has an Enemy Lord present — cannot Muster there "
             f"(3.4.1)", code="enemy_lord_present")
    lord.cylinder = Cylinder(kind="locale", locale_id=seat)
    static = load_lords()["lords"][lord_id]
    lord.forces = dict(static["forces"])
    lord.assets = dict(static["assets"])
    state.calendar.service_markers = [
        s for s in state.calendar.service_markers
        if not (s.lord_id == lord_id and s.vassal_id is None)
    ]
    svc_box = min(17, state.calendar.current_box + lord.service_rating)
    state.calendar.service_markers.append(
        ServiceMarker(lord_id=lord_id, box=svc_box))
    lord.just_arrived_this_levy = True
    taifa_adjust = None
    if lord.is_taifa and lord.home_taifa:
        from almoravid.campaign import adjust_taifa_status
        taifa_adjust = adjust_taifa_status(state, lord.home_taifa, "independent")
    return {"mustered_at": seat, "service_box": svc_box,
            "taifa_adjust": taifa_adjust}


def _cta_move_seat_marker(state: GameState, lord_id: str, seat: str) -> None:
    """Move a movable Seat marker (Rodrigo's, or Yusuf/Sir's single
    Seat) to `seat`, removing it from wherever it currently sits.
    A Stronghold with that Seat becomes Friendly to the Lord's side
    (1.8)."""
    for loc in state.locales.values():
        if lord_id in loc.seat_marker_lord_ids:
            loc.seat_marker_lord_ids.remove(lord_id)
    if lord_id not in state.locales[seat].seat_marker_lord_ids:
        state.locales[seat].seat_marker_lord_ids.append(lord_id)


def _cta_collect_payment(state: GameState, side: Side, payments: list,
                         required: int, *, allow_taifa_box: bool) -> None:
    """Validate and remove a total of `required` Coin per a list of
    explicit payment entries (no greedy auto-pick).

    Each entry is {"lord_id": <id>, "coin": <n>} (Coin from an
    Unbesieged Lord of `side`) or, when allow_taifa_box, {"taifa_box":
    <n>} (Coin from the Taifas box). Raises on any shortfall or
    ineligible payer; mutates nothing until all checks pass.
    """
    from almoravid.effective import is_besieged
    _require(isinstance(payments, list) and payments,
             "payments list required (explicit Coin sources, 3.5)",
             code="bad_arg")
    total = 0
    plan: list[tuple] = []  # (kind, lord_id_or_None, amount)
    taifa_amt = 0
    for entry in payments:
        _require(isinstance(entry, dict), "payment entry must be a dict",
                 code="bad_arg")
        if "taifa_box" in entry:
            _require(allow_taifa_box,
                     "Taifas-box Coin not allowed for this option",
                     code="bad_arg")
            amt = int(entry["taifa_box"])
            _require(amt >= 1, "taifa_box coin must be >= 1", code="bad_arg")
            taifa_amt += amt
            total += amt
            plan.append(("taifa", None, amt))
        else:
            plid = entry.get("lord_id")
            _require(plid in state.lords, "payment lord_id required (str)",
                     code="bad_arg")
            amt = int(entry.get("coin", 0))
            _require(amt >= 1, "coin amount must be >= 1", code="bad_arg")
            payer = state.lords[plid]
            _require(payer.side == side,
                     f"{plid} is not on {side}'s side (3.5 payment)",
                     code="wrong_side")
            _require(not is_besieged(state, plid),
                     f"{plid} is Besieged — cannot contribute Coin (3.5)",
                     code="besieged")
            have = payer.assets.get("coin", 0)
            _require(have >= amt,
                     f"{plid} has {have} Coin, payment claims {amt}",
                     code="no_coin")
            total += amt
            plan.append(("lord", plid, amt))
    _require(total == required,
             f"payments total {total} Coin, need exactly {required} (3.5)",
             code="bad_payment_total")
    _require(taifa_amt <= state.taifas_box_coin,
             f"Taifas box has {state.taifas_box_coin} Coin, "
             f"payment claims {taifa_amt}", code="no_coin")
    # All validated — apply.
    for kind, plid, amt in plan:
        if kind == "taifa":
            state.taifas_box_coin -= amt
        else:
            payer = state.lords[plid]
            payer.assets["coin"] = payer.assets.get("coin", 0) - amt
            if payer.assets["coin"] == 0:
                payer.assets.pop("coin", None)


# ----- 3.5.1 Christian options ---------------------------------------------


def _h_cta_reconcile_rodrigo(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.5.1 Reconcile with Rodrigo. Available if Rodrigo al-Sayyid
    (green) is on the map OR Disband/combat has permanently removed any
    Christian Lord (3.3.1, 4.4.4, 4.5.2).

    Effect: add to the Taifas box (Muslim VP) one green 1VP Conquered
    marker PLUS 1VP per Calendar box that al-Sayyid's Service marker is
    ahead of the current Levy. Disband al-Sayyid (if on map) and set his
    green cylinder + Seat aside; place Rodrigo Campeador's yellow
    cylinder onto the Calendar two boxes ahead of the current Levy.
    """
    side = _require_side(action)
    _require(side == "christian", "Reconcile is a Christian option (3.5.1)",
             code="wrong_side")
    _cta_require_turn(state, side)
    from almoravid.state import Cylinder
    sayyid = state.lords["rodrigo_al_sayyid"]
    campeador = state.lords["rodrigo_campeador"]
    sayyid_on_map = sayyid.cylinder.kind == "locale"
    christian_removed = any(
        l.side == "christian" and l.cylinder.kind == "removed"
        for l in state.lords.values())
    _require(sayyid_on_map or christian_removed,
             "Reconcile needs al-Sayyid on the map OR a permanently "
             "removed Christian Lord (3.5.1)", code="cta_unavailable")
    # VP: 1 (Conquered marker) + boxes al-Sayyid's Service is ahead.
    sm = next((s for s in state.calendar.service_markers
               if s.lord_id == "rodrigo_al_sayyid" and s.vassal_id is None),
              None)
    ahead = max(0, sm.box - state.calendar.current_box) if sm is not None else 0
    vp = 1.0 + float(ahead)
    state.taifas_box_vp += vp
    state.score.muslim += vp
    # Disband al-Sayyid if on the map: clear his pieces, set cylinder
    # aside, remove his Service marker and Seat marker.
    if sayyid_on_map:
        for field_name in sayyid.cleanup_on_removal_fields:
            try:
                setattr(sayyid, field_name,
                        type(getattr(sayyid, field_name))())
            except Exception:
                pass
    sayyid.cylinder = Cylinder(kind="set_aside")
    state.calendar.service_markers = [
        s for s in state.calendar.service_markers
        if s.lord_id != "rodrigo_al_sayyid"]
    if "rodrigo_al_sayyid" in state.calendar.off_left_service:
        state.calendar.off_left_service.remove("rodrigo_al_sayyid")
    for loc in state.locales.values():
        if "rodrigo_al_sayyid" in loc.seat_marker_lord_ids:
            loc.seat_marker_lord_ids.remove("rodrigo_al_sayyid")
    # Place Campeador's yellow cylinder on the Calendar two boxes ahead.
    box = min(16, state.calendar.current_box + 2)
    campeador.cylinder = Cylinder(kind="calendar", box=box)
    _record(state, action,
            f"Christian Reconciles Rodrigo: +{vp:g} VP to Taifas box; "
            f"al-Sayyid set aside; Campeador onto Calendar box {box}")
    result = {"vp_to_taifas_box": vp, "campeador_calendar_box": box,
              "sayyid_was_on_map": sayyid_on_map}
    _cta_finish_option(state, side)
    return result


def _h_cta_employ_rodrigo(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.5.1 / 3.5.2 Employ Rodrigo. Christian employs Campeador (yellow,
    pay 2 Coin from Unbesieged Christian Lords); Muslim employs al-Sayyid
    (green, pay 3 Coin from the Taifas box and/or Unbesieged Muslim
    Lords). The relevant Rodrigo must be Ready (3.4.1). Move his Seat
    marker to a Friendly Stronghold free of Siege and auto-Muster him
    there.

    Args:
      side, seat (locale_id), payments (list of Coin sources, 3.5).
    """
    side = _require_side(action)
    _cta_require_turn(state, side)
    if side == "christian":
        rod_id, required, allow_taifa = "rodrigo_campeador", 2, False
    else:
        rod_id, required, allow_taifa = "rodrigo_al_sayyid", 3, True
    rod = state.lords[rod_id]
    _require(_cta_is_ready(state, rod),
             f"{rod_id} is not Ready (3.4.1) — cannot Employ", code="not_ready")
    from almoravid.effective import is_friendly_locale
    seat = action.get("seat")
    _require(seat in state.locales, "seat (locale_id) required", code="bad_arg")
    loc = state.locales[seat]
    _require(loc.base_type in _STRONGHOLD_TYPES,
             f"{seat} is not a Stronghold (3.5)", code="not_stronghold")
    _require(is_friendly_locale(state, seat, side),
             f"{seat} is not Friendly to {side} (3.5)", code="not_friendly")
    _require(_cta_locale_free_of_siege(state, seat),
             f"{seat} is not free of Siege (3.5)", code="under_siege")
    # 3.4.1: the Muster Seat must have no Enemy Lord present. Check before
    # collecting payment so a rejected Employ does not charge Coin. [P-5]
    _require(not _cta_seat_has_enemy_lord(state, seat, side),
             f"{seat} has an Enemy Lord present — cannot Muster there "
             f"(3.4.1)", code="enemy_lord_present")
    # Pay first (validates fully before any mutation), then place Seat
    # and auto-Muster.
    _cta_collect_payment(state, side, action.get("payments", []),
                         required, allow_taifa_box=allow_taifa)
    _cta_move_seat_marker(state, rod_id, seat)
    muster = _cta_auto_muster(state, rod_id, seat)
    _record(state, action,
            f"{side} Employs {rod_id}: paid {required} Coin; Seat -> "
            f"{seat}; auto-Mustered (Service box {muster['service_box']})")
    result = {"lord_id": rod_id, "seat": seat, "coin_paid": required, **muster}
    _cta_finish_option(state, side)
    return result


def _h_cta_call_crusade(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.5.1 Call for Crusade. If Eudes is Ready and Pamplona is
    Christian-Friendly and free of Siege, automatically Muster Eudes at
    Pamplona. The Muslim player MAY then add one Jihad marker (resolved
    as a separate optional action during the Muslim 3.5.2 sub-turn —
    flagged here via cta_crusade_jihad_pending).
    """
    side = _require_side(action)
    _require(side == "christian", "Call for Crusade is Christian (3.5.1)",
             code="wrong_side")
    _cta_require_turn(state, side)
    eudes = state.lords["eudes"]
    _require(_cta_is_ready(state, eudes),
             "Eudes is not Ready (3.4.1) — cannot Call for Crusade",
             code="not_ready")
    from almoravid.effective import is_friendly_locale
    _require(is_friendly_locale(state, "pamplona", "christian"),
             "Pamplona is not Christian-Friendly (3.5.1)", code="not_friendly")
    _require(_cta_locale_free_of_siege(state, "pamplona"),
             "Pamplona is not free of Siege (3.5.1)", code="under_siege")
    muster = _cta_auto_muster(state, "eudes", "pamplona")
    # Muslim MAY add one Jihad marker (1.4.4) — resolved on their turn.
    state.meta.cta_crusade_jihad_pending = True
    _record(state, action,
            f"Christian Calls for Crusade: Eudes auto-Mustered at "
            f"Pamplona (Service box {muster['service_box']}); Muslim may "
            f"add one Jihad marker")
    result = {"lord_id": "eudes", **muster, "muslim_jihad_pending": True}
    _cta_finish_option(state, side)
    return result


# ----- 3.5.2 Muslim options ------------------------------------------------


def _h_cta_invite_almoravids(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.5.2 Invite the Almoravids. If Yusuf or Sir is Ready, place the
    single Seat marker for the chosen one at Algeciras and auto-Muster
    him there. If Algeciras is not Muslim-Friendly or is Besieged, use
    the nearest Port that is Friendly and free of Siege. Then, if Eudes
    is not already on the Calendar or Mustered, place his cylinder onto
    the Calendar two boxes ahead.

    Args:
      side ('muslim'), lord_id ('yusuf' | 'sir').
    """
    side = _require_side(action)
    _require(side == "muslim", "Invite the Almoravids is Muslim (3.5.2)",
             code="wrong_side")
    _cta_require_turn(state, side)
    lord_id = action.get("lord_id")
    _require(lord_id in ("yusuf", "sir"),
             "lord_id must be 'yusuf' or 'sir' (3.5.2)", code="bad_arg")
    lord = state.lords[lord_id]
    _require(_cta_is_ready(state, lord),
             f"{lord_id} is not Ready (3.4.1) — cannot Invite", code="not_ready")
    from almoravid.effective import is_friendly_locale
    from almoravid.map import nearest_ports
    # Algeciras unless not Friendly / Besieged, then nearest qualifying Port.
    seat = None
    if (is_friendly_locale(state, "algeciras", "muslim")
            and _cta_locale_free_of_siege(state, "algeciras")
            and not _cta_seat_has_enemy_lord(state, "algeciras", "muslim")):
        seat = "algeciras"
    else:
        for port, _dist in nearest_ports("algeciras"):
            if port == "algeciras":
                continue
            if (is_friendly_locale(state, port, "muslim")
                    and _cta_locale_free_of_siege(state, port)
                    and not _cta_seat_has_enemy_lord(state, port, "muslim")):
                seat = port
                break
    _require(seat is not None,
             "no Muslim-Friendly Port free of Siege to Invite at (3.5.2)",
             code="no_port")
    _cta_move_seat_marker(state, lord_id, seat)
    muster = _cta_auto_muster(state, lord_id, seat)
    # Place Eudes onto the Calendar two boxes ahead if not already on
    # the Calendar or Mustered.
    eudes = state.lords["eudes"]
    eudes_placed = None
    if eudes.cylinder.kind not in ("calendar", "locale"):
        from almoravid.state import Cylinder
        box = min(16, state.calendar.current_box + 2)
        eudes.cylinder = Cylinder(kind="calendar", box=box)
        eudes_placed = box
    _record(state, action,
            f"Muslim Invites {lord_id} at {seat} (auto-Mustered, Service "
            f"box {muster['service_box']})"
            + (f"; Eudes onto Calendar box {eudes_placed}"
               if eudes_placed is not None else ""))
    result = {"lord_id": lord_id, "seat": seat,
              "eudes_calendar_box": eudes_placed, **muster}
    _cta_finish_option(state, side)
    return result


def _h_cta_uphold_dynasties(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.5.2 Uphold the Dynasties. If both Yusuf and Sir are Ready
    (cylinders on the Calendar at or left of current Levy), shift both
    cylinders into the 40-Days box just right of the current Levy box,
    to add one green 1VP Conquered marker to the Taifas box and one
    Jihad marker to the map (if able, 1.4.4).

    Args:
      side ('muslim'), jihad_locale (locale_id; required if a Jihad-
        eligible Locale exists).
    """
    side = _require_side(action)
    _require(side == "muslim", "Uphold the Dynasties is Muslim (3.5.2)",
             code="wrong_side")
    _cta_require_turn(state, side)
    yusuf = state.lords["yusuf"]
    sir = state.lords["sir"]
    for lid, l in (("yusuf", yusuf), ("sir", sir)):
        _require(l.cylinder.kind == "calendar"
                 and l.cylinder.box is not None
                 and l.cylinder.box <= state.calendar.current_box,
                 f"{lid} is not Ready on the Calendar (3.5.2)",
                 code="not_ready")
    from almoravid.events import _jihad_eligible_locales
    from almoravid.state import Cylinder
    box = min(16, state.calendar.current_box + 1)
    yusuf.cylinder = Cylinder(kind="calendar", box=box)
    sir.cylinder = Cylinder(kind="calendar", box=box)
    state.taifas_box_vp += 1.0
    state.score.muslim += 1.0
    # One Jihad marker, if able.
    eligible = _jihad_eligible_locales(state)
    jihad_locale = action.get("jihad_locale")
    placed = None
    if eligible:
        _require(jihad_locale in eligible,
                 f"jihad_locale must be a Jihad-eligible Locale "
                 f"{eligible} (3.5.2/1.4.4)", code="bad_jihad_target")
        state.locales[jihad_locale].jihad_markers += 1
        placed = jihad_locale
    _record(state, action,
            f"Muslim Upholds the Dynasties: Yusuf+Sir -> Calendar box "
            f"{box}; +1 VP to Taifas box"
            + (f"; +1 Jihad at {placed}" if placed else "; no Jihad (none able)"))
    result = {"calendar_box": box, "vp_to_taifas_box": 1.0,
              "jihad_locale": placed}
    _cta_finish_option(state, side)
    return result


def _h_cta_call_emir(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.5.2 Call upon an Emir. If Yusuf is at a Taifa Lord's Seat
    (1.5.1) that is neither Enemy nor Besieged, either Muster that Taifa
    Lord from any box on the Calendar automatically (no Fealty roll) OR
    shift that Taifa Lord's Service rightward by two boxes.

    Args:
      side ('muslim'), taifa_lord_id, mode ('muster' | 'shift'),
      seat (locale_id; required for mode='muster').
    """
    side = _require_side(action)
    _require(side == "muslim", "Call upon an Emir is Muslim (3.5.2)",
             code="wrong_side")
    _cta_require_turn(state, side)
    from almoravid.effective import is_friendly_locale, is_besieged
    yusuf = state.lords["yusuf"]
    _require(yusuf.cylinder.kind == "locale",
             "Yusuf is not on the map (3.5.2)", code="not_on_map")
    here = yusuf.cylinder.locale_id
    # Yusuf must be at a Taifa Lord's (printed) Seat.
    taifa_lord_id = action.get("taifa_lord_id")
    _require(taifa_lord_id in state.lords, "taifa_lord_id required",
             code="bad_arg")
    tlord = state.lords[taifa_lord_id]
    _require(tlord.is_taifa, f"{taifa_lord_id} is not a Taifa Lord (3.5.2)",
             code="not_taifa_lord")
    _require(here in tlord.seats,
             f"Yusuf ({here}) is not at {taifa_lord_id}'s Seat (3.5.2)",
             code="not_at_seat")
    # The Seat Locale must be neither Enemy nor Besieged.
    _require(is_friendly_locale(state, here, "muslim"),
             f"{here} is Enemy to the Muslims (3.5.2)", code="enemy_locale")
    _require(loc_unbesieged := _cta_locale_free_of_siege(state, here),
             f"{here} is Besieged (3.5.2)", code="under_siege")
    mode = action.get("mode")
    _require(mode in ("muster", "shift"),
             "mode must be 'muster' or 'shift' (3.5.2)", code="bad_arg")
    if mode == "muster":
        _require(tlord.cylinder.kind == "calendar",
                 f"{taifa_lord_id} is not on the Calendar to Muster (3.5.2)",
                 code="not_on_calendar")
        seat = action.get("seat")
        free = _free_seats_for(state, taifa_lord_id)
        _require(seat in free,
                 f"seat must be a free Seat of {taifa_lord_id}: {free}",
                 code="bad_seat")
        muster = _cta_auto_muster(state, taifa_lord_id, seat)
        _record(state, action,
                f"Muslim Calls upon Emir {taifa_lord_id}: auto-Mustered at "
                f"{seat} (Service box {muster['service_box']})")
        result = {"taifa_lord_id": taifa_lord_id, "mode": "muster", **muster}
    else:
        # Shift only applies to a Taifa Lord already in play (has a
        # Service marker); a not-yet-Mustered Lord uses 'muster'.
        has_marker = any(sm.lord_id == taifa_lord_id and sm.vassal_id is None
                         for sm in state.calendar.service_markers)
        _require(has_marker,
                 f"{taifa_lord_id} has no Service marker to shift — "
                 f"use mode='muster' (3.5.2)", code="no_service_marker")
        new_box = _shift_service_right(state, taifa_lord_id, boxes=2)
        _record(state, action,
                f"Muslim Calls upon Emir {taifa_lord_id}: Service shifted "
                f"+2 -> box {new_box}")
        result = {"taifa_lord_id": taifa_lord_id, "mode": "shift",
                  "service_box": new_box}
    _cta_finish_option(state, side)
    return result


def _h_cta_add_crusade_jihad(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.5.1 follow-up: after the Christians Call for Crusade, the
    Muslim player MAY add one Jihad marker (1.4.4). This is a SEPARATE
    optional action that does NOT consume the Muslim's own 3.5.2 option.

    Args:
      side ('muslim'), jihad_locale (locale_id, must be eligible).
    """
    side = _require_side(action)
    _require(side == "muslim", "Crusade-Jihad add is Muslim", code="wrong_side")
    _require_levy_step(state, "call_to_arms")
    _require_active(state, side)
    _require(state.meta.cta_crusade_jihad_pending,
             "no pending Crusade Jihad to add (3.5.1)", code="no_pending")
    from almoravid.events import _jihad_eligible_locales
    eligible = _jihad_eligible_locales(state)
    _require(bool(eligible), "no Jihad-eligible Locale (1.4.4)",
             code="no_jihad_target")
    jihad_locale = action.get("jihad_locale")
    _require(jihad_locale in eligible,
             f"jihad_locale must be eligible {eligible} (1.4.4)",
             code="bad_jihad_target")
    state.locales[jihad_locale].jihad_markers += 1
    state.meta.cta_crusade_jihad_pending = False
    _record(state, action,
            f"Muslim adds one Crusade Jihad marker at {jihad_locale} (3.5.1)")
    return {"jihad_locale": jihad_locale,
            "new_jihad_total": state.locales[jihad_locale].jihad_markers}



# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------









def _shift_service_left(state: GameState, lord_id: str, boxes: int = 1) -> int:
    """Shift a Lord's Service marker N boxes left (toward Disband).

    Pattern 6 (off-edge): box can land at 0 (off_left_service). Per
    rule, off-Calendar Service markers transition to off_left_service.
    Multi-box shifts that would go below 0 are clamped at 0.

    Returns the new box position (0..16, where 0 means off-left).
    """
    # Phase 7d: advanced Vassal Service (3.4.2) — Lord Service shifts
    # cascade to that Lord's Vassal Service markers by the same boxes.
    if state.meta.advanced_vassal_service:
        for vm in list(state.calendar.service_markers):
            if vm.lord_id == lord_id and vm.vassal_id is not None:
                vm.box = max(0, vm.box - boxes)
        # Drop Vassal markers that hit off-left.
        state.calendar.service_markers = [
            s for s in state.calendar.service_markers
            if not (s.lord_id == lord_id and s.vassal_id is not None
                    and s.box <= 0)
        ]

    # The Lord's OWN Service marker has vassal_id is None.
    sm = next((s for s in state.calendar.service_markers
               if s.lord_id == lord_id and s.vassal_id is None), None)
    if sm is None:
        # Already off-edge or no marker — append to off_left_service if not present
        if lord_id not in state.calendar.off_left_service:
            state.calendar.off_left_service.append(lord_id)
        return 0
    new_box = sm.box - boxes
    if new_box <= 0:
        # Goes off-left (remove only the Lord's own marker, not Vassals')
        state.calendar.service_markers = [
            s for s in state.calendar.service_markers
            if not (s.lord_id == lord_id and s.vassal_id is None)
        ]
        if lord_id not in state.calendar.off_left_service:
            state.calendar.off_left_service.append(lord_id)
        return 0
    sm.box = new_box
    return new_box

def _shift_service_right(state: GameState, lord_id: str, boxes: int = 1) -> int:
    """Shift a Lord's Service marker N boxes right (ahead / away from
    Disband), per Pay (3.2). Box caps at 17 (the "17+" box). If the
    marker was off-left, it re-enters at box `boxes` from box 0.
    Returns the new box (1..17)."""
    # 3.4.2: a Lord's Service shift (any direction, any reason) cascades
    # to that Lord's Vassal Service markers by the same number of boxes.
    if state.meta.advanced_vassal_service:
        for vm in state.calendar.service_markers:
            if vm.lord_id == lord_id and vm.vassal_id is not None:
                vm.box = min(17, vm.box + boxes)
    sm = next((s for s in state.calendar.service_markers
               if s.lord_id == lord_id and s.vassal_id is None), None)
    if sm is None:
        # Off-left lane: re-enter onto the track.
        if lord_id in state.calendar.off_left_service:
            state.calendar.off_left_service.remove(lord_id)
        from almoravid.state import ServiceMarker
        sm = ServiceMarker(lord_id=lord_id, box=0)
        state.calendar.service_markers.append(sm)
    sm.box = min(17, sm.box + boxes)
    return sm.box


def _disband_vassals_for_side(state: GameState, side: str) -> list[dict]:
    """3.4.2 advanced Vassal Service — Disband step (3.3 / 4.8.2): for
    every Mustered Vassal (one with a Calendar Service marker) of `side`:
      - marker LEFT of the marker box -> permanently removed (3.3.1):
        return its Forces to the pool, drop its marker; it cannot Muster
        again (stays Unready with no marker).
      - marker IN the current box -> Disband at limit (3.3.2): return its
        Forces, drop its marker, set the Vassal Pennant-DOWN (Unready).
    If returning a Vassal's Forces leaves its Lord with NO Forces, that
    Lord immediately Disbands to the Calendar (1.6, 3.3.2).
    Only runs under the advanced rule. Never applies to Bishops/Crusaders
    (their markers are never on the Calendar; not modelled here)."""
    if not state.meta.advanced_vassal_service:
        return []
    cur = state.calendar.current_box
    out: list[dict] = []
    no_force_lords: list[str] = []
    for lid, lord in state.lords.items():
        if lord.side != side or lord.cylinder.kind != "locale":
            continue
        markers = [m for m in state.calendar.service_markers
                   if m.lord_id == lid and m.vassal_id is not None]
        for m in markers:
            if m.box > cur:
                continue  # not yet at Service limit
            vassal = next((v for v in lord.vassals if v.id == m.vassal_id),
                          None)
            removed = m.box < cur
            # Return the Vassal's Forces from the Lord's mat to the pool.
            if vassal is not None:
                for ut, n in vassal.forces.items():
                    have = lord.forces.get(ut, 0)
                    lord.forces[ut] = max(0, have - n)
                    if lord.forces[ut] == 0:
                        lord.forces.pop(ut, None)
                if removed:
                    vassal.pennant_down = False
                    vassal.ready = False   # permanently gone (no re-Muster)
                else:
                    vassal.pennant_down = True   # Unready until flip-up
                    vassal.ready = False
            out.append({"lord_id": lid, "vassal_id": m.vassal_id,
                        "fate": "removed" if removed else "pennant_down"})
        # Drop the processed Vassal markers.
        state.calendar.service_markers = [
            mm for mm in state.calendar.service_markers
            if not (mm.lord_id == lid and mm.vassal_id is not None
                    and mm.box <= cur)]
        # 1.6: a Lord left with no Forces Disbands to the Calendar.
        if markers and not lord.forces and lord.cylinder.kind == "locale":
            no_force_lords.append(lid)
    for lid in no_force_lords:
        # The 1.6 no-Forces Disband reuses _h_disband_lord (3.3.2). That
        # handler is guarded for the Levy service_disband step, but this
        # pass also runs during Campaign 4.8.2 — temporarily present a
        # Levy/service_disband context, then restore.
        _saved = (state.meta.phase, state.meta.levy_step,
                  state.meta.active_player)
        state.meta.phase = "levy"
        state.meta.levy_step = "service_disband"
        state.meta.active_player = side
        try:
            _h_disband_lord(state, {"type": "disband_lord",
                                    "side": side, "lord_id": lid,
                                    "bypass_limit_check": True})
        finally:
            (state.meta.phase, state.meta.levy_step,
             state.meta.active_player) = _saved
        out.append({"lord_id": lid, "fate": "lord_no_forces_disband"})
    return out


def _flip_up_pennants(state: GameState, side: str) -> list[str]:
    """3.4.2: after a side finishes its Vassal Muster segment this Levy,
    flip up all its Pennant-down (Unready) Vassal markers, making them
    Ready for Muster in a later Levy."""
    if not state.meta.advanced_vassal_service:
        return []
    flipped = []
    for lord in state.lords.values():
        if lord.side != side:
            continue
        for v in lord.vassals:
            if v.pennant_down:
                v.pennant_down = False
                v.ready = True
                flipped.append(f"{lord.id}:{v.id}")
    return flipped


def _compute_disband_target_box(state: GameState, lord: "Lord") -> int:
    """Errata p.12: where the Disbanding Lord's cylinder lands.

    During Levy: current_box + service_rating.
    During Campaign: current_box + 1 + service_rating ('next box if
    Campaign' per Errata p.12, inserted before 'marker' in 3.3.2
    bullet 1). The +1 accounts for the Campaign-step Calendar advance
    that hasn't happened yet at the moment of Disband.

    Pattern 9 audit fix N — codifies the Errata before Campaign-time
    Disband paths get wired in a later phase.
    """
    base = state.calendar.current_box + lord.service_rating
    if state.meta.phase == "campaign":
        return base + 1
    return base

# ---------------------------------------------------------------------------
# 3.2 Pay (Phase 5g)
# ---------------------------------------------------------------------------


def _h_pay_lord(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.2 Pay. Spend Coin (3.2.1) or Loot (3.2.2) to shift a Service
    marker RIGHTWARD (ahead, away from Disband) one 40-Days box per
    marker spent. Coin/Loot may be removed in this step ONLY to
    actually shift a marker (1.7.2).

    Action parameters (all explicit — the paying player chooses; no
    greedy defaults):
      side: acting side.
      payer_lord_id: the Lord whose mat the Coin/Loot comes from
        (omit for Taifa-box Coin).
      resource: "coin" | "loot" | "taifa_coin".
      amount: number of markers to spend (>=1).
      target_lord_id: whose Service marker shifts.

    Rules enforced:
      3.2.1 Coin: paying Lord's own marker, OR another Lord at the
        SAME Locale, OR (Taifa-box Coin) any Unbesieged Muslim Lord.
      3.2.2 Loot: payer must be in a Friendly Locale free of Siege
        (Bypassed OK); shifts his own or a same-Locale Lord's marker.
    """
    from almoravid.effective import is_besieged, is_friendly_locale
    side = _require_side(action)
    _require_levy_step(state, "pay")
    _require_active(state, side)
    resource = action.get("resource", "coin")
    _require(resource in ("coin", "loot", "taifa_coin"),
             "resource must be coin|loot|taifa_coin", code="bad_arg")
    amount = action.get("amount", 1)
    _require(isinstance(amount, int) and amount >= 1,
             "amount must be a positive int", code="bad_arg")
    target_lord_id = action.get("target_lord_id")
    _require(target_lord_id in state.lords,
             "target_lord_id required (str)", code="bad_arg")
    target = state.lords[target_lord_id]

    if resource == "taifa_coin":
        _require(side == "muslim", "Taifa-box Coin is Muslim only",
                 code="wrong_side")
        _require(state.taifas_box_coin >= amount,
                 f"Taifas box has {state.taifas_box_coin} Coin, need {amount}",
                 code="no_coin")
        _require(target.side == "muslim", "Taifa Coin shifts a Muslim Lord",
                 code="wrong_side")
        _require(not is_besieged(state, target_lord_id),
                 f"{target_lord_id} is Besieged (3.2.1 Taifa-Coin needs "
                 f"Unbesieged)", code="besieged")
        state.taifas_box_coin -= amount
    else:
        payer_lord_id = action.get("payer_lord_id")
        _require(payer_lord_id in state.lords,
                 "payer_lord_id required (str)", code="bad_arg")
        payer = state.lords[payer_lord_id]
        _require(payer.side == side, f"{payer_lord_id} not on {side}'s side",
                 code="wrong_side")
        _require(payer.cylinder.kind == "locale",
                 f"{payer_lord_id} not on map", code="not_on_map")
        have = payer.assets.get(resource, 0)
        _require(have >= amount,
                 f"{payer_lord_id} has {have} {resource}, need {amount}",
                 code="no_coin" if resource == "coin" else "no_loot")
        # Target eligibility: own marker, or another Lord at SAME Locale.
        if target_lord_id != payer_lord_id:
            _require(target.cylinder.kind == "locale"
                     and target.cylinder.locale_id == payer.cylinder.locale_id,
                     f"{target_lord_id} not at the same Locale as "
                     f"{payer_lord_id} (3.2)", code="not_same_locale")
        if resource == "loot":
            here = payer.cylinder.locale_id
            _require(is_friendly_locale(state, here, side),
                     f"Pay-with-Loot requires a Friendly Locale (3.2.2); "
                     f"{here} is not Friendly to {side}",
                     code="not_friendly_locale")
            _require(not is_besieged(state, payer_lord_id),
                     f"Pay-with-Loot requires a Locale free of Siege "
                     f"(3.2.2); {payer_lord_id} is Besieged",
                     code="besieged")
        payer.assets[resource] = have - amount
        if payer.assets[resource] == 0:
            payer.assets.pop(resource, None)

    new_box = _shift_service_right(state, target_lord_id, boxes=amount)
    _record(state, action,
            f"{side} pays {amount} {resource} -> {target_lord_id} "
            f"Service to box {new_box} (rightward)")
    return {"target_lord_id": target_lord_id, "service_box": new_box,
            "resource": resource, "amount": amount}


# ---------------------------------------------------------------------------
# 3.3 Service / Disband (Phase 5g)
# ---------------------------------------------------------------------------


def _award_parias_coin(state: GameState, amount: int, targets) -> dict[str, Any]:
    """1.4.3 PARIAS COIN: when an Independent Taifa Lord Disbands, the
    Christians add `amount` Coin (= the Disbanding Taifa Lord's Service
    rating: six if al-Mutamid, four otherwise) from the pool among any
    Unbesieged Christian Lords' mats.

    `targets` is an explicit list of {"lord_id", "coin"} (the Christian
    player's distribution); each lord must be an Unbesieged Christian
    Lord on the map and the coins must total `amount`. When omitted, a
    deterministic distribution is built (fill Unbesieged Christian Lords
    in id order) — the controlling side may override with explicit
    targets. If no Unbesieged Christian Lord exists, the Coin cannot be
    placed (stays in the pool).
    """
    from almoravid.effective import is_besieged
    eligible = [lid for lid, l in state.lords.items()
                if l.side == "christian" and l.cylinder.kind == "locale"
                and not is_besieged(state, lid)]
    if not eligible:
        return {"amount": amount, "placed": {}, "unplaced": amount,
                "reason": "no Unbesieged Christian Lord"}
    if targets is None:
        # Deterministic default: all to the first eligible Lord.
        targets = [{"lord_id": eligible[0], "coin": amount}]
    placed: dict[str, int] = {}
    total = 0
    for entry in targets:
        plid = entry.get("lord_id")
        _require(plid in eligible,
                 f"{plid} is not an Unbesieged Christian Lord for Parias "
                 f"Coin (1.4.3)", code="bad_parias_target")
        c = int(entry.get("coin", 0))
        _require(c >= 1, "Parias Coin amount must be >= 1", code="bad_arg")
        placed[plid] = placed.get(plid, 0) + c
        total += c
    _require(total == amount,
             f"Parias Coin distribution totals {total}, need {amount} "
             f"(1.4.3)", code="bad_parias_total")
    for plid, c in placed.items():
        lord = state.lords[plid]
        lord.assets["coin"] = lord.assets.get("coin", 0) + c
    return {"amount": amount, "placed": placed, "unplaced": 0}


def _h_disband_lord(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.3 Disband. Lords are Disbanded by the POSITION of their Service
    marker relative to the Levy/Campaign marker — Disband is mandatory,
    not voluntary (3.3).

      - Service marker LEFT of the marker (box < current) -> 3.3.1
        Beyond Service Limit: PERMANENTLY removed from the game
        (cylinder kind='removed'); "This Lord" Capabilities return to
        the side's board-edge stock; Seat + Lord/Vassal Service markers
        removed.
      - Service marker in the SAME box as the marker (box == current)
        -> 3.3.2 At Service Limit: Disband to the Calendar (cylinder
        placed service_rating boxes right of the current box if Levy;
        next box + service if Campaign), mat cards discarded, Service
        markers set aside (removed from the Calendar) for future Muster,
        Seat markers removed.

    A Lord whose Service marker is RIGHT of the marker is not subject
    to Disband and cannot be Disbanded here.

    Important (3.3.2): when an Independent Taifa Lord Disbands (either
    way), his Taifa adjusts to Parias (1.4.3) — awarding Parias Coin
    (= his Service rating) and a victory point to the Christians.

    Args:
      side, lord_id, parias_coin_targets (optional explicit Coin
        distribution for the Independent-Taifa case, 1.4.3).
    """
    from almoravid.state import Cylinder
    side = _require_side(action)
    _require_levy_step(state, "service_disband")
    _require_active(state, side)
    lord_id = action.get("lord_id")
    _require(isinstance(lord_id, str), "lord_id required", code="bad_arg")
    lord_id = cast(str, lord_id)
    _require(lord_id in state.lords, f"unknown lord {lord_id}",
             code="unknown_lord")
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not on map", code="not_on_map")
    # Eligibility gate (3.3): Disband only Lords AT or BEYOND the Service
    # limit (Service marker box <= current Levy/Campaign box).
    cur = state.calendar.current_box
    sm = next((m for m in state.calendar.service_markers
               if m.lord_id == lord_id and m.vassal_id is None), None)
    # 1.6 no-Forces auto-Disband (3.3.2) bypasses the at-limit gate.
    bypass_limit = bool(action.get("bypass_limit_check"))
    if sm is None:
        beyond, at_limit = True, False  # off the Calendar (off-left)
    else:
        if not bypass_limit:
            _require(sm.box <= cur,
                     f"{lord_id} Service marker (box {sm.box}) is right of the "
                     f"Levy marker (box {cur}) — not subject to Disband (3.3)",
                     code="not_at_limit")
        beyond = sm.box < cur
        at_limit = sm.box >= cur  # at limit OR (forced) right-of-limit

    # 3.3.2 Important / 1.4.3: Independent Taifa Lord -> Parias + Coin + VP.
    taifa_adjust = None
    parias_coin = None
    if (lord.is_taifa and lord.home_taifa
            and state.taifas.get(lord.home_taifa) is not None
            and state.taifas[lord.home_taifa].status == "independent"):
        from almoravid.campaign import adjust_taifa_status
        # T5: the Disband path awards Parias Coin with the Christian
        # player's explicit distribution, so suppress adjust_taifa_status'
        # own auto-award to avoid double-paying (1.4.3 / L7).
        taifa_adjust = adjust_taifa_status(
            state, lord.home_taifa, "parias", award_parias_coin=False,
            neutrality_choices=action.get("neutrality_choices"))
        parias_coin = _award_parias_coin(
            state, lord.service_rating, action.get("parias_coin_targets"))
        # Running-score tracker; final VP is recomputed from Parias status.
        state.score.christian += 1.0
        # T4 (1.4.3): if no explicit neutrality_choices were given and a
        # side has Lords Besieging a now-Neutral Stronghold, set a pending
        # RECOGNITION OF NEUTRALITY decision (resolved before play
        # continues; the disbanding side's turn resumes after).
        from almoravid.campaign import _maybe_set_neutrality_pending
        _maybe_set_neutrality_pending(state, taifa_adjust,
                                      state.meta.active_player)

    # Remove this Lord's Seat markers from the map (both 3.3.1 and 3.3.2).
    for loc in state.locales.values():
        if lord_id in loc.seat_marker_lord_ids:
            loc.seat_marker_lord_ids.remove(lord_id)
    # Cathedral Seats belong to Alfonso; remove them if he leaves the map
    # (rule 1.3.1 / 5.1: Seat markers — including Cathedrals — are removed
    # when that Lord leaves the map).
    if lord_id == "alfonso":
        state.cathedral_seat_locales = []

    # Route "This Lord" Capability cards: 3.3.1 returns them to the
    # side's board-edge stock; 3.3.2 discards them (cards at his mat).
    caps = list(lord.capabilities)
    if caps:
        if beyond:
            state.decks.board_edge.setdefault(side, []).extend(caps)
        else:
            state.decks.discard.extend(caps)

    # Remove the Lord's own AND Vassal Service markers; clear off-edge.
    state.calendar.service_markers = [
        m for m in state.calendar.service_markers if m.lord_id != lord_id]
    if lord_id in state.calendar.off_left_service:
        state.calendar.off_left_service.remove(lord_id)
    if lord_id in state.calendar.off_right_service:
        state.calendar.off_right_service.remove(lord_id)

    # Pattern 8: clear cleanup_on_removal_fields.
    lord.forces = {}
    lord.assets = {}
    lord.capabilities = []
    lord.vassals = []
    lord.in_stronghold = False
    lord.moved_fought = False
    lord.just_arrived_this_levy = False
    lord.lordship_used = 0
    lord.first_march_used_this_card = False
    lord.raiders_used_this_card = False
    lord.routed_units = {}
    lord.crusader_markers = 0
    # C8 (4.1.3): if a Lieutenant or his Lower Lord Disbands while the
    # other does not, the remaining Lord becomes a normal Lord.
    if lord.is_lieutenant:
        # Disbanding Lord was the Lieutenant -> free its Lower Lord(s).
        for other_l in state.lords.values():
            if other_l.id != lord_id and other_l.lieutenant_of == lord_id:
                other_l.lieutenant_of = None
    if lord.lieutenant_of is not None:
        # Disbanding Lord was a Lower Lord -> its Lieutenant, if it has
        # no other Lower Lord, reverts to a normal Lord.
        upper_id = lord.lieutenant_of
        upper = state.lords.get(upper_id)
        if upper is not None:
            still_has_lower = any(
                x.id != lord_id and x.lieutenant_of == upper_id
                for x in state.lords.values())
            if not still_has_lower:
                upper.is_lieutenant = False
    lord.is_lieutenant = False
    lord.lieutenant_of = None

    # Locale being vacated, for the 4.3.5 Siege/Bypass-marker cleanup.
    left_locale = (lord.cylinder.locale_id
                   if lord.cylinder.kind == "locale" else None)
    if beyond:
        # 3.3.1 permanent removal.
        lord.cylinder = Cylinder(kind="removed")
        outcome = "removed (3.3.1 Beyond Service)"
        result_box = None
    else:
        # 3.3.2 to the Calendar.
        new_box = _compute_disband_target_box(state, lord)
        if new_box > 16:
            new_box = 17
            state.calendar.off_right.append(lord_id)
        lord.cylinder = Cylinder(kind="calendar", box=new_box)
        outcome = f"to Calendar box {new_box} (3.3.2 At Limit)"
        result_box = new_box

    # 4.3.5 / playtest F7: a Stronghold left free of the besieging side's
    # Lords loses that side's Siege/Bypass markers.
    if left_locale is not None:
        from almoravid.campaign import _remove_orphaned_siege_bypass
        _remove_orphaned_siege_bypass(state, left_locale)

    _record(state, action, f"{side} {lord_id} Disbands -> {outcome}")
    return {"lord_id": lord_id, "permanent": beyond,
            "calendar_box": result_box, "taifa_adjust": taifa_adjust,
            "parias_coin": parias_coin}


# ---------------------------------------------------------------------------
# 3.4 Lordship-spending (Phase 5g)
# ---------------------------------------------------------------------------


def _require_levy_actor_eligible(state: GameState, lord, lord_id: str) -> None:
    """3.4 Muster intro: a Lord taking Levy actions must be on the map
    at a Friendly Locale with no Siege there (he may be Bypassed,
    4.3.5). Applies to all Lordship-spending Levy actions (Levy Lord
    to Muster, Levy Vassal, Levy Transport, Levy Capability)."""
    from almoravid.effective import is_friendly_locale, is_besieged
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not on the map (3.4)", code="not_on_map")
    here = lord.cylinder.locale_id
    _require(is_friendly_locale(state, here, lord.side),
             f"{lord_id} is not at a Friendly Locale ({here}); cannot take "
             f"Levy actions (3.4)", code="not_friendly_locale")
    _require(not is_besieged(state, lord_id),
             f"{lord_id} is Besieged; cannot take Levy actions (3.4, "
             f"Bypassed is OK)", code="besieged")


def _h_levy_transport(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.4.3 Levy Transport. Spend one Lordship action to add one
    Transport (Cart or Mule) to the Lord's mat. If the Lord has lost a
    Serf unit, return one Serf to his mat (required).

    Args:
      side, lord_id, transport ("cart" | "mule").
    """
    side = _require_side(action)
    _require_levy_step(state, "muster")
    _require_active(state, side)
    lord_id = action.get("lord_id")
    _require(isinstance(lord_id, str), "lord_id required", code="bad_arg")
    lord_id = cast(str, lord_id)
    _require(lord_id in state.lords, f"unknown lord {lord_id}",
             code="unknown_lord")
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require_levy_actor_eligible(state, lord, lord_id)
    _require(lord.lordship_used < lord.lordship_rating,
             f"{lord_id} has already spent {lord.lordship_used}/"
             f"{lord.lordship_rating} Lordship", code="lordship_exhausted")
    transport = action.get("transport")
    _require(transport in ("cart", "mule"),
             "transport must be 'cart' or 'mule' (3.4.3)", code="bad_arg")
    lord.assets[transport] = lord.assets.get(transport, 0) + 1
    lord.lordship_used += 1
    # Return one lost Serf (required) — compare to the Lord's starting
    # Serf count from static data.
    start_serfs = load_lords()["lords"][lord_id]["forces"].get("serfs", 0)
    cur_serfs = lord.forces.get("serfs", 0)
    returned_serf = False
    if start_serfs > 0 and cur_serfs < start_serfs:
        lord.forces["serfs"] = cur_serfs + 1
        returned_serf = True
    _record(state, action,
            f"{side} {lord_id} Levies Transport (+1 {transport})"
            + ("; returned 1 lost Serf" if returned_serf else ""))
    return {"lord_id": lord_id, "transport": transport,
            "returned_serf": returned_serf,
            "lordship_used": lord.lordship_used}


def _h_levy_take_vassal(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.4 Muster Levy action: spend 1 Lordship to add a Vassal's Forces
    to the Lord's mat. The Vassal must be Ready.

    Phase 5g baseline: just bring a Ready Vassal into play (set ready=False
    means in-play / spent; for now we track via a marker on the Lord).
    Actual Service marker advancement of the Vassal happens with the
    advanced Vassal Service rule (3.4.2), deferred.
    """
    side = _require_side(action)
    _require_levy_step(state, "muster")
    _require_active(state, side)
    lord_id = action.get("lord_id")
    vassal_index = action.get("vassal_index")
    _require(isinstance(lord_id, str), "lord_id required", code="bad_arg")
    _require(isinstance(vassal_index, int), "vassal_index required (int)",
             code="bad_arg")
    lord_id = cast(str, lord_id)
    vassal_index = cast(int, vassal_index)
    _require(lord_id in state.lords, f"unknown lord {lord_id}",
             code="unknown_lord")
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not mustered", code="not_on_map")
    _require_levy_actor_eligible(state, lord, lord_id)
    _require(lord.lordship_used < lord.lordship_rating,
             f"{lord_id} has already spent {lord.lordship_used}/"
             f"{lord.lordship_rating} Lordship",
             code="lordship_exhausted")
    _require(0 <= vassal_index < len(lord.vassals),
             f"vassal_index {vassal_index} out of range",
             code="bad_arg")
    vassal = lord.vassals[vassal_index]
    _require(vassal.ready, f"vassal {vassal.name} not Ready",
             code="vassal_not_ready")
    # 3.4.2 advanced rule: a Pennant-down (Unready) Vassal may not Muster.
    if state.meta.advanced_vassal_service:
        _require(not vassal.pennant_down,
                 f"vassal {vassal.name} is Pennant-down (Unready) this "
                 f"Levy (3.4.2)", code="vassal_unready")
    # Bring Vassal's Forces onto the Lord's mat
    for ut, n in vassal.forces.items():
        lord.forces[ut] = lord.forces.get(ut, 0) + n
    vassal.ready = False
    lord.lordship_used += 1
    # Phase 7d: advanced Vassal Service (3.4.2) — place the Vassal's
    # Service marker on the Calendar at the Lord's current Service box.
    if state.meta.advanced_vassal_service:
        from almoravid.state import ServiceMarker
        # 3.4.2: place the Vassal's Service marker right of the Levy
        # marker by the Vassal's Service Rating (service_cost), just as
        # for a Lord (3.4.1) — NOT at the Lord's current box.
        box = min(17, state.calendar.current_box + vassal.service_cost)
        already = any(s.lord_id == lord_id and s.vassal_id == vassal.id
                      for s in state.calendar.service_markers)
        if not already:
            state.calendar.service_markers.append(
                ServiceMarker(lord_id=lord_id, box=box, vassal_id=vassal.id))
    _record(state, action,
            f"{side} {lord_id} spends Lordship -> takes Vassal {vassal.name}")
    return {"lord_id": lord_id, "vassal_name": vassal.name,
            "lordship_used": lord.lordship_used}


def _unused_capability_cards(state: GameState, side: str) -> list[str]:
    """3.4.4 source pool: the side's currently UNUSED Arts of War cards
    that carry a Capability half.

    "Unused" mirrors the 3.1.1 deck rebuild (see _rebuild_aow_deck):
    every card of this side EXCEPT those currently in play or held —
    deployed Capabilities (board edge + tucked under Lord mats), Held
    Events, and cards pending implementation this Levy. Cards in the
    draw pile the player has never seen, and discarded cards, both
    count as unused (the deck is a face-up "menu" for Capability Levy).
    Per the rules there is no permanent card-removal mechanic active in
    this engine, so nothing else is excluded.
    """
    cards = load_cards()["cards"]
    excluded: set[str] = set()
    for bucket in (state.decks.this_levy_events,
                   state.decks.this_campaign_events, state.decks.held):
        excluded.update(bucket.get(side, []))
    excluded.update(state.decks.board_edge.get(side, []))
    excluded.update(c.card_id for c in state.decks.capabilities_in_play
                    if c.owner_side == side)
    for l in state.lords.values():
        if l.side == side:
            excluded.update(l.capabilities)
    excluded.update(state.decks.pending_draw.get(side, []))
    return [cid for cid, c in cards.items()
            if c["side"] == side and cid not in excluded
            and not c.get("no_capability")
            and c.get("capability_scope") is not None]


def _this_lord_cap_titles(lord) -> list[str]:
    """capability_name (title) of each This-Lord Capability on this Lord."""
    from almoravid.static_data import load_cards
    cards = load_cards()["cards"]
    return [cards.get(cid, {}).get("capability_name")
            for cid in lord.capabilities]


def _check_this_lord_cap_limits(lord, card_id: str) -> None:
    """3.4.4 This-Lord Capability restrictions: a Lord may hold at most
    TWO This-Lord Capabilities, and may not hold two with the same title.
    Enforced as a hard gate on adding a new one (rather than a forced
    discard, which would require a separate player choice)."""
    from almoravid.static_data import load_cards
    cards = load_cards()["cards"]
    new_title = cards.get(card_id, {}).get("capability_name")
    existing = _this_lord_cap_titles(lord)
    _require(new_title not in existing,
             f"{lord.id} already has a This-Lord Capability titled "
             f"{new_title!r} (3.4.4: no two same-title)",
             code="duplicate_this_lord_title")
    _require(len(lord.capabilities) < 2,
             f"{lord.id} already holds two This-Lord Capabilities "
             f"(3.4.4 max); discard one first",
             code="this_lord_cap_limit")


def _h_levy_take_capability(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.4.4 Muster Levy action: spend 1 Lordship to obtain a Capability
    from ANY of the side's currently UNUSED Arts of War cards (the deck
    functions as a face-up menu), deploying it either to this Lord
    (this_lord) or to the side's board edge (side_wide). Levying the
    Capability blocks that card's Event (the card leaves the unused pool
    once in play). Source = _unused_capability_cards (3.1.1 semantics).
    """
    from almoravid.state import CardInPlay
    from almoravid.static_data import load_cards
    side = _require_side(action)
    _require_levy_step(state, "muster")
    _require_active(state, side)
    lord_id = action.get("lord_id")
    card_id = action.get("card_id")
    _require(isinstance(lord_id, str), "lord_id required", code="bad_arg")
    _require(isinstance(card_id, str), "card_id required", code="bad_arg")
    lord_id = cast(str, lord_id)
    card_id = cast(str, card_id)
    _require(lord_id in state.lords, f"unknown lord {lord_id}",
             code="unknown_lord")
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not mustered", code="not_on_map")
    _require_levy_actor_eligible(state, lord, lord_id)
    _require(lord.lordship_used < lord.lordship_rating,
             "lordship exhausted", code="lordship_exhausted")
    # 3.4.4: select from ANY of the side's currently UNUSED Capability
    # cards (full deck minus in-play/held/pending), not just board edge.
    _require(card_id in _unused_capability_cards(state, side),
             f"{card_id} is not an unused {side} Capability card (3.4.4)",
             code="card_not_available")
    cards = load_cards()["cards"]
    rec = cards.get(card_id)
    _require(rec and not rec["no_capability"],
             f"{card_id} has no Capability half", code="no_capability_half")
    scope = rec["capability_scope"]
    if scope == "this_lord":
        _check_this_lord_cap_limits(lord, card_id)
    # Deploy: this_lord caps tuck under the Lord's mat; side_wide caps go
    # to the board edge. Both register in capabilities_in_play and leave
    # the unused pool. Drop from the materialised draw list if present.
    if card_id in state.decks.draw:
        state.decks.draw.remove(card_id)
    if scope == "this_lord":
        lord.capabilities.append(card_id)
    else:
        state.decks.board_edge.setdefault(side, []).append(card_id)
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id=card_id, scope=scope, owner_side=side,
        owner_lord_id=lord_id if scope == "this_lord" else None,
    ))
    lord.lordship_used += 1
    _record(state, action,
            f"{side} {lord_id} spends Lordship -> Levies Capability {card_id}"
            f" ({scope})")
    return {"lord_id": lord_id, "card_id": card_id, "scope": scope,
            "lordship_used": lord.lordship_used}


_HANDLERS = {
    "begin_levy": _h_begin_levy,
    "bid_for_sides": _h_bid_for_sides,
    "pass_step": _h_pass_step,
    "aow_shuffle": _h_aow_shuffle,
    "aow_draw": _h_aow_draw,
    "aow_deploy_capability": _h_aow_deploy_capability,
    "aow_implement_event": _h_aow_implement_event,
    "muster_lord": _h_muster_lord,
    "pay_lord": _h_pay_lord,
    "disband_lord": _h_disband_lord,
    "levy_take_vassal": _h_levy_take_vassal,
    "levy_take_capability": _h_levy_take_capability,
    "levy_transport": _h_levy_transport,
    # 3.5 Call to Arms (FIX-A / L2)
    "cta_reconcile_rodrigo": _h_cta_reconcile_rodrigo,
    "cta_employ_rodrigo": _h_cta_employ_rodrigo,
    "cta_call_crusade": _h_cta_call_crusade,
    "cta_invite_almoravids": _h_cta_invite_almoravids,
    "cta_uphold_dynasties": _h_cta_uphold_dynasties,
    "cta_call_emir": _h_cta_call_emir,
    "cta_add_crusade_jihad": _h_cta_add_crusade_jihad,
}

# Campaign handlers registered in campaign.py. Imported lazily to avoid
# a circular import.
def _ensure_campaign_handlers() -> None:
    if "begin_campaign" in _HANDLERS:
        return
    from almoravid.campaign import CAMPAIGN_HANDLERS
    _HANDLERS.update(CAMPAIGN_HANDLERS)


def apply_action(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Single entry point for state mutation.

    Routes by `action["type"]` to a handler. Returns the handler's
    result dict. Raises IllegalAction on validation failure.
    """
    _ensure_campaign_handlers()
    action_type = action.get("type")
    if action_type not in _HANDLERS:
        raise IllegalAction(
            f"unknown action type {action_type!r}. "
            f"Known: {sorted(_HANDLERS)}",
            code="unknown_action",
        )
    return _HANDLERS[action_type](state, action)
