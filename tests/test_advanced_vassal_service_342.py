"""3.4.2 Advanced Vassal Service (opt-in): per-Vassal Calendar markers
that shift with the Lord and Disband independently."""
from __future__ import annotations

from almoravid.scenarios import load_scenario
from almoravid.actions import (
    _shift_service_right, _shift_service_left,
    _disband_vassals_for_side, _flip_up_pennants,
)
from almoravid.state import Cylinder, ServiceMarker


def _avs_lord_with_vassal(seed=1):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    s.meta.advanced_vassal_service = True
    lid = next(l for l in s.lords.values()
               if l.cylinder.kind == "locale" and l.vassals)
    lord = lid
    # Give the Lord and one Vassal Calendar markers.
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != lord.id]
    s.calendar.service_markers.append(ServiceMarker(lord_id=lord.id, box=8))
    v = lord.vassals[0]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id=lord.id, box=8, vassal_id=v.id))
    # Vassal forces are on the Lord's mat (mustered).
    for ut, n in v.forces.items():
        lord.forces[ut] = lord.forces.get(ut, 0) + n
    return s, lord, v


def _vbox(s, lid, vid):
    return next((m.box for m in s.calendar.service_markers
                 if m.lord_id == lid and m.vassal_id == vid), None)


def test_right_shift_cascades_to_vassal() -> None:
    s, lord, v = _avs_lord_with_vassal()
    _shift_service_right(s, lord.id, 2)   # Pay
    assert _vbox(s, lord.id, v.id) == 10   # 8 -> 10, same as Lord


def test_left_shift_cascades_to_vassal() -> None:
    s, lord, v = _avs_lord_with_vassal()
    _shift_service_left(s, lord.id, 1)
    assert _vbox(s, lord.id, v.id) == 7


def test_vassal_disband_at_limit_pennant_down_returns_forces() -> None:
    s, lord, v = _avs_lord_with_vassal()
    s.calendar.current_box = 8           # Vassal marker AT limit (box 8)
    before = dict(lord.forces)
    r = _disband_vassals_for_side(s, lord.side)
    assert any(e["vassal_id"] == v.id and e["fate"] == "pennant_down" for e in r)
    assert v.pennant_down is True and v.ready is False
    assert _vbox(s, lord.id, v.id) is None    # marker dropped
    # Vassal's Forces returned to the pool (removed from the Lord).
    for ut, n in v.forces.items():
        assert lord.forces.get(ut, 0) == before.get(ut, 0) - n


def test_vassal_disband_beyond_limit_removed() -> None:
    s, lord, v = _avs_lord_with_vassal()
    s.calendar.current_box = 9           # Vassal marker (box 8) BEYOND limit
    r = _disband_vassals_for_side(s, lord.side)
    assert any(e["vassal_id"] == v.id and e["fate"] == "removed" for e in r)
    assert v.ready is False and v.pennant_down is False  # gone, no re-Muster


def test_no_forces_lord_disbands_to_calendar() -> None:
    s, lord, v = _avs_lord_with_vassal()
    s.calendar.current_box = 8
    # Make the Vassal's Forces the Lord's ONLY Forces.
    lord.forces = dict(v.forces)
    r = _disband_vassals_for_side(s, lord.side)
    assert any(e.get("fate") == "lord_no_forces_disband"
               and e["lord_id"] == lord.id for e in r)
    assert s.lords[lord.id].cylinder.kind != "locale"   # disbanded off-map


def test_flip_up_makes_pennant_down_ready() -> None:
    s, lord, v = _avs_lord_with_vassal()
    v.pennant_down = True
    v.ready = False
    flipped = _flip_up_pennants(s, lord.side)
    assert f"{lord.id}:{v.id}" in flipped
    assert v.pennant_down is False and v.ready is True


def test_avs_off_by_default_no_cascade() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert s.meta.advanced_vassal_service is False
    lord = next(l for l in s.lords.values()
                if l.cylinder.kind == "locale" and l.vassals)
    s.calendar.service_markers = [ServiceMarker(lord_id=lord.id, box=8),
        ServiceMarker(lord_id=lord.id, box=8, vassal_id=lord.vassals[0].id)]
    _shift_service_right(s, lord.id, 2)
    # No cascade when the rule is off: Vassal marker stays at 8.
    assert _vbox(s, lord.id, lord.vassals[0].id) == 8
    assert _disband_vassals_for_side(s, lord.side) == []
