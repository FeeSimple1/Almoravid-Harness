"""Campaign-phase handlers (rule 4).

Phase 3a scope: Plan (4.1) and Activation (4.2) framework, with a
single command implementation (cmd_pass — burn a card with no
actions). Subsequent commits flesh out March, Supply, Forage, Ravage,
Tax, Siege, Battle.

Architectural choices driven by FUTURE_PROJECTS_LESSONS.md:
  - Pattern 1 (state-set-but-unreachable): every Plan / Activation
    state transition is reachable via legal_moves. The "advance the
    revealed card" path goes through end_card -> command_reveal so
    there's exactly one place control flows through.
  - Pattern 11 (active-player desync): command_reveal is what flips
    `active_player` between sides during Activation.
  - Pattern 13 (per-window once-only): Plan stacks (decks.plan) are
    cleared at end_campaign so they don't leak into the next Campaign.
"""

from __future__ import annotations

from typing import Any, cast

from almoravid.actions import (
    ACTOR_ORDER,
    IllegalAction,
    _record,
    _require,
    _require_active,
    _require_phase,
    _require_side,
)
from almoravid.state import (
    GameState,
    PlanEntry,
    Side,
)


# Plan size per season (SoP §4.1 / hard-coded seasonal command_cards).
PLAN_SIZE_BY_SEASON: dict[str, int] = {
    "spring": 7,
    "summer": 8,
    "autumn": 7,
    "winter": 0,  # Winter handled via 6.3, not normal Plan
}


def _other(side: Side) -> Side:
    return "muslim" if side == "christian" else "christian"


def _current_season(state: GameState) -> str:
    box = state.calendar.current_box
    return state.calendar.boxes[box - 1].season


def _plan_target_size(state: GameState) -> int:
    """The plan size each side must reach to finalize this Campaign."""
    return PLAN_SIZE_BY_SEASON.get(_current_season(state), 7)


def _require_campaign_step(state: GameState, step: str) -> None:
    _require_phase(state, "campaign")
    _require(state.meta.campaign_step == step,
             f"campaign_step is {state.meta.campaign_step}, expected {step}",
             code="bad_campaign_step")


# ---------------------------------------------------------------------------
# Lifecycle: begin_campaign
# ---------------------------------------------------------------------------


