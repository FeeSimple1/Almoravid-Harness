"""FIX-A L1/L8/L10: Muster places Service marker, checks Ready, and
adjusts a Taifa Lord to Independent (3.4.1)."""
from __future__ import annotations
import pytest
from almoravid.actions import IllegalAction, apply_action
from almoravid.effective import is_friendly_locale, is_besieged
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import step_levy


def _to_muster(s):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "muster")
    return s


def _pick_levier(s, side):
    """An eligible Levying Lord: on map, side, Friendly+Unbesieged,
    has Lordship, not newly Mustered this segment (3.4.1)."""
    for lid, l in s.lords.items():
        if (l.side == side and l.cylinder.kind == "locale"
                and not l.just_arrived_this_levy
                and l.lordship_rating > 0
                and is_friendly_locale(s, l.cylinder.locale_id, side)
                and not is_besieged(s, lid)):
            return lid
    return None


def _muster_until_success(s, side, lord_id, levier_id, seed_tries=30):
    """Retry Muster until the Fealty roll succeeds. The levier's
    Lordship is refreshed each attempt so the test can iterate the
    deterministic RNG without exhausting Lordship."""
    for _ in range(seed_tries):
        s.lords[levier_id].lordship_used = 0
        r = apply_action(s, {"type": "muster_lord", "side": side,
                             "lord_id": lord_id,
                             "levying_lord_id": levier_id})
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
        step_levy(s)
    levier = _pick_levier(s, "christian")
    assert levier is not None
    r = _muster_until_success(s, "christian", lid, levier)
    assert r is not None, "Fealty roll should succeed within the retry window"
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
        step_levy(s)
    levier = _pick_levier(s, "christian")
    assert levier is not None
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": lid, "levying_lord_id": levier})
    assert ei.value.code == "not_ready"


def test_muster_taifa_lord_sets_independent():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    # Force a Muslim Taifa Lord with Fealty onto the Calendar, Ready.
    lid = next((l.id for l in s.lords.values()
                if l.is_taifa and l.side == "muslim" and l.fealty is not None
                and l.home_taifa), None)
    assert lid is not None, "no Taifa Lord with Fealty"
    s.lords[lid].cylinder = Cylinder(kind="calendar",
                                     box=s.calendar.current_box)
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != lid]
    home = s.lords[lid].home_taifa
    s.taifas[home].status = "parias"
    _to_muster(s)
    while s.meta.active_player != "muslim":
        step_levy(s)
    levier = _pick_levier(s, "muslim")
    assert levier is not None, "no eligible Muslim Levying Lord"
    r = _muster_until_success(s, "muslim", lid, levier)
    assert r is not None, "Fealty roll should succeed within the retry window"
    assert s.taifas[home].status == "independent"
