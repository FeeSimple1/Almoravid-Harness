"""Phase 3c effective-state helper tests.

Pattern 5: every overlay-aware lookup goes through effective.py; raw
reads of locale.base_type / locale.ravaged outside this module are an
audit smell.
"""

from __future__ import annotations

from almoravid.effective import (
    effective_stronghold_type,
    effective_stronghold_value,
    has_gardens,
    is_besieged,
    is_bypassed,
    is_friendly_locale,
)
from almoravid.scenarios import load_scenario


# ---- Stronghold type / value ------------------------------------------

def test_toledo_is_a_city() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert effective_stronghold_type(s, "toledo") == "city"
    assert effective_stronghold_value(s, "toledo") == 3


def test_lerida_is_a_fortress() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert effective_stronghold_type(s, "lerida") == "fortress"
    assert effective_stronghold_value(s, "lerida") == 2


def test_sevilla_is_a_city() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert effective_stronghold_type(s, "sevilla") == "city"


def test_zamora_is_a_castle() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert effective_stronghold_type(s, "zamora") == "castle"
    assert effective_stronghold_value(s, "zamora") == 1


def test_region_has_no_stronghold_value() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert effective_stronghold_value(s, "sahagun") == 0


def test_gardens_at_city_and_fortress() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert has_gardens(s, "toledo") is True       # City
    assert has_gardens(s, "lerida") is True       # Fortress
    assert has_gardens(s, "leon") is False        # Town
    assert has_gardens(s, "zamora") is False      # Castle


# ---- Friendliness rule 1.3.1 ------------------------------------------

def test_christian_kingdom_friendly_to_christian() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # León is a Christian Kingdom -> Friendly to Christian, not to Muslim.
    assert is_friendly_locale(s, "leon", "christian") is True
    assert is_friendly_locale(s, "leon", "muslim") is False


def test_independent_taifa_friendly_to_muslim() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Scenario A: Zaragoza is Independent -> Muslim-friendly.
    assert s.taifas["zaragoza"].status == "independent"
    assert is_friendly_locale(s, "zaragoza", "muslim") is True
    assert is_friendly_locale(s, "zaragoza", "christian") is False


def test_parias_taifa_is_neutral() -> None:
    """Rule 1.3.1: a Parias Taifa is Neutral — friendly to neither side
    UNLESS the specific Locale has a Conquered, Seat, or Jihad marker
    overriding it.

    Madrid is a Town in Toledo Taifa with no overrides; Toledo is Parias
    in Scenario A.
    """
    s = load_scenario("scenario_a_toledo_beset")
    assert s.taifas["toledo"].status == "parias"
    assert s.locales["madrid"].conquered_markers == 0
    assert s.locales["madrid"].jihad_markers == 0
    assert s.locales["madrid"].seat_marker_lord_ids == []
    assert is_friendly_locale(s, "madrid", "christian") is False
    assert is_friendly_locale(s, "madrid", "muslim") is False


def test_reconquista_taifa_friendly_to_christian() -> None:
    s = load_scenario("scenario_b_quelling_of_tajo")
    # Scenario B: Toledo Taifa is Reconquista -> Christian-friendly.
    assert s.taifas["toledo"].status == "reconquista"
    assert is_friendly_locale(s, "talavera", "christian") is True
    assert is_friendly_locale(s, "talavera", "muslim") is False


def test_jihad_marker_makes_locale_muslim_friendly() -> None:
    """Rule 1.3.1: a Jihad marker is Muslim-friendly, even on a
    Reconquista Christian Taifa."""
    s = load_scenario("scenario_a_toledo_beset")
    # Scenario A: Calatrava in Parias Toledo with 2 Jihad markers.
    assert s.locales["calatrava"].jihad_markers == 2
    assert is_friendly_locale(s, "calatrava", "muslim") is True


def test_seat_marker_friendly_to_seat_owner_side() -> None:
    """Locale with Yusuf's Seat marker on it -> Muslim-friendly."""
    s = load_scenario("scenario_d_arrival")
    assert "yusuf" in s.locales["algeciras"].seat_marker_lord_ids
    assert is_friendly_locale(s, "algeciras", "muslim") is True


# ---- Besieged / Bypassed ----------------------------------------------

def test_lord_outside_stronghold_not_besieged() -> None:
    """Álvar Fáñez at Toledo with siege_yellow=1 but in_stronghold=False
    (he's the besieger, not the besieged) -> not Besieged."""
    s = load_scenario("scenario_a_toledo_beset")
    af = s.lords["alvar_fanez"]
    assert af.cylinder.locale_id == "toledo"
    assert af.in_stronghold is False
    assert is_besieged(s, "alvar_fanez") is False


def test_lord_in_stronghold_with_enemy_siege_is_besieged() -> None:
    """Synthetic test: place a Muslim Lord inside Toledo with a yellow
    Siege marker (Christian-placed)."""
    s = load_scenario("scenario_a_toledo_beset")
    # Move a Muslim Lord into Toledo for this test
    from almoravid.state import Cylinder
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.lords["al_mutamid"].in_stronghold = True
    # Toledo already has siege_yellow=1
    assert is_besieged(s, "al_mutamid") is True


def test_bypass_yellow_makes_muslim_in_stronghold_bypassed() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.locales["sevilla"].bypass_yellow = True
    s.lords["al_mutamid"].in_stronghold = True
    assert is_bypassed(s, "al_mutamid") is True


def test_lord_not_at_locale_not_besieged() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Yusuf is set_aside in Scenario A
    assert s.lords["yusuf"].cylinder.kind == "set_aside"
    assert is_besieged(s, "yusuf") is False
    assert is_bypassed(s, "yusuf") is False
