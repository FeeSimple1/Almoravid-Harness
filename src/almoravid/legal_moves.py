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

from almoravid.state import GameState, Lord, Side


def legal_moves(state: GameState) -> list[dict[str, Any]]:
    """Return the list of currently-legal action dicts."""
    moves: list[dict[str, Any]] = []

    # Battle of Sagrajas minigame (Background Book pp.44-47). The Christian
    # chooses Attack/Defend, then the Attacker resolves the Battle.
    if (state.pending is not None
            and state.pending.kind == "sagrajas_who_attacks"):
        return [{"type": "sagrajas_attack", "side": "christian"},
                {"type": "sagrajas_defend", "side": "christian"}]
    if (state.pending is not None
            and state.pending.kind == "sagrajas_resolve"):
        return [{"type": "resolve_battle", "side": state.pending.waiting_on}]

    # Phase 6b: when a march_arrival_response decision is pending, the
    # responder owes one of Avoid Battle / Withdraw / Stand & Fight
    # before any other action can proceed. Pattern 11: only the
    # waiting_on side may act.
    if (state.pending is not None
            and state.pending.kind == "march_arrival_response"):
        moves.extend(_march_response_moves(state))
        return moves

    # C1 (4.3.5): after a Withdraw, the Active side must choose Besiege
    # or Bypass before any other action.
    if (state.pending is not None
            and state.pending.kind == "besiege_or_bypass"):
        side = state.pending.waiting_on
        moves.append({"type": "respond_besiege", "side": side})
        moves.append({"type": "respond_bypass", "side": side})
        return moves

    # T4 (1.4.3): RECOGNITION OF NEUTRALITY — the besieging side chooses
    # remove-Siege vs add-Enemy-markers at each now-Neutral Stronghold.
    # Offer the two canonical resolutions (all-remove / all-add); the
    # agent may also send custom per-Stronghold choices.
    if (state.pending is not None
            and state.pending.kind == "neutrality_choice"):
        side = state.pending.waiting_on
        locs = [sh["locale_id"] for sh in state.pending.payload["strongholds"]]
        moves.append({"type": "respond_neutrality_choice", "side": side,
                      "choices": {lid: "remove" for lid in locs}})
        moves.append({"type": "respond_neutrality_choice", "side": side,
                      "choices": {lid: "add" for lid in locs}})
        return moves

    # 4.4.2 CONCEDE THE FIELD? — reactive per-Round Concede declaration in
    # an interactive Battle. The waiting side declares whether the Attacker
    # and/or Defender Concedes this Round (Attacker then Defender). Offer
    # the three meaningful choices; the driver may also send a custom
    # combination of attacker_concede / defender_concede.
    if (state.pending is not None
            and state.pending.kind == "battle_concede"):
        side = state.pending.waiting_on
        moves.append({"type": "battle_concede", "side": side})
        moves.append({"type": "battle_concede", "side": side,
                      "attacker_concede": True})
        moves.append({"type": "battle_concede", "side": side,
                      "defender_concede": True})
        return moves

    # S10 Storm Concede — Attacker only (4.5.2), reactive per Round (2+).
    if (state.pending is not None
            and state.pending.kind == "storm_concede"):
        side = state.pending.waiting_on
        moves.append({"type": "storm_concede", "side": side})
        moves.append({"type": "storm_concede", "side": side,
                      "attacker_concede": True})
        return moves

    # 6.3.2 Winter Siege (Scenario F): the besieging side acts one Lord
    # at a time (Supply / Ravage / pass), then Christian-then-Muslim Pay
    # (or done) at Sieges. Pattern 11: only the waiting_on side may act.
    if (state.pending is not None
            and state.pending.kind == "winter_siege"):
        from almoravid.static_data import load_strongholds  # noqa: F401
        side = state.pending.waiting_on
        payload = state.pending.payload
        if payload["step"] == "besieger_actions" and payload["queue"]:
            lord_id = payload["queue"][0]
            lord = state.lords.get(lord_id)
            moves.append({"type": "winter_siege_action", "side": side,
                          "lord_id": lord_id, "mode": "pass"})
            moves.append({"type": "winter_siege_action", "side": side,
                          "lord_id": lord_id, "mode": "ravage"})
            # Supply: one option per reachable Seat (mirror cmd_supply).
            try:
                from almoravid.campaign import _find_supply_routes, _own_seats
                if lord is not None and lord.cylinder.kind == "locale":
                    seats = _own_seats(state, lord_id)
                    here = lord.cylinder.locale_id
                    assert here is not None
                    cart = lord.assets.get("cart", 0)
                    mule = lord.assets.get("mule", 0)
                    routes = _find_supply_routes(state, here, seats,
                                                 side, lord)
                    for seat, route in routes.items():
                        if seat == here or (route is not None
                                            and len(route) <= cart + mule):
                            moves.append({"type": "winter_siege_action",
                                          "side": side, "lord_id": lord_id,
                                          "mode": "supply",
                                          "source_seat": seat})
            except (ImportError, KeyError, AttributeError, FileNotFoundError):
                pass
            return moves
        # Pay step: offer Pay for Lords at Sieges of the current side + done.
        from almoravid.campaign import _siege_locale_lords
        siege_lords = [lid for lid in _siege_locale_lords(state)
                       if state.lords[lid].side == side]
        for lid in siege_lords:
            moves.append({"type": "winter_siege_pay", "side": side,
                          "resource": "coin", "amount": 1,
                          "target_lord_id": lid})
        moves.append({"type": "winter_siege_pay", "side": side, "done": True})
        return moves

    # M11 "Al-Qadir balks at payment" is a discretionary HOLD event: the
    # Muslim may play it (to add Jihad) at any of his decision points
    # once held (3.1.3 / 1.4.4). Offered in Levy or Campaign on Muslim's
    # turn; carried through since the phase branches extend this list.
    if (state.meta.active_player == "muslim"
            and state.meta.phase in ("levy", "campaign")
            and "M11" in state.decks.this_levy_events.get("muslim", [])
            and any(state.lords.get(x) is not None
                    and state.lords[x].cylinder.kind == "locale"
                    for x in ("yusuf", "sir"))):
        moves.append({"type": "play_al_qadir", "side": "muslim"})

    # C14 Pope Gregory (Sancho/Eudes) and C15 Cluniacs (any Christian) are
    # discretionary Christian HOLD events: "play on a Lord any time to
    # Muster him from Calendar, OR shift his Service, OR for Lordship +2"
    # (Arts of War ref C14/C15; 3.4.1). Like M11 above, offered on the
    # Christian's turn in Levy/Campaign once held. Each (lord, mode) combo
    # is gated by that mode's precondition so the menu mirrors the handler
    # (muster needs a Calendar lord + free Seat; the shift needs a Service
    # marker; +2 Lordship applies to any usable target). [Advisory #3 under-enum]
    if (state.meta.active_player == "christian"
            and state.meta.phase in ("levy", "campaign")):
        from almoravid.actions import _free_seats_for as _fs_c

        def _has_svc_marker(lid: str) -> bool:
            return any(sm.lord_id == lid and sm.vassal_id is None
                       for sm in state.calendar.service_markers)

        _held_c = state.decks.this_levy_events.get("christian", [])
        _c_targets = {
            "C14": (("sancho", "eudes"), "play_pope_gregory"),
            "C15": (tuple(lid for lid, lord_obj in state.lords.items()
                          if lord_obj.side == "christian"), "play_cluniacs"),
        }
        for _card, (_targets, _atype) in _c_targets.items():
            if _card not in _held_c:
                continue
            for _lid in _targets:
                _l = state.lords.get(_lid)
                if _l is None or _l.cylinder.kind not in ("calendar", "locale"):
                    continue  # set-aside: not a usable target
                if _l.cylinder.kind == "calendar" and _fs_c(state, _lid):
                    moves.append({"type": _atype, "side": "christian",
                                  "lord_id": _lid,
                                  "mode": "muster_from_calendar"})
                if _has_svc_marker(_lid):
                    moves.append({"type": _atype, "side": "christian",
                                  "lord_id": _lid,
                                  "mode": "service_shift_right"})
                moves.append({"type": _atype, "side": "christian",
                              "lord_id": _lid, "mode": "lordship_plus_2"})

    # Lifecycle: begin_levy only from setup. Levy<->Campaign transitions
    # are handled by _advance_step_if_both_done and _h_end_campaign — the
    # agent never has to explicitly invoke a phase-start handler mid-game.
    if state.meta.phase == "setup":
        # 6.1 Bidding for Sides is a one-time PRE-GAME setup agreement,
        # not an in-game move — it is a valid callable action (handler
        # bid_for_sides) but is intentionally NOT enumerated in the
        # default move stream, so automated drivers don't auto-bid (which
        # would perturb the game's RNG / seat assignment). A player who
        # wants to bid issues the action explicitly before begin_levy.
        moves.append({"type": "begin_levy"})
        return moves

    if state.meta.phase == "campaign":
        moves.extend(_campaign_moves(state))
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

    # pass_step is legal for the active side during a Levy step, EXCEPT
    # during service_disband while that side still owes a mandatory
    # Disband (3.3) — keeps the legal_moves<->apply contract intact.
    if step in ("arts_of_war", "pay", "service_disband", "muster", "call_to_arms"):
        if step == "service_disband" and pending_mandatory_disbands(state, active):
            pass
        elif step == "arts_of_war" and (
                state.decks.pending_draw.get(active)
                or not state.meta.aow_draw_done.get(active)):
            # 3.1.2/3.1.3 + L13: must draw two AoW cards and deploy/
            # implement them before passing the Arts-of-War step.
            pass
        else:
            moves.append({"type": "pass_step", "side": active})

    return moves


