"""Arts of War Event resolution.

An Event is the TOP half of an AoW card. Events have one of three
persistence kinds:

  - immediate: fires once on play, then discards.
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

from typing import Any, Callable

from almoravid.state import GameState, Side
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


def _is_immediate(card_id: str) -> bool:
    rec = load_cards()["cards"].get(card_id, {})
    return rec.get("event_persistence") == "immediate"


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
    return resolver(state, side, card_id, payload or {})


# ---------------------------------------------------------------------------
# Battle-context hold events — Phase 4b stubs.
# Combat resolution is Phase 5; these stubs place the card in the
# this_levy_events bucket so the Phase 5 Battle resolver can find them.
# ---------------------------------------------------------------------------


@register("C1")  # Hills (Christian)
@register("M1")  # Hills (Muslim)
def _hills(state, side, card_id, payload):
    """Hold-event Hills: Defending side, Slingers x1.5, other Missiles
    x1 (not x1/2). Combat hook in Phase 5; here we just persist it.
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C3")
@register("M3")
def _swollen_river(state, side, card_id, payload):
    """Hold-event Swollen River: affects movement / battle terrain.
    Phase 5 hooks into March / Battle eligibility."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C4")  # Arid Terrain
@register("M4")
def _arid_terrain(state, side, card_id, payload):
    """Hold-event: triggers when enemy Marches (Phase 6h hook in
    _h_cmd_march). Buffered in this_levy_events until that fires."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C5")  # Drought
@register("M5")  # Drought
def _drought(state, side, card_id, payload):
    """Drought: Immediate. The TARGET side (opposite of the side that
    drew) immediately Feeds 2 of their Lords not at Friendly Gardens
    or Seat. Phase 6h: pick deterministically (first two on the map
    who don't qualify for Gardens/Seat exemption).

    Note: per card text, the side that DRAWS Drought triggers it
    against the OTHER side ("Unless Muslims discard Camels, they
    immediately Feed 2"). C5 drawn by Christian targets Muslims;
    M5 drawn by Muslim targets Christians.
    """
    from almoravid.campaign import _feed_lord
    from almoravid.effective import has_gardens, is_friendly_locale
    target_side: Side = "muslim" if card_id == "C5" else "christian"
    candidates: list[str] = []
    for l in state.lords.values():
        if l.side != target_side:
            continue
        if l.cylinder.kind != "locale":
            continue
        loc_id = l.cylinder.locale_id
        gardens_ok = has_gardens(state, loc_id)
        seat_ok = loc_id in state.lords[l.id].seats
        friendly = is_friendly_locale(state, loc_id, target_side)
        if (gardens_ok or seat_ok) and friendly:
            continue
        candidates.append(l.id)
    if not candidates:
        return _no_op_with_note(state, card_id, side,
                                f"no eligible {target_side} Lord to Feed")
    fed = []
    for lid in sorted(candidates)[:2]:
        r = _feed_lord(state, lid, force=True)
        fed.append({"lord_id": lid, **r})
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "target_side": target_side, "fed_lords": fed}


@register("C7")  # Baggage Parapet
@register("M7")  # Spear Wall
def _baggage_or_spear(state, side, card_id, payload):
    """Hold-event battle bonuses. Phase 5 combat hook."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C8")  # Cantador
def _cantador(state, side, card_id, payload):
    """Hold-event: Knights and Sergeants +1 Hit Round 1 Melee. Phase 5 combat hook."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C9")  # Betrayal of Terms
def _c9_betrayal_of_terms(state, side, card_id, payload):
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
@register("M6")  # Feigned Retreat — immediate
def _battle_immediate_marker(state, side, card_id, payload):
    """Cards whose effect manifests in a specific Battle moment.
    Buffered in this_campaign_events; Phase 5 Battle code will fish
    them out at the right moment."""
    return _move_to_hold_bucket(state, card_id, side, "this_campaign_events")


# ---------------------------------------------------------------------------
# Immediate events that adjust state directly. Useful for Phase 4
# testing because no combat is required.
# ---------------------------------------------------------------------------