def _h_begin_campaign(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Move from levy/done into campaign/plan (rule 4.1 entry).

    Action dispatcher in actions.py routes here when the Levy phase
    finishes via _advance_step_if_both_done. This handler is also the
    user-facing entry point if the harness is started with the state
    already past Levy.
    """
    _require(state.meta.phase == "campaign",
             f"begin_campaign requires phase=campaign (got {state.meta.phase})",
             code="bad_phase")
    state.meta.campaign_step = "plan"
    state.meta.plan_finalized_christian = False
    state.meta.plan_finalized_muslim = False
    state.meta.plan_index_christian = 0
    state.meta.plan_index_muslim = 0
    state.meta.actions_remaining = 0
    state.meta.active_lord_id = None
    state.decks.plan = {"christian": [], "muslim": []}
    state.meta.active_player = ACTOR_ORDER[0]
    _record(state, action, "Begin Campaign — Plan step")
    return {"campaign_step": "plan",
            "plan_target_size": _plan_target_size(state)}


# ---------------------------------------------------------------------------
# 4.1 Plan
# ---------------------------------------------------------------------------


def _h_plan_add_card(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Append one card to a side's Plan stack (rule 4.1).

    Both sides plan privately; the harness treats both stacks as part
    of state so the agent abstraction stays clean. (A real two-player
    UI would hide the opponent's stack until reveal.)
    """
    side = _require_side(action)
    _require_campaign_step(state, "plan")
    # Either side may add to their own plan in any order during the
    # plan step. Pattern 11: no active_player gate here, but we still
    # validate the side belongs to the game.
    kind = action.get("plan_kind", "command")
    _require(kind in ("command", "pass"),
             f"plan_kind must be 'command' or 'pass', got {kind!r}",
             code="bad_arg")
    lord_id = action.get("lord_id")
    if kind == "command":
        _require(isinstance(lord_id, str),
                 "command plan entries require lord_id",
                 code="bad_arg")
        _require(lord_id in state.lords,
                 f"unknown lord {lord_id!r}",
                 code="unknown_lord")
        lord = state.lords[lord_id]
        _require(lord.side == side,
                 f"{lord_id} is not on {side}'s side",
                 code="wrong_side")
    plan = state.decks.plan.setdefault(side, [])
    target = _plan_target_size(state)
    _require(len(plan) < target,
             f"plan already at target size {target}",
             code="plan_full")
    plan.append(PlanEntry(kind=kind, lord_id=lord_id if kind == "command" else None))
    _record(state, action, f"{side} adds {kind} card"
            + (f" for {lord_id}" if lord_id else ""))
    return {"plan_size": len(plan), "target": target}


def _h_finalize_plan(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Side declares its Plan complete (rule 4.1 end).

    Plan must be exactly the season's target size. When both sides
    finalize, transition to activation step.
    """
    side = _require_side(action)
    _require_campaign_step(state, "plan")
    target = _plan_target_size(state)
    plan = state.decks.plan.get(side, [])
    _require(len(plan) == target,
             f"plan has {len(plan)} entries, must be {target}",
             code="plan_size_mismatch")
    if side == "christian":
        _require(not state.meta.plan_finalized_christian,
                 "christian plan already finalized",
                 code="already_finalized")
        state.meta.plan_finalized_christian = True
    else:
        _require(not state.meta.plan_finalized_muslim,
                 "muslim plan already finalized",
                 code="already_finalized")
        state.meta.plan_finalized_muslim = True
    advanced = False
    if state.meta.plan_finalized_christian and state.meta.plan_finalized_muslim:
        # Both sides finalized: enter Activation. Skip straight to
        # end_campaign if neither side planned any cards (Winter season
        # with PLAN_SIZE_BY_SEASON["winter"] = 0). Proper Scenario F
        # Winter Sequence (6.3) lands in a later phase.
        plan_c = state.decks.plan.get("christian", [])
        plan_m = state.decks.plan.get("muslim", [])
        if not plan_c and not plan_m:
            state.meta.campaign_step = "end_campaign"
        else:
            state.meta.campaign_step = "activation"
            state.meta.active_player = ACTOR_ORDER[0]
        advanced = True
    _record(state, action,
            f"{side} finalizes plan ({len(plan)} cards)"
            + ("; both finalized — activation step" if advanced else ""))
    return {"campaign_step": state.meta.campaign_step, "advanced": advanced}


# ---------------------------------------------------------------------------
# 4.2 Activation
# ---------------------------------------------------------------------------


def _h_command_reveal(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Reveal the next card from the acting side's Plan (rule 4.2).

    Christian and Muslim alternate. If the revealed card's Lord is not
    on the map (cylinder.kind != 'locale') or the entry is kind='pass',
    it's a "no actions taken" reveal — record and continue (rule
    4.2.3). Otherwise, set active_lord_id and actions_remaining = the
    Lord's command_rating.
    """
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is None,
             "a Lord is already active; finish their card with end_card first",
             code="lord_already_active")

    idx_attr = f"plan_index_{side}"
    idx = getattr(state.meta, idx_attr)
    plan = state.decks.plan.get(side, [])
    _require(idx < len(plan),
             f"{side} plan exhausted (idx={idx}, plan_size={len(plan)})",
             code="plan_exhausted")
    entry = plan[idx]
    setattr(state.meta, idx_attr, idx + 1)

    auto_pass = False
    if entry.kind == "pass":
        auto_pass = True
    elif entry.lord_id is not None:
        lord = state.lords[entry.lord_id]
        if lord.cylinder.kind != "locale":
            auto_pass = True

    if auto_pass:
        # No actions taken — flip baton and check campaign end.
        _record(state, action,
                f"{side} reveals "
                + (f"pass card" if entry.kind == "pass"
                   else f"command card for {entry.lord_id} (not on map)"))
        _advance_or_end_campaign(state)
        return {"revealed": entry.model_dump(), "auto_pass": True,
                "active_lord_id": state.meta.active_lord_id,
                "campaign_step": state.meta.campaign_step}

    # A Lord is now active for command_rating actions.
    assert entry.lord_id is not None
    lord = state.lords[entry.lord_id]
    state.meta.active_lord_id = entry.lord_id
    state.meta.actions_remaining = lord.command_rating
    _record(state, action,
            f"{side} reveals command card for {entry.lord_id} "
            f"({lord.command_rating} actions)")
    return {"revealed": entry.model_dump(), "auto_pass": False,
            "active_lord_id": entry.lord_id,
            "actions_remaining": lord.command_rating}


def _advance_or_end_campaign(state: GameState) -> None:
    """After a card finishes, advance to the other side OR end Campaign
    if both sides have exhausted their plans.

    Pattern 1 / Pattern 11: this is the single place card-to-card and
    Activation -> end transitions happen.
    """
    c_done = state.meta.plan_index_christian >= len(state.decks.plan.get("christian", []))
    m_done = state.meta.plan_index_muslim >= len(state.decks.plan.get("muslim", []))
    if c_done and m_done:
        # End of Campaign — clear plans (Pattern 13) and end the Campaign
        state.meta.campaign_step = "end_campaign"
        state.meta.active_lord_id = None
        state.meta.actions_remaining = 0
        return
    # Flip baton; if one side is exhausted, the other side continues alone.
    other = _other(state.meta.active_player)
    other_done = (state.meta.plan_index_muslim
                  >= len(state.decks.plan.get("muslim", []))
                  if other == "muslim"
                  else state.meta.plan_index_christian
                  >= len(state.decks.plan.get("christian", [])))
    if not other_done:
        state.meta.active_player = other


def _h_end_card(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """End the currently-active Lord's card and flip the baton.

    Future phases will trigger Feed/Pay/Disband here per rule 4.8 (in
    Almoravid: at end of each Command card, the Lord Feeds and may
    Pay / Disband). Phase 3a only does the bookkeeping.
    """
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord — reveal a card first",
             code="no_active_lord")
    lord_id = state.meta.active_lord_id
    state.meta.active_lord_id = None
    state.meta.actions_remaining = 0
    # Clear per-card flags (Pattern 3: per-card scope reset).
    lord = state.lords[lord_id]
    lord.lordship_used = 0
    lord.first_march_used_this_card = False
    lord.raiders_used_this_card = False
    _advance_or_end_campaign(state)
    _record(state, action,
            f"{side} ends {lord_id}'s card"
            + (f" -> campaign_step={state.meta.campaign_step}"
               if state.meta.campaign_step != "activation" else ""))
    return {"ended": lord_id, "campaign_step": state.meta.campaign_step}


def _h_cmd_pass(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Consume actions_remaining without doing anything (rule 4.7.4).

    The active Lord may Pass on any of their remaining actions. Pass
    is always available, which keeps the Activation loop reachable
    (Pattern 1).
    """
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord — reveal a card first",
             code="no_active_lord")
    _require(state.meta.actions_remaining > 0,
             "no actions remaining — call end_card",
             code="no_actions_left")
    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{side} {state.meta.active_lord_id} passes "
            f"({state.meta.actions_remaining} actions left)")
    return {"actions_remaining": state.meta.actions_remaining}


# ---------------------------------------------------------------------------
# End of Campaign
# ---------------------------------------------------------------------------


def _h_end_campaign(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Resolve end-of-Campaign bookkeeping and advance the Calendar.

    Phase 3a: minimal — clear Plans (Pattern 13), advance current_box
    by 1, transition back to Levy (or to ended if scenario_end reached).
    Real Feed/Pay/Disband / Wastage / Plow / Grow land in Phase 3+.
    """
    _require_campaign_step(state, "end_campaign")
    # Clear plans (per-Campaign window — Pattern 13)
    state.decks.plan = {"christian": [], "muslim": []}
    state.meta.plan_finalized_christian = False
    state.meta.plan_finalized_muslim = False
    state.meta.plan_index_christian = 0
    state.meta.plan_index_muslim = 0
    # Clear per-Campaign event bucket
    state.decks.this_campaign_events = {}
    # Advance Calendar
    prev_box = state.calendar.current_box
    new_box = prev_box + 1
    # Check Scenario End marker
    if new_box > len(state.calendar.boxes):
        state.meta.phase = "ended"
        _record(state, action, f"Campaign end at box {prev_box}; scenario ended (off calendar)")
        return {"phase": "ended", "current_box": prev_box}
    state.calendar.current_box = new_box
    # If new box has scenario_end marker, end the game
    new_box_obj = state.calendar.boxes[new_box - 1]
    if "scenario_end" in new_box_obj.decorations:
        state.meta.phase = "ended"
        _record(state, action,
                f"Campaign end; advanced box {prev_box} -> {new_box} (Scenario End)")
        return {"phase": "ended", "current_box": new_box}
    # Otherwise return to Levy
    state.meta.phase = "levy"
    state.meta.campaign_step = None
    state.meta.levy_step = "arts_of_war"
    state.meta.levy_step_completed_christian = False
    state.meta.levy_step_completed_muslim = False
    state.meta.active_player = ACTOR_ORDER[0]
    state.meta.turn_index += 1
    _record(state, action,
            f"End Campaign; advanced box {prev_box} -> {new_box}; back to Levy")
    return {"phase": state.meta.phase, "current_box": new_box,
            "turn_index": state.meta.turn_index}


# ---------------------------------------------------------------------------
# Public registry — actions.py picks these up
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 4.3 March (Phase 5a — single-Lord March only; group March via Marshal
# lands in a later commit alongside Lieutenant/Marshal mechanics).
# ---------------------------------------------------------------------------


def _is_laden(lord) -> bool:
    """A Lord is Laden if Cart or Mule carries two Provender (incl.
    shared, 1.5.2), or Cart carries any Provender over a Pass, or
    moving any Loot (rule 4.3.2).

    Phase 5a simplification: 'two or more Provender total' AND 'any
    Loot' are the two-action triggers. The Cart-over-Pass conditional
    is checked separately at March time so it can fire even with one
    Provender.
    """
    prov = lord.assets.get("prov", 0)
    loot = lord.assets.get("loot", 0)
    return prov >= 2 or loot >= 1


def _h_cmd_march(state, action):
    """4.3 March: move the active Lord to an adjacent Locale.

    Args:
      side (Side): the acting side.
      target_locale_id (str): destination locale_id.
      way_type ('road' | 'pass'): which Way to march along.

    Cost: 1 action Unladen, 2 actions if Laden (rule 4.3, 4.3.2).
    Besieged Lord may only Sally / Forage (Gardens) / Pass (rule 4.5.3).
    Cart cannot cross a Pass Laden with Provender (rule 4.3.2): if the
    way_type is 'pass' and Lord has any Cart-borne Provender, the
    March is rejected. The agent can pre-discard Provender via a
    future asset-management action.
    """
    from almoravid.effective import is_besieged
    from almoravid.map import neighbors_via

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord — reveal a card first",
             code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} is not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord may only Sally / Forage (Gardens) / Pass (4.5.3)",
             code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"Lord {lord_id} is not at a Locale (cannot March)",
             code="not_on_map")
    from_loc = lord.cylinder.locale_id

    target = action.get("target_locale_id")
    way_type = action.get("way_type", "road")
    _require(isinstance(target, str), "target_locale_id required (str)",
             code="bad_arg")
    _require(way_type in ("road", "pass"),
             f"way_type must be road or pass, got {way_type!r}",
             code="bad_arg")
    _require(target in state.locales, f"unknown locale {target!r}",
             code="unknown_locale")

    # Pattern 4: enforce the named way_type, never pick first match.
    nbrs = neighbors_via(from_loc, way_type)
    _require(target in nbrs,
             f"{target} is not reachable from {from_loc} via {way_type}",
             code="not_adjacent")

    laden = _is_laden(lord)
    cost = 2 if laden else 1
    _require(state.meta.actions_remaining >= cost,
             f"March costs {cost} actions ({'Laden' if laden else 'Unladen'}), "
             f"only {state.meta.actions_remaining} remaining",
             code="not_enough_actions")

    # Cart cannot cross a Pass with Provender (rule 4.3.2).
    if (way_type == "pass" and lord.assets.get("cart", 0) > 0
            and lord.assets.get("prov", 0) > 0):
        raise IllegalAction(
            "Cart laden with Provender cannot cross a Pass (4.3.2). "
            "Discard Provender or use a Road.",
            code="cart_over_pass_with_prov",
        )

    # Execute March.
    from almoravid.state import Cylinder
    lord.cylinder = Cylinder(kind="locale", locale_id=target)
    # On arrival at a Stronghold, Lord is outside walls by default
    # (entering requires explicit action — to be defined in a later
    # Phase 5 commit for stronghold-entry mechanics).
    lord.in_stronghold = False
    lord.moved_fought = True
    lord.first_march_used_this_card = True  # Pattern 3 per-card flag
    state.meta.actions_remaining -= cost
    _record(state, action,
            f"{side} {lord_id} marches {from_loc} -> {target} via {way_type}"
            f" ({'Laden, 2 actions' if laden else '1 action'})")
    return {"from": from_loc, "to": target, "way_type": way_type,
            "laden": laden, "cost": cost,
            "actions_remaining": state.meta.actions_remaining}



# ---------------------------------------------------------------------------
# 4.6 Supply (Phase 5b)
# ---------------------------------------------------------------------------


def _own_seats(state, lord_id: str) -> list[str]:
    """Locale ids that are printed Seats for this Lord (from static data)."""
    from almoravid.static_data import load_lords
    return list(load_lords()["lords"][lord_id].get("seats", []))


def _route_blocked_by_enemy(state, route: list[str], side) -> bool:
    """Per rule 4.6.1: route may not include a Locale with an Enemy
    Stronghold or Lord, unless that Enemy is Besieged or Bypassed.

    Phase 5b simplification: an Enemy Stronghold is any Locale whose
    territory is unfriendly to `side` per is_friendly_locale, and an
    Enemy Lord is any opposing-side Lord physically present. Bypassed
    /Besieged exemptions consult effective.is_besieged / is_bypassed.
    """
    from almoravid.effective import is_besieged, is_bypassed, is_friendly_locale
    other = "muslim" if side == "christian" else "christian"
    for locale_id in route:
        # Enemy Lord present unless Besieged/Bypassed
        for lord in state.lords.values():
            if (lord.side == other and lord.cylinder.kind == "locale"
                    and lord.cylinder.locale_id == locale_id):
                if not (is_besieged(state, lord.id) or is_bypassed(state, lord.id)):
                    return True
        # Enemy Stronghold (Locale not Friendly to active side and has Stronghold)
        loc = state.locales[locale_id]
        if loc.base_type != "region" and not is_friendly_locale(state, locale_id, side):
            # An Enemy Stronghold is exempt only if Besieged or Bypassed by us
            if not ((side == "christian" and (loc.siege_yellow > 0 or loc.bypass_yellow))
                    or (side == "muslim" and (loc.siege_green > 0 or loc.bypass_green))):
                return True
    return False


def _h_cmd_supply(state, action):
    """4.6 Supply: 1 action. Active Lord (not Besieged) supplies from
    one or more of his own Seats. For each Seat used as Source:
    +1 Provender on the Lord's mat.

    Phase 5b implements two cases:
      (a) Lord at his own Seat: trivial +1 Prov, no Transport needed
          (rule 4.6.1 'Lord at his Seat needs no Transport for that Seat').
      (b) Lord adjacent to a free own Seat via Road: 1 Cart or Mule
          consumed for the intervening Way; +1 Prov.

    Multi-hop routes (2+ Ways) are deferred — they require a graph-
    search planner. Q-001 candidate if/when the agent needs them
    before they're implemented.
    """
    from almoravid.effective import is_besieged
    from almoravid.map import neighbors_via

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord — reveal a card first",
             code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} is not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord cannot Supply (4.2.1 / 4.6)",
             code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale",
             code="not_on_map")
    _require(state.meta.actions_remaining >= 1,
             "Supply costs 1 action; none remaining",
             code="not_enough_actions")

    seats = _own_seats(state, lord_id)
    _require(seats, f"{lord_id} has no printed Seats; Supply impossible",
             code="no_own_seat")

    here = lord.cylinder.locale_id
    seats_at_here = [s for s in seats if s == here]
    seats_adjacent_road = []
    for s in seats:
        if s == here:
            continue
        # Phase 5b: only 1-hop Road routes (no Pass routes — Cart can't
        # cross Pass with Prov anyway; 4.6.1 doesn't forbid Mule on Pass
        # but the simplified route check is Road-only for now).
        if s in neighbors_via(here, "road"):
            seats_adjacent_road.append(s)

    used_seat = action.get("source_seat")
    if used_seat is None:
        # Default: prefer at-here Seat, else first adjacent Road Seat.
        if seats_at_here:
            used_seat = seats_at_here[0]
        elif seats_adjacent_road:
            used_seat = seats_adjacent_road[0]
        else:
            raise IllegalAction(
                f"{lord_id} has no Supply-reachable Seat in Phase 5b "
                f"(at-here or 1-hop Road). Multi-hop routes are Q-001 work.",
                code="no_supply_route",
            )
    _require(used_seat in seats,
             f"{used_seat} is not an own Seat for {lord_id}",
             code="bad_seat")

    transport_consumed = None
    if used_seat == here:
        # At own Seat — no Transport (rule 4.6.1).
        pass
    elif used_seat in seats_adjacent_road:
        # Route blocking check (1-hop route is just [used_seat]).
        if _route_blocked_by_enemy(state, [used_seat], side):
            raise IllegalAction(
                f"Supply route via {used_seat} blocked by Enemy "
                f"Stronghold or Lord (4.6.1)",
                code="route_blocked",
            )
        # Need 1 Cart or Mule for the intervening Way.
        has_cart = lord.assets.get("cart", 0) > 0
        has_mule = lord.assets.get("mule", 0) > 0
        # Phase 5b: prefer Mule (lighter, won't be needed for Pass anyway).
        if has_mule:
            transport_consumed = "mule"
        elif has_cart:
            transport_consumed = "cart"
        else:
            raise IllegalAction(
                "Supply route needs 1 Cart or Mule for the intervening Way "
                "(4.6.1)",
                code="no_transport",
            )
        # Note: Transport is DEDICATED to the route for this Supply
        # action, not consumed permanently. Phase 5b doesn't model the
        # Dedicate / restore cycle; left intact on the mat.
    else:
        raise IllegalAction(
            f"Seat {used_seat} not reachable from {here} in Phase 5b",
            code="no_supply_route",
        )

    # Apply: +1 Provender (cap at 8 per Pattern 12 / rule 1.7.3).
    new_prov = min(8, lord.assets.get("prov", 0) + 1)
    lord.assets["prov"] = new_prov
    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{side} {lord_id} Supplies from {used_seat} (+1 Prov -> {new_prov})"
            + (f" via {transport_consumed}" if transport_consumed else " (at-Seat)"))
    return {"source_seat": used_seat, "transport": transport_consumed,
            "prov_after": new_prov,
            "actions_remaining": state.meta.actions_remaining}


