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
    _require(state.meta.phase == "setup",
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
    # Phase 6d: M16/M17 ban Muster of/by specified Lord for the Levy.
    _require(lord_id not in state.meta.muster_banned_this_levy_lord_ids,
             f"{lord_id} cannot Muster this Levy "
             f"(M16/M17 Revolt ban active)",
             code="muster_banned")
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
            "fealty": lord.fealty}


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


def _h_disband_lord(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.3 Disband: voluntarily Disband a Lord whose Service marker is
    at or beyond Service limit (Beyond-Service per rule 3.3.1) OR
    voluntarily before Service expires.

    Phase 5g baseline: Disband to the Calendar. Sets cylinder to
    'calendar' at the current Levy box + Lord's service_rating
    (rule 3.4.1 'Service-rating boxes ahead'). Clears all
    Lord.cleanup_on_removal_fields per Pattern 8.
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
    # Bug N (Pattern 9 audit / Errata p.12): Disband target box differs
    # by phase per the Errata correction —
    #   if Levy: current_box + service_rating
    #   if Campaign: current_box + 1 + service_rating  (the +1 is the
    #     errata 'next box if Campaign (4.8.2)' insertion)
    # Today _h_disband_lord is gated on Levy step, so the if-branch is
    # what runs; the helper is in place so when 4.8.2/4.8.3 voluntary
    # Campaign-time Disband lands later it uses the right box.
    new_box = _compute_disband_target_box(state, lord)
    if new_box > 16:
        new_box = 17  # off-right sentinel
        state.calendar.off_right.append(lord_id)
    lord.cylinder = Cylinder(kind="calendar", box=new_box)
    # Pattern 8: clear cleanup_on_removal_fields
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
    # Remove Service marker
    state.calendar.service_markers = [
        s for s in state.calendar.service_markers if s.lord_id != lord_id
    ]
    _record(state, action,
            f"{side} {lord_id} Disbands -> Calendar box {new_box}")
    return {"lord_id": lord_id, "calendar_box": new_box}


# ---------------------------------------------------------------------------
# 3.4 Lordship-spending (Phase 5g)
# ---------------------------------------------------------------------------


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
    # Bring Vassal's Forces onto the Lord's mat
    for ut, n in vassal.forces.items():
        lord.forces[ut] = lord.forces.get(ut, 0) + n
    vassal.ready = False
    lord.lordship_used += 1
    # Phase 7d: advanced Vassal Service (3.4.2) — place the Vassal's
    # Service marker on the Calendar at the Lord's current Service box.
    if state.meta.advanced_vassal_service:
        from almoravid.state import ServiceMarker
        lord_sm = next((s for s in state.calendar.service_markers
                        if s.lord_id == lord_id and s.vassal_id is None),
                       None)
        box = lord_sm.box if lord_sm is not None else 1
        already = any(s.lord_id == lord_id and s.vassal_id == vassal.id
                      for s in state.calendar.service_markers)
        if not already:
            state.calendar.service_markers.append(
                ServiceMarker(lord_id=lord_id, box=box, vassal_id=vassal.id))
    _record(state, action,
            f"{side} {lord_id} spends Lordship -> takes Vassal {vassal.name}")
    return {"lord_id": lord_id, "vassal_name": vassal.name,
            "lordship_used": lord.lordship_used}


def _h_levy_take_capability(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """3.4 Muster Levy action: spend 1 Lordship to add a Capability
    card from this side's board-edge stock to a Lord's mat (this_lord)
    or to capabilities_in_play (side_wide).

    Phase 5g baseline: validates Lordship, capability scope, and card
    availability; moves card from board_edge to the appropriate target.
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
    _require(lord.lordship_used < lord.lordship_rating,
             "lordship exhausted", code="lordship_exhausted")
    # Card must be in the side's board_edge stock
    edge = state.decks.board_edge.get(side, [])
    _require(card_id in edge, f"{card_id} not in {side} board edge",
             code="card_not_available")
    cards = load_cards()["cards"]
    rec = cards.get(card_id)
    _require(rec and not rec["no_capability"],
             f"{card_id} has no Capability half", code="no_capability_half")
    scope = rec["capability_scope"]
    # Move from edge to target
    state.decks.board_edge[side].remove(card_id)
    if scope == "this_lord":
        lord.capabilities.append(card_id)
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id=card_id, scope=scope, owner_side=side,
        owner_lord_id=lord_id if scope == "this_lord" else None,
    ))
    lord.lordship_used += 1
    _record(state, action,
            f"{side} {lord_id} spends Lordship -> takes Capability {card_id}")
    return {"lord_id": lord_id, "card_id": card_id, "scope": scope,
            "lordship_used": lord.lordship_used}


_HANDLERS = {
    "begin_levy": _h_begin_levy,
    "pass_step": _h_pass_step,
    "aow_shuffle": _h_aow_shuffle,
    "aow_draw": _h_aow_draw,
    "muster_lord": _h_muster_lord,
    "pay_lord": _h_pay_lord,
    "disband_lord": _h_disband_lord,
    "levy_take_vassal": _h_levy_take_vassal,
    "levy_take_capability": _h_levy_take_capability,
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