@register("M12")  # Taifa Marriage
def _m12_taifa_marriage(state, side, card_id, payload):
    """M12 (Hold): shift up to 2 Taifa Lords' cylinder LEFT if on
    Calendar, or Service RIGHT if Lord is on the map. OR one Lord
    uses Lordship +2.

    Phase 6j+: greedy default — pick up to 2 Taifa Lords sorted by
    lord_id; for each, if cylinder.kind == 'calendar' shift the
    Calendar cylinder via service marker; if on the map, shift their
    Service marker RIGHT (toward end of campaign, +1 box).
    payload['lord_ids']: optional explicit list of up to 2 Lord IDs.
    """
    taifa_lord_ids = [lid for lid, l in state.lords.items()
                      if l.is_taifa and l.side == "muslim"]
    # Lordship +2 branch: payload['mode']=='lordship', one Lord.
    if payload.get("mode") == "lordship":
        lid = payload.get("lord_id")
        if lid not in taifa_lord_ids:
            lid = sorted(taifa_lord_ids)[0] if taifa_lord_ids else None
        if lid is None:
            return _no_op_with_note(state, card_id, side,
                                    "no Taifa Lord for Lordship")
        state.lords[lid].lordship_rating += 2
        state.decks.discard.append(card_id)
        return {"card_id": card_id, "side": side,
                "lordship_plus_2": lid,
                "lordship_rating_now": state.lords[lid].lordship_rating}
    chosen = payload.get("lord_ids") or sorted(taifa_lord_ids)[:2]
    if not chosen:
        return _no_op_with_note(state, card_id, side,
                                "no Taifa Lord eligible")
    shifted = []
    for lid in chosen[:2]:
        l = state.lords.get(lid)
        if l is None:
            continue
        if l.cylinder.kind == "calendar":
            # Shift cylinder LEFT (toward box 1 / earlier activation).
            cur = l.cylinder.box if l.cylinder.box is not None else 1
            l.cylinder.box = max(0, cur - 1)
            shifted.append({"lord_id": lid, "shifted": "cylinder_left",
                            "new_cylinder_box": l.cylinder.box})
        else:
            sm = next((s for s in state.calendar.service_markers
                       if s.lord_id == lid), None)
            if sm is not None:
                sm.box = min(16, sm.box + 1)  # Service RIGHT (delay Disband)
                shifted.append({"lord_id": lid, "shifted": "service_right",
                                "new_service_box": sm.box})
    if not shifted:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Lord could be shifted")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "shifted": shifted}





import math as _math


@register("C10")  # Devaluation (Christian-played, drains Muslim Coin)
def _c10_devaluation_christian(state, side, card_id, payload):
    """C10 Devaluation: 'Muslims reduce their Coin among Taifas box
    and Lords to 2/3 of the total (rounded up).'

    Phase 6d: drains all Muslim Lords' Coin down to ceil(total * 2/3).
    Taifas-box Coin is not modeled in state (no Taifa.assets field) so
    only Lord-held Coin is affected. Pattern 10: no Coin -> no-op.
    """
    muslim_lords = [l for l in state.lords.values() if l.side == "muslim"]
    box = state.taifas_box_coin
    total_before = sum(l.assets.get("coin", 0) for l in muslim_lords) + box
    if total_before == 0:
        return _no_op_with_note(state, card_id, side,
                                "no Muslim Coin to devalue")
    target = _math.ceil(total_before * 2 / 3)
    to_remove = total_before - target
    removed = 0
    # Drain the Taifas box first, then Lord mats (deterministic).
    box_take = min(box, to_remove)
    state.taifas_box_coin -= box_take
    removed += box_take
    for l in sorted(muslim_lords, key=lambda x: x.id):
        if removed >= to_remove:
            break
        have = l.assets.get("coin", 0)
        take = min(have, to_remove - removed)
        if take > 0:
            l.assets["coin"] = have - take
            if l.assets["coin"] == 0:
                l.assets.pop("coin", None)
            removed += take
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "coin_before": total_before, "coin_after": target,
            "removed": removed}


@register("M14")  # Devaluation (Muslim-played, drains Christian Coin)
def _m14_devaluation_muslim(state, side, card_id, payload):
    """M14 Devaluation: 'Each Locale where Christian Lords have Coin,
    they reduce their total there to half (rounded up).'

    Phase 6d: per-Locale halving for Christian Coin. Pattern 10: no
    Coin -> no-op.
    """
    per_locale: dict[str, list] = {}
    for l in state.lords.values():
        if (l.side == "christian" and l.cylinder.kind == "locale"
                and l.assets.get("coin", 0) > 0):
            per_locale.setdefault(l.cylinder.locale_id, []).append(l)
    if not per_locale:
        return _no_op_with_note(state, card_id, side,
                                "no Christian Coin at any Locale")
    total_removed = 0
    for locale_id, lords in per_locale.items():
        total_before = sum(l.assets.get("coin", 0) for l in lords)
        target = _math.ceil(total_before / 2)
        to_remove = total_before - target
        removed = 0
        for l in sorted(lords, key=lambda x: x.id):
            if removed >= to_remove:
                break
            have = l.assets.get("coin", 0)
            take = min(have, to_remove - removed)
            if take > 0:
                l.assets["coin"] = have - take
                if l.assets["coin"] == 0:
                    l.assets.pop("coin", None)
                removed += take
        total_removed += removed
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "locales_affected": list(per_locale),
            "total_removed": total_removed}


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

