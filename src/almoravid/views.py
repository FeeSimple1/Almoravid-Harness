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
    1.5.2). The engine resolves combat atomically, so the only
    persistent pre-combat state is a pending Approach Battle / Relief
    Sally / Sortie (march_arrival_response) at a locale."""
    pd = state.pending
    out: set[str] = set()
    if pd is not None and pd.kind == "march_arrival_response":
        loc = pd.payload.get("locale_id")
        if isinstance(loc, str):
            out.add(loc)
    return out


def redacted_view(state: GameState, viewer_side: Side) -> dict[str, Any]:
    """Return `state` as a dict from `viewer_side`'s perspective.

    With Hidden Mats off (default), this is the full state dump. With it
    on, the opponent's on-map Lords have their strength fields hidden
    (replaced by None) and a `hidden_mat: True` flag added, except for
    Lords in Battle/Storm. The opponent's pending-draw hand stays hidden
    too (you never see the enemy's drawn-but-unplayed Arts of War cards,
    1.9 "Players may not inspect each other's decks")."""
    dump = state.model_dump()
    if not state.meta.hidden_mats:
        return dump
    opp = _other(viewer_side)
    revealed = _combat_revealed_locales(state)
    for lid, lord in dump["lords"].items():
        if lord.get("side") != opp:
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
    # The opponent's just-drawn (pending) Arts of War cards are private.
    if "decks" in dump and "pending_draw" in dump["decks"]:
        dump["decks"]["pending_draw"][opp] = None
    return dump