def _aow_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.1 Arts of War: shuffle / draw, then deploy Capabilities (first
    Levy, 3.1.2) or implement Events (later Levy, 3.1.3) for drawn cards."""
    from almoravid.static_data import load_cards
    out: list[dict[str, Any]] = []
    pend = state.decks.pending_draw.get(side, [])
    if pend:
        # L13: drawn cards MUST be processed before anything else.
        from almoravid.actions import aow_capability_phase
        if aow_capability_phase(state):
            cards = load_cards()["cards"]
            for cid in pend:
                rec = cards.get(cid, {})
                if rec.get("no_capability") or rec.get("capability_scope") is None:
                    out.append({"type": "aow_deploy_capability",
                                "side": side, "card_id": cid})
                elif rec["capability_scope"] == "side_wide":
                    out.append({"type": "aow_deploy_capability",
                                "side": side, "card_id": cid})
                else:  # this_lord: offer each eligible Mustered Lord (+ discard)
                    _nm = rec.get("capability_name")
                    from almoravid.capabilities import capability_eligible_lords as _cel_d
                    _elig_d = _cel_d(cid)   # 3.4.4 card-text eligibility [Q-001]
                    for lid, lord in state.lords.items():
                        if lord.side != side or lord.cylinder.kind != "locale":
                            continue
                        if _elig_d is not None and lid not in _elig_d:
                            continue
                        held = [cards.get(c, {}).get("capability_name")
                                for c in lord.capabilities]
                        # 3.4.4: max 2 This-Lord caps, no same title.
                        if len(lord.capabilities) >= 2 or _nm in held:
                            continue
                        out.append({"type": "aow_deploy_capability",
                                    "side": side, "card_id": cid,
                                    "lord_id": lid})
                    out.append({"type": "aow_deploy_capability",
                                "side": side, "card_id": cid})
        else:
            # Implement Events in draw order (FIFO): only the first.
            out.append({"type": "aow_implement_event", "side": side,
                        "card_id": pend[0]})
        return out
    # No pending cards. 3.1.2/3.1.3: each side MUST draw two AoW cards
    # this Levy before proceeding. Until that mandatory draw is done,
    # offer Shuffle and the (fixed, count-2) Draw; afterwards the step is
    # complete (pass_step advances — gated in the caller).
    if not state.meta.aow_draw_done.get(side):
        # Offer the (mandatory, count-2) Draw first so a greedy agent
        # completes the draw; Shuffle remains available (Draw also
        # auto-rebuilds the deck if empty).
        out.append({"type": "aow_draw", "side": side})
        out.append({"type": "aow_shuffle", "side": side})
    return out


def _pay_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.2 Pay: spend Coin (3.2.1) / Loot (3.2.2) / Taifa-box Coin to
    shift a Service marker rightward. Surfaces the simplest faithful
    options (pay 1 to a payer's own marker, and Taifa-box Coin to any
    Unbesieged Muslim Lord); richer same-Locale / multi-amount targets
    are reachable by supplying explicit parameters."""
    from almoravid.effective import is_besieged, is_friendly_locale
    out: list[dict[str, Any]] = []
    has_marker = {sm.lord_id for sm in state.calendar.service_markers
                  if sm.vassal_id is None}
    for lid, lord in state.lords.items():
        if lord.side != side or lord.cylinder.kind != "locale":
            continue
        if lid not in has_marker:
            continue
        if lord.assets.get("coin", 0) >= 1:
            out.append({"type": "pay_lord", "side": side,
                        "payer_lord_id": lid, "target_lord_id": lid,
                        "resource": "coin", "amount": 1})
        if lord.assets.get("loot", 0) >= 1:
            try:
                here = lord.cylinder.locale_id
                assert here is not None
                if (is_friendly_locale(state, here, side)
                        and not is_besieged(state, lid)):
                    out.append({"type": "pay_lord", "side": side,
                                "payer_lord_id": lid, "target_lord_id": lid,
                                "resource": "loot", "amount": 1})
            except (ImportError, KeyError, AttributeError, FileNotFoundError):
                pass
    # Taifa-box Coin -> any Unbesieged Muslim Lord with a marker.
    if side == "muslim" and state.taifas_box_coin >= 1:
        for lid, lord in state.lords.items():
            if (lord.side == "muslim" and lid in has_marker
                    and lord.cylinder.kind == "locale"):
                try:
                    if not is_besieged(state, lid):
                        out.append({"type": "pay_lord", "side": "muslim",
                                    "target_lord_id": lid,
                                    "resource": "taifa_coin", "amount": 1})
                except (ImportError, KeyError, AttributeError, FileNotFoundError):
                    pass
    return out