@register("C13")  # Berenguer Ramon — Christian event
def _c13_berenguer_ramon(state, side, card_id, payload):
    """C13 (Immediate): If Count of Barcelona with Muslims, discard.
    Otherwise a named Christian Lord may pay 1 Asset and Levy this
    card and its units (2 Knights + 2 Men-at-Arms per Capability text).

    Phase 6k: if Count of Barcelona is with Muslim side, discard
    no-effect. Otherwise the target Lord gains +2 Knights + +2 MaA
    once (payload['target_lord_id']; default = first eligible
    Sancho/Eudes/al-Mustain/al-Mundir). Pay 1 Asset (coin) when
    available.
    """
    if state.meta.count_of_barcelona_side == "muslim":
        state.decks.discard.append(card_id)
        return {"card_id": card_id, "side": side,
                "discarded_no_effect": True,
                "reason": "Count of Barcelona with Muslims"}
    eligible = [lid for lid in ("sancho", "eudes",
                                 "al_mustain", "al_mundir")
                if lid in state.lords
                and state.lords[lid].cylinder.kind == "locale"]
    target = payload.get("target_lord_id")
    if target and target not in eligible:
        target = None
    if target is None:
        target = eligible[0] if eligible else None
    if target is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Lord on map")
    lord = state.lords[target]
    # Pay 1 Coin if available.
    paid = False
    if lord.assets.get("coin", 0) > 0:
        lord.assets["coin"] -= 1
        if lord.assets["coin"] == 0:
            lord.assets.pop("coin", None)
        paid = True
    lord.forces["knights"] = lord.forces.get("knights", 0) + 2
    lord.forces["men_at_arms"] = lord.forces.get("men_at_arms", 0) + 2
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "target": target,
            "knights_added": 2, "men_at_arms_added": 2,
            "asset_paid": paid}


@register("M23")  # Berenguer Ramon — Muslim event (mirror)
def _m23_berenguer_ramon(state, side, card_id, payload):
    """M23: mirror of C13 — if Count of Barcelona with Christians,
    discard no-effect. Otherwise a Muslim Lord gets 2 Knights + 2 MaA
    by paying 1 Asset (coin).
    """
    if state.meta.count_of_barcelona_side == "christian":
        state.decks.discard.append(card_id)
        return {"card_id": card_id, "side": side,
                "discarded_no_effect": True,
                "reason": "Count of Barcelona with Christians"}
    eligible = [lid for lid in ("al_mustain", "al_mundir",
                                 "sancho", "eudes")
                if lid in state.lords
                and state.lords[lid].cylinder.kind == "locale"]
    target = payload.get("target_lord_id") if payload.get("target_lord_id")         in eligible else (eligible[0] if eligible else None)
    if target is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Lord on map")
    lord = state.lords[target]
    paid = False
    if lord.assets.get("coin", 0) > 0:
        lord.assets["coin"] -= 1
        if lord.assets["coin"] == 0:
            lord.assets.pop("coin", None)
        paid = True
    lord.forces["knights"] = lord.forces.get("knights", 0) + 2
    lord.forces["men_at_arms"] = lord.forces.get("men_at_arms", 0) + 2
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "target": target,
            "knights_added": 2, "men_at_arms_added": 2,
            "asset_paid": paid}


# --- Immediate events with side-wide state effects ---


@register("C11")  # Indulgences
@register("C12")  # Song of Roland
def _crusader_event(state, side, card_id, payload):
    """C11 Indulgences / C12 Song of Roland: Place 1 Crusader marker
    on an Unbesieged Christian Lord with 2 Knights attached (modeled
    by incrementing lord.crusader_markers + adding 2 Knights to forces).

    Phase 6i: Eudes-Muster-all-Ready-Vassals clause only fires if
    Eudes is on the map AND has Ready Vassals. We auto-Muster any
    Ready Vassals of Eudes (3.4.2 ARTS OF WAR) when triggered.
    """
    from almoravid.effective import is_besieged
    target_lord_id = payload.get("target_lord_id")
    available_christians = [
        l.id for l in state.lords.values()
        if l.side == "christian"
        and l.cylinder.kind == "locale"
        and not is_besieged(state, l.id)
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
            if v.ready:
                continue
            v.ready = True
            for ut, n in v.forces.items():
                eudes.forces[ut] = eudes.forces.get(ut, 0) + n
            eudes_mustered.append(v.id)

    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "target": target,
            "crusader_markers_now": target_lord.crusader_markers,
            "knights_added": 2,
            "eudes_vassals_mustered": eudes_mustered}


