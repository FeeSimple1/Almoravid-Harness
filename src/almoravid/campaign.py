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
        # Rule 4.2.3 / 4.1.3: a Lower Lord's own Command card is passed
        # (he moves only when his Lieutenant activates).
        elif lord.is_lieutenant and lord.lieutenant_of is not None:
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

    # A Lord is now active for effective-Command actions (rule 1.5.3:
    # base Command rating + Mesnada/Hasham +1 capability bonuses).
    assert entry.lord_id is not None
    lord = state.lords[entry.lord_id]
    from almoravid.capabilities import effective_command
    cmd = effective_command(state, entry.lord_id)
    state.meta.active_lord_id = entry.lord_id
    state.meta.actions_remaining = cmd
    _record(state, action,
            f"{side} reveals command card for {entry.lord_id} "
            f"({cmd} actions)")
    return {"revealed": entry.model_dump(), "auto_pass": False,
            "active_lord_id": entry.lord_id,
            "actions_remaining": cmd}


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


def _feed_lord(state: GameState, lord_id: str, *,
                force: bool = False) -> dict[str, Any]:
    """Rule 4.8.1 Feed: a Lord who Moved/Fought this card consumes
    ceil((units + mules) / 6) Provender or Loot. Unfed -> Service
    marker shifts 1 box left.

    Phase 6h: `force=True` bypasses the moved_fought guard so event
    cards (C4/M4 Arid Terrain, C5/M5 Drought) can compel an immediate
    Feed regardless of whether the Lord has acted yet.
    """
    import math
    lord = state.lords[lord_id]
    if not force and not lord.moved_fought:
        return {"skipped": "did_not_move_fight", "consumed": 0}
    units = sum(lord.forces.values())
    mules = lord.assets.get("mule", 0)
    needed = math.ceil((units + mules) / 6) if (units + mules) > 0 else 0
    prov = lord.assets.get("prov", 0)
    loot = lord.assets.get("loot", 0)
    use_prov = min(prov, needed)
    short_after = needed - use_prov
    use_loot = min(loot, short_after)
    short = short_after - use_loot
    lord.assets["prov"] = prov - use_prov
    lord.assets["loot"] = loot - use_loot
    unfed = False
    if short > 0:
        sm = next((s for s in state.calendar.service_markers
                   if s.lord_id == lord_id), None)
        if sm is not None:
            sm.box = max(0, sm.box - 1)
        unfed = True
    return {"consumed": use_prov + use_loot, "needed": needed,
            "short": short, "unfed_penalty": unfed,
            "use_prov": use_prov, "use_loot": use_loot}


def _auto_disband_at_service_limit(state: GameState, lord_id: str) -> dict[str, Any]:
    """Rule 4.8.3 / 3.3.2: auto-Disband when Lord's Service marker is
    at or beyond the Campaign marker. Uses _compute_disband_target_box
    so Errata p.12 'next box if Campaign' (Bug N) is honored.
    """
    from almoravid.actions import _compute_disband_target_box
    from almoravid.state import Cylinder
    lord = state.lords[lord_id]
    sm = next((s for s in state.calendar.service_markers
               if s.lord_id == lord_id), None)
    # Service marker at-or-before current Campaign box -> at-Service-limit
    if sm is None:
        return {"no_op": True, "reason": "no service marker (already off-Calendar)"}
    if sm.box > state.calendar.current_box:
        return {"no_op": True, "reason": "not at service limit"}
    new_box = _compute_disband_target_box(state, lord)
    if new_box > 16:
        new_box = 17
        state.calendar.off_right.append(lord_id)
    lord.cylinder = Cylinder(kind="calendar", box=new_box)
    # Pattern 8: cleanup
    lord.forces = {}
    lord.assets = {}
    lord.capabilities = []
    lord.vassals = []
    lord.in_stronghold = False
    lord.moved_fought = False
    lord.routed_units = {}
    state.calendar.service_markers = [
        s for s in state.calendar.service_markers if s.lord_id != lord_id
    ]
    return {"disbanded": lord_id, "to_box": new_box}


def _clear_per_card_event_flags(state) -> None:
    """Phase 6h: clear card-scope event flags at end_card."""
    state.meta.swollen_river_blocked_card_lord_id = None


