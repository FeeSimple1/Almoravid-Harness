"""Supply routing fixes (rule 4.6.1).

Bug 3: the BFS in _find_supply_routes stopped at the Lord's own Seat, so a
farther Seat reachable only THROUGH a nearer Seat was wrongly unreachable.
Bug 4: the Supply handler/menu counted only the Lord's own Carts/Mules,
ignoring 4.6.1 "have or Share (1.5.2)" co-located Transport.
"""

from __future__ import annotations

from almoravid.campaign import (
    _find_supply_routes,
    _h_cmd_supply,
    _own_seats,
    _shared_transport_at,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _meta_ctx(state, lord_id, side):
    from almoravid.campaign import _MetaCtx
    return _MetaCtx(state, phase="campaign", campaign_step="activation",
                    active_player=side, active_lord_id=lord_id,
                    actions_remaining=2)


# ---- Bug 3: BFS expands through an own Seat to reach a farther Seat -------

def test_supply_route_passes_through_own_seat() -> None:
    s = load_scenario("scenario_f_reconquista")
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id="astorga")
    seats = _own_seats(s, "alfonso")               # burgos + leon
    routes = _find_supply_routes(s, "astorga", seats, "christian", al)
    # leon is the near Seat (1 hop); burgos is reachable only via leon.
    assert routes["leon"] == ["leon"]
    assert routes["burgos"] is not None, "farther Seat unreachable through own Seat"
    assert routes["burgos"][-1] == "burgos"
    assert "leon" in routes["burgos"]              # route passes through leon


def test_supply_through_seat_round_trips() -> None:
    s = load_scenario("scenario_f_reconquista")
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id="astorga")
    al.assets = {"mule": 5}                          # enough for the 3 hops
    before = al.assets.get("prov", 0)
    with _meta_ctx(s, "alfonso", "christian"):
        r = _h_cmd_supply(s, {"type": "cmd_supply", "side": "christian",
                              "source_seats": ["burgos"]})
    assert "burgos" in r["source_seats"]
    assert al.assets.get("prov", 0) == before + 1


# ---- Bug 4: shared (co-located) Transport counts for Supply ---------------

def test_shared_transport_helper_pools_colocated_lords() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    s.lords["alfonso"].assets = {}                  # no transport of his own
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="sahagun")
    s.lords["alvar_fanez"].assets = {"mule": 4}
    carts, mules = _shared_transport_at(s, "sahagun", "christian")
    assert mules >= 4


def test_supply_uses_shared_transport_round_trips() -> None:
    s = load_scenario("scenario_f_reconquista")
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id="sahagun")
    al.assets = {}                                   # 0 own transport
    ally = s.lords["alvar_fanez"]
    ally.cylinder = Cylinder(kind="locale", locale_id="sahagun")
    ally.assets = {"mule": 4}
    # sahagun -> leon is one Way; Alfonso has no Cart/Mule but Shares Alvar's.
    before = al.assets.get("prov", 0)
    with _meta_ctx(s, "alfonso", "christian"):
        r = _h_cmd_supply(s, {"type": "cmd_supply", "side": "christian",
                              "source_seats": ["leon"]})
    assert al.assets.get("prov", 0) == before + 1
    assert r["actions_remaining"] == 1