@register("C14")  # Pope Gregory
def _pope_gregory(state, side, card_id, payload):
    """Pope Gregory: hold-event eligibility on Sancho (Pope Gregory cap).
    Phase 5j: held in this_levy_events; resolver hook for Sancho's
    capability bonus."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C15")  # Cluniacs
def _religious_hold(state, side, card_id, payload):
    """C15 Cluniacs (Hold): Lord Muster from Calendar, OR Service +1
    right, OR Lordship +2 for this Levy. Phase 6j: parks in
    this_levy_events; consumed by ad-hoc Levy action (TODO)."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


# --- Rodrigo (El Cid) family ---


@register("C25")  # De Vivar
def _c25_de_vivar(state, side, card_id, payload):
    """C25 (Hold): Play as Christian Call to Arms if Rodrigo al-Sayyid
    on map. Reconcile with Rodrigo for 1 VP to Taifas box.

    Phase 6j: parks in this_levy_events. The Reconcile + VP-to-Taifa
    transfer is a deferred follow-up (no Taifa Coin box in state).
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C26")  # Freebooter
def _c26_freebooter(state, side, card_id, payload):
    """C26 (Immediate): Disband Rodrigo al-Sayyid as if at Service
    Limit (3.3.2). Optional Reconcile clause deferred.

    Phase 6j: greedy disband — clears Rodrigo's forces/assets, sends
    his cylinder back to off-left-service.
    """
    target = "rodrigo_al_sayyid"
    lord = state.lords.get(target)
    if lord is None or lord.cylinder.kind != "locale":
        return _no_op_with_note(state, card_id, side,
                                f"{target} not on map")
    from almoravid.actions import _shift_service_left
    from almoravid.state import Cylinder
    for field_name in lord.cleanup_on_removal_fields:
        try:
            setattr(lord, field_name,
                    type(getattr(lord, field_name))())
        except Exception:
            pass
    _shift_service_left(state, target, boxes=20)  # off-left
    lord.cylinder = Cylinder(kind="removed")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "disbanded": target}


@register("M13")  # Severed Heads
def _m13_severed_heads(state, side, card_id, payload):
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
def _m15_parias_revolt(state, side, card_id, payload):
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
    here_lord_ids = [l.id for l in state.lords.values()
                     if l.cylinder.kind == "locale"
                     and l.cylinder.locale_id == locale_id]
    if "yusuf" in here_lord_ids or "sir" in here_lord_ids:
        add = 3
    loc.jihad_markers += add
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "locale_id": locale_id, "jihad_added": add,
            "new_jihad_total": loc.jihad_markers}


_M16_LORDS = ("pedro_ansurez", "garcia_ordonez", "alvar_fanez")
_M17_LORDS = ("pedro_ansurez", "garcia_ordonez", "alvar_fanez",
              "rodrigo_campeador")


def _shift_one_service_left(state, lord_id: str, boxes: int = 1) -> int:
    from almoravid.actions import _shift_service_left
    return _shift_service_left(state, lord_id, boxes=boxes)


@register("M16")  # Galician Revolt
def _m16_galician_revolt(state, side, card_id, payload):
    """M16 Galician Revolt: 'Shift Service of Ansurez, Ordonez, OR
    Fanez by 1 box left. This Levy, no Muster of or by Alfonso.'

    Phase 6d: targets one of the 3 listed Lords via payload['lord_id'].
    Defaults to whichever has the leftmost Service marker on the
    Calendar. Bans Alfonso from being Mustered (the 'of' clause); the
    'by' clause (Alfonso musters others) is approximated by the same
    ban since our muster handler is the only Muster code path.
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
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "service_shifted": target, "new_service_box": new_box,
            "muster_ban": ["alfonso"]}


@register("M17")  # Leon y Castilla
def _m17_leon_y_castilla(state, side, card_id, payload):
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
    state.decks.discard.append(card_id)
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
            l = state.lords.get(lid)
            if l is None or l.cylinder.kind != "locale":
                continue
            for t in state.taifas.values():
                if l.cylinder.locale_id in t.locale_ids:
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
                l for l in state.lords.values()
                if l.side == "christian" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == lid
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