def _h_end_card(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """End the currently-active Lord's card. Runs the rule 4.8 cascade.

    Phase 5h + deferred fix: auto-Feed via _feed_lord, then auto-
    Disband if the Lord is at-or-beyond Service limit (rule 4.8.3 /
    3.3.2). Voluntary Pay during the FPD step uses the same
    pay_lord handler the Levy step uses but during Campaign is not
    yet exposed via legal_moves; agent-driven Pay during FPD is a
    Q-NNN candidate for when scenarios demand it.
    """
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord — reveal a card first",
             code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    # 4.8.1 Feed
    feed_result = _feed_lord(state, lord_id)
    # 4.8.3 auto-Disband at service limit (deferred fix landed here)
    disband_result = _auto_disband_at_service_limit(state, lord_id)
    # Bookkeeping
    state.meta.active_lord_id = None
    state.meta.actions_remaining = 0
    # Pattern 3 per-card flag reset (only if Lord still exists in state
    # — disband doesn't remove Lord from state.lords, just changes
    # cylinder, so this is safe)
    if lord.cylinder.kind == "locale":
        lord.lordship_used = 0
        lord.first_march_used_this_card = False
        lord.raiders_used_this_card = False
        lord.moved_fought = False
    _clear_per_card_event_flags(state)
    _advance_or_end_campaign(state)
    _record(state, action,
            f"{side} ends {lord_id}'s card; Feed: "
            f"consumed={feed_result.get('consumed',0)} "
            f"short={feed_result.get('short',0)} "
            f"unfed={feed_result.get('unfed_penalty', False)}"
            + (f"; auto-disband {disband_result}"
               if disband_result.get('disbanded') else "")
            + (f" -> campaign_step={state.meta.campaign_step}"
               if state.meta.campaign_step != "activation" else ""))
    return {"ended": lord_id, "feed": feed_result,
            "auto_disband": disband_result,
            "campaign_step": state.meta.campaign_step}


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
    # Phase 7c: unstack all Lieutenants / Lower Lords (4.1.3).
    _unstack_all_lieutenants(state)
    # Phase 7g: Wastage (4.9.4) — each Mustered Lord with more than one
    # of any Asset type, or more than one This-Lord Capability card,
    # discards one excess (greedy: drop one Asset of the largest stack,
    # else one This-Lord Capability).
    _apply_wastage(state)
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
        verdict = compute_victory(state)
        _record(state, action,
                f"Campaign end at box {prev_box}; scenario ended "
                f"(off calendar); winner={verdict['winner']}")
        return {"phase": "ended", "current_box": prev_box,
                "victory": verdict}
    state.calendar.current_box = new_box
    # If new box has scenario_end marker, end the game
    new_box_obj = state.calendar.boxes[new_box - 1]
    if "scenario_end" in new_box_obj.decorations:
        state.meta.phase = "ended"
        verdict = compute_victory(state)
        _record(state, action,
                f"Campaign end; advanced box {prev_box} -> {new_box} "
                f"(Scenario End); winner={verdict['winner']}")
        return {"phase": "ended", "current_box": new_box,
                "victory": verdict}
    # Otherwise return to Levy
    state.meta.phase = "levy"
    state.meta.campaign_step = None
    state.meta.levy_step = "arts_of_war"
    state.meta.levy_step_completed_christian = False
    state.meta.levy_step_completed_muslim = False
    state.meta.cta_option_used_christian = False
    state.meta.cta_option_used_muslim = False
    state.meta.cta_crusade_jihad_pending = False
    state.meta.active_player = ACTOR_ORDER[0]
    state.meta.turn_index += 1

    # Deferred fix: Scenario F Curias / Winter / Spring Muster auto-wire.
    # When the Calendar advances into box 5 or 6 (Autumn 1085), run
    # check_curias; if triggered, run apply_curias which advances the
    # Levy marker to box 7. When advancing into box 7, run winter_disband.
    # When advancing into box 9 (end of box 8 Spring Muster), run
    # spring_muster.
    auto_actions: list[dict[str, object]] = []
    if state.meta.scenario_letter == "F":
        if new_box in (5, 6):
            r_curias = check_curias(state)
            if r_curias["triggered"]:
                applied = apply_curias(state, new_box)
                auto_actions.append({"curias": applied})
                new_box = state.calendar.current_box  # may have advanced to 7
        if new_box == 7:
            wd = winter_disband(state)
            auto_actions.append({"winter_disband": wd})
        if new_box == 9:
            sm = spring_muster(state)
            auto_actions.append({"spring_muster": sm})

    _record(state, action,
            f"End Campaign; advanced box {prev_box} -> {new_box}; back to Levy"
            + (f"; auto: {auto_actions}" if auto_actions else ""))
    return {"phase": state.meta.phase, "current_box": new_box,
            "turn_index": state.meta.turn_index,
            "auto_actions": auto_actions}


# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 6.2 Curias check + 6.3 Winter Sequence (Phase 5k — Scenario F only)
# ---------------------------------------------------------------------------


def check_curias(state) -> dict:
    """Rule 6.2: Curias check at start of Autumn (box 5) and again at
    box 6 if not triggered in 5. Only applies in Scenario F.

    Condition: Locales (NOT Taifas Box) have MORE total yellow (Christian)
    Conquered + Ravaged markers than green (Muslim) Conquered + Ravaged +
    Jihad markers.

    Returns dict with {triggered: bool, yellow_count, green_count}.
    """
    yellow = 0
    green = 0
    for loc in state.locales.values():
        # Conquered markers: store side via territory context.
        # Phase 1 simplification: conquered_markers is a single counter;
        # we attribute by territory's allegiance (Muslim Taifa -> Christian
        # placed). Phase 5k will refine if needed.
        if loc.territory in state.taifas:
            # Muslim Taifa: yellow Conquered markers (Christian conquered)
            yellow += loc.conquered_markers
            green += loc.jihad_markers
        elif loc.territory in ("leon", "aragon"):
            # Christian Kingdom: green Conquered markers (Muslim conquered)
            green += loc.conquered_markers
        if loc.ravaged == "yellow":
            yellow += 1
        elif loc.ravaged == "green":
            green += 1
    return {"triggered": yellow > green,
            "yellow_count": yellow, "green_count": green}


def apply_curias(state, box: int) -> dict:
    """Rule 6.2 trigger actions. Returns dict describing the cascade.

    Place a Curias marker in the current box (and a 2nd in box 6 if firing
    at box 5). Remove 1 yellow Conquered marker from the Taifas box per
    Curias marker placed (adjust VP). Advance Levy marker to box 7.
    Shift Service markers of Beyond-Service Lords (box <= current box)
    forward to box 7. If Pedro Ansurez and/or Garcia Ordonez on map,
    Disband them (3.3.2).
    """
    # Place Curias marker in current box (and a 2nd in box 6 if firing
    # at box 5).
    placed = []
    state.calendar.boxes[box - 1].decorations.append("curias")
    placed.append(box)
    if box == 5:
        state.calendar.boxes[5].decorations.append("curias")  # box 6 (index 5)
        placed.append(6)

    # Phase 5k baseline: deduct from Christian VP for each Curias marker
    # placed (treating Taifas Box 1VP markers as already-counted yellow
    # Conquered that get reversed by Curias). The actual Taifas Box marker
    # model is small enough to add when Phase 5l Adjust Status lands.
    state.score.christian = max(0, state.score.christian - len(placed))

    # Advance Levy marker to box 7
    state.calendar.current_box = 7

    # Shift Beyond-Service Lords (Service marker at box <= prior current
    # box) forward to box 7.
    shifted = []
    for sm in list(state.calendar.service_markers):
        if sm.box <= box:
            sm.box = 7
            shifted.append(sm.lord_id)

    # Disband Pedro Ansurez / Garcia Ordonez if on map
    disbanded = []
    from almoravid.state import Cylinder
    for lid in ("pedro_ansurez", "garcia_ordonez"):
        l = state.lords.get(lid)
        if l is None or l.cylinder.kind != "locale":
            continue
        # Apply Phase 5g _h_disband_lord behavior inline
        new_box = state.calendar.current_box + l.service_rating
        if new_box > 16:
            new_box = 17
            state.calendar.off_right.append(lid)
        l.cylinder = Cylinder(kind="calendar", box=new_box)
        l.forces = {}
        l.assets = {}
        l.capabilities = []
        l.vassals = []
        l.in_stronghold = False
        l.moved_fought = False
        l.routed_units = {}
        state.calendar.service_markers = [
            s for s in state.calendar.service_markers if s.lord_id != lid
        ]
        disbanded.append(lid)

    return {"curias_placed_in_boxes": placed,
            "service_shifted_lords": shifted,
            "auto_disbanded": disbanded}


def winter_disband(state) -> dict:
    """Rule 6.3.1 Winter Disband at box 7 (Scenario F only).

    Mustered Lords (except those at Sieges) Disband to their mats:
    clear mat fields, place cylinder on mat (not Calendar). Disbanding
    Taifa Lords put all Coin from mats into the Taifas box. If
    Disbanding either Rodrigo, cylinder goes to Calendar box 9 even
    if Beyond Service. Discard all board-edge Capabilities.

    Phase 5k baseline: applies the structural pieces (cylinder->mat,
    clear forces/assets/caps, Rodrigo->box 9). Taifas-box coin
    aggregation is a stub; full pool model lands with the Taifas Box
    state expansion.
    """
    from almoravid.state import Cylinder
    results = {"disbanded_to_mat": [], "rodrigo_to_box_9": [],
               "lords_at_sieges_kept": [], "board_edge_discarded": []}

    for lid, l in state.lords.items():
        if l.cylinder.kind != "locale":
            continue
        loc = state.locales[l.cylinder.locale_id]
        # Lord at an active Siege keeps for Winter Siege step
        at_siege = (loc.siege_yellow > 0 or loc.siege_green > 0)
        if at_siege:
            results["lords_at_sieges_kept"].append(lid)
            continue
        if lid in ("rodrigo_campeador", "rodrigo_al_sayyid"):
            l.cylinder = Cylinder(kind="calendar", box=9)
            results["rodrigo_to_box_9"].append(lid)
        else:
            l.cylinder = Cylinder(kind="mat")
            results["disbanded_to_mat"].append(lid)
        # Clear cleanup_on_removal_fields except: cylinder already set,
        # we DO keep capabilities on mat (3.4.1 - they re-Muster with the
        # Lord). Actually per 6.3.1 we 'clear each mat' — so capabilities
        # too go. But the cards aren't lost — board-edge holds them.
        l.forces = {}
        l.assets = {}
        l.capabilities = []
        l.in_stronghold = False
        l.moved_fought = False
        l.routed_units = {}

    # Discard board-edge Capabilities
    for side in ("christian", "muslim"):
        edge = state.decks.board_edge.get(side, [])
        if edge:
            state.decks.discard.extend(edge)
            results["board_edge_discarded"].extend(edge)
        state.decks.board_edge[side] = []

    # Clear Service markers (6.3.1 Disbands)
    state.calendar.service_markers = []
    return results


def spring_muster(state) -> dict:
    """Rule 6.3.3 Spring Muster at end of box 8 (Scenario F only).

    Christian Lords on mats automatically Muster — cylinder to a free
    Seat, Service markers ahead. Lords with no free Seat go to Calendar
    as if Disbanded this turn. Then Muslim Lords likewise; Taifa Lords
    with no free Seat go to Calendar and adjust Taifa status.
    """
    from almoravid.state import Cylinder, ServiceMarker
    from almoravid.static_data import load_lords
    results = {"christian_mustered": [], "muslim_mustered": [],
               "no_free_seat": []}
    static = load_lords()["lords"]

    for side in ("christian", "muslim"):
        for lid, l in state.lords.items():
            if l.side != side:
                continue
            if l.cylinder.kind != "mat":
                continue
            free_seats = []
            for seat in l.seats:
                # Free = no Enemy Lord present
                enemy_here = any(
                    o for o in state.lords.values()
                    if o.side != side
                    and o.cylinder.kind == "locale"
                    and o.cylinder.locale_id == seat
                )
                if not enemy_here:
                    free_seats.append(seat)
            if free_seats:
                # Alfonso prefers Leon (per Scenario F rule)
                if lid == "alfonso" and "leon" in free_seats:
                    chosen = "leon"
                else:
                    chosen = free_seats[0]
                l.cylinder = Cylinder(kind="locale", locale_id=chosen)
                l.forces = dict(static[lid]["forces"])
                l.assets = dict(static[lid]["assets"])
                # Service marker advanced
                new_box = state.calendar.current_box + l.service_rating
                state.calendar.service_markers.append(
                    ServiceMarker(lord_id=lid, box=min(new_box, 17)))
                results[f"{side}_mustered"].append((lid, chosen))
            else:
                # No free Seat: place on Calendar
                new_box = state.calendar.current_box + l.service_rating
                l.cylinder = Cylinder(kind="calendar",
                                       box=min(new_box, 17))
                results["no_free_seat"].append(lid)
    return results





# ---------------------------------------------------------------------------
# 1.4.3 Adjust Status cascade (Phase 5l)
# ---------------------------------------------------------------------------


def adjust_taifa_status(state, taifa_id: str, new_status: str) -> dict:
    """Apply a Taifa status transition and its cascades per 1.4.3.

    Returns dict with the cascade effects: ravaged flips, forced Conquests,
    Siege removals, etc.

    The full cascades from Quick Ref Table 5:

      INDEPENDENT -> PARIAS:
        - Christians +Coin = Service of disbanded Taifa Lord (handled
          by caller when called from Disband path).
        - Muslim Lord at Muslim Stronghold that would go Neutral:
          add Jihad (Conquer).
        - Christian Lord at Muslim Stronghold that would go Neutral:
          remove Siege/Bypass OR add Jihad (markers = value).
      INDEPENDENT -> RECONQUISTA:
        - Flip yellow Ravaged in Taifa to green.
        - Muslim Lord at Muslim Stronghold that would go Christian:
          add Jihad.
        - Christian Lord at Muslim Stronghold that goes Christian:
          remove Siege/Bypass.
      PARIAS -> INDEPENDENT:
        - Flip green Ravaged to yellow.
        - Christian Lord at Neutral Stronghold that would go Muslim:
          Conquer them.
      PARIAS -> RECONQUISTA:
        - Flip yellow Ravaged to green.
        - Muslim Lord at Neutral Stronghold that would go Christian:
          add Jihad.
      RECONQUISTA -> INDEPENDENT:
        - Flip green Ravaged to yellow.
        - Christian Lord at Christian Stronghold that would go Muslim:
          Conquer them.
        - Muslim Lord at Christian Stronghold that goes Muslim:
          remove Siege/Bypass.
      RECONQUISTA -> PARIAS:
        - Christian Lord at Christian Stronghold that would go Neutral:
          Conquer them.
        - Muslim Lord at Christian Stronghold that would go Neutral:
          remove Siege/Bypass OR add Christian Conquered (= value).

    Phase 5l baseline: applies the structural pieces deterministically.
    "OR" choices (remove Siege OR add Jihad) are resolved toward the
    option that's more conservative (remove Siege) to keep the cascade
    confined; in future the agent could be asked to choose.
    """
    taifa = state.taifas.get(taifa_id)
    if taifa is None:
        return {"no_op": True, "reason": f"unknown taifa {taifa_id}"}
    old_status = taifa.status
    if old_status == new_status:
        return {"no_op": True, "reason": "no change"}

    results = {"taifa_id": taifa_id, "from": old_status, "to": new_status,
               "ravaged_flips": [], "auto_conquered": [],
               "siege_removed": [], "jihad_added": []}
    taifa.status = new_status

    # Determine the transition and apply the cascade.
    flip_color_from, flip_color_to = None, None
    if (old_status, new_status) in (
        ("independent", "reconquista"), ("parias", "reconquista")
    ):
        flip_color_from, flip_color_to = "yellow", "green"
    elif (old_status, new_status) in (
        ("parias", "independent"), ("reconquista", "independent")
    ):
        flip_color_from, flip_color_to = "green", "yellow"
    # Flip Ravaged markers in this Taifa
    if flip_color_from:
        for lid in taifa.locale_ids:
            if state.locales[lid].ravaged == flip_color_from:
                state.locales[lid].ravaged = flip_color_to  # type: ignore[assignment]
                results["ravaged_flips"].append((lid, flip_color_from, flip_color_to))

    # Force-Siege / force-Conquest at each Stronghold in the Taifa based
    # on Lord presence (1.4.3).
    going_muslim_friendly = (new_status == "independent")
    going_christian_friendly = (new_status == "reconquista")
    going_neutral = (new_status == "parias")

    for lid in taifa.locale_ids:
        loc = state.locales[lid]
        if loc.base_type == "region":
            continue
        # Find Lords present at this Locale (one of each side, generally)
        present_christian = [
            l.id for l in state.lords.values()
            if l.side == "christian"
            and l.cylinder.kind == "locale"
            and l.cylinder.locale_id == lid
        ]
        present_muslim = [
            l.id for l in state.lords.values()
            if l.side == "muslim"
            and l.cylinder.kind == "locale"
            and l.cylinder.locale_id == lid
        ]
        # Muslim Lord at Muslim Stronghold "would go Neutral or Christian"
        if going_neutral or going_christian_friendly:
            if present_muslim:
                # Add Jihad markers (Conquer per Muslim side).
                sh_value = {"city": 3, "fortress": 2, "town": 1, "castle": 1}.get(
                    loc.base_type, 0)
                loc.jihad_markers += sh_value
                results["jihad_added"].append((lid, sh_value))
        # Christian Lord at Muslim Stronghold "goes Christian": remove Siege/Bypass
        if going_christian_friendly:
            if present_christian and (loc.siege_yellow > 0 or loc.bypass_yellow):
                loc.siege_yellow = 0
                loc.bypass_yellow = False
                results["siege_removed"].append(lid)
        # Bug A (mirror gap audit): RECONQUISTA -> INDEPENDENT —
        # Muslim Lord at Christian Stronghold that goes Muslim:
        # remove Siege/Bypass (1.4.3).
        if (old_status == "reconquista"
                and new_status == "independent"):
            if present_muslim and (loc.siege_green > 0 or loc.bypass_green):
                loc.siege_green = 0
                loc.bypass_green = False
                results["siege_removed"].append((lid, "muslim"))
        # Bug B (mirror gap audit): RECONQUISTA -> PARIAS —
        # Muslim Lord at Christian Stronghold that would go Neutral:
        # OR clause (1.4.3). Phase 5l conservative resolution: remove
        # Siege/Bypass rather than place Christian Conquered markers.
        if (old_status == "reconquista" and new_status == "parias"):
            if present_muslim and (loc.siege_green > 0 or loc.bypass_green):
                loc.siege_green = 0
                loc.bypass_green = False
                results["siege_removed"].append((lid, "muslim_or_clause"))
        # Bug C (mirror gap audit): INDEPENDENT -> PARIAS —
        # Christian Lord at Muslim Stronghold that would go Neutral:
        # OR clause (1.4.3). Conservative: remove Siege/Bypass.
        if (old_status == "independent" and new_status == "parias"):
            if present_christian and (loc.siege_yellow > 0 or loc.bypass_yellow):
                loc.siege_yellow = 0
                loc.bypass_yellow = False
                results["siege_removed"].append((lid, "christian_or_clause"))
        # Christian Lord at Neutral Stronghold "would go Muslim": Conquer
        if going_neutral or (new_status == "independent"
                              and old_status != "independent"):
            if present_christian and old_status in ("parias", "reconquista"):
                # Christian Conquers the Stronghold
                from almoravid.static_data import load_strongholds
                sh_value = load_strongholds()["strongholds"][loc.base_type]["value"]
                loc.conquered_markers += sh_value
                state.score.christian += sh_value
                results["auto_conquered"].append((lid, "christian", sh_value))
    return results


def maybe_recompute_taifa_status(state, taifa_id: str) -> dict:
    """Re-evaluate a Taifa's status based on current map state per 1.4.1.

    Status rules:
      - Reconquista: ALL Cities and Seats in the Taifa are Christian-
        conquered (yellow Conquered markers covering each).
      - Parias: at least one unconquered City or Seat AND no Taifa Lord
        on the map.
      - Independent: Taifa Lord on the map AND at least one unconquered
        City or Seat. (And not Reconquista.)

    Special: Toledo can never be Independent (rule 1.4.1 note).
    """
    from almoravid.static_data import load_lords
    taifa = state.taifas.get(taifa_id)
    if taifa is None:
        return {"no_op": True}
    # Find Cities + printed Seats in the Taifa
    target_locales = [
        lid for lid in taifa.locale_ids
        if state.locales[lid].base_type in ("city", "fortress", "town",
                                              "castle")
        and (state.locales[lid].is_reconquista_target
             or lid in [
                 seat for l in state.lords.values()
                 for seat in l.seats if l.home_taifa == taifa_id
             ])
    ]
    all_christian = all(
        state.locales[lid].conquered_markers > 0
        for lid in target_locales
    ) if target_locales else False
    # Taifa Lord on map?
    taifa_lord_on_map = any(
        l.is_taifa
        and l.home_taifa == taifa_id
        and l.cylinder.kind == "locale"
        for l in state.lords.values()
    )
    new_status = taifa.status  # default no change
    if all_christian and target_locales:
        new_status = "reconquista"
    elif not taifa_lord_on_map:
        if not target_locales or any(
            state.locales[lid].conquered_markers == 0
            for lid in target_locales
        ):
            new_status = "parias"
        else:
            new_status = "reconquista"
    else:
        new_status = "independent"
    # Toledo: never Independent
    if taifa_id == "toledo" and new_status == "independent":
        new_status = "parias"
    if new_status != taifa.status:
        return adjust_taifa_status(state, taifa_id, new_status)
    return {"no_op": True, "current_status": taifa.status}


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

    # Phase 6h: enemy Hold-event auto-triggers on March.
    enemy = _other(side)
    enemy_hold = state.decks.this_levy_events.get(enemy, [])
    # C3/M3 Swollen River: blocks this and any further March on the
    # current Command card by this Lord.
    if state.meta.swollen_river_blocked_card_lord_id == lord_id:
        raise IllegalAction(
            f"Swollen River already blocked {lord_id}'s March on this card",
            code="swollen_river_blocked",
        )
    swollen_id = "C3" if enemy == "christian" else "M3"
    if swollen_id in enemy_hold:
        # Adalides (C3/C10, Christian this_lord, Phase 7a): if the
        # Marching Christian Lord has Adalides, Muslim Swollen River
        # (M3) is discarded without effect (M3 Tips / rule 1.9.1).
        from almoravid.capabilities import capabilities_for_lord
        adalides = (side == "christian" and swollen_id == "M3"
                    and bool(set(capabilities_for_lord(state, lord_id))
                             & {"C3", "C10"}))
        enemy_hold.remove(swollen_id)
        state.decks.discard.append(swollen_id)
        if adalides:
            _record(state, action,
                    f"Adalides cancels {enemy} Swollen River ({swollen_id}) "
                    f"at {lord_id}'s Locale — no effect")
        else:
            state.meta.swollen_river_blocked_card_lord_id = lord_id
            raise IllegalAction(
                f"Swollen River ({swollen_id}) played by {enemy} blocks "
                f"{lord_id}'s March on this card (4.3.4)",
                code="swollen_river_blocked",
            )
    # C4/M4 Arid Terrain: forces an immediate Feed on the Marching Lord
    # BEFORE the March (per Tips). Discards regardless of Feed outcome.
    arid_id = "C4" if enemy == "christian" else "M4"
    if arid_id in enemy_hold:
        enemy_hold.remove(arid_id)
        state.decks.discard.append(arid_id)
        # Camels (M16, Muslim side_wide, Phase 7a): the Muslim player
        # may discard Camels to ignore Arid Terrain. Greedy: auto-
        # discard when the marching side is Muslim and holds Camels.
        from almoravid.capabilities import side_has_capability
        camels_negate = (side == "muslim"
                         and side_has_capability(state, "muslim", "M16"))
        if camels_negate:
            # Remove Camels from play (board-edge + capabilities_in_play).
            state.decks.capabilities_in_play = [
                c for c in state.decks.capabilities_in_play
                if c.card_id != "M16"
            ]
            for edge in state.decks.board_edge.values():
                if "M16" in edge:
                    edge.remove("M16")
            state.decks.discard.append("M16")
            _record(state, action,
                    f"Muslim discards Camels (M16) to ignore Arid "
                    f"Terrain ({arid_id})")
        else:
            _feed_lord(state, lord_id, force=True)
            _record(state, action,
                    f"{enemy} Arid Terrain ({arid_id}) forces "
                    f"{lord_id} to Feed before March")

    # Phase 6i: C6 Surprise auto-trigger for Christian attacker.
    # When Christian holds C6 AND Marches to an Enemy Stronghold
    # locale that contains NO Lord (either side), place 2 Siege
    # markers and queue a forced Storm with Walls -1 via
    # state.meta.surprise_storm_pending_locale_id.
    if side == "christian" and "C6" in state.decks.this_levy_events.get(
            "christian", []):
        target_loc = state.locales[target]
        from almoravid.effective import is_friendly_locale
        is_enemy_stronghold = (target_loc.base_type != "region"
                               and not is_friendly_locale(state, target,
                                                          "christian"))
        any_lord_there = any(
            l.cylinder.kind == "locale" and l.cylinder.locale_id == target
            for l in state.lords.values()
        )
        if is_enemy_stronghold and not any_lord_there:
            state.decks.this_levy_events["christian"].remove("C6")
            state.decks.discard.append("C6")
            # Place 2 Siege markers (instead of usual 1 from Bypass).
            target_loc.siege_yellow = min(4, target_loc.siege_yellow + 2)
            state.meta.surprise_storm_pending_locale_id = target
            _record(state, action,
                    f"christian Surprise (C6) at {target}: placed 2 Siege, "
                    f"forced Storm with Walls -1 pending")

    # Execute March.
    from almoravid.state import Cylinder
    # Group March (4.3.1): Lower Lords stacked with this Lieutenant at
    # the same Locale move along for the same action.
    group_followers = [
        l for l in state.lords.values()
        if l.lieutenant_of == lord_id and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == from_loc
    ]
    lord.cylinder = Cylinder(kind="locale", locale_id=target)
    for follower in group_followers:
        follower.cylinder = Cylinder(kind="locale", locale_id=target)
        follower.in_stronghold = False
        follower.moved_fought = True
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

    # Phase 6b — rule 4.3.4 Approach trigger. If an Unbesieged/Unbypassed
    # enemy Lord (not inside a Stronghold) is at `target`, the defender
    # owes a response: Avoid Battle, Withdraw, or Stand & Fight.
    trigger = _check_approach_trigger(
        state, target, side, from_loc, way_type, lord_id,
    )
    base = {"from": from_loc, "to": target, "way_type": way_type,
            "laden": laden, "cost": cost,
            "actions_remaining": state.meta.actions_remaining}
    if trigger is not None:
        base["pending"] = trigger
    return base



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





def _find_supply_routes(state, here: str, seats: list[str],
                          side, lord) -> dict[str, list[str] | None]:
    """BFS from `here` looking for an unblocked path to each Seat.

    Returns {seat_id: route_locale_list_or_None}. The route list
    excludes `here` and ends at the Seat. If no unblocked route
    exists, the value is None.

    Per 4.6.1: route may not include a Locale with an Enemy
    Stronghold or Lord (unless Besieged or Bypassed by us).
    Supply uses Road OR Pass — Mule can go either way; Cart can't
    cross a Pass with Prov but for Supply the route doesn't carry
    Prov, so Cart on Pass is allowed for Supply purposes.
    """
    from almoravid.map import neighbors_via
    seat_set = set(seats)
    target_routes: dict[str, list[str] | None] = {s: None for s in seats}
    if here in seat_set:
        target_routes[here] = []
    # BFS; expand each node along Road + Pass; stop at a Seat or
    # blocked Locale.
    visited: dict[str, list[str]] = {here: []}
    queue: list[str] = [here]
    while queue:
        node = queue.pop(0)
        nbrs = (neighbors_via(node, "road")
                + neighbors_via(node, "pass"))
        for nbr in nbrs:
            if nbr in visited:
                continue
            # Block on Enemy Stronghold / Lord per 4.6.1 (skip the
            # destination Seat itself — by definition our own Seat,
            # not Enemy).
            if nbr in seat_set:
                # Reached a Seat. Record route and continue (Seats
                # don't propagate further as intervening Locales).
                visited[nbr] = visited[node] + [nbr]
                target_routes[nbr] = visited[nbr]
                continue
            # Not a Seat — check blocking
            if _route_blocked_by_enemy(state, [nbr], side):
                continue
            visited[nbr] = visited[node] + [nbr]
            queue.append(nbr)
    return target_routes

def _h_cmd_supply(state, action):
    """4.6 Supply: 1 action. Active Lord (not Besieged) supplies from
    one or more of his own Seats. For each Seat used as Source:
    +1 Provender on the Lord's mat.

    Full rule 4.6.1: a Lord may use one OR MORE of his own Seats as
    Sources in a single Supply action, gaining +1 Provender per Seat.
    Each non-here Seat needs a multi-hop unblocked Supply Route (BFS
    via _find_supply_routes), dedicating 1 Cart/Mule per intervening
    Way; the at-here Seat needs no Transport. Routes may not pass
    through an Enemy Stronghold/Lord unless Besieged or Bypassed.
    Provender caps at 8 (1.7.3). Dawud ibn Aisha (M8) adds +1 once.
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
    # Find the shortest unblocked route from `here` to each of `seats`,
    # consuming 1 Cart/Mule per intervening Way (rule 4.6.1). Multi-hop
    # via BFS. Lord at his Seat needs no Transport for that Seat.
    routes = _find_supply_routes(state, here, seats, side, lord)

    # Multiple Seats may be used as Sources in one Supply action
    # (rule 4.6.1: "+1 Provender per Seat used"). Accept either
    # source_seats (list) or source_seat (single). Default: the
    # at-here Seat if present, else the single nearest reachable Seat.
    requested = action.get("source_seats")
    if requested is None:
        single = action.get("source_seat")
        if single is not None:
            requested = [single]
    if requested is None:
        if here in seats:
            requested = [here]
        else:
            reachable = [(s, r) for s, r in routes.items() if r is not None]
            if not reachable:
                raise IllegalAction(
                    f"{lord_id} has no reachable Seat for Supply "
                    f"(no route found honoring 4.6.1 constraints)",
                    code="no_supply_route",
                )
            reachable.sort(key=lambda kv: len(kv[1]))
            requested = [reachable[0][0]]

    for s in requested:
        _require(s in seats, f"{s} is not an own Seat for {lord_id}",
                 code="bad_seat")
    _require(len(set(requested)) == len(requested),
             "duplicate Seat in source_seats", code="bad_arg")

    # Total dedicated Transport = sum of intervening Ways over all
    # non-here Seats. At-here Seat needs none.
    total_hops = 0
    per_seat_hops: dict[str, int] = {}
    for s in requested:
        if s == here:
            per_seat_hops[s] = 0
            continue
        route = routes.get(s)
        if route is None:
            raise IllegalAction(
                f"Supply route to {s} is blocked by Enemy Stronghold "
                f"or Lord (4.6.1)",
                code="no_supply_route",
            )
        per_seat_hops[s] = len(route)
        total_hops += len(route)

    has_cart = lord.assets.get("cart", 0)
    has_mule = lord.assets.get("mule", 0)
    if has_cart + has_mule < total_hops:
        raise IllegalAction(
            f"Supply needs {total_hops} Cart/Mule(s) for "
            f"{requested}; have {has_cart} Cart + {has_mule} Mule (4.6.1)",
            code="no_transport",
        )
    if total_hops > 0:
        if has_mule >= total_hops:
            transport_consumed = f"{total_hops} mule"
        elif has_cart >= total_hops:
            transport_consumed = f"{total_hops} cart"
        else:
            transport_consumed = (
                f"{has_mule} mule + {total_hops - has_mule} cart")
    else:
        transport_consumed = None

    # Apply: +1 Provender per Seat (cap 8). Dawud ibn Aisha (M8,
    # Phase 7a) adds 1 extra Prov per Supply action (once).
    from almoravid.capabilities import lord_has_capability
    gain = len(requested)
    if lord_has_capability(state, lord_id, "M8"):
        gain += 1
    new_prov = min(8, lord.assets.get("prov", 0) + gain)
    lord.assets["prov"] = new_prov
    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{side} {lord_id} Supplies from {requested} "
            f"(+{gain} Prov -> {new_prov})"
            + (f" via {transport_consumed}" if transport_consumed
               else " (at-Seat)"))
    return {"source_seats": requested, "transport": transport_consumed,
            "prov_after": new_prov, "prov_gained": gain,
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

    # War Drums (M22, Muslim side_wide, Phase 7a): Yusuf, Sir, and
    # Muslim Lieutenants Ravage for 1 extra Prov.
    from almoravid.capabilities import side_has_capability
    war_drums_bonus = 0
    if (side == "muslim"
            and side_has_capability(state, "muslim", "M22")
            and (lord_id in ("yusuf", "sir") or lord.is_lieutenant)):
        war_drums_bonus = 1

    # Rustling: assets to the Ravaging Lord.
    if loc.base_type == "region":
        new_loot = min(8, lord.assets.get("loot", 0) + 1)
        lord.assets["loot"] = new_loot
        rustling_note = f"+1 Loot -> {new_loot} (Region)"
        if war_drums_bonus:
            new_prov = min(8, lord.assets.get("prov", 0) + war_drums_bonus)
            lord.assets["prov"] = new_prov
            rustling_note += f", +{war_drums_bonus} Prov (War Drums) -> {new_prov}"
    else:
        new_loot = min(8, lord.assets.get("loot", 0) + 1)
        new_prov = min(8, lord.assets.get("prov", 0) + 1 + war_drums_bonus)
        lord.assets["loot"] = new_loot
        lord.assets["prov"] = new_prov
        rustling_note = (f"+1 Loot -> {new_loot}, "
                         f"+{1 + war_drums_bonus} Prov -> {new_prov} "
                         f"(Stronghold{'/War Drums' if war_drums_bonus else ''})")

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
            # Deferred fix: rule 4.7.2 — shift the Taifa Lord's Service
            # 1 box left (NOT Yusuf / Sir / either Rodrigo per AoW
            # reference text). Vassal Service markers also shift if
            # advanced Vassal Service rule (3.4.2) is in use; that
            # rule isn't yet active in this harness, so we shift the
            # Lord's marker only.
            from almoravid.actions import _shift_service_left
            for tlid, tlord in state.lords.items():
                if (tlord.is_taifa
                        and tlord.home_taifa == loc.territory
                        and tlid not in ("yusuf", "sir",
                                         "rodrigo_campeador",
                                         "rodrigo_al_sayyid")):
                    _shift_service_left(state, tlid, 1)

    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{side} {lord_id} Ravages {here}: {rustling_note}, "
            f"+0.5 VP{', Enforcing Parias triggered (Service shift TODO)' if enforcing_parias else ''}")
    return {"locale": here, "color": color, "rustling": rustling_note,
            "enforcing_parias": enforcing_parias,
            "actions_remaining": state.meta.actions_remaining}



# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 4.5.1 Surrender + 1.3.1 / 1.4.4 Conquest (Phase 5i)
# ---------------------------------------------------------------------------


def _ravaged_count_in_taifa_for_side(state, locale_id: str, side) -> int:
    """Count Ravaged markers of `side`'s color in the Taifa containing
    locale_id. Used by Surrender (4.5.1) — die rolls cancel if <=
    siege_markers + ravaged_markers_of_besieging_side.
    """
    loc = state.locales[locale_id]
    taifa = state.taifas.get(loc.territory)
    if taifa is None:
        return 0
    color = "yellow" if side == "christian" else "green"
    return sum(
        1 for lid in taifa.locale_ids
        if state.locales[lid].ravaged == color
    )


def _conquer_stronghold(state, locale_id: str, conquering_side) -> dict:
    """Apply Conquest of a Stronghold (rule 1.4.4, 4.5.1 Surrender,
    4.5.2 Storm victory, 4.5.3 Sally retreat).

    Effects:
      - Place Conquered or Jihad markers per Taifa status (per Quick
        Reference Table 4 — see Phase 5l for the full Adjust Status
        cascade).
      - Remove Siege markers there.
      - Adjust VP (1.3.1: 1 VP per Conquered; 1/2 VP per Jihad).
      - Phase 5i baseline ignores Taifa-status-transition cascades —
        those are Phase 5l Adjust Status work.

    Returns dict with marker counts placed and VP delta.
    """
    from almoravid.static_data import load_strongholds
    loc = state.locales[locale_id]
    if loc.base_type == "region":
        return {"no_op": True, "reason": "region_no_stronghold"}
    sh_value = load_strongholds()["strongholds"][loc.base_type]["value"]
    taifa = state.taifas.get(loc.territory)
    # Determine marker type (Quick Reference Table 4):
    # Independent + Christian conquers: Conquered (1 VP × value)
    # Reconquista + Muslim conquers: Jihad (1/2 VP × value)
    # Parias + either: 1 VP / 0.5 VP per side
    # For Phase 5i baseline, use a simplified rule:
    #   - Christian conquers Muslim: place Conquered yellow markers
    #   - Muslim conquers Christian: place Conquered green markers
    #   - Muslim conquers Conquered (Reconquista) Christian Stronghold:
    #     place Jihad markers
    # 1.4.4 / 4.5: Muslim Conquest of ANY Stronghold in a Parias or
    # Reconquista Taifa places Jihad markers (1 per Stronghold Value)
    # AND removes any Christian Conquered + Christian Seat markers
    # there. Christian Conquest (anywhere), and Muslim Conquest of a
    # Christian Kingdom, place Conquered markers AND remove all Jihad.
    # A Locale never holds both Conquered and Jihad markers.
    is_taifa = taifa is not None
    place_jihad = (conquering_side == "muslim" and is_taifa
                   and taifa.status in ("parias", "reconquista"))
    removed = {}
    if place_jihad:
        if loc.conquered_markers:
            removed["conquered"] = loc.conquered_markers
            loc.conquered_markers = 0
        # Remove Christian Seat markers (Muslim Jihad cannot coexist).
        christian_seats = [sid for sid in loc.seat_marker_lord_ids
                           if state.lords.get(sid)
                           and state.lords[sid].side == "christian"]
        if christian_seats:
            removed["christian_seats"] = christian_seats
            loc.seat_marker_lord_ids = [
                sid for sid in loc.seat_marker_lord_ids
                if sid not in christian_seats]
        loc.jihad_markers += sh_value
        vp_delta = 0.5 * sh_value
        marker = "jihad"
    else:
        if loc.jihad_markers:
            removed["jihad"] = loc.jihad_markers
            loc.jihad_markers = 0
        # Conquered markers = exactly the Stronghold Value (1.3.1).
        loc.conquered_markers = sh_value
        vp_delta = 1.0 * sh_value
        marker = "conquered"
    # Remove the Conquering side's Siege markers (Conquest ends Siege).
    if conquering_side == "christian":
        loc.siege_yellow = 0
        state.score.christian += vp_delta
    else:
        loc.siege_green = 0
        state.score.muslim += vp_delta
    return {"locale": locale_id, "marker": marker, "value": sh_value,
            "vp_delta": vp_delta, "conquered_total": loc.conquered_markers,
            "jihad_total": loc.jihad_markers, "removed": removed}



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

    from almoravid.static_data import load_strongholds
    from almoravid.rng import roll_d6_n
    capacity = load_strongholds()["strongholds"][loc.base_type]["capacity"]
    sh_value = load_strongholds()["strongholds"][loc.base_type]["value"]

    enemy_inside = any(
        l for l in state.lords.values()
        if l.side != side and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == here and l.in_stronghold
    )

    # --- 4.5.1 SURRENDER? (FIRST, before Siegeworks; only if no
    # Besieged Lords inside). Dice = Stronghold VP; each die must be
    # <= (Siege markers there, max 4) + (Ravaged marker there, max 1).
    surrender_result = None
    surrendered = False
    do_surrender = action.get("surrender", True) and not enemy_inside
    if do_surrender:
        # C21 Mozarabes auto-success in a Reconquista Taifa.
        c21_held = (side == "christian" and "C21" in
                    state.decks.this_levy_events.get("christian", []))
        target_taifa = state.taifas.get(loc.territory)
        c21_eligible = (c21_held and target_taifa is not None
                        and target_taifa.status == "reconquista")
        # Ravaged marker THERE (at the Locale), of the besieging side,
        # capped at 1 (rule 4.5.1).
        ravaged_here = 1 if loc.ravaged == color else 0
        threshold = min(4, current) + ravaged_here
        if c21_eligible:
            state.decks.this_levy_events["christian"].remove("C21")
            state.decks.discard.append("C21")
            dice = []
            cancellations = sh_value
            threshold = "auto_mozarabes"
        else:
            dice = roll_d6_n(state, sh_value)
            cancellations = sum(1 for d in dice if d <= threshold)
        if cancellations == sh_value:
            surrendered = True
            conq_result = _conquer_stronghold(state, here, side)
            # Surrender provides NO Spoils (4.5.1 Terms). C9 Betrayal of
            # Terms (Christian) overrides: take Spoils as if Sack, OR
            # double + Muslims add 1 Jihad.
            from almoravid.battle import distribute_spoils_round_robin
            sh = load_strongholds()["strongholds"][loc.base_type]
            base_spoils = {k: v for k, v in sh.get("spoils", {}).items()
                           if k in ("coin", "loot", "prov")}
            c9_held = (side == "christian" and "C9" in
                       state.decks.this_levy_events.get("christian", []))
            spoils = {}
            if c9_held:
                multiplier = 2
                spoils = {k: v * multiplier for k, v in base_spoils.items()}
                friendly_here = [
                    l.id for l in state.lords.values()
                    if l.side == side and l.cylinder.kind == "locale"
                    and l.cylinder.locale_id == here
                ]
                if friendly_here and spoils:
                    distribute_spoils_round_robin(state, friendly_here, spoils)
                state.decks.this_levy_events["christian"].remove("C9")
                state.decks.discard.append("C9")
                from almoravid.events import _add_jihad
                _add_jihad(state, 1, {})
            surrender_result = {"dice": dice, "threshold": threshold,
                                "succeeded": True, "conquest": conq_result,
                                "spoils": spoils, "c9_betrayal_used": c9_held}
        else:
            surrender_result = {"dice": dice, "threshold": threshold,
                                "succeeded": False}

    # --- 4.5.1 SIEGEWORKS: only if the Stronghold did NOT Surrender
    # (incl. declined to roll), and the besieging side has Lords >=
    # Capacity. Add exactly ONE marker, max 4.
    placed = 0
    siegeworks = False
    if not surrendered:
        lords_here_our_side = sum(
            1 for other in state.lords.values()
            if other.side == side and other.cylinder.kind == "locale"
            and other.cylinder.locale_id == here
        )
        siegeworks = lords_here_our_side >= capacity
        if siegeworks and current < 4:
            setattr(loc, marker_field, current + 1)
            placed = 1

    # End-of-card: consume all remaining actions (SoP end_card_action).
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    _record(state, action,
            f"{side} {lord_id} Siege {here}: placed {placed} {color} marker(s)"
            f" (total {getattr(loc, marker_field)})"
            + (f"; Siegeworks (capacity {capacity}, "
               f"{lords_here_our_side} lords here)" if siegeworks else "")
            + (f"; Surrender check: {surrender_result}"
               if surrender_result else "")
            + f"; card spent ({consumed} actions)")
    return {"locale": here, "color": color, "placed": placed,
            "total_markers": getattr(loc, marker_field),
            "siegeworks": siegeworks, "surrender": surrender_result,
            "actions_consumed": consumed}



# ---------------------------------------------------------------------------
# 4.4 Battle (Phase 5e — single-Lord baseline; multi-Lord arrays land
# with Reserve/Flanking handling in Phase 5e+).
# ---------------------------------------------------------------------------


def _h_cmd_battle(state, action):
    """4.4 Battle: end-of-card action.

    Active Lord at a Locale containing exactly one Enemy Lord triggers
    a Battle. Both Lords participate; Battle resolution is deterministic
    per seed.

    Phase 5e: only single-Lord-each-side Battles supported. If multiple
    Lords are on either side at the Locale, raises IllegalAction with
    code='multi_lord_battle' (Phase 5e+ work).
    """
    from almoravid.battle import (
        apply_aftermath,
        battleside_for_lord,
        battleside_for_lords,
        commit_forces_after_battle,
        resolve_battle,
    )
    from almoravid.effective import is_besieged

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _apply_absorption_policy(state, side, action)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord cannot Battle; must Sally instead (4.5.3)",
             code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    here = lord.cylinder.locale_id

    # Find enemy Lord(s) at this Locale
    other = "muslim" if side == "christian" else "christian"
    enemy_lord_ids = [
        l.id for l in state.lords.values()
        if l.side == other
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == here
        and not is_besieged(state, l.id)  # 4.4 doesn't engage besieged Lords here
    ]
    _require(enemy_lord_ids, f"No Enemy Lord at {here} to Battle",
             code="no_enemy")
    # Deferred fix: multi-Lord aggregation. All Lords of each side at the
    # Locale (not inside a Stronghold and not Besieged) participate per
    # rule 4.3.4 'ALL Lords at the Locale not inside a Stronghold must
    # participate'. Forces, capabilities pooled; aftermath distributes
    # losses back proportionally. Full Array (Front/Reserve/Flanking)
    # is a Phase 6 refinement.
    our_at_here = [
        l.id for l in state.lords.values()
        if l.side == side
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == here
        and not l.in_stronghold
    ]
    other = "muslim" if side == "christian" else "christian"
    atk = battleside_for_lords(state, our_at_here, side, "attacker")
    dfd = battleside_for_lords(state, enemy_lord_ids, other, "defender")
    result = resolve_battle(state, atk, dfd)
    commit_forces_after_battle(state, atk)
    commit_forces_after_battle(state, dfd)
    # Bug P fix: Retreat aftermath FIRST so C7 opt-out can fire.
    from almoravid.battle import (
        apply_retreat_aftermath, apply_battle_losses,
    )
    retreat_summary = apply_retreat_aftermath(state, result)
    losses = apply_battle_losses(state, result, retreat_summary)
    apply_aftermath(state, result)

    # Battle ends the card (rule 4.4.5).
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0

    _record(state, action,
            f"{side} {our_at_here} Battles {enemy_lord_ids} at {here}: "
            f"winner={result.winner}, rounds={len(result.rounds)}; "
            f"card spent ({consumed} actions)")
    return {
        "winner": result.winner,
        "rounds": len(result.rounds),
        "attacker_routed": dict(atk.routed_units),
        "defender_routed": dict(dfd.routed_units),
        "actions_consumed": consumed,
        "retreat_summary": retreat_summary,
    }



# ---------------------------------------------------------------------------
# 4.5.2 Storm + 4.5.3 Sally (Phase 5f)
# ---------------------------------------------------------------------------


def _h_cmd_storm(state, action):
    """4.5.2 Storm. Active Lord outside a Besieged Stronghold (i.e.,
    with at least one of our Siege markers at the Locale) assaults
    the defending Garrison + any besieged enemy Lords inside.

    Uses entire card. Resolution via battle.resolve_storm.
    """
    from almoravid.battle import (
        BattleSide,
        apply_aftermath,
        battleside_for_lord,
        commit_forces_after_battle,
        resolve_storm,
    )
    from almoravid.effective import is_besieged, is_friendly_locale

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, code="wrong_side",
             message=f"{lord_id} not on {side}'s side") if False else _require(lord.side == side, f"{lord_id} not on {side}'s side", code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord must Sally not Storm", code="besieged")
    _apply_absorption_policy(state, side, action)
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    here = lord.cylinder.locale_id
    loc = state.locales[here]
    _require(loc.base_type != "region",
             f"No Stronghold at {here} to Storm", code="region_no_storm")
    _require(not is_friendly_locale(state, here, side),
             f"Cannot Storm Friendly Stronghold {here}",
             code="friendly_locale")
    siege_markers = (loc.siege_yellow if side == "christian"
                     else loc.siege_green)
    _require(siege_markers > 0,
             f"No {side} Siege at {here}; place a Siege first",
             code="no_siege")

    # Find enemy Lords inside the Stronghold (defenders)
    enemy_inside = [
        l.id for l in state.lords.values()
        if l.side != side
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == here
        and l.in_stronghold
    ]
    atk = battleside_for_lord(state, lord_id, "attacker")
    # Build defender side. If multiple Lords inside, aggregate (Phase 5f).
    if enemy_inside:
        dfd_forces: dict = {}
        dfd_caps: list[str] = []
        for eid in enemy_inside:
            for ut, n in state.lords[eid].forces.items():
                dfd_forces[ut] = dfd_forces.get(ut, 0) + n
            dfd_caps.extend(state.lords[eid].capabilities)
        dfd = BattleSide(
            side=("muslim" if side == "christian" else "christian"),
            role="defender",
            lord_ids=enemy_inside,
            forces=dfd_forces,
            capabilities_in_play=dfd_caps,
        )
    else:
        # No defending Lord — pure Garrison defense.
        dfd = BattleSide(
            side=("muslim" if side == "christian" else "christian"),
            role="defender",
            lord_ids=[],
            forces={},
            capabilities_in_play=[],
        )
    # Phase 6i: C6 Surprise pending → modify walls_range to -1.
    surprise_loc = state.meta.surprise_storm_pending_locale_id
    if surprise_loc == here:
        from almoravid.static_data import load_strongholds
        base_walls = load_strongholds()["strongholds"][loc.base_type]["walls_range"]
        modified_walls = (base_walls[0], max(0, base_walls[1] - 1))
        result = resolve_storm(state, atk, dfd, walls_range_override=modified_walls)
        state.meta.surprise_storm_pending_locale_id = None
    else:
        result = resolve_storm(state, atk, dfd)
    commit_forces_after_battle(state, atk)
    # Defender: only commit back if single-Lord (Phase 5f limit)
    if len(dfd.lord_ids) == 1:
        commit_forces_after_battle(state, dfd)

    # 4.5.2 SACK: if the Besieged Defenders lose the Storm, the
    # Stronghold is Sacked.
    conq_result = None
    sack = None
    if result.winner == side:
        from almoravid.battle import distribute_spoils_round_robin
        from almoravid.state import Cylinder
        from almoravid.actions import _shift_service_left as _ssl
        from almoravid.static_data import load_strongholds as _ls
        # Besieging Lords present (Spoils recipients).
        besiegers_here = [
            l.id for l in state.lords.values()
            if l.side == side and l.cylinder.kind == "locale"
            and l.cylinder.locale_id == here
        ]
        sack_spoils: dict[str, int] = {}
        removed_lords: list[str] = []
        # (a) Permanently remove all losing Lords (3.3.1); award all
        #     their Assets as Spoils (4.4.3) — capture BEFORE cleanup.
        for eid in enemy_inside:
            elord = state.lords[eid]
            for atype, n in list(elord.assets.items()):
                if n > 0:
                    sack_spoils[atype] = sack_spoils.get(atype, 0) + n
            for fld in elord.cleanup_on_removal_fields:
                try:
                    setattr(elord, fld, type(getattr(elord, fld))())
                except Exception:
                    pass
            elord.cylinder = Cylinder(kind="removed")
            _ssl(state, eid, boxes=20)
            removed_lords.append(eid)
        # (b) Conquer the Stronghold as per Surrender (4.5.1).
        conq_result = _conquer_stronghold(state, here, side)
        # (c) In addition, award Stronghold Spoils (table) to besiegers.
        sh_spoils = _ls()["strongholds"][loc.base_type].get("spoils", {})
        for k in ("coin", "loot", "prov"):
            if sh_spoils.get(k):
                sack_spoils[k] = sack_spoils.get(k, 0) + sh_spoils[k]
        if besiegers_here and sack_spoils:
            distribute_spoils_round_robin(state, besiegers_here, sack_spoils)
        sack = {"removed_lords": removed_lords, "spoils": sack_spoils,
                "recipients": besiegers_here}

    # 4.5.2 -> 4.4.4 Losses: both sides roll for Routed units. The
    # Storm Attacker's Routed units always need a 1; the Defender
    # always rolls Protection (handled by apply_battle_losses storm
    # flag + winner path). Then 4.4.5 Aftermath.
    from almoravid.battle import apply_battle_losses
    apply_battle_losses(state, result, {"losers": []}, storm=True)
    apply_aftermath(state, result)

    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    _record(state, action,
            f"{side} {lord_id} Storms {here}: winner={result.winner}, "
            f"rounds={len(result.rounds)}"
            + (f", Sack: {sack}" if sack else "")
            + f"; card spent ({consumed} actions)")
    return {"winner": result.winner, "rounds": len(result.rounds),
            "conquest": conq_result, "sack": sack,
            "actions_consumed": consumed}


def _h_cmd_sally(state, action):
    """4.5.3 Sally. Besieged Lord attacks the besieger.

    Uses entire card. If Sally loses, sallying Lords Withdraw back
    inside; Siege markers reduce to 1.
    """
    from almoravid.battle import (
        BattleSide,
        apply_sally_aftermath,
        battleside_for_lord,
        commit_forces_after_battle,
        resolve_sally,
    )
    from almoravid.effective import is_besieged

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _apply_absorption_policy(state, side, action)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(is_besieged(state, lord_id),
             "Sally requires Besieged Lord (4.5.3)", code="not_besieged")
    here = lord.cylinder.locale_id  # type: ignore[union-attr]

    # Find besieging Lord(s) outside the Stronghold at this Locale
    other = "muslim" if side == "christian" else "christian"
    besiegers = [
        l.id for l in state.lords.values()
        if l.side == other
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == here
        and not l.in_stronghold
    ]
    _require(besiegers, f"No besiegers to Sally against at {here}",
             code="no_besiegers")
    atk = battleside_for_lord(state, lord_id, "attacker")
    atk.lord_ids = [lord_id]  # the sallying Lord
    # Sally exits the Stronghold for the duration of the Sally
    state.lords[lord_id].in_stronghold = False

    # Build defender side (besiegers)
    dfd_forces: dict = {}
    dfd_caps: list[str] = []
    for bid in besiegers:
        for ut, n in state.lords[bid].forces.items():
            dfd_forces[ut] = dfd_forces.get(ut, 0) + n
        dfd_caps.extend(state.lords[bid].capabilities)
    dfd = BattleSide(
        side=other,
        role="defender",
        lord_ids=besiegers,
        forces=dfd_forces,
        capabilities_in_play=dfd_caps,
    )
    result = resolve_sally(state, atk, dfd)
    commit_forces_after_battle(state, atk)
    if len(dfd.lord_ids) == 1:
        commit_forces_after_battle(state, dfd)
    apply_sally_aftermath(state, result, here)

    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    _record(state, action,
            f"{side} {lord_id} Sallies at {here}: winner={result.winner}, "
            f"rounds={len(result.rounds)}; card spent ({consumed} actions)")
    return {"winner": result.winner, "rounds": len(result.rounds),
            "actions_consumed": consumed}




# ---------------------------------------------------------------------------
# Phase 6b: rule 4.3.4 Approach / Avoid / Withdraw / Stand-and-Fight.
# ---------------------------------------------------------------------------


def _check_approach_trigger(
    state, locale_id: str, active_side: Side,
    from_locale_id: str, way_type: str, active_lord_id: str,
) -> dict[str, Any] | None:
    """If an Unbesieged/Unbypassed enemy Lord is at `locale_id` not
    inside a Stronghold, set a PendingDecision and return the payload.
    Otherwise return None.

    Pattern 11 (active-player desync): swaps active_player to the
    defender side so the response handler can be invoked.
    """
    from almoravid.effective import is_besieged, is_bypassed
    from almoravid.state import PendingDecision
    other = _other(active_side)
    defenders = [
        l.id for l in state.lords.values()
        if l.side == other
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == locale_id
        and not l.in_stronghold
        and not is_besieged(state, l.id)
        and not is_bypassed(state, l.id)
    ]
    if not defenders:
        return None
    payload = {
        "locale_id": locale_id,
        "from_locale_id": from_locale_id,
        "via_way_type": way_type,
        "active_lord_id": active_lord_id,
        "active_side": active_side,
        "defender_lord_ids": defenders,
    }
    state.pending = PendingDecision(
        kind="march_arrival_response",
        waiting_on=other,
        payload=payload,
    )
    # Pattern 11: waiting_on == active_player while pending is set.
    state.meta.active_player = other
    return dict(payload)


def _clear_approach_pending(state, original_active: Side) -> None:
    """Clear the PendingDecision and restore active_player to the
    marching side so their card continues."""
    state.pending = None
    state.meta.active_player = original_active


def _require_pending(state, kind: str, side: Side):
    pd = state.pending
    _require(pd is not None and pd.kind == kind,
             f"no pending {kind} decision", code="no_pending")
    _require(pd.waiting_on == side,
             f"pending decision waiting on {pd.waiting_on}, not {side}",
             code="not_responder")
    return pd


def _h_respond_avoid_battle(state, action):
    """4.3.4 Avoid Battle. Defender Lords move together to an adjacent
    Locale that:
      - is not the Locale the Active side came from (way_not_used_by_enemy_approach)
      - has no Unbesieged enemy Lord
      - is reachable via the requested way_type

    Args:
      side: defender side
      target_locale_id: where to move to
      way_type: 'road' | 'pass'
    """
    from almoravid.effective import is_besieged
    from almoravid.map import neighbors_via
    from almoravid.state import Cylinder

    side = _require_side(action)
    pd = _require_pending(state, "march_arrival_response", side)
    payload = pd.payload
    locale_id = payload["locale_id"]
    from_locale = payload["from_locale_id"]
    active_side = payload["active_side"]

    target = action.get("target_locale_id")
    way_type = action.get("way_type", "road")
    _require(isinstance(target, str), "target_locale_id required",
             code="bad_arg")
    _require(way_type in ("road", "pass"),
             "way_type must be road or pass", code="bad_arg")
    _require(target != from_locale,
             "Avoid Battle may not use the Way the Attacker Approached on",
             code="avoid_blocked_by_approach_way")
    nbrs = neighbors_via(locale_id, way_type)
    _require(target in nbrs,
             f"{target} not reachable from {locale_id} via {way_type}",
             code="not_adjacent")
    # Destination must not have an Unbesieged/Unbypassed enemy Lord
    # (Bug S fix — Pattern 2 mirror: trigger filters by both
    # is_besieged AND is_bypassed; this destination check must match).
    from almoravid.effective import is_bypassed
    for l in state.lords.values():
        if (l.side == active_side and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == target
                and not is_besieged(state, l.id)
                and not is_bypassed(state, l.id)):
            raise IllegalAction(
                f"Cannot Avoid into {target} — Unbesieged/Unbypassed "
                f"{active_side} Lord {l.id} present",
                code="destination_has_enemy",
            )
    # Bug Q fix (Pattern 9) — SoP requires Unladen for Avoid Battle.
    # Any Laden defender Lord blocks the Avoid.
    for lid in payload["defender_lord_ids"]:
        if lid in state.lords:
            if _is_laden(state.lords[lid]):
                raise IllegalAction(
                    f"Cannot Avoid — {lid} is Laden (SoP 4.3.4 "
                    f"avoid_battle requires Unladen)",
                    code="laden_blocks_avoid",
                )
    # Move all defender Lords. Avoid Battle does NOT mark
    # moved_fought (SoP withdraw_definition / 4.3.4 — defender
    # avoidance is reactive, not an action).
    for lid in payload["defender_lord_ids"]:
        if lid in state.lords:
            l = state.lords[lid]
            l.cylinder = Cylinder(kind="locale", locale_id=target)
            l.in_stronghold = False
    _record(state, action,
            f"{side} avoids Battle: {payload['defender_lord_ids']} "
            f"move {locale_id} -> {target} via {way_type}")
    _clear_approach_pending(state, active_side)
    return {"avoided_to": target, "lord_ids": payload["defender_lord_ids"]}


def _h_respond_withdraw(state, action):
    """4.3.4 Withdraw. Defender Lords enter Friendly Stronghold at the
    Approach Locale, up to Siege Capacity (1.3.1). Does NOT mark
    moved_fought (SoP withdraw_definition).
    """
    from almoravid.effective import is_friendly_locale
    from almoravid.static_data import load_strongholds

    side = _require_side(action)
    pd = _require_pending(state, "march_arrival_response", side)
    payload = pd.payload
    locale_id = payload["locale_id"]
    active_side = payload["active_side"]

    loc = state.locales[locale_id]
    _require(loc.base_type != "region",
             f"{locale_id} has no Stronghold — Withdraw impossible",
             code="no_stronghold")
    _require(is_friendly_locale(state, locale_id, side),
             f"{locale_id} not Friendly to {side} — Withdraw impossible",
             code="stronghold_not_friendly")
    capacity = load_strongholds()["strongholds"][loc.base_type]["capacity"]
    # Count Lords already inside the Stronghold + the withdrawing group.
    already_inside = sum(
        1 for l in state.lords.values()
        if l.cylinder.kind == "locale"
        and l.cylinder.locale_id == locale_id
        and l.in_stronghold
    )
    incoming = len(payload["defender_lord_ids"])
    _require(already_inside + incoming <= capacity,
             f"Siege Capacity {capacity} at {locale_id} would be "
             f"exceeded ({already_inside} inside + {incoming} withdrawing)",
             code="exceeds_capacity")
    for lid in payload["defender_lord_ids"]:
        if lid in state.lords:
            state.lords[lid].in_stronghold = True
    _record(state, action,
            f"{side} withdraws inside {locale_id} Stronghold "
            f"({payload['defender_lord_ids']})")
    _clear_approach_pending(state, active_side)
    return {"withdrew_to_stronghold": locale_id,
            "lord_ids": payload["defender_lord_ids"]}


def _h_respond_stand_battle(state, action):
    """4.3.4 Stand & Fight. Auto-resolve Battle with all eligible Lords
    on both sides at the Approach Locale. Battle ends the active side's
    card (rule 4.4.5)."""
    from almoravid.battle import (
        apply_aftermath,
        battleside_for_lords,
        commit_forces_after_battle,
        resolve_battle,
    )

    side = _require_side(action)
    pd = _require_pending(state, "march_arrival_response", side)
    _apply_absorption_policy(state, side, action)
    payload = pd.payload
    locale_id = payload["locale_id"]
    active_side = payload["active_side"]
    other = _other(active_side)

    attacker_lord_ids = [
        l.id for l in state.lords.values()
        if l.side == active_side
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == locale_id
        and not l.in_stronghold
    ]
    # Relief Sally (4.4.1, Phase 7f): if the Approaching side also has
    # its own Besieged Lords inside a Stronghold at this Locale, they
    # Sally out to join the Approach as relief attackers.
    from almoravid.effective import is_besieged as _isb
    relief_sally_ids = [
        l.id for l in state.lords.values()
        if l.side == active_side
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == locale_id
        and l.in_stronghold and _isb(state, l.id)
    ]
    for rid in relief_sally_ids:
        if rid not in attacker_lord_ids:
            attacker_lord_ids.append(rid)
            state.lords[rid].in_stronghold = False  # Sallied out
    defender_lord_ids = list(payload["defender_lord_ids"])
    _require(attacker_lord_ids, "no attacker Lords at Battle locale",
             code="no_attacker")
    _require(defender_lord_ids, "no defender Lords at Battle locale",
             code="no_defender")

    atk = battleside_for_lords(state, attacker_lord_ids, active_side,
                               "attacker")
    dfd = battleside_for_lords(state, defender_lord_ids, other, "defender")
    result = resolve_battle(state, atk, dfd)
    commit_forces_after_battle(state, atk)
    commit_forces_after_battle(state, dfd)
    # Bug P fix: Retreat aftermath FIRST so it can consult Hold events
    # (C7 Baggage Parapet opt-out) in this_levy_events before
    # apply_aftermath clears that bucket.
    from almoravid.battle import (
        apply_retreat_aftermath, apply_battle_losses,
    )
    retreat_summary = apply_retreat_aftermath(
        state, result,
        approach_from_locale=payload.get("from_locale_id"),
        approach_way_type=payload.get("via_way_type"),
    )
    losses = apply_battle_losses(state, result, retreat_summary)
    apply_aftermath(state, result)

    # End the active side's card (rule 4.4.5).
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    _clear_approach_pending(state, active_side)

    _record(state, action,
            f"{side} stands; Battle at {locale_id}: "
            f"winner={result.winner}, rounds={len(result.rounds)}")
    return {
        "winner": result.winner,
        "rounds": len(result.rounds),
        "attacker_routed": dict(atk.routed_units),
        "defender_routed": dict(dfd.routed_units),
        "actions_consumed": consumed,
        "retreat_summary": retreat_summary,
    }


# ---------------------------------------------------------------------------
# Phase 6k: Hold-card consumer actions.
# ---------------------------------------------------------------------------


def _h_play_pope_gregory(state, action):
    """C14 (Hold) Pope Gregory: Play on Sancho or Eudes to
    Muster him from Calendar, OR shift his Service 2 boxes right,
    OR for Lordship +2.

    Args:
      side: 'christian'
      mode: 'muster_from_calendar' | 'service_shift_right' |
            'lordship_plus_2'
      lord_id: 'sancho' | 'eudes'
    """
    side = _require_side(action)
    _require(side == "christian", "C14 is a Christian event",
             code="wrong_side")
    _require("C14" in state.decks.this_levy_events.get("christian", []),
             "C14 not held in this_levy_events", code="card_not_held")
    lord_id = action.get("lord_id")
    _require(lord_id in ("sancho", "eudes"),
             "lord_id must be sancho or eudes", code="bad_arg")
    _require(lord_id in state.lords, f"{lord_id} not in scenario",
             code="unknown_lord")
    mode = action.get("mode", "service_shift_right")
    lord = state.lords[lord_id]
    result: dict[str, Any] = {"lord_id": lord_id, "mode": mode}
    if mode == "muster_from_calendar":
        _require(lord.cylinder.kind == "calendar",
                 f"{lord_id} not on Calendar", code="not_on_calendar")
        from almoravid.static_data import load_lords as _ll
        from almoravid.state import Cylinder
        rec = _ll()["lords"].get(lord_id, {})
        seats = list(rec.get("seats", []))
        _require(seats, f"{lord_id} has no Seats", code="no_seat")
        lord.cylinder = Cylinder(kind="locale", locale_id=seats[0])
        lord.forces = dict(rec.get("forces", {}))
        lord.assets = dict(rec.get("assets", {}))
        lord.just_arrived_this_levy = True
        result["mustered_at"] = seats[0]
    elif mode == "service_shift_right":
        sm = next((s for s in state.calendar.service_markers
                   if s.lord_id == lord_id), None)
        if sm is not None:
            sm.box = min(16, sm.box + 2)
            result["new_service_box"] = sm.box
    elif mode == "lordship_plus_2":
        # Phase 6k: record + grant a +2 Lordship for this Lord this
        # Levy. The Lordship action consumer would consult this.
        # For now, just bump lordship_rating temporarily.
        lord.lordship_rating += 2
        result["lordship_rating_now"] = lord.lordship_rating
    else:
        raise IllegalAction(f"unknown mode {mode!r}", code="bad_arg")
    state.decks.this_levy_events["christian"].remove("C14")
    state.decks.discard.append("C14")
    _record(state, action, f"Christian plays C14 Pope Gregory on "
            f"{lord_id} ({mode})")
    return result


def _h_play_cluniacs(state, action):
    """C15 (Hold) Cluniacs: Play on a Lord to Muster from Calendar,
    OR shift Service +1 right, OR Lordship +2.

    Args:
      side: 'christian'
      mode: 'muster_from_calendar' | 'service_shift_right' |
            'lordship_plus_2'
      lord_id: any Christian Lord
    """
    side = _require_side(action)
    _require(side == "christian", "C15 is a Christian event",
             code="wrong_side")
    _require("C15" in state.decks.this_levy_events.get("christian", []),
             "C15 not held in this_levy_events", code="card_not_held")
    lord_id = action.get("lord_id")
    _require(lord_id in state.lords, f"unknown lord {lord_id}",
             code="unknown_lord")
    lord = state.lords[lord_id]
    _require(lord.side == "christian", f"{lord_id} not Christian",
             code="wrong_side")
    mode = action.get("mode", "service_shift_right")
    result: dict[str, Any] = {"lord_id": lord_id, "mode": mode}
    if mode == "muster_from_calendar":
        _require(lord.cylinder.kind == "calendar",
                 f"{lord_id} not on Calendar", code="not_on_calendar")
        from almoravid.static_data import load_lords as _ll
        from almoravid.state import Cylinder
        rec = _ll()["lords"].get(lord_id, {})
        seats = list(rec.get("seats", []))
        _require(seats, f"{lord_id} has no Seats", code="no_seat")
        lord.cylinder = Cylinder(kind="locale", locale_id=seats[0])
        lord.forces = dict(rec.get("forces", {}))
        lord.assets = dict(rec.get("assets", {}))
        lord.just_arrived_this_levy = True
        result["mustered_at"] = seats[0]
    elif mode == "service_shift_right":
        sm = next((s for s in state.calendar.service_markers
                   if s.lord_id == lord_id), None)
        if sm is not None:
            sm.box = min(16, sm.box + 1)
            result["new_service_box"] = sm.box
    elif mode == "lordship_plus_2":
        lord.lordship_rating += 2
        result["lordship_rating_now"] = lord.lordship_rating
    else:
        raise IllegalAction(f"unknown mode {mode!r}", code="bad_arg")
    state.decks.this_levy_events["christian"].remove("C15")
    state.decks.discard.append("C15")
    _record(state, action, f"Christian plays C15 Cluniacs on "
            f"{lord_id} ({mode})")
    return result


def _h_play_de_vivar_reconcile(state, action):
    """C25 (Hold) De Vivar: Reconcile with Rodrigo (3.5.1) — Rodrigo
    al-Sayyid leaves the map; Muslim side gains 1 VP "to Taifas box"
    (modeled as +1 Muslim score).

    Args:
      side: 'christian'
    """
    side = _require_side(action)
    _require(side == "christian", "C25 is a Christian event",
             code="wrong_side")
    _require("C25" in state.decks.this_levy_events.get("christian", []),
             "C25 not held in this_levy_events", code="card_not_held")
    sayyid = state.lords.get("rodrigo_al_sayyid")
    _require(sayyid is not None and sayyid.cylinder.kind == "locale",
             "Rodrigo al-Sayyid not on map", code="not_on_map")
    # Reconcile: remove al-Sayyid from the map; Muslim +1 VP.
    from almoravid.state import Cylinder
    for field_name in sayyid.cleanup_on_removal_fields:
        try:
            setattr(sayyid, field_name,
                    type(getattr(sayyid, field_name))())
        except Exception:
            pass
    sayyid.cylinder = Cylinder(kind="removed")
    from almoravid.actions import _shift_service_left as _ssl
    _ssl(state, "rodrigo_al_sayyid", boxes=20)
    state.score.muslim += 1.0
    state.taifas_box_vp += 1.0  # Phase 7g: 1 VP banked in the Taifas box
    state.decks.this_levy_events["christian"].remove("C25")
    state.decks.discard.append("C25")
    _record(state, action, "Christian Reconciles Rodrigo via C25 "
            "(al-Sayyid removed; +1 VP to Muslim)")
    return {"reconciled": True, "muslim_vp_delta": 1.0}


def _h_cmd_march_port_to_port(state, action):
    """M19 (Hold) African Fleet: Lord uses entire Command card to
    March between two Ports where no Christian Lord at destination.

    Args:
      side: acting (Muslim)
      target_locale_id: destination Port
    """
    from almoravid.state import Cylinder
    from almoravid.effective import is_besieged
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(side == "muslim", "M19 African Fleet is a Muslim event",
             code="wrong_side")
    _require("M19" in state.decks.this_levy_events.get("muslim", []),
             "M19 not held", code="card_not_held")
    lord_id = state.meta.active_lord_id
    _require(lord_id is not None, "no active Lord", code="no_active_lord")
    lord = state.lords[lord_id]
    _require(lord.cylinder.kind == "locale", f"{lord_id} not at Locale",
             code="not_on_map")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord may only Sally/Forage/Pass",
             code="besieged")
    from_loc = lord.cylinder.locale_id
    _require(state.locales[from_loc].has_port,
             f"{from_loc} is not a Port", code="not_port")
    target = action.get("target_locale_id")
    _require(target in state.locales, f"unknown locale {target!r}",
             code="unknown_locale")
    _require(state.locales[target].has_port,
             f"{target} is not a Port", code="not_port")
    # No Christian Lord at target.
    for l in state.lords.values():
        if (l.side == "christian" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == target):
            raise IllegalAction(
                f"Christian Lord {l.id} at {target} — blocked",
                code="destination_has_enemy",
            )
    # Execute Port-to-Port March.
    lord.cylinder = Cylinder(kind="locale", locale_id=target)
    lord.in_stronghold = False
    lord.moved_fought = True
    state.decks.this_levy_events["muslim"].remove("M19")
    state.decks.discard.append("M19")
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0  # consumes entire card per Tips
    _record(state, action,
            f"muslim {lord_id} African Fleet (M19): {from_loc} -> "
            f"{target} (Port to Port, card spent)")
    return {"from": from_loc, "to": target,
            "actions_consumed": consumed}

# ---------------------------------------------------------------------------
# Phase 7b: Victory determination (rules 5.1 / 5.2 / 5.3).
# ---------------------------------------------------------------------------


def _mustered_lords_on_map(state, side: Side) -> int:
    """Count a side's Lords with a cylinder on a map Locale."""
    return sum(
        1 for l in state.lords.values()
        if l.side == side and l.cylinder.kind == "locale"
    )


def check_campaign_victory(state) -> str | None:
    """Rule 5.2: during the Campaign, if a side has no Mustered Lords
    on the map, the OTHER side wins immediately regardless of VP.
    Returns the winning side, or None."""
    if _mustered_lords_on_map(state, "christian") == 0:
        return "muslim"
    if _mustered_lords_on_map(state, "muslim") == 0:
        return "christian"
    return None


def compute_final_vp(state) -> tuple[float, float]:
    """Recompute board VP per rule 5.1 (independent of the running
    incremental score, which doesn't track Taifa-status VP).

    Christian:
      +1 per Conquered marker on a Taifa (Muslim-territory) Locale
      +0.5 per yellow Ravaged marker
      +3 per Reconquista Taifa, +1 per Parias Taifa
    Muslim:
      +0.5 per Jihad marker
      +1 per Conquered marker on a Christian Kingdom Locale
      +0.5 per green Ravaged marker
    """
    christian = 0.0
    muslim = 0.0
    for lid, loc in state.locales.items():
        is_taifa_terr = loc.territory in state.taifas
        if loc.conquered_markers:
            if is_taifa_terr:
                christian += 1.0 * loc.conquered_markers
            else:
                muslim += 1.0 * loc.conquered_markers
        muslim += 0.5 * loc.jihad_markers
        if loc.ravaged == "yellow":
            christian += 0.5
        elif loc.ravaged == "green":
            muslim += 0.5
    for tf in state.taifas.values():
        # 1.4.2: Reconquista Taifa = 3 Christian VP (9 if Sevilla);
        # Parias Taifa = 1 Christian VP (3 if Sevilla); Independent = 0.
        is_sevilla = (tf.id == "sevilla")
        if tf.status == "reconquista":
            christian += 9.0 if is_sevilla else 3.0
        elif tf.status == "parias":
            christian += 3.0 if is_sevilla else 1.0
    # Taifas-box VP (rule 1.4.2) counts for the Muslims.
    muslim += state.taifas_box_vp
    return christian, muslim


def compute_victory(state) -> dict:
    """Determine the winner (rule 5.1/5.2/5.3) and store the verdict
    on state.score. Campaign victory (5.2) takes precedence; otherwise
    higher recomputed VP wins, tie = draw."""
    campaign_winner = check_campaign_victory(state)
    cvp, mvp = compute_final_vp(state)
    state.score.christian_final = cvp
    state.score.muslim_final = mvp
    if campaign_winner is not None:
        state.score.winner = campaign_winner
        state.score.victory_reason = (
            f"Campaign victory (5.2): {('muslim' if campaign_winner=='muslim' else 'christian')} "
            f"opponent had no Mustered Lords on map"
        )
        return {"winner": campaign_winner,
                "christian_vp": cvp, "muslim_vp": mvp,
                "reason": state.score.victory_reason}
    if cvp > mvp:
        winner = "christian"
    elif mvp > cvp:
        winner = "muslim"
    else:
        winner = "draw"
    state.score.winner = winner
    state.score.victory_reason = (
        f"End of scenario (5.1/5.3): Christian {cvp} vs Muslim {mvp}"
    )
    return {"winner": winner, "christian_vp": cvp, "muslim_vp": mvp,
            "reason": state.score.victory_reason}



# ---------------------------------------------------------------------------
# Phase 7c: Lieutenants / Marshal / Group March (4.1.3, 4.3.1).
# ---------------------------------------------------------------------------


# Per-side Marshal (cannot be a Lieutenant / Lower Lord, rule 4.1.3).
_MARSHALS = {"christian": "alfonso", "muslim": "yusuf"}


def _is_marshal(lord_id: str, side: Side) -> bool:
    return _MARSHALS.get(side) == lord_id


def _h_designate_lieutenant(state, action):
    """4.1.3 (Plan step): stack `lord_id` as a Lower Lord with
    `commander_id` (its Lieutenant) at the same Locale.

    Restrictions:
      - both same side, both on the map at the same Locale;
      - neither is the Marshal;
      - the commander isn't itself a Lower Lord;
      - a Lieutenant has at most one Lower Lord.
    """
    side = _require_side(action)
    _require(state.meta.campaign_step == "plan",
             "Lieutenants are designated during the Plan step (4.1.3)",
             code="wrong_step")
    lord_id = action.get("lord_id")
    commander_id = action.get("commander_id")
    _require(lord_id in state.lords and commander_id in state.lords,
             "lord_id and commander_id required", code="bad_arg")
    _require(lord_id != commander_id, "a Lord cannot be his own Lieutenant",
             code="bad_arg")
    lord = state.lords[lord_id]
    cmd = state.lords[commander_id]
    _require(lord.side == side and cmd.side == side,
             "both Lords must be on the acting side", code="wrong_side")
    _require(not _is_marshal(lord_id, side),
             f"{lord_id} is the Marshal — cannot be a Lower Lord (4.1.3)",
             code="marshal_cannot_subordinate")
    _require(not _is_marshal(commander_id, side),
             f"{commander_id} is the Marshal — cannot be a Lieutenant",
             code="marshal_cannot_subordinate")
    _require(lord.cylinder.kind == "locale"
             and cmd.cylinder.kind == "locale"
             and lord.cylinder.locale_id == cmd.cylinder.locale_id,
             "both Lords must be at the same Locale", code="not_same_locale")
    _require(cmd.lieutenant_of is None,
             f"{commander_id} is itself a Lower Lord — cannot lead",
             code="commander_is_subordinate")
    existing = [l.id for l in state.lords.values()
                if l.lieutenant_of == commander_id]
    _require(not existing,
             f"{commander_id} already has Lower Lord {existing}",
             code="lieutenant_full")
    lord.is_lieutenant = True
    lord.lieutenant_of = commander_id
    _record(state, action,
            f"{side} designates {lord_id} as Lower Lord of {commander_id}")
    return {"lower_lord": lord_id, "lieutenant": commander_id}


def _h_toggle_lieutenant(state, action):
    """C15 Alferez (capability): a Lord with Alferez may spend 1 Command
    action to become, or stop being, a Lower Lord stacked on another
    Christian Lord at the same Locale (rule 4.1.3 exception).

    Args:
      side, lord_id (must hold C15 cap), commander_id (to stack onto),
      or mode='unstack' to detach.
    """
    from almoravid.capabilities import lord_has_capability
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    lord_id = state.meta.active_lord_id
    _require(lord_id is not None, "no active Lord", code="no_active_lord")
    _require(lord_has_capability(state, lord_id, "C15"),
             f"{lord_id} lacks Alferez (C15)", code="no_alferez")
    _require(state.meta.actions_remaining >= 1,
             "toggle costs 1 Command action", code="not_enough_actions")
    lord = state.lords[lord_id]
    mode = action.get("mode", "stack")
    if mode == "unstack":
        lord.is_lieutenant = False
        lord.lieutenant_of = None
        state.meta.actions_remaining -= 1
        _record(state, action, f"{lord_id} unstacks (Alferez)")
        return {"unstacked": lord_id,
                "actions_remaining": state.meta.actions_remaining}
    commander_id = action.get("commander_id")
    _require(commander_id in state.lords, "commander_id required",
             code="bad_arg")
    cmd = state.lords[commander_id]
    _require(cmd.side == side and not _is_marshal(commander_id, side),
             "invalid commander", code="bad_arg")
    _require(lord.cylinder.kind == "locale"
             and cmd.cylinder.kind == "locale"
             and lord.cylinder.locale_id == cmd.cylinder.locale_id,
             "must be at the same Locale", code="not_same_locale")
    existing = [l.id for l in state.lords.values()
                if l.lieutenant_of == commander_id]
    _require(not existing, f"{commander_id} already has a Lower Lord",
             code="lieutenant_full")
    lord.is_lieutenant = True
    lord.lieutenant_of = commander_id
    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{lord_id} stacks as Lower Lord of {commander_id} (Alferez)")
    return {"lower_lord": lord_id, "lieutenant": commander_id,
            "actions_remaining": state.meta.actions_remaining}


def _unstack_all_lieutenants(state) -> None:
    """End-of-Campaign cleanup (4.1.3 / SoP 'Unstack Lieutenants and
    Lower Lords')."""
    for l in state.lords.values():
        l.is_lieutenant = False
        l.lieutenant_of = None



# ---------------------------------------------------------------------------
# Phase 7g: Wastage (4.9.4), Encamp (4.3.6), Dinars deposit (4.1.4).
# ---------------------------------------------------------------------------


def _apply_wastage(state) -> list[dict]:
    """Rule 4.9.4: each Mustered Lord (on the map) with MORE THAN ONE
    of any Asset type, or more than one This-Lord Capability card,
    discards one excess. Greedy/deterministic: drop one unit of the
    largest Asset stack > 1; if none, drop one This-Lord Capability."""
    from almoravid.capabilities import capabilities_for_lord
    out: list[dict] = []
    for lid in sorted(state.lords):
        lord = state.lords[lid]
        if lord.cylinder.kind != "locale":
            continue
        # Largest Asset stack with count > 1.
        over = [(n, a) for a, n in lord.assets.items() if n > 1]
        if over:
            over.sort(reverse=True)
            _, atype = over[0]
            lord.assets[atype] -= 1
            if lord.assets[atype] == 0:
                lord.assets.pop(atype, None)
            out.append({"lord_id": lid, "discarded_asset": atype})
            continue
        caps = capabilities_for_lord(state, lid)
        if len(caps) > 1:
            drop = sorted(caps)[-1]
            lord.capabilities.remove(drop)
            state.decks.capabilities_in_play = [
                c for c in state.decks.capabilities_in_play
                if not (c.card_id == drop and c.owner_lord_id == lid)
            ]
            state.decks.discard.append(drop)
            out.append({"lord_id": lid, "discarded_capability": drop})
    if out:
        state.history.append  # no-op marker; recorded by caller log
    return out


def _h_cmd_encamp(state, action):
    """4.3.6 Encamp: a Bypassing Lord uses 1 March action (ignore
    Laden) to replace all his Bypass markers at the Locale with 1
    Siege marker; this ends his actions on the current card."""
    from almoravid.effective import is_bypassed
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    lord_id = state.meta.active_lord_id
    _require(lord_id is not None, "no active Lord", code="no_active_lord")
    lord = state.lords[lord_id]
    _require(lord.cylinder.kind == "locale", f"{lord_id} not at a Locale",
             code="not_on_map")
    _require(state.meta.actions_remaining >= 1,
             "Encamp costs 1 March action", code="not_enough_actions")
    here = lord.cylinder.locale_id
    loc = state.locales[here]
    color_bypass = "bypass_yellow" if side == "christian" else "bypass_green"
    _require(getattr(loc, color_bypass),
             f"{lord_id} is not Bypassing {here} (4.3.6)",
             code="not_bypassing")
    # Replace Bypass with 1 Siege marker (our color).
    setattr(loc, color_bypass, False)
    if side == "christian":
        loc.siege_yellow = max(loc.siege_yellow, 1)
    else:
        loc.siege_green = max(loc.siege_green, 1)
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0  # ends actions on this card
    _record(state, action,
            f"{side} {lord_id} Encamps at {here}: Bypass -> 1 Siege "
            f"(card ends, {consumed} actions spent)")
    return {"locale": here, "encamped": True, "actions_consumed": consumed}


def _h_dinars_deposit(state, action):
    """4.1.4 Dinars: an Unbesieged Taifa Lord (not Yusuf/Sir/Rodrigo)
    deposits any Coin from his mat into the Taifas box (Plan step)."""
    from almoravid.effective import is_besieged
    side = _require_side(action)
    _require(side == "muslim", "Dinars is a Muslim Plan-step option",
             code="wrong_side")
    lord_id = action.get("lord_id")
    _require(lord_id in state.lords, "lord_id required", code="bad_arg")
    lord = state.lords[lord_id]
    _require(lord.is_taifa and lord_id not in
             ("yusuf", "sir", "rodrigo_campeador", "rodrigo_al_sayyid"),
             f"{lord_id} cannot deposit Dinars (4.1.4)",
             code="not_taifa_lord")
    _require(not is_besieged(state, lord_id),
             f"{lord_id} is Besieged — cannot deposit", code="besieged")
    coin = lord.assets.get("coin", 0)
    _require(coin > 0, f"{lord_id} has no Coin to deposit",
             code="no_coin")
    lord.assets.pop("coin", None)
    state.taifas_box_coin += coin
    _record(state, action,
            f"{lord_id} deposits {coin} Coin into Taifas box "
            f"(total {state.taifas_box_coin})")
    return {"lord_id": lord_id, "deposited": coin,
            "taifas_box_coin": state.taifas_box_coin}



# ---------------------------------------------------------------------------
# Hit-absorption policy (4.4.2 ASSIGN HITS — per-combat owner choice).
# ---------------------------------------------------------------------------

_ABSORB_POLICIES = ("weakest_first", "armored_first")


def _apply_absorption_policy(state, side: Side, action: dict) -> None:
    """If a combat action carries an 'absorption_policy', set it as the
    acting side's standing policy for this (and subsequent) combats.
    The Storm Attacker is still rule-forced to armored_first (4.5.2)
    inside battle resolution regardless."""
    pol = action.get("absorption_policy")
    if pol is None:
        return
    _require(pol in _ABSORB_POLICIES,
             f"absorption_policy must be one of {_ABSORB_POLICIES}",
             code="bad_arg")
    state.meta.absorption_policy[side] = pol


def _h_set_absorption_policy(state, action):
    """Set a side's Hit-absorption policy (rule 4.4.2 ASSIGN HITS) at
    any time — the owner's standing strategic choice for how its units
    soak Hits: 'weakest_first' (shield strong units) or 'armored_first'
    (armored soak to maximize cancels). Usable so a side that will be
    a passive Defender (e.g. in an Approach Battle or a Storm) can set
    its policy before the enemy's combat action resolves."""
    side = _require_side(action)
    pol = action.get("policy")
    _require(pol in _ABSORB_POLICIES,
             f"policy must be one of {_ABSORB_POLICIES}", code="bad_arg")
    state.meta.absorption_policy[side] = pol
    _record(state, action, f"{side} sets absorption policy = {pol}")
    return {"side": side, "absorption_policy": pol}


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
    "cmd_battle": _h_cmd_battle,
    "cmd_storm": _h_cmd_storm,
    "cmd_sally": _h_cmd_sally,
    "end_campaign": _h_end_campaign,
    "respond_avoid_battle": _h_respond_avoid_battle,
    "respond_withdraw": _h_respond_withdraw,
    "respond_stand_battle": _h_respond_stand_battle,
    "play_pope_gregory": _h_play_pope_gregory,
    "play_cluniacs": _h_play_cluniacs,
    "play_de_vivar_reconcile": _h_play_de_vivar_reconcile,
    "cmd_march_port_to_port": _h_cmd_march_port_to_port,
    "designate_lieutenant": _h_designate_lieutenant,
    "toggle_lieutenant": _h_toggle_lieutenant,
    "cmd_encamp": _h_cmd_encamp,
    "dinars_deposit": _h_dinars_deposit,
    "set_absorption_policy": _h_set_absorption_policy,
}
