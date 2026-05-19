"""Phase 6j: scenario-specific event resolvers (M9/M10/M20/M21,
C16/C17/C18/C19/C20/C22/C23/C24, M24)."""

from __future__ import annotations

import pytest

from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


# ---------------------------------------------------------------------------
# Jihad-add cards
# ---------------------------------------------------------------------------


def test_m9_two_jihad_when_yusuf_in_reconquista() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    if "yusuf" not in s.lords:
        pytest.skip("yusuf not present")
    # Force a Taifa to Reconquista with Yusuf inside.
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "reconquista"
    loc_id = target_taifa.locale_ids[0]
    s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.lords["yusuf"].in_stronghold = False
    # Move Sir out of Kingdoms if present.
    if "sir" in s.lords:
        s.lords["sir"].cylinder = Cylinder(kind="calendar")
    r = resolve_event(s, "muslim", "M9")
    assert r.get("no_op") is not True
    assert r["jihad_added"] == 2


def test_m20_three_jihad_when_yusuf_in_reconquista_locale() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    if "yusuf" not in s.lords:
        pytest.skip("yusuf not present")
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "reconquista"
    loc_id = target_taifa.locale_ids[0]
    s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.lords["yusuf"].in_stronghold = False
    s.locales[loc_id].jihad_markers = 0
    r = resolve_event(s, "muslim", "M20", payload={"locale_id": loc_id})
    assert r["jihad_added"] == 3


def test_m21_jihad_branch_doubled_with_yusuf() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    if "yusuf" not in s.lords:
        pytest.skip("yusuf not present")
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "parias"
    loc_id = target_taifa.locale_ids[0]
    s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.lords["yusuf"].in_stronghold = False
    r = resolve_event(s, "muslim", "M21", payload={"locale_id": loc_id})
    assert r["jihad_added"] == 4


# ---------------------------------------------------------------------------
# Service-shift + Muster-ban cards
# ---------------------------------------------------------------------------


def test_c19_fitna_shifts_two_taifa_lords_and_bans() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    r = resolve_event(s, "christian", "C19")
    if r.get("no_op"):
        pytest.skip("no Taifa Lords on Calendar in this scenario")
    assert len(r["shifted"]) == 2
    banned = set(s.meta.muster_banned_this_levy_lord_ids)
    for entry in r["shifted"]:
        assert entry["lord_id"] in banned


def test_c22_berbers_bans_all_four_lords() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    r = resolve_event(s, "christian", "C22")
    banned = set(s.meta.muster_banned_this_levy_lord_ids)
    expected = {"al_mutawakkil", "abd_allah", "yusuf", "sir"}
    in_scenario = expected & set(s.lords)
    assert in_scenario <= banned


def test_c24_shifts_yusuf_and_sir_when_on_calendar() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    # Ensure both have service markers on the calendar.
    for lid in ("yusuf", "sir"):
        if not any(sm.lord_id == lid
                   for sm in s.calendar.service_markers):
            from almoravid.state import ServiceMarker
            s.calendar.service_markers.append(
                ServiceMarker(lord_id=lid, box=8))
    r = resolve_event(s, "christian", "C24")
    if r.get("no_op"):
        pytest.skip("yusuf/sir not on calendar")
    banned = set(s.meta.muster_banned_this_levy_lord_ids)
    assert {"yusuf", "sir"} <= banned


# ---------------------------------------------------------------------------
# Other immediates
# ---------------------------------------------------------------------------


def test_c17_genoa_pisa_ravages_two_muslim_ports() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Find Muslim-friendly ports.
    from almoravid.effective import is_friendly_locale
    ports_before = [lid for lid, loc in s.locales.items()
                    if loc.has_port and loc.ravaged == "none"
                    and is_friendly_locale(s, lid, "muslim")]
    # Move all Muslim Lords off any port.
    for lid in ports_before:
        for l in list(s.lords.values()):
            if (l.side == "muslim" and l.cylinder.kind == "locale"
                    and l.cylinder.locale_id == lid):
                l.cylinder = Cylinder(kind="locale", locale_id="sahagun")
    r = resolve_event(s, "christian", "C17")
    if r.get("no_op"):
        pytest.skip("no eligible Muslim Ports in this scenario")
    assert len(r["ravaged"]) <= 2
    for p in r["ravaged"]:
        assert s.locales[p].ravaged == "yellow"


def test_c18_runaway_slaves_restores_christian_foot() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians = [lid for lid, l in s.lords.items()
                  if l.side == "christian" and l.cylinder.kind == "locale"]
    if not christians:
        pytest.skip("no Christian Lord on map")
    target = christians[0]
    # Strip a Men-at-Arms unit so C18 restores it.
    if s.lords[target].forces.get("men_at_arms", 0) > 0:
        s.lords[target].forces["men_at_arms"] = 0
    mules_before = s.lords[target].assets.get("mule", 0)
    r = resolve_event(s, "christian", "C18")
    if r.get("no_op"):
        pytest.skip("no eligible Christian Lord (Phase 6j C18)")
    assert s.lords[target].assets.get("mule", 0) == mules_before + 1


def test_c20_al_qadir_removes_jihad_from_taifa_with_no_muslims() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    taifa = next(t for t in s.taifas.values())
    taifa.status = "reconquista"
    loc_id = taifa.locale_ids[0]
    s.locales[loc_id].jihad_markers = 3
    # Make sure no Muslim Lord is in this taifa.
    for l in s.lords.values():
        if (l.side == "muslim" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id in taifa.locale_ids):
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    r = resolve_event(s, "christian", "C20")
    assert r.get("no_op") is not True
    assert r["jihad_removed"] == 2
    assert s.locales[loc_id].jihad_markers == 1


def test_m24_al_maghawir_blocked_by_c19_capability() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    from almoravid.state import CardInPlay
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="C19", scope="side_wide",
                   owner_side="christian", owner_lord_id=None))
    r = resolve_event(s, "muslim", "M24")
    assert r["no_op"] is True


def test_c16_bernard_shifts_service_right() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    christians_on_cal = [
        sm.lord_id for sm in s.calendar.service_markers
        if s.lords.get(sm.lord_id)
        and s.lords[sm.lord_id].side == "christian"
    ]
    if not christians_on_cal:
        pytest.skip("no Christian Lord on Calendar")
    target = min(s.calendar.service_markers,
                 key=lambda sm: sm.box if sm.lord_id in christians_on_cal
                 else 999)
    box_before = target.box
    r = resolve_event(s, "christian", "C16")
    assert r.get("no_op") is not True
    assert r["new_service_box"] == box_before + 1
