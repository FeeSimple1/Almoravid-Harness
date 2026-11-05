"""Cross-game ALM-01/02: Way-specific Shared Transport and M16 Camels."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import BattleResult, BattleSide, apply_retreat_aftermath
from almoravid.campaign import _is_laden, _march_load
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, GameState, PendingDecision


def fresh(camels=False):
    state = load_scenario("scenario_f_reconquista", seed=7)
    for lord in state.lords.values():
        lord.cylinder = Cylinder(kind="mat")
        lord.in_stronghold = False
        lord.assets = {}
        lord.forces = {"militia": 1}
        lord.capabilities = []
    state.decks.held = {"christian": [], "muslim": []}
    state.decks.this_levy_events = {"christian": [], "muslim": []}
    state.decks.this_campaign_events = {"christian": [], "muslim": []}
    state.decks.capabilities_in_play = []
    if camels:
        state.decks.capabilities_in_play.append(
            CardInPlay(card_id="M16", scope="side_wide", owner_side="muslim"))
    state.meta.phase = "campaign"
    state.meta.campaign_step = "activation"
    state.meta.active_player = "muslim"
    state.meta.active_lord_id = "yusuf"
    state.meta.actions_remaining = 2
    state.pending = None
    return state


def place(state, lid, locale, **assets):
    lord = state.lords[lid]
    lord.cylinder = Cylinder(kind="locale", locale_id=locale)
    lord.assets = dict(assets)
    return lord


def retreat(state, losers, where="la_mancha", origin="zancara", way="road", conceded=True):
    for lid in ["alfonso", *losers]:
        state.lords[lid].cylinder = Cylinder(kind="locale", locale_id=where)
    attacker = BattleSide(side="muslim", role="attacker", lord_ids=losers,
                          forces={"militia": len(losers)}, conceded=conceded)
    defender = BattleSide(side="christian", role="defender", lord_ids=["alfonso"],
                          forces={"militia": 1})
    result = BattleResult(engagement="battle", attacker=attacker,
                          defender=defender, winner="christian")
    return apply_retreat_aftermath(state, result, approach_from_locale=origin,
                                   approach_way_type=way)


@pytest.mark.parametrize("way,lid,assets,camels,kept", [
    ("pass", "yusuf", {"cart": 1, "prov": 1}, False, 0),
    ("pass", "yusuf", {"cart": 1, "mule": 1, "prov": 2}, False, 1),
    ("pass", "yusuf", {"mule": 1, "prov": 2}, False, 1),
    ("pass", "yusuf", {"mule": 1, "prov": 2}, True, 2),
    ("road", "sir", {"mule": 1, "prov": 2}, True, 2),
    ("road", "yusuf", {"cart": 1, "mule": 1, "prov": 2}, False, 2),
    ("road", "al_mutamid", {"mule": 1, "prov": 2}, True, 1),
])
def test_conceded_retreat_uses_actual_way_and_only_eligible_camels(way, lid, assets, camels, kept):
    state = fresh(camels)
    state.lords[lid].assets = {**assets, "loot": 1, "coin": 2}
    where, origin = ("somosierra", "madrid") if way == "pass" else ("la_mancha", "zancara")
    result = retreat(state, [lid], where, origin, way)
    lord = state.lords[lid]
    assert lord.assets.get("prov", 0) == kept
    assert state.lords["alfonso"].assets.get("prov", 0) == assets["prov"] - kept
    assert lord.assets.get("loot", 0) == 0 and lord.assets["coin"] == 2
    assert state.lords["alfonso"].assets["loot"] == 1
    assert result["losers"][0]["retreat_way"] == way


@pytest.mark.parametrize("way,transport,camels,kept", [
    ("road", {"mule": 2}, False, 2),
    ("pass", {"mule": 2}, False, 2),
    ("pass", {"cart": 2}, False, 0),
    ("road", {"mule": 1}, True, 2),
    ("pass", {"mule": 1}, True, 2),
])
def test_conceding_group_shares_spare_transport_without_moving_food_between_mats(
        way, transport, camels, kept):
    state = fresh(camels)
    state.lords["yusuf"].assets = {"prov": 2}
    state.lords["sir"].assets = transport
    where, origin = ("somosierra", "madrid") if way == "pass" else ("la_mancha", "zancara")
    result = retreat(state, ["yusuf", "sir"], where, origin, way)
    assert state.lords["yusuf"].assets.get("prov", 0) == kept
    assert state.lords["sir"].assets.get("prov", 0) == 0
    assert state.lords["alfonso"].assets.get("prov", 0) == 2 - kept
    assert all(e["retreat_to"] == origin for e in result["losers"])
    assert GameState.model_validate_json(state.model_dump_json()) == state


def test_group_reserves_each_lords_own_loaded_transport_before_sharing():
    state = fresh()
    state.lords["sir"].assets = {"mule": 2, "prov": 2}
    state.lords["yusuf"].assets = {"mule": 1, "prov": 3}
    retreat(state, ["yusuf", "sir"])
    assert state.lords["sir"].assets["prov"] == 2
    assert state.lords["yusuf"].assets["prov"] == 1
    assert state.lords["alfonso"].assets["prov"] == 2


def test_lord_remaining_at_battle_locale_cannot_share_retreat_transport():
    state = fresh()
    state.lords["yusuf"].assets = {"prov": 2}
    place(state, "sir", "la_mancha", mule=10)
    retreat(state, ["yusuf"])
    assert state.lords["yusuf"].assets.get("prov", 0) == 0
    assert state.lords["alfonso"].assets["prov"] == 2


def test_withdrawing_lord_cannot_share_transport_with_retreating_lord():
    state = fresh()
    state.lords["sir"].assets = {"mule": 10}
    state.lords["yusuf"].assets = {"prov": 2}
    result = retreat(state, ["sir", "yusuf"], "trujillo", "talavera")
    assert result["losers"][0]["fate"] == "withdraw"
    assert result["losers"][1]["fate"] == "retreat"
    assert state.lords["yusuf"].assets.get("prov", 0) == 0


def test_nonconceding_retreat_still_loses_all_assets_despite_shared_capacity():
    state = fresh(True)
    state.lords["yusuf"].assets = {"prov": 2, "coin": 1}
    state.lords["sir"].assets = {"mule": 2}
    retreat(state, ["yusuf", "sir"], conceded=False)
    assert not state.lords["yusuf"].assets and not state.lords["sir"].assets
    assert state.lords["alfonso"].assets == {"prov": 2, "coin": 1, "mule": 2}


@pytest.mark.parametrize("way,lid,camels,kept", [
    ("road", "yusuf", True, 2), ("pass", "sir", True, 2),
    ("road", "al_mutamid", True, 1), ("pass", "yusuf", False, 1),
])
def test_public_avoid_retains_camels_capacity_and_sends_only_excess_to_enemy(
        way, lid, camels, kept):
    state = fresh(camels)
    where, target, origin = (("somosierra", "madrid", "penafiel") if way == "pass"
                             else ("sahagun", "leon", "burgos"))
    loser = place(state, lid, where, mule=1, prov=2, loot=1)
    winner = place(state, "alfonso", where)
    state.meta.active_lord_id = winner.id
    state.pending = PendingDecision(kind="march_arrival_response", waiting_on="muslim", payload={
        "locale_id": where, "from_locale_id": origin, "via_way_type": way,
        "active_side": "christian", "active_lord_id": winner.id,
        "defender_lord_ids": [lid]})
    result = apply_action(state, {"type": "respond_avoid_battle", "side": "muslim",
                                 "target_locale_id": target, "way_type": way})
    result = apply_action(state, {"type": "respond_swollen_river_block",
                          "side": state.pending.waiting_on, "play": False})
    assert loser.cylinder.locale_id == target and loser.moved_fought
    assert loser.assets.get("prov", 0) == kept
    assert result["discarded_as_spoils"].get("prov", 0) == 2 - kept
    assert winner.assets.get("prov", 0) == 2 - kept
    assert winner.assets["loot"] == 1


def test_public_approach_concession_uses_shared_camels_on_retreat():
    state = fresh(True)
    place(state, "yusuf", "la_mancha", prov=2)
    place(state, "sir", "la_mancha", mule=1)
    place(state, "alfonso", "la_mancha")
    state.meta.active_player = "christian"
    state.pending = PendingDecision(kind="march_arrival_response", waiting_on="christian", payload={
        "locale_id": "la_mancha", "from_locale_id": "zancara", "via_way_type": "road",
        "active_side": "muslim", "active_lord_id": "yusuf", "defender_lord_ids": ["alfonso"]})
    result = apply_action(state, {"type": "respond_stand_battle", "side": "christian",
                                 "attacker_concede_round": 1})
    assert result["winner"] == "christian"
    assert state.lords["yusuf"].cylinder.locale_id == "zancara"
    assert state.lords["yusuf"].assets["prov"] == 2
    assert state.lords["alfonso"].assets.get("prov", 0) == 0


def test_pass_march_cannot_hide_double_loaded_mule_behind_empty_cart():
    state = fresh()
    lord = place(state, "alfonso", "somosierra", mule=1, cart=1, prov=2)
    place(state, "yusuf", "sevilla")
    state.meta.active_player = "christian"
    state.meta.active_lord_id = lord.id
    assert _is_laden(lord, "pass") and _march_load(state, [lord.id], "pass") == (True, 0)
    before = state.model_dump_json()
    state.meta.actions_remaining = 1
    rejected = state.model_dump_json()
    action = {"type": "cmd_march", "side": "christian",
              "target_locale_id": "madrid", "way_type": "pass"}
    with pytest.raises(IllegalAction, match="March costs 2"):
        apply_action(state, action)
    assert state.model_dump_json() == rejected
    state = GameState.model_validate_json(before)
    result = apply_action(state, action)
    assert result["laden"] and result["cost"] == 2
    assert state.lords["alfonso"].assets["prov"] == 2
