"""Playtest F4: printed home Seats (pennants) do NOT confer Locale
Friendliness; only placed Seat MARKERS do (rule 1.3.1). Set-aside
special Lords have no Seat marker on the map."""
from __future__ import annotations

from almoravid.scenarios import load_scenario
from almoravid.effective import is_friendly_locale
from almoravid.state import Cylinder


def test_parias_capital_printed_seat_is_neutral() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Lerida: al-Mundir's printed Seat, in a Parias (Neutral) Taifa, and
    # al-Mundir is set aside. It must be Neutral, not Muslim-Friendly.
    loc = s.locales["lerida"]
    assert loc.printed_seat_lord_ids == ["al_mundir"]
    assert loc.seat_marker_lord_ids == []   # no placed marker
    assert not is_friendly_locale(s, "lerida", "muslim")
    assert not is_friendly_locale(s, "lerida", "christian")  # Neutral


def test_set_aside_yusuf_sir_have_no_seat_marker() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Yusuf/Sir are set aside in Scenario A -> no double-Seat marker.
    assert s.lords["yusuf"].cylinder.kind != "locale"
    assert "yusuf" not in s.locales["algeciras"].seat_marker_lord_ids
    assert "sir" not in s.locales["algeciras"].seat_marker_lord_ids


def test_placed_seat_marker_confers_friendliness() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Simulate a placed Christian Seat marker (e.g., Cathedral / Rodrigo)
    # at an otherwise-Neutral Parias locale -> Friendly to Christians.
    loc = s.locales["lerida"]
    loc.seat_marker_lord_ids = ["alfonso"]   # alfonso is Christian
    assert is_friendly_locale(s, "lerida", "christian")
    assert not is_friendly_locale(s, "lerida", "muslim")


def test_yusuf_sir_double_seat_placed_when_mustered() -> None:
    # When Yusuf is on the map at setup, the double-Seat marker sits at
    # his printed Seat (Algeciras). Use a scenario where he's present.
    for name in ("scenario_d_arrival", "scenario_e_alfonso",
                 "scenario_f_reconquista"):
        s = load_scenario(name)
        y = s.lords.get("yusuf")
        if y is not None and y.cylinder.kind == "locale":
            assert "yusuf" in s.locales["algeciras"].seat_marker_lord_ids
            return
    import pytest
    pytest.skip("no scenario starts with Yusuf mustered")