def _add_jihad(
    state: GameState,
    count: int,
    payload: dict,
    *,
    statuses: tuple[str, ...] = ("parias", "reconquista"),
    same_taifa_as: tuple[str, ...] | None = None,
) -> dict | None:
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
                state.locales[lid].jihad_markers += 1
                placement[lid] = placement.get(lid, 0) + 1
                placed += 1
        # Any leftover markers spill round-robin onto eligible Locales.
        i = 0
        while placed < count and eligible:
            lid = eligible[i % len(eligible)]
            state.locales[lid].jihad_markers += 1
            placement[lid] = placement.get(lid, 0) + 1
            placed += 1
            i += 1
    else:
        for n in range(count):
            lid = eligible[n % len(eligible)]
            state.locales[lid].jihad_markers += 1
            placement[lid] = placement.get(lid, 0) + 1
    return placement


@register("M8")  # Ahmad Ibn Rumayla
def _m8_ahmad_ibn_rumayla(state, side, card_id, payload):
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
        if any(l.cylinder.kind == "locale" and l.cylinder.locale_id == loc_id
               for l in state.lords.values()):
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


def _m11_jihad_bonus_active(state) -> bool:
    """M11 3-Jihad bonus: Yusuf or Sir in any Reconquista/Parias Taifa
    or in a Kingdom (Leon/Aragon)."""
    for lid in ("yusuf", "sir"):
        l = state.lords.get(lid)
        if l is None or l.cylinder.kind != "locale":
            continue
        loc = state.locales.get(l.cylinder.locale_id)
        if loc is None:
            continue
        in_taifa_bonus = any(
            l.cylinder.locale_id in t.locale_ids
            and t.status in ("reconquista", "parias")
            for t in state.taifas.values())
        if in_taifa_bonus or loc.territory in ("leon", "aragon"):
            return True
    return False


@register("M11")  # Al-Qadir balks at payment
def _m11_al_qadir(state, side, card_id, payload):
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
def _m18_refugees(state, side, card_id, payload):
    """M18 (Hold played in Muster): each Unbesieged Taifa Lord
    restores Lost Unarmored units (Light Horse + Militia) to their
    starting Forces + Vassal Mustered units, AND adds 1 Transport
    (Cart or Mule — pick Mule deterministically).
    """
    from almoravid.effective import is_besieged
    from almoravid.static_data import load_lords
    statics = load_lords()["lords"]
    restored: list[dict] = []
    for lid, l in state.lords.items():
        if not l.is_taifa or l.side != "muslim":
            continue
        if l.cylinder.kind != "locale":
            continue
        if is_besieged(state, lid):
            continue
        rec = statics.get(lid, {})
        starting = dict(rec.get("forces", {}))
        for v in l.vassals:
            if v.ready:
                continue  # Not Mustered
            for ut, n in v.forces.items():
                starting[ut] = starting.get(ut, 0) + n
        added: dict[str, int] = {}
        for ut in ("light_horse", "militia"):
            want = starting.get(ut, 0)
            have = l.forces.get(ut, 0)
            if want > have:
                add = want - have
                l.forces[ut] = have + add
                added[ut] = add
        # Add 1 Transport (Mule).
        l.assets["mule"] = l.assets.get("mule", 0) + 1
        added["mule"] = 1
        restored.append({"lord_id": lid, "added": added})
    if not restored:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Taifa Lord on map")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "restored": restored}


@register("M22")  # Massacre
def _m22_massacre(state, side, card_id, payload):
    """M22: If Eudes or Crusaders on map, Muster a Taifa Lord OR add 3
    Jihad. If not, add 1 Jihad.

    Phase 6h: Crusaders model (lord.crusader_markers) lands in Phase
    6i; for now "on map" means Eudes is at a locale. Add-Jihad
    branch fires deterministically.
    """
    eudes = state.lords.get("eudes")
    crusaders_on_map = any(
        l.side == "christian" and l.crusader_markers > 0
        for l in state.lords.values()
    )
    bonus = ((eudes is not None and eudes.cylinder.kind == "locale")
             or crusaders_on_map)
    # Bonus branch may instead Muster a Taifa Lord from the Calendar
    # (payload['lord_id']); default = add Jihad.
    if bonus and payload.get("lord_id"):
        lid = payload["lord_id"]
        l = state.lords.get(lid)
        if (l is not None and l.is_taifa and l.side == "muslim"
                and l.cylinder.kind == "calendar"):
            from almoravid.static_data import load_lords as _ll
            from almoravid.state import Cylinder
            rec = _ll()["lords"].get(lid, {})
            seats = list(rec.get("seats", []))
            if seats:
                l.cylinder = Cylinder(kind="locale", locale_id=seats[0])
                l.forces = dict(rec.get("forces", {}))
                l.assets = dict(rec.get("assets", {}))
                l.just_arrived_this_levy = True
                state.decks.discard.append(card_id)
                return {"card_id": card_id, "side": side,
                        "mustered": lid, "seat": seats[0], "bonus": True}
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


