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
    AssetType,
    GameState,
    Lord,
    PendingDecision,
    PlanEntry,
    Side,
    TaifaStatus,
    UnitType,
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


def _concede_round_arg(action: dict[str, Any], key: str) -> int | None:
    """Read an optional pre-declared Concede-the-Field Round (4.4.2).

    None = that side never Concedes; otherwise the 1-based Round at the
    start of which that side Concedes (Attacker or Defender; either may,
    from Round 1 — unlike the Storm, where only the Attacker may, Round
    2+). Mirrors the Storm's pre-declared concede_after_round."""
    val = action.get(key)
    if val is None:
        return None
    _require(isinstance(val, int) and val >= 1,
             f"{key} must be a positive int (Round number) or omitted",
             code="bad_arg")
    assert isinstance(val, int)
    return val


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


def _apply_capability_discard(state: GameState) -> dict[str, Any]:
    """Rule 4.0 CAPABILITY DISCARD: at the start of each Campaign the
    players (Christian first, then Muslim) must discard side-wide
    Capability cards (those tucked under the map edge, state.decks.
    board_edge) in excess of their number of Mustered (on-map) Lords.
    'This Lord' Capabilities (on Lord mats) are NOT counted or
    discarded. Excess is discarded deterministically from the end of
    the board_edge list (a minor player choice that does not affect
    totals).
    """
    out: dict[str, Any] = {}
    for side in ("christian", "muslim"):
        edge = state.decks.board_edge.get(side, [])
        n_lords = sum(1 for lord in state.lords.values()
                      if lord.side == side and lord.cylinder.kind == "locale")
        if len(edge) > n_lords:
            discarded = edge[n_lords:]
            state.decks.board_edge[side] = edge[:n_lords]
            state.decks.discard.extend(discarded)
            out[side] = {"discarded": discarded, "kept": n_lords}
    return out


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
    # Rule 5.2: a side with no Mustered Lords on the map at any moment
    # during the Campaign loses immediately (the other side wins). A
    # side with zero Mustered Lords also cannot legally build a Plan
    # (it has no Command cards and only five Pass cards < the 7/8 target,
    # 4.1.1/1.9.2), so check here at Campaign entry before the Plan step.
    cw = check_campaign_victory(state)
    if cw is not None:
        verdict = compute_victory(state)
        state.meta.phase = "ended"
        _record(state, action,
                f"Begin Campaign: rule 5.2 — {cw} wins (opponent has no "
                f"Mustered Lords on the map)")
        return {"phase": "ended", "victory": verdict}
    # 4.0 CAPABILITY DISCARD (Christian first, then Muslim).
    _apply_capability_discard(state)
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
    lord_id = cast(str, lord_id)
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
        # C7 (4.1.1): only currently Mustered Lords' Command cards may
        # be selected. Mustered == cylinder on a map Locale.
        _require(lord.cylinder.kind == "locale",
                 f"{lord_id} is not Mustered (on the map); only Mustered "
                 f"Lords' Command cards may be planned (4.1.1)",
                 code="not_mustered")
    plan = state.decks.plan.setdefault(side, [])
    target = _plan_target_size(state)
    _require(len(plan) < target,
             f"plan already at target size {target}",
             code="plan_full")
    if kind == "command":
        # C7 (1.9.2/4.1.1): each Lord has only three Command cards
        # (four if a Marshal), so a Lord may appear at most that many
        # times in a Plan.
        cap = 4 if _is_marshal(lord_id, side) else 3
        used = sum(1 for e in plan
                   if e.kind == "command" and e.lord_id == lord_id)
        _require(used < cap,
                 f"{lord_id} already has {used} Command cards in the Plan "
                 f"(max {cap}; 1.9.2)", code="lord_card_cap")
    else:
        # C7 (1.9.2): each side has only FIVE Pass cards.
        used_pass = sum(1 for e in plan if e.kind == "pass")
        _require(used_pass < 5,
                 f"{side} already has {used_pass} Pass cards in the Plan "
                 f"(max 5; 1.9.2)", code="pass_cap")
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
                + ("pass card" if entry.kind == "pass"
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
                force: bool = False,
                discard_excess_mules: bool = False) -> dict[str, Any]:
    """Rule 4.8.1 Feed: a Lord who Moved/Fought this card consumes
    ceil((units + mules) / 6) Provender or Loot. Unfed -> Service
    marker shifts 1 box left.

    Phase 6h: `force=True` bypasses the moved_fought guard so event
    cards (C4/M4 Arid Terrain, C5/M5 Drought) can compel an immediate
    Feed regardless of whether the Lord has acted yet.
    """
    lord = state.lords[lord_id]
    if not force and not lord.moved_fought:
        return {"skipped": "did_not_move_fight", "consumed": 0}
    res = _feed_consume_own(state, lord_id,
                            discard_excess_mules=discard_excess_mules)
    # Single-Lord (event-forced) Feed applies the Unfed penalty
    # immediately; the comprehensive end-card Feed defers it until after
    # Sharing (4.8.1 SHARING).
    unfed = False
    if res["short"] > 0:
        _apply_unfed_penalty(state, lord_id)
        unfed = True
    return {"consumed": res["consumed"], "needed": res["needed"],
            "short": res["short"], "unfed_penalty": unfed,
            "use_prov": res["use_prov"], "use_loot": res["use_loot"],
            "mules_discarded": res["mules_discarded"]}


def _apply_unfed_penalty(state: GameState, lord_id: str) -> None:
    """4.8.1 UNFED: shift the Lord's Service marker one 40-Days box left."""
    sm = next((s for s in state.calendar.service_markers
               if s.lord_id == lord_id), None)
    if sm is not None:
        sm.box = max(0, sm.box - 1)


def _feed_consume_own(state: GameState, lord_id: str, *,
                      discard_excess_mules: bool = False) -> dict[str, Any]:
    """4.8.1 own-Feed: a Lord consumes ceil((units + Mules)/6) Provender
    or Loot from his OWN mat (Provender first, then Loot). Does NOT apply
    the Unfed penalty (the caller decides when, after Sharing).

    E6 GREED (rule 4.8.1): if `discard_excess_mules`, the Lord may first
    discard Mules in excess of those his own Provender + Loot can Feed,
    keeping as many Mules as feeding capacity allows. This is an OPTIONAL
    player choice (rule: "may"); it is NOT auto-exercised by the default
    end-card Feed, which keeps Mules and accepts any Unfed penalty.
    """
    import math
    lord = state.lords[lord_id]
    units = sum(lord.forces.values())
    mules = lord.assets.get("mule", 0)
    prov = lord.assets.get("prov", 0)
    loot = lord.assets.get("loot", 0)
    discarded = 0
    if discard_excess_mules and mules > 0:
        capacity = prov + loot              # Assets available to Feed
        keep = max(0, min(mules, capacity * 6 - units))
        discarded = mules - keep
        if discarded > 0:
            mules = keep
            if mules > 0:
                lord.assets["mule"] = mules
            else:
                lord.assets.pop("mule", None)
    needed = math.ceil((units + mules) / 6) if (units + mules) > 0 else 0
    use_prov = min(prov, needed)
    short_after = needed - use_prov
    use_loot = min(loot, short_after)
    short = short_after - use_loot
    if use_prov > 0:
        lord.assets["prov"] = prov - use_prov
    if use_loot > 0:
        lord.assets["loot"] = loot - use_loot
    return {"needed": needed, "consumed": use_prov + use_loot,
            "use_prov": use_prov, "use_loot": use_loot, "short": short,
            "mules_discarded": discarded}


def _feed_all_moved_fought(state: GameState, *,
                           discard_excess_mules: bool = False) -> dict[str, Any]:
    """4.8.1 Feed for the per-card Feed/Pay/Disband step (4.8).

    E4: ALL Lords marked Moved/Fought on BOTH sides Feed (Christians
    then Muslims), not only the active Lord (a Battle/Storm or Group
    March marks several Lords).
    E5 SHARING: after every Lord Feeds his own Forces + Mules, each
    side's other Lords in the SAME Locale must expend their remaining
    Provender and Loot to Feed same-side Lords there who came up short
    (mandatory, no withholding). Any Lord still short is Unfed (Service
    -1). Markers are NOT cleared here (4.8.3 handles that).
    """
    summary: dict[str, Any] = {"fed": [], "shared": [], "unfed": []}
    shortfall: dict[str, int] = {}

    # Phase A: own-Feed, Christians then Muslims.
    for side in ("christian", "muslim"):
        for lid, lord in state.lords.items():
            if lord.side != side or not lord.moved_fought:
                continue
            if lord.cylinder.kind != "locale":
                continue
            r = _feed_consume_own(state, lid,
                                  discard_excess_mules=discard_excess_mules)
            summary["fed"].append({"lord_id": lid, **r})
            if r["short"] > 0:
                shortfall[lid] = r["short"]

    # Phase B: SHARING within each side at each Locale.
    for lid in list(shortfall.keys()):
        if shortfall[lid] <= 0:
            continue
        lord = state.lords[lid]
        loc_id = lord.cylinder.locale_id
        assert loc_id is not None
        # Same-side Lords at the same Locale (excluding self) must share
        # their remaining Provender then Loot.
        for donor_id, donor in state.lords.items():
            if shortfall[lid] <= 0:
                break
            if (donor_id == lid or donor.side != lord.side
                    or donor.cylinder.kind != "locale"
                    or donor.cylinder.locale_id != loc_id):
                continue
            for asset in ("prov", "loot"):
                if shortfall[lid] <= 0:
                    break
                have = donor.assets.get(asset, 0)
                give = min(have, shortfall[lid])
                if give > 0:
                    donor.assets[asset] = have - give
                    shortfall[lid] -= give
                    summary["shared"].append(
                        {"to": lid, "from": donor_id, "asset": asset,
                         "amount": give})

    # Phase C: UNFED penalty for any Lord still short after Sharing.
    for lid, short in shortfall.items():
        if short > 0:
            _apply_unfed_penalty(state, lid)
            summary["unfed"].append(lid)
    return summary


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
    # Locale being vacated — for the 4.3.5 Siege/Bypass-marker cleanup.
    left_locale = (lord.cylinder.locale_id
                   if lord.cylinder.kind == "locale" else None)
    new_box = _compute_disband_target_box(state, lord)
    if new_box > 16:
        new_box = 17
        state.calendar.off_right.append(lord_id)
    lord.cylinder = Cylinder(kind="calendar", box=new_box)
    # 4.3.5 / playtest F7: a Stronghold free of the besieging side's
    # Lords loses that side's Siege/Bypass markers.
    if left_locale is not None:
        _remove_orphaned_siege_bypass(state, left_locale)
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