# ---------------------------------------------------------------------------
# 4.7.3 Tax (Phase 5b)
# ---------------------------------------------------------------------------


def _h_cmd_tax(state, action):
    """4.7.3 Tax: end-of-card action. Lord at his own Seat (and not
    Besieged) adds 1 Coin to his mat. Uses the ENTIRE Command card —
    consumes all remaining actions.
    """
    from almoravid.effective import is_besieged

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord cannot Tax (4.7.3)",
             code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale",
             code="not_on_map")
    here = lord.cylinder.locale_id
    seats = _own_seats(state, lord_id)
    _require(here in seats,
             f"Tax requires Lord at own Seat; {lord_id} is at {here} "
             f"(seats: {seats})",
             code="not_at_own_seat")

    new_coin = min(8, lord.assets.get("coin", 0) + 1)
    lord.assets["coin"] = new_coin
    # Tax consumes the entire card.
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    _record(state, action,
            f"{side} {lord_id} Taxes at {here} (+1 Coin -> {new_coin}); "
            f"card spent ({consumed} actions consumed)")
    return {"coin_after": new_coin, "actions_consumed": consumed}



# ---------------------------------------------------------------------------
# 4.7.1 Forage (Phase 5c)
# ---------------------------------------------------------------------------


def _h_cmd_forage(state, action):
    """4.7.1 Forage: 1 action. Two eligibility paths:

      (a) Locale Unravaged AND Lord Unbesieged: roll 1d6, 1-3 add
          1 Provender, 4-6 nothing.
      (b) Locale is Friendly City or Fortress (Gardens): auto-add
          1 Provender. Besieged Lord may use Forage Gardens only when
          inside his own Friendly Stronghold (4.7.1 Gardens exemption).

    Pattern 12: Provender capped at 8 (rule 1.7.3).
    """
    from almoravid.effective import has_gardens, is_besieged, is_friendly_locale
    from almoravid.rng import roll_d6

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    _require(state.meta.actions_remaining >= 1,
             "Forage costs 1 action", code="not_enough_actions")

    here = lord.cylinder.locale_id
    loc = state.locales[here]
    gardens_path = (has_gardens(state, here)
                    and is_friendly_locale(state, here, side))
    besieged = is_besieged(state, lord_id)
    if besieged:
        # Besieged Lord may Forage only via the Gardens path.
        _require(gardens_path,
                 "Besieged Lord may Forage only at Friendly City/Fortress "
                 "Gardens (4.7.1)",
                 code="besieged_no_gardens")
    elif gardens_path:
        pass  # Friendly Stronghold: auto path
    else:
        # Open Forage requires Unravaged
        _require(loc.ravaged == "none",
                 f"Cannot Forage Ravaged Locale {here}",
                 code="ravaged")

    if gardens_path:
        new_prov = min(8, lord.assets.get("prov", 0) + 1)
        lord.assets["prov"] = new_prov
        _record(state, action,
                f"{side} {lord_id} Forages Gardens at {here} (+1 Prov -> "
                f"{new_prov})")
        state.meta.actions_remaining -= 1
        return {"path": "gardens", "prov_after": new_prov, "roll": None,
                "actions_remaining": state.meta.actions_remaining}

    # Open Forage: 1d6 roll.
    roll = roll_d6(state)
    if roll <= 3:
        new_prov = min(8, lord.assets.get("prov", 0) + 1)
        lord.assets["prov"] = new_prov
        result = "success"
    else:
        new_prov = lord.assets.get("prov", 0)
        result = "fail"
    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{side} {lord_id} Forages at {here} (roll={roll} -> {result}, "
            f"prov={new_prov})")
    return {"path": "open", "roll": roll, "result": result,
            "prov_after": new_prov,
            "actions_remaining": state.meta.actions_remaining}


