"""C16 Cathedrals capability + Cathedral Seat VP (5.1, 1.4.4)."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import _conquer_stronghold, compute_final_vp
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _setup_alfonso_at_conquered_city(s, city=None):
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    if city is None:
        city = next(lid for lid, loc in s.locales.items()
                    if loc.base_type == "city" and loc.territory in s.taifas)
    s.locales[city].conquered_markers = 3      # Christian-Conquered City
    s.locales[city].jihad_markers = 0
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=city)
    s.lords["alfonso"].in_stronghold = False
    if "C16" not in s.lords["alfonso"].capabilities:
        s.lords["alfonso"].capabilities.append("C16")
    s.meta.active_lord_id = "alfonso"
    s.meta.actions_remaining = 2
    return city


def test_place_cathedral_seat_adds_vp_and_jihad_rider() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    city = _setup_alfonso_at_conquered_city(s)
    cvp_before, _ = compute_final_vp(s)
    jihad_before = sum(l.jihad_markers for l in s.locales.values())
    r = apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    assert city in s.cathedral_seat_locales
    assert "alfonso" in s.locales[city].seat_marker_lord_ids
    cvp_after, _ = compute_final_vp(s)
    assert cvp_after == cvp_before + 1          # +1 Christian VP
    jihad_after = sum(l.jihad_markers for l in s.locales.values())
    assert jihad_after == jihad_before + 1      # +1 Jihad rider
    # Free placement: actions unchanged.
    assert s.meta.actions_remaining == 2


def test_cannot_place_two_at_same_city() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup_alfonso_at_conquered_city(s)
    apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    assert ei.value.code == "already_seat"


def test_cap_two_markers_requires_relocate() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    cities = [lid for lid, loc in s.locales.items()
              if loc.base_type == "city" and loc.territory in s.taifas][:3]
    assert len(cities) >= 3
    for c in cities:
        s.locales[c].conquered_markers = 3
    # Place two.
    _setup_alfonso_at_conquered_city(s, cities[0])
    apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=cities[1])
    apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    assert len(s.cathedral_seat_locales) == 2
    # Third placement requires relocate_from.
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=cities[2])
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    assert ei.value.code == "cathedral_cap"
    apply_action(s, {"type": "place_cathedral_seat", "side": "christian",
                     "relocate_from": cities[0]})
    assert set(s.cathedral_seat_locales) == {cities[1], cities[2]}


def test_muslim_conquest_removes_cathedral_seat() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    city = _setup_alfonso_at_conquered_city(s)
    apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    s.taifas[s.locales[city].territory].status = "reconquista"
    _conquer_stronghold(s, city, "muslim")     # Muslim re-conquers
    assert city not in s.cathedral_seat_locales
    assert "alfonso" not in s.locales[city].seat_marker_lord_ids


def test_requires_capability_and_conquered_city() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    city = _setup_alfonso_at_conquered_city(s)
    s.lords["alfonso"].capabilities = [c for c in
                                       s.lords["alfonso"].capabilities
                                       if c != "C16"]
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "place_cathedral_seat", "side": "christian"})
    assert ei.value.code == "no_cathedrals"