def _yusuf_or_sir_in_status(state, statuses: tuple[str, ...]) -> bool:
    """Check whether Yusuf or Sir is at a locale whose Taifa is in
    `statuses`."""
    for lid in ("yusuf", "sir"):
        l = state.lords.get(lid)
        if l is None or l.cylinder.kind != "locale":
            continue
        for t in state.taifas.values():
            if l.cylinder.locale_id in t.locale_ids and t.status in statuses:
                return True
    return False


def _yusuf_or_sir_in_kingdom(state) -> bool:
    """Yusuf or Sir at a Christian Kingdom locale."""
    for lid in ("yusuf", "sir"):
        l = state.lords.get(lid)
        if l is None or l.cylinder.kind != "locale":
            continue
        loc = state.locales.get(l.cylinder.locale_id)
        if loc and loc.territory in ("leon", "aragon"):
            return True
    return False


@register("M9")  # Maliki Islam
def _m9_maliki_islam(state, side, card_id, payload):
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
def _m10_fatwa(state, side, card_id, payload):
    """M10 (Hold): +1 Jihad OR +1 per (Yusuf/Sir in Kingdom, Eudes on
    map, each Crusader Vassal Mustered on a Christian Lord)."""
    bonus = 0
    if _yusuf_or_sir_in_kingdom(state):
        bonus += 1
    eudes = state.lords.get("eudes")
    if eudes is not None and eudes.cylinder.kind == "locale":
        bonus += 1
    for l in state.lords.values():
        if l.side == "christian":
            bonus += l.crusader_markers
    add = max(1, bonus)
    placement = _add_jihad(state, add, payload)
    if placement is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "placement": placement, "bonus": bonus}


@register("M20")  # Mudejares
def _m20_mudejares(state, side, card_id, payload):
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
    here_ids = [l.id for l in state.lords.values()
                if l.cylinder.kind == "locale"
                and l.cylinder.locale_id == target]
    if "yusuf" in here_ids or "sir" in here_ids:
        add = 3
    loc.jihad_markers += add
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "locale_id": target}


@register("M21")  # Al-Sumaisir
def _m21_al_sumaisir(state, side, card_id, payload):
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
        from almoravid.static_data import load_lords as _ll
        l = state.lords[target_lord_id]
        if l.is_taifa and l.side == "muslim" and l.cylinder.kind == "calendar":
            rec = _ll()["lords"].get(target_lord_id, {})
            seats = list(rec.get("seats", []))
            if seats:
                from almoravid.state import Cylinder
                l.cylinder = Cylinder(kind="locale", locale_id=seats[0])
                l.forces = dict(rec.get("forces", {}))
                l.assets = dict(rec.get("assets", {}))
                l.just_arrived_this_levy = True
                state.decks.discard.append(card_id)
                return {"card_id": card_id, "side": side,
                        "mustered": target_lord_id, "seat": seats[0]}
    # Jihad branch (default) — Parias Taifa, Table-4 eligible.
    eligible = _jihad_eligible_locales(state, statuses=("parias",))
    if not eligible:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Parias Locale")
    # 4 Jihad if Yusuf/Sir at any eligible Parias Locale, else 2.
    yusuf_sir_present = any(
        l.id in ("yusuf", "sir") and l.cylinder.kind == "locale"
        and l.cylinder.locale_id in eligible
        for l in state.lords.values()
    )
    add = 4 if yusuf_sir_present else 2
    placement = _add_jihad(state, add, payload, statuses=("parias",))
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "placement": placement}


# ---------------------------------------------------------------------------
# Phase 6j: C16-C24 — Service-shift / Muster-ban / scenario events.
# ---------------------------------------------------------------------------


