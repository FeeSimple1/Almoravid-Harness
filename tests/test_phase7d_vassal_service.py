"""Phase 7d: Advanced Vassal Service (rule 3.4.2)."""

from __future__ import annotations

from almoravid.actions import _shift_service_left
from almoravid.scenarios import load_scenario
from almoravid.state import ServiceMarker


def test_basic_rule_no_vassal_cascade() -> None:
    """With advanced rule OFF (default), shifting a Lord's Service does
    NOT touch any vassal markers."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.advanced_vassal_service = False
    s.calendar.service_markers = [
        ServiceMarker(lord_id="alfonso", box=8),
        ServiceMarker(lord_id="alfonso", box=8, vassal_id="alfonso_v1"),
    ]
    _shift_service_left(s, "alfonso", boxes=2)
    lord_sm = next(m for m in s.calendar.service_markers
                   if m.lord_id == "alfonso" and m.vassal_id is None)
    vassal_sm = next(m for m in s.calendar.service_markers
                     if m.vassal_id == "alfonso_v1")
    assert lord_sm.box == 6
    assert vassal_sm.box == 8  # untouched under basic rule


def test_advanced_rule_cascades_to_vassal_markers() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.advanced_vassal_service = True
    s.calendar.service_markers = [
        ServiceMarker(lord_id="alfonso", box=8),
        ServiceMarker(lord_id="alfonso", box=8, vassal_id="alfonso_v1"),
        ServiceMarker(lord_id="alfonso", box=8, vassal_id="alfonso_v2"),
        ServiceMarker(lord_id="al_mutamid", box=8, vassal_id="m_v1"),
    ]
    _shift_service_left(s, "alfonso", boxes=3)
    lord_sm = next(m for m in s.calendar.service_markers
                   if m.lord_id == "alfonso" and m.vassal_id is None)
    assert lord_sm.box == 5
    for vid in ("alfonso_v1", "alfonso_v2"):
        vm = next(m for m in s.calendar.service_markers if m.vassal_id == vid)
        assert vm.box == 5  # cascaded
    # Other Lord's vassal marker untouched.
    other = next(m for m in s.calendar.service_markers if m.vassal_id == "m_v1")
    assert other.box == 8


def test_advanced_rule_vassal_marker_off_left_removed() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.advanced_vassal_service = True
    s.calendar.service_markers = [
        ServiceMarker(lord_id="alfonso", box=5),
        ServiceMarker(lord_id="alfonso", box=2, vassal_id="alfonso_v1"),
    ]
    _shift_service_left(s, "alfonso", boxes=3)
    # Vassal marker (box 2 - 3 <= 0) removed off-left.
    assert not any(m.vassal_id == "alfonso_v1"
                   for m in s.calendar.service_markers)
    # Lord marker survives at box 2.
    lord_sm = next(m for m in s.calendar.service_markers
                   if m.lord_id == "alfonso" and m.vassal_id is None)
    assert lord_sm.box == 2


def test_take_vassal_places_service_marker_under_advanced_rule() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.advanced_vassal_service = True
    # Place Alfonso's own Service marker; Muster a Ready Vassal.
    s.calendar.service_markers = [ServiceMarker(lord_id="alfonso", box=7)]
    lord = s.lords["alfonso"]
    from almoravid.state import Cylinder
    lord.cylinder = Cylinder(kind="locale", locale_id=lord.seats[0]
                             if lord.seats else "leon")
    lord.lordship_used = 0
    # Ensure at least one Ready Vassal.
    if not lord.vassals or not any(v.ready for v in lord.vassals):
        import pytest
        pytest.skip("alfonso has no Ready Vassal in this scenario")
    ready_idx = next(i for i, v in enumerate(lord.vassals) if v.ready)
    vassal_id = lord.vassals[ready_idx].id
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    from almoravid.actions import apply_action
    svc_rating = lord.vassals[ready_idx].service_cost
    expected = min(17, s.calendar.current_box + svc_rating)
    apply_action(s, {"type": "levy_take_vassal", "side": "christian",
                     "lord_id": "alfonso", "vassal_index": ready_idx})
    # 3.4.2: the Vassal marker is placed right of the LEVY marker by the
    # Vassal's Service Rating (not at the Lord's own box).
    vm = next((m for m in s.calendar.service_markers
               if m.vassal_id == vassal_id), None)
    assert vm is not None
    assert vm.box == expected
