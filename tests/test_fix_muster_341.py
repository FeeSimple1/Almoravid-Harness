"""FIX-A L1/L8/L10: Muster places Service marker, checks Ready, and
adjusts a Taifa Lord to Independent (3.4.1)."""
from __future__ import annotations
import pytest
from almoravid.actions import IllegalAction, apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _to_muster(s):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "muster")
    return s


def _muster_until_success(s, side, lord_id, seed_tries=30):
    """Retry Muster until the Fealty roll succeeds (deterministic seed
    advances each call)."""
    for _ in range(seed_tries):
        r = apply_action(s, {"type": "muster_lord", "side": side,
                             "lord_id": lord_id})
        if r["success"]:
            return r
    return None


def test_muster_places_service_marker_ahead():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    # Force a Christian Lord onto the Calendar, Ready.
    lid = next(l.id for l in s.lords.values()
               if l.side == "christian" and l.fealty is not None)
    s.lords[lid].cylinder = Cylinder(kind="calendar",
                                     box=s.calendar.current_box)
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != lid]
    svc_rating = s.lords[lid].service_rating
    _to_muster(s)
    while s.meta.active_player != "christian":
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    r = _muster_until_success(s, "christian", lid)
    if r is None:
        pytest.skip("Fealty roll never succeeded in window")
    expected = min(17, s.calendar.current_box + svc_rating)
    assert r["service_box"] == expected
    sm = next(m for m in s.calendar.service_markers
              if m.lord_id == lid and m.vassal_id is None)
    assert sm.box == expected


def test_muster_rejects_unready_lord():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    lid = next((l.id for l in s.lords.values()
                if l.side == "christian" and l.fealty is not None), None)
    s.lords[lid].cylinder = Cylinder(kind="calendar",
                                     box=s.calendar.current_box + 3)
    _to_muster(s)
    while s.meta.active_player != "christian":
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": lid})
    assert ei.value.code == "not_ready"


def test_muster_taifa_lord_sets_independent():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    # Force a Muslim Taifa Lord with Fealty onto the Calendar, Ready.
    lid = next((l.id for l in s.lords.values()
                if l.is_taifa and l.side == "muslim" and l.fealty is not None
                and l.home_taifa), None)
    if lid is None:
        pytest.skip("no Taifa Lord with Fealty")
    s.lords[lid].cylinder = Cylinder(kind="calendar",
                                     box=s.calendar.current_box)
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != lid]
    home = s.lords[lid].home_taifa
    s.taifas[home].status = "parias"
    _to_muster(s)
    while s.meta.active_player != "muslim":
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    r = _muster_until_success(s, "muslim", lid)
    if r is None:
        pytest.skip("Fealty roll never succeeded")
    assert s.taifas[home].status == "independent"
