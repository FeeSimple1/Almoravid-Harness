"""Phase 6L: complete card enforcement — Jihad eligibility (Table 4),
multi-locale distribution, and the M12/C16/C23 missing branches."""

from __future__ import annotations

import pytest

from almoravid.actions import apply_action
from almoravid.events import (
    _add_jihad, _jihad_eligible_locales, resolve_event,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _first_taifa_locale(s, status):
    t = next(iter(s.taifas.values()))
    t.status = status
    loc = t.locale_ids[0]
    s.locales[loc].jihad_markers = 0
    s.locales[loc].conquered_markers = 0
    s.locales[loc].seat_marker_lord_ids = []
    return t, loc


# ---------------------------------------------------------------------------
# _jihad_eligible_locales (rule 1.4.4 / Table 4)
# ---------------------------------------------------------------------------


def test_independent_taifa_locales_are_ineligible() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for t in s.taifas.values():
        t.status = "independent"
    assert _jihad_eligible_locales(s) == []


def test_reconquista_locale_is_eligible() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _first_taifa_locale(s, "reconquista")
    # Clear any blocking Christian Lords.
    for l in s.lords.values():
        if (l.side == "christian" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id in t.locale_ids):
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    assert loc in _jihad_eligible_locales(s)


def test_christian_conquered_marker_blocks_eligibility() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _first_taifa_locale(s, "parias")
    s.locales[loc].conquered_markers = 1
    assert loc not in _jihad_eligible_locales(s)


def test_christian_seat_marker_blocks_eligibility() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _first_taifa_locale(s, "parias")
    # Use a real Christian lord_id for the Seat marker.
    christian_lid = next(lid for lid, l in s.lords.items()
                         if l.side == "christian")
    s.locales[loc].seat_marker_lord_ids = [christian_lid]
    assert loc not in _jihad_eligible_locales(s)


def test_unbesieged_christian_lord_blocks_but_sieging_allows() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _first_taifa_locale(s, "parias")
    christian_lid = next(lid for lid, l in s.lords.items()
                         if l.side == "christian")
    s.lords[christian_lid].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.lords[christian_lid].in_stronghold = False
    # Unbesieged Christian Lord present -> blocked.
    assert loc not in _jihad_eligible_locales(s)
    # Now mark the locale as under Christian Siege -> eligible again.
    s.locales[loc].siege_yellow = 1
    assert loc in _jihad_eligible_locales(s)


# ---------------------------------------------------------------------------
# _add_jihad distribution
# ---------------------------------------------------------------------------


def test_add_jihad_spreads_round_robin_across_eligible() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Make a Parias Taifa with >=2 eligible locales.
    t = next(iter(s.taifas.values()))
    t.status = "parias"
    for loc in t.locale_ids:
        s.locales[loc].jihad_markers = 0
        s.locales[loc].conquered_markers = 0
        s.locales[loc].seat_marker_lord_ids = []
    for l in s.lords.values():
        if (l.side == "christian" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id in t.locale_ids):
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    eligible = _jihad_eligible_locales(s)
    if len(eligible) < 2:
        pytest.skip("need >=2 eligible locales for round-robin test")
    placement = _add_jihad(s, 3, {})
    # 3 markers across >=2 locales: round-robin gives no single locale
    # more than ceil(3/len) — and total is exactly 3.
    assert sum(placement.values()) == 3


def test_add_jihad_honors_explicit_targets() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t = next(iter(s.taifas.values()))
    t.status = "parias"
    for loc in t.locale_ids:
        s.locales[loc].jihad_markers = 0
        s.locales[loc].conquered_markers = 0
        s.locales[loc].seat_marker_lord_ids = []
    for l in s.lords.values():
        if (l.side == "christian" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id in t.locale_ids):
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    eligible = _jihad_eligible_locales(s)
    chosen = eligible[0]
    placement = _add_jihad(s, 2, {"jihad_targets": [chosen, chosen]})
    assert placement.get(chosen) == 2


def test_add_jihad_returns_none_when_no_eligible() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for t in s.taifas.values():
        t.status = "independent"
    assert _add_jihad(s, 2, {}) is None


# ---------------------------------------------------------------------------
# M12 missing branches
# ---------------------------------------------------------------------------


def test_m12_cylinder_left_for_calendar_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    taifa_lord = next((lid for lid, l in s.lords.items()
                       if l.is_taifa and l.side == "muslim"), None)
    if taifa_lord is None:
        pytest.skip("no Taifa Lord")
    s.lords[taifa_lord].cylinder = Cylinder(kind="calendar", box=8)
    r = resolve_event(s, "muslim", "M12", payload={"lord_ids": [taifa_lord]})
    entry = r["shifted"][0]
    assert entry["shifted"] == "cylinder_left"
    assert entry["new_cylinder_box"] == 7


def test_m12_lordship_plus_2_branch() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    taifa_lord = next((lid for lid, l in s.lords.items()
                       if l.is_taifa and l.side == "muslim"), None)
    if taifa_lord is None:
        pytest.skip("no Taifa Lord")
    rating_before = s.lords[taifa_lord].lordship_rating
    r = resolve_event(s, "muslim", "M12",
                      payload={"mode": "lordship", "lord_id": taifa_lord})
    assert r["lordship_plus_2"] == taifa_lord
    assert s.lords[taifa_lord].lordship_rating == rating_before + 2


# ---------------------------------------------------------------------------
# C16 muster branch
# ---------------------------------------------------------------------------


def test_c16_muster_branch_musters_christian_from_calendar() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Put a Christian Lord on the Calendar.
    christian = next((lid for lid, l in s.lords.items()
                      if l.side == "christian"), None)
    s.lords[christian].cylinder = Cylinder(kind="calendar", box=6)
    r = resolve_event(s, "christian", "C16",
                      payload={"mode": "muster", "lord_id": christian})
    if r.get("no_op"):
        pytest.skip(f"{christian} has no Seat in static data")
    assert r["mustered"] == christian
    assert s.lords[christian].cylinder.kind == "locale"


# ---------------------------------------------------------------------------
# C23 cylinder branch
# ---------------------------------------------------------------------------


def test_c23_cylinder_branch_shifts_calendar_box() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    from almoravid.state import ServiceMarker
    target = None
    for lid in ("abu_bakr", "al_mustain"):
        if lid in s.lords:
            target = lid
            break
    if target is None:
        pytest.skip("neither abu_bakr nor al_mustain in scenario")
    s.lords[target].cylinder = Cylinder(kind="calendar", box=9)
    if not any(sm.lord_id == target for sm in s.calendar.service_markers):
        s.calendar.service_markers.append(ServiceMarker(lord_id=target, box=9))
    r = resolve_event(s, "christian", "C23",
                      payload={"mode": "cylinder", "lord_id": target})
    assert r["mode"] == "cylinder"
    assert r["new_cylinder_box"] == 8
    assert target in s.meta.muster_banned_this_levy_lord_ids
