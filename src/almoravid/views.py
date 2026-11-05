"""Player-facing redacted views (1.5.2 Hidden Mats Option).

The engine itself always holds full information. When the optional
Hidden Mats fog-of-war rule is enabled (meta.hidden_mats), a player
should only be shown a REDACTED view of the opponent: a Mustered
(on-map) Lord's strength — his Forces, Assets, Vassals, "This Lord"
Capabilities and Routed units — is hidden behind a screen, EXCEPT
when that Lord is in Battle or Storm (1.5.2 / 4.4 / 4.5.2). Side-wide
Capabilities remain revealed (3.4.4). A Lord's identity, ratings, and
map position (cylinder) are public and stay visible.

This is purely a presentation/serialisation concern — it does NOT
change rules, legal moves, or resolution (which use full state).
"""
from __future__ import annotations

from typing import Any

from almoravid.state import GameState, Side

_HIDDEN_LORD_FIELDS = ("forces", "assets", "routed_units", "capabilities",
                       "vassals")


def _other(side: Side) -> Side:
    return "muslim" if side == "christian" else "christian"


def _combat_revealed_lords(state: GameState) -> set[str]:
    """Actual participants during combat or its interactive decisions."""
    from almoravid.visibility import combat_visible_lords
    revealed = set(combat_visible_lords(state))
    pd = state.pending
    if pd is None or pd.kind not in {
            "battle_concede", "storm_concede", "relief_concede", "oneround_timing"}:
        return revealed
    payload = pd.payload
    snapshots = [payload.get("attacker"), payload.get("defender")]
    relief = payload.get("rs", {})
    snapshots.extend(relief.get(key) for key in (
        "marchers", "sallyers", "def_front", "def_rear"))
    participants = {lid for snap in snapshots if isinstance(snap, dict)
                    for lid in snap.get("lord_ids", [])}
    if participants:
        revealed.update(participants)
    else:
        # Compatibility for older pending saves that only name the Locale.
        locale = payload.get("locale_id", payload.get("here"))
        revealed.update(lid for lid, lord in state.lords.items()
                        if lord.cylinder.kind == "locale" and lord.cylinder.locale_id == locale)
    return revealed


def redacted_view(state: GameState, viewer_side: Side) -> dict[str, Any]:
    """Return `state` as a dict from `viewer_side`'s perspective.

    With Hidden Mats on, the opponent's on-map Lords have their strength fields hidden
    (replaced by None) and a `hidden_mat: True` flag added, except for
    Lords in Battle/Storm. Private cards and unused Plans are hidden
    regardless of the Hidden Mats option (1.9, 3.1.3, 4.1). The engine's
    full state remains available through GameState.model_dump()."""
    dump = state.model_dump()
    if dump.get("pending") is not None:
        for key in ("_wastage_resume", "_end_campaign_resume", "_severed_heads_resume"):
            dump["pending"]["payload"].pop(key, None)
        if dump["pending"]["waiting_on"] != viewer_side:
            dump["pending"]["payload"].pop("blocker_card", None)
    # Controller saves retain RNG inputs; player snapshots must not expose
    # enough information to reconstruct future dice or shuffles.
    dump["meta"].pop("seed", None)
    dump["meta"].pop("rng_state", None)
    opp = _other(viewer_side)
    revealed = _combat_revealed_lords(state)
    for _lid, lord in dump["lords"].items():
        if not state.meta.hidden_mats or lord.get("side") != opp:
            continue
        cyl = lord.get("cylinder", {})
        on_map = cyl.get("kind") == "locale"
        if not on_map:
            continue
        if _lid in revealed:
            continue  # in Battle/Storm -> mat is face-up
        for f in _HIDDEN_LORD_FIELDS:
            if f in lord:
                lord[f] = None
        lord["hidden_mat"] = True
    # The opponent's unused Command cards are private even with open Mats.
    # Keep revealed entries visible, and preserve the public stack size.
    decks = dump["decks"]
    # This-Lord cards also live in the global registry. Apply the same
    # combat/ownership mask as the mat, without hiding public side-wide cards.
    hidden_cards = {c["card_id"] for c in decks["capabilities_in_play"]
                    if c["scope"] == "this_lord"
                    and dump["lords"].get(c["owner_lord_id"], {}).get("hidden_mat")}
    decks["capabilities_in_play"] = [c for c in decks["capabilities_in_play"]
                                     if c["card_id"] not in hidden_cards]
    plan = decks["plan"].get(opp, [])
    revealed_count = getattr(state.meta, f"plan_index_{opp}")
    decks["plan"][opp] = [entry if i < revealed_count else None
                           for i, entry in enumerate(plan)]
    decks["pending_draw"][opp] = None
    decks["held"][opp] = None
    # Neither player may inspect the order of undrawn Arts of War cards.
    decks["draw"] = None
    # The action log must not provide a second route to the hidden cards.
    for entry in dump["history"]:
        # Scenario-loading history duplicates the seed even for the system
        # actor. Strip controller RNG inputs before any ownership filtering.
        entry["args"].pop("seed", None)
        entry["args"].pop("rng_state", None)
        if entry["actor"] != opp:
            continue
        event_card = entry["args"].get("card_id")
        private_event = (entry["action"] == "aow_implement_event"
                         and (event_card is None
                              or event_card in state.decks.held.get(opp, [])))
        private_capability = (entry["action"] in {"aow_deploy_capability",
                                                   "levy_take_capability"}
                              and event_card in hidden_cards)
        if (entry["action"] in {"plan_add_card", "aow_draw"}
                or private_event or private_capability):
            entry["args"] = {}
            entry["summary"] = f"{opp}: {entry['action']} (private cards)"
    return dump
