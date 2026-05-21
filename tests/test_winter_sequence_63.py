"""Winter sequence fixes (6.3.1 coin + Beyond-Service, 6.3.4 Plowing,
6.3.5 box-9 Capabilities) — Scenario F."""
from __future__ import annotations

from almoravid.scenarios import load_scenario
from almoravid.campaign import winter_disband, winter_plowing
from almoravid.actions import aow_capability_phase
from almoravid.state import Cylinder, ServiceMarker


def _on_map_taifa_lord(s):
    return next(l for l in s.lords.values()
               if l.is_taifa and l.cylinder.kind == "locale")


def test_winter_disband_taifa_coin_to_box() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.calendar.current_box = 7
    tl = _on_map_taifa_lord(s)
    # Ensure not at a Siege and give him Coin.
    loc = s.locales[tl.cylinder.locale_id]
    loc.siege_yellow = 0
    loc.siege_green = 0
    tl.assets["coin"] = 3
    # In-service so he Disbands to mat (not Beyond-Service removed).
    s.calendar.service_markers = [
        ServiceMarker(lord_id=tl.id, box=7)]
    before = s.taifas_box_coin
    r = winter_disband(s)
    assert tl.id in r["disbanded_to_mat"]
    assert s.taifas_box_coin == before + 3
    assert tl.cylinder.kind == "mat"


def test_winter_disband_beyond_service_removed() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.calendar.current_box = 7
    tl = _on_map_taifa_lord(s)
    loc = s.locales[tl.cylinder.locale_id]
    loc.siege_yellow = 0
    loc.siege_green = 0
    # Service marker LEFT of the box -> Beyond Service -> removed.
    s.calendar.service_markers = [
        ServiceMarker(lord_id=tl.id, box=5)]
    r = winter_disband(s)
    assert tl.id in r["beyond_service_removed"]
    assert tl.cylinder.kind == "removed"


def test_winter_plowing_halves_siege_lord_transport() -> None:
    s = load_scenario("scenario_f_reconquista")
    lord = next(l for l in s.lords.values() if l.cylinder.kind == "locale")
    loc = s.locales[lord.cylinder.locale_id]
    loc.siege_yellow = 1   # mark as a Siege Locale
    lord.assets["cart"] = 3
    lord.assets["mule"] = 2
    out = winter_plowing(s)
    assert any(p["lord_id"] == lord.id for p in out["plowed"])
    assert lord.assets["cart"] == 2   # ceil(3/2)
    assert lord.assets["mule"] == 1   # ceil(2/2)


def test_box9_is_capability_phase_in_scenario_f() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.meta.first_levy_done = True
    s.calendar.current_box = 9
    assert aow_capability_phase(s) is True
    # A normal later box implements Events, not Capabilities.
    s.calendar.current_box = 10
    assert aow_capability_phase(s) is False


def test_box9_capability_phase_only_scenario_f() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.meta.first_levy_done = True
    s.calendar.current_box = 9
    assert aow_capability_phase(s) is False   # not Scenario F
