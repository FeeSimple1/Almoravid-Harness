"""Playtest F7: a Stronghold left free of the besieging side's Lords
loses that side's Siege/Bypass markers (4.3.5) — including when the sole
besieger leaves via Disband (not just March)."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.campaign import _auto_disband_at_service_limit
from almoravid.scenarios import load_scenario
from almoravid.effective import is_friendly_locale
from almoravid.state import Cylinder, ServiceMarker


def _enemy_stronghold(s, side="christian"):
    return next(lid for lid, l in s.locales.items()
               if l.base_type != "region"
               and not is_friendly_locale(s, lid, side))


def test_levy_disband_removes_orphaned_siege_marker() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    loc = _enemy_stronghold(s)
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id=loc)
    al.in_stronghold = False
    s.locales[loc].siege_yellow = 1
    # Sole Christian besieger at the Locale; put him at Service limit.
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(ServiceMarker(lord_id="alfonso", box=1))
    s.meta.phase = "levy"
    s.meta.levy_step = "service_disband"
    s.meta.active_player = "christian"
    apply_action(s, {"type": "disband_lord", "side": "christian",
                     "lord_id": "alfonso"})
    assert s.lords["alfonso"].cylinder.kind != "locale"
    assert s.locales[loc].siege_yellow == 0   # orphaned marker removed


def test_campaign_auto_disband_removes_orphaned_siege() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    loc = _enemy_stronghold(s)
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id=loc)
    al.in_stronghold = False
    s.locales[loc].siege_yellow = 1
    s.calendar.current_box = 3
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(ServiceMarker(lord_id="alfonso", box=3))
    _auto_disband_at_service_limit(s, "alfonso")
    assert s.lords["alfonso"].cylinder.kind != "locale"
    assert s.locales[loc].siege_yellow == 0


def test_marker_kept_if_another_besieger_remains() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    loc = _enemy_stronghold(s)
    for lid in ("alfonso", "alvar_fanez"):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id=loc)
        s.lords[lid].in_stronghold = False
    s.locales[loc].siege_yellow = 1
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(ServiceMarker(lord_id="alfonso", box=1))
    s.meta.phase = "levy"
    s.meta.levy_step = "service_disband"
    s.meta.active_player = "christian"
    apply_action(s, {"type": "disband_lord", "side": "christian",
                     "lord_id": "alfonso"})
    # alvar_fanez still besieging -> marker stays.
    assert s.locales[loc].siege_yellow == 1
