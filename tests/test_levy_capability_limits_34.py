"""3.4.4 This-Lord Capability limits (max 2, no same-title) and the
Errata free-Seat 'neither Enemy' check for Muster (3.4.1)."""
from __future__ import annotations

import pytest

from almoravid.scenarios import load_scenario
from almoravid.actions import (
    _check_this_lord_cap_limits, _free_seats_for,
)
from almoravid.actions import IllegalAction


def test_third_this_lord_cap_rejected() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    al = s.lords["alfonso"]
    al.capabilities = ["C1", "C2"]   # two This-Lord caps already
    with pytest.raises(IllegalAction) as ei:
        _check_this_lord_cap_limits(al, "C3")
    assert ei.value.code == "this_lord_cap_limit"


def test_same_title_this_lord_cap_rejected() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    al = s.lords["alfonso"]
    al.capabilities = ["C1"]         # Battering Ram
    with pytest.raises(IllegalAction) as ei:
        _check_this_lord_cap_limits(al, "C1")  # same title
    assert ei.value.code == "duplicate_this_lord_title"


def test_second_distinct_cap_allowed() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    al = s.lords["alfonso"]
    al.capabilities = ["C1"]
    _check_this_lord_cap_limits(al, "C2")   # no raise


def test_free_seats_excludes_enemy_territory_seat() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Take a Muslim Lord and make one of his Seats Enemy (Christian-
    # Conquered) — it must drop out of the free-Seat list.
    ml = next(l for l in s.lords.values() if l.side == "muslim" and l.seats)
    seat = ml.seats[0]
    from almoravid.effective import is_friendly_locale
    # Force the Seat Friendly to Christians via a Conquered marker.
    s.locales[seat].conquered_markers = 1
    s.locales[seat].seat_marker_lord_ids = []
    assert is_friendly_locale(s, seat, "christian")
    assert seat not in _free_seats_for(s, ml.id)


def test_free_seats_allows_neutral_seat() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    ml = next(l for l in s.lords.values() if l.side == "muslim" and l.seats)
    seat = ml.seats[0]
    # Make the Seat Neutral (Parias) and clear any markers/lords.
    s.locales[seat].conquered_markers = 0
    s.locales[seat].jihad_markers = 0
    s.locales[seat].seat_marker_lord_ids = []
    taifa = s.taifas.get(s.locales[seat].territory)
    if taifa is not None:
        taifa.status = "parias"
    from almoravid.effective import is_friendly_locale
    assert not is_friendly_locale(s, seat, "christian")
    assert not is_friendly_locale(s, seat, "muslim")  # Neutral
    # No enemy Lord present -> Neutral Seat stays free.
    for o in s.lords.values():
        if o.side == "christian" and o.cylinder.kind == "locale" \
                and o.cylinder.locale_id == seat:
            o.cylinder = type(o.cylinder)(kind="mat")
    assert seat in _free_seats_for(s, ml.id)