def _service_disband_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.3 Disband. Disband is driven by Service-marker position and is
    MANDATORY for Lords at or beyond the Service limit (box <= current
    Levy/Campaign box). Only those Lords are offered. Independent Taifa
    Lords get a deterministic Parias-Coin distribution (1.4.3) that the
    caller may override."""
    from almoravid.effective import is_besieged
    out: list[dict[str, Any]] = []
    cur = state.calendar.current_box
    marker_box = {m.lord_id: m.box for m in state.calendar.service_markers
                  if m.vassal_id is None}
    for lid, lord in state.lords.items():
        if lord.side != side or lord.cylinder.kind != "locale":
            continue
        box = marker_box.get(lid)
        # Eligible iff off-Calendar (no marker) or at/left of the marker.
        if box is not None and box > cur:
            continue
        move: dict[str, Any] = {"type": "disband_lord", "side": side,
                                "lord_id": lid}
        if (lord.is_taifa and lord.home_taifa
                and state.taifas.get(lord.home_taifa) is not None
                and state.taifas[lord.home_taifa].status == "independent"):
            elig = [cid for cid, c in state.lords.items()
                    if c.side == "christian" and c.cylinder.kind == "locale"
                    and not is_besieged(state, cid)]
            if elig:
                move["parias_coin_targets"] = [
                    {"lord_id": elig[0], "coin": lord.service_rating}]
        out.append(move)
    return out


def pending_mandatory_disbands(state: GameState, side: Side) -> list[str]:
    """Lords of `side` that MUST Disband now (3.3): on the map with a
    Service marker at or left of the Levy/Campaign marker, or off the
    Calendar entirely. Used to block passing the service_disband step
    while a mandatory Disband is outstanding."""
    cur = state.calendar.current_box
    marker_box = {m.lord_id: m.box for m in state.calendar.service_markers
                  if m.vassal_id is None}
    out: list[str] = []
    for lid, lord in state.lords.items():
        if lord.side != side or lord.cylinder.kind != "locale":
            continue
        box = marker_box.get(lid)
        if box is None or box <= cur:
            out.append(lid)
    return out


def _muster_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.4 Muster: Lord-Muster + Lordship-spending Levy actions."""
    from almoravid.effective import is_besieged, is_friendly_locale
    out: list[dict[str, Any]] = []
    # 3.4.1: a Levying Lord (on the map, eligible, with spare Lordship,
    # not newly Mustered this segment) must spend a point to enable a
    # Muster roll. Enumerate the eligible leviers once.
    leviers: list[str] = []
    for clid, cl in state.lords.items():
        if (cl.side == side and cl.cylinder.kind == "locale"
                and not cl.just_arrived_this_levy
                and cl.lordship_used < cl.lordship_rating):
            try:
                cl_here = cl.cylinder.locale_id
                assert cl_here is not None
                assert cl_here is not None
                if (is_friendly_locale(state, cl_here, side)
                        and not is_besieged(state, clid)):
                    leviers.append(clid)
            except Exception:
                pass
    for lid, lord in state.lords.items():
        if lord.side != side:
            continue
        # Path 1: Muster a Lord from Calendar. 3.4.1: must have a
        # Fealty rating, be Ready (cylinder box at or left of the Levy
        # marker), and not be under a M16/M17 Muster ban; AND an
        # eligible Levying Lord must be available to spend Lordship.
        if (lord.fealty is not None
                and lord.cylinder.kind == "calendar"
                and (lord.cylinder.box is None
                     or lord.cylinder.box <= state.calendar.current_box)
                and lid not in state.meta.muster_banned_this_levy_lord_ids):
            free = _free_seats_for(state, lid)
            for seat in free:
                for levier_id in leviers:
                    out.append({"type": "muster_lord", "side": side,
                                "lord_id": lid, "seat": seat,
                                "levying_lord_id": levier_id})
        # Path 2: Spend Lordship on a Mustered Lord. 3.4 intro gate:
        # the Lord must be on the map at a Friendly Locale and Unbesieged
        # (Bypassed is OK) to take any Levy action.
        if (lord.cylinder.kind == "locale"
                and lord.lordship_used < lord.lordship_rating):
            from almoravid.effective import is_besieged, is_friendly_locale
            here = lord.cylinder.locale_id
            assert here is not None
            try:
                eligible = (is_friendly_locale(state, here, side)
                            and not is_besieged(state, lid))
            except Exception:
                eligible = False
            if eligible:
                for i, v in enumerate(lord.vassals):
                    if v.ready:
                        out.append({"type": "levy_take_vassal", "side": side,
                                    "lord_id": lid, "vassal_index": i})
                from almoravid.actions import _unused_capability_cards
                from almoravid.static_data import load_cards as _lc_cap
                _capcards = _lc_cap()["cards"]
                _held = [_capcards.get(c, {}).get("capability_name")
                         for c in lord.capabilities]
                # 3.4.4: select from ANY of the side's unused Capability
                # cards (full deck minus in-play/held/pending), not just
                # the board edge.
                for card_id in _unused_capability_cards(state, side):
                    _rec = _capcards.get(card_id, {})
                    if _rec.get("capability_scope") == "this_lord":
                        # 3.4.4: max 2 This-Lord caps, no same title, and
                        # card-text eligibility (e.g. C8/C15/C24). [Q-001]
                        from almoravid.capabilities import capability_eligible_lords as _cel_l
                        _elig_l = _cel_l(card_id)
                        if (len(lord.capabilities) >= 2
                                or _rec.get("capability_name") in _held
                                or (_elig_l is not None
                                    and lid not in _elig_l)):
                            continue
                    out.append({"type": "levy_take_capability", "side": side,
                                "lord_id": lid, "card_id": card_id})
                # 3.4.3 Levy Transport: add a Cart or a Mule.
                for tr in ("cart", "mule"):
                    out.append({"type": "levy_transport", "side": side,
                                "lord_id": lid, "transport": tr})
    return out


