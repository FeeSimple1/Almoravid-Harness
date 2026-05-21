"""FIX-A L9b: Mustering a Lord costs the Levying Lord one Lordship
point (3.4.1); a newly-Mustered Lord cannot levy the same segment;
Muster is impossible with no eligible Levying Lord."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.effective import is_besieged, is_friendly_locale
from almoravid.legal_moves import legal_moves
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
    for lid, l in s.lords.items():
        if (l.side == side and l.cylinder.kind == "locale"
                and not l.just_arrived_this_levy and l.lordship_rating > 0
                and is_friendly_locale(s, l.cylinder.locale_id, side)
                and not is_besieged(s, lid)):
            return lid
    return None


def _ready_calendar_lord(s, side):
    lid = next(l.id for l in s.lords.values()
               if l.side == side and l.fealty is not None)
    s.lords[lid].cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != lid]
    return lid


def test_muster_spends_levier_lordship():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    rolling = _ready_calendar_lord(s, "christian")
    _to_muster(s, "christian")
    levier = _pick_levier(s, "christian")
    assert levier is not None
    used0 = s.lords[levier].lordship_used
    apply_action(s, {"type": "muster_lord", "side": "christian",
                     "lord_id": rolling, "levying_lord_id": levier})
    assert s.lords[levier].lordship_used == used0 + 1


def test_muster_requires_levier():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    rolling = _ready_calendar_lord(s, "christian")
    _to_muster(s, "christian")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": rolling})
    assert ei.value.code == "bad_arg"


def test_levier_out_of_lordship_rejected():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    rolling = _ready_calendar_lord(s, "christian")
    _to_muster(s, "christian")
    levier = _pick_levier(s, "christian")
    s.lords[levier].lordship_used = s.lords[levier].lordship_rating
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": rolling, "levying_lord_id": levier})
    assert ei.value.code == "lordship_exhausted"


def test_just_arrived_levier_blocked():
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    rolling = _ready_calendar_lord(s, "christian")
    _to_muster(s, "christian")
    levier = _pick_levier(s, "christian")
    s.lords[levier].just_arrived_this_levy = True
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": rolling, "levying_lord_id": levier})
    assert ei.value.code == "levier_just_arrived"


def test_enumerator_muster_moves_carry_levier_and_apply():
    import copy
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    _ready_calendar_lord(s, "christian")
    _to_muster(s, "christian")
    mm = [m for m in legal_moves(s) if m["type"] == "muster_lord"]
    assert mm
    assert all("levying_lord_id" in m for m in mm)
    for m in mm[:5]:
        apply_action(copy.deepcopy(s), m)  # must not raise
