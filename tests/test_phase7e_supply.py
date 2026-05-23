"""Phase 7e: multi-hop + multi-Seat Supply (rule 4.6.1)."""

from __future__ import annotations

import pytest

from almoravid.actions import apply_action, IllegalAction
from almoravid.campaign import _find_supply_routes
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _activate_supply(s, lord_id, locale_id, assets):
    s.lords[lord_id].cylinder = Cylinder(kind="locale", locale_id=locale_id)
    s.lords[lord_id].in_stronghold = False
    s.lords[lord_id].assets = dict(assets)
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = s.lords[lord_id].side
    s.meta.active_lord_id = lord_id
    s.meta.actions_remaining = 3
    return s


def test_bfs_finds_multi_hop_route() -> None:
    """_find_supply_routes returns a 2+ hop route when one exists."""
    from almoravid.map import neighbors_via
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Alfonso's seats include leon/burgos. Start him 2 hops away from a
    # Seat by following the road graph.
    seats = s.lords["alfonso"].seats
    assert seats
    seat = seats[0]
    # Find a locale 2 road-hops from `seat`.
    one = neighbors_via(seat, "road")
    two = None
    for a in one:
        for b in neighbors_via(a, "road"):
            if b != seat and b not in one:
                two = b
                break
        if two:
            break
    assert two is not None, "no 2-hop road locale from seat in this map"
    # Clear enemies off the path.
    for l in s.lords.values():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    routes = _find_supply_routes(s, two, seats, "christian",
                                 s.lords["alfonso"])
    assert routes.get(seat) is not None
    assert len(routes[seat]) >= 2  # multi-hop


def test_multi_seat_supply_adds_prov_per_seat() -> None:
    """A Lord at one Seat that's adjacent to another own Seat can use
    BOTH in one Supply action: +1 Prov per Seat."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord_id = "alfonso"
    seats = s.lords[lord_id].seats
    assert len(seats) >= 2, "alfonso should have >=2 Seats"
    from almoravid.map import neighbors_via
    # Need the two seats road-connected and enemy-free.
    s0, s1 = seats[0], seats[1]
    for l in s.lords.values():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    routes = _find_supply_routes(s, s0, seats, "christian", s.lords[lord_id])
    assert routes.get(s1) is not None, "seats should be connected by a route"
    hops = len(routes[s1])
    _activate_supply(s, lord_id, s0, {"mule": hops})
    prov_before = 0
    s.lords[lord_id].assets["prov"] = prov_before
    r = apply_action(s, {"type": "cmd_supply", "side": "christian",
                         "source_seats": [s0, s1]})
    # At-here Seat (s0) + reachable Seat (s1) => +2 Prov.
    assert r["prov_gained"] == 2
    assert s.lords[lord_id].assets.get("prov", 0) == 2


def test_supply_insufficient_transport_for_multi_seat_rejected() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord_id = "alfonso"
    seats = s.lords[lord_id].seats
    assert len(seats) >= 2, "alfonso should have >=2 Seats"
    s0, s1 = seats[0], seats[1]
    for l in s.lords.values():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    routes = _find_supply_routes(s, s0, seats, "christian", s.lords[lord_id])
    assert routes.get(s1) is not None, "seats should be connected"
    # Zero transport — the non-here Seat can't be supplied.
    _activate_supply(s, lord_id, s0, {})  # no cart/mule
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_supply", "side": "christian",
                         "source_seats": [s0, s1]})
    assert ei.value.code == "no_transport"


def test_single_seat_backcompat() -> None:
    """The legacy single source_seat key still works."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord_id = "alfonso"
    seat = s.lords[lord_id].seats[0]
    _activate_supply(s, lord_id, seat, {})
    s.lords[lord_id].assets["prov"] = 0
    r = apply_action(s, {"type": "cmd_supply", "side": "christian",
                         "source_seat": seat})
    assert r["prov_gained"] == 1
    assert s.lords[lord_id].assets.get("prov", 0) == 1