def _call_to_arms_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.5 Call to Arms (FIX-A / L2). Surfaces each currently-legal
    option for `side` with a deterministic, directly-executable
    parameter set; richer payment splits / seat choices are reachable
    by supplying explicit parameters. Enforces the one-option-per-side
    limit and the Christian-first / Muslim-then sequencing implicitly
    via active_player + cta_option_used_{side}.
    """
    from almoravid.effective import is_besieged, is_friendly_locale
    out: list[dict[str, Any]] = []
    if state.meta.phase != "levy" or state.meta.levy_step != "call_to_arms":
        return out
    strong_types = ("city", "fortress", "town", "castle")

    def free_of_siege(lid: str) -> bool:
        loc = state.locales[lid]
        return loc.siege_yellow == 0 and loc.siege_green == 0

    def no_enemy_lord(lid: str) -> bool:
        # 3.4.1: a Muster Seat must have no Enemy Lord present. [P-5]
        return not any(
            lord.cylinder.kind == "locale" and lord.cylinder.locale_id == lid
            and lord.side != side
            for lord in state.lords.values())

    def ready(lord: Lord) -> bool:
        return (lord.cylinder.kind == "calendar"
                and (lord.cylinder.box is None
                     or lord.cylinder.box <= state.calendar.current_box))

    def build_payment(payer_side: Side, required: int,
                      allow_taifa: bool) -> list[dict[str, Any]] | None:
        remaining = required
        plan: list[dict[str, Any]] = []
        if allow_taifa and state.taifas_box_coin > 0:
            take = min(state.taifas_box_coin, remaining)
            if take > 0:
                plan.append({"taifa_box": take})
                remaining -= take
        for lid, lord in state.lords.items():
            if remaining <= 0:
                break
            if lord.side != payer_side or lord.cylinder.kind != "locale":
                continue
            try:
                if is_besieged(state, lid):
                    continue
            except Exception:
                continue
            c = lord.assets.get("coin", 0)
            if c <= 0:
                continue
            take = min(c, remaining)
            plan.append({"lord_id": lid, "coin": take})
            remaining -= take
        return plan if remaining <= 0 else None

    # Muslim Crusade-Jihad add (3.5.1 follow-up) — independent of the
    # one-option limit.
    if side == "muslim" and state.meta.cta_crusade_jihad_pending:
        from almoravid.events import _jihad_eligible_locales
        for lid in _jihad_eligible_locales(state):
            out.append({"type": "cta_add_crusade_jihad", "side": "muslim",
                        "jihad_locale": lid})

    used = (state.meta.cta_option_used_christian if side == "christian"
            else state.meta.cta_option_used_muslim)
    if used:
        return out

    if side == "christian":
        sayyid = state.lords["rodrigo_al_sayyid"]
        camp = state.lords["rodrigo_campeador"]
        eudes = state.lords["eudes"]
        christian_removed = any(
            lord.side == "christian" and lord.cylinder.kind == "removed"
            for lord in state.lords.values())
        if sayyid.cylinder.kind == "locale" or christian_removed:
            out.append({"type": "cta_reconcile_rodrigo", "side": "christian"})
        if ready(camp):
            pay = build_payment("christian", 2, False)
            if pay is not None:
                for lid, loc in state.locales.items():
                    if (loc.base_type in strong_types and free_of_siege(lid)
                            and is_friendly_locale(state, lid, "christian")
                            and no_enemy_lord(lid)):
                        out.append({"type": "cta_employ_rodrigo",
                                    "side": "christian", "seat": lid,
                                    "payments": pay})
        if (ready(eudes) and free_of_siege("pamplona")
                and is_friendly_locale(state, "pamplona", "christian")
                and no_enemy_lord("pamplona")):
            out.append({"type": "cta_call_crusade", "side": "christian"})
        return out

    # Muslim 3.5.2 options.
    yusuf = state.lords["yusuf"]
    sir = state.lords["sir"]
    sayyid = state.lords["rodrigo_al_sayyid"]
    if ready(sayyid):
        pay = build_payment("muslim", 3, True)
        if pay is not None:
            for lid, loc in state.locales.items():
                if (loc.base_type in strong_types and free_of_siege(lid)
                        and is_friendly_locale(state, lid, "muslim")
                        and no_enemy_lord(lid)):
                    out.append({"type": "cta_employ_rodrigo",
                                "side": "muslim", "seat": lid,
                                "payments": pay})
    # Invite the Almoravids (3.5.2): only offer when an actual Muster Port
    # exists -- Algeciras (Muslim-Friendly, free of Siege, no Enemy Lord),
    # else the nearest qualifying Port. Mirrors _h_cta_invite_almoravids so
    # the enumerator never offers a move the handler would reject. [P-5]
    from almoravid.map import nearest_ports as _nearest_ports

    def _invite_seat_exists() -> bool:
        if (is_friendly_locale(state, "algeciras", "muslim")
                and free_of_siege("algeciras")
                and no_enemy_lord("algeciras")):
            return True
        for port, _d in _nearest_ports("algeciras"):
            if port == "algeciras":
                continue
            if (is_friendly_locale(state, port, "muslim")
                    and free_of_siege(port) and no_enemy_lord(port)):
                return True
        return False

    if _invite_seat_exists():
        for cand in ("yusuf", "sir"):
            if ready(state.lords[cand]):
                out.append({"type": "cta_invite_almoravids", "side": "muslim",
                            "lord_id": cand})

    def on_cal_ready(lord: Lord) -> bool:
        return (lord.cylinder.kind == "calendar"
                and lord.cylinder.box is not None
                and lord.cylinder.box <= state.calendar.current_box)

    if on_cal_ready(yusuf) and on_cal_ready(sir):
        from almoravid.events import _jihad_eligible_locales
        elig = _jihad_eligible_locales(state)
        if elig:
            for lid in elig:
                out.append({"type": "cta_uphold_dynasties", "side": "muslim",
                            "jihad_locale": lid})
        else:
            out.append({"type": "cta_uphold_dynasties", "side": "muslim"})
    if yusuf.cylinder.kind == "locale":
        here = yusuf.cylinder.locale_id
        assert here is not None
        if is_friendly_locale(state, here, "muslim") and free_of_siege(here):
            marker_lords = {sm.lord_id for sm in state.calendar.service_markers
                            if sm.vassal_id is None}
            for tlid, tl in state.lords.items():
                if not (tl.is_taifa and here in tl.seats):
                    continue
                if tl.cylinder.kind == "calendar":
                    for seat in _free_seats_for(state, tlid):
                        out.append({"type": "cta_call_emir", "side": "muslim",
                                    "taifa_lord_id": tlid, "mode": "muster",
                                    "seat": seat})
                if tlid in marker_lords:
                    out.append({"type": "cta_call_emir", "side": "muslim",
                                "taifa_lord_id": tlid, "mode": "shift"})
    return out


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



def _campaign_moves(state: GameState) -> list[dict[str, Any]]:
    """Enumerate currently-legal Campaign moves."""
    out: list[dict[str, Any]] = []
    cstep = state.meta.campaign_step
    active = state.meta.active_player

    # cstep is set by _advance_step_if_both_done at Levy->Campaign
    # transition; cstep is never None during the Campaign phase under
    # normal operation. If it somehow is, begin_campaign is the recovery.
    if cstep is None:
        out.append({"type": "begin_campaign"})
        return out

    if cstep == "plan":
        # Either side may add to their own plan in any order.
        for side in ("christian", "muslim"):
            plan = state.decks.plan.get(side, [])
            from almoravid.campaign import _plan_target_size
            target = _plan_target_size(state)
            if len(plan) < target:
                # C7 (1.9.2/4.1.1): only Mustered (on-map) Lords' Command
                # cards may be planned; each Lord has 3 cards (4 Marshal);
                # and a side has only five Pass cards. Offer only LEGAL
                # additions so the enumerator/handler stay in lockstep.
                from almoravid.campaign import _is_marshal
                pass_used = sum(1 for e in plan if e.kind == "pass")
                if pass_used < 5:
                    out.append({"type": "plan_add_card", "side": side,
                                "plan_kind": "pass"})
                for lid, lord in state.lords.items():
                    if not (lord.side == side
                            and lord.cylinder.kind == "locale"):
                        continue
                    cap = 4 if _is_marshal(lid, side) else 3
                    used = sum(1 for e in plan
                               if e.kind == "command" and e.lord_id == lid)
                    if used < cap:
                        out.append({"type": "plan_add_card", "side": side,
                                    "plan_kind": "command", "lord_id": lid})
            # 4.1.4 Dinars: an Unbesieged Muslim Taifa Lord (not Yusuf/
            # Sir/Rodrigo) with Coin may deposit it into the Taifas box
            # during the Plan step. (Was a working handler with no menu
            # entry -> under-enumeration; mirrors _h_dinars_deposit gates.)
            if side == "muslim":
                from almoravid.effective import is_besieged as _ib_dn
                for lid, lord in state.lords.items():
                    if (lord.side == "muslim" and lord.is_taifa
                            and lid not in ("yusuf", "sir",
                                            "rodrigo_campeador",
                                            "rodrigo_al_sayyid")
                            and lord.cylinder.kind == "locale"
                            and lord.assets.get("coin", 0) > 0
                            and not _ib_dn(state, lid)):
                        out.append({"type": "dinars_deposit", "side": side,
                                    "lord_id": lid})
            # 4.1.3 Designate Lieutenant: stack a Lower Lord under a
            # Lieutenant at the same Locale (Plan step). Both same-side on
            # the map, neither the Marshal, the commander not itself a Lower
            # Lord and not already leading one. (Working handler, no menu
            # entry -> under-enumeration; mirrors _h_designate_lieutenant.)
            from almoravid.campaign import _is_marshal as _ismar
            side_on_map = [(lid, lord_obj) for lid, lord_obj in state.lords.items()
                           if lord_obj.side == side and lord_obj.cylinder.kind == "locale"]
            for lid, lord_obj in side_on_map:
                if _ismar(lid, side):
                    continue
                for cid, cl in side_on_map:
                    if cid == lid or _ismar(cid, side):
                        continue
                    if cl.cylinder.locale_id != lord_obj.cylinder.locale_id:
                        continue
                    if cl.lieutenant_of is not None:
                        continue
                    if any(x.lieutenant_of == cid
                           for x in state.lords.values()):
                        continue
                    out.append({"type": "designate_lieutenant", "side": side,
                                "lord_id": lid, "commander_id": cid})
            already_fin = (state.meta.plan_finalized_christian
                           if side == "christian"
                           else state.meta.plan_finalized_muslim)
            if len(plan) == target and not already_fin:
                out.append({"type": "finalize_plan", "side": side})
        return out

    if cstep == "activation":
        if state.meta.active_lord_id is None:
            out.append({"type": "command_reveal", "side": active})
        else:
            # C16 Cathedrals: Alfonso at a Christian-Conquered City with
            # the capability may place a Cathedral Seat (free, optional).
            if (state.meta.active_lord_id == "alfonso"
                    and "C16" in state.lords["alfonso"].capabilities
                    and state.lords["alfonso"].cylinder.kind == "locale"):
                _al = state.lords["alfonso"]
                assert _al.cylinder.locale_id is not None
                _loc = state.locales.get(_al.cylinder.locale_id)
                _gate = (state.meta.scenario_letter != "F"
                         or any(state.lords.get(x) is not None
                                and state.lords[x].cylinder.kind == "locale"
                                for x in ("yusuf", "sir")))
                if (_loc is not None and _loc.base_type == "city"
                        and _loc.conquered_markers > 0
                        and _loc.territory in state.taifas
                        and _al.cylinder.locale_id
                        not in state.cathedral_seat_locales
                        and len(state.cathedral_seat_locales) < 2
                        and _gate):
                    out.append({"type": "place_cathedral_seat",
                                "side": "christian"})
            # An active Lord has actions_remaining > 0.
            if state.meta.actions_remaining > 0:
                lord_id = state.meta.active_lord_id
                lord = state.lords[lord_id]
                out.append({"type": "cmd_pass", "side": active})
                # C15 Alferez (This-Lord capability): the bearer may spend
                # 1 Command action to stack as a Lieutenant onto a same-Locale
                # Christian Lord, or unstack -- the 4.1.3 exception allowing
                # (un)stacking outside the Plan step, repeatable within a card.
                # Q-001 resolved (scope=this_lord; eligible bearers = the four
                # captains, enforced at Levy/deploy), so lord_has_capability is
                # now reachable. Mirrors _h_toggle_lieutenant's 4.1.3 gates.
                from almoravid.capabilities import lord_has_capability as _lhc_al
                if _lhc_al(state, lord_id, "C15"):
                    if lord.lieutenant_of is not None:
                        out.append({"type": "toggle_lieutenant",
                                    "side": active, "mode": "unstack"})
                    else:
                        from almoravid.campaign import _is_marshal as _ism_al
                        _here_al = lord.cylinder.locale_id
                        assert _here_al is not None
                        for _cid, _cl in state.lords.items():
                            if (_cid != lord_id and _cl.side == active
                                    and not _ism_al(_cid, active)
                                    and _cl.cylinder.kind == "locale"
                                    and _cl.cylinder.locale_id == _here_al
                                    and not any(x.lieutenant_of == _cid
                                                for x in state.lords.values())):
                                out.append({"type": "toggle_lieutenant",
                                            "side": active, "mode": "stack",
                                            "commander_id": _cid})
                # M9 Emir al-Muslimin: Yusuf, if closer than any Christian
                # to a Jihad-eligible Locale (1.4.4), may use his entire
                # Command card to add 1 Jihad there (Arts of War ref M9).
                if lord_id == "yusuf":
                    from almoravid.campaign import _emir_jihad_targets
                    for _tgt in _emir_jihad_targets(state):
                        out.append({"type": "cmd_emir_jihad", "side": active,
                                    "jihad_locale": _tgt})
                # C14/C17 Cabalgadas long-range Ravage: the bearer (with 1
                # Provender, own or Shared) may Ravage a Locale up to two
                # Ways away with no Unbesieged Enemy Lord on the path/target,
                # using his entire Command card (Arts of War ref C14/C17).
                from almoravid.campaign import (
                    _cabalgadas_capable,
                    _cabalgadas_prov_holder,
                    _cabalgadas_targets,
                )
                if (_cabalgadas_capable(state, lord_id)
                        and _cabalgadas_prov_holder(state, lord_id, active)
                        is not None):
                    for _ct in _cabalgadas_targets(state, lord_id, active):
                        out.append({"type": "cmd_cabalgadas", "side": active,
                                    "target_locale": _ct})
                # March destinations (rule 4.3) — one option per
                # adjacent locale per way_type. Pattern 4: keep way_type
                # explicit so the agent's intent is honored.
                # CROSS_PROJECT_LESSONS.md §1: defensive try/except
                # around static-data lookups in the enumerator. Bias:
                # miss a legal move (the agent can still pass) over
                # offering a phantom-legal move that the handler will
                # reject.
                try:
                    from almoravid.campaign import _is_laden
                    from almoravid.effective import is_besieged
                    from almoravid.map import neighbors_via
                    if (not is_besieged(state, lord_id)
                            and lord.cylinder.kind == "locale"
                            # C3/M3 Swollen River: a Lord already blocked
                            # this card may not March again (handler mirror).
                            and state.meta.swollen_river_blocked_card_lord_id
                            != lord_id):
                        cost = 2 if _is_laden(lord) else 1
                        if state.meta.actions_remaining >= cost:
                            from_loc = lord.cylinder.locale_id
                            assert from_loc is not None
                            for way_type in ("road", "pass"):
                                for nbr in neighbors_via(from_loc, way_type):
                                    # Pattern 9 mirror: pre-check
                                    # Cart-over-Pass so legal_moves
                                    # doesn't surface a move that
                                    # apply_action would reject.
                                    if (way_type == "pass"
                                            and lord.assets.get("cart", 0) > 0
                                            and lord.assets.get("prov", 0) > 0):
                                        continue
                                    out.append({
                                        "type": "cmd_march",
                                        "side": active,
                                        "target_locale_id": nbr,
                                        "way_type": way_type,
                                    })
                except (ImportError, KeyError, AttributeError, FileNotFoundError):
                    # Safe: omit March moves; the agent can still
                    # cmd_pass / end_card. CROSS_PROJECT_LESSONS.md §1.
                    pass

                # cmd_supply (4.6) and cmd_tax (4.7.3) enumeration.
                # CROSS_PROJECT_LESSONS.md §1 defensive try/except.
                try:
                    from almoravid.campaign import (
                        _find_supply_routes,
                        _own_seats,
                    )
                    from almoravid.effective import is_besieged
                    if (not is_besieged(state, lord_id)
                            and lord.cylinder.kind == "locale"
                            and state.meta.actions_remaining >= 1):
                        seats = _own_seats(state, lord_id)
                        here = lord.cylinder.locale_id
                        assert here is not None
                        # Multi-hop Supply (4.6.1): enumerate every reachable
                        # Seat. Handler-mirror filter:
                        #   - at-Seat is always offered (no Transport).
                        #   - others require sufficient Cart+Mule and
                        #     an unblocked BFS route.
                        cart = lord.assets.get("cart", 0)
                        mule = lord.assets.get("mule", 0)
                        routes = _find_supply_routes(state, here, seats,
                                                     active, lord)
                        for s, route in routes.items():
                            if s == here:
                                out.append({"type": "cmd_supply",
                                            "side": active,
                                            "source_seat": s})
                            elif route is not None and len(route) <= (cart + mule):
                                out.append({"type": "cmd_supply",
                                            "side": active,
                                            "source_seat": s})
                        if here in seats:
                            out.append({"type": "cmd_tax", "side": active})
                except (ImportError, KeyError, AttributeError, FileNotFoundError):
                    pass

                # Forage (4.7.1) and Ravage (4.7.2). CROSS_PROJECT
                # _LESSONS §1: try/except wrap.
                try:
                    from almoravid.effective import (
                        has_gardens,
                        is_friendly_locale,
                    )
                    from almoravid.effective import (
                        is_besieged as _ib,
                    )
                    if (lord.cylinder.kind == "locale"
                            and state.meta.actions_remaining >= 1):
                        here = lord.cylinder.locale_id
                        assert here is not None
                        loc = state.locales[here]
                        besieged = _ib(state, lord_id)
                        gardens_path = (has_gardens(state, here)
                                        and is_friendly_locale(state, here,
                                                               active))
                        # Forage: gardens path always available if
                        # eligible; open-forage available if not Besieged
                        # and Locale Unravaged.
                        if (gardens_path
                                or (not besieged and loc.ravaged == "none")):
                            out.append({"type": "cmd_forage", "side": active})
                        # Ravage: not Besieged, Enemy Locale, not already
                        # Ravaged by us. Pattern 9 mirror against handler.
                        if not besieged:
                            color = ("yellow" if active == "christian"
                                     else "green")
                            if (not is_friendly_locale(state, here, active)
                                    and loc.ravaged != color):
                                out.append({"type": "cmd_ravage",
                                            "side": active})
                            # Siege: enemy Stronghold, marker cap not
                            # reached. Uses entire card.
                            if (loc.base_type != "region"
                                    and not is_friendly_locale(state, here,
                                                               active)):
                                cur = (loc.siege_yellow
                                       if active == "christian"
                                       else loc.siege_green)
                                if cur < 4:
                                    out.append({"type": "cmd_siege",
                                                "side": active})
                            # Battle: single-Lord against single enemy
                            # Lord at this Locale (Phase 5e baseline).
                            our_here = [
                                lord_obj.id for lord_obj in state.lords.values()
                                if lord_obj.side == active
                                and lord_obj.cylinder.kind == "locale"
                                and lord_obj.cylinder.locale_id == here
                            ]
                            enemy_here = [
                                lord_obj.id for lord_obj in state.lords.values()
                                if lord_obj.side != active
                                and lord_obj.cylinder.kind == "locale"
                                and lord_obj.cylinder.locale_id == here
                                and not _ib(state, lord_obj.id)
                            ]
                            # Deferred fix: multi-Lord battles now
                            # allowed via aggregated BattleSide.
                            if our_here and enemy_here:
                                out.append({"type": "cmd_battle",
                                            "side": active})
                            # Storm: at enemy Stronghold with our Siege.
                            if (loc.base_type != "region"
                                    and not is_friendly_locale(state, here,
                                                               active)):
                                siege_markers = (loc.siege_yellow
                                                 if active == "christian"
                                                 else loc.siege_green)
                                if siege_markers > 0:
                                    out.append({"type": "cmd_storm",
                                                "side": active})
                    # Sally: Besieged Lord with besiegers outside.
                    if _ib(state, lord_id):
                        here = lord.cylinder.locale_id
                        assert here is not None
                        besiegers = [
                            lord_obj.id for lord_obj in state.lords.values()
                            if lord_obj.side != active
                            and lord_obj.cylinder.kind == "locale"
                            and lord_obj.cylinder.locale_id == here
                            and not lord_obj.in_stronghold
                        ]
                        if besiegers:
                            out.append({"type": "cmd_sally",
                                        "side": active})
                    # Encamp (4.3.6): a Bypassing Lord (our Bypass marker
                    # here) may replace it with 1 Siege marker.
                    if (lord.cylinder.kind == "locale"
                            and state.meta.actions_remaining >= 1):
                        here = lord.cylinder.locale_id
                        assert here is not None
                        loc = state.locales[here]
                        our_bypass = (loc.bypass_yellow if active == "christian"
                                      else loc.bypass_green)
                        if our_bypass:
                            out.append({"type": "cmd_encamp", "side": active})
                    # Sortie (4.3.6): a Lord inside a Friendly Stronghold
                    # that the Enemy is Bypassing may Approach the
                    # Bypassing Enemy.
                    if (lord.cylinder.kind == "locale"
                            and lord.in_stronghold
                            and state.meta.actions_remaining >= 1):
                        here = lord.cylinder.locale_id
                        assert here is not None
                        loc = state.locales[here]
                        enemy_bypass = (loc.bypass_green if active == "christian"
                                        else loc.bypass_yellow)
                        if (loc.base_type != "region" and enemy_bypass
                                and is_friendly_locale(state, here, active)):
                            enemy_out = any(
                                lord_obj for lord_obj in state.lords.values()
                                if lord_obj.side != active
                                and lord_obj.cylinder.kind == "locale"
                                and lord_obj.cylinder.locale_id == here
                                and not lord_obj.in_stronghold)
                            if enemy_out:
                                out.append({"type": "cmd_sortie",
                                            "side": active})
                except (ImportError, KeyError, AttributeError, FileNotFoundError):
                    pass
            out.append({"type": "end_card", "side": active})
        return out

    if cstep == "end_campaign":
        out.append({"type": "end_campaign"})
        return out

    return out


def _march_response_moves(state: GameState) -> list[dict[str, Any]]:
    """Phase 6b: enumerate Avoid / Withdraw / Stand options for the
    defender owing a march_arrival_response decision.

    Pattern 9 mirror: every option pre-validates the same conditions the
    handler checks (defensive try/except per CROSS_PROJECT_LESSONS §1).
    Bias: omit a move rather than offer a phantom-legal one.
    """
    out: list[dict[str, Any]] = []
    pd = state.pending
    if pd is None:
        return out
    payload = pd.payload
    side = pd.waiting_on
    locale_id = payload.get("locale_id")
    from_locale = payload.get("from_locale_id")
    active_side = payload.get("active_side")
    if not locale_id or not active_side:
        return out

    # Stand & Fight is always available (Battle resolution is the
    # default outcome if nothing else fires).
    out.append({"type": "respond_stand_battle", "side": side})

    # Withdraw: friendly stronghold present, capacity check.
    try:
        from almoravid.effective import is_friendly_locale
        from almoravid.static_data import load_strongholds
        loc = state.locales.get(locale_id)
        if (loc is not None and loc.base_type != "region"
                and is_friendly_locale(state, locale_id, side)):
            capacity = (load_strongholds()["strongholds"][loc.base_type]
                        ["capacity"])
            already_inside = sum(
                1 for lord in state.lords.values()
                if lord.cylinder.kind == "locale"
                and lord.cylinder.locale_id == locale_id
                and lord.in_stronghold
            )
            incoming = len(payload.get("defender_lord_ids", []))
            if already_inside + incoming <= capacity:
                out.append({"type": "respond_withdraw", "side": side})
    except (ImportError, KeyError, AttributeError, FileNotFoundError):
        pass

    # Avoid Battle: enumerate adjacent locales (not from_locale, no
    # Unbesieged/Unbypassed active-side Lord present).
    # Bug Q fix (Pattern 9): omit Avoid options when any defender Lord
    # is Laden (SoP requires Unladen).
    # Bug S fix (Pattern 2 mirror): destination check matches trigger
    # by also filtering Bypassed enemy Lords.
    try:
        from almoravid.effective import is_besieged, is_bypassed
        from almoravid.map import neighbors_via
        # C5 (4.3.4): a Laden defender may DISCARD to become Unladen and
        # still Avoid, so Avoid options are always offered (the handler
        # performs the discard + Spoils transfer).
        if True:
            for way_type in ("road", "pass"):
                for nbr in neighbors_via(locale_id, way_type):
                    if nbr == from_locale:
                        continue
                    blocked = False
                    for lord in state.lords.values():
                        if (lord.side == active_side
                                and lord.cylinder.kind == "locale"
                                and lord.cylinder.locale_id == nbr
                                and not is_besieged(state, lord.id)
                                and not is_bypassed(state, lord.id)):
                            blocked = True
                            break
                    if blocked:
                        continue
                    out.append({
                        "type": "respond_avoid_battle", "side": side,
                        "target_locale_id": nbr, "way_type": way_type,
                    })
    except (ImportError, KeyError, AttributeError, FileNotFoundError):
        pass

    return out