@register("C16")  # Bernard de Sedirac
def _c16_bernard_de_sedirac(state, side, card_id, payload):
    """C16: Shift a Lord's Service 1 box right OR Muster a Lord from
    Calendar now. (Cathedrals capability levy is a separate Capability
    half handled at Muster.)

    payload['mode']: 'service_right' (default) or 'muster'.
    payload['lord_id']: target Christian Lord (defaults greedy).
    """
    mode = payload.get("mode", "service_right")
    if mode == "muster":
        lid = payload.get("lord_id")
        cands = [l for l in state.lords.values()
                 if l.side == "christian" and l.cylinder.kind == "calendar"]
        target = state.lords.get(lid) if lid else None
        if target is None or target.side != "christian"                 or target.cylinder.kind != "calendar":
            target = cands[0] if cands else None
        if target is None:
            return _no_op_with_note(state, card_id, side,
                                    "no Christian Lord on Calendar to Muster")
        from almoravid.static_data import load_lords as _ll
        from almoravid.state import Cylinder
        rec = _ll()["lords"].get(target.id, {})
        seats = list(rec.get("seats", []))
        if not seats:
            return _no_op_with_note(state, card_id, side,
                                    f"{target.id} has no Seat")
        target.cylinder = Cylinder(kind="locale", locale_id=seats[0])
        target.forces = dict(rec.get("forces", {}))
        target.assets = dict(rec.get("assets", {}))
        target.just_arrived_this_levy = True
        state.decks.discard.append(card_id)
        return {"card_id": card_id, "side": side,
                "mustered": target.id, "seat": seats[0]}
    # service_right branch
    candidates = [
        sm for sm in state.calendar.service_markers
        if state.lords.get(sm.lord_id)
        and state.lords[sm.lord_id].side == "christian"
    ]
    if not candidates:
        return _no_op_with_note(state, card_id, side,
                                "no Christian Lord on Calendar")
    lid = payload.get("lord_id")
    target_sm = next((sm for sm in candidates if sm.lord_id == lid), None)         or min(candidates, key=lambda sm: sm.box)
    target_sm.box = min(16, target_sm.box + 1)
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "shifted_right": target_sm.lord_id,
            "new_service_box": target_sm.box}


@register("C17")  # Genoa & Pisa
def _c17_genoa_pisa(state, side, card_id, payload):
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
            l.side == "muslim" and l.cylinder.kind == "locale"
            and l.cylinder.locale_id == lid
            for l in state.lords.values()
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
def _c18_runaway_slaves(state, side, card_id, payload):
    """C18 (Hold played in Muster): Christian Lords restore Lost Foot
    units + add Transport. Mirror of M18 Refugees for the Christian
    Foot triumvirate (men_at_arms, militia, serfs)."""
    from almoravid.effective import is_besieged
    from almoravid.static_data import load_lords
    statics = load_lords()["lords"]
    restored: list[dict] = []
    for lid, l in state.lords.items():
        if l.side != "christian":
            continue
        if l.cylinder.kind != "locale":
            continue
        if is_besieged(state, lid):
            continue
        rec = statics.get(lid, {})
        starting = dict(rec.get("forces", {}))
        for v in l.vassals:
            if v.ready:
                continue
            for ut, n in v.forces.items():
                starting[ut] = starting.get(ut, 0) + n
        added: dict[str, int] = {}
        for ut in ("men_at_arms", "militia", "serfs"):
            want = starting.get(ut, 0)
            have = l.forces.get(ut, 0)
            if want > have:
                add = want - have
                l.forces[ut] = have + add
                added[ut] = add
        l.assets["mule"] = l.assets.get("mule", 0) + 1
        added["mule"] = 1
        restored.append({"lord_id": lid, "added": added})
    if not restored:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Christian Lord on map")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "restored": restored}


@register("C19")  # Fitna
def _c19_fitna(state, side, card_id, payload):
    """C19 (Immediate): Choose 2 Taifa Lords; Service -1 left each;
    this Levy, no Muster of/by them."""
    from almoravid.actions import _shift_service_left
    taifa_lords = [lid for lid, l in state.lords.items()
                   if l.is_taifa and l.side == "muslim"
                   and any(sm.lord_id == lid
                           for sm in state.calendar.service_markers)]
    if not taifa_lords:
        return _no_op_with_note(state, card_id, side,
                                "no Taifa Lord on Calendar")
    targets = sorted(taifa_lords)[:2]
    shifted = []
    for lid in targets:
        new_box = _shift_service_left(state, lid, boxes=1)
        shifted.append({"lord_id": lid, "new_service_box": new_box})
        if lid not in state.meta.muster_banned_this_levy_lord_ids:
            state.meta.muster_banned_this_levy_lord_ids.append(lid)
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "shifted": shifted}


@register("C20")  # Al-Qadir
def _c20_al_qadir(state, side, card_id, payload):
    """C20 (Hold): Remove 2 Jihad from a Reconquista or Parias Taifa
    free of Muslim Lords."""
    eligible = []
    for t in state.taifas.values():
        if t.status not in ("reconquista", "parias"):
            continue
        if any(
            l.side == "muslim" and l.cylinder.kind == "locale"
            and l.cylinder.locale_id in t.locale_ids
            for l in state.lords.values()
        ):
            continue
        for lid in t.locale_ids:
            if state.locales[lid].jihad_markers > 0:
                eligible.append((t.id, lid))
    if not eligible:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Taifa free of Muslim Lords")
    removed = 0
    for taifa_id, lid in eligible:
        loc = state.locales[lid]
        take = min(loc.jihad_markers, 2 - removed)
        loc.jihad_markers -= take
        removed += take
        if removed >= 2:
            break
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "jihad_removed": removed}


