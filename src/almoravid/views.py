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
_PRIVATE_CONTINGENT_CARDS = {"M15", "M20"}
_LEGACY_MARCH_HOLDS = {"christian": {"C3", "C4", "C6"}, "muslim": {"M3", "M4"}}


def _other(side: Side) -> Side:
    return "muslim" if side == "christian" else "christian"


def _combat_revealed_lords(state: GameState) -> set[str]:
    """Actual participants during combat or its interactive decisions."""
    from almoravid.visibility import combat_visible_lords
    revealed = set(combat_visible_lords(state))
    pd = state.pending
    if pd is not None and pd.kind in {"combat_holds", "relief_sally", "storm_front"}:
        revealed.update(pd.payload["attacker_ids"])
        revealed.update(pd.payload["defender_ids"])
        return revealed
    if pd is None or pd.kind not in {
            "battle_concede", "storm_concede", "relief_concede", "oneround_timing",
            "battle_fate", "camp_attack"}:
        return revealed
    payload = pd.payload
    snapshots = [payload.get("attacker"), payload.get("defender")]
    relief = payload.get("rs", {})
    snapshots.extend(relief.get(key) for key in (
        "result_attacker", "result_defender"))
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
    Lords in Battle/Storm. Opponent Muster choices are screened in history;
    Advanced Vassal Service markers are public. Private cards and unused Plans are hidden
    regardless of the Hidden Mats option (1.9, 3.1.3, 4.1). The engine's
    full state remains available through GameState.model_dump()."""
    dump = state.model_dump()
    if dump.get("pending") is not None:
        pending = dump["pending"]
        payload = pending["payload"]
        if state.pending is not None and state.pending.kind == "battle_fate":
            from almoravid.battle import available_battle_fates

            pl = state.pending.payload
            available, _ = available_battle_fates(
                state, pl["options"], pl["withdraw_slots"], pl["fates"])
            payload["options"] = available
        for key in ("_wastage_resume", "_end_campaign_resume", "_severed_heads_resume",
                    "_reset_discard_resume", "_battle_spoils_resume",
                    "_retreat_provender_resume", "_combat_hold_resume", "_relief_sally_resume",
                    "_storm_front_resume", "_feed_loot", "_arid_resume",
                    "_march_resume", "_surprise_resume"):
            payload.pop(key, None)
        if pending["waiting_on"] != viewer_side:
            payload.pop("blocker_card", None)
            payload.pop("feed_options", None)
            if state.meta.hidden_mats and pending["kind"] == "devaluation_choice":
                pending["payload"] = {"card_id": payload["card_id"]}
            if state.meta.hidden_mats and pending["kind"] == "arid_terrain_choice":
                payload.pop("discard_lords", None)
        if (state.meta.hidden_mats and "eligible" in payload
                and pending["kind"] in {"greed_mule_choice", "feed_resource_choice",
                                        "pay_before_disband", "drought_choice",
                                        "arid_terrain_choice"}):
            # Old Pay saves can contain rows from the other side's Greed.
            # Each mat's owner controls visibility regardless of the current actor.
            own = [row for row in payload["eligible"]
                   if dump["lords"].get(row["lord_id"], {}).get("side") == viewer_side]
            if own:
                payload["eligible"] = own
            else:
                payload.pop("eligible")
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
    if state.meta.hidden_mats and opp == "muslim":
        cap_state = dump["meta"]["aow_cap_state"]
        for card in _PRIVATE_CONTINGENT_CARDS:
            units = cap_state.get(f"{card}_units", {})
            if units.get("lord") not in revealed:
                cap_state.pop(f"{card}_units", None)
                cap_state.pop(f"{card}_used", None)
    plan = decks["plan"].get(opp, [])
    revealed_count = getattr(state.meta, f"plan_index_{opp}")
    decks["plan"][opp] = [entry if i < revealed_count else None
                           for i, entry in enumerate(plan)]
    decks["pending_draw"][opp] = None
    decks["held"][opp] = None
    # Older saves also stored unplayed March Holds in in-play buckets.
    legacy_holds = _LEGACY_MARCH_HOLDS[opp]
    hidden_holds = set(state.decks.held.get(opp, []))
    for key in ("this_levy_events", "this_campaign_events"):
        cards = decks[key].get(opp, [])
        if legacy_holds.intersection(cards):
            hidden_holds.update(legacy_holds.intersection(cards))
            remaining = [card for card in cards if card not in legacy_holds]
            if remaining:
                decks[key][opp] = remaining
            else:
                decks[key].pop(opp)
    # Neither player may inspect the order of undrawn Arts of War cards.
    decks["draw"] = None
    if state.meta.hidden_mats:
        dump["history"] = [entry for entry in dump["history"]
                           if (entry["actor"], entry["action"]) != (opp, "devaluation_choice")]
    # Screen private choices in the action log as well as on the mats.
    for entry in dump["history"]:
        # Scenario-loading history duplicates the seed even for the system
        # actor. Strip controller RNG inputs before any ownership filtering.
        entry["args"].pop("seed", None)
        entry["args"].pop("rng_state", None)
        if entry["actor"] != opp:
            continue
        if state.meta.hidden_mats and entry["action"] in {
            "end_card", "feed_resource_choice", "drought_choice", "arid_terrain_choice",
        }:
            entry["args"].pop("feed_loot", None)
            if entry["action"] == "arid_terrain_choice":
                entry["args"].pop("discard_lords", None)
        if state.meta.hidden_mats and entry["action"] in {
            "levy_take_vassal", "levy_transport", "cap_fonsadera",
        }:
            # The Lord's expenditure is public. For Advanced Vassal Service,
            # the Calendar exposes the Vassal whose marker was placed there.
            lord_id = entry["args"].get("lord_id")
            entry["args"] = {"lord_id": lord_id} if lord_id is not None else {}
            entry["summary"] = f"{opp}: {entry['action']} (private Muster)"
            continue
        if state.meta.hidden_mats and entry["action"] in {"cap_saqalibah", "cap_al_rum"}:
            entry["action"] = "muster_capability"
            entry["args"] = {}
            entry["summary"] = f"{opp}: private Capability Muster"
            continue
        event_card = entry["args"].get("card_id")
        private_event = (entry["action"] == "aow_implement_event"
                         and (event_card is None or event_card in hidden_holds))
        private_capability = (entry["action"] in {"aow_deploy_capability",
                                                   "levy_take_capability"}
                              and event_card in hidden_cards)
        if (entry["action"] in {"plan_add_card", "aow_draw"}
                or private_event or private_capability):
            entry["args"] = {}
            entry["summary"] = f"{opp}: {entry['action']} (private cards)"
    return dump
