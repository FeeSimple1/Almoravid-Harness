"""Printed map regressions found with Almoravid Vassal 1.3.

Authority: the published board artwork (module image
``Almoravid Map on Table 3.png``), and Rules of Play 1.3.1, 4.3, 4.6.
Vassal's own scripts are not a rules authority. See VASSAL_AUDIT.md.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.map import all_neighbors, is_port, nearest_ports, neighbors_via
from almoravid.scenarios import list_scenarios, load_scenario
from tests.test_audit_march_supply import _active, _cap


PRINTED_PORTS = {
    "algeciras", "malaga", "almeria", "cartagena", "alicante", "denia",
    "valencia", "tortosa", "jerez", "huelva", "sevilla",
}

PHANTOM_WAYS = [
    ("calatayud", "zaragoza", "road"),
    ("barbastro", "lerida", "road"),
    ("denia", "alicante", "road"),
    ("sevilla", "moron", "road"),
    ("lorca", "almeria", "pass"),
]


@pytest.mark.parametrize("origin,target", [("palencia", "simancas"),
                                          ("simancas", "palencia")])
def test_printed_palencia_simancas_road_is_playable(origin, target):
    state = _active("pedro_ansurez", origin, {"cart": 1, "prov": 1})
    move = {"type": "cmd_march", "side": "christian",
            "target_locale_id": target, "way_type": "road"}
    assert target in neighbors_via(origin, "road")
    assert move in legal_moves(state)
    result = apply_action(state, move)
    assert result["cost"] == 1
    assert state.lords["pedro_ansurez"].cylinder.locale_id == target
    assert state.lords["pedro_ansurez"].assets["prov"] == 1


def test_palencia_can_supply_from_simancas_with_one_cart():
    state = _active("pedro_ansurez", "palencia", {"cart": 1})
    move = {"type": "cmd_supply", "side": "christian", "source_seat": "simancas"}
    assert move in legal_moves(state)
    assert apply_action(state, move)["prov_gained"] == 1


@pytest.mark.parametrize("origin,target,way_type", PHANTOM_WAYS)
@pytest.mark.parametrize("reverse", [False, True])
def test_nonexistent_map_connections_are_not_playable(origin, target, way_type, reverse):
    if reverse:
        origin, target = target, origin
    state = _active("al_mutamid", origin)
    move = {"type": "cmd_march", "side": "muslim",
            "target_locale_id": target, "way_type": way_type}
    assert target not in all_neighbors(origin)
    assert move not in legal_moves(state)
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalAction):
        apply_action(state, move)
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("scenario", list_scenarios())
def test_all_scenarios_have_exactly_the_printed_ship_icons(scenario):
    state = load_scenario(scenario)
    assert {lid for lid, loc in state.locales.items() if loc.has_port} == PRINTED_PORTS
    assert {lid for lid in state.locales if is_port(lid)} == PRINTED_PORTS
    assert {lid for lid, _ in nearest_ports("algeciras")} == PRINTED_PORTS


@pytest.mark.parametrize("inland", ["zaragoza", "lerida"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("move_type", ["cmd_guadalquivir", "cmd_march_port_to_port"])
def test_m19_cannot_treat_inland_cities_as_ports(inland, reverse, move_type):
    origin, target = (inland, "sevilla") if reverse else ("sevilla", inland)
    state = _active("al_mutamid", origin)
    if move_type == "cmd_guadalquivir":
        _cap(state, "M19")
    else:
        state.decks.held["muslim"] = ["M19"]
    move = {"type": move_type, "side": "muslim", "target_locale_id": target}
    assert move not in legal_moves(state)
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalAction):
        apply_action(state, move)
    assert state.model_dump(mode="json") == before
