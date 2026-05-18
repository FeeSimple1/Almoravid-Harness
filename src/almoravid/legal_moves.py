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

    # Lifecycle: begin_levy only from setup. Levy<->Campaign transitions
    # are handled by _advance_step_if_both_done and _h_end_campaign — the
    # agent never has to explicitly invoke a phase-start handler mid-game.
    if state.meta.phase == "setup":
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
    """3.2 Pay: spend 1 Coin to shift Service marker 1 box left."""
    out: list[dict[str, Any]] = []
    for lid, lord in state.lords.items():
        if (lord.side == side
                and lord.cylinder.kind == "locale"
                and lord.assets.get("coin", 0) >= 1):
            # Must have a Service marker to shift
            if any(sm.lord_id == lid for sm in state.calendar.service_markers):
                out.append({"type": "pay_lord", "side": side, "lord_id": lid})
    return out


def _service_disband_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.3 Service / Disband: voluntary Disband of own Lords."""
    out: list[dict[str, Any]] = []
    for lid, lord in state.lords.items():
        if lord.side == side and lord.cylinder.kind == "locale":
            out.append({"type": "disband_lord", "side": side, "lord_id": lid})
    return out


def _muster_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """3.4 Muster: Lord-Muster + Lordship-spending Levy actions."""
    out: list[dict[str, Any]] = []
    for lid, lord in state.lords.items():
        if lord.side != side:
            continue
        # Path 1: Muster a Lord from Calendar
        if (lord.fealty is not None
                and lord.cylinder.kind == "calendar"):
            free = _free_seats_for(state, lid)
            for seat in free:
                out.append({"type": "muster_lord", "side": side,
                            "lord_id": lid, "seat": seat})
        # Path 2: Spend Lordship on a Mustered Lord
        if (lord.cylinder.kind == "locale"
                and lord.lordship_used < lord.lordship_rating):
            for i, v in enumerate(lord.vassals):
                if v.ready:
                    out.append({"type": "levy_take_vassal", "side": side,
                                "lord_id": lid, "vassal_index": i})
            for card_id in state.decks.board_edge.get(side, []):
                out.append({"type": "levy_take_capability", "side": side,
                            "lord_id": lid, "card_id": card_id})
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
                # Lords with cylinder on map can be planned;
                # any Lord could in principle (rule 4.1 doesn't gate on
                # location). Phase 3a offers the simplest variant:
                # offer 'pass' entry plus one command entry per Lord
                # currently on the map (most useful subset).
                out.append({"type": "plan_add_card", "side": side, "plan_kind": "pass"})
                for lid, lord in state.lords.items():
                    if lord.side == side and lord.cylinder.kind == "locale":
                        out.append({"type": "plan_add_card", "side": side,
                                    "plan_kind": "command", "lord_id": lid})
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
            # An active Lord has actions_remaining > 0.
            if state.meta.actions_remaining > 0:
                lord_id = state.meta.active_lord_id
                lord = state.lords[lord_id]
                out.append({"type": "cmd_pass", "side": active})
                # March destinations (rule 4.3) — one option per
                # adjacent locale per way_type. Pattern 4: keep way_type
                # explicit so the agent's intent is honored.
                # CROSS_PROJECT_LESSONS.md §1: defensive try/except
                # around static-data lookups in the enumerator. Bias:
                # miss a legal move (the agent can still pass) over
                # offering a phantom-legal move that the handler will
                # reject.
                try:
                    from almoravid.effective import is_besieged
                    from almoravid.map import neighbors_via
                    from almoravid.campaign import _is_laden
                    if (not is_besieged(state, lord_id)
                            and lord.cylinder.kind == "locale"):
                        cost = 2 if _is_laden(lord) else 1
                        if state.meta.actions_remaining >= cost:
                            from_loc = lord.cylinder.locale_id
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
                    from almoravid.effective import is_besieged
                    from almoravid.campaign import (
                        _find_supply_routes,
                        _own_seats,
                    )
                    if (not is_besieged(state, lord_id)
                            and lord.cylinder.kind == "locale"
                            and state.meta.actions_remaining >= 1):
                        seats = _own_seats(state, lord_id)
                        here = lord.cylinder.locale_id
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
                        has_gardens, is_besieged as _ib, is_friendly_locale,
                    )
                    if (lord.cylinder.kind == "locale"
                            and state.meta.actions_remaining >= 1):
                        here = lord.cylinder.locale_id
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
                                l.id for l in state.lords.values()
                                if l.side == active
                                and l.cylinder.kind == "locale"
                                and l.cylinder.locale_id == here
                            ]
                            enemy_here = [
                                l.id for l in state.lords.values()
                                if l.side != active
                                and l.cylinder.kind == "locale"
                                and l.cylinder.locale_id == here
                                and not _ib(state, l.id)
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
                        besiegers = [
                            l.id for l in state.lords.values()
                            if l.side != active
                            and l.cylinder.kind == "locale"
                            and l.cylinder.locale_id == here
                            and not l.in_stronghold
                        ]
                        if besiegers:
                            out.append({"type": "cmd_sally",
                                        "side": active})
                except (ImportError, KeyError, AttributeError, FileNotFoundError):
                    pass
            out.append({"type": "end_card", "side": active})
        return out

    if cstep == "end_campaign":
        out.append({"type": "end_campaign"})
        return out

    return out
