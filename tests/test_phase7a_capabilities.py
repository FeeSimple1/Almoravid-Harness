"""Phase 7a: capability effects — Command +1, Andalusians, Siege
Towers, Adalides, Camels, Dawud, War Drums."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.capabilities import effective_command
from almoravid.battle import (
    BattleSide, _resolve_protection_roll, resolve_storm,
)
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder
from tests._plan_helpers import legal_pad, step_levy


def _give_this_lord_cap(s, lord_id, card_id):
    s.lords[lord_id].capabilities.append(card_id)
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id=card_id, scope="this_lord",
        owner_side=s.lords[lord_id].side, owner_lord_id=lord_id))


def _give_side_cap(s, side, card_id):
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id=card_id, scope="side_wide", owner_side=side,
        owner_lord_id=None))


# ---------------------------------------------------------------------------
# Mesnada / Hasham Command +1
# ---------------------------------------------------------------------------


def test_mesnada_grants_command_plus_one_with_knights() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    base = s.lords["alfonso"].command_rating
    s.lords["alfonso"].forces = {"knights": 1}
    assert effective_command(s, "alfonso") == base
    _give_this_lord_cap(s, "alfonso", "C11")  # Mesnada
    assert effective_command(s, "alfonso") == base + 1


def test_mesnada_no_bonus_without_knights() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    base = s.lords["alfonso"].command_rating
    s.lords["alfonso"].forces = {"men_at_arms": 2}  # no Knights
    _give_this_lord_cap(s, "alfonso", "C12")  # Mesnada
    assert effective_command(s, "alfonso") == base


def test_hasham_grants_command_plus_one_with_horse() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord_id = "al_mutamid"
    base = s.lords[lord_id].command_rating
    s.lords[lord_id].forces = {"light_horse": 1}
    _give_this_lord_cap(s, lord_id, "M11")  # Hasham
    assert effective_command(s, lord_id) == base + 1


def test_command_reveal_uses_effective_command() -> None:
    """The actions_remaining at reveal should reflect Mesnada +1."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    side = "christian"
    other = "muslim"
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    s.lords["alfonso"].forces = {"knights": 2}
    _give_this_lord_cap(s, "alfonso", "C11")
    base = s.lords["alfonso"].command_rating
    apply_action(s, {"type": "plan_add_card", "side": side,
                     "plan_kind": "command", "lord_id": "alfonso"})
    legal_pad(s, side)
    legal_pad(s, other)
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == "alfonso":
            break
        r = apply_action(s, {"type": "command_reveal",
                             "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != "alfonso":
            apply_action(s, {"type": "end_card",
                             "side": s.meta.active_player})
    assert s.meta.active_lord_id == "alfonso"
    assert s.meta.actions_remaining == base + 1


# ---------------------------------------------------------------------------
# Andalusians (M10) Light Horse Evade 1-3
# ---------------------------------------------------------------------------


def test_andalusians_light_horse_evades_more() -> None:
    """Over many seeds, Muslim Light Horse survive Battle Melee more
    often with M10 Andalusians in play."""
    surv_with = surv_without = 0
    for seed in range(40):
        for cap in (False, True):
            s = load_scenario("scenario_a_toledo_beset", seed=seed)
            dfd = BattleSide(side="muslim", role="defender",
                             lord_ids=["al_mutamid"],
                             forces={"light_horse": 6})
            if cap:
                _give_side_cap(s, "muslim", "M10")
            # 6 melee Hits against the Light Horse pool.
            for _ in range(6):
                if not dfd.has_unrouted():
                    break
                _resolve_protection_roll(s, dfd, "melee", context="battle")
            survivors = dfd.forces.get("light_horse", 0)
            if cap:
                surv_with += survivors
            else:
                surv_without += survivors
    assert surv_with > surv_without


# ---------------------------------------------------------------------------
# Dawud ibn Aisha (M8) Supply +1 Prov
# ---------------------------------------------------------------------------


def test_dawud_supply_amount_via_handler() -> None:
    """Dawud ibn Aisha (M8): the Lord's Supply adds +2 Prov (1 base +
    1 extra). Set up an activation state directly to avoid scenario-
    specific plan-size plumbing."""
    s = load_scenario("scenario_d_arrival", seed=1)
    assert "yusuf" in s.lords
    from almoravid.static_data import load_lords
    seats = load_lords()["lords"]["yusuf"].get("seats", [])
    assert seats, "yusuf has no seat"
    seat = seats[0]
    s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id=seat)
    s.lords["yusuf"].in_stronghold = False
    s.lords["yusuf"].assets = {"prov": 1}
    _give_this_lord_cap(s, "yusuf", "M8")
    # Hand-set the campaign-activation context.
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "muslim"
    s.meta.active_lord_id = "yusuf"
    s.meta.actions_remaining = 2
    r = apply_action(s, {"type": "cmd_supply", "side": "muslim"})
    # Dawud => +2 Prov instead of +1 (1 base seat + 1 Dawud).
    assert s.lords["yusuf"].assets.get("prov", 0) == 3


# ---------------------------------------------------------------------------
# Camels (M16) negates Arid Terrain
# ---------------------------------------------------------------------------


def test_camels_negates_arid_terrain() -> None:
    from tests.test_phase6h_tier_a import _setup_active_lord
    # Muslim marches; Christian holds C4 Arid Terrain; Muslim has Camels.
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    assert "al_mutamid" in s.lords
    s2 = _setup_active_lord("scenario_a_toledo_beset", "al_mutamid",
                            "sevilla", seed=11)
    s2.decks.this_levy_events["christian"] = ["C4"]
    _give_side_cap(s2, "muslim", "M16")  # Camels
    s2.lords["al_mutamid"].assets = {"prov": 3, "mule": 2}  # transport so 1.7.2 keeps prov
    s2.lords["al_mutamid"].forces = {"sergeants": 2, "men_at_arms": 2}
    from almoravid.map import neighbors_via
    target = neighbors_via("sevilla", "road")[0]
    prov_before = s2.lords["al_mutamid"].assets.get("prov", 0)
    apply_action(s2, {"type": "cmd_march", "side": "muslim",
                      "target_locale_id": target, "way_type": "road"})
    # Camels discarded; no Feed -> Prov unchanged.
    assert s2.lords["al_mutamid"].assets.get("prov", 0) == prov_before
    assert "M16" in s2.decks.discard
