"""FIX-A L6/L7: Disband 3.3.1 (permanent) vs 3.3.2 (to Calendar) split,
and Independent-Taifa-Lord -> Parias + Parias Coin + VP (1.4.3 / 3.3.2
Important)."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker


def _to_disband(s, side="muslim"):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "service_disband")
    while s.meta.active_player != side:
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    return s


def _put_taifa_lord_on_map_at_limit(s, lord_id):
    """Place a Muslim Taifa Lord on the map with his Service marker at
    the current Levy box (3.3.2 At Limit)."""
    cur = s.calendar.current_box
    seat = s.lords[lord_id].seats[0]
    s.lords[lord_id].cylinder = Cylinder(kind="locale", locale_id=seat)
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != lord_id]
    s.calendar.service_markers.append(ServiceMarker(lord_id=lord_id, box=cur))
    return seat


def test_independent_taifa_lord_disband_awards_parias_coin_and_status():
    s = load_scenario("scenario_c_parias_wars")
    # al-Mutamid: Service rating 6 -> Parias Coin 6.
    lord_id = "al_mutamid"
    s.taifas[s.lords[lord_id].home_taifa].status = "independent"
    _put_taifa_lord_on_map_at_limit(s, lord_id)
    # Ensure an Unbesieged Christian Lord exists on the map to receive Coin.
    cl = next(l for l in s.lords.values()
              if l.side == "christian" and l.cylinder.kind == "locale")
    coin0 = cl.assets.get("coin", 0)
    _to_disband(s, "muslim")
    r = apply_action(s, {"type": "disband_lord", "side": "muslim",
                         "lord_id": lord_id,
                         "parias_coin_targets": [{"lord_id": cl.id, "coin": 6}]})
    assert s.taifas[s.lords[lord_id].home_taifa].status == "parias"
    assert r["parias_coin"]["amount"] == 6
    assert cl.assets["coin"] == coin0 + 6


def test_parias_coin_wrong_total_raises():
    s = load_scenario("scenario_c_parias_wars")
    lord_id = "al_mustain"  # Service rating 4.
    s.taifas[s.lords[lord_id].home_taifa].status = "independent"
    _put_taifa_lord_on_map_at_limit(s, lord_id)
    cl = next(l for l in s.lords.values()
              if l.side == "christian" and l.cylinder.kind == "locale")
    _to_disband(s, "muslim")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "disband_lord", "side": "muslim",
                         "lord_id": lord_id,
                         "parias_coin_targets": [{"lord_id": cl.id, "coin": 2}]})
    assert ei.value.code == "bad_parias_total"


def test_enumerator_supplies_parias_distribution():
    from almoravid.legal_moves import legal_moves
    s = load_scenario("scenario_c_parias_wars")
    lord_id = "al_mustain"
    s.taifas[s.lords[lord_id].home_taifa].status = "independent"
    _put_taifa_lord_on_map_at_limit(s, lord_id)
    _to_disband(s, "muslim")
    dm = [m for m in legal_moves(s)
          if m["type"] == "disband_lord" and m["lord_id"] == lord_id]
    assert dm
    # The offered move carries a valid Parias-Coin distribution that
    # applies without error.
    import copy
    apply_action(copy.deepcopy(s), dm[0])
