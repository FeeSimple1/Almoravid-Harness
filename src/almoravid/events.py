"""Arts of War Event resolution.

An Event is the TOP half of an AoW card. Events have these lifetimes:

  - immediate: fires once on play, then discards.
  - this_levy: remains in play until both sides finish the Levy.
  - hold (Battle scope): fires when a relevant Battle / Storm / Sally
    starts; discards at engagement end.
  - hold (Campaign scope): fires when the qualifying condition occurs
    during the Campaign; discards at end of Campaign.

Per Pattern 10 from FUTURE_PROJECTS_LESSONS.md (SMOKE-112/113/114 in
Nevsky): if an immediate event has no rule-valid target — for example,
'shift this Service marker right by 1' with no eligible marker — the
resolver MUST treat it as a no-op (discard with no effect), NOT raise.
The agent had no way to know targets were unavailable at the time it
queued the event; making it unresolvable strands the harness.

This file is the resolver registry + a handful of representative
resolvers. The combat-tied events (Hills, Camp Attack, Spear Wall,
Cantador, etc.) are stubbed and surface as no-op-with-warning until
Phase 5 wires Battle resolution. Each stub records its presence in
state so the eventual Battle code can find them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from almoravid.state import GameState, PendingDecision, Side
from almoravid.static_data import load_cards

# (state, side, card_id, payload) -> result dict
ResolverFn = Callable[[GameState, Side, str, dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class EventNotResolvable(ValueError):
    """Card's event has no resolver registered AND no default behavior fits.

    Distinct from IllegalAction — this is a developer error, not a
    rules failure. Resolvers should be registered for every card with
    an event half before the agent tries to play it.
    """

    def __init__(self, card_id: str) -> None:
        super().__init__(
            f"No resolver for event {card_id}. Either register one in "
            f"events.py or mark the card no_event=true in cards.json."
        )


def _is_levy_event(card_id: str) -> bool:
    return load_cards()["cards"].get(card_id, {}).get("event_persistence") == "this_levy"


def discard_levy_events(state: GameState) -> None:
    """3.5.3: discard continuing Events, preserving legacy Holds in the bucket."""
    for side, cards in list(state.decks.this_levy_events.items()):
        for card_id in dict.fromkeys(cards):
            if _is_levy_event(card_id) and card_id not in state.decks.discard:
                state.decks.discard.append(card_id)
        remaining = [card_id for card_id in cards if not _is_levy_event(card_id)]
        if remaining:
            state.decks.this_levy_events[side] = remaining
        else:
            state.decks.this_levy_events.pop(side)


def restore_legacy_levy_events(state: GameState) -> None:
    """Recover continuing cards sent to discard by older Levy saves."""
    if state.meta.phase != "levy":
        return
    discarded = {cid for cid in state.decks.discard if _is_levy_event(cid)}
    if not discarded:
        return
    for entry in reversed(state.history):
        if entry.turn_index != state.meta.turn_index or entry.action == "begin_levy":
            break
        if entry.action != "aow_implement_event" or entry.actor == "system":
            continue
        card_id = entry.args.get("card_id")
        if card_id is None:
            # The implementation action allows the queued card id to be omitted.
            card_id = entry.summary.removesuffix(" (3.1.3)").rsplit(" ", 1)[-1]
        if not isinstance(card_id, str) or card_id not in discarded:
            continue
        if load_cards()["cards"][card_id]["side"] != entry.actor:
            continue
        state.decks.discard = [cid for cid in state.decks.discard if cid != card_id]
        cards = state.decks.this_levy_events.setdefault(entry.actor, [])
        if card_id not in cards:
            cards.append(card_id)
        discarded.remove(card_id)


def _no_op_with_note(state: GameState, card_id: str, side: Side, note: str) -> dict[str, Any]:
    """Pattern 10: discard with no effect when no valid target.

    Records the no-op in history so audits can find it; the card moves
    to discard so it doesn't loop back.
    """
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "no_op": True, "note": note}


def _move_to_hold_bucket(state: GameState, card_id: str, side: Side, bucket: str) -> dict[str, Any]:
    """Place a hold event in its persistence bucket (Pattern 13)."""
    if bucket == "this_levy_events":
        state.decks.this_levy_events.setdefault(side, []).append(card_id)
    elif bucket == "this_campaign_events":
        state.decks.this_campaign_events.setdefault(side, []).append(card_id)
    else:
        raise ValueError(f"Unknown hold bucket: {bucket}")
    return {"card_id": card_id, "side": side, "held": bucket}


def held_event_ids(state: GameState, side: Side) -> list[str]:
    """Unspent Events, including legacy saves' event buckets (3.1.3).

    New draws use ``held``. The other buckets remain readable for saved
    games and for combat effects already placed in play by a resolver.
    """
    return list(dict.fromkeys(
        state.decks.held.get(side, [])
        + [card for card in state.decks.this_levy_events.get(side, [])
           if not _is_levy_event(card)]
        + state.decks.this_campaign_events.get(side, [])))


def has_held_event(state: GameState, side: Side, card_id: str) -> bool:
    return card_id in held_event_ids(state, side)


def consume_held_event(state: GameState, side: Side, card_id: str) -> None:
    """Remove a played Event from every compatible holding location.

    The effect's caller owns the discard/in-play destination. Removing
    duplicates also repairs old saves without letting a card play twice.
    """
    for bucket in (state.decks.held, state.decks.this_levy_events,
                   state.decks.this_campaign_events):
        cards = bucket.get(side, [])
        cards[:] = [card for card in cards if card != card_id]


def hold_drawn_event(state: GameState, side: Side, card_id: str) -> dict[str, Any]:
    """3.1.3: a drawn Hold is kept hidden; drawing never plays its effect."""
    consume_held_event(state, side, card_id)
    state.decks.held.setdefault(side, []).append(card_id)
    return {"card_id": card_id, "side": side, "held": "held"}


# Holds with unrestricted timing or a Muster window. Reactive Holds use
# their existing Battle/March/Surrender/Call-to-Arms consumer actions.
_DIRECT_HOLDS = {"C18", "C20", "M8", "M9", "M10", "M12", "M15",
                 "M18", "M20", "M21"}


def play_held_event(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Play an owned, previously drawn Hold at its printed time (3.1.3)."""
    from almoravid.actions import (
        _record,
        _require,
        _require_active,
        _require_levy_step,
        _require_side,
    )
    side = _require_side(action)
    card_id = action.get("card_id")
    _require(card_id in _DIRECT_HOLDS,
             "this Event uses its specific response/play action", code="bad_card")
    _require(load_cards()["cards"][card_id]["side"] == side,
             "Event belongs to the other side", code="wrong_side")
    _require(has_held_event(state, side, card_id),
             f"{card_id} is not held", code="card_not_held")
    _require(state.meta.phase in ("levy", "campaign"),
             "Events can be played during Levy or Campaign", code="bad_phase")
    _require(state.pending is None, "resolve the pending decision first",
             code="pending_decision")
    _require_active(state, side)
    payload = dict(action.get("payload") or {})
    if card_id in ("C18", "M18"):
        _require_levy_step(state, "muster")
    if card_id == "M12" and payload.get("mode") == "lordship":
        _require_levy_step(state, "muster")
        from almoravid.campaign import _muster_cap_lord_eligible
        lid = payload.get("lord_id")
        _require(isinstance(lid, str) and lid in state.lords and state.lords[lid].is_taifa
                 and _muster_cap_lord_eligible(state, lid, side),
                 "Lordship requires an eligible Taifa Lord in Muster",
                 code="not_eligible")
    # Leave the held card untouched if resolver validation rejects play.
    result = resolve_event(state, side, card_id, payload)
    consume_held_event(state, side, card_id)
    _record(state, action, f"{side} plays held Event {card_id} (3.1.3)")
    return result


def held_event_moves(state: GameState, side: Side) -> list[dict[str, Any]]:
    """Expose direct Holds, including scenario setup cards (3.1.3)."""
    from itertools import combinations

    from almoravid.campaign import _muster_cap_lord_eligible
    if state.meta.phase not in ("levy", "campaign") or state.pending is not None:
        return []
    moves: list[dict[str, Any]] = []
    muster = state.meta.phase == "levy" and state.meta.levy_step == "muster"
    for card_id in held_event_ids(state, side):
        if card_id not in _DIRECT_HOLDS:
            continue
        move = {"type": "play_event", "side": side, "card_id": card_id}
        if card_id in ("C18", "M18"):
            if muster:
                for transport in ("cart", "mule"):
                    moves.append({**move, "payload": {"transport": transport}})
        elif card_id == "C20":
            for selected in al_qadir_choices(state):
                moves.append({**move, "payload": {"locale_ids": selected}})
        elif card_id == "M12":
            targets = _taifa_marriage_targets(state)
            for count in (1, 2):
                for selected in combinations(targets, count):
                    moves.append({**move, "payload": {"lord_ids": list(selected)}})
            if muster:
                for lid in targets:
                    if _muster_cap_lord_eligible(state, lid, side):
                        moves.append({**move, "payload": {"mode": "lordship",
                                                         "lord_id": lid}})
        else:
            moves.append(move)
            if card_id == "M21":
                from almoravid.actions import _free_seats_for
                for lid, lord in state.lords.items():
                    if (lord.side == side and lord.is_taifa
                            and lord.cylinder.kind == "calendar"
                            and lid not in state.meta.muster_banned_this_levy_lord_ids
                            and _free_seats_for(state, lid)):
                        moves.append({**move, "payload": {"lord_id": lid}})
    return moves


# ---------------------------------------------------------------------------
# Resolver registry
# ---------------------------------------------------------------------------


_RESOLVERS: dict[str, ResolverFn] = {}


def register(card_id: str) -> Callable[[ResolverFn], ResolverFn]:
    def deco(fn: ResolverFn) -> ResolverFn:
        _RESOLVERS[card_id] = fn
        return fn
    return deco