_C22_LORDS = ("al_mutawakkil", "abd_allah", "yusuf", "sir")


@register("C22")  # Berbers
def _c22_berbers(state, side, card_id, payload):
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
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "service_shifted": target, "new_service_box": new_box}


_C23_LORDS = ("abu_bakr", "al_mustain")


@register("C23")  # Illness of the Emir
def _c23_illness(state, side, card_id, payload):
    """C23: On Calendar, shift cylinder OR Service of Abu Bakr OR
    al-Mustain by 1 box; this Levy, no Muster of/by him.

    payload['mode']: 'service' (default, Service 1 box left) or
    'cylinder' (cylinder 1 box left on the Calendar).
    payload['lord_id']: abu_bakr | al_mustain.
    """
    from almoravid.actions import _shift_service_left
    mode = payload.get("mode", "service")
    eligible = [lid for lid in _C23_LORDS
                if lid in state.lords
                and any(sm.lord_id == lid
                        for sm in state.calendar.service_markers)]
    target = payload.get("lord_id") if payload.get("lord_id") in _C23_LORDS         else None
    if target is None and eligible:
        target = eligible[0]
    if target is None:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Lord on Calendar")
    result: dict = {"card_id": card_id, "side": side, "target": target,
                    "mode": mode}
    if mode == "cylinder":
        l = state.lords[target]
        if l.cylinder.kind == "calendar":
            cur = l.cylinder.box if l.cylinder.box is not None else 1
            l.cylinder.box = max(0, cur - 1)
            result["new_cylinder_box"] = l.cylinder.box
        else:
            # On the map: fall back to Service shift (cylinder branch
            # only meaningful on Calendar per card text).
            result["new_service_box"] = _shift_service_left(state, target,
                                                            boxes=1)
    else:
        result["new_service_box"] = _shift_service_left(state, target,
                                                        boxes=1)
    if target not in state.meta.muster_banned_this_levy_lord_ids:
        state.meta.muster_banned_this_levy_lord_ids.append(target)
    state.decks.discard.append(card_id)
    return result


@register("C24")  # Abu Bakr ibn Umar
def _c24_abu_bakr(state, side, card_id, payload):
    """C24: On Calendar, shift Service of Yusuf AND Sir each 1 box
    left; this Levy, no Muster of/by either."""
    from almoravid.actions import _shift_service_left
    shifted = []
    for lid in ("yusuf", "sir"):
        if lid not in state.lords:
            continue
        if not any(sm.lord_id == lid
                   for sm in state.calendar.service_markers):
            continue
        new_box = _shift_service_left(state, lid, boxes=1)
        shifted.append({"lord_id": lid, "new_service_box": new_box})
        if lid not in state.meta.muster_banned_this_levy_lord_ids:
            state.meta.muster_banned_this_levy_lord_ids.append(lid)
    if not shifted:
        return _no_op_with_note(state, card_id, side,
                                "neither Yusuf nor Sir on Calendar")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "shifted": shifted}


@register("M24")  # Al-Maghawir
def _m24_al_maghawir(state, side, card_id, payload):
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


# C21 Mozarabes — Hold, consumed during Surrender roll (auto-success).
# Park in this_levy_events; campaign.py cmd_siege Surrender path
# already checks Spoils etc. but we don't wire auto-success here in
# 6j (would require a payload from the holder at the moment of the
# Surrender roll). Stays as immediate-discard-no-op for now.
@register("C21")  # Mozarabes
def _c21_mozarabes(state, side, card_id, payload):
    """C21 (Hold): Play for a Surrender roll in a Reconquista Taifa to
    succeed automatically. Phase 6j: parks in this_levy_events for
    consumption by a future cmd_siege Mozarabes hook."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")



@register("M19")  # African Fleet
def _m19_african_fleet(state, side, card_id, payload):
    """M19 (Hold): Play for a Lord to use his Command card to March
    Port-to-Port where no Christian Lord at destination.

    Phase 6j: parks in this_levy_events. Port-to-Port March is a
    deferred follow-up — would require a new cmd_march_port_to_port
    action that consumes this Hold + the active Lord's entire card.
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")
