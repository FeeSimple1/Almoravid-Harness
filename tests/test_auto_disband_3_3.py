"""End-of-card (4.8.2) auto-Disband must follow full rule 3.3.

Previously _auto_disband_at_service_limit sent EVERY at/over-limit Lord to
the Calendar, skipping:
  - 3.3.1 permanent removal for a Beyond-Service Lord (Service marker LEFT
    of the Campaign marker), and
  - the 3.3 Important / 1.4.3 cascade when an Independent-Taifa Lord
    Disbands (Taifa -> Parias, Parias Coin, +1 Christian VP).
It now routes through _h_disband_lord (like the Winter-Siege Disband), while
keeping the Campaign phase so the Errata "+1" at-limit placement is intact.
"""

from __future__ import annotations

from almoravid.campaign import _auto_disband_at_service_limit
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _set_service_box(state, lord_id, box):
    sm = next(m for m in state.calendar.service_markers
              if m.lord_id == lord_id and m.vassal_id is None)
    sm.box = box


def test_beyond_service_lord_is_permanently_removed() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.meta.phase = "campaign"
    s.calendar.current_box = 3
    lord = s.lords["al_mutamid"]
    lord.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    _set_service_box(s, "al_mutamid", 2)        # box 2 < current 3 -> Beyond
    res = _auto_disband_at_service_limit(s, "al_mutamid")
    assert res.get("disbanded") == "al_mutamid"
    assert lord.cylinder.kind == "removed", "Beyond-Service Lord not removed (3.3.1)"


def test_independent_taifa_disband_triggers_parias_cascade() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.meta.phase = "campaign"
    s.calendar.current_box = 3
    assert s.taifas["sevilla"].status == "independent"
    lord = s.lords["al_mutamid"]
    lord.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    _set_service_box(s, "al_mutamid", 3)        # at limit
    vp_before = s.score.christian
    _auto_disband_at_service_limit(s, "al_mutamid")
    assert s.taifas["sevilla"].status == "parias", "Independent Taifa did not adjust to Parias"
    assert s.score.christian == vp_before + 1.0, "missing +1 Christian VP (1.4.3)"


def test_at_limit_non_taifa_still_goes_to_calendar_with_campaign_plus_one() -> None:
    """Regression: the at-limit (3.3.2) Calendar placement keeps the Errata
    'next box if Campaign' +1 (current + 1 + service_rating)."""
    s = load_scenario("scenario_f_reconquista")
    s.meta.phase = "campaign"
    s.calendar.current_box = 3
    lord = s.lords["alfonso"]
    lord.cylinder = Cylinder(kind="locale", locale_id="leon")
    _set_service_box(s, "alfonso", 3)           # at limit
    svc = lord.service_rating
    _auto_disband_at_service_limit(s, "alfonso")
    assert lord.cylinder.kind == "calendar"
    assert lord.cylinder.box == 3 + 1 + svc     # Errata +1 preserved
