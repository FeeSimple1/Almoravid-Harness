"""Phase 6d: real per-card non-combat event effects (C10, M14, M15,
M16, M17)."""

from __future__ import annotations

import math

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


# ---------------------------------------------------------------------------
# C10 Devaluation: Muslim total Coin -> ceil(*2/3)
# ---------------------------------------------------------------------------


def test_c10_drains_muslim_coin_to_two_thirds() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Set deterministic Muslim Coin totals (10 total -> ceil(10*2/3)=7).
    muslims = [l for l in s.lords.values() if l.side == "muslim"]
    for l in muslims:
        l.assets["coin"] = 0
    muslims[0].assets["coin"] = 6
    muslims[1].assets["coin"] = 4
    r = resolve_event(s, "christian", "C10")
    assert r["coin_before"] == 10
    assert r["coin_after"] == 7
    assert r["removed"] == 3
    after = sum(l.assets.get("coin", 0) for l in muslims)
    assert after == 7


def test_c10_no_op_when_no_muslim_coin() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    for l in s.lords.values():
        if l.side == "muslim":
            l.assets.pop("coin", None)
    r = resolve_event(s, "christian", "C10")
    assert r["no_op"] is True


# ---------------------------------------------------------------------------
# M14 Devaluation: per-Locale Christian Coin -> ceil(/2)
# ---------------------------------------------------------------------------


def test_m14_halves_christian_coin_per_locale() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    christians = [l for l in s.lords.values() if l.side == "christian"]
    # Park two Christian Lords at the same locale with 3 + 1 coin
    # (total 4 -> ceil(4/2)=2 — remove 2). Strip all other Christian
    # coin so we can verify per-locale halving.
    for l in christians:
        l.assets.pop("coin", None)
    christians[0].cylinder = Cylinder(kind="locale", locale_id="leon")
    christians[0].in_stronghold = False
    christians[0].assets["coin"] = 3
    christians[1].cylinder = Cylinder(kind="locale", locale_id="leon")
    christians[1].in_stronghold = False
    christians[1].assets["coin"] = 1
    r = resolve_event(s, "muslim", "M14")
    assert r["total_removed"] == 2
    after = (christians[0].assets.get("coin", 0)
             + christians[1].assets.get("coin", 0))
    assert after == 2


def test_m14_no_op_when_no_christian_coin_anywhere() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    for l in s.lords.values():
        if l.side == "christian":
            l.assets.pop("coin", None)
    r = resolve_event(s, "muslim", "M14")
    assert r["no_op"] is True


# ---------------------------------------------------------------------------
# M15 Parias Revolt: Jihad markers on a Parias-Taifa locale.
# ---------------------------------------------------------------------------


def test_m15_adds_one_jihad_default() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Force a Taifa into Parias status so M15 has a target. Clear any
    # pre-seeded Jihad markers so the +1-base branch fires.
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "parias"
    target_locale = target_taifa.locale_ids[0]
    s.locales[target_locale].jihad_markers = 0
    before = 0
    r = resolve_event(s, "muslim", "M15",
                      payload={"locale_id": target_locale})
    assert r["jihad_added"] == 1
    assert s.locales[target_locale].jihad_markers == before + 1


def test_m15_adds_two_jihad_when_already_present() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "parias"
    target_locale = target_taifa.locale_ids[0]
    s.locales[target_locale].jihad_markers = 1  # already Jihad here
    r = resolve_event(s, "muslim", "M15",
                      payload={"locale_id": target_locale})
    assert r["jihad_added"] == 2
    assert s.locales[target_locale].jihad_markers == 3


def test_m15_adds_three_jihad_when_yusuf_present() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "parias"
    target_locale = target_taifa.locale_ids[0]
    if "yusuf" in s.lords:
        s.lords["yusuf"].cylinder = Cylinder(kind="locale",
                                             locale_id=target_locale)
        s.lords["yusuf"].in_stronghold = False
        r = resolve_event(s, "muslim", "M15",
                          payload={"locale_id": target_locale})
        assert r["jihad_added"] == 3
    else:
        pytest.skip("yusuf not in this scenario")


def test_m15_no_op_when_no_parias_taifa() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    for t in s.taifas.values():
        if t.status == "parias":
            t.status = "independent"
    r = resolve_event(s, "muslim", "M15")
    assert r["no_op"] is True


# ---------------------------------------------------------------------------
# M16 Galician Revolt: Service shift + Alfonso Muster ban.
# ---------------------------------------------------------------------------


def test_m16_shifts_service_and_bans_alfonso_muster() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Pick alvar_fanez as target (he's one of the three eligibles).
    box_before = next(
        (sm.box for sm in s.calendar.service_markers
         if sm.lord_id == "alvar_fanez"), None)
    if box_before is None:
        pytest.skip("alvar_fanez not on Calendar in this scenario")
    r = resolve_event(s, "muslim", "M16",
                      payload={"lord_id": "alvar_fanez"})
    assert r["service_shifted"] == "alvar_fanez"
    assert r["new_service_box"] is not None
    assert r["new_service_box"] < box_before
    assert "alfonso" in s.meta.muster_banned_this_levy_lord_ids


def test_m16_blocks_alfonso_muster_handler() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.meta.muster_banned_this_levy_lord_ids.append("alfonso")
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": "alfonso"})
    assert ei.value.code in ("muster_banned", "not_on_calendar")


# ---------------------------------------------------------------------------
# M17 Leon y Castilla: Service shift + 4-Lord ban.
# ---------------------------------------------------------------------------


def test_m17_bans_all_four_lords_from_muster() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "muslim", "M17",
                      payload={"lord_id": "garcia_ordonez"})
    banned = set(s.meta.muster_banned_this_levy_lord_ids)
    expected = {"pedro_ansurez", "garcia_ordonez", "alvar_fanez",
                "rodrigo_campeador"}
    # Intersect with lords actually in the scenario (some may not exist).
    expected_in_scenario = expected & set(s.lords)
    assert expected_in_scenario <= banned