def resolve_event(
    state: GameState,
    side: Side,
    card_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve an event card's top half for `side`.

    Validates the card has an event half. Routes to the registered
    resolver. If none is registered, raises EventNotResolvable (a
    developer signal — not the agent's fault).
    """
    cards = load_cards()["cards"]
    rec = cards.get(card_id)
    if rec is None:
        raise EventNotResolvable(card_id)
    if rec.get("no_event"):
        # Cards without events should never enter this path; the dispatcher
        # in actions.py / campaign.py won't route them here. Treat as no-op
        # if it happens (Pattern 10).
        return _no_op_with_note(state, card_id, side,
                                "card has no event half")
    resolver = _RESOLVERS.get(card_id)
    if resolver is None:
        raise EventNotResolvable(card_id)
    result = resolver(state, side, card_id, payload or {})
    if _is_levy_event(card_id):
        state.decks.this_levy_events.setdefault(side, []).append(card_id)
    return result


# ---------------------------------------------------------------------------
# Battle-context hold events — Phase 4b stubs.
# Combat resolution is Phase 5; these stubs place the card in the
# this_levy_events bucket so the Phase 5 Battle resolver can find them.
# ---------------------------------------------------------------------------


@register("C1")  # Hills (Christian)
@register("M1")  # Hills (Muslim)
def _hills(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Hold-event Hills: Defending side, Slingers x1.5, other Missiles
    x1 (not x1/2). Combat hook in Phase 5; here we just persist it.
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C3")
@register("M3")
def _swollen_river(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Hold-event Swollen River: affects movement / battle terrain.
    Phase 5 hooks into March / Battle eligibility."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C4")  # Arid Terrain
@register("M4")
def _arid_terrain(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Hold-event: triggers when enemy Marches (Phase 6h hook in
    _h_cmd_march). Buffered in this_levy_events until that fires."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C5")  # Drought
@register("M5")  # Drought
def _drought(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Begin Drought, with the affected side choosing its eligible Lords (C5/M5)."""
    from almoravid.actions import _other, _require
    from almoravid.capabilities import side_has_capability
    from almoravid.effective import has_gardens, is_friendly_locale

    _require(not payload, "the affected side chooses how to resolve Drought",
             code="bad_drought_choice")
    _require(state.pending is None, "finish the pending decision before Drought",
             code="pending_decision")
    target_side = _other(side)
    candidates: list[str] = []
    for lord in state.lords.values():
        if lord.side != target_side or lord.cylinder.kind != "locale":
            continue
        loc_id = lord.cylinder.locale_id
        assert loc_id is not None
        locale = state.locales[loc_id]
        has_seat = bool(locale.printed_seat_lord_ids or locale.seat_marker_lord_ids)
        if (has_seat or has_gardens(state, loc_id)) and is_friendly_locale(
                state, loc_id, target_side):
            continue
        candidates.append(lord.id)
    if not candidates:
        return _no_op_with_note(state, card_id, side,
                                f"no eligible {target_side} Lord to Feed")
    candidates.sort()
    context = {"card_id": card_id, "side": side, "target_side": target_side,
               "resume_active": state.meta.active_player}
    can_cancel = target_side == "muslim" and side_has_capability(state, "muslim", "M16")
    if len(candidates) > 2 or can_cancel:
        return _drought_prompt(
            state, context, "targets", eligible_lord_ids=candidates,
            required=min(2, len(candidates)), can_discard_camels=can_cancel)
    return _drought_feed(state, context, candidates)


def _drought_prompt(state: GameState, context: dict[str, Any], step: str,
                    **options: Any) -> dict[str, Any]:
    side = context["target_side"]
    state.pending = PendingDecision(
        kind="drought_choice", waiting_on=side, payload={**context, "step": step, **options})
    state.meta.active_player = side
    return {"card_id": context["card_id"], "side": context["side"], "target_side": side,
            "pending": "drought_choice", "waiting_on": side, "step": step}


def _finish_drought(state: GameState, context: dict[str, Any],
                    fed: list[dict[str, Any]]) -> dict[str, Any]:
    card_id = context["card_id"]
    state.decks.discard.append(card_id)
    state.pending = None
    state.meta.active_player = context["resume_active"]
    return {"card_id": card_id, "side": context["side"], "target_side": context["target_side"],
            "fed_lords": fed}


def _drought_feed(state: GameState, context: dict[str, Any], lord_ids: list[str], *,
                  discard_lords: list[str] | None = None,
                  feed_loot: dict[str, int] | None = None) -> dict[str, Any]:
    from almoravid.campaign import _forced_feed_lords, _immediate_feed_options

    if feed_loot is None:
        options = _immediate_feed_options(state, context["target_side"], lord_ids, discard_lords)
        if options:
            return _drought_prompt(state, context, lord_ids=lord_ids, **options)
    fed = _forced_feed_lords(state, lord_ids, discard_mules_lords=set(discard_lords or []),
                             feed_loot=feed_loot)
    return _finish_drought(state, context, fed)


def resolve_drought_choice(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Resolve the affected owner's target, Greed, or resource election."""
    from almoravid.actions import _record, _require, _require_side
    from almoravid.campaign import _feed_loot_election, _require_pending
    from almoravid.capabilities import discard_capability, side_has_capability

    side = _require_side(action)
    payload = _require_pending(state, "drought_choice", side).payload
    context = {key: payload[key] for key in ("card_id", "side", "target_side", "resume_active")}
    step = payload["step"]
    fields = {"targets": {"lord_ids", "discard_camels"}, "greed": {"discard_lords"},
              "feed": {"feed_loot"}}[step]
    _require(set(action) <= {"type", "side"} | fields,
             f"choose only the current Drought {step} options", code="bad_drought_choice")
    if step == "targets":
        cancel = action.get("discard_camels", False)
        _require(type(cancel) is bool, "discard_camels must be true or false",
                 code="bad_drought_choice")
        if cancel:
            _require(payload["can_discard_camels"] and side_has_capability(state, side, "M16")
                     and "lord_ids" not in action,
                     "cancel Drought with Camels or choose Lords to Feed",
                     code="bad_drought_choice")
            discard_capability(state, "M16")
            result = {**_finish_drought(state, context, []), "camels_negated": True}
        else:
            ids = action.get("lord_ids")
            _require(isinstance(ids, list) and len(ids) == payload["required"]
                     and all(isinstance(lid, str) and lid in payload["eligible_lord_ids"]
                             for lid in ids) and len(set(ids)) == len(ids),
                     f"choose {payload['required']} distinct eligible Lords for Drought",
                     code="bad_drought_choice")
            result = _drought_feed(state, context, cast(list[str], ids))
    elif step == "greed":
        discards = action.get("discard_lords", [])
        eligible = {row["lord_id"] for row in payload["eligible"]}
        _require(isinstance(discards, list)
                 and all(isinstance(lid, str) and lid in eligible for lid in discards)
                 and len(set(discards)) == len(discards),
                 "choose distinct Drought Lords eligible to discard excess Mules",
                 code="bad_drought_choice")
        result = _drought_feed(state, context, payload["lord_ids"], discard_lords=discards)
    else:
        options = {lid: tuple(bounds) for lid, bounds in payload["feed_options"].items()}
        feed_loot = _feed_loot_election(action.get("feed_loot", {}), options)
        result = _drought_feed(state, context, payload["lord_ids"],
                               discard_lords=payload["discard_lords"], feed_loot=feed_loot)
    _record(state, action, f"{side} resolves Drought {step} ({context['card_id']})")
    return result


@register("C7")  # Baggage Parapet
@register("M7")  # Spear Wall
def _baggage_or_spear(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Hold-event battle bonuses. Phase 5 combat hook."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C8")  # Cantador
def _cantador(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Hold-event: Knights and Sergeants +1 Hit Round 1 Melee. Phase 5 combat hook."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C9")  # Betrayal of Terms
def _c9_betrayal_of_terms(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C9 (Hold): Play upon Surrender to take Spoils as if Sack, OR
    take double and Muslims add 1 Jihad. Phase 6i: parked in
    this_levy_events; consumed by the Surrender hook in _h_cmd_siege.
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


# ---------------------------------------------------------------------------
# Pure no-op-with-history events (rare; for cards whose only effect is
# being held until a later trigger event resolves them).
# ---------------------------------------------------------------------------


@register("C2")  # Camp Attack — immediate, fires at start of next Battle
@register("M2")
@register("C6")  # Surprise — immediate
def _battle_immediate_marker(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Cards whose effect manifests in a specific Battle moment.
    Buffered in this_campaign_events; Phase 5 Battle code will fish
    them out at the right moment."""
    return _move_to_hold_bucket(state, card_id, side, "this_campaign_events")


@register("M6")  # Feigned Retreat — one-Round battle Hold
def _feigned_retreat(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M6 Feigned Retreat reorders Round 2 Melee. Like the other
    one-Round battle Holds (C8 Cantador, M7 Spear Wall) it lives in
    this_levy_events — the bucket the Battle/Sally Round-2 readers and
    _discard_round1_events actually consult (4.4.1 Events)."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


# ---------------------------------------------------------------------------
# Immediate events that adjust state directly. Useful for Phase 4
# testing because no combat is required.
# ---------------------------------------------------------------------------


def _taifa_marriage_targets(state: GameState) -> list[str]:
    """Taifa Muslims with a Calendar cylinder or a Service marker to shift."""
    service_lords = {m.lord_id for m in state.calendar.service_markers if m.vassal_id is None}
    service_lords.update(state.calendar.off_left_service)
    return [lid for lid, lord in state.lords.items()
            if lord.is_taifa and lord.side == "muslim"
            and ((lord.cylinder.kind == "calendar" and lord.cylinder.box is not None)
                 or (lord.cylinder.kind == "locale" and lid in service_lords))]


@register("M12")  # Taifa Marriage
def _m12_taifa_marriage(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M12 (Hold): shift up to 2 Taifa Lords' cylinder LEFT if on
    Calendar, or Service RIGHT if Lord is on the map. OR one Lord
    uses Lordship +2.

    An omitted `lord_ids` defaults to the first two eligible Lords by ID.
    Explicit elections must name one or two distinct eligible Lords.
    """
    from almoravid.actions import _require, _shift_service_right

    # Lordship +2 branch: payload['mode']=='lordship', one Lord.
    if payload.get("mode") == "lordship":
        taifa_lord_ids = [lid for lid, lord in state.lords.items()
                          if lord.is_taifa and lord.side == "muslim"]
        lid = payload.get("lord_id")
        if lid not in taifa_lord_ids:
            lid = sorted(taifa_lord_ids)[0] if taifa_lord_ids else None
        if lid is None:
            return _no_op_with_note(state, card_id, side,
                                    "no Taifa Lord for Lordship")
        from almoravid.campaign import _grant_event_lordship
        _grant_event_lordship(state, lid, "muslim")
        state.decks.discard.append(card_id)
        return {"card_id": card_id, "side": side,
                "lordship_plus_2": lid,
                "lordship_rating_now": state.lords[lid].lordship_rating
                + state.lords[lid].lordship_bonus_this_levy}
    eligible = _taifa_marriage_targets(state)
    if "lord_ids" in payload:
        chosen = payload["lord_ids"]
        _require(isinstance(chosen, list) and 1 <= len(chosen) <= 2
                 and all(isinstance(lid, str) for lid in chosen)
                 and len(set(chosen)) == len(chosen),
                 "Taifa Marriage requires one or two distinct Lord IDs", code="bad_arg")
        _require(all(lid in eligible for lid in chosen),
                 "Taifa Marriage targets must be Taifa Muslims with a cylinder or Service marker "
                 "on the Calendar", code="not_eligible")
    else:
        chosen = sorted(eligible)[:2]
    if not chosen:
        return _no_op_with_note(state, card_id, side,
                                "no Taifa Lord eligible")
    shifted = []
    for lid in chosen:
        cylinder = state.lords[lid].cylinder
        if cylinder.kind == "calendar":
            assert cylinder.box is not None
            cylinder.box = max(0, cylinder.box - 1)
            if lid in state.calendar.off_right:
                state.calendar.off_right.remove(lid)
            if cylinder.box == 0 and lid not in state.calendar.off_left:
                state.calendar.off_left.append(lid)
            shifted.append({"lord_id": lid, "shifted": "cylinder_left",
                            "new_cylinder_box": cylinder.box})
        else:
            new_box = _shift_service_right(state, lid)
            shifted.append({"lord_id": lid, "shifted": "service_right",
                            "new_service_box": new_box})
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "shifted": shifted}



def _devaluation_groups(state: GameState, card_id: str) -> dict[str, dict[str, int]]:
    if card_id == "C10":
        sources = {"taifa_box": state.taifas_box_coin} if state.taifas_box_coin else {}
        sources.update({lord.id: lord.assets["coin"]
                        for lord in state.lords.values()
                        if lord.side == "muslim" and lord.assets.get("coin", 0) > 0})
        return {"muslim": sources} if sources else {}

    groups: dict[str, dict[str, int]] = {}
    for lord in state.lords.values():
        if (lord.side == "christian" and lord.cylinder.kind == "locale"
                and lord.assets.get("coin", 0) > 0):
            assert lord.cylinder.locale_id is not None
            groups.setdefault(lord.cylinder.locale_id, {})[lord.id] = lord.assets["coin"]
    return groups


@register("C10")
@register("M14")
def _devaluation(state: GameState, side: Side, card_id: str,
                 payload: dict[str, Any]) -> dict[str, Any]:
    """The affected side allocates the mandatory Coin loss (C10/M14)."""
    from almoravid.actions import _other, _require

    _require(not payload, "the affected side chooses the Devaluation allocation",
             code="bad_devaluation_choice")
    _require(state.pending is None, "finish the pending decision before Devaluation",
             code="pending_decision")
    groups = _devaluation_groups(state, card_id)
    divisor = 3 if card_id == "C10" else 2
    context = {
        "card_id": card_id,
        "side": side,
        "target_side": _other(side),
        "resume_active": state.meta.active_player,
        "groups": groups,
        "required": {group: sum(sources.values()) // divisor
                     for group, sources in groups.items()},
    }
    return _continue_devaluation(state, context, {})


def _continue_devaluation(state: GameState, context: dict[str, Any],
                          selected: dict[str, int]) -> dict[str, Any]:
    """Resolve forced amounts and offer the full feasible range at each choice."""
    for group, sources in context["groups"].items():
        remaining = context["required"][group] - sum(selected.get(lid, 0) for lid in sources)
        available = sum(coin for lid, coin in sources.items() if lid not in selected)
        for source, coin in sources.items():
            if source in selected:
                continue
            available -= coin
            minimum = max(0, remaining - available)
            maximum = min(coin, remaining)
            if minimum != maximum:
                return _devaluation_prompt(
                    state, context, selected, {"source": source, "min": minimum, "max": maximum})
            selected[source] = minimum
            remaining -= minimum
    # A private response is always owed with Hidden Mats, so the drawer
    # cannot infer whether the opponent's allocation was forced or empty.
    if state.meta.hidden_mats and state.pending is None:
        return _devaluation_prompt(state, context, selected, None)
    return _finish_devaluation(state, context, selected)


def _devaluation_prompt(state: GameState, context: dict[str, Any], selected: dict[str, int],
                        choice: dict[str, Any] | None) -> dict[str, Any]:
    side = context["target_side"]
    state.pending = PendingDecision(
        kind="devaluation_choice", waiting_on=side,
        payload={**context, "selected": selected, "choice": choice})
    state.meta.active_player = side
    return {"card_id": context["card_id"], "pending": "devaluation_choice", "waiting_on": side}


def _finish_devaluation(state: GameState, context: dict[str, Any],
                        allocation: dict[str, int]) -> dict[str, Any]:
    for source, amount in allocation.items():
        if not amount:
            continue
        if source == "taifa_box":
            state.taifas_box_coin -= amount
        else:
            assets = state.lords[source].assets
            assets["coin"] -= amount
            if assets["coin"] == 0:
                assets.pop("coin")
    card_id = context["card_id"]
    state.pending = None
    state.meta.active_player = context["resume_active"]
    if not context["groups"]:
        return _no_op_with_note(state, card_id, context["side"], "no Coin to devalue")
    state.decks.discard.append(card_id)
    result = {"card_id": card_id, "side": context["side"]}
    removed = sum(allocation.values())
    if card_id == "C10":
        before = sum(context["groups"]["muslim"].values())
        return {**result, "coin_before": before, "coin_after": before - removed, "removed": removed}
    return {**result, "locales_affected": list(context["groups"]), "total_removed": removed}


def resolve_devaluation_choice(state: GameState, action: dict[str, Any]) -> dict[str, Any]:
    """Choose Coin from the current source or submit the complete allocation."""
    from almoravid.actions import _record, _require, _require_side
    from almoravid.campaign import _require_pending

    side = _require_side(action)
    payload = _require_pending(state, "devaluation_choice", side).payload
    context = {key: value for key, value in payload.items() if key not in {"selected", "choice"}}
    selected = payload["selected"].copy()
    fields = action.keys() - {"type", "side"}
    if fields == {"coin_by_source"}:
        allocation = action["coin_by_source"]
        sources = {lid: coin for group in context["groups"].values()
                   for lid, coin in group.items()}
        _require(isinstance(allocation, dict) and all(
            lid in sources and type(coin) is int and 0 <= coin <= sources[lid]
            for lid, coin in allocation.items()),
            "choose only available Coin from eligible sources", code="bad_devaluation_choice")
        _require(all(allocation.get(lid, 0) == coin for lid, coin in selected.items())
                 and all(sum(allocation.get(lid, 0) for lid in group) == context["required"][key]
                         for key, group in context["groups"].items()),
                 "allocate the exact required loss for each group and keep earlier choices",
                 code="bad_devaluation_choice")
        result = _finish_devaluation(state, context, allocation)
    else:
        choice = payload["choice"]
        coin = action.get("coin")
        _require(choice is not None and fields == {"source", "coin"}
                 and action["source"] == choice["source"]
                 and type(coin) is int and choice["min"] <= coin <= choice["max"],
                 "choose an offered Coin amount for the current source",
                 code="bad_devaluation_choice")
        selected[choice["source"]] = coin
        result = _continue_devaluation(state, context, selected)
    _record(state, action, f"{side} allocates Coin for Devaluation ({context['card_id']})")
    return result

# ---------------------------------------------------------------------------
# Catch-all: a registry coverage helper for the test suite
# ---------------------------------------------------------------------------


def registered_cards() -> set[str]:
    """All card_ids with a resolver — useful for Phase 5 coverage tests."""
    return set(_RESOLVERS.keys())


def unresolved_event_cards() -> list[str]:
    """All card_ids that HAVE an event half but no resolver yet.

    Phase 5+ will whittle this list to []. Used as the canonical 'what's
    left to wire' inventory.
    """
    cards = load_cards()["cards"]
    out = []
    for cid, c in cards.items():
        if not c.get("no_event") and cid not in _RESOLVERS:
            out.append(cid)
    return sorted(out)



# ===========================================================================
# Phase 5j: structural resolvers for the remaining event halves.
# Each card here has a known effect per the AoW Reference; Phase 5j ships
# the dispatch + Pattern 10 no-op-on-missing-target check + deferred-marker
# bucket placement. Detailed per-card mechanics (specific Service shifts,
# specific marker placements, VP adjustments beyond the standard 1/2 VP
# per marker) land in later commits as the agent exercises each.
# ===========================================================================


# --- Hold events affecting Battle / Storm / Sally (this_levy bucket) ---
# These cards persist through Battle resolution; Phase 5 Battle code
# (battle.py) can consult state.decks.this_levy_events to apply effects.

def _remove_count_units(state: GameState, card: str) -> dict[str, Any] | None:
    """Remove the units a Count-of-Barcelona capability (C13/M23) granted,
    recorded in meta.aow_cap_state[f'{card}_units'] (Pattern 8 discard)."""
    rec = state.meta.aow_cap_state.pop(f"{card}_units", None)
    state.meta.aow_cap_state.pop(f"{card}_used", None)
    side = "christian" if card == "C13" else "muslim"
    if rec and state.meta.count_of_barcelona_side == side:
        state.meta.count_of_barcelona_side = None
    if not rec:
        return None
    lord = state.lords.get(rec.get("lord"))
    if lord is None:
        return None
    for ut in ("knights", "men_at_arms"):
        n = rec.get(ut, 0)
        if n:
            lord.forces[ut] = max(0, lord.forces.get(ut, 0) - n)
    return cast(dict[str, Any], rec)


def _discard_count_capability(state: GameState, card: str) -> dict[str, Any] | None:
    """C13/M23: discard the opposing Count card and its recorded contingent."""
    removed = state.meta.aow_cap_state.get(f"{card}_units")
    from almoravid.capabilities import discard_capability
    discard_capability(state, card)
    state.meta.count_of_barcelona_side = None
    return removed


def _berenguer_ramon(state: GameState, side: Side, card_id: str,
                      payload: dict[str, Any]) -> dict[str, Any]:
    """C13/M23 printed Event + Tips: optional immediate Levy for one Asset.

    This is a paid This-Lord Capability, with exactly the same tracked
    contingent as its Muster action. Sharing (1.5.2) and Taifas Coin
    (1.3.3) apply; target/payment choices may be supplied in the payload.
    """
    from almoravid.actions import _check_this_lord_cap_limits, _require
    from almoravid.campaign import _muster_cap_lord_eligible
    from almoravid.state import CardInPlay
    enemy = "muslim" if side == "christian" else "christian"
    other_card = "M23" if side == "christian" else "C13"
    if state.meta.count_of_barcelona_side == enemy:
        removed = _discard_count_capability(state, other_card)
        state.decks.discard.append(card_id)
        return {"card_id": card_id, "side": side, "discarded": True,
                "removed_units": removed, "reason": f"Count of Barcelona with {enemy}"}
    target = payload.get("target_lord_id") or payload.get("lord_id")
    if not target or payload.get("decline"):
        return _no_op_with_note(state, card_id, side, "optional Count Levy declined")
    eligible = ("sancho", "eudes") if side == "christian" else ("al_mustain", "al_mundir")
    _require(target in eligible and _muster_cap_lord_eligible(state, target, side),
             "Count requires an eligible Lord at a Friendly Locale free of Siege",
             code="not_eligible")
    lord = state.lords[target]
    _check_this_lord_cap_limits(lord, card_id)
    asset = payload.get("asset", "coin")
    _require(asset in ("coin", "loot", "prov", "mule", "cart", "taifa_coin"),
             "choose one Asset to pay for Count", code="bad_arg")
    payer_id = payload.get("payer_lord_id", target)
    if asset == "taifa_coin":
        _require(side == "muslim", "only Muslims spend Taifas Coin", code="wrong_side")
        if state.taifas_box_coin < 1:
            return _no_op_with_note(state, card_id, side, "no Asset to pay for Count")
    else:
        payer = state.lords.get(payer_id)
        _require(payer is not None and payer.side == side
                 and payer.cylinder.kind == "locale"
                 and payer.cylinder.locale_id == lord.cylinder.locale_id,
                 "Asset payer must share the target's Locale", code="bad_payer")
        assert payer is not None
        if payer.assets.get(asset, 0) < 1:
            return _no_op_with_note(state, card_id, side, "no Asset to pay for Count")
    # Validation precedes all changes, including payment and card placement.
    if asset == "taifa_coin":
        state.taifas_box_coin -= 1
    else:
        assert payer is not None
        payer.assets[asset] -= 1
        if payer.assets[asset] == 0:
            payer.assets.pop(asset)
    lord.capabilities.append(card_id)
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id=card_id, scope="this_lord", owner_side=side, owner_lord_id=target))
    state.decks.draw = [c for c in state.decks.draw if c != card_id]
    state.decks.discard = [c for c in state.decks.discard if c != card_id]
    for unit in ("knights", "men_at_arms"):
        lord.forces[unit] = lord.forces.get(unit, 0) + 2
    state.meta.count_of_barcelona_side = side
    state.meta.aow_cap_state[f"{card_id}_used"] = True
    state.meta.aow_cap_state[f"{card_id}_units"] = {
        "lord": target, "knights": 2, "men_at_arms": 2}
    return {"card_id": card_id, "side": side, "target": target,
            "knights_added": 2, "men_at_arms_added": 2, "asset_paid": True,
            "capability_levied": True, "asset": asset, "payer_lord_id": payer_id}


@register("C13")
@register("M23")
def _count_event(state: GameState, side: Side, card_id: str,
                 payload: dict[str, Any]) -> dict[str, Any]:
    return _berenguer_ramon(state, side, card_id, payload)


# --- Immediate events with side-wide state effects ---


@register("C11")  # Indulgences
@register("C12")  # Song of Roland
def _crusader_event(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C11 Indulgences / C12 Song of Roland: Place 1 Crusader marker
    on an Unbesieged Christian Lord with 2 Knights attached (modeled
    by incrementing lord.crusader_markers + adding 2 Knights to forces).

    Phase 6i: Eudes-Muster-all-Ready-Vassals clause only fires if
    Eudes is on the map AND has Ready Vassals. We auto-Muster any
    Ready Vassals of Eudes (3.4.2 ARTS OF WAR) when triggered.
    """
    from almoravid.actions import _muster_vassal_forces
    from almoravid.effective import is_besieged
    target_lord_id = payload.get("target_lord_id")
    available_christians = [
        lord.id for lord in state.lords.values()
        if lord.side == "christian"
        and lord.cylinder.kind == "locale"
        and not is_besieged(state, lord.id)
    ]
    if not available_christians:
        return _no_op_with_note(state, card_id, side,
                                "no unbesieged Christian Lord available")
    if target_lord_id and target_lord_id not in available_christians:
        return _no_op_with_note(state, card_id, side,
                                f"target {target_lord_id} not eligible")
    target = target_lord_id or available_christians[0]
    target_lord = state.lords[target]
    target_lord.crusader_markers += 1
    target_lord.forces["knights"] = target_lord.forces.get("knights", 0) + 2

    # Eudes Muster-Ready-Vassals clause.
    eudes_mustered: list[str] = []
    eudes = state.lords.get("eudes")
    if (eudes is not None and eudes.cylinder.kind == "locale"
            and not is_besieged(state, "eudes")):
        for v in eudes.vassals:
            if not v.available_to_muster or v.id in eudes.removed_vassal_ids:
                continue
            _muster_vassal_forces(state, eudes, v)
            eudes_mustered.append(v.id)

    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "target": target,
            "crusader_markers_now": target_lord.crusader_markers,
            "knights_added": 2,
            "eudes_vassals_mustered": eudes_mustered}


@register("C14")  # Pope Gregory
def _pope_gregory(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Pope Gregory: hold-event eligibility on Sancho (Pope Gregory cap).
    Phase 5j: held in this_levy_events; resolver hook for Sancho's
    capability bonus."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C15")  # Cluniacs
def _religious_hold(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C15 Cluniacs (Hold): Lord Muster from Calendar, OR Service +1
    right, OR Lordship +2 for this Levy. Phase 6j: parks in
    this_levy_events; consumed by ad-hoc Levy action (TODO)."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


# --- Rodrigo (El Cid) family ---


@register("C25")  # De Vivar
def _c25_de_vivar(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C25 (Hold): Play as Christian Call to Arms if Rodrigo al-Sayyid
    on map. Reconcile with Rodrigo for 1 VP to Taifas box.

    Parks in this_levy_events; the Reconcile + 1 VP to the Taifas box is
    carried out by the play handler campaign._h_play_de_vivar_reconcile.
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("M25")
@register("M26")
def _m25_m26_freebooter(state: GameState, side: Side, card_id: str,
                        payload: dict[str, Any]) -> dict[str, Any]:
    """M25/M26: Disband yellow Rodrigo at Limit, then optional conversion.

    The card's Tips allow conversion from ANY Calendar position, however
    reached. Full 3.3.2 cleanup is shared with ordinary Disband.
    """
    from almoravid.actions import _h_disband_lord
    from almoravid.state import Cylinder
    target = "rodrigo_campeador"
    lord = state.lords.get(target)
    if lord is None:
        return _no_op_with_note(state, card_id, side, "Rodrigo not in scenario")
    disbanded = lord.cylinder.kind == "locale"
    if disbanded:
        _h_disband_lord(state, {"type": "disband_lord", "side": "christian",
                               "lord_id": target, "auto_service_disband": True,
                               "force_at_service_limit": True})
    swapped = False
    box = lord.cylinder.box if lord.cylinder.kind == "calendar" else None
    sayyid = state.lords.get("rodrigo_al_sayyid")
    if (payload.get("swap_to_al_sayyid") and box is not None
            and state.taifas_box_vp >= 1 and sayyid is not None):
        state.taifas_box_vp -= 1.0
        state.score.muslim -= 1.0
        sayyid.cylinder = Cylinder(kind="calendar", box=box)
        lord.cylinder = Cylinder(kind="set_aside")
        if target in state.calendar.off_right:
            state.calendar.off_right.remove(target)
            if sayyid.id not in state.calendar.off_right:
                state.calendar.off_right.append(sayyid.id)
        swapped = True
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "disbanded": target if disbanded else None,
            "calendar_box": box, "swapped_to_al_sayyid": swapped}


@register("C26")
def _c26_freebooter(state: GameState, side: Side, card_id: str,
                    payload: dict[str, Any]) -> dict[str, Any]:
    """C26: mandatory 3.3.2 Disband, optional immediate 1-VP Reconcile."""
    from almoravid.actions import _h_disband_lord, _reconcile_rodrigo_effect
    target = "rodrigo_al_sayyid"
    lord = state.lords.get(target)
    if lord is None or lord.cylinder.kind != "locale":
        return _no_op_with_note(state, card_id, side, f"{target} not on map")
    result = _h_disband_lord(state, {"type": "disband_lord", "side": "muslim",
                                    "lord_id": target, "auto_service_disband": True,
                                    "force_at_service_limit": True})
    reconciled = bool(payload.get("reconcile"))
    if reconciled:
        _reconcile_rodrigo_effect(state, 1.0)
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "disbanded": target,
            "calendar_box": result["calendar_box"], "reconciled": reconciled}


@register("M13")  # Severed Heads
def _m13_severed_heads(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M13 (Hold): multi-trigger event.
      - Play as Ravaging to shift 1 Taifa Lord's cylinder or Service
        2 boxes OR add 2 Jihad.
      - Play if Christians Retreat or Sacked for 2 Lords OR 4 Jihad.

    Phase 6i: parked in this_levy_events; consumed by
    apply_retreat_aftermath when Christians Retreat (+4 Jihad bonus
    branch fires automatically).
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


# ---------------------------------------------------------------------------
# Phase 6d: real effects for M15, M16, M17.
# ---------------------------------------------------------------------------


@register("M15")  # Parias Revolt
def _m15_parias_revolt(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M15 Parias Revolt: 'Hold: Play to add 1 Jihad in Parias Taifa,
    OR 2 Jihad at Jihad there, OR 3 Jihad if Yusuf or Sir there.'

    Phase 6d: target a Parias Taifa locale via payload['locale_id'].
    Bonuses stack per card text: +1 base, +1 if there's already
    Jihad there, +1 if Yusuf or Sir is at that locale. Pattern 10:
    no Parias Taifa -> no-op.
    """
    # 1.4.4 Jihad eligibility: a Parias-Taifa Stronghold with NO Christian
    # Conquered / Seat marker (a Locale never holds both Conquered and
    # Jihad, 1.3.1). Mirrors M20; prevents stacking Jihad on a Conquered
    # Locale.
    eligible = _jihad_eligible_locales(state, statuses=("parias",))
    if not eligible:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Parias-Taifa Jihad Locale")
    locale_id = payload.get("locale_id")
    if locale_id not in eligible:
        locale_id = eligible[0]
    loc = state.locales[locale_id]
    add = 1
    if loc.jihad_markers > 0:
        add = 2
    here_lord_ids = [lord.id for lord in state.lords.values()
                     if lord.cylinder.kind == "locale"
                     and lord.cylinder.locale_id == locale_id]
    if "yusuf" in here_lord_ids or "sir" in here_lord_ids:
        add = 3
    loc.add_jihad(add)
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "locale_id": locale_id, "jihad_added": add,
            "new_jihad_total": loc.jihad_markers}


_M16_LORDS = ("pedro_ansurez", "garcia_ordonez", "alvar_fanez")
_M17_LORDS = ("pedro_ansurez", "garcia_ordonez", "alvar_fanez",
              "rodrigo_campeador")


def _shift_one_service_left(state: GameState, lord_id: str,
                            boxes: int = 1) -> int:
    from almoravid.actions import _shift_service_left
    return _shift_service_left(state, lord_id, boxes=boxes)


@register("M16")  # Galician Revolt
def _m16_galician_revolt(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M16 Galician Revolt: 'Shift Service of Ansurez, Ordonez, OR
    Fanez by 1 box left. This Levy, no Muster of or by Alfonso.'

    Phase 6d: targets one of the 3 listed Lords via payload['lord_id'].
    Defaults to whichever has the leftmost Service marker on the
    Calendar. Bans Alfonso from being Mustered (the 'of' clause) AND from
    acting as the Levying Lord to Muster others (the 'by' clause); both are
    enforced via muster_banned_this_levy_lord_ids in the muster_lord handler.
    """
    eligible = [lid for lid in _M16_LORDS
                if lid in state.lords
                and any(sm.lord_id == lid
                        for sm in state.calendar.service_markers)]
    target = payload.get("lord_id")
    if target and target not in _M16_LORDS:
        target = None
    if target is None and eligible:
        # Greedy: pick the leftmost (smallest box) — biggest threat.
        target = min(eligible, key=lambda lid: next(
            sm.box for sm in state.calendar.service_markers
            if sm.lord_id == lid))
    new_box = None
    if target is not None:
        new_box = _shift_one_service_left(state, target, boxes=1)
    if ("alfonso" in state.lords
            and "alfonso" not in
            state.meta.muster_banned_this_levy_lord_ids):
        state.meta.muster_banned_this_levy_lord_ids.append("alfonso")
    return {"card_id": card_id, "side": side,
            "service_shifted": target, "new_service_box": new_box,
            "muster_ban": ["alfonso"]}


@register("M17")  # Leon y Castilla
def _m17_leon_y_castilla(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M17 Leon y Castilla: 'Shift Service of Ansurez, Ordonez, Fanez,
    OR Rodrigo Campeador 1 box left. This Levy, no Muster of or by them.'

    Phase 6d: targets one of the 4 listed Lords; bans Muster for all
    four for the rest of the Levy.
    """
    eligible = [lid for lid in _M17_LORDS
                if lid in state.lords
                and any(sm.lord_id == lid
                        for sm in state.calendar.service_markers)]
    target = payload.get("lord_id")
    if target and target not in _M17_LORDS:
        target = None
    if target is None and eligible:
        target = min(eligible, key=lambda lid: next(
            sm.box for sm in state.calendar.service_markers
            if sm.lord_id == lid))
    new_box = None
    if target is not None:
        new_box = _shift_one_service_left(state, target, boxes=1)
    for lid in _M17_LORDS:
        if (lid in state.lords
                and lid not in state.meta.muster_banned_this_levy_lord_ids):
            state.meta.muster_banned_this_levy_lord_ids.append(lid)
    return {"card_id": card_id, "side": side,
            "service_shifted": target, "new_service_box": new_box,
            "muster_ban": list(_M17_LORDS)}


# ---------------------------------------------------------------------------
# Phase 6h: Tier-A event resolvers with real effects.
# ---------------------------------------------------------------------------


def _jihad_eligible_locales(
    state: GameState,
    *,
    statuses: tuple[str, ...] = ("parias", "reconquista"),
    same_taifa_as: tuple[str, ...] | None = None,
    require_existing_jihad: bool = False,
) -> list[str]:
    """All Jihad-eligible Locales per rule 1.4.4 "Important" / Quick
    Reference Table 4.

    A Stronghold Locale is Jihad-eligible when:
      - its Taifa status is in `statuses` (Reconquista/Parias; never
        Independent — Independent Taifas cannot receive Jihad);
      - it has NO Christian Conquered marker and NO Christian Seat
        marker;
      - any Christian Lord present is there ONLY via Siege or Bypass
        (an Unbesieged/Unbypassed Christian Lord blocks the Locale).

    Optional filters:
      - `same_taifa_as`: restrict to Taifas whose territory contains
        one of the given lord_ids (used by M8: "within the same Taifa
        as Yusuf/Sir/al-Mutamid").
      - `require_existing_jihad`: only Locales that already hold >=1
        Jihad marker (used by M15/M20 "at Jihad").

    Deterministic order (Taifa iteration then locale_ids order).
    """
    # Resolve which taifa_ids satisfy same_taifa_as.
    allowed_taifa_ids: set[str] | None = None
    if same_taifa_as:
        allowed_taifa_ids = set()
        for lid in same_taifa_as:
            lord = state.lords.get(lid)
            if lord is None or lord.cylinder.kind != "locale":
                continue
            for t in state.taifas.values():
                if lord.cylinder.locale_id in t.locale_ids:
                    allowed_taifa_ids.add(t.id)
    out: list[str] = []
    for taifa in state.taifas.values():
        if taifa.status not in statuses:
            continue
        if allowed_taifa_ids is not None and taifa.id not in allowed_taifa_ids:
            continue
        for lid in taifa.locale_ids:
            loc = state.locales.get(lid)
            if loc is None or loc.base_type == "region":
                continue
            # No Christian Conquered marker (model: Conquered count is
            # Christian-on-Muslim by default on Muslim territory).
            if loc.conquered_markers > 0:
                continue
            # No Christian Seat marker.
            if any(state.lords.get(slid) and state.lords[slid].side == "christian"
                   for slid in loc.seat_marker_lord_ids):
                continue
            # Unbesieged/Unbypassed Christian Lord blocks the Locale.
            christian_here = [
                lord for lord in state.lords.values()
                if lord.side == "christian" and lord.cylinder.kind == "locale"
                and lord.cylinder.locale_id == lid
            ]
            if christian_here:
                sieging_or_bypassing = (loc.siege_yellow > 0
                                        or loc.bypass_yellow)
                if not sieging_or_bypassing:
                    continue
            if require_existing_jihad and loc.jihad_markers <= 0:
                continue
            out.append(lid)
    return out


def _first_jihad_eligible_locale(
    state: GameState, taifa_filter: tuple[str, ...] = ("parias", "reconquista")
) -> str | None:
    """Back-compat shim: first Table-4-eligible Locale or None."""
    eligible = _jihad_eligible_locales(state, statuses=taifa_filter)
    return eligible[0] if eligible else None


def _place_jihad_marker(state: GameState, locale_id: str) -> None:
    from almoravid.effective import is_friendly_locale

    loc = state.locales[locale_id]
    loc.add_jihad(1)
    # 1.4.4 Open Gates also clears a Muslim Bypass if Jihad makes it Friendly.
    if loc.bypass_green and is_friendly_locale(state, locale_id, "muslim"):
        loc.bypass_green = False


def _add_jihad(
    state: GameState,
    count: int,
    payload: dict[str, Any],
    *,
    statuses: tuple[str, ...] = ("parias", "reconquista"),
    same_taifa_as: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    """Distribute `count` Jihad markers across Table-4-eligible Locales.

    If payload['jihad_targets'] is given (list of locale_ids, possibly
    with repeats to stack), validate each is eligible and place there
    in order until `count` is exhausted. Otherwise greedily fill
    eligible Locales round-robin (one marker each, looping) so a single
    call can spread markers per the card text "any eligible Locale(s)".

    Returns a placement dict {locale_id: added} or None when no
    eligible Locale exists (caller should no-op).
    """
    eligible = _jihad_eligible_locales(state, statuses=statuses,
                                       same_taifa_as=same_taifa_as)
    if not eligible:
        return None
    placement: dict[str, int] = {}
    targets = payload.get("jihad_targets")
    if targets:
        # Explicit player choice; only eligible targets count.
        placed = 0
        for lid in targets:
            if placed >= count:
                break
            if lid in eligible:
                _place_jihad_marker(state, lid)
                placement[lid] = placement.get(lid, 0) + 1
                placed += 1
        # Any leftover markers spill round-robin onto eligible Locales.
        i = 0
        while placed < count and eligible:
            lid = eligible[i % len(eligible)]
            _place_jihad_marker(state, lid)
            placement[lid] = placement.get(lid, 0) + 1
            placed += 1
            i += 1
    else:
        for n in range(count):
            lid = eligible[n % len(eligible)]
            _place_jihad_marker(state, lid)
            placement[lid] = placement.get(lid, 0) + 1
    return placement


@register("M8")  # Ahmad Ibn Rumayla
def _m8_ahmad_ibn_rumayla(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M8 (Hold): Play in Taifa with Yusuf, Sir, or al-Mutamid to
    remove Conquered from empty Town OR add 2 Jihad.

    Phase 6h: default to add-2-Jihad branch (greedy/deterministic).
    Allow payload['mode']='remove_conquered' with a target locale_id
    for the alternative.
    """
    mode = payload.get("mode", "add_jihad")
    if mode == "remove_conquered":
        loc_id = payload.get("locale_id")
        loc = state.locales.get(loc_id) if loc_id else None
        if loc is None or loc.base_type != "town" or loc.conquered_markers == 0:
            return _no_op_with_note(state, card_id, side,
                                    "no eligible empty Conquered Town")
        # Must be empty (no Lords either side).
        if any(lord.cylinder.kind == "locale" and lord.cylinder.locale_id == loc_id
               for lord in state.lords.values()):
            return _no_op_with_note(state, card_id, side,
                                    f"{loc_id} is not empty")
        loc.conquered_markers = max(0, loc.conquered_markers - 1)
        state.decks.discard.append(card_id)
        return {"card_id": card_id, "side": side,
                "removed_conquered_from": loc_id}
    # add_jihad branch — within the same Taifa as Yusuf/Sir/al-Mutamid.
    placement = _add_jihad(state, 2, payload,
                           same_taifa_as=("yusuf", "sir", "al_mutamid"))
    if placement is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": 2, "placement": placement}


def _m11_jihad_bonus_active(state: GameState) -> bool:
    """M11 3-Jihad bonus: Yusuf or Sir in any Reconquista/Parias Taifa
    or in a Kingdom (Leon/Aragon)."""
    for lid in ("yusuf", "sir"):
        lord = state.lords.get(lid)
        if lord is None or lord.cylinder.kind != "locale":
            continue
        assert lord.cylinder.locale_id is not None
        loc = state.locales.get(lord.cylinder.locale_id)
        if loc is None:
            continue
        in_taifa_bonus = any(
            lord.cylinder.locale_id in t.locale_ids
            and t.status in ("reconquista", "parias")
            for t in state.taifas.values())
        if in_taifa_bonus or loc.territory in ("leon", "aragon"):
            return True
    return False


@register("M11")  # Al-Qadir balks at payment
def _m11_al_qadir(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M11 "Al-Qadir balks at payment" is a HOLD event (the card text
    begins "Hold:"). It is NOT applied when drawn; it is held and the
    Muslim plays it at a moment of his choosing to add Jihad (base 1, or
    3 if the Yusuf/Sir bonus is active — see _h_play_al_qadir). Bucketed
    like its sibling Hold-Jihad cards (M13, C9). The card's "Lords. Yusuf
    or Sir" line is the EVENT's restriction: M11 may be played only with
    Yusuf or Sir on the map (enforced in _h_play_al_qadir). Base +1 Jihad;
    +3 if that Lord is in a Reconquista/Parias Taifa or a Kingdom."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")



@register("M18")  # Refugees
def _m18_refugees(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M18 (Hold played in Muster): each Unbesieged Taifa Lord
    restores Lost Unarmored units (Light Horse + Militia) to their
    starting Forces + Vassal Mustered units, AND adds 1 Transport
    (Cart or Mule — pick Mule deterministically).
    """
    from almoravid.effective import is_besieged, mustered_vassals
    from almoravid.static_data import load_lords
    statics = load_lords()["lords"]
    from almoravid.actions import _require
    transport_choices = payload.get("transport_by_lord", {})
    default_transport = payload.get("transport", "mule")
    _require(default_transport in ("cart", "mule")
             and all(t in ("cart", "mule") for t in transport_choices.values()),
             "Transport must be cart or mule", code="bad_transport")
    restored: list[dict[str, Any]] = []
    for lid, lord in state.lords.items():
        if not lord.is_taifa or lord.side != "muslim":
            continue
        if lord.cylinder.kind != "locale":
            continue
        if is_besieged(state, lid):
            continue
        rec = statics.get(lid, {})
        starting = dict(rec.get("forces", {}))
        for v in mustered_vassals(state, lord):
            for ut, n in v.forces.items():
                starting[ut] = starting.get(ut, 0) + n
        added: dict[str, int] = {}
        for ut in ("light_horse", "militia"):
            want = starting.get(ut, 0)
            have = lord.forces.get(ut, 0)
            if want > have:
                add = want - have
                lord.forces[ut] = have + add
                added[ut] = add
        # Add 1 Transport (Mule).
        transport = transport_choices.get(lid, default_transport)
        lord.assets[transport] = lord.assets.get(transport, 0) + 1
        added[transport] = 1
        restored.append({"lord_id": lid, "added": added})
    if not restored:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Taifa Lord on map")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "restored": restored}


@register("M22")  # Massacre
def _m22_massacre(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M22: If Eudes or Crusaders on map, Muster a Taifa Lord OR add 3
    Jihad. If not, add 1 Jihad.

    Phase 6h: Crusaders model (lord.crusader_markers) lands in Phase
    6i; for now "on map" means Eudes is at a locale. Add-Jihad
    branch fires deterministically.
    """
    eudes = state.lords.get("eudes")
    crusaders_on_map = any(
        lord.side == "christian" and lord.crusader_markers > 0
        for lord in state.lords.values()
    )
    bonus = ((eudes is not None and eudes.cylinder.kind == "locale")
             or crusaders_on_map)
    # Bonus branch may instead Muster a Taifa Lord from the Calendar
    # (payload['lord_id']); default = add Jihad.
    if bonus and payload.get("lord_id"):
        lid = payload["lord_id"]
        lord = state.lords.get(lid)
        if (lord is not None and lord.is_taifa and lord.side == "muslim"
                and lord.cylinder.kind == "calendar"):
            from almoravid.actions import _free_seats_for, _require_muster_allowed
            _require_muster_allowed(state, lid)
            # 3.4.1: auto-Muster places only at a free Seat (neither Enemy
            # nor with an Enemy Lord present); no free Seat -> fall through
            # to the Jihad branch (the Muster cannot happen). [Door C]
            free = _free_seats_for(state, lid)
            if free:
                from almoravid.actions import _initialize_mustered_lord
                _initialize_mustered_lord(state, lord.id, free[0])
                state.decks.discard.append(card_id)
                return {"card_id": card_id, "side": side,
                        "mustered": lid, "seat": free[0], "bonus": True}
    add = 3 if bonus else 1
    placement = _add_jihad(state, add, payload)
    if placement is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "placement": placement, "bonus": bonus}



# ---------------------------------------------------------------------------
# Phase 6j: M9/M10/M20/M21 — Jihad-add variants.
# ---------------------------------------------------------------------------


def _yusuf_or_sir_in_status(state: GameState,
                            statuses: tuple[str, ...]) -> bool:
    """Check whether Yusuf or Sir is at a locale whose Taifa is in
    `statuses`."""
    for lid in ("yusuf", "sir"):
        lord = state.lords.get(lid)
        if lord is None or lord.cylinder.kind != "locale":
            continue
        for t in state.taifas.values():
            if lord.cylinder.locale_id in t.locale_ids and t.status in statuses:
                return True
    return False


def _yusuf_or_sir_in_kingdom(state: GameState) -> bool:
    """Yusuf or Sir at a Christian Kingdom locale."""
    for lid in ("yusuf", "sir"):
        lord = state.lords.get(lid)
        if lord is None or lord.cylinder.kind != "locale":
            continue
        assert lord.cylinder.locale_id is not None
        loc = state.locales.get(lord.cylinder.locale_id)
        if loc and loc.territory in ("leon", "aragon"):
            return True
    return False


@register("M9")  # Maliki Islam
def _m9_maliki_islam(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M9 (Hold): +2 Jihad if Yusuf/Sir in Reconquista Taifa, OR
    +4 Jihad if in a Kingdom."""
    add = 0
    if _yusuf_or_sir_in_kingdom(state):
        add = 4
    elif _yusuf_or_sir_in_status(state, ("reconquista",)):
        add = 2
    if add == 0:
        return _no_op_with_note(state, card_id, side,
                                "Yusuf/Sir not in eligible Taifa")
    placement = _add_jihad(state, add, payload)
    if placement is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "placement": placement}


@register("M10")  # Fatwa
def _m10_fatwa(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M10 (Hold): +1 Jihad OR +1 per (Yusuf/Sir in Kingdom, Eudes on
    map, each Crusader Vassal Mustered on a Christian Lord)."""
    bonus = 0
    if _yusuf_or_sir_in_kingdom(state):
        bonus += 1
    eudes = state.lords.get("eudes")
    if eudes is not None and eudes.cylinder.kind == "locale":
        bonus += 1
    for lord in state.lords.values():
        if lord.side == "christian":
            bonus += lord.crusader_markers
    add = max(1, bonus)
    placement = _add_jihad(state, add, payload)
    if placement is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "placement": placement, "bonus": bonus}


@register("M20")  # Mudejares
def _m20_mudejares(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M20 (Hold): +1 Jihad in Reconquista Taifa, +2 at Jihad there,
    +3 if Yusuf/Sir there."""
    eligible = _jihad_eligible_locales(state, statuses=("reconquista",))
    if not eligible:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Reconquista Locale")
    target = payload.get("locale_id")
    if target not in eligible:
        target = eligible[0]
    loc = state.locales[target]
    add = 1
    if loc.jihad_markers > 0:
        add = 2
    here_ids = [lord.id for lord in state.lords.values()
                if lord.cylinder.kind == "locale"
                and lord.cylinder.locale_id == target]
    if "yusuf" in here_ids or "sir" in here_ids:
        add = 3
    loc.add_jihad(add)
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "locale_id": target}


@register("M21")  # Al-Sumaisir
def _m21_al_sumaisir(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M21 (Hold): Muster a Taifa Lord from Calendar OR add 2 Jihad
    in Parias Taifa — 4 Jihad if Yusuf/Sir there.

    Phase 6j: greedy default = Jihad branch. payload['lord_id']
    selects a Taifa Lord on the Calendar for the Muster branch.
    """
    target_lord_id = payload.get("lord_id")
    if target_lord_id and target_lord_id in state.lords:
        # Muster branch — for now, simply set cylinder to Lord's first
        # Seat and copy starting forces/assets (mirrors muster_lord but
        # bypasses Fealty and steps).
        lord = state.lords[target_lord_id]
        if lord.is_taifa and lord.side == "muslim" and lord.cylinder.kind == "calendar":
            from almoravid.actions import _free_seats_for, _require_muster_allowed
            _require_muster_allowed(state, target_lord_id)
            # 3.4.1 free Seat only; no free Seat -> fall through to Jihad. [Door C]
            free = _free_seats_for(state, target_lord_id)
            if free:
                from almoravid.actions import _initialize_mustered_lord
                _initialize_mustered_lord(state, lord.id, free[0])
                state.decks.discard.append(card_id)
                return {"card_id": card_id, "side": side,
                        "mustered": target_lord_id, "seat": free[0]}
    # Jihad branch (default) — Parias Taifa, Table-4 eligible.
    eligible = _jihad_eligible_locales(state, statuses=("parias",))
    if not eligible:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Parias Locale")
    # 4 Jihad if Yusuf/Sir at any eligible Parias Locale, else 2.
    yusuf_sir_present = any(
        lord.id in ("yusuf", "sir") and lord.cylinder.kind == "locale"
        and lord.cylinder.locale_id in eligible
        for lord in state.lords.values()
    )
    add = 4 if yusuf_sir_present else 2
    placement = _add_jihad(state, add, payload, statuses=("parias",))
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "placement": placement}


# ---------------------------------------------------------------------------
# Phase 6j: C16-C24 — Service-shift / Muster-ban / scenario events.
# ---------------------------------------------------------------------------


def _bernard_service_targets(state: GameState) -> dict[str, int]:
    from almoravid.actions import _lord_service_box

    return {
        lord.id: box for lord in state.lords.values()
        if lord.side == "christian" and lord.cylinder.kind == "locale"
        and (box := _lord_service_box(state, lord.id)) is not None
    }


def _bernard_muster_seats(state: GameState) -> dict[str, list[str]]:
    from almoravid.actions import _free_seats_for

    return {
        lord.id: seats for lord in state.lords.values()
        if lord.side == "christian" and lord.cylinder.kind == "calendar"
        and lord.id not in state.meta.muster_banned_this_levy_lord_ids
        and (seats := _free_seats_for(state, lord.id))
    }


def bernard_choices(state: GameState) -> list[dict[str, Any]]:
    """The Christian player's immediate Service and Muster alternatives."""
    from itertools import combinations

    from almoravid.effective import is_besieged

    targets = _bernard_service_targets(state)
    choices: list[dict[str, Any]] = [
        {"mode": "service_right", "lord_id": lord_id}
        for lord_id in sorted(targets, key=targets.__getitem__)
    ]
    for lord_id, seats in _bernard_muster_seats(state).items():
        muster = {"mode": "muster", "lord_id": lord_id}
        if lord_id != "rodrigo_campeador":
            choices.extend({**muster, "seat": seat} for seat in seats)
            continue
        payers = {lord.id: lord.assets["coin"] for lord in state.lords.values()
                  if lord.side == "christian" and lord.cylinder.kind == "locale"
                  and lord.assets.get("coin", 0) > 0 and not is_besieged(state, lord.id)}
        payments = [[{"lord_id": lid, "coin": 2}] for lid, coin in payers.items() if coin >= 2]
        payments.extend([{"lord_id": a, "coin": 1}, {"lord_id": b, "coin": 1}]
                        for a, b in combinations(payers, 2))
        choices.extend({**muster, "seat": seat, "payments": payment}
                       for seat in seats for payment in payments)
    return choices


@register("C16")
def _c16_bernard_de_sedirac(state: GameState, side: Side, card_id: str,
                            payload: dict[str, Any]) -> dict[str, Any]:
    """C16: immediate Service/Muster choice, then compulsory Cathedrals.

    The printed Tips require the card under the Christian board edge
    regardless of which Christian Lord receives the Event benefit.
    """
    from almoravid.actions import (
        _initialize_mustered_lord,
        _require,
        _require_muster_allowed,
    )
    from almoravid.campaign import _shift_event_service
    from almoravid.state import CardInPlay

    result: dict[str, Any] = {"card_id": card_id, "side": side}
    candidates = _bernard_service_targets(state)
    if not payload and not candidates:
        # A bare replay still resolves if only the Muster branch is possible.
        payload = next(iter(bernard_choices(state)), {})
    mode = payload.get("mode", "service_right")
    _require(mode in ("service_right", "muster"), "unknown Bernard mode", code="bad_arg")
    if mode == "muster":
        requested = payload.get("lord_id")
        if isinstance(requested, str):
            _require_muster_allowed(state, requested)
        eligible = _bernard_muster_seats(state)
        lid = requested or next(iter(eligible), None)
        if lid not in eligible:
            result.update(no_op=True, note="no Christian Lord with a free Seat to Muster")
        else:
            free = eligible[lid]
            seat = payload.get("seat", free[0])
            _require(seat in free, "choose a free Seat", code="bad_seat")
            if lid == "rodrigo_campeador":
                from almoravid.actions import _cta_collect_payment
                _cta_collect_payment(state, side, payload.get("payments", []),
                                     2, allow_taifa_box=False)
            muster = _initialize_mustered_lord(state, lid, seat)
            result.update(mustered=lid, seat=seat, **muster)
    else:
        target = payload.get("lord_id")
        if "lord_id" in payload:
            _require(isinstance(target, str) and target in candidates,
                     "choose a Christian Lord's own Service marker", code="bad_target")
        elif candidates:
            target = min(candidates, key=lambda lid: candidates[lid])
        if target is None:
            result.update(no_op=True, note="no Christian Lord Service marker to shift")
        else:
            result.update(shifted_right=target,
                          new_service_box=_shift_event_service(state, target, 1))
    # This compulsory Levy costs no action and does not consume a mat slot.
    state.decks.discard = [c for c in state.decks.discard if c != card_id]
    state.decks.draw = [c for c in state.decks.draw if c != card_id]
    state.decks.capabilities_in_play = [c for c in state.decks.capabilities_in_play
                                       if c.card_id != card_id]
    if card_id not in state.decks.board_edge.setdefault("christian", []):
        state.decks.board_edge["christian"].append(card_id)
    state.decks.capabilities_in_play.append(CardInPlay(
        card_id=card_id, scope="side_wide", owner_side="christian"))
    result["capability_levied"] = "C16"
    return result


@register("C17")  # Genoa & Pisa
def _c17_genoa_pisa(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C17 (Immediate): Place Ravaged at 2 Unravaged Enemy Ports where
    no Muslim Lords. Total +1 Christian VP per card text Tips."""
    from almoravid.effective import is_friendly_locale
    ports: list[str] = []
    for lid, loc in state.locales.items():
        if not loc.has_port:
            continue
        if loc.ravaged != "none":
            continue
        if not is_friendly_locale(state, lid, "muslim"):
            continue
        muslim_here = any(
            lord.side == "muslim" and lord.cylinder.kind == "locale"
            and lord.cylinder.locale_id == lid
            for lord in state.lords.values()
        )
        if muslim_here:
            continue
        ports.append(lid)
    placed: list[str] = []
    for p in ports[:2]:
        state.locales[p].ravaged = "yellow"  # Christian-placed
        placed.append(p)
    if not placed:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Muslim Port")
    state.score.christian += 0.5 * len(placed)  # 1 VP per 2 markers
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "ravaged": placed}


@register("C18")  # Runaway Slaves
def _c18_runaway_slaves(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C18 (Hold played in Muster): Christian Lords restore Lost Foot
    units + add Transport. Mirror of M18 Refugees for the Christian
    Foot triumvirate (men_at_arms, militia, serfs)."""
    from almoravid.effective import is_besieged, mustered_vassals
    from almoravid.static_data import load_lords
    statics = load_lords()["lords"]
    from almoravid.actions import _require
    transport_choices = payload.get("transport_by_lord", {})
    default_transport = payload.get("transport", "mule")
    _require(default_transport in ("cart", "mule")
             and all(t in ("cart", "mule") for t in transport_choices.values()),
             "Transport must be cart or mule", code="bad_transport")
    restored: list[dict[str, Any]] = []
    for lid, lord in state.lords.items():
        if lord.side != "christian":
            continue
        if lord.cylinder.kind != "locale":
            continue
        if is_besieged(state, lid):
            continue
        rec = statics.get(lid, {})
        starting = dict(rec.get("forces", {}))
        for v in mustered_vassals(state, lord):
            for ut, n in v.forces.items():
                starting[ut] = starting.get(ut, 0) + n
        added: dict[str, int] = {}
        for ut in ("men_at_arms", "militia", "serfs"):
            want = starting.get(ut, 0)
            have = lord.forces.get(ut, 0)
            if want > have:
                add = want - have
                lord.forces[ut] = have + add
                added[ut] = add
        transport = transport_choices.get(lid, default_transport)
        lord.assets[transport] = lord.assets.get(transport, 0) + 1
        added[transport] = 1
        restored.append({"lord_id": lid, "added": added})
    if not restored:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Christian Lord on map")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "restored": restored}


def fitna_choices(state: GameState) -> list[list[str]]:
    from itertools import combinations

    eligible = sorted(lid for lid, lord in state.lords.items()
                      if lord.side == "muslim" and lord.is_taifa
                      and lord.cylinder.kind in ("locale", "calendar"))
    return [list(pair) for pair in combinations(eligible, min(2, len(eligible)))]


@register("C19")  # Fitna
def _c19_fitna(state: GameState, side: Side, card_id: str,
               payload: dict[str, Any]) -> dict[str, Any]:
    """Choose up to two Taifa Lords. Shift only Mustered Lords' Service."""
    from almoravid.actions import _require, _shift_service_left

    choices = fitna_choices(state)
    targets = payload.get("lord_ids", choices[0] if len(choices) == 1 else None)
    _require(targets is not None, "select Fitna targets with payload.lord_ids",
             code="choice_required")
    _require(isinstance(targets, list) and all(isinstance(lid, str) for lid in targets)
             and sorted(targets) in choices, "select distinct eligible Taifa Lords for Fitna",
             code="bad_target")
    shifted = []
    service = {sm.lord_id for sm in state.calendar.service_markers if sm.vassal_id is None}
    service.update(state.calendar.off_left_service)
    for lid in targets:
        if state.lords[lid].cylinder.kind == "locale" and lid in service:
            new_box = _shift_service_left(state, lid, boxes=1)
            shifted.append({"lord_id": lid, "new_service_box": new_box})
        if lid not in state.meta.muster_banned_this_levy_lord_ids:
            state.meta.muster_banned_this_levy_lord_ids.append(lid)
    return {"card_id": card_id, "side": side, "shifted": shifted,
            "muster_ban": targets, "no_op": not targets}


def al_qadir_choices(state: GameState) -> list[list[str]]:
    """C20 marker selections: repeat a Locale id to choose two markers there.

    Both markers must be in one eligible Taifa. Remove only one when that
    Taifa has only one, per the general do-as-much-as-possible Event rule.
    """
    from itertools import combinations_with_replacement

    choices: list[list[str]] = []
    for taifa in state.taifas.values():
        if taifa.status not in ("reconquista", "parias"):
            continue
        if any(lord.side == "muslim" and lord.cylinder.kind == "locale"
               and lord.cylinder.locale_id in taifa.locale_ids
               for lord in state.lords.values()):
            continue
        targets = sorted(lid for lid in taifa.locale_ids
                         if state.locales[lid].jihad_markers > 0)
        available = sum(state.locales[lid].jihad_markers for lid in targets)
        if available == 1:
            choices.append(targets)
        elif available >= 2:
            for first, second in combinations_with_replacement(targets, 2):
                if first != second or state.locales[first].jihad_markers >= 2:
                    choices.append([first, second])
    return choices


@register("C20")  # Al-Qadir
def _c20_al_qadir(state: GameState, side: Side, card_id: str,
                  payload: dict[str, Any]) -> dict[str, Any]:
    """C20 Hold: the player selects two Jihad within one eligible Taifa.

    payload.locale_ids selects individual markers, e.g. ["ucles", "ucles"]
    or ["ucles", "calatrava"]. payload.locale_id is a single-Locale shorthand.
    No target is chosen automatically, and invalid play leaves the card held.
    """
    from almoravid.actions import _require

    _require(side == "christian", "Al-Qadir is a Christian Event", code="wrong_side")
    choices = al_qadir_choices(state)
    _require(bool(choices), "no eligible Jihad in a Taifa free of Muslim Lords",
             code="bad_target")
    _require(not ("locale_ids" in payload and "locale_id" in payload),
             "choose locale_ids or locale_id, not both", code="bad_arg")
    selected = payload.get("locale_ids")
    if "locale_id" in payload:
        target = payload["locale_id"]
        _require(isinstance(target, str), "locale_id must be a string", code="bad_arg")
        selected = next((choice for choice in choices
                         if all(lid == target for lid in choice)), None)
        _require(selected is not None, "cannot remove the required markers there",
                 code="bad_target")
    _require(selected is not None, "select Jihad markers with payload.locale_ids",
             code="choice_required")
    _require(isinstance(selected, list) and all(isinstance(lid, str) for lid in selected),
             "locale_ids must be a list of Locale ids", code="bad_arg")
    selected = sorted(selected)
    _require(selected in choices, "select two available Jihad within one eligible Taifa",
             code="bad_target")
    taifa_id = state.locales[selected[0]].territory
    for lid in selected:
        state.locales[lid].jihad_markers -= 1
    state.score.muslim -= 0.5 * len(selected)
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "jihad_removed": len(selected),
            "taifa": taifa_id, "locale_ids": selected}


_C22_LORDS = ("al_mutawakkil", "abd_allah", "yusuf", "sir")


@register("C22")  # Berbers
def _c22_berbers(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C22: Shift Service of al-Mutawakkil/Abd Allah/Yusuf/Sir 1 box;
    this Levy, no Muster of/by any of them."""
    from almoravid.actions import _shift_service_left
    eligible = [lid for lid in _C22_LORDS
                if lid in state.lords
                and any(sm.lord_id == lid
                        for sm in state.calendar.service_markers)]
    target = payload.get("lord_id") if payload.get("lord_id") in _C22_LORDS         else None
    if target is None and eligible:
        target = min(eligible, key=lambda lid: next(
            sm.box for sm in state.calendar.service_markers
            if sm.lord_id == lid))
    new_box = None
    if target is not None:
        new_box = _shift_service_left(state, target, boxes=1)
    for lid in _C22_LORDS:
        if (lid in state.lords
                and lid not in state.meta.muster_banned_this_levy_lord_ids):
            state.meta.muster_banned_this_levy_lord_ids.append(lid)
    return {"card_id": card_id, "side": side,
            "service_shifted": target, "new_service_box": new_box}


_C23_LORDS = ("abu_bakr", "al_mustain")


def illness_choices(state: GameState) -> list[dict[str, str]]:
    service = {sm.lord_id for sm in state.calendar.service_markers if sm.vassal_id is None}
    return [{"lord_id": lid, "mode": mode}
            for lid in _C23_LORDS if lid in state.lords
            for mode in ("service", "cylinder")
            if (lid in service if mode == "service"
                else state.lords[lid].cylinder.kind == "calendar")]


@register("C23")  # Illness of the Emir
def _c23_illness(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C23: On Calendar, shift cylinder OR Service of Abu Bakr OR
    al-Mustain by 1 box; this Levy, no Muster of/by him.

    payload['mode']: 'service' (default, Service 1 box left) or
    'cylinder' (cylinder 1 box left on the Calendar).
    payload['lord_id']: abu_bakr | al_mustain.
    """
    from almoravid.actions import _require, _shift_service_left

    choices = illness_choices(state)
    matches = [choice for choice in choices
               if all(choice[key] == payload.get(key, choice[key]) for key in choice)]
    if not choices and not payload:
        return {"card_id": card_id, "side": side, "no_op": True}
    _require(bool(matches), "select an eligible cylinder or Service marker for Illness",
             code="bad_target")
    target, mode = matches[0]["lord_id"], matches[0]["mode"]
    result: dict[str, Any] = {"card_id": card_id, "side": side,
                              "target": target, "mode": mode}
    if mode == "cylinder":
        lord = state.lords[target]
        cur = lord.cylinder.box if lord.cylinder.box is not None else 1
        lord.cylinder.box = max(0, cur - 1)
        if target in state.calendar.off_right:
            state.calendar.off_right.remove(target)
        if lord.cylinder.box == 0 and target not in state.calendar.off_left:
            state.calendar.off_left.append(target)
        result["new_cylinder_box"] = lord.cylinder.box
    else:
        result["new_service_box"] = _shift_service_left(state, target,
                                                        boxes=1)
    if target not in state.meta.muster_banned_this_levy_lord_ids:
        state.meta.muster_banned_this_levy_lord_ids.append(target)
    return result


@register("C24")  # Abu Bakr ibn Umar
def _c24_abu_bakr(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C24: On Calendar, shift Service of Yusuf AND Sir each 1 box
    left; this Levy, no Muster of/by either."""
    from almoravid.actions import _shift_service_left
    shifted = []
    for lid in ("yusuf", "sir"):
        if lid not in state.lords:
            continue
        if lid not in state.meta.muster_banned_this_levy_lord_ids:
            state.meta.muster_banned_this_levy_lord_ids.append(lid)
        if not any(sm.lord_id == lid
                   and sm.vassal_id is None for sm in state.calendar.service_markers):
            continue
        new_box = _shift_service_left(state, lid, boxes=1)
        shifted.append({"lord_id": lid, "new_service_box": new_box})
    return {"card_id": card_id, "side": side, "shifted": shifted}


@register("M24")  # Al-Maghawir
def _m24_al_maghawir(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M24 (Immediate): Unless C19 Caballeria Villana, place Ravaged at
    2 Unravaged Enemy Locales adjacent to Friendly Locales."""
    from almoravid.effective import is_friendly_locale
    from almoravid.map import neighbors_via
    # C19 Caballeria Villana (capability) blocks: check
    # state.decks.capabilities_in_play.
    for cip in state.decks.capabilities_in_play:
        if cip.card_id == "C19":
            return _no_op_with_note(state, card_id, side,
                                    "blocked by C19 Caballeria Villana")
    eligible: list[str] = []
    for lid, loc in state.locales.items():
        if loc.ravaged != "none":
            continue
        if not is_friendly_locale(state, lid, "christian"):
            continue
        # Adjacent to a Muslim-friendly locale?
        all_n = set()
        for wt in ("road", "pass"):
            all_n.update(neighbors_via(lid, wt))
        if any(is_friendly_locale(state, n, "muslim") for n in all_n):
            eligible.append(lid)
    placed: list[str] = []
    for p in eligible[:2]:
        state.locales[p].ravaged = "green"
        placed.append(p)
    if not placed:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Christian Locale")
    state.score.muslim += 0.5 * len(placed)
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "ravaged": placed}


# C21 Mozarabes — Hold: parked in this_levy_events; the auto-success on a
# Reconquista-Taifa Surrender roll is consumed by the cmd_siege Surrender
# path (it checks for a held C21 and discards it on auto-success).
@register("C21")  # Mozarabes
def _c21_mozarabes(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """C21 (Hold): Play for a Surrender roll in a Reconquista Taifa to
    succeed automatically. Phase 6j: parks in this_levy_events for
    consumption by a future cmd_siege Mozarabes hook."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")



@register("M19")  # African Fleet
def _m19_african_fleet(state: GameState, side: Side, card_id: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """M19 (Hold): Play for a Lord to use his Command card to March
    Port-to-Port where no Christian Lord at destination.

    Parks in this_levy_events; the Port-to-Port March is carried out by
    the play handler campaign._h_cmd_march_port_to_port (consumes this
    Hold + the active Lord's entire Command card).
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")
