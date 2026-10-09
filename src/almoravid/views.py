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


def _combat_revealed_locales(state: GameState) -> set[str]:
    """Locales whose Lords are currently in Battle/Storm (mats face-up,
    1.5.2), including the pauses between interactive combat rounds."""
    pd = state.pending
    out: set[str] = set()
    if pd is not None and pd.kind in {
        "march_arrival_response", "battle_concede", "storm_concede",
        "relief_concede",
    }:
        loc = pd.payload.get("locale_id", pd.payload.get("here"))
        if isinstance(loc, str):
            out.add(loc)
    return out


def redacted_view(state: GameState, viewer_side: Side) -> dict[str, Any]:
    """Return `state` as a dict from `viewer_side`'s perspective.

    With Hidden Mats on, the opponent's on-map Lords have their strength fields hidden
    (replaced by None) and a `hidden_mat: True` flag added, except for
    Lords in Battle/Storm. Private cards and unused Plans are hidden
    regardless of the Hidden Mats option (1.9, 3.1.3, 4.1). The engine's
    full state remains available through GameState.model_dump()."""
    dump = state.model_dump()
    opp = _other(viewer_side)
    revealed = _combat_revealed_locales(state)
    for _lid, lord in dump["lords"].items():
        if not state.meta.hidden_mats or lord.get("side") != opp:
            continue
        cyl = lord.get("cylinder", {})
        on_map = cyl.get("kind") == "locale"
        if not on_map:
            continue
        if cyl.get("locale_id") in revealed:
            continue  # in Battle/Storm -> mat is face-up
        for f in _HIDDEN_LORD_FIELDS:
            if f in lord:
                lord[f] = None
        lord["hidden_mat"] = True
    # The opponent's unused Command cards are private even with open Mats.
    # Keep revealed entries visible, and preserve the public stack size.
    decks = dump["decks"]
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
        if entry["actor"] != opp:
            continue
        event_card = entry["args"].get("card_id")
        private_event = (entry["action"] == "aow_implement_event"
                         and (event_card is None
                              or event_card in state.decks.held.get(opp, [])))
        if entry["action"] in {"plan_add_card", "aow_draw"} or private_event:
            entry["args"] = {}
            entry["summary"] = f"{opp}: {entry['action']} (private cards)"
    return dump