# ---------------------------------------------------------------------------
# 4.7.2 Ravage (Phase 5c)
# ---------------------------------------------------------------------------


def _h_cmd_ravage(state, action):
    """4.7.2 Ravage: 1 action. Not Besieged. Enemy Locale not already
    Ravaged by this side.

    Effects:
      - Place this side's Ravaged marker (yellow=Christian, green=Muslim).
      - VP adjust: 1/2 VP per Ravaged marker (5.1).
      - Rustling: at Stronghold +1 Loot AND +1 Prov; at Region +1 Loot.
      - Enforcing Parias: if this is the 1st, 3rd, 5th... CHRISTIAN
        (yellow) Ravaged marker in the Taifa, shift that Taifa Lord's
        (not Yusuf/Sir/Rodrigo) Service 1 box left. Phase 5c stub: log
        the trigger; actual Service shift lands with Calendar mutators.
    """
    from almoravid.effective import is_besieged, is_friendly_locale

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord cannot Ravage (4.7.2)", code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    _require(state.meta.actions_remaining >= 1,
             "Ravage costs 1 action", code="not_enough_actions")

    here = lord.cylinder.locale_id
    loc = state.locales[here]
    # Enemy Locale: not Friendly to active side (rule 4.7.2 "locale_is_enemy")
    _require(not is_friendly_locale(state, here, side),
             f"Cannot Ravage Friendly Locale {here}", code="friendly_locale")
    # Already Ravaged by this side check.
    color = "yellow" if side == "christian" else "green"
    _require(loc.ravaged != color,
             f"{here} already Ravaged by {side} (color {color})",
             code="already_ravaged_by_us")

    # Place Ravaged marker; rule 4.7.2: each side has at most one
    # Ravaged marker per Locale. The other side's marker is overwritten
    # only per Adjust-Status (1.4.3); for now if the locale has the
    # opposite-color marker, the rule says we still place ours (the
    # Locale ends up with one of each — represented here by overwriting
    # with our color since the model only stores one). Q-001 candidate.
    loc.ravaged = color  # type: ignore[assignment]

    # Rustling: assets to the Ravaging Lord.
    if loc.base_type == "region":
        new_loot = min(8, lord.assets.get("loot", 0) + 1)
        lord.assets["loot"] = new_loot
        rustling_note = f"+1 Loot -> {new_loot} (Region)"
    else:
        new_loot = min(8, lord.assets.get("loot", 0) + 1)
        new_prov = min(8, lord.assets.get("prov", 0) + 1)
        lord.assets["loot"] = new_loot
        lord.assets["prov"] = new_prov
        rustling_note = f"+1 Loot -> {new_loot}, +1 Prov -> {new_prov} (Stronghold)"

    # VP: 1/2 per Ravaged marker (5.1)
    if side == "christian":
        state.score.christian += 0.5
    else:
        state.score.muslim += 0.5

    # Enforcing Parias trigger check: count Christian Ravage markers in
    # this Taifa AFTER placing the new one. If the count is odd, the
    # Service-shift hook fires.
    enforcing_parias = False
    if side == "christian" and loc.territory in state.taifas:
        taifa_ravage_count = sum(
            1 for lid in state.taifas[loc.territory].locale_ids
            if state.locales[lid].ravaged == "yellow"
        )
        if taifa_ravage_count % 2 == 1:
            enforcing_parias = True
            # Phase 5c: log only. Service-shift implementation needs the
            # Calendar mutators (shift_service_left, off-edge handling
            # per Pattern 6 / SMOKE-062). Q-NNN candidate.

    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{side} {lord_id} Ravages {here}: {rustling_note}, "
            f"+0.5 VP{', Enforcing Parias triggered (Service shift TODO)' if enforcing_parias else ''}")
    return {"locale": here, "color": color, "rustling": rustling_note,
            "enforcing_parias": enforcing_parias,
            "actions_remaining": state.meta.actions_remaining}



