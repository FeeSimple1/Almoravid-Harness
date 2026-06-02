"""M16/M17 Revolt bans Muster *of OR by* the named Lord (rule: the
Arts-of-War events read 'no Muster of or by <Lord>'). Regression test for
the audit fix: the ban must apply to the LEVYING (Mustering) Lord, not only
to the Lord being Mustered."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.effective import is_besieged, is_friendly_locale
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import step_levy


def _to_muster(s, side="christian"):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "muster")
    while s.meta.active_player != side:
        step_levy(s)
    return s


def _pick_levier(s, side):
    for lid, lord in s.lords.items():
        if (lord.side == side and lord.cylinder.kind == "locale"
                and not lord.just_arrived_this_levy
                and lord.lordship_rating > 0
                and is_friendly_locale(s, lord.cylinder.locale_id, side)
                and not is_besieged(s, lid)):
            return lid
    return None


def _ready_calendar_lord(s, side):
    lid = next(lord.id for lord in s.lords.values()
               if lord.side == side and lord.fealty is not None)
    s.lords[lid].cylinder = Cylinder(kind="calendar",
                                     box=s.calendar.current_box)
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != lid]
    return lid


def test_banned_lord_cannot_be_the_levying_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    rolling = _ready_calendar_lord(s, "christian")
    _to_muster(s, "christian")
    levier = _pick_levier(s, "christian")
    assert levier is not None and levier != rolling
    # Revolt bans the levier from Mustering others (the 'by' clause).
    s.meta.muster_banned_this_levy_lord_ids.append(levier)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": rolling, "levying_lord_id": levier})
    assert ei.value.code == "muster_banned"


def test_unbanned_levier_still_allowed() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    rolling = _ready_calendar_lord(s, "christian")
    _to_muster(s, "christian")
    levier = _pick_levier(s, "christian")
    assert levier is not None
    # No ban -> the Muster proceeds (spends the levier's Lordship).
    used0 = s.lords[levier].lordship_used
    apply_action(s, {"type": "muster_lord", "side": "christian",
                     "lord_id": rolling, "levying_lord_id": levier})
    assert s.lords[levier].lordship_used == used0 + 1
