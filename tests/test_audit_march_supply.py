"""Audit findings 13–17: real movement/Supply outcomes and menu parity.

Authority: Rules of Play 4.3.1–4.3.5 / 4.6.1 and Arts of War M8/M16/M19.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.capabilities import effective_command
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def _active(lord_id, locale_id, assets=None, actions=None):
    state = load_scenario("scenario_f_reconquista", seed=1)
    for lord in state.lords.values():
        lord.cylinder = Cylinder(kind="calendar", box=1)
        lord.lieutenant_of = None
        lord.is_lieutenant = False
        lord.in_stronghold = False
        lord.assets = {}
    lord = state.lords[lord_id]
    enemy, enemy_locale = (("alfonso", "leon") if lord.side == "muslim"
                           else ("al_mutamid", "sevilla"))
    state.lords[enemy].cylinder = Cylinder(kind="locale", locale_id=enemy_locale)
    lord.cylinder = Cylinder(kind="locale", locale_id=locale_id)
    lord.assets = assets or {}
    state.meta.phase = "campaign"
    state.meta.campaign_step = "activation"
    state.meta.active_player = lord.side
    state.meta.active_lord_id = lord_id
    state.meta.actions_remaining = (effective_command(state, lord_id)
                                    if actions is None else actions)
    return state


def _cap(state, card):
    state.decks.capabilities_in_play.append(
        CardInPlay(card_id=card, scope="side_wide", owner_side="muslim"))


@pytest.mark.parametrize("prov,cost", [(2, 1), (4, 2), (6, 2)])
def test_camels_march_capacity_and_menu_match(prov, cost):
    state = _active("yusuf", "algeciras", {"mule": 1, "prov": prov}, actions=cost)
    _cap(state, "M16")
    move = {"type": "cmd_march", "side": "muslim",
            "target_locale_id": "jerez", "way_type": "road"}
    assert move in legal_moves(state)
    result = apply_action(state, move)
    assert result["cost"] == cost
    assert state.lords["yusuf"].assets["prov"] == min(prov, 4)


def test_camels_does_not_double_taifa_mules():
    state = _active("al_mutamid", "sevilla", {"mule": 1, "prov": 4})
    _cap(state, "M16")
    result = apply_action(state, {"type": "cmd_march", "side": "muslim",
                                  "target_locale_id": "jerez", "way_type": "road"})
    assert result["cost"] == 2
    assert state.lords["al_mutamid"].assets["prov"] == 2


def test_arid_discards_camels_after_the_completed_march():
    """C4 Tips permit play just after March; later Marches lose M16 capacity."""
    state = _active("yusuf", "algeciras", {"mule": 1, "prov": 4})
    _cap(state, "M16")
    state.decks.held["christian"] = ["C4"]
    apply_action(state, {"type": "cmd_march", "side": "muslim",
                         "target_locale_id": "jerez", "way_type": "road"})
    assert state.lords["yusuf"].assets["prov"] == 4
    assert "M16" in state.decks.discard and "C4" in state.decks.discard
    state.meta.actions_remaining = 2
    apply_action(state, {"type": "cmd_march", "side": "muslim",
                         "target_locale_id": "sevilla", "way_type": "road"})
    assert state.lords["yusuf"].assets["prov"] == 2


@pytest.mark.parametrize("blocker", ["stronghold", "lord"])
def test_enemy_at_source_seat_blocks_supply_menu_and_execution(blocker):
    state = _active("alfonso", "sahagun", {"mule": 1})
    if blocker == "stronghold":
        state.locales["leon"].conquered_markers = 3
    else:
        state.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="leon")
    move = {"type": "cmd_supply", "side": "christian", "source_seat": "leon"}
    assert move not in legal_moves(state)
    with pytest.raises(IllegalAction, match="blocked") as exc:
        apply_action(state, move)
    assert exc.value.code == "no_supply_route"
    assert not state.lords["alfonso"].assets.get("prov", 0)


def test_bypassed_enemy_source_remains_a_valid_route():
    state = _active("alfonso", "sahagun", {"mule": 1})
    state.locales["leon"].conquered_markers = 3
    state.locales["leon"].bypass_yellow = True
    state.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="leon")
    move = {"type": "cmd_supply", "side": "christian", "source_seat": "leon"}
    assert move in legal_moves(state)
    assert apply_action(state, move)["prov_gained"] == 1


def test_camels_supply_menu_uses_double_distance():
    state = _active("yusuf", "sevilla", {"mule": 1})
    _cap(state, "M16")
    move = {"type": "cmd_supply", "side": "muslim", "source_seat": "algeciras"}
    assert move in legal_moves(state)
    assert apply_action(state, move)["prov_gained"] == 1


def test_double_source_supply_requires_transport_for_both_routes():
    state = _active("yusuf", "jerez", {"mule": 1})
    _cap(state, "M12")
    move = {"type": "cmd_supply", "side": "muslim", "source_seat": "algeciras"}
    assert move not in legal_moves(state)
    with pytest.raises(IllegalAction) as exc:
        apply_action(state, move)
    assert exc.value.code == "no_transport"
    _cap(state, "M16")
    assert move in legal_moves(state)
    assert apply_action(state, move)["prov_gained"] == 2


def test_guadalquivir_laden_cost_is_two_actions():
    state = _active("al_mutamid", "sevilla", {"loot": 1}, actions=1)
    _cap(state, "M19")
    move = {"type": "cmd_guadalquivir", "side": "muslim", "target_locale_id": "cordoba"}
    assert move not in legal_moves(state)
    with pytest.raises(IllegalAction) as exc:
        apply_action(state, move)
    assert exc.value.code == "not_enough_actions"
    assert state.lords["al_mutamid"].cylinder.locale_id == "sevilla"
    state.meta.actions_remaining = 2
    assert move in legal_moves(state)
    result = apply_action(state, move)
    assert result["cost"] == 2
    assert state.meta.actions_remaining == 0


def test_guadalquivir_brings_lower_lord_and_counts_his_load():
    state = _active("al_mutamid", "sevilla", actions=1)
    _cap(state, "M19")
    sir = state.lords["sir"]
    sir.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    sir.lieutenant_of = "al_mutamid"
    sir.is_lieutenant = True
    sir.assets = {"loot": 1}
    move = {"type": "cmd_guadalquivir", "side": "muslim", "target_locale_id": "cordoba"}
    assert move not in legal_moves(state)
    state.meta.actions_remaining = 2
    assert move in legal_moves(state)
    apply_action(state, move)
    assert sir.cylinder.locale_id == "cordoba"
    assert sir.moved_fought
    assert state.lords["al_mutamid"].first_march_used_this_card


def test_normal_march_menu_includes_mandatory_lower_lord_load():
    state = _active("al_mutamid", "sevilla", actions=1)
    sir = state.lords["sir"]
    sir.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    sir.lieutenant_of = "al_mutamid"
    sir.assets = {"loot": 1}
    assert not [m for m in legal_moves(state) if m["type"] == "cmd_march"]


@pytest.mark.parametrize("move_type", ["cmd_guadalquivir", "cmd_march_port_to_port"])
def test_special_march_cannot_leave_after_bypassing_this_card(move_type):
    state = _active("al_mutamid", "sevilla")
    _cap(state, "M19")
    state.decks.held["muslim"] = ["M19"]
    state.lords["al_mutamid"].bypassed_this_card = True
    assert not [m for m in legal_moves(state) if m["type"] == move_type]
    with pytest.raises(IllegalAction):
        apply_action(state, {"type": move_type, "side": "muslim",
                             "target_locale_id": "algeciras"})


@pytest.mark.parametrize("move_type", ["cmd_guadalquivir", "cmd_march_port_to_port"])
def test_special_march_cannot_start_with_christian_lord(move_type):
    state = _active("al_mutamid", "sevilla")
    _cap(state, "M19")
    state.decks.held["muslim"] = ["M19"]
    state.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    assert not [m for m in legal_moves(state) if m["type"] == move_type]


def test_african_fleet_arrival_requires_besiege_or_bypass():
    state = _active("yusuf", "algeciras")
    state.decks.held["muslim"] = ["M19"]
    state.locales["sevilla"].conquered_markers = 3
    move = {"type": "cmd_march_port_to_port", "side": "muslim",
            "target_locale_id": "sevilla"}
    assert move in legal_moves(state)
    result = apply_action(state, move)
    assert result["actions_consumed"] == 2
    assert state.pending is not None
    assert state.pending.kind == "besiege_or_bypass"
    assert state.pending.payload["locale_id"] == "sevilla"
    assert "M19" in state.decks.discard
    assert "M19" not in state.decks.held["muslim"]


def test_african_fleet_marshal_group_and_departure_cleanup():
    state = _active("yusuf", "algeciras", {"mule": 1, "prov": 4})
    _cap(state, "M16")
    state.decks.held["muslim"] = ["M19"]
    state.locales["algeciras"].bypass_green = True
    companion = state.lords["al_mutamid"]
    companion.cylinder = Cylinder(kind="locale", locale_id="algeciras")
    move = {"type": "cmd_march_port_to_port", "side": "muslim",
            "target_locale_id": "sevilla", "group_lord_ids": ["al_mutamid"]}
    assert move in legal_moves(state)
    apply_action(state, move)
    assert state.lords["yusuf"].assets["prov"] == 4
    assert companion.cylinder.locale_id == "sevilla"
    assert companion.moved_fought
    assert not state.locales["algeciras"].bypass_green


def test_african_fleet_requires_whole_card():
    state = _active("yusuf", "algeciras", actions=1)
    state.decks.held["muslim"] = ["M19"]
    assert not [m for m in legal_moves(state) if m["type"] == "cmd_march_port_to_port"]
    with pytest.raises(IllegalAction):
        apply_action(state, {"type": "cmd_march_port_to_port", "side": "muslim",
                             "target_locale_id": "sevilla"})
    assert "M19" in state.decks.held["muslim"]


@pytest.mark.parametrize("command", [{}, {"source_seats": []}])
def test_dawud_source_free_supply_default_and_menu(command):
    state = _active("yusuf", "jerez")
    state.lords["yusuf"].capabilities.append("M8")
    move = {"type": "cmd_supply", "side": "muslim", "source_seats": []}
    assert move in legal_moves(state)
    result = apply_action(state, {"type": "cmd_supply", "side": "muslim", **command})
    assert result["prov_gained"] == 1
    assert state.lords["yusuf"].assets["prov"] == 1
    assert state.meta.actions_remaining == 1


