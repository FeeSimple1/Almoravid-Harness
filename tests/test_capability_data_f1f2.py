"""Playtest F1/F2: capability card-data corrections (Arts of War Ref).
F1: C14 & C17 carry the Cabalgadas this_lord capability (was missing).
F2: C8 Hueste and M9 Emir al-Muslimin are this_lord (were side_wide)."""
from __future__ import annotations

from almoravid.static_data import load_cards


def test_cabalgadas_present_on_c14_and_c17() -> None:
    c = load_cards()["cards"]
    for k in ("C14", "C17"):
        assert c[k]["capability_name"] == "Cabalgadas"
        assert c[k]["capability_scope"] == "this_lord"
        assert c[k]["no_capability"] is False


def test_hueste_and_emir_are_this_lord() -> None:
    c = load_cards()["cards"]
    assert c["C8"]["capability_name"] == "Hueste"
    assert c["C8"]["capability_scope"] == "this_lord"
    assert c["M9"]["capability_name"] == "Emir al-Muslimin"
    assert c["M9"]["capability_scope"] == "this_lord"


def test_cabalgadas_same_title_blocks_second_copy() -> None:
    # 3.4.4: a Lord may have only one Cabalgadas card (no two same-title
    # This-Lord caps). C14 and C17 share the title, so the limit applies.
    from almoravid.scenarios import load_scenario
    from almoravid.actions import _check_this_lord_cap_limits, IllegalAction
    import pytest
    s = load_scenario("scenario_a_toledo_beset")
    al = s.lords["alfonso"]
    al.capabilities = ["C14"]   # holds Cabalgadas (via C14)
    with pytest.raises(IllegalAction) as ei:
        _check_this_lord_cap_limits(al, "C17")  # also Cabalgadas
    assert ei.value.code == "duplicate_this_lord_title"
