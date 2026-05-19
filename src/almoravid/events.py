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
    total_before = sum(l.assets.get("coin", 0) for l in muslim_lords)
    if total_before == 0:
        return _no_op_with_note(state, card_id, side,
                                "no Muslim Coin to devalue")
    target = _math.ceil(total_before * 2 / 3)
    to_remove = total_before - target
    removed = 0
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

@register("C13")  # Berenguer Ramon (Count of Barcelona / event side)
@register("M23")  # Berenguer Ramon (Muslim side)
def _berenguer_ramon(state, side, card_id, payload):
    """Berenguer Ramon: Count of Barcelona event. Held in this_levy
    bucket; Phase 5 Battle resolver consults for force-modifier bonus.
    """
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


# --- Immediate events with side-wide state effects ---


@register("C11")  # Indulgences
@register("C12")  # Song of Roland
def _crusader_event(state, side, card_id, payload):
    """C11 Indulgences / C12 Song of Roland: immediate, Muster 1
    Crusaders marker onto any unbesieged Christian Lord. Also forces
    Eudes (if on map and Unbesieged) to Muster all Ready Vassals.

    Phase 5j: validates a target Christian Lord; records the
    intent. Crusader-marker placement and forced-Eudes-Vassal-Muster
    are Phase 5j+ once the Crusaders model lands in state.
    """
    target_lord_id = payload.get("target_lord_id")
    available_christians = [
        l.id for l in state.lords.values()
        if l.side == "christian"
        and l.cylinder.kind == "locale"
    ]
    if not available_christians:
        return _no_op_with_note(state, card_id, side,
                                "no unbesieged Christian Lord available")
    if target_lord_id and target_lord_id not in available_christians:
        return _no_op_with_note(state, card_id, side,
                                f"target {target_lord_id} not eligible")
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "target": target_lord_id or available_christians[0],
            "deferred": "phase_5j_plus"}


@register("C14")  # Pope Gregory
def _pope_gregory(state, side, card_id, payload):
    """Pope Gregory: hold-event eligibility on Sancho (Pope Gregory cap).
    Phase 5j: held in this_levy_events; resolver hook for Sancho's
    capability bonus."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C15")  # Cluniacs
@register("M9")   # Maliki Islam
@register("M20")  # Mudejares
def _religious_hold(state, side, card_id, payload):
    """Religious hold events: persistent through some window. Buffered
    in this_levy_events; specific mechanics in Phase 5j+."""
    return _move_to_hold_bucket(state, card_id, side, "this_levy_events")


@register("C16")  # Bernard de Sedirac
@register("C17")  # Genoa & Pisa send fleets
@register("C18")  # Runaway Slaves
@register("C19")  # Fitna
@register("C20")  # Al-Qadir
@register("C21")  # Mozarabes
@register("C22")  # Berbers
@register("C23")  # Illness of the Emir
@register("C24")  # Abu Bakr ibn Umar
@register("M19")  # African Fleet
@register("M24")  # Al-Maghawir
def _generic_immediate(state, side, card_id, payload):
    """Immediate events with side-wide or scenario-specific effects.

    Phase 5j: discard with a deferred note. Per CROSS_PROJECT_LESSONS
    Pattern 10, these resolvers do NOT raise even if the effect isn't
    fully wired — the card discards cleanly and the agent moves on.
    The specific mechanics land per-card as agents exercise them and
    the implementation pressure points itself.
    """
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "deferred": "phase_5j_plus"}


# --- Rodrigo (El Cid) family ---


@register("C25")  # De Vivar
@register("M10")  # Fatwa (immediate Muslim)
def _de_vivar(state, side, card_id, payload):
    """C25 De Vivar / M10 Fatwa: scenario-specific effects.
    Phase 5j: structural no-op."""
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "deferred": "phase_5j_plus"}


@register("C26")  # Freebooter
@register("M13")  # Severed Heads
def _hostile_event(state, side, card_id, payload):
    """C26 Freebooter / M13 Severed Heads: structural no-op for Phase 5j."""
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side, "deferred": "phase_5j_plus"}


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
    parias_taifas = [t for t in state.taifas.values()
                     if t.status == "parias"]
    if not parias_taifas:
        return _no_op_with_note(state, card_id, side,
                                "no Parias Taifa available")
    locale_id = payload.get("locale_id")
    if locale_id is None:
        # Pick first Parias Taifa's first locale deterministically.
        locale_id = parias_taifas[0].locale_ids[0]
    loc = state.locales.get(locale_id)
    if loc is None:
        return _no_op_with_note(state, card_id, side,
                                f"unknown locale {locale_id!r}")
    # Validate the locale's territory is a Parias Taifa.
    in_parias = any(locale_id in t.locale_ids for t in parias_taifas)
    if not in_parias:
        return _no_op_with_note(state, card_id, side,
                                f"{locale_id} not in a Parias Taifa")
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


def _first_jihad_eligible_locale(
    state: GameState, taifa_filter: tuple[str, ...] = ("parias", "reconquista")
) -> str | None:
    """Pick the first locale (deterministic) in a Taifa matching filter.

    Used by M8/M11/M22 for Jihad placement when no payload target is
    provided. Returns None when no eligible locale exists.
    """
    for taifa in state.taifas.values():
        if taifa.status not in taifa_filter:
            continue
        for lid in taifa.locale_ids:
            return lid
    return None


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
    # add_jihad branch
    target_loc = payload.get("locale_id")         or _first_jihad_eligible_locale(state)
    if target_loc is None or target_loc not in state.locales:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.locales[target_loc].jihad_markers += 2
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": 2, "locale_id": target_loc}


@register("M11")  # Al-Qadir balks at payment
def _m11_al_qadir(state, side, card_id, payload):
    """M11 (Hold): Add 1 Jihad OR — if Yusuf or Sir in any Reconquista
    or Parias Taifa or Kingdom — 3 Jihad.
    """
    bonus_active = False
    for lid in ("yusuf", "sir"):
        l = state.lords.get(lid)
        if l is None or l.cylinder.kind != "locale":
            continue
        loc = state.locales.get(l.cylinder.locale_id)
        if loc is None:
            continue
        # Check Taifa status if in a Taifa.
        for t in state.taifas.values():
            if l.cylinder.locale_id in t.locale_ids                     and t.status in ("reconquista", "parias"):
                bonus_active = True
                break
        else:
            # Not in a Taifa — check if in a Kingdom (territory "leon"
            # or "aragon"). Treat any non-Taifa territory as Kingdom.
            if loc.territory in ("leon", "aragon"):
                bonus_active = True
        if bonus_active:
            break
    add = 3 if bonus_active else 1
    target_loc = payload.get("locale_id")         or _first_jihad_eligible_locale(state)
    if target_loc is None or target_loc not in state.locales:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.locales[target_loc].jihad_markers += add
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "locale_id": target_loc,
            "bonus": bonus_active}


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
    bonus = (eudes is not None and eudes.cylinder.kind == "locale")
    add = 3 if bonus else 1
    target_loc = payload.get("locale_id")         or _first_jihad_eligible_locale(state)
    if target_loc is None or target_loc not in state.locales:
        return _no_op_with_note(state, card_id, side,
                                "no eligible Jihad locale")
    state.locales[target_loc].jihad_markers += add
    state.decks.discard.append(card_id)
    return {"card_id": card_id, "side": side,
            "jihad_added": add, "locale_id": target_loc,
            "bonus": bonus}