def _clear_per_card_event_flags(state: GameState) -> None:
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
    assert lord_id is not None
    lord = state.lords[lord_id]
    # 4.8.1 Feed — E4/E5: ALL Lords marked Moved/Fought on both sides
    # Feed (a Battle/Storm or Group March marks several), with Sharing
    # among same-Locale same-side Lords.
    feed_result = _feed_all_moved_fought(state)
    # 4.8.2/4.8.3 auto-Disband at Service limit: "any Christian then Muslim
    # Lords whose Service markers are at their limit must Disband." Sweep
    # ALL on-map Lords (both sides), not only the active one, since the Feed
    # Unfed penalty (or other Service shifts this card) can push a different
    # Lord to its limit. _auto_disband_at_service_limit no-ops when a Lord
    # is not at its limit.
    disbanded_now: list[dict[str, Any]] = []
    _sides_order: tuple[Side, Side] = ("christian", "muslim")
    for _sd in _sides_order:
        for _lid in [lo.id for lo in state.lords.values()
                     if lo.side == _sd and lo.cylinder.kind == "locale"]:
            _res = _auto_disband_at_service_limit(state, _lid)
            if _res.get("disbanded"):
                disbanded_now.append(_res)
    disband_result: dict[str, Any] = (
        {"disbanded_lords": [d["disbanded"] for d in disbanded_now]}
        if disbanded_now else {"no_op": True})
    # 3.4.2 advanced Vassal Service: at the 4.8.2 Disband step the
    # Mustered Vassals at/beyond Service limit also Disband (Christian
    # then Muslim), with the no-Forces Lord cascade (1.6).
    if state.meta.advanced_vassal_service:
        from almoravid.actions import _disband_vassals_for_side
        for _sd in _sides_order:
            _disband_vassals_for_side(state, _sd)
    # Bookkeeping
    state.meta.active_lord_id = None
    state.meta.actions_remaining = 0
    # 4.8.3 Remove Moved/Fought markers from ALL Lords (both sides).
    for _l in state.lords.values():
        _l.moved_fought = False
    # Pattern 3 per-card flag reset (only if Lord still exists in state
    # — disband doesn't remove Lord from state.lords, just changes
    # cylinder, so this is safe)
    if lord.cylinder.kind == "locale":
        lord.lordship_used = 0
        lord.first_march_used_this_card = False
        lord.raiders_used_this_card = False
    _clear_per_card_event_flags(state)
    _advance_or_end_campaign(state)
    _record(state, action,
            f"{side} ends {lord_id}'s card; Feed: "
            f"fed={len(feed_result.get('fed', []))} "
            f"shared={len(feed_result.get('shared', []))} "
            f"unfed={feed_result.get('unfed', [])}"
            + (f"; auto-disband {disband_result}"
               if disband_result.get('disbanded_lords') else "")
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


def _apply_grow_harvest_repairs(state: GameState, prev_box: int) -> dict[str, Any]:
    """Rules 4.9.2 GROW / HARVEST and 4.9.3 REPAIRS, applied for the
    Campaign that just concluded in `prev_box` (1-indexed). Only runs
    when the game continues (4.9.1 Game End is checked first).

    GROW (end of the SECOND 40 Days of Spring): the Christian then the
    Muslim player each reduces ENEMY Ravage markers on the map to half
    their number, rounded up (mandatory). Christian removes Muslim
    (green) Ravaged markers; Muslim removes Christian (yellow). Removing
    floor(n/2) markers leaves ceil(n/2). Which markers are removed is a
    minor player choice with no VP-total effect (VP is count-based);
    a deterministic selection is used.

    HARVEST (end of the SECOND 40 Days of Summer): each Lord reduces his
    Carts and Mules EACH to half, rounded up.

    REPAIRS (end of each Campaign except Winter): remove one Siege
    marker from each Siege Locale that has three OR four Siege markers
    (per besieger color).
    """
    import math as _m
    out: dict[str, Any] = {"grow": None, "harvest": None, "repairs": []}
    boxes = state.calendar.boxes
    if prev_box < 1 or prev_box > len(boxes):
        return out
    season = boxes[prev_box - 1].season
    second_of_season = (prev_box >= 2
                        and boxes[prev_box - 2].season == season)

    # GROW (second Spring) -------------------------------------------
    if season == "spring" and second_of_season:
        def _reduce(color: str) -> list[str]:
            ravaged = [lid for lid, loc in state.locales.items()
                       if loc.ravaged == color]
            n = len(ravaged)
            remove = n - _m.ceil(n / 2) if n > 0 else 0  # = floor(n/2)
            removed = sorted(ravaged)[:remove]
            for lid in removed:
                state.locales[lid].ravaged = "none"
                # 4.9.2 "adjust VP": removing a Ravage marker drops its
                # ½VP from the running tally (yellow=Christian, green=
                # Muslim, 5.1). compute_final_vp is count-based so the
                # board verdict stays correct either way; this keeps the
                # displayed running score honest.
                if color == "yellow":
                    state.score.christian -= 0.5
                else:
                    state.score.muslim -= 0.5
            return removed
        # Christian reduces ENEMY (green) markers; Muslim reduces yellow.
        green_removed = _reduce("green")
        yellow_removed = _reduce("yellow")
        out["grow"] = {"christian_removed_green": green_removed,
                       "muslim_removed_yellow": yellow_removed}

    # HARVEST (second Summer) ----------------------------------------
    if season == "summer" and second_of_season:
        harvested = []
        for lid, lord in state.lords.items():
            if lord.cylinder.kind != "locale":
                continue
            cart = lord.assets.get("cart", 0)
            mule = lord.assets.get("mule", 0)
            if cart <= 1 and mule <= 1:
                continue
            new_cart = _m.ceil(cart / 2) if cart > 0 else 0
            new_mule = _m.ceil(mule / 2) if mule > 0 else 0
            if new_cart > 0:
                lord.assets["cart"] = new_cart
            else:
                lord.assets.pop("cart", None)
            if new_mule > 0:
                lord.assets["mule"] = new_mule
            else:
                lord.assets.pop("mule", None)
            harvested.append({"lord_id": lid,
                              "cart": (cart, new_cart),
                              "mule": (mule, new_mule)})
        out["harvest"] = harvested

    # REPAIRS (every Campaign except Winter) -------------------------
    if season != "winter":
        for lid, loc in state.locales.items():
            for fld in ("siege_yellow", "siege_green"):
                n = getattr(loc, fld)
                if n in (3, 4):
                    setattr(loc, fld, n - 1)
                    out["repairs"].append({"locale": lid, "marker": fld,
                                           "from": n, "to": n - 1})
    return out


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
    # 4.9.2 Grow/Harvest + 4.9.3 Repairs for the just-concluded Campaign
    # (only reached when the game continues, i.e. 4.9.1 Game End did not
    # fire above). `prev_box` is the box whose Campaign just ended.
    ghr = _apply_grow_harvest_repairs(state, prev_box)
    # Otherwise return to Levy
    _return_to_levy(state)

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
            # 6.3.1 Winter Disband, then the interactive 6.3.2 Winter
            # Siege sequence which OWNS the flow through boxes 7->8 and
            # ends by entering the box-9 Spring Levy (6.3.3/.4/.5). The
            # ordinary Levy/Campaign cycle does NOT run at winter boxes.
            wd = winter_disband(state)
            auto_actions.append({"winter_disband": wd})
            ws = _enter_winter_box(state, 7)
            auto_actions.append({"winter_siege": ws})
            _record(state, action,
                    f"End Campaign; advanced box {prev_box} -> 7; Winter "
                    f"Disband + Winter Siege: {auto_actions}")
            return {"phase": state.meta.phase, "current_box": 7,
                    "turn_index": state.meta.turn_index,
                    "grow_harvest_repairs": ghr,
                    "auto_actions": auto_actions}

    _record(state, action,
            f"End Campaign; advanced box {prev_box} -> {new_box}; back to Levy"
            + (f"; grow/harvest/repairs: {ghr}"
               if (ghr.get("grow") or ghr.get("harvest") or ghr.get("repairs"))
               else "")
            + (f"; auto: {auto_actions}" if auto_actions else ""))
    return {"phase": state.meta.phase, "current_box": new_box,
            "turn_index": state.meta.turn_index,
            "grow_harvest_repairs": ghr,
            "auto_actions": auto_actions}


# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 6.2 Curias check + 6.3 Winter Sequence (Phase 5k — Scenario F only)
# ---------------------------------------------------------------------------


def check_curias(state: GameState) -> dict[str, Any]:
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


def apply_curias(state: GameState, box: int) -> dict[str, Any]:
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

    # T6 (rule 6.2.2 / 5.1): remove one 1VP Conquered marker from the
    # Muslims' Taifas box per Curias marker placed -- this REDUCES the
    # Muslim Taifas-box VP, it does NOT deduct from the Christian score.
    state.taifas_box_vp = max(0.0, state.taifas_box_vp - float(len(placed)))

    # Advance Levy marker to box 7
    state.calendar.current_box = 7

    # 6.2.2: shift the Service markers of any Lords "Beyond Service (in box
    # 6 or lower)" to the current 40 Days (box 7). The threshold is a FIXED
    # box 6 (relative to the post-Curias Levy marker at box 7), regardless
    # of whether Curias fires at box 5 or box 6.
    shifted = []
    for sm in list(state.calendar.service_markers):
        if sm.box <= 6:
            sm.box = 7
            shifted.append(sm.lord_id)

    # Disband Pedro Ansurez / Garcia Ordonez if on map
    disbanded = []
    from almoravid.state import Cylinder
    for lid in ("pedro_ansurez", "garcia_ordonez"):
        lord = state.lords.get(lid)
        if lord is None or lord.cylinder.kind != "locale":
            continue
        # Apply Phase 5g _h_disband_lord behavior inline
        new_box = state.calendar.current_box + lord.service_rating
        if new_box > 16:
            new_box = 17
            state.calendar.off_right.append(lid)
        lord.cylinder = Cylinder(kind="calendar", box=new_box)
        lord.forces = {}
        lord.assets = {}
        lord.capabilities = []
        lord.vassals = []
        lord.in_stronghold = False
        lord.moved_fought = False
        lord.routed_units = {}
        state.calendar.service_markers = [
            s for s in state.calendar.service_markers if s.lord_id != lid
        ]
        disbanded.append(lid)

    return {"curias_placed_in_boxes": placed,
            "service_shifted_lords": shifted,
            "auto_disbanded": disbanded}


def winter_disband(state: GameState) -> dict[str, Any]:
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
    results: dict[str, Any] = {"disbanded_to_mat": [], "rodrigo_to_box_9": [],
               "lords_at_sieges_kept": [], "board_edge_discarded": [],
               "beyond_service_removed": [], "taifas_box_coin_added": 0}

    cur_box = state.calendar.current_box
    svc = {sm.lord_id: sm.box for sm in state.calendar.service_markers
           if sm.vassal_id is None}

    def _strip_seats(lord_id: str) -> None:
        for loc2 in state.locales.values():
            if lord_id in loc2.seat_marker_lord_ids:
                loc2.seat_marker_lord_ids.remove(lord_id)

    for lid, lord in state.lords.items():
        if lord.cylinder.kind != "locale":
            continue
        assert lord.cylinder.locale_id is not None
        loc = state.locales[lord.cylinder.locale_id]
        # Lord at an active Siege keeps for the Winter Siege step (6.3.2).
        at_siege = (loc.siege_yellow > 0 or loc.siege_green > 0)
        if at_siege:
            results["lords_at_sieges_kept"].append(lid)
            continue
        is_rodrigo = lid in ("rodrigo_campeador", "rodrigo_al_sayyid")
        # 3.3.1 Beyond Service: a Service marker LEFT of the marker box
        # (lower-numbered) is permanently removed FIRST — EXCEPTION:
        # Rodrigo (placed at box 9 even if Beyond Service, 6.3.1).
        beyond_service = (lid in svc and svc[lid] < cur_box)
        if is_rodrigo:
            lord.cylinder = Cylinder(kind="calendar", box=9)
            results["rodrigo_to_box_9"].append(lid)
            lord.forces = {}
            lord.assets = {}
            lord.capabilities = []
            lord.in_stronghold = False
            lord.moved_fought = False
            lord.routed_units = {}
            continue
        if beyond_service:
            # Permanently removed from the game (3.3.1): Forces/Assets to
            # pools (cleared), This-Lord Capabilities to their deck,
            # cylinder/mat/Seat markers out of the game.
            state.decks.discard.extend(lord.capabilities)
            _strip_seats(lid)
            lord.cylinder = Cylinder(kind="removed")
            lord.forces = {}
            lord.assets = {}
            lord.capabilities = []
            lord.in_stronghold = False
            lord.moved_fought = False
            lord.routed_units = {}
            results["beyond_service_removed"].append(lid)
            continue
        # Otherwise Disband as if at Service limit (3.3.2) but to the mat
        # (6.3.1 modification), to auto-Muster at Spring Muster (6.3.3).
        # Disbanding Taifa Lords put all Coin from their mats into the
        # Taifas box (do NOT adjust Taifa status / award Parias Coin).
        if lord.is_taifa:
            coin = lord.assets.get("coin", 0)
            if coin:
                state.taifas_box_coin += coin
                results["taifas_box_coin_added"] += coin
        lord.cylinder = Cylinder(kind="mat")
        results["disbanded_to_mat"].append(lid)
        lord.forces = {}
        lord.assets = {}
        lord.capabilities = []
        lord.in_stronghold = False
        lord.moved_fought = False
        lord.routed_units = {}

    # Discard board-edge Capabilities (3.4.4)
    for side in ("christian", "muslim"):
        edge = state.decks.board_edge.get(side, [])
        if edge:
            state.decks.discard.extend(edge)
            results["board_edge_discarded"].extend(edge)
        state.decks.board_edge[side] = []

    # Clear Service markers (6.3.1 Disbands; Spring Muster re-places them)
    state.calendar.service_markers = []
    return results


def spring_muster(state: GameState) -> dict[str, Any]:
    """Rule 6.3.3 Spring Muster at end of box 8 (Scenario F only).

    Christian Lords on mats automatically Muster — cylinder to a free
    Seat, Service markers ahead. Lords with no free Seat go to Calendar
    as if Disbanded this turn. Then Muslim Lords likewise; Taifa Lords
    with no free Seat go to Calendar and adjust Taifa status.
    """
    from almoravid.state import Cylinder, ServiceMarker
    from almoravid.static_data import load_lords
    results: dict[str, Any] = {"christian_mustered": [], "muslim_mustered": [],
               "no_free_seat": []}
    static = load_lords()["lords"]

    for side in ("christian", "muslim"):
        for lid, lord in state.lords.items():
            if lord.side != side:
                continue
            if lord.cylinder.kind != "mat":
                continue
            free_seats = []
            for seat in lord.seats:
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
                lord.cylinder = Cylinder(kind="locale", locale_id=chosen)
                lord.forces = dict(static[lid]["forces"])
                lord.assets = dict(static[lid]["assets"])
                # Service marker advanced
                new_box = state.calendar.current_box + lord.service_rating
                state.calendar.service_markers.append(
                    ServiceMarker(lord_id=lid, box=min(new_box, 17)))
                results[f"{side}_mustered"].append((lid, chosen))
            else:
                # No free Seat: place on Calendar
                new_box = state.calendar.current_box + lord.service_rating
                lord.cylinder = Cylinder(kind="calendar",
                                       box=min(new_box, 17))
                results["no_free_seat"].append(lid)
    return results


def winter_plowing(state: GameState) -> dict[str, Any]:
    """Rule 6.3.4 Plowing: at the end of the second 40 Days of Winter
    (box 8), each Lord at a Siege (only) reduces his Carts and Mules
    each to half their number, rounded up. Mirrors 4.9.2 Harvest but
    restricted to Lords at a Siege Locale."""
    import math as _m
    out: dict[str, Any] = {"plowed": []}
    for lid, lord in state.lords.items():
        if lord.cylinder.kind != "locale":
            continue
        assert lord.cylinder.locale_id is not None
        loc = state.locales[lord.cylinder.locale_id]
        if not (loc.siege_yellow > 0 or loc.siege_green > 0):
            continue
        cart = lord.assets.get("cart", 0)
        mule = lord.assets.get("mule", 0)
        if cart <= 1 and mule <= 1:
            continue
        new_cart = _m.ceil(cart / 2) if cart > 0 else 0
        new_mule = _m.ceil(mule / 2) if mule > 0 else 0
        if new_cart > 0:
            lord.assets["cart"] = new_cart
        else:
            lord.assets.pop("cart", None)
        if new_mule > 0:
            lord.assets["mule"] = new_mule
        else:
            lord.assets.pop("mule", None)
        out["plowed"].append({"lord_id": lid, "cart": (cart, new_cart),
                              "mule": (mule, new_mule)})
    return out


# ---------------------------------------------------------------------------
# Return-to-Levy reset (shared by End Campaign and the Winter sequence exit).
# ---------------------------------------------------------------------------


def _return_to_levy(state: GameState) -> None:
    """Reset turn state for the start of a new Levy phase."""
    state.meta.phase = "levy"
    state.meta.campaign_step = None
    state.meta.levy_step = "arts_of_war"
    state.meta.aow_draw_done = {}
    state.meta.levy_step_completed_christian = False
    state.meta.levy_step_completed_muslim = False
    state.meta.cta_option_used_christian = False
    state.meta.cta_option_used_muslim = False
    state.meta.cta_crusade_jihad_pending = False
    for _l in state.lords.values():
        _l.just_arrived_this_levy = False
    state.meta.active_player = ACTOR_ORDER[0]
    state.meta.turn_index += 1


# ---------------------------------------------------------------------------
# 6.3.2 Winter Siege (Scenario F) — interactive per-box mini-sequence.
#
# Per Winter box (7 then 8): (1) walk the Besieging Lords offering each
# ONE Supply or Ravage action, or pass (Forage is NOT offered); (2)
# auto-Feed EVERY Lord at a Siege Locale (both sides, incl. Besieged
# garrisons); (3) Christian then Muslim Pay Lords at Sieges; (4)
# auto-Disband Lords at Sieges at/beyond Service limit (per 3.3). The
# ordering is load-bearing: Supply feeds the Provender that Feed
# consumes, and Pay can advance Service to dodge the mandatory Disband.
# ---------------------------------------------------------------------------


def _siege_locale_lords(state: GameState) -> list[str]:
    """All Lords (both sides, including Besieged garrisons inside) whose
    cylinder is at a Locale that has any Siege marker."""
    out = []
    for lid, lord in state.lords.items():
        if lord.cylinder.kind != "locale":
            continue
        assert lord.cylinder.locale_id is not None
        loc = state.locales[lord.cylinder.locale_id]
        if loc.siege_yellow > 0 or loc.siege_green > 0:
            out.append(lid)
    return out


def _winter_besiegers(state: GameState) -> list[str]:
    """6.3.2 bullet 1 "each Besieging Lord (only)": a Lord OUTSIDE a
    Stronghold at a Locale where HIS side has a Siege marker."""
    out = []
    for lid, lord in state.lords.items():
        if lord.cylinder.kind != "locale" or lord.in_stronghold:
            continue
        assert lord.cylinder.locale_id is not None
        loc = state.locales[lord.cylinder.locale_id]
        if lord.side == "christian" and loc.siege_yellow > 0:
            out.append(lid)
        elif lord.side == "muslim" and loc.siege_green > 0:
            out.append(lid)
    return out


class _MetaCtx:
    """Save/restore turn-context + pending so the guarded Campaign/Levy
    command handlers (Supply, Ravage, Pay, Disband) can be reused inside
    the Winter sequence without duplicating their effect logic."""

    def __init__(self, state: GameState, **overrides: Any) -> None:
        self.state = state
        self.overrides = overrides

    def __enter__(self) -> _MetaCtx:
        m = self.state.meta
        self._saved = {k: getattr(m, k) for k in (
            "phase", "campaign_step", "levy_step", "active_player",
            "active_lord_id", "actions_remaining")}
        self._pending = self.state.pending
        for k, v in self.overrides.items():
            setattr(m, k, v)
        self.state.pending = None
        return self

    def __exit__(self, *exc: object) -> None:
        m = self.state.meta
        for k, v in self._saved.items():
            setattr(m, k, v)
        self.state.pending = self._pending
        return None


def _winter_feed(state: GameState) -> dict[str, Any]:
    """6.3.2 bullet 2: each Lord at a Siege Locale Feeds (4.8.1). Marks
    those Lords Moved/Fought and runs the shared Feed (Christians then
    Muslims, Sharing among same-Locale allies, Unfed Service-shift)."""
    for lid in _siege_locale_lords(state):
        state.lords[lid].moved_fought = True
    return _feed_all_moved_fought(state)


def _winter_siege_disband(state: GameState) -> list[dict[str, Any]]:
    """6.3.2 bullet 3 (mandatory): Disband Lords at Siege Locales at or
    beyond Service limit per 3.3 (Beyond -> permanent removal; At limit
    -> Calendar). Reuses the tested disband handler."""
    from almoravid.actions import _h_disband_lord
    results = []
    cur = state.calendar.current_box
    for lid in list(_siege_locale_lords(state)):
        lord = state.lords[lid]
        if lord.cylinder.kind != "locale":
            continue
        sm = next((m for m in state.calendar.service_markers
                   if m.lord_id == lid and m.vassal_id is None), None)
        at_or_beyond = (sm is None) or (sm.box <= cur)
        if not at_or_beyond:
            continue
        with _MetaCtx(state, phase="levy", levy_step="service_disband",
                      active_player=lord.side):
            results.append(_h_disband_lord(
                state, {"type": "disband_lord", "side": lord.side,
                        "lord_id": lid}))
    return results


def _enter_winter_box(state: GameState, box: int) -> dict[str, Any]:
    """Begin the Winter Siege sequence for `box` (7 or 8)."""
    from almoravid.state import PendingDecision
    state.meta.phase = "winter"
    state.calendar.current_box = box
    state.pending = PendingDecision(
        kind="winter_siege", waiting_on="christian",
        payload={"box": box, "step": "besieger_actions",
                 "queue": _winter_besiegers(state)})
    return _winter_advance(state)


def _winter_advance(state: GameState) -> dict[str, Any]:
    """Progress the Winter Siege state machine, pausing (leaving the
    pending set with waiting_on correct) only when player input is
    needed; runs the auto Feed at the besieger->pay boundary."""
    pd = state.pending
    assert pd is not None
    payload = pd.payload
    if payload["step"] == "besieger_actions":
        # Drop any besieger no longer eligible (e.g. removed mid-step).
        payload["queue"] = [lid for lid in payload["queue"]
                            if lid in state.lords
                            and state.lords[lid].cylinder.kind == "locale"]
        if payload["queue"]:
            nxt = payload["queue"][0]
            pd.waiting_on = state.lords[nxt].side
            state.meta.active_player = pd.waiting_on
            return {"winter": "besieger_pending", "box": payload["box"],
                    "lord": nxt}
        # All besiegers done -> mandatory Feed -> Pay phase.
        fed = _winter_feed(state)
        # If no Lords are at any Siege Locale, there is nothing left to
        # Pay or Disband this box — finish it automatically.
        if not _siege_locale_lords(state):
            return {"winter": "no_siege_lords", "box": payload["box"],
                    "feed": fed, "finish": _finish_winter_box(state, payload["box"])}
        payload["step"] = "pay"
        payload["pay_side"] = "christian"
        pd.waiting_on = "christian"
        state.meta.active_player = "christian"
        return {"winter": "pay_pending", "box": payload["box"],
                "feed": fed, "pay_side": "christian"}
    # step == "pay": wait for the current side's Pay/done.
    pd.waiting_on = payload["pay_side"]
    state.meta.active_player = payload["pay_side"]
    return {"winter": "pay_pending", "box": payload["box"],
            "pay_side": payload["pay_side"]}


def _finish_winter_box(state: GameState, box: int) -> dict[str, Any]:
    """After both sides' Pay: mandatory at-limit Disband, then either
    advance to box 8 (interactive again) or, after box 8, run Spring
    Muster (6.3.3) + Plowing (6.3.4) and enter the box-9 Spring Levy."""
    disb = _winter_siege_disband(state)
    if box == 7:
        nxt = _enter_winter_box(state, 8)
        return {"winter": "box7_done", "disband": disb, "next": nxt}
    # box 8: Plowing (end of box 8) + Spring Muster, then box-9 Levy.
    pl = winter_plowing(state)
    sm = spring_muster(state)
    state.pending = None
    state.calendar.current_box = 9
    _return_to_levy(state)
    return {"winter": "box8_done", "disband": disb, "plowing": pl,
            "spring_muster": sm, "phase": state.meta.phase}


def _h_winter_siege_action(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """6.3.2 bullet 1: the current Besieging Lord takes ONE Supply or
    Ravage action, or passes. Forage is NOT offered in Winter Siege."""
    side = _require_side(action)
    pd = _require_pending(state, "winter_siege", side)
    payload = pd.payload
    _require(payload["step"] == "besieger_actions",
             "not the Winter-Siege besieger-action step", code="wrong_winter_step")
    _require(payload["queue"], "no Besieging Lord awaiting an action",
             code="no_besieger")
    lord_id = payload["queue"][0]
    _require(state.lords[lord_id].side == side,
             f"the current Besieging Lord {lord_id} is not {side}'s",
             code="wrong_side")
    mode = action.get("mode")
    _require(mode in ("supply", "ravage", "pass"),
             "mode must be supply|ravage|pass", code="bad_arg")
    result = None
    if mode == "supply":
        with _MetaCtx(state, phase="campaign", campaign_step="activation",
                      active_player=side, active_lord_id=lord_id,
                      actions_remaining=1):
            result = _h_cmd_supply(state, {"type": "cmd_supply", "side": side,
                                           "source_seat": action.get("source_seat")})
    elif mode == "ravage":
        with _MetaCtx(state, phase="campaign", campaign_step="activation",
                      active_player=side, active_lord_id=lord_id,
                      actions_remaining=1):
            result = _h_cmd_ravage(state, {"type": "cmd_ravage", "side": side})
    # Lord done either way — remove from queue and progress.
    if payload["queue"] and payload["queue"][0] == lord_id:
        payload["queue"].pop(0)
    adv = _winter_advance(state)
    _record(state, action,
            f"Winter Siege (box {payload['box']}): {side} {lord_id} {mode}")
    return {"winter_action": mode, "lord": lord_id, "result": result,
            "advance": adv}


def _h_winter_siege_pay(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """6.3.2 bullet 3 (optional half): Christian then Muslim may Pay
    Lords at Sieges (3.2). `done` ends that side's Pay; after Muslim's
    `done` the mandatory at-limit Disband runs and the box completes."""
    side = _require_side(action)
    pd = _require_pending(state, "winter_siege", side)
    payload = pd.payload
    _require(payload["step"] == "pay", "not the Winter-Siege Pay step",
             code="wrong_winter_step")
    _require(side == payload["pay_side"],
             f"Pay step is waiting on {payload['pay_side']}, not {side}",
             code="not_pay_side")
    if action.get("done"):
        if payload["pay_side"] == "christian":
            payload["pay_side"] = "muslim"
            return {"winter_pay": "done", "next_side": "muslim",
                    "advance": _winter_advance(state)}
        return _finish_winter_box(state, payload["box"])
    # A Pay action — only Lords AT a Siege Locale may be Paid (6.3.2).
    target_id = action.get("target_lord_id")
    _require(target_id in _siege_locale_lords(state),
             "Winter Siege Pay may only target a Lord at a Siege Locale",
             code="not_at_siege")
    from almoravid.actions import _h_pay_lord
    with _MetaCtx(state, phase="levy", levy_step="pay", active_player=side):
        res = _h_pay_lord(state, {**action, "type": "pay_lord"})
    return {"winter_pay": res}






# ---------------------------------------------------------------------------
# 1.4.3 Adjust Status cascade (Phase 5l)
# ---------------------------------------------------------------------------


def _taifa_ravaged_count(state: GameState, taifa_id: str) -> int:
    """Count Ravaged markers (either color) in a Taifa's Locales."""
    taifa = state.taifas.get(taifa_id)
    if taifa is None:
        return 0
    return sum(1 for lid in taifa.locale_ids
               if state.locales[lid].ravaged != "none")


def _parias_coin_amount(state: GameState, taifa_id: str | None,
                        base: int) -> int:
    """1.4.3 Parias Coin amount. Under the Ruined Land special rule
    (Scenarios E & F) it is Service LESS the number of Ravaged markers
    (either side) in the Taifa, floored at zero."""
    if state.meta.ruined_land and taifa_id is not None:
        return max(0, base - _taifa_ravaged_count(state, taifa_id))
    return base


def adjust_taifa_status(state: GameState, taifa_id: str, new_status: str,
                        *, award_parias_coin: bool = True,
                        neutrality_choices: dict[str, Any] | None = None) -> dict[str, Any]:
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

    results: dict[str, Any] = {"taifa_id": taifa_id, "from": old_status, "to": new_status,
               "ravaged_flips": [], "auto_conquered": [],
               "siege_removed": [], "jihad_added": [],
               "deferred_neutrality": []}
    taifa.status = cast("TaifaStatus", new_status)

    # T5 (rule 1.4.3 PARIAS COIN): changing from Independent to Parias,
    # the Christians add Coin from the pool = the departing Taifa Lord's
    # Service (six if al-Mutamid / Sevilla, four otherwise) among any
    # Unbesieged Christian Lords. Awarded here so EVERY caller (Muster,
    # combat removal, recompute) triggers it; the Disband path passes
    # award_parias_coin=False and awards with its own player-chosen
    # distribution (1.4.3 / L7).
    if (old_status == "independent" and new_status == "parias"
            and award_parias_coin):
        from almoravid.actions import _award_parias_coin
        base = 6 if taifa_id == "sevilla" else 4
        amount = _parias_coin_amount(state, taifa_id, base)
        results["parias_coin"] = _award_parias_coin(state, amount, None)

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
    # Flip Ravaged markers in this Taifa (1.4.3). Each flip moves the
    # ½VP between sides in the running tally (yellow scores Christian,
    # green scores Muslim, 5.1 / Ravage handler 4.7.2).
    if flip_color_from:
        for lid in taifa.locale_ids:
            if state.locales[lid].ravaged == flip_color_from:
                state.locales[lid].ravaged = flip_color_to  # type: ignore[assignment]
                results["ravaged_flips"].append((lid, flip_color_from, flip_color_to))
                if flip_color_from == "yellow":
                    state.score.christian -= 0.5
                    state.score.muslim += 0.5
                else:
                    state.score.muslim -= 0.5
                    state.score.christian += 0.5

    # Force-Siege / force-Conquest at each Stronghold in the Taifa based
    # on Lord presence (1.4.3).
    going_christian_friendly = (new_status == "reconquista")
    going_neutral = (new_status == "parias")

    for lid in taifa.locale_ids:
        loc = state.locales[lid]
        if loc.base_type == "region":
            continue
        # Find Lords present at this Locale (one of each side, generally)
        present_christian = [
            lord.id for lord in state.lords.values()
            if lord.side == "christian"
            and lord.cylinder.kind == "locale"
            and lord.cylinder.locale_id == lid
        ]
        present_muslim = [
            lord.id for lord in state.lords.values()
            if lord.side == "muslim"
            and lord.cylinder.kind == "locale"
            and lord.cylinder.locale_id == lid
        ]
        # HOSTAGE POPULACE (1.4.3): a Muslim Lord force-Conquers only a
        # Stronghold that was Friendly/Neutral-to-him and turns Enemy or
        # (for ->Parias) Friendly->Neutral. ->Reconquista (christian =
        # enemy): old Independent (friendly) or Parias (neutral). ->Parias
        # (neutral): only old Independent (friendly->neutral). A
        # Reconquista (christian/enemy) Stronghold going Neutral is
        # RECOGNITION OF NEUTRALITY (the OR clause below), NOT Hostage.
        muslim_hostage = (
            (going_christian_friendly and old_status in ("independent",
                                                         "parias"))
            or (going_neutral and old_status == "independent"))
        if muslim_hostage:
            if present_muslim:
                # T3 (1.4.3 HOSTAGE POPULACE / 1.4.4): the Muslim Lord
                # forcibly Conquers, placing Jihad markers = the
                # Stronghold's Value via _conquer_stronghold (which also
                # applies 1.4.4 eligibility: removes Christian Conquered
                # + Christian Seat markers first, never double-stacks
                # with Conquered, and adjusts Victory). taifa.status is
                # already new_status (Parias/Reconquista) so Jihad is the
                # correct marker.
                cres = _conquer_stronghold(state, lid, "muslim")
                if cres.get("marker") == "jihad":
                    results["jihad_added"].append((lid, cres["value"]))
                elif cres.get("marker") == "conquered":
                    results["auto_conquered"].append(
                        (lid, "muslim", cres["value"]))
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
            if (present_muslim and (loc.siege_green > 0 or loc.bypass_green)
                    and loc.conquered_markers == 0 and loc.jihad_markers == 0):
                # T4 (1.4.3 RECOGNITION OF NEUTRALITY): the besieging
                # side CHOOSES either to remove its Siege/Bypass OR to
                # add Enemy victory markers (= Stronghold Value): a
                # Muslim besieger adds Christian Conquered. The choice is
                # surfaced via neutrality_choices[locale]="remove"|"add"
                # (no greedy default beyond the conservative "remove"
                # when the caller does not specify).
                from almoravid.static_data import load_strongholds
                v = load_strongholds()["strongholds"][loc.base_type]["value"]
                if neutrality_choices is not None and lid in neutrality_choices:
                    choice = neutrality_choices[lid]
                elif neutrality_choices is not None:
                    choice = "remove"      # explicit dict, default for this loc
                else:
                    # No explicit choices: DEFER for an interactive
                    # RECOGNITION OF NEUTRALITY decision (T4).
                    results["deferred_neutrality"].append(
                        {"locale_id": lid, "side": "muslim", "value": v})
                    choice = None
                if choice == "add":
                    loc.conquered_markers += v
                    state.score.christian += v
                    results["auto_conquered"].append(
                        (lid, "christian_recognition", v))
                elif choice == "remove":
                    loc.siege_green = 0
                    loc.bypass_green = False
                    results["siege_removed"].append((lid, "muslim_or_clause"))
        # Bug C (mirror gap audit): INDEPENDENT -> PARIAS —
        # Christian Lord at Muslim Stronghold that would go Neutral:
        # OR clause (1.4.3). Conservative: remove Siege/Bypass.
        if (old_status == "independent" and new_status == "parias"):
            if (present_christian
                    and (loc.siege_yellow > 0 or loc.bypass_yellow)
                    and loc.conquered_markers == 0 and loc.jihad_markers == 0):
                # T4 (1.4.3 RECOGNITION OF NEUTRALITY): a Christian
                # besieger CHOOSES to remove its Siege/Bypass OR add
                # Jihad markers (= Stronghold Value).
                from almoravid.static_data import load_strongholds
                v = load_strongholds()["strongholds"][loc.base_type]["value"]
                if neutrality_choices is not None and lid in neutrality_choices:
                    choice = neutrality_choices[lid]
                elif neutrality_choices is not None:
                    choice = "remove"
                else:
                    results["deferred_neutrality"].append(
                        {"locale_id": lid, "side": "christian", "value": v})
                    choice = None
                if choice == "add":
                    loc.jihad_markers += v
                    state.score.muslim += 0.5 * v
                    results["jihad_added"].append((lid, v))
                elif choice == "remove":
                    loc.siege_yellow = 0
                    loc.bypass_yellow = False
                    results["siege_removed"].append((lid, "christian_or_clause"))
        # Christian Lord at Neutral Stronghold "would go Muslim": Conquer
        if going_neutral or (new_status == "independent"
                              and old_status != "independent"):
            if present_christian and old_status in ("parias", "reconquista"):
                # T3 (1.4.3 HOSTAGE POPULACE): the Christian Lord forcibly
                # Conquers, placing Christian Conquered markers = the
                # Stronghold's Value via _conquer_stronghold (removes any
                # Jihad, adjusts Victory).
                cres = _conquer_stronghold(state, lid, "christian")
                results["auto_conquered"].append(
                    (lid, "christian", cres["value"]))
    return results


def maybe_recompute_taifa_status(state: GameState, taifa_id: str) -> dict[str, Any]:
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
                 seat for lord in state.lords.values()
                 for seat in lord.seats if lord.home_taifa == taifa_id
             ])
    ]
    all_christian = all(
        state.locales[lid].conquered_markers > 0
        for lid in target_locales
    ) if target_locales else False
    # Taifa Lord on map?
    taifa_lord_on_map = any(
        lord.is_taifa
        and lord.home_taifa == taifa_id
        and lord.cylinder.kind == "locale"
        for lord in state.lords.values()
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


def _is_laden(lord: Lord, way_type: str | None = None) -> bool:
    """A Lord is Laden if (rule 4.3.2):
      - a Mule or Cart carries TWO Provender (i.e. Provender exceeds the
        number of Transport units, so at least one unit must double up);
      - a Cart carries any Provender over a Pass (only Carts are hindered
        on Passes — Mules carry Provender over a Pass freely; the Cart
        must carry Provender only when Provender exceeds Mule capacity,
        2 per Mule); or
      - the Lord is moving any Loot.

    C4 (4.3.2): transport-carrying is now accounted for — Provender that
    fits one-per-Transport-unit is NOT Laden (the old code treated any
    >=2 Provender as Laden regardless of Transport). `way_type='pass'`
    adds the Cart-over-Pass trigger (so a single Cart carrying one
    Provender across a Pass is legal but Laden)."""
    prov = lord.assets.get("prov", 0)
    loot = lord.assets.get("loot", 0)
    cart = lord.assets.get("cart", 0)
    mule = lord.assets.get("mule", 0)
    transport = cart + mule
    if loot >= 1:
        return True
    if prov > transport:           # some Transport unit carries two
        return True
    if way_type == "pass" and cart > 0 and prov > 2 * mule:
        # Provender beyond Mule capacity must ride a Cart -> Laden on a Pass.
        return True
    return False


def _group_laden(state: GameState, lord_ids: list[str],
                 way_type: str | None = None) -> bool:
    """C3/C4 (4.3.1/4.3.2 SHARED TRANSPORT): a March group's Laden status
    is computed from the COMBINED Provender, Loot, Carts and Mules of all
    Lords moving together (1.5.2). Same triggers as _is_laden."""
    prov = loot = cart = mule = 0
    for lid in lord_ids:
        lord = state.lords.get(lid)
        if lord is None:
            continue
        prov += lord.assets.get("prov", 0)
        loot += lord.assets.get("loot", 0)
        cart += lord.assets.get("cart", 0)
        mule += lord.assets.get("mule", 0)
    transport = cart + mule
    if loot >= 1:
        return True
    if prov > transport:
        return True
    if way_type == "pass" and cart > 0 and prov > 2 * mule:
        return True
    return False


def _h_cmd_march(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    assert lord_id is not None
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
    assert from_loc is not None

    target = action.get("target_locale_id")
    target = cast(str, target)
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

    # C3 (4.3.1) Group March: a Marshal may lead any/all Unbesieged
    # same-Locale Lords (an explicit player-chosen group_lord_ids — no
    # greedy default). A Lieutenant's Lower Lord always moves with it.
    from almoravid.effective import is_besieged as _isb_grp
    group_req = list(action.get("group_lord_ids", []) or [])
    if group_req:
        # 4.3.1 + C8 Hueste: a Marshal, or a Hueste bearer on a March
        # with a Taifa endpoint, may lead a Group March.
        _require(_counts_as_marshal_for_march(state, lord_id, side,
                                              from_loc, target),
                 f"only a Marshal (or a Hueste bearer on a Taifa March) "
                 f"may lead a Group March (4.3.1); {lord_id} cannot",
                 code="not_marshal")
        # C8 Hueste: the bearer "may not use that ability to take Alfonso
        # along in his Marching Group" (only the true Marshal can lead the
        # Marshal). So when leading via Hueste (not the side's Marshal),
        # Alfonso may not be a group member.
        _hueste_lead = not _is_marshal(lord_id, side)
        for gid in group_req:
            if _hueste_lead:
                _require(gid != "alfonso",
                         "Hueste may not take Alfonso (the Marshal) along "
                         "in the Marching Group (Arts of War ref C8)",
                         code="hueste_no_alfonso")
            _require(gid in state.lords and gid != lord_id,
                     f"bad group member {gid!r}", code="bad_group")
            g = state.lords[gid]
            _require(g.side == side, f"{gid} not on {side}'s side",
                     code="wrong_side")
            _require(g.cylinder.kind == "locale"
                     and g.cylinder.locale_id == from_loc,
                     f"{gid} is not at {from_loc} with the Marshal (4.3.1)",
                     code="not_same_locale")
            _require(not _isb_grp(state, gid),
                     f"{gid} is Besieged and cannot Group March (4.3.1)",
                     code="besieged")
    # The full moving set: the active Lord + the chosen group + every
    # Lower Lord stacked under any mover (Lieutenants move their Lower
    # Lord, 4.1.3/4.3.1).
    moving = {lord_id, *group_req}
    for mover in list(moving):
        for lord_obj in state.lords.values():
            if (lord_obj.lieutenant_of == mover and lord_obj.cylinder.kind == "locale"
                    and lord_obj.cylinder.locale_id == from_loc):
                moving.add(lord_obj.id)
    moving_lords = sorted(moving)
    # 1.7.2 Provender capacity: each Cart/Mule carries up to TWO
    # Provender, so the (shared) Transport caps carriable Provender at
    # 2 x (Carts + Mules); any excess must be discarded to March. (The
    # Pass affects only Laden status for a March, not capacity — a Cart
    # may carry Provender over a Pass, it just makes the Lord Laden.)
    g_prov = sum(state.lords[m].assets.get("prov", 0) for m in moving_lords)
    g_loot = sum(state.lords[m].assets.get("loot", 0) for m in moving_lords)
    g_cart = sum(state.lords[m].assets.get("cart", 0) for m in moving_lords)
    g_mule = sum(state.lords[m].assets.get("mule", 0) for m in moving_lords)
    g_transport = g_cart + g_mule
    capacity = 2 * g_transport
    prov_excess = max(0, g_prov - capacity)
    prov_eff = g_prov - prov_excess
    # Shared Transport (4.3.2): Laden uses the COMBINED post-discard
    # assets (a unit carries two, or a Cart carries Provender over a
    # Pass, or any Loot moves).
    laden = (g_loot >= 1
             or prov_eff > g_transport
             or (way_type == "pass" and g_cart > 0 and prov_eff > 2 * g_mule))
    cost = 2 if laden else 1
    _require(state.meta.actions_remaining >= cost,
             f"March costs {cost} actions ({'Laden' if laden else 'Unladen'}), "
             f"only {state.meta.actions_remaining} remaining",
             code="not_enough_actions")

    # C4 (4.3.2): a Cart carrying Provender over a Pass is LEGAL but
    # Laden (already reflected in `laden`/`cost` above) — no longer
    # rejected. (Only Carts are hindered on Passes; Mules carry
    # Provender over a Pass freely.)

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
            # Declaring a March is legal; the enemy's reactive Swollen
            # River Hold event INTERRUPTS it (the Lord does not move and
            # may not March again on this card, but other actions remain).
            # Modelled as a legal "blocked" outcome — not an IllegalAction
            # — so legal_moves -> apply_action stays total (Pattern 9).
            state.meta.swollen_river_blocked_card_lord_id = lord_id
            _record(state, action,
                    f"Swollen River ({swollen_id}) played by {enemy} blocks "
                    f"{lord_id}'s March on this card (4.3.4); Lord does not "
                    f"move, other actions on the card remain")
            return {"from": from_loc, "to": None, "moved": False,
                    "swollen_river_blocked": True, "by": swollen_id,
                    "actions_remaining": state.meta.actions_remaining}
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
            lord_obj.cylinder.kind == "locale" and lord_obj.cylinder.locale_id == target
            for lord_obj in state.lords.values()
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

    # 1.7.2: discard Provender the group cannot carry (beyond capacity).
    to_discard = prov_excess
    for mid in moving_lords:
        if to_discard <= 0:
            break
        m = state.lords[mid]
        have = m.assets.get("prov", 0)
        drop = min(have, to_discard)
        if drop > 0:
            m.assets["prov"] = have - drop
            if m.assets["prov"] == 0:
                m.assets.pop("prov", None)
            to_discard -= drop
    # Execute March: move the whole group (Marshal + chosen Lords +
    # Lieutenant Lower Lords) together (4.3.1). On arrival at a
    # Stronghold each Lord is outside walls by default.
    from almoravid.state import Cylinder
    for mid in moving_lords:
        m = state.lords[mid]
        m.cylinder = Cylinder(kind="locale", locale_id=target)
        m.in_stronghold = False
        m.moved_fought = True
    lord.first_march_used_this_card = True  # Pattern 3 per-card flag
    state.meta.actions_remaining -= cost
    # 4.3.5/4.3.6 DEPART: if the group's departure leaves the origin
    # Stronghold free of this side's Lords, remove our Siege/Bypass
    # markers there ("becomes free of Enemy Lords ... remove markers").
    _remove_orphaned_siege_bypass(state, from_loc)
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


def _own_seats(state: GameState, lord_id: str) -> list[str]:
    """Locale ids that are Seats for this Lord. Per the 4.6 NOTE, this is
    the printed Pennant Seats (static data) PLUS any movable Seat markers
    on the map — Rodrigo/Yusuf/Sir's Seat markers and (via Cathedrals)
    Alfonso's — which all live in Locale.seat_marker_lord_ids."""
    from almoravid.static_data import load_lords
    seats = set(load_lords()["lords"][lord_id].get("seats", []))
    for lid, loc in state.locales.items():
        if lord_id in loc.seat_marker_lord_ids:
            seats.add(lid)
    return sorted(seats)


def _route_blocked_by_enemy(state: GameState, route: list[str],
                            side: Side) -> bool:
    """Per rule 4.6.1: route may not include a Locale with an Enemy
    Stronghold or Lord, unless that Enemy is Besieged or Bypassed.

    Phase 5b simplification: an Enemy Stronghold is any Locale whose
    territory is unfriendly to `side` per is_friendly_locale, and an
    Enemy Lord is any opposing-side Lord physically present. Bypassed
    /Besieged exemptions consult effective.is_besieged / is_bypassed.
    """
    from almoravid.effective import is_besieged, is_bypassed, is_friendly_locale
    other: Side = "muslim" if side == "christian" else "christian"
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





def _find_supply_routes(state: GameState, here: str, seats: list[str],
                          side: Side, lord: Lord) -> dict[str, list[str] | None]:
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

def _h_cmd_supply(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord — reveal a card first",
             code="no_active_lord")
    lord_id = state.meta.active_lord_id
    assert lord_id is not None
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
    assert here is not None
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


def _h_cmd_tax(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    assert lord_id is not None
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
    assert here is not None
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


def _h_cmd_forage(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    assert lord_id is not None
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    _require(state.meta.actions_remaining >= 1,
             "Forage costs 1 action", code="not_enough_actions")

    here = lord.cylinder.locale_id
    assert here is not None
    loc = state.locales[here]
    friendly = is_friendly_locale(state, here, side)
    is_stronghold = loc.base_type != "region"
    besieged = is_besieged(state, lord_id)
    # 4.7.1 PROCEDURE: "Forage in a Friendly Stronghold adds one Provender
    # automatically. For Forage anywhere else, roll a die." GARDENS (City
    # or Fortress only) auto-add even if the Locale is Ravaged or the Lord
    # is Besieged.
    gardens_path = has_gardens(state, here) and friendly
    friendly_strong_auto = (friendly and is_stronghold and not besieged
                            and loc.ravaged == "none")
    auto = gardens_path or friendly_strong_auto
    if besieged:
        # The Lord may not be Besieged (4.7.1) — EXCEPTION: Gardens.
        _require(gardens_path,
                 "Besieged Lord may Forage only at his Friendly City/Fortress "
                 "Gardens (4.7.1)",
                 code="besieged_no_gardens")
    if not auto:
        # Forage "anywhere else": the Locale may not be Ravaged; roll a die.
        _require(loc.ravaged == "none",
                 f"Cannot Forage Ravaged Locale {here}",
                 code="ravaged")

    if auto:
        new_prov = min(8, lord.assets.get("prov", 0) + 1)
        lord.assets["prov"] = new_prov
        path = "gardens" if gardens_path else "friendly_stronghold"
        _record(state, action,
                f"{side} {lord_id} Forages ({path}) at {here} (+1 Prov -> "
                f"{new_prov})")
        state.meta.actions_remaining -= 1
        return {"path": path, "prov_after": new_prov, "roll": None,
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


def _h_cmd_ravage(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.7.2 Ravage: 1 action. Not Besieged. Enemy Locale not already
    Ravaged by this side.

    Effects:
      - Place this side's Ravaged marker (yellow=Christian, green=Muslim).
      - VP adjust: 1/2 VP per Ravaged marker (5.1).
      - Rustling: at Stronghold +1 Loot AND +1 Prov; at Region +1 Loot.
      - Enforcing Parias: if this is the 1st, 3rd, 5th... CHRISTIAN
        (yellow) Ravaged marker in the Taifa, shift that Taifa Lord's
        (not Yusuf/Sir/Rodrigo) Service 1 box left (applied below via
        _shift_service_left).
    """
    from almoravid.effective import is_besieged, is_friendly_locale

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    assert lord_id is not None
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
    assert here is not None
    loc = state.locales[here]
    # Enemy Locale: not Friendly to active side (rule 4.7.2 "locale_is_enemy")
    _require(not is_friendly_locale(state, here, side),
             f"Cannot Ravage Friendly Locale {here}", code="friendly_locale")
    # 4.7.2: Ravage may only target a Locale "not yet Ravaged" — neither
    # color. (Markers flip to Enemy color only via Conquest, 1.3.1.)
    _require(loc.ravaged == "none",
             f"{here} is already Ravaged (4.7.2 targets an un-Ravaged Locale)",
             code="already_ravaged")

    res = _apply_ravage_effect(state, lord, side, here)
    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{side} {lord_id} Ravages {here}: {res['rustling']}, "
            f"+0.5 VP{', Enforcing Parias triggered' if res['enforcing_parias'] else ''}")
    return {"locale": here, "color": res["color"], "rustling": res["rustling"],
            "enforcing_parias": res["enforcing_parias"],
            "actions_remaining": state.meta.actions_remaining}


def _apply_ravage_effect(state: GameState, lord: Lord, side: Side,
                         target_id: str) -> dict[str, Any]:
    """Shared 4.7.2 Ravage EFFECT applied to `target_id` (which may differ
    from the Lord's Locale for long-range Ravage / Cabalgadas): place the
    side's Ravaged marker, Rustling (Loot/Prov to the Ravaging Lord, War
    Drums M22 bonus), +1/2 VP, and the Enforcing-Parias odd-marker Taifa
    Service shift. Does NOT spend actions/Provender (the caller does)."""
    loc = state.locales[target_id]
    color = "yellow" if side == "christian" else "green"
    loc.ravaged = color  # type: ignore[assignment]
    from almoravid.capabilities import side_has_capability
    war_drums_bonus = 0
    if (side == "muslim" and side_has_capability(state, "muslim", "M22")
            and (lord.id in ("yusuf", "sir") or lord.is_lieutenant)):
        war_drums_bonus = 1
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
        rustling_note = (f"+1 Loot -> {new_loot}, +{1 + war_drums_bonus} "
                         f"Prov -> {new_prov} (Stronghold"
                         f"{'/War Drums' if war_drums_bonus else ''})")
    if side == "christian":
        state.score.christian += 0.5
    else:
        state.score.muslim += 0.5
    enforcing_parias = False
    if side == "christian" and loc.territory in state.taifas:
        cnt = sum(1 for lid in state.taifas[loc.territory].locale_ids
                  if state.locales[lid].ravaged == "yellow")
        if cnt % 2 == 1:
            enforcing_parias = True
            from almoravid.actions import _shift_service_left
            for tlid, tlord in state.lords.items():
                if (tlord.is_taifa and tlord.home_taifa == loc.territory
                        and tlord.cylinder.kind == "locale"
                        and tlid not in ("yusuf", "sir", "rodrigo_campeador",
                                         "rodrigo_al_sayyid")):
                    _shift_service_left(state, tlid, 1)
    return {"color": color, "rustling": rustling_note,
            "enforcing_parias": enforcing_parias}



# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 4.5.1 Surrender + 1.3.1 / 1.4.4 Conquest (Phase 5i)
# ---------------------------------------------------------------------------


def _ravaged_count_in_taifa_for_side(state: GameState, locale_id: str,
                                     side: Side) -> int:
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


def _conquer_stronghold(state: GameState, locale_id: str,
                        conquering_side: Side) -> dict[str, Any]:
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
    # Full Table 4 rule (implemented below):
    #   - Muslim conquers a Parias/Reconquista Taifa Stronghold -> Jihad;
    #   - otherwise (incl. Christian conquest, Muslim conquest of a
    #     Christian Kingdom) -> Conquered.
    # 1.4.4 / 4.5: Muslim Conquest of ANY Stronghold in a Parias or
    # Reconquista Taifa places Jihad markers (1 per Stronghold Value)
    # AND removes any Christian Conquered + Christian Seat markers
    # there. Christian Conquest (anywhere), and Muslim Conquest of a
    # Christian Kingdom, place Conquered markers AND remove all Jihad.
    # A Locale never holds both Conquered and Jihad markers.
    place_jihad = (conquering_side == "muslim" and taifa is not None
                   and taifa.status in ("parias", "reconquista"))
    removed: dict[str, Any] = {}
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
        # A Cathedral Seat is removed when the Enemy Conquers the City.
        if locale_id in state.cathedral_seat_locales:
            state.cathedral_seat_locales.remove(locale_id)
            removed["cathedral_seat"] = locale_id
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
    # 1.3.1: Conquest of a Stronghold flips a Ravage marker there to the
    # NON-conquering (Enemy) side's color. The summary (4.5) phrases it
    # "Conquest flips Ravage to Enemy color"; the 4.5.1 Surrender bullet
    # conditions on "if the Conquering side has a Ravaged marker there,
    # flip it" — i.e. only the conqueror's own-color marker flips (to the
    # Enemy). A marker already in the Enemy's color is unchanged. Design:
    # ravaged land you just took now scores its ½VP penalty against you.
    # The running state.score tracks Ravage ½VP incrementally (placed in
    # the Ravage handler, 4.7.2), so the flip moves 0.5 between sides.
    ravaged_flip = None
    enemy_color = "green" if conquering_side == "christian" else "yellow"
    own_color = "yellow" if conquering_side == "christian" else "green"
    if loc.ravaged == own_color:
        loc.ravaged = enemy_color  # type: ignore[assignment]
        ravaged_flip = (own_color, enemy_color)
        if conquering_side == "christian":
            state.score.christian -= 0.5
            state.score.muslim += 0.5
        else:
            state.score.muslim -= 0.5
            state.score.christian += 0.5
    # Remove the Conquering side's Siege markers (Conquest ends Siege).
    if conquering_side == "christian":
        loc.siege_yellow = 0
        state.score.christian += vp_delta
    else:
        loc.siege_green = 0
        state.score.muslim += vp_delta
    return {"locale": locale_id, "marker": marker, "value": sh_value,
            "vp_delta": vp_delta, "conquered_total": loc.conquered_markers,
            "jihad_total": loc.jihad_markers, "removed": removed,
            "ravaged_flip": ravaged_flip}



# 4.5.1 Siege (Phase 5d minimal-viable)
# ---------------------------------------------------------------------------


def _h_cmd_siege(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    assert lord_id is not None
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord cannot Siege (4.5.1)", code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    here = lord.cylinder.locale_id
    assert here is not None
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

    from almoravid.rng import roll_d6_n
    from almoravid.static_data import load_strongholds
    capacity = load_strongholds()["strongholds"][loc.base_type]["capacity"]
    sh_value = load_strongholds()["strongholds"][loc.base_type]["value"]

    enemy_inside = any(
        lord_obj for lord_obj in state.lords.values()
        if lord_obj.side != side and lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == here and lord_obj.in_stronghold
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
                    lord_obj.id for lord_obj in state.lords.values()
                    if lord_obj.side == side and lord_obj.cylinder.kind == "locale"
                    and lord_obj.cylinder.locale_id == here
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

    # 4.5.1 MOVED/FOUGHT: "Finally, mark all Lords of both sides there
    # as Fought." This holds whether the Stronghold Surrendered, gained
    # Siegeworks, or neither — every Lord (both sides) at the Locale is
    # marked, so they must Feed at end of card (4.8.1) and cannot escape
    # the Feed by Besieging. Besieged Lords inside count as "there".
    fought_marked = []
    for other in state.lords.values():
        if other.cylinder.kind == "locale" and other.cylinder.locale_id == here:
            if not other.moved_fought:
                other.moved_fought = True
                fought_marked.append(other.id)

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
            "fought_marked": fought_marked,
            "actions_consumed": consumed}



# ---------------------------------------------------------------------------
# 4.4 Battle (Phase 5e — single-Lord baseline; multi-Lord arrays land
# with Reserve/Flanking handling in Phase 5e+).
# ---------------------------------------------------------------------------


def _finish_sally(
    state: GameState,
    action: dict[str, Any],
    *,
    atk: Any,
    dfd: Any,
    result: Any,
    pl: dict[str, Any],
) -> dict[str, Any]:
    """Post-Sally aftermath (4.5.3), shared by the synchronous cmd_sally
    path and the interactive battle_concede driver."""
    from almoravid.battle import apply_sally_aftermath, commit_forces_after_battle
    side: Side = pl["side"]
    here: str = pl["here"]
    commit_forces_after_battle(state, atk)
    if len(dfd.lord_ids) == 1:
        commit_forces_after_battle(state, dfd)
    apply_sally_aftermath(state, result, here)
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    _record(state, action,
            f"{side} {pl['lord_id']} Sallies at {here}: "
            f"winner={result.winner}, rounds={len(result.rounds)}; "
            f"card spent ({consumed} actions)")
    return {"winner": result.winner, "rounds": len(result.rounds),
            "actions_consumed": consumed}


def _finish_open_field_battle(
    state: GameState,
    action: dict[str, Any],
    *,
    atk: Any,
    dfd: Any,
    result: Any,
    pl: dict[str, Any],
) -> dict[str, Any]:
    """Post-Battle aftermath for an open-field Battle (4.4.3-.5), shared by
    the synchronous `cmd_battle` path and the interactive (round-stepped)
    battle_concede driver so the two cannot diverge."""
    from almoravid.battle import (
        apply_aftermath,
        apply_battle_losses,
        apply_retreat_aftermath,
        commit_forces_after_battle,
    )
    side: Side = pl["side"]
    here: str = pl["here"]
    commit_forces_after_battle(state, atk)
    commit_forces_after_battle(state, dfd)
    # Bug P fix: Retreat aftermath FIRST so C7 opt-out can fire.
    retreat_summary = apply_retreat_aftermath(state, result)
    apply_battle_losses(state, result, retreat_summary)
    apply_aftermath(state, result)
    # Battle ends the card (rule 4.4.5).
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    # C1b (4.3.5): force Besiege-or-Bypass if the loser Withdrew inside.
    bb = _set_besiege_or_bypass_pending(state, here, side,
                                        pl.get("active_lord_id"))
    _record(state, action,
            f"{side} {pl['our_at_here']} Battles {pl['enemy_lord_ids']} at "
            f"{here}: winner={result.winner}, rounds={len(result.rounds)}; "
            f"card spent ({consumed} actions)"
            + ("; Besiege-or-Bypass pending" if bb else ""))
    return {
        "winner": result.winner,
        "rounds": len(result.rounds),
        "attacker_routed": dict(atk.routed_units),
        "defender_routed": dict(dfd.routed_units),
        "actions_consumed": consumed,
        "retreat_summary": retreat_summary,
    }


def _begin_interactive_battle(
    state: GameState,
    action: dict[str, Any],
    atk: Any,
    dfd: Any,
    pl: dict[str, Any],
    *,
    defender_walls_range: tuple[int, int] | None = None,
    max_rounds: int = 6,
) -> dict[str, Any]:
    """Start a reactive (round-stepped) Battle: do the once-per-Battle
    start consumption, snapshot both sides into a `battle_concede` pending
    decision, and pause for the Round-1 Concede declaration (4.4.2)."""
    from almoravid.battle import (
        BattleResult,
        _consume_camp_attack,
        battle_side_to_snapshot,
        init_m7_cap,
    )
    init_m7_cap(state, atk)
    init_m7_cap(state, dfd)
    _consume_camp_attack(
        state, atk, dfd,
        BattleResult(engagement=pl["engagement_label"], attacker=atk,
                     defender=dfd))
    pl = dict(pl)
    pl["round_idx"] = 1
    pl["max_rounds"] = max_rounds
    pl["rounds_done"] = 0
    pl["attacker"] = battle_side_to_snapshot(atk)
    pl["defender"] = battle_side_to_snapshot(dfd)
    pl["defender_walls_range"] = (list(defender_walls_range)
                                  if defender_walls_range else None)
    state.pending = PendingDecision(
        kind="battle_concede", waiting_on=pl["side"], payload=pl)
    state.meta.active_player = pl["side"]
    return {"battle": "awaiting_concede", "round": 1,
            "engagement": pl["engagement_label"]}


def _h_battle_concede(state: GameState,
                      action: dict[str, Any]) -> dict[str, Any]:
    """Resolve one Round of a reactive Battle after its start-of-Round
    Concede declaration (rule 4.4.2). The response carries this Round's
    `attacker_concede` / `defender_concede` booleans (Attacker then
    Defender). Runs the Round; if a side Conceded, the Battle is over by
    Rout, or the Round cap is hit, finishes via the shared aftermath;
    otherwise re-pends for the next Round's declaration."""
    from almoravid.battle import (
        BattleResult,
        BattleRound,
        _battle_one_round,
        _battle_over,
        _side_all_lords_routed,
        battle_side_from_snapshot,
        battle_side_to_snapshot,
    )
    side = _require_side(action)
    pd = _require_pending(state, "battle_concede", side)
    pl = pd.payload
    atk = battle_side_from_snapshot(pl["attacker"])
    dfd = battle_side_from_snapshot(pl["defender"])
    round_idx: int = pl["round_idx"]
    dwr_raw = pl.get("defender_walls_range")
    dwr: tuple[int, int] | None = (
        (int(dwr_raw[0]), int(dwr_raw[1])) if dwr_raw else None)
    # Apply this Round's Concede declarations (Attacker then Defender).
    if bool(action.get("attacker_concede")):
        atk.conceded = True
    if bool(action.get("defender_concede")):
        dfd.conceded = True
    _battle_one_round(state, atk, dfd, round_idx, defender_walls_range=dwr)
    rounds_done: int = pl["rounds_done"] + 1
    ended = (atk.conceded or dfd.conceded
             or _battle_over(atk, dfd)
             or round_idx >= pl["max_rounds"])
    if not ended:
        atk.conceded = False
        dfd.conceded = False
        pl = dict(pl)
        pl["attacker"] = battle_side_to_snapshot(atk)
        pl["defender"] = battle_side_to_snapshot(dfd)
        pl["round_idx"] = round_idx + 1
        pl["rounds_done"] = rounds_done
        state.pending = PendingDecision(
            kind="battle_concede", waiting_on=side, payload=pl)
        return {"battle": "in_progress", "round_resolved": round_idx,
                "rounds_done": rounds_done}
    # Battle ended this Round -> winner + aftermath.
    result = BattleResult(engagement=pl["engagement_label"],
                          attacker=atk, defender=dfd)
    result.rounds = [BattleRound(index=i) for i in range(1, rounds_done + 1)]
    if atk.conceded and not dfd.conceded:
        result.winner = dfd.side
    elif dfd.conceded and not atk.conceded:
        result.winner = atk.side
    elif (not _side_all_lords_routed(atk)
          and _side_all_lords_routed(dfd)):
        result.winner = atk.side
    elif (not _side_all_lords_routed(dfd)
          and _side_all_lords_routed(atk)):
        result.winner = dfd.side
    else:
        result.winner = None
    state.pending = None
    if pl.get("finish") == "sally":
        return _finish_sally(state, action, atk=atk, dfd=dfd,
                             result=result, pl=pl)
    return _finish_open_field_battle(state, action, atk=atk, dfd=dfd,
                                     result=result, pl=pl)


def _h_cmd_battle(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.4 Battle: end-of-card action.

    Active Lord at a Locale containing exactly one Enemy Lord triggers
    a Battle. Both Lords participate; Battle resolution is deterministic
    per seed.

    Phase 5e: only single-Lord-each-side Battles supported. If multiple
    Lords are on either side at the Locale, raises IllegalAction with
    code='multi_lord_battle' (Phase 5e+ work).
    """
    from almoravid.battle import (
        _front_lord_count,
        battleside_for_lords,
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
    assert lord_id is not None
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord cannot Battle; must Sally instead (4.5.3)",
             code="besieged")
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    here = lord.cylinder.locale_id
    assert here is not None

    # Find enemy Lord(s) at this Locale
    other: Side = "muslim" if side == "christian" else "christian"
    enemy_lord_ids = [
        lord_obj.id for lord_obj in state.lords.values()
        if lord_obj.side == other
        and lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == here
        and not is_besieged(state, lord_obj.id)  # 4.4 doesn't engage besieged Lords here
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
        lord_obj.id for lord_obj in state.lords.values()
        if lord_obj.side == side
        and lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == here
        and not lord_obj.in_stronghold
    ]
    other = "muslim" if side == "christian" else "christian"
    atk = battleside_for_lords(state, our_at_here, side, "attacker",
                               active_lord_id=state.meta.active_lord_id)
    # B4 (4.4.1): the Defender places one Lord opposite each Attacking
    # Front Lord; extras go to Reserve. Cap the Defender's Front count
    # at the Attacker's populated Front-Lord count.
    dfd = battleside_for_lords(state, enemy_lord_ids, other, "defender",
                               front_limit=_front_lord_count(atk))
    pl: dict[str, Any] = {
        "engagement_label": "battle",
        "side": side,
        "here": here,
        "our_at_here": our_at_here,
        "enemy_lord_ids": enemy_lord_ids,
        "active_lord_id": state.meta.active_lord_id,
    }
    # Reactive (round-stepped) Concede: pause for a per-Round Concede
    # declaration (4.4.2). Opt-in so the synchronous default is unchanged.
    if bool(action.get("interactive_concede")):
        return _begin_interactive_battle(state, action, atk, dfd, pl)
    result = resolve_battle(
        state, atk, dfd,
        attacker_concede_round=_concede_round_arg(
            action, "attacker_concede_round"),
        defender_concede_round=_concede_round_arg(
            action, "defender_concede_round"))
    return _finish_open_field_battle(state, action, atk=atk, dfd=dfd,
                                     result=result, pl=pl)



# ---------------------------------------------------------------------------
# 4.5.2 Storm + 4.5.3 Sally (Phase 5f)
# ---------------------------------------------------------------------------


def _begin_interactive_storm(
    state: GameState,
    action: dict[str, Any],
    atk: Any,
    dfd: Any,
    pl: dict[str, Any],
    *,
    walls_range_override: tuple[int, int] | None = None,
    reposition_defender: bool = True,
) -> dict[str, Any]:
    """Start a reactive Storm: build the per-Lord context, resolve Round 1
    immediately (S10 Concede is Attacker-only, Round 2+), then pause on a
    storm_concede decision before Round 2 (or finish if the Storm ended)."""
    from almoravid.battle import (
        BattleResult,
        _storm_attacker_alive,
        _storm_defender_alive,
        _storm_finalize,
        _storm_run_round,
        _storm_setup,
        _storm_winner,
        battle_side_to_snapshot,
    )
    ss, max_rounds = _storm_setup(
        state, atk, dfd, walls_range_override=walls_range_override,
        reposition_defender=reposition_defender)
    result = BattleResult(engagement="storm", attacker=atk, defender=dfd)
    result.rounds.append(_storm_run_round(state, atk, dfd, ss, 1))
    pl = dict(pl)
    pl["ss"] = ss
    pl["max_rounds"] = max_rounds
    pl["rounds_done"] = 1
    over = (not _storm_attacker_alive(ss)
            or not _storm_defender_alive(ss, dfd))
    if over or max_rounds < 2:
        _storm_finalize(ss, atk, dfd, result)
        _storm_winner(result, ss, atk, dfd, conceded=False,
                      max_rounds=max_rounds)
        state.pending = None
        return _finish_storm(state, action, atk=atk, dfd=dfd, result=result,
                             pl=pl)
    pl["attacker"] = battle_side_to_snapshot(atk)
    pl["defender"] = battle_side_to_snapshot(dfd)
    pl["round_idx"] = 2
    state.pending = PendingDecision(
        kind="storm_concede", waiting_on=pl["side"], payload=pl)
    state.meta.active_player = pl["side"]
    return {"storm": "awaiting_concede", "round": 2}


def _h_storm_concede(state: GameState,
                     action: dict[str, Any]) -> dict[str, Any]:
    """Resolve one Storm Round after its start-of-Round Attacker Concede
    declaration (S10, Round 2+). `attacker_concede` ends the Storm with the
    Attacker as loser; otherwise the Round runs and the Storm either ends or
    re-pends for the next Round."""
    from almoravid.battle import (
        BattleResult,
        BattleRound,
        _storm_attacker_alive,
        _storm_defender_alive,
        _storm_finalize,
        _storm_run_round,
        _storm_winner,
        battle_side_from_snapshot,
        battle_side_to_snapshot,
    )
    side = _require_side(action)
    pd = _require_pending(state, "storm_concede", side)
    pl = pd.payload
    atk = battle_side_from_snapshot(pl["attacker"])
    dfd = battle_side_from_snapshot(pl["defender"])
    ss = pl["ss"]
    round_idx: int = pl["round_idx"]
    max_rounds: int = pl["max_rounds"]
    if bool(action.get("attacker_concede")):
        result = BattleResult(engagement="storm", attacker=atk, defender=dfd)
        result.rounds = [BattleRound(index=i)
                         for i in range(1, pl["rounds_done"] + 1)]
        result.notes.append(
            f"Attacker Concedes at start of Round {round_idx}")
        _storm_finalize(ss, atk, dfd, result)
        _storm_winner(result, ss, atk, dfd, conceded=True,
                      max_rounds=max_rounds)
        state.pending = None
        return _finish_storm(state, action, atk=atk, dfd=dfd, result=result,
                             pl=pl)
    result = BattleResult(engagement="storm", attacker=atk, defender=dfd)
    _storm_run_round(state, atk, dfd, ss, round_idx)
    rounds_done: int = pl["rounds_done"] + 1
    over = (not _storm_attacker_alive(ss)
            or not _storm_defender_alive(ss, dfd))
    if over or round_idx >= max_rounds:
        result.rounds = [BattleRound(index=i)
                         for i in range(1, rounds_done + 1)]
        _storm_finalize(ss, atk, dfd, result)
        _storm_winner(result, ss, atk, dfd, conceded=False,
                      max_rounds=max_rounds)
        state.pending = None
        return _finish_storm(state, action, atk=atk, dfd=dfd, result=result,
                             pl=pl)
    pl = dict(pl)
    pl["ss"] = ss
    pl["attacker"] = battle_side_to_snapshot(atk)
    pl["defender"] = battle_side_to_snapshot(dfd)
    pl["round_idx"] = round_idx + 1
    pl["rounds_done"] = rounds_done
    state.pending = PendingDecision(
        kind="storm_concede", waiting_on=side, payload=pl)
    return {"storm": "in_progress", "round_resolved": round_idx,
            "rounds_done": rounds_done}


def _finish_storm(
    state: GameState,
    action: dict[str, Any],
    *,
    atk: Any,
    dfd: Any,
    result: Any,
    pl: dict[str, Any],
) -> dict[str, Any]:
    """Post-Storm aftermath (4.5.2 commit + Sack + Losses), shared by the
    synchronous cmd_storm path and the interactive storm_concede driver."""
    from almoravid.battle import apply_aftermath, commit_forces_after_battle
    side: Side = pl["side"]
    here: str = pl["here"]
    enemy_inside: list[str] = pl["enemy_inside"]
    lord_id: str = pl["lord_id"]
    loc = state.locales[here]
    # S11b: commit each besieging Lord and each Defender Lord exactly
    # from the per-Lord post-Storm forces (resolve_storm tracked them).
    if result.attacker_lord_forces:
        for bid, f in result.attacker_lord_forces.items():
            if bid in state.lords:
                state.lords[bid].forces = dict(f)
                # S11b: write per-Lord Routed units so 4.4.4 Storm Losses
                # (apply_battle_losses storm=True) roll per-Lord and any
                # survivors return to that Lord's Forces.
                state.lords[bid].routed_units = dict(
                    result.attacker_lord_routed.get(bid, {}))
    else:
        commit_forces_after_battle(state, atk)
    if result.defender_lord_forces:
        for did, f in result.defender_lord_forces.items():
            if did in state.lords:
                state.lords[did].forces = dict(f)
                state.lords[did].routed_units = dict(
                    result.defender_lord_routed.get(did, {}))
    elif len(dfd.lord_ids) == 1:
        commit_forces_after_battle(state, dfd)

    # 4.5.2 SACK: if the Besieged Defenders lose the Storm, the
    # Stronghold is Sacked.
    conq_result = None
    sack = None
    if result.winner == side:
        from almoravid.actions import _shift_service_left as _ssl
        from almoravid.battle import distribute_spoils_round_robin
        from almoravid.state import Cylinder
        from almoravid.static_data import load_strongholds as _ls
        # Besieging Lords present (Spoils recipients).
        besiegers_here = [
            lord_obj.id for lord_obj in state.lords.values()
            if lord_obj.side == side and lord_obj.cylinder.kind == "locale"
            and lord_obj.cylinder.locale_id == here
        ]
        sack_spoils: dict[AssetType, int] = {}
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


def _h_cmd_storm(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.5.2 Storm. Active Lord outside a Besieged Stronghold (i.e.,
    with at least one of our Siege markers at the Locale) assaults
    the defending Garrison + any besieged enemy Lords inside.

    Uses entire card. Resolution via battle.resolve_storm.
    """
    from almoravid.battle import (
        BattleSide,
        battleside_for_lord,
        resolve_storm,
    )
    from almoravid.effective import is_besieged, is_friendly_locale

    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    assert lord_id is not None
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord must Sally not Storm", code="besieged")
    _apply_absorption_policy(state, side, action)
    _require(lord.cylinder.kind == "locale",
             f"{lord_id} not at a Locale", code="not_on_map")
    here = lord.cylinder.locale_id
    assert here is not None
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
        lord_obj.id for lord_obj in state.lords.values()
        if lord_obj.side != side
        and lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == here
        and lord_obj.in_stronghold
    ]
    # S11b (4.5.2): all besieging Lords at the Locale (outside the
    # Stronghold) may Storm together — the Active Lord starts at Front,
    # the others in Reserve (resolve_storm handles Front/Reserve +
    # Reposition). Build the multi-besieger Attacker side, Active first.
    besieger_ids = [lord_id] + [
        lord_obj.id for lord_obj in state.lords.values()
        if lord_obj.side == side and lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == here and not lord_obj.in_stronghold
        and lord_obj.id != lord_id]
    if len(besieger_ids) == 1:
        atk = battleside_for_lord(state, lord_id, "attacker")
    else:
        a_forces: dict[UnitType, int] = {}
        a_caps: list[str] = []
        for bid in besieger_ids:
            for ut, n in state.lords[bid].forces.items():
                a_forces[ut] = a_forces.get(ut, 0) + n
            a_caps.extend(state.lords[bid].capabilities)
        atk = BattleSide(side=side, role="attacker", lord_ids=besieger_ids,
                         forces=a_forces, capabilities_in_play=a_caps)
    # Build defender side. If multiple Lords inside, aggregate (Phase 5f).
    if enemy_inside:
        dfd_forces: dict[UnitType, int] = {}
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
    # Phase 6i: C6 Surprise pending -> modify walls_range to -1.
    surprise_loc = state.meta.surprise_storm_pending_locale_id
    walls_override: tuple[int, int] | None = None
    if surprise_loc == here:
        from almoravid.static_data import load_strongholds
        base_walls = load_strongholds()["strongholds"][loc.base_type]["walls_range"]
        walls_override = (base_walls[0], max(0, base_walls[1] - 1))
    reposition_defender = bool(action.get("reposition_defender", True))
    pl: dict[str, Any] = {
        "engagement_label": "storm",
        "finish": "storm",
        "side": side,
        "here": here,
        "enemy_inside": enemy_inside,
        "lord_id": lord_id,
    }
    # Reactive (round-stepped) Storm Concede (S10, Attacker-only, Round
    # 2+). Opt-in so the synchronous default path is unchanged.
    if bool(action.get("interactive_concede")):
        if surprise_loc == here:
            state.meta.surprise_storm_pending_locale_id = None
        return _begin_interactive_storm(
            state, action, atk, dfd, pl,
            walls_range_override=walls_override,
            reposition_defender=reposition_defender)
    concede_after_round = action.get("concede_after_round")
    result = resolve_storm(
        state, atk, dfd, walls_range_override=walls_override,
        concede_after_round=concede_after_round,
        reposition_defender=reposition_defender)
    if surprise_loc == here:
        state.meta.surprise_storm_pending_locale_id = None
    return _finish_storm(state, action, atk=atk, dfd=dfd, result=result,
                         pl=pl)


def _h_cmd_sally(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.5.3 Sally. Besieged Lord attacks the besieger.

    Uses entire card. If Sally loses, sallying Lords Withdraw back
    inside; Siege markers reduce to 1.
    """
    from almoravid.battle import (
        BattleSide,
        battleside_for_lord,
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
    assert lord_id is not None
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(is_besieged(state, lord_id),
             "Sally requires Besieged Lord (4.5.3)", code="not_besieged")
    here = lord.cylinder.locale_id
    assert here is not None

    # Find besieging Lord(s) outside the Stronghold at this Locale
    other: Side = "muslim" if side == "christian" else "christian"
    besiegers = [
        lord_obj.id for lord_obj in state.lords.values()
        if lord_obj.side == other
        and lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == here
        and not lord_obj.in_stronghold
    ]
    _require(besiegers, f"No besiegers to Sally against at {here}",
             code="no_besiegers")
    atk = battleside_for_lord(state, lord_id, "attacker")
    atk.lord_ids = [lord_id]  # the sallying Lord
    # Sally exits the Stronghold for the duration of the Sally
    state.lords[lord_id].in_stronghold = False

    # Build defender side (besiegers)
    dfd_forces: dict[UnitType, int] = {}
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
    pl: dict[str, Any] = {
        "engagement_label": "sally",
        "finish": "sally",
        "side": side,
        "here": here,
        "lord_id": lord_id,
    }
    if bool(action.get("interactive_concede")):
        loc = state.locales[here]
        siege = (loc.siege_yellow if other == "christian"
                 else loc.siege_green)
        walls = (1, siege) if siege > 0 else None
        return _begin_interactive_battle(state, action, atk, dfd, pl,
                                         defender_walls_range=walls)
    result = resolve_sally(
        state, atk, dfd,
        attacker_concede_round=_concede_round_arg(
            action, "attacker_concede_round"),
        defender_concede_round=_concede_round_arg(
            action, "defender_concede_round"))
    return _finish_sally(state, action, atk=atk, dfd=dfd, result=result,
                         pl=pl)




# ---------------------------------------------------------------------------
# Phase 6b: rule 4.3.4 Approach / Avoid / Withdraw / Stand-and-Fight.
# ---------------------------------------------------------------------------


def _sweep_all_orphaned_markers(state: GameState) -> None:
    """Door B backstop (Advisory #2; RoP 4.3.5/4.3.6/4.4.1): "Whenever a
    Besieged or Bypassed Stronghold becomes free of Enemy Lords in the
    Locale, remove all Siege and Bypass markers there." Run after every
    action so NO departure path (March-out, Depart, Disband, combat
    Removal, M19 Sail, event removal, Winter/Curias Disband) can leave an
    orphaned marker. Per-side and idempotent: a marker is cleared only
    when the owning side has no Lord at that Locale, so it never touches a
    live Siege/Bypass (the besieger/bypasser is still present there)."""
    for lid, loc in state.locales.items():
        if (loc.siege_yellow or loc.siege_green
                or loc.bypass_yellow or loc.bypass_green):
            _remove_orphaned_siege_bypass(state, lid)


def _remove_orphaned_siege_bypass(state: GameState, locale_id: str) -> dict[str, Any]:
    """4.3.5/4.3.6 DEPART: when a Besieged or Bypassed Stronghold
    becomes free of the besieging side's (Enemy) Lords in the Locale,
    remove that side's Siege and Bypass markers there. Markers are
    color-coded, so a side's markers clear once that side has no Lord
    present at the Locale. Called after any departure (e.g. March)."""
    loc = state.locales.get(locale_id)
    out: dict[str, Any] = {"removed": []}
    if loc is None or loc.base_type == "region":
        return out
    for color, sd in (("yellow", "christian"), ("green", "muslim")):
        present = any(
            lord for lord in state.lords.values()
            if lord.side == sd and lord.cylinder.kind == "locale"
            and lord.cylinder.locale_id == locale_id)
        if present:
            continue
        sfield = "siege_yellow" if color == "yellow" else "siege_green"
        bfield = "bypass_yellow" if color == "yellow" else "bypass_green"
        if getattr(loc, sfield) or getattr(loc, bfield):
            out["removed"].append(
                {"side": sd, "siege": getattr(loc, sfield),
                 "bypass": getattr(loc, bfield)})
            setattr(loc, sfield, 0)
            setattr(loc, bfield, False)
    return out


def _check_approach_trigger(
    state: GameState, locale_id: str, active_side: Side,
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
        lord.id for lord in state.lords.values()
        if lord.side == other
        and lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id == locale_id
        and not lord.in_stronghold
        and not is_besieged(state, lord.id)
        and not is_bypassed(state, lord.id)
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


def _clear_approach_pending(state: GameState, original_active: Side) -> None:
    """Clear the PendingDecision and restore active_player to the
    marching side so their card continues."""
    state.pending = None
    state.meta.active_player = original_active


def _require_pending(state: GameState, kind: str, side: Side) -> PendingDecision:
    pd = state.pending
    _require(pd is not None and pd.kind == kind,
             f"no pending {kind} decision", code="no_pending")
    assert pd is not None
    _require(pd.waiting_on == side,
             f"pending decision waiting on {pd.waiting_on}, not {side}",
             code="not_responder")
    assert pd is not None
    return pd


def _approach_subset(payload: dict[str, Any],
                     action: dict[str, Any]) -> list[str]:
    """C2 (4.3.4): the Inactive side may partition its Lords across
    Avoid / Withdraw / Battle. An avoid/withdraw response acts on the
    `lord_ids` subset of the still-pending defenders (default: ALL of
    them, preserving the whole-group behavior)."""
    pending = list(payload["defender_lord_ids"])
    subset = action.get("lord_ids")
    if subset is None:
        return pending
    subset = list(subset)
    _require(all(lid in pending for lid in subset) and subset,
             "lord_ids must be a non-empty subset of the pending "
             "defenders (4.3.4)", code="bad_subset")
    return subset


def _resolve_or_repend_approach(state: GameState, payload: dict[str, Any],
                                active_side: Side, *,
                                some_withdrew: bool) -> bool:
    """After an Avoid/Withdraw subset acts, either re-pend the remaining
    defenders' response (still owing Avoid/Withdraw/Battle) or, when none
    remain, resolve the Approach: trigger Besiege-or-Bypass (4.3.5) if
    any Enemy Lords Withdrew inside, else restore control to the Active
    side. Returns True if a new pending decision was set."""
    from almoravid.state import PendingDecision
    remaining = payload["defender_lord_ids"]
    if remaining:
        # Keep waiting on the defender for the remaining Lords.
        state.pending = PendingDecision(
            kind="march_arrival_response",
            waiting_on=_other(active_side),
            payload=payload)
        state.meta.active_player = _other(active_side)
        return True
    # Fully resolved. If Enemy Lords Withdrew inside, force Besiege/Bypass.
    locale_id = payload["locale_id"]
    active_lord_id = payload.get("active_lord_id")
    if some_withdrew and _set_besiege_or_bypass_pending(
            state, locale_id, active_side, active_lord_id):
        return True
    _clear_approach_pending(state, active_side)
    return False


def _h_respond_avoid_battle(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    target = cast(str, target)
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
    for lord in state.lords.values():
        if (lord.side == active_side and lord.cylinder.kind == "locale"
                and lord.cylinder.locale_id == target
                and not is_besieged(state, lord.id)
                and not is_bypassed(state, lord.id)):
            raise IllegalAction(
                f"Cannot Avoid into {target} — Unbesieged/Unbypassed "
                f"{active_side} Lord {lord.id} present",
                code="destination_has_enemy",
            )
    # C5 (4.3.4): Avoid Battle must be Unladen, but a Laden Lord may
    # DISCARD Loot and excess Provender to become Unladen and thereby
    # Avoid. Avoiding Lords take NO Loot, and only Provender up to their
    # Transport (one per Cart/Mule) — and across a Pass no Cart may carry
    # Provender, so only Mules (one each) may. All discarded Loot and
    # Provender go to the Approaching Enemy Lords as Spoils (4.4.3),
    # divided among them.
    avoiding = _approach_subset(payload, action)   # C2 partition subset
    discarded = {"loot": 0, "prov": 0}
    # E7 / 4.3.4 + 1.5.2 SHARED TRANSPORT: avoiding Lords move together
    # and Share Transport, so Provender capacity is the GROUP total —
    # one per Cart/Mule on a Road, one per Mule only across a Pass (no
    # Cart carries Provender when Avoiding over a Pass). All Loot is
    # discarded (no Loot may be taken when Avoiding).
    avoiders = [lid for lid in avoiding if lid in state.lords]
    for lid in avoiders:
        lord = state.lords[lid]
        loot = lord.assets.get("loot", 0)
        if loot > 0:
            discarded["loot"] += loot
            lord.assets.pop("loot", None)
    group_cap = sum(
        (state.lords[lid].assets.get("mule", 0) if way_type == "pass"
         else state.lords[lid].assets.get("cart", 0)
         + state.lords[lid].assets.get("mule", 0))
        for lid in avoiders)
    group_prov = sum(state.lords[lid].assets.get("prov", 0)
                     for lid in avoiders)
    excess = max(0, group_prov - group_cap)
    discarded["prov"] = excess
    to_drop = excess
    for lid in avoiders:
        if to_drop <= 0:
            break
        lord = state.lords[lid]
        have = lord.assets.get("prov", 0)
        drop = min(have, to_drop)
        if drop > 0:
            lord.assets["prov"] = have - drop
            if lord.assets["prov"] == 0:
                lord.assets.pop("prov", None)
            to_drop -= drop
    # Distribute discarded Assets to the Approaching attackers as Spoils.
    spoils = {k: v for k, v in discarded.items() if v > 0}
    attackers = [
        lord.id for lord in state.lords.values()
        if lord.side == active_side and lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id == locale_id and not lord.in_stronghold]
    spoils_dist = {}
    if spoils and attackers:
        from almoravid.battle import distribute_spoils_round_robin
        spoils_dist = distribute_spoils_round_robin(
            state, attackers, cast("dict[AssetType, int]", spoils))
    # Move the avoiding subset. Avoid Battle DOES mark Moved/Fought
    # (4.3.4 "Mark Avoiding Lords as Moved/Fought"; 4.8.1 lists Avoid
    # Battle among the Moved/Fought triggers). Only Withdrawal alone is
    # exempt (4.3.4 WITHDRAW).
    for lid in avoiding:
        if lid in state.lords:
            lord = state.lords[lid]
            lord.cylinder = Cylinder(kind="locale", locale_id=target)
            lord.in_stronghold = False
            lord.moved_fought = True
    # 4.3.4: "Mark Lords Avoiding Battle to an Unbesieged Enemy
    # Stronghold as Bypassing it (4.3.5)." If the destination holds an
    # Enemy Stronghold to the avoiding (inactive) side that is not
    # already Besieged/Bypassed, place a Bypass marker of that side's
    # color (per-Locale, like _h_respond_bypass). Lords arriving at an
    # already-Bypassed/Besieged Stronghold simply join it.
    from almoravid.effective import is_friendly_locale as _is_friendly
    dest = state.locales.get(target)
    if (avoiding and dest is not None and dest.base_type != "region"
            and not _is_friendly(state, target, side)):
        if side == "christian" and not dest.bypass_yellow and dest.siege_yellow == 0:
            dest.bypass_yellow = True
        elif side == "muslim" and not dest.bypass_green and dest.siege_green == 0:
            dest.bypass_green = True
    # C2: remove the avoiding subset from the still-pending defenders.
    payload["defender_lord_ids"] = [
        d for d in payload["defender_lord_ids"] if d not in avoiding]
    _record(state, action,
            f"{side} avoids Battle: {avoiding} move {locale_id} -> "
            f"{target} via {way_type}"
            + (f"; discarded {spoils} to {active_side} as Spoils"
               if spoils else ""))
    _resolve_or_repend_approach(state, payload, active_side,
                                some_withdrew=False)
    return {"avoided_to": target, "lord_ids": avoiding,
            "remaining_defenders": list(payload["defender_lord_ids"]),
            "discarded_as_spoils": spoils, "spoils_distribution": spoils_dist}


def _h_respond_withdraw(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    withdrawing = _approach_subset(payload, action)   # C2 partition subset
    # Count Lords already inside the Stronghold + the withdrawing group.
    already_inside = sum(
        1 for lord in state.lords.values()
        if lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id == locale_id
        and lord.in_stronghold
    )
    incoming = len(withdrawing)
    # C9 (4.1.3): a Lieutenant and his Lower Lord always move together,
    # so both must Withdraw together — and since they are two Lords they
    # can never Withdraw into a Castle (Capacity 1; enforced by the
    # capacity check below). Reject a Withdraw that would separate a
    # Lt/Lower pair (one withdraws, the partner stays outside).
    wset = set(withdrawing)
    for lid in withdrawing:
        lord = state.lords.get(lid)
        if lord is None:
            continue
        partner = None
        if lord.lieutenant_of is not None:
            partner = lord.lieutenant_of
        elif lord.is_lieutenant:
            partner = next((x.id for x in state.lords.values()
                            if x.lieutenant_of == lid), None)
        if partner is not None and partner not in wset:
            _require(False,
                     f"{lid} and partner {partner} are a Lieutenant/Lower "
                     f"pair and must Withdraw together (4.1.3)",
                     code="lt_pair_split")
    _require(already_inside + incoming <= capacity,
             f"Siege Capacity {capacity} at {locale_id} would be "
             f"exceeded ({already_inside} inside + {incoming} withdrawing)",
             code="exceeds_capacity")
    for lid in withdrawing:
        if lid in state.lords:
            state.lords[lid].in_stronghold = True
    # C2: remove the withdrawing subset from the still-pending defenders.
    payload["defender_lord_ids"] = [
        d for d in payload["defender_lord_ids"] if d not in withdrawing]
    _record(state, action,
            f"{side} withdraws inside {locale_id} Stronghold "
            f"({withdrawing})")
    # C1 (4.3.5): once the Approach is fully resolved (no more defenders
    # owe a response) and Enemy Lords Withdrew inside, the Active side
    # must Besiege or Bypass. _resolve_or_repend_approach handles both
    # the re-pend (defenders remain) and the Besiege/Bypass trigger.
    repended = _resolve_or_repend_approach(
        state, payload, active_side, some_withdrew=True)
    return {"withdrew_to_stronghold": locale_id,
            "lord_ids": withdrawing,
            "remaining_defenders": list(payload["defender_lord_ids"]),
            "pending_followup": repended}


def _set_besiege_or_bypass_pending(state: GameState, locale_id: str,
                                   active_side: Side,
                                   active_lord_id: str | None) -> bool:
    """4.3.5: if `active_side` has Lord(s) outside the Enemy Stronghold
    at `locale_id`, that Stronghold is not already Besieged/Bypassed by
    that side, and Enemy Lords are inside it, set a `besiege_or_bypass`
    pending decision (waiting on the Active side) and return True."""
    from almoravid.state import PendingDecision
    loc = state.locales.get(locale_id)
    if loc is None or loc.base_type == "region":
        return False
    other = _other(active_side)
    # Enemy Lords inside the Stronghold here?
    enemy_inside = any(
        lord.side == other and lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id == locale_id and lord.in_stronghold
        for lord in state.lords.values())
    if not enemy_inside:
        return False
    # Active-side Lord(s) outside the Stronghold here?
    ours_outside = [
        lord.id for lord in state.lords.values()
        if lord.side == active_side and lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id == locale_id and not lord.in_stronghold]
    if not ours_outside:
        return False
    # Already Besieged or Bypassed by this side?
    if active_side == "christian":
        already = loc.siege_yellow > 0 or loc.bypass_yellow
    else:
        already = loc.siege_green > 0 or loc.bypass_green
    if already:
        return False
    state.pending = PendingDecision(
        kind="besiege_or_bypass",
        waiting_on=active_side,
        payload={"locale_id": locale_id, "active_side": active_side,
                 "active_lord_id": active_lord_id,
                 "lord_ids": ours_outside})
    state.meta.active_player = active_side
    return True


def _h_respond_besiege(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.3.5 Besiege: place one Siege marker of the Active side's color
    on the Enemy Stronghold, skip any remaining actions on this card,
    and proceed to Feed/Pay/Disband (the card ends)."""
    side = _require_side(action)
    pd = _require_pending(state, "besiege_or_bypass", side)
    locale_id = pd.payload["locale_id"]
    loc = state.locales[locale_id]
    if side == "christian":
        loc.siege_yellow += 1
    else:
        loc.siege_green += 1
    state.pending = None
    state.meta.active_player = side
    # Skip remaining actions -> Feed/Pay/Disband (4.3.5).
    state.meta.actions_remaining = 0
    _record(state, action,
            f"{side} Besieges {locale_id} (4.3.5): +1 Siege marker, "
            f"card ends -> Feed/Pay/Disband")
    return {"besieged": locale_id,
            "siege_marker": "siege_yellow" if side == "christian"
            else "siege_green"}


def _h_respond_bypass(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.3.5 Bypass: place a Bypass marker of the Active side's color on
    the Lord(s) outside and continue any remaining actions on the card
    without leaving the Locale."""
    side = _require_side(action)
    pd = _require_pending(state, "besiege_or_bypass", side)
    locale_id = pd.payload["locale_id"]
    loc = state.locales[locale_id]
    if side == "christian":
        loc.bypass_yellow = True
    else:
        loc.bypass_green = True
    state.pending = None
    state.meta.active_player = side
    # Card continues with whatever actions remain (4.3.5 / 4.3.6).
    _record(state, action,
            f"{side} Bypasses {locale_id} (4.3.5): Bypass marker placed, "
            f"card continues ({state.meta.actions_remaining} actions left)")
    return {"bypassed": locale_id,
            "bypass_marker": "bypass_yellow" if side == "christian"
            else "bypass_green",
            "actions_remaining": state.meta.actions_remaining}


def _finish_relief_sally(
    state: GameState,
    action: dict[str, Any],
    *,
    result: Any,
    atk: Any,
    dfd: Any,
    pl: dict[str, Any],
) -> dict[str, Any]:
    """Relief-Sally aftermath + the shared stand-battle tail (besiege/bypass
    or restore control, end card). Used by the synchronous and interactive
    relief-sally paths."""
    from almoravid.battle import apply_relief_sally_aftermath
    locale_id: str = pl["locale_id"]
    active_side: Side = pl["active_side"]
    side: Side = pl["side"]
    retreat_summary = apply_relief_sally_aftermath(
        state, result, locale_id=locale_id, besieger_side=pl["other"],
        approach_from_locale=pl.get("from_locale_id"),
        approach_way_type=pl.get("via_way_type"))
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    if not _set_besiege_or_bypass_pending(
            state, locale_id, active_side, pl.get("active_lord_id")):
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


def _begin_interactive_relief(
    state: GameState,
    action: dict[str, Any],
    marcher_ids: list[str],
    sallyer_ids: list[str],
    defender_lord_ids: list[str],
    pl: dict[str, Any],
) -> dict[str, Any]:
    """Start a reactive Relief Sally: build the lane state and pause on a
    relief_concede decision before Round 1 (either side may Concede)."""
    from almoravid.battle import _relief_setup, _relief_to_snapshot
    rs = _relief_setup(state, marcher_ids, sallyer_ids, defender_lord_ids,
                       besieger_side=pl["other"], locale_id=pl["locale_id"],
                       max_rounds=6)
    pl = dict(pl)
    pl["rs"] = _relief_to_snapshot(rs)
    pl["round_idx"] = 1
    pl["max_rounds"] = 6
    state.pending = PendingDecision(
        kind="relief_concede", waiting_on=pl["active_side"], payload=pl)
    state.meta.active_player = pl["active_side"]
    return {"relief_sally": "awaiting_concede", "round": 1}


def _h_relief_concede(state: GameState,
                      action: dict[str, Any]) -> dict[str, Any]:
    """Resolve one Relief-Sally Round after its start-of-Round Concede
    declaration (4.4.2; either side, from Round 1). Runs the Round, then
    finishes (Concede / Rout / Round cap) or re-pends for the next Round."""
    from almoravid.battle import (
        _relief_declare_concede,
        _relief_finalize,
        _relief_from_snapshot,
        _relief_over,
        _relief_run_round,
        _relief_to_snapshot,
    )
    side = _require_side(action)
    pd = _require_pending(state, "relief_concede", side)
    pl = pd.payload
    rs = _relief_from_snapshot(state, pl["rs"])
    rnd_i: int = pl["round_idx"]
    atk_concedes = bool(action.get("attacker_concede"))
    dfd_concedes = bool(action.get("defender_concede"))
    _relief_declare_concede(rs, atk_concedes=atk_concedes,
                            dfd_concedes=dfd_concedes)
    rs.result.rounds.append(_relief_run_round(state, rs, rnd_i))
    ended = (atk_concedes or dfd_concedes
             or _relief_over(state, rs)
             or rnd_i >= pl["max_rounds"])
    if not ended:
        pl = dict(pl)
        pl["rs"] = _relief_to_snapshot(rs)
        pl["round_idx"] = rnd_i + 1
        state.pending = PendingDecision(
            kind="relief_concede", waiting_on=side, payload=pl)
        return {"relief_sally": "in_progress", "round_resolved": rnd_i,
                "rounds_done": len(rs.result.rounds)}
    if atk_concedes or dfd_concedes:
        rs.result.notes.append(
            f"Round {rnd_i} ended with Concede; Relief Sally ends")
    _relief_finalize(state, rs)
    state.pending = None
    return _finish_relief_sally(state, action, result=rs.result,
                                atk=rs.result.attacker,
                                dfd=rs.result.defender, pl=pl)


def _h_respond_stand_battle(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.3.4 Stand & Fight. Auto-resolve Battle with all eligible Lords
    on both sides at the Approach Locale. Battle ends the active side's
    card (rule 4.4.5)."""
    from almoravid.battle import (
        _front_lord_count,
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
        lord.id for lord in state.lords.values()
        if lord.side == active_side
        and lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id == locale_id
        and not lord.in_stronghold
    ]
    # Relief Sally (4.4.1, Phase 7f): if the Approaching side also has
    # its own Besieged Lords inside a Stronghold at this Locale, they
    # Sally out to join the Approach as relief attackers.
    from almoravid.effective import is_besieged as _isb
    relief_sally_ids = [
        lord.id for lord in state.lords.values()
        if lord.side == active_side
        and lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id == locale_id
        and lord.in_stronghold and _isb(state, lord.id)
    ]
    # B6 (4.4.1): the relieving Marchers and the Sallying (Besieged)
    # Lords are SEPARATE groups in the Array, not one merged Attacker.
    marcher_ids = list(attacker_lord_ids)
    for rid in relief_sally_ids:
        if rid not in marcher_ids:
            state.lords[rid].in_stronghold = False  # Sallied out
    sallyer_ids = [rid for rid in relief_sally_ids if rid not in marcher_ids]
    defender_lord_ids = list(payload["defender_lord_ids"])
    _require(marcher_ids or sallyer_ids,
             "no attacker Lords at Battle locale", code="no_attacker")
    _require(defender_lord_ids, "no defender Lords at Battle locale",
             code="no_defender")

    from almoravid.battle import (
        apply_battle_losses,
        apply_retreat_aftermath,
    )

    if sallyer_ids:
        # ---- Relief Sally dual-lane resolution (4.4.1 / 4.5.3). ----
        relief_pl: dict[str, Any] = {
            "side": side,
            "locale_id": locale_id,
            "active_side": active_side,
            "other": other,
            "from_locale_id": payload.get("from_locale_id"),
            "via_way_type": payload.get("via_way_type"),
            "active_lord_id": payload.get("active_lord_id"),
        }
        # Reactive (round-stepped) Concede for the Relief Sally (opt-in).
        if bool(action.get("interactive_concede")):
            return _begin_interactive_relief(
                state, action, marcher_ids, sallyer_ids,
                defender_lord_ids, relief_pl)
        from almoravid.battle import (
            apply_relief_sally_aftermath,
            resolve_relief_sally,
        )
        result, lanes = resolve_relief_sally(
            state, marcher_ids, sallyer_ids, defender_lord_ids,
            besieger_side=other, locale_id=locale_id,
            attacker_concede_round=_concede_round_arg(
                action, "attacker_concede_round"),
            defender_concede_round=_concede_round_arg(
                action, "defender_concede_round"))
        marchers, sallyers, def_front, def_rear, shared = lanes
        # resolve_relief_sally has already committed each Lord's Forces +
        # Routed units exactly (per-Lord), so no proportional commit here.
        retreat_summary = apply_relief_sally_aftermath(
            state, result,
            locale_id=locale_id, besieger_side=other,
            approach_from_locale=payload.get("from_locale_id"),
            approach_way_type=payload.get("via_way_type"))
        atk = result.attacker
        dfd = result.defender
    else:
        # ---- Standard Approach Battle (no Relief Sally). ----
        atk = battleside_for_lords(state, marcher_ids, active_side,
                                   "attacker",
                                   active_lord_id=state.meta.active_lord_id)
        # B4 (4.4.1): Defender Front count capped at the Attacker's.
        dfd = battleside_for_lords(state, defender_lord_ids, other,
                                   "defender",
                                   front_limit=_front_lord_count(atk))
        result = resolve_battle(
            state, atk, dfd,
            attacker_concede_round=_concede_round_arg(
                action, "attacker_concede_round"),
            defender_concede_round=_concede_round_arg(
                action, "defender_concede_round"))
        commit_forces_after_battle(state, atk)
        commit_forces_after_battle(state, dfd)
        # Bug P fix: Retreat aftermath FIRST so it can consult Hold events
        # (C7 Baggage Parapet opt-out) in this_levy_events before
        # apply_aftermath clears that bucket.
        retreat_summary = apply_retreat_aftermath(
            state, result,
            approach_from_locale=payload.get("from_locale_id"),
            approach_way_type=payload.get("via_way_type"))
        apply_battle_losses(state, result, retreat_summary)
        apply_aftermath(state, result)

    # End the active side's card (rule 4.4.5).
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0
    # C1b (4.3.5): after the Battle, if the losing Enemy Withdrew inside
    # and the Active side has Lord(s) outside, force Besiege-or-Bypass;
    # otherwise restore control to the Active side.
    if not _set_besiege_or_bypass_pending(
            state, locale_id, active_side, payload.get("active_lord_id")):
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


def _h_play_pope_gregory(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    lord_id = cast(str, lord_id)
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
        from almoravid.actions import _free_seats_for
        from almoravid.state import Cylinder
        from almoravid.static_data import load_lords as _ll
        rec = _ll()["lords"].get(lord_id, {})
        # 3.4.1: auto-Muster places only at a free Seat (neither Enemy nor
        # with an Enemy Lord present); "must otherwise still Muster by the
        # usual rules" (3.4.1 ARTS OF WAR). [Door C, Advisory #2]
        free = _free_seats_for(state, lord_id)
        _require(free, f"{lord_id} has no free Seat to Muster (3.4.1)",
                 code="no_free_seat")
        lord.cylinder = Cylinder(kind="locale", locale_id=free[0])
        lord.forces = dict(rec.get("forces", {}))
        lord.assets = dict(rec.get("assets", {}))
        lord.just_arrived_this_levy = True
        result["mustered_at"] = free[0]
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


def _h_play_al_qadir(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Play held M11 "Al-Qadir balks at payment" (Hold, Muslim) to add
    Jihad per 1.4.4: base 1, or 3 if the Yusuf/Sir bonus is active
    (_m11_jihad_bonus_active). Optional payload jihad_targets choose the
    eligible Locale(s); base_only=True forces the +1 option even when the
    +3 bonus is available (the card's "OR" — player's choice)."""
    from almoravid.events import _add_jihad, _m11_jihad_bonus_active
    side = _require_side(action)
    _require(side == "muslim", "M11 is a Muslim event", code="wrong_side")
    _require("M11" in state.decks.this_levy_events.get("muslim", []),
             "M11 not held", code="card_not_held")
    # The card's "Lords. Yusuf or Sir" line restricts the EVENT: M11 can
    # only be played with Yusuf or Sir on the map. (Resolved ambiguity /
    # Q-candidate: the conservative reading — it prevents fabricating
    # Jihad VP when neither Almoravid leader is in play, e.g. Scenario A.)
    _require(any(state.lords.get(x) is not None
                 and state.lords[x].cylinder.kind == "locale"
                 for x in ("yusuf", "sir")),
             "M11 requires Yusuf or Sir on the map to play (Lords line)",
             code="no_eligible_lord")
    bonus = _m11_jihad_bonus_active(state)
    add = 3 if (bonus and not action.get("base_only")) else 1
    placement = _add_jihad(state, add, action.get("payload") or
                           {"jihad_targets": action.get("jihad_targets")})
    if placement is None:
        return {"no_op": True, "reason": "no eligible Jihad locale"}
    state.decks.this_levy_events["muslim"].remove("M11")
    state.decks.discard.append("M11")
    _record(state, action,
            f"Muslim plays M11 Al-Qadir: +{add} Jihad "
            f"(bonus {'active' if bonus else 'inactive'}) -> {placement}")
    return {"card_id": "M11", "side": side, "jihad_added": add,
            "bonus": bonus, "placement": placement}


def _h_play_cluniacs(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    lord_id = cast(str, lord_id)
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
        from almoravid.actions import _free_seats_for
        from almoravid.state import Cylinder
        from almoravid.static_data import load_lords as _ll
        rec = _ll()["lords"].get(lord_id, {})
        # 3.4.1: auto-Muster places only at a free Seat (neither Enemy nor
        # with an Enemy Lord present); "must otherwise still Muster by the
        # usual rules" (3.4.1 ARTS OF WAR). [Door C, Advisory #2]
        free = _free_seats_for(state, lord_id)
        _require(free, f"{lord_id} has no free Seat to Muster (3.4.1)",
                 code="no_free_seat")
        lord.cylinder = Cylinder(kind="locale", locale_id=free[0])
        lord.forces = dict(rec.get("forces", {}))
        lord.assets = dict(rec.get("assets", {}))
        lord.just_arrived_this_levy = True
        result["mustered_at"] = free[0]
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


def _h_play_de_vivar_reconcile(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    assert sayyid is not None
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


def _h_cmd_march_port_to_port(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """M19 (Hold) African Fleet: Lord uses entire Command card to
    March between two Ports where no Christian Lord at destination.

    Args:
      side: acting (Muslim)
      target_locale_id: destination Port
    """
    from almoravid.effective import is_besieged
    from almoravid.state import Cylinder
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(side == "muslim", "M19 African Fleet is a Muslim event",
             code="wrong_side")
    _require("M19" in state.decks.this_levy_events.get("muslim", []),
             "M19 not held", code="card_not_held")
    lord_id = state.meta.active_lord_id
    assert lord_id is not None
    _require(lord_id is not None, "no active Lord", code="no_active_lord")
    lord = state.lords[lord_id]
    _require(lord.cylinder.kind == "locale", f"{lord_id} not at Locale",
             code="not_on_map")
    _require(not is_besieged(state, lord_id),
             "Besieged Lord may only Sally/Forage/Pass",
             code="besieged")
    from_loc = lord.cylinder.locale_id
    assert from_loc is not None
    _require(state.locales[from_loc].has_port,
             f"{from_loc} is not a Port", code="not_port")
    target = action.get("target_locale_id")
    target = cast(str, target)
    _require(target in state.locales, f"unknown locale {target!r}",
             code="unknown_locale")
    _require(state.locales[target].has_port,
             f"{target} is not a Port", code="not_port")
    # No Christian Lord at target.
    for lord_obj in state.lords.values():
        if (lord_obj.side == "christian" and lord_obj.cylinder.kind == "locale"
                and lord_obj.cylinder.locale_id == target):
            raise IllegalAction(
                f"Christian Lord {lord_obj.id} at {target} — blocked",
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


def _mustered_lords_on_map(state: GameState, side: Side) -> int:
    """Count a side's Lords with a cylinder on a map Locale."""
    return sum(
        1 for lord in state.lords.values()
        if lord.side == side and lord.cylinder.kind == "locale"
    )


def check_campaign_victory(state: GameState) -> str | None:
    """Rule 5.2: during the Campaign, if a side has no Mustered Lords
    on the map, the OTHER side wins immediately regardless of VP.
    Returns the winning side, or None."""
    if _mustered_lords_on_map(state, "christian") == 0:
        return "muslim"
    if _mustered_lords_on_map(state, "muslim") == 0:
        return "christian"
    return None


def compute_final_vp(state: GameState) -> tuple[float, float]:
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
    for _lid, loc in state.locales.items():
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
    # 5.1: +1 Christian VP per Cathedral Seat marker on the map.
    christian += float(len(state.cathedral_seat_locales))
    # Taifas-box VP (rule 1.4.2) counts for the Muslims.
    muslim += state.taifas_box_vp
    return christian, muslim


def compute_victory(state: GameState) -> dict[str, Any]:
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


def _is_taifa_locale(state: GameState, locale_id: str) -> bool:
    """A Locale in Muslim Taifa territory (not a Christian Kingdom)."""
    loc = state.locales.get(locale_id)
    return loc is not None and loc.territory in state.taifas


def _counts_as_marshal_for_march(state: GameState, lord_id: str, side: Side,
                                 from_loc: str, target: str) -> bool:
    """4.3.1 Group March leader test. True for the side's actual Marshal,
    OR a Lord with C8 Hueste for a March to/from any Taifa Locale (not
    Kingdom->Kingdom), provided he is not himself a Lower Lord (Arts of
    War ref C8: 'A Lord with Hueste counts as a Marshal when he undertakes
    March actions to or from any Locales in any Taifas ... If he is a Lower
    Lord, he ... cannot make use of Hueste')."""
    if _is_marshal(lord_id, side):
        return True
    from almoravid.capabilities import lord_has_capability
    lord = state.lords.get(lord_id)
    if (lord is not None and lord.lieutenant_of is None
            and lord_has_capability(state, lord_id, "C8")
            and (_is_taifa_locale(state, from_loc)
                 or _is_taifa_locale(state, target))):
        return True
    return False


def _h_designate_lieutenant(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    lord_id = cast(str, lord_id)
    commander_id = action.get("commander_id")
    commander_id = cast(str, commander_id)
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
    existing = [lord_obj.id for lord_obj in state.lords.values()
                if lord_obj.lieutenant_of == commander_id]
    _require(not existing,
             f"{commander_id} already has Lower Lord {existing}",
             code="lieutenant_full")
    lord.is_lieutenant = True
    lord.lieutenant_of = commander_id
    _record(state, action,
            f"{side} designates {lord_id} as Lower Lord of {commander_id}")
    return {"lower_lord": lord_id, "lieutenant": commander_id}


def _h_toggle_lieutenant(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    assert lord_id is not None
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
    commander_id = cast(str, commander_id)
    _require(commander_id in state.lords, "commander_id required",
             code="bad_arg")
    cmd = state.lords[commander_id]
    _require(cmd.side == side and not _is_marshal(commander_id, side),
             "invalid commander", code="bad_arg")
    _require(lord.cylinder.kind == "locale"
             and cmd.cylinder.kind == "locale"
             and lord.cylinder.locale_id == cmd.cylinder.locale_id,
             "must be at the same Locale", code="not_same_locale")
    existing = [lord_obj.id for lord_obj in state.lords.values()
                if lord_obj.lieutenant_of == commander_id]
    _require(not existing, f"{commander_id} already has a Lower Lord",
             code="lieutenant_full")
    lord.is_lieutenant = True
    lord.lieutenant_of = commander_id
    state.meta.actions_remaining -= 1
    _record(state, action,
            f"{lord_id} stacks as Lower Lord of {commander_id} (Alferez)")
    return {"lower_lord": lord_id, "lieutenant": commander_id,
            "actions_remaining": state.meta.actions_remaining}


def _unstack_all_lieutenants(state: GameState) -> None:
    """End-of-Campaign cleanup (4.1.3 / SoP 'Unstack Lieutenants and
    Lower Lords')."""
    for lord in state.lords.values():
        lord.is_lieutenant = False
        lord.lieutenant_of = None



# ---------------------------------------------------------------------------
# Phase 7g: Wastage (4.9.4), Encamp (4.3.6), Dinars deposit (4.1.4).
# ---------------------------------------------------------------------------


def _apply_wastage(state: GameState) -> list[dict[str, Any]]:
    """Rule 4.9.4: each Mustered Lord (on the map) with MORE THAN ONE
    of any Asset type, or more than one This-Lord Capability card,
    discards one excess. Greedy/deterministic: drop one unit of the
    largest Asset stack > 1; if none, drop one This-Lord Capability."""
    from almoravid.capabilities import capabilities_for_lord
    out: list[dict[str, Any]] = []
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
    return out


def _h_cmd_encamp(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.3.6 Encamp: a Bypassing Lord uses 1 March action (ignore
    Laden) to replace all his Bypass markers at the Locale with 1
    Siege marker; this ends his actions on the current card."""
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    lord_id = state.meta.active_lord_id
    assert lord_id is not None
    _require(lord_id is not None, "no active Lord", code="no_active_lord")
    lord = state.lords[lord_id]
    _require(lord.cylinder.kind == "locale", f"{lord_id} not at a Locale",
             code="not_on_map")
    _require(state.meta.actions_remaining >= 1,
             "Encamp costs 1 March action", code="not_enough_actions")
    here = lord.cylinder.locale_id
    assert here is not None
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


def _h_cmd_sortie(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.3.6 SORTIE: a Lord (or a Marshal/Lieutenant-led group, 4.3.1)
    inside a Bypassed FRIENDLY Stronghold uses one March action
    (regardless of Laden status, 4.3.2) to Approach (4.3.4) the
    Bypassing Enemy in the same Locale instead of moving adjacent.

    The Sortieing Lords come out of the Stronghold and become the
    Active Attacker; the Bypassing Enemy may then Avoid / Withdraw /
    Stand (handled by the standard march_arrival_response machinery).
    This is the one case where an Approach targets a *Bypassed* Enemy
    (4.3.4 normally skips Besieged/Bypassed Lords), so the pending is
    built directly here. If they lose the Battle they Withdraw or
    Retreat normally (4.3.4/4.4.3 aftermath). Sortieing Lords are
    marked Moved (4.3.6 "mark Marching Lords as Moved")."""
    from almoravid.effective import is_friendly_locale
    from almoravid.state import PendingDecision
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    lord_id = state.meta.active_lord_id
    assert lord_id is not None
    _require(lord_id is not None, "no active Lord", code="no_active_lord")
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(lord.cylinder.kind == "locale", f"{lord_id} not at a Locale",
             code="not_on_map")
    here = lord.cylinder.locale_id
    assert here is not None
    loc = state.locales[here]
    _require(loc.base_type != "region",
             f"Sortie requires a Stronghold; {here} is a Region",
             code="region_no_stronghold")
    _require(lord.in_stronghold,
             f"Sortie requires {lord_id} inside the Stronghold (4.3.6)",
             code="not_in_stronghold")
    _require(is_friendly_locale(state, here, side),
             "Sortie only from a Friendly Stronghold (4.3.6)",
             code="not_friendly")
    other = _other(side)
    enemy_bypass = loc.bypass_green if side == "christian" else loc.bypass_yellow
    _require(enemy_bypass,
             f"{here} is not Bypassed by the Enemy (4.3.6)",
             code="not_bypassed")
    bypassing_enemy = [
        lord_obj.id for lord_obj in state.lords.values()
        if lord_obj.side == other and lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == here and not lord_obj.in_stronghold]
    _require(bypassing_enemy,
             "no Bypassing Enemy Lord to Sortie against (4.3.6)",
             code="no_enemy")
    _require(state.meta.actions_remaining >= 1,
             "Sortie costs 1 March action (4.3.6)", code="not_enough_actions")

    # Group Sortie: only a Marshal or a Lieutenant may take a group
    # (4.3.1). Members must be same-side, inside this Stronghold.
    sortie_ids = [lord_id]
    group_req = list(action.get("group_lord_ids", []) or [])
    if group_req:
        _require(_is_marshal(lord_id, side) or lord.is_lieutenant,
                 "only a Marshal or Lieutenant may Sortie a group (4.3.1)",
                 code="not_group_leader")
        for gid in group_req:
            _require(gid in state.lords and gid != lord_id,
                     f"bad group member {gid!r}", code="bad_group")
            g = state.lords[gid]
            _require(g.side == side and g.cylinder.kind == "locale"
                     and g.cylinder.locale_id == here and g.in_stronghold,
                     f"{gid} is not inside {here} with the leader (4.3.6)",
                     code="bad_group")
            sortie_ids.append(gid)

    # Come out of the Stronghold and mark Moved (4.3.6).
    for sid in sortie_ids:
        state.lords[sid].in_stronghold = False
        state.lords[sid].moved_fought = True
    state.meta.actions_remaining -= 1

    # Approach the Bypassing Enemy in-place (no incoming Way, so Avoid
    # is unrestricted by the approach Way; from_locale_id = None).
    payload = {
        "locale_id": here,
        "from_locale_id": None,
        "via_way_type": None,
        "active_lord_id": lord_id,
        "active_side": side,
        "defender_lord_ids": bypassing_enemy,
        "sortie": True,
    }
    state.pending = PendingDecision(
        kind="march_arrival_response", waiting_on=other, payload=payload)
    state.meta.active_player = other
    _record(state, action,
            f"{side} {lord_id} Sorties from {here} (4.3.6) vs Bypassing "
            f"Enemy {bypassing_enemy}; awaiting their Approach response")
    return {"sortie": here, "sortie_lords": sortie_ids,
            "defenders": bypassing_enemy,
            "actions_remaining": state.meta.actions_remaining}


def _h_dinars_deposit(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.1.4 Dinars: an Unbesieged Taifa Lord (not Yusuf/Sir/Rodrigo)
    deposits any Coin from his mat into the Taifas box (Plan step)."""
    from almoravid.effective import is_besieged
    side = _require_side(action)
    _require(side == "muslim", "Dinars is a Muslim Plan-step option",
             code="wrong_side")
    lord_id = action.get("lord_id")
    lord_id = cast(str, lord_id)
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


def _apply_absorption_policy(state: GameState, side: Side, action: dict[str, Any]) -> None:
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


def _h_set_absorption_policy(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
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
    pol = cast(str, pol)
    state.meta.absorption_policy[side] = pol
    _record(state, action, f"{side} sets absorption policy = {pol}")
    return {"side": side, "absorption_policy": pol}


def _h_place_cathedral_seat(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """C16 Cathedrals (Arts of War ref): Alfonso at a Conquered City may
    place a Cathedral Seat marker if none is there yet. The marker acts
    as a Christian Seat AND is worth +1 Christian VP (5.1); placing it
    triggers +1 Jihad for the Muslims (1.4.4). Up to two such markers
    exist — when both are on the map the Christians may relocate one
    (relocate_from). Scenario F: may not place until Yusuf or Sir Muster.

    Modeled as a free (0-action) placement during Alfonso's Activation;
    optional (the Christian chooses). The +1 Jihad rider is placed
    deterministically via _add_jihad (the Muslim 'where' choice is a
    minor placement detail; VP totals are unaffected by which eligible
    Stronghold receives it)."""
    side = _require_side(action)
    _require(side == "christian", "Cathedrals is a Christian capability",
             code="wrong_side")
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id == "alfonso",
             "only Alfonso may place a Cathedral Seat (C16)",
             code="not_alfonso")
    alfonso = state.lords["alfonso"]
    _require("C16" in alfonso.capabilities,
             "Alfonso does not have the Cathedrals (C16) capability",
             code="no_cathedrals")
    _require(alfonso.cylinder.kind == "locale", "Alfonso not on the map",
             code="not_on_map")
    # Scenario F gate: no Cathedral Seats until Yusuf or Sir Muster.
    if state.meta.scenario_letter == "F":
        gate_ok = any(
            lid in state.lords and state.lords[lid].cylinder.kind == "locale"
            for lid in ("yusuf", "sir"))
        _require(gate_ok,
                 "Scenario F: Cathedrals may not place Seats until Yusuf "
                 "or Sir Muster", code="cathedrals_gated")
    here = alfonso.cylinder.locale_id
    assert here is not None
    loc = state.locales[here]
    _require(loc.base_type == "city",
             f"{here} is not a City (Cathedral Seat requires a Conquered "
             f"City)", code="not_city")
    _require(loc.conquered_markers > 0 and loc.territory in state.taifas,
             f"{here} is not a Christian-Conquered City",
             code="not_conquered_city")
    _require(here not in state.cathedral_seat_locales,
             f"{here} already has a Cathedral Seat", code="already_seat")
    # Two-marker cap; relocate one if both already placed.
    relocate_from = action.get("relocate_from")
    relocate_from = cast(str, relocate_from)
    if len(state.cathedral_seat_locales) >= 2:
        _require(relocate_from in state.cathedral_seat_locales,
                 "both Cathedral Seats are placed; specify relocate_from "
                 "(a current Cathedral Seat locale) to move one",
                 code="cathedral_cap")
        state.cathedral_seat_locales.remove(relocate_from)
        rloc = state.locales.get(relocate_from)
        if rloc is not None and "alfonso" in rloc.seat_marker_lord_ids:
            rloc.seat_marker_lord_ids.remove("alfonso")
    # Place: Cathedral Seat acts as Alfonso's (Christian) Seat too.
    state.cathedral_seat_locales.append(here)
    if "alfonso" not in loc.seat_marker_lord_ids:
        loc.seat_marker_lord_ids.append("alfonso")
    # Jihad rider: Muslims add +1 Jihad (1.4.4).
    from almoravid.events import _add_jihad
    jihad = _add_jihad(state, 1, {})
    _record(state, action,
            f"christian places Cathedral Seat at {here} (+1 VP, C16)"
            + (f"; relocated from {relocate_from}" if relocate_from else "")
            + f"; Muslim +1 Jihad rider: {jihad}")
    return {"cathedral_seat": here, "relocated_from": relocate_from,
            "jihad_rider": jihad,
            "cathedral_seats": list(state.cathedral_seat_locales)}


def _set_neutrality_pending(state: GameState, deferred: list[Any],
                            resume_active: Side) -> bool:
    """T4 (1.4.3 RECOGNITION OF NEUTRALITY): set a pending decision for
    the first side (Christian then Muslim) that has a Lord Besieging a
    now-Neutral Enemy Stronghold, letting it choose remove-Siege vs
    add-Enemy-markers per Stronghold. `resume_active` is restored once
    all sides' choices are made."""
    from almoravid.state import PendingDecision
    for s in ("christian", "muslim"):
        side_sh = [d for d in deferred if d["side"] == s]
        if side_sh:
            state.pending = PendingDecision(
                kind="neutrality_choice", waiting_on=s,
                payload={"strongholds": side_sh,
                         "all_deferred": list(deferred),
                         "resume_active": resume_active})
            state.meta.active_player = s
            return True
    return False


def _maybe_set_neutrality_pending(state: GameState, results: dict[str, Any],
                                  resume_active: Side) -> bool:
    deferred = results.get("deferred_neutrality") or []
    return _set_neutrality_pending(state, deferred, resume_active) if deferred \
        else False


def _h_respond_neutrality_choice(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """4.3.5/1.4.3: resolve one side's RECOGNITION OF NEUTRALITY choices.
    `choices` maps locale_id -> 'remove'|'add' (default 'remove'). A
    Muslim besieger that 'adds' places Christian Conquered markers (=
    Value); a Christian besieger that 'adds' places Jihad markers."""
    side = _require_side(action)
    pd = _require_pending(state, "neutrality_choice", side)
    choices = action.get("choices", {}) or {}
    applied = []
    for sh in pd.payload["strongholds"]:
        lid = sh["locale_id"]
        v = sh["value"]
        loc = state.locales[lid]
        ch = choices.get(lid, "remove")
        if ch == "add":
            if side == "muslim":
                loc.conquered_markers += v
                state.score.christian += v
            else:
                loc.jihad_markers += v
                state.score.muslim += 0.5 * v
        else:
            if side == "muslim":
                loc.siege_green = 0
                loc.bypass_green = False
            else:
                loc.siege_yellow = 0
                loc.bypass_yellow = False
        applied.append((lid, ch))
    remaining = [d for d in pd.payload["all_deferred"] if d["side"] != side]
    resume = pd.payload["resume_active"]
    state.pending = None
    if remaining and _set_neutrality_pending(state, remaining, resume):
        next_pending = True
    else:
        state.meta.active_player = resume
        next_pending = False
    _record(state, action,
            f"{side} resolves RECOGNITION OF NEUTRALITY: {applied}")
    return {"applied": applied, "more_pending": next_pending}


def _emir_jihad_targets(state: GameState) -> list[str]:
    """M9 Emir al-Muslimin: the Jihad-eligible Locales (1.4.4) to which
    Yusuf -- holding the M9 capability and on the map -- is STRICTLY closer
    than every Christian Lord on the map (shortest chain of adjacent
    spaces; co-location with a Christian counts as NOT closer). Empty
    unless Yusuf is on map and holds M9. Shared by the handler and the
    enumerator so they stay in lockstep."""
    from almoravid.capabilities import lord_has_capability
    from almoravid.map import hop_distances
    yusuf = state.lords.get("yusuf")
    if (yusuf is None or yusuf.cylinder.kind != "locale"
            or not lord_has_capability(state, "yusuf", "M9")):
        return []
    from almoravid.events import _jihad_eligible_locales
    eligible = _jihad_eligible_locales(state)
    if not eligible:
        return []
    christian_locs = [cast(str, lord.cylinder.locale_id)
                      for lord in state.lords.values()
                      if lord.side == "christian" and lord.cylinder.kind == "locale"]
    out: list[str] = []
    for tgt in eligible:
        dist = hop_distances(tgt)
        y = dist.get(cast(str, yusuf.cylinder.locale_id))
        if y is None:
            continue
        # Strictly closer than EVERY Christian (None = unreachable = farther;
        # equal distance, e.g. co-location, is NOT closer).
        if all(dist.get(cl) is None or y < dist[cl] for cl in christian_locs):
            out.append(tgt)
    return out


def _h_cmd_emir_jihad(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """M9 Emir al-Muslimin (Arts of War ref M9): Yusuf, if closer than any
    Christian to a Jihad-eligible Locale (1.4.4), may use his ENTIRE
    Command card to add 1 Jihad there."""
    side = _require_side(action)
    _require(side == "muslim", "Emir al-Muslimin is a Muslim ability (M9)",
             code="wrong_side")
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id == "yusuf",
             "M9 Emir al-Muslimin is Yusuf's ability", code="not_yusuf")
    from almoravid.capabilities import lord_has_capability
    _require(lord_has_capability(state, "yusuf", "M9"),
             "Yusuf lacks Emir al-Muslimin (M9)", code="no_capability")
    _require(state.meta.actions_remaining >= 1,
             "needs an unspent Command card", code="not_enough_actions")
    target = action.get("jihad_locale")
    target = cast(str, target)
    _require(target in state.locales, "jihad_locale required", code="bad_arg")
    _require(target in _emir_jihad_targets(state),
             f"{target} is not a Jihad-eligible Locale Yusuf is closer to "
             f"than any Christian (M9)", code="not_eligible")
    from almoravid.events import _add_jihad
    placement = _add_jihad(state, 1, {"jihad_targets": [target]})
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0   # uses Yusuf's ENTIRE Command card
    _record(state, action,
            f"muslim Yusuf (M9 Emir al-Muslimin) adds 1 Jihad at {target}")
    return {"jihad_locale": target, "placement": placement,
            "actions_consumed": consumed}

def _has_unbesieged_enemy_lord(state: GameState, locale_id: str,
                               side: Side) -> bool:
    """Any Enemy (other-side) Lord at `locale_id` who is NOT Besieged
    (a Bypassed Lord still counts as Unbesieged). Blocks Cabalgadas
    path/target (Arts of War ref C14/C17 / M24: "not at or past any
    Unbesieged Enemy Lord, even if Bypassed")."""
    from almoravid.effective import is_besieged
    for lord in state.lords.values():
        if (lord.side != side and lord.cylinder.kind == "locale"
                and lord.cylinder.locale_id == locale_id
                and not is_besieged(state, lord.id)):
            return True
    return False


# The long-range-Ravage capability family: C14/C17 Cabalgadas (Christian) and
# M24 Al-Garada (Muslim, "See Cabalgadas"). Same mechanics; one per Lord (3.4.4
# same-title cap; C/M are different sides so no Lord can hold both anyway).
CABALGADAS_CAPS = ("C14", "C17", "M24")


def _cabalgadas_capable(state: GameState, lord_id: str) -> bool:
    """The Lord holds a Cabalgadas-family long-range-Ravage capability
    (C14/C17 Cabalgadas or M24 Al-Garada)."""
    from almoravid.capabilities import lord_has_capability
    return any(lord_has_capability(state, lord_id, c) for c in CABALGADAS_CAPS)


def _cabalgadas_prov_holder(state: GameState, lord_id: str,
                            side: Side) -> str | None:
    """Who pays the 1 Provender (1.5.2 Share): the Lord himself if he has
    Provender, else a same-Locale same-side ally with Provender. Returns
    the paying lord_id or None."""
    lord = state.lords[lord_id]
    if lord.assets.get("prov", 0) >= 1:
        return lord_id
    here = lord.cylinder.locale_id
    assert here is not None
    for lid, lord_obj in state.lords.items():
        if (lid != lord_id and lord_obj.side == side and lord_obj.cylinder.kind == "locale"
                and lord_obj.cylinder.locale_id == here and lord_obj.assets.get("prov", 0) >= 1):
            return lid
    return None


def _cabalgadas_targets(state: GameState, lord_id: str,
                        side: Side) -> list[str]:
    """Valid Cabalgadas targets for the Lord at his Locale: a Locale up to
    two Ways distant whose path's intervening Locale (if any) and target
    both have NO Unbesieged Enemy Lord, and the target is a legal Ravage
    target (Enemy Locale not already Ravaged by this side). 4.7.2 + C14/C17."""
    from almoravid.effective import is_besieged, is_friendly_locale
    from almoravid.map import all_neighbors
    lord = state.lords.get(lord_id)
    if lord is None or lord.cylinder.kind != "locale" or is_besieged(state, lord_id):
        return []
    here = lord.cylinder.locale_id
    assert here is not None

    def ravageable(t: str) -> bool:
        loc = state.locales.get(t)
        return (loc is not None and t != here
                and not is_friendly_locale(state, t, side)
                and loc.ravaged == "none"
                and not _has_unbesieged_enemy_lord(state, t, side))

    targets: set[str] = set()
    for n1 in all_neighbors(here):                 # 1 Way
        if ravageable(n1):
            targets.add(n1)
        # 2 Ways: traverse n1 only if it is free of Unbesieged Enemy Lords
        if _has_unbesieged_enemy_lord(state, n1, side):
            continue
        for n2 in all_neighbors(n1):
            if ravageable(n2):
                targets.add(n2)
    return sorted(targets)


def _h_cmd_cabalgadas(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """C14/C17 Cabalgadas long-range Ravage (Arts of War ref): the bearer
    must have or Share (1.5.2) one Provender and use ALL actions on his
    Command card; expend the Provender and Ravage a Locale up to two
    Locales distant (no Unbesieged Enemy Lord on the intervening or target
    Locale). Effect = normal Ravage (4.7.2)."""
    side = _require_side(action)
    _require_campaign_step(state, "activation")
    _require_active(state, side)
    _require(state.meta.active_lord_id is not None,
             "no active Lord", code="no_active_lord")
    lord_id = state.meta.active_lord_id
    assert lord_id is not None
    lord = state.lords[lord_id]
    _require(lord.side == side, f"{lord_id} not on {side}'s side",
             code="wrong_side")
    _require(_cabalgadas_capable(state, lord_id),
             f"{lord_id} lacks a Cabalgadas capability (C14/C17)",
             code="no_capability")
    _require(state.meta.actions_remaining >= 1,
             "Cabalgadas uses the entire Command card", code="not_enough_actions")
    payer = _cabalgadas_prov_holder(state, lord_id, side)
    _require(payer is not None,
             "Cabalgadas needs 1 Provender (own or Shared, 1.5.2)",
             code="no_provender")
    payer = cast(str, payer)
    target = action.get("target_locale")
    target = cast(str, target)
    _require(target in state.locales, "target_locale required", code="bad_arg")
    _require(target in _cabalgadas_targets(state, lord_id, side),
             f"{target} is not a legal Cabalgadas target (<=2 Ways, no "
             f"Unbesieged Enemy Lord on path/target, Ravageable)",
             code="not_eligible")
    # Expend 1 Provender (from the payer) and Ravage the target.
    state.lords[payer].assets["prov"] = state.lords[payer].assets.get("prov", 0) - 1
    res = _apply_ravage_effect(state, lord, side, target)
    consumed = state.meta.actions_remaining
    state.meta.actions_remaining = 0   # uses ALL actions on the card
    _record(state, action,
            f"{side} {lord_id} Cabalgadas-Ravages {target} (prov from {payer}): "
            f"{res['rustling']}"
            f"{', Enforcing Parias' if res['enforcing_parias'] else ''}")
    return {"target": target, "color": res["color"], "prov_payer": payer,
            "rustling": res["rustling"],
            "enforcing_parias": res["enforcing_parias"],
            "actions_consumed": consumed}

# ---------------------------------------------------------------------------
# Battle of Sagrajas minigame handlers (Background Book pp.44-47)
# ---------------------------------------------------------------------------

def _h_sagrajas_attack(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Christians Attack (historical). Add: two French Crusaders Vassal
    markers (4 Knights total), Jabalinas (C7) + Slingers (C9), and
    Cantador (C8) as a Held Event. Then the Christians are the Attacker."""
    from almoravid.state import CardInPlay, PendingDecision
    _require(state.meta.phase == "battle"
             and state.pending is not None
             and state.pending.kind == "sagrajas_who_attacks",
             "no Sagrajas Who-Attacks decision pending", code="wrong_phase")
    side = _require_side(action)
    _require(side == "christian", "only the Christian chooses (Background Book)",
             code="wrong_side")
    # Two French Crusaders (4 Knights total): 2 to Alfonso, 2 to Alvar Fanez.
    state.lords["alfonso"].forces["knights"] = \
        state.lords["alfonso"].forces.get("knights", 0) + 2
    state.lords["alvar_fanez"].forces["knights"] = \
        state.lords["alvar_fanez"].forces.get("knights", 0) + 2
    # Jabalinas (C7) -> Alfonso; Slingers (C9) -> Alvar Fanez (this_lord caps).
    state.lords["alfonso"].capabilities.append("C7")
    state.lords["alvar_fanez"].capabilities.append("C9")
    for lid, cid in (("alfonso", "C7"), ("alvar_fanez", "C9")):
        state.decks.capabilities_in_play.append(CardInPlay(
            card_id=cid, scope="this_lord", owner_side="christian",
            owner_lord_id=lid))
    # Cantador (C8) as a Held Event, played at the outset of Battle.
    state.decks.this_levy_events.setdefault("christian", []).append("C8")
    state.meta.sagrajas_role = "attack"
    state.meta.active_player = "christian"        # Christians Attack
    state.pending = PendingDecision(kind="sagrajas_resolve",
                                    waiting_on="christian", payload={})
    _record(state, action, "Sagrajas: Christians choose to ATTACK (historical)")
    return {"role": "attack", "attacker": "christian"}


def _h_sagrajas_defend(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Christians Defend (Yusuf attacks). Muslims add: Saqalibah (M15) at
    al-Mutamid (+2 Men-at-Arms), Harbah (M3) at a Taifa Lord, Andalusians
    (M10, side-wide Light-Horse Evade), and hold Feigned Retreat (M6)."""
    from almoravid.state import CardInPlay, PendingDecision
    _require(state.meta.phase == "battle"
             and state.pending is not None
             and state.pending.kind == "sagrajas_who_attacks",
             "no Sagrajas Who-Attacks decision pending", code="wrong_phase")
    side = _require_side(action)
    _require(side == "christian", "only the Christian chooses (Background Book)",
             code="wrong_side")
    # Saqalibah (M15) at al-Mutamid's mat, adding 2 Men-at-Arms.
    state.lords["al_mutamid"].forces["men_at_arms"] = \
        state.lords["al_mutamid"].forces.get("men_at_arms", 0) + 2
    state.lords["al_mutamid"].capabilities.append("M15")
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id="M15", scope="side_wide", owner_side="muslim",
        owner_lord_id=None))
    state.decks.board_edge.setdefault("muslim", []).append("M15")
    # Harbah (M3) at a Taifa Lord (not Yusuf/Sir): al-Mutawakkil.
    state.lords["al_mutawakkil"].capabilities.append("M3")
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id="M3", scope="this_lord", owner_side="muslim",
        owner_lord_id="al_mutawakkil"))
    # Andalusians (M10) in play, side-wide: all Muslim Light Horse Evade.
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id="M10", scope="side_wide", owner_side="muslim",
        owner_lord_id=None))
    state.decks.board_edge.setdefault("muslim", []).append("M10")
    # Hold Feigned Retreat (M6), in addition to Spear Wall.
    state.decks.this_levy_events.setdefault("muslim", []).append("M6")
    state.meta.sagrajas_role = "defend"
    state.meta.active_player = "muslim"           # Yusuf Attacks
    state.pending = PendingDecision(kind="sagrajas_resolve",
                                    waiting_on="muslim", payload={})
    _record(state, action, "Sagrajas: Christians choose to DEFEND (Yusuf attacks)")
    return {"role": "defend", "attacker": "muslim"}


def _h_resolve_battle(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Resolve the Sagrajas Battle (4.4) once the role is chosen. The
    Attacker's Marshal (Alfonso or Yusuf) is at Front center; whoever wins
    the Battle wins the game (Background Book). Supports an optional
    per-combat absorption_policy (4.4.2)."""
    from almoravid.battle import (
        _front_lord_count,
        battleside_for_lords,
        commit_forces_after_battle,
        resolve_battle,
    )
    from almoravid.state import Cylinder
    _require(state.meta.phase == "battle"
             and state.pending is not None
             and state.pending.kind == "sagrajas_resolve",
             "no Sagrajas Battle ready to resolve", code="wrong_phase")
    side = _require_side(action)
    assert state.pending is not None
    _require(side == state.pending.waiting_on,
             f"{side} is not the Attacker", code="wrong_side")
    role = state.meta.sagrajas_role
    atk_side: Side
    def_side: Side
    if role == "attack":
        atk_side, def_side, marshal = "christian", "muslim", "alfonso"
    else:
        atk_side, def_side, marshal = "muslim", "christian", "yusuf"
    from almoravid.scenarios import _SAGRAJAS_LOCALE
    here = _SAGRAJAS_LOCALE
    atk_lords = [lid for lid, lord in state.lords.items()
                 if lord.side == atk_side and lord.cylinder.kind == "locale"
                 and lord.cylinder.locale_id == here]
    def_lords = [lid for lid, lord in state.lords.items()
                 if lord.side == def_side and lord.cylinder.kind == "locale"
                 and lord.cylinder.locale_id == here]
    _apply_absorption_policy(state, atk_side, action)
    _apply_absorption_policy(state, def_side, action)
    atk = battleside_for_lords(state, atk_lords, atk_side, "attacker",
                               active_lord_id=marshal)
    dfd = battleside_for_lords(state, def_lords, def_side, "defender",
                               front_limit=_front_lord_count(atk))
    # The 6-Round default is only a programming safety guard; Battle (4.4)
    # continues until a side Concedes or all its Lords Rout, with no rules
    # round limit. Sagrajas is a large 5-vs-5 Battle that can run >6 Rounds,
    # so use a generous cap that the natural termination reaches first --
    # the cap must NOT decide the result. [Sagrajas cap fix]
    result = resolve_battle(
        state, atk, dfd, max_rounds=24,
        attacker_concede_round=_concede_round_arg(
            action, "attacker_concede_round"),
        defender_concede_round=_concede_round_arg(
            action, "defender_concede_round"))
    commit_forces_after_battle(state, atk)
    commit_forces_after_battle(state, dfd)
    winner = result.winner
    # Defensive fallback: if the (generous) cap was somehow reached with no
    # side fully Routed, the cap must still not determine the outcome --
    # decide by remaining (unrouted) strength; a true tie is a no-decision.
    if winner is None:
        def _strength(sd: str) -> int:
            return sum(sum(lord.forces.values()) for lord in state.lords.values()
                       if lord.side == sd and lord.cylinder.kind == "locale")
        a_str, d_str = _strength(atk_side), _strength(def_side)
        if a_str > d_str:
            winner = atk_side
        elif d_str > a_str:
            winner = def_side
    # "Whoever wins the Battle wins the game." End the minigame: the losing
    # side's Lords leave the field (so no post-game co-location); the winner
    # holds the field. A genuine tie (winner None) removes BOTH armies.
    if winner is not None:
        losers = [(def_side if winner == atk_side else atk_side)]
    else:
        losers = [atk_side, def_side]   # no decision: clear the field
    for _lid, lord in state.lords.items():
        if lord.side in losers:
            lord.cylinder = Cylinder(kind="removed")
            lord.in_stronghold = False
    state.score.winner = winner
    state.score.victory_reason = (
        f"Battle of Sagrajas: {winner} wins the Battle" if winner
        else "Battle of Sagrajas: no decision")
    if winner == "christian":
        state.score.christian += 1.0
    elif winner == "muslim":
        state.score.muslim += 1.0
    state.meta.phase = "ended"
    state.pending = None
    _record(state, action,
            f"Sagrajas Battle resolved over {len(result.rounds)} rounds: "
            f"winner={winner}")
    return {"winner": winner, "rounds": len(result.rounds),
            "attacker": atk_side, "defender": def_side}

CAMPAIGN_HANDLERS = {
    "respond_neutrality_choice": _h_respond_neutrality_choice,
    "place_cathedral_seat": _h_place_cathedral_seat,
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
    "respond_besiege": _h_respond_besiege,
    "respond_bypass": _h_respond_bypass,
    "battle_concede": _h_battle_concede,
    "storm_concede": _h_storm_concede,
    "relief_concede": _h_relief_concede,
    "play_pope_gregory": _h_play_pope_gregory,
    "play_cluniacs": _h_play_cluniacs,
    "play_al_qadir": _h_play_al_qadir,
    "play_de_vivar_reconcile": _h_play_de_vivar_reconcile,
    "cmd_march_port_to_port": _h_cmd_march_port_to_port,
    "designate_lieutenant": _h_designate_lieutenant,
    "toggle_lieutenant": _h_toggle_lieutenant,
    "cmd_encamp": _h_cmd_encamp,
    "cmd_sortie": _h_cmd_sortie,
    "winter_siege_action": _h_winter_siege_action,
    "winter_siege_pay": _h_winter_siege_pay,
    "dinars_deposit": _h_dinars_deposit,
    "cmd_emir_jihad": _h_cmd_emir_jihad,
    "cmd_cabalgadas": _h_cmd_cabalgadas,
    "sagrajas_attack": _h_sagrajas_attack,
    "sagrajas_defend": _h_sagrajas_defend,
    "resolve_battle": _h_resolve_battle,
    "set_absorption_policy": _h_set_absorption_policy,
}
