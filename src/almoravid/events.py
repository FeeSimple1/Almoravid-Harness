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
@register("C5")  # Drought
@register("M5")
def _arid_or_drought(state, side, card_id, payload):
    """Hold-event terrain modifiers. Phase 5 combat / supply hooks."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


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
def _betrayal_of_terms(state, side, card_id, payload):
    """Immediate event affecting a Siege. Pattern 10: no active Siege ->
    no-op. Phase 5 will check Siege markers; for now we no-op-and-note."""
    has_siege = any(
        (loc.siege_yellow or loc.siege_green) > 0
        for loc in state.locales.values()
    )
    if not has_siege:
        return _no_op_with_note(state, card_id, side,
                                "no active Siege; immediate event discards")
    # Phase 5 implements the actual effect; for now place in immediate-discard
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "deferred": "phase_5"}


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
def _taifa_marriage(state, side, card_id, payload):
    """TAIFA MARRIAGE (Muslim, scenario A/F): adjusts Taifa status.

    Phase 4b minimal implementation: target a named Taifa (payload
    'taifa_id'). If target Taifa is Parias and condition met, can shift
    its status. Pattern 10: missing/invalid target -> no-op.

    The full rule wording is in the Background Book; this stub records
    the play and defers detailed mechanics to Phase 5.
    """
    taifa_id = payload.get("taifa_id")
    if not taifa_id or taifa_id not in state.taifas:
        return _no_op_with_note(state, card_id, side,
                                f"taifa target {taifa_id!r} invalid")
    # Phase 5 will implement: shift target Taifa status, place Conquered
    # marker, etc. For now record-and-discard so the agent can play it.
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "target_taifa": taifa_id,
            "deferred": "phase_5"}


@register("M21")  # Al-Sumaisir
def _al_sumaisir(state, side, card_id, payload):
    """AL-SUMAISIR (Muslim, scenario B): poet reproaches emirs. Phase 4b
    records the play and defers effects (VP adjustment / mat flips)."""
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "deferred": "phase_5"}


@register("C10")  # Devaluation (Christian)
@register("M14")  # Devaluation (Muslim)
def _devaluation(state, side, card_id, payload):
    """Devaluation: target side discards Coin. Pattern 10: target side
    has no Coin -> no-op."""
    target_side: Side = "muslim" if side == "christian" else "christian"
    target_lords = [l for l in state.lords.values()
                    if l.side == target_side
                    and l.cylinder.kind == "locale"
                    and l.assets.get("coin", 0) > 0]
    if not target_lords:
        return _no_op_with_note(state, card_id, side,
                                f"{target_side} has no Coin to devalue")
    # Phase 5 will implement actual coin removal per rule text.
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "target_lord_ids": [l.id for l in target_lords],
            "deferred": "phase_5"}


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