# ---------------------------------------------------------------------------
# 4.5.1 Siege (Phase 5d minimal-viable)
# ---------------------------------------------------------------------------


def _h_cmd_siege(state, action):
    """4.5.1 Siege: end-of-card action.

    Active Lord at an Enemy Stronghold (Locale with Stronghold not
    Friendly to active side) — including with Bypass or existing Siege
    markers — places one additional Siege marker of his color. Cap at
    4 markers per side (SoP max_siege_markers: 4).

    Phase 5d scope: Siegeworks bonus (extra marker when total Lords-
    here meets the Stronghold's Capacity per 4.5.1) IS implemented;
    Surrender check (dice vs siege+ravage markers) is Phase 5+ work,
    pending the dice/Conquest mechanics that overlap with Battle.
    Bypass-to-Siege transition is also Phase 5+.

    Uses entire Command card per SoP §4.5.1.
    """
    from almoravid.effective import is_besieged, is_friendly_locale

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord cannot Siege (4.5.1)", code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    here = lord.cylinder.locale_id
    loc = state.locales[here]
    _require(loc.base_type != "region",
             f"Siege requires a Stronghold; {here} is a Region",
             code="region_no_siege")
    _require(not is_friendly_locale(state, here, side),
             f"Cannot Siege Friendly Locale {here}",
             code="friendly_locale")

    color = "yellow" if side == "christian" else "green"
    marker_field = "siege_yellow" if color == "yellow" else "siege_green"
    current = getattr(loc, marker_field)
    _require(current < 4,
             f"{here} already has {current} {color} Siege markers (max 4)",
             code="siege_cap_reached")

    # Count Lords here on our side for Siegeworks Capacity check
    lords_here_our_side = sum(
        1 for other in state.lords.values()
        if other.side == side
        and other.cylinder.kind == "locale"
        and other.cylinder.locale_id == here
    )
    from almoravid.static_data import load_strongholds
    capacity = load_strongholds()["strongholds"][loc.base_type]["capacity"]
    siegeworks = lords_here_our_side >= capacity

    # Place +1 marker (or +2 if Siegeworks and room).
    placed = 1
    setattr(loc, marker_field, current + 1)
    if siegeworks and current + 1 < 4:
        setattr(loc, marker_field, current + 2)
        placed = 2

    # End-of-card: consume all remaining actions (SoP end_card_action).
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    _record(state, action,
            f"{side} {lord_id} Siege {here}: placed {placed} {color} marker(s)"
            f" (total {getattr(loc, marker_field)})"
            + (f"; Siegeworks (capacity {capacity}, "
               f"{lords_here_our_side} lords here)" if siegeworks else "")
            + f"; card spent ({consumed} actions)")
    return {"locale": here, "color": color, "placed": placed,
            "total_markers": getattr(loc, marker_field),
            "siegeworks": siegeworks, "actions_consumed": consumed}


CAMPAIGN_HANDLERS = {
    "begin_campaign": _h_begin_campaign,
    "plan_add_card": _h_plan_add_card,
    "finalize_plan": _h_finalize_plan,
    "command_reveal": _h_command_reveal,
    "end_card": _h_end_card,
    "cmd_pass": _h_cmd_pass,
    "cmd_march": _h_cmd_march,
    "cmd_supply": _h_cmd_supply,
    "cmd_tax": _h_cmd_tax,
    "cmd_forage": _h_cmd_forage,
    "cmd_ravage": _h_cmd_ravage,
    "cmd_siege": _h_cmd_siege,
    "end_campaign": _h_end_campaign,
}
