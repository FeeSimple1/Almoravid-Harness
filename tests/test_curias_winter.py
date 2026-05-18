"""Phase 5k Curias (6.2) + Winter Sequence (6.3) tests.

Scenario F-specific mechanics. The helpers are exposed for external
callers; full integration into the auto-flow at boxes 5-8 is Phase 5k+
work as the scenarios reach those boxes during play.
"""

from __future__ import annotations

from almoravid.campaign import (
    apply_curias,
    check_curias,
    spring_muster,
    winter_disband,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker


def test_check_curias_default_scenario_f_not_triggered() -> None:
    """At start of Scenario F (box 1) the condition isn't triggered:
    yellow markers ~= green markers."""
    s = load_scenario("scenario_f_reconquista")
    r = check_curias(s)
    # Scenario F starts with 1 yellow Ravaged (Toledo), 6 Jihad
    # markers (3 Toledo + 2 Calatrava + 2 Uclés + 1 Trujillo), 1 Siege
    # marker which is NOT counted by Curias.
    assert r["yellow_count"] < r["green_count"]
    assert r["triggered"] is False


def test_check_curias_triggers_with_lots_of_yellow() -> None:
    """Synthetic: paint many Locales yellow Ravaged -> Curias triggers."""
    s = load_scenario("scenario_f_reconquista")
    for lid in list(s.locales)[:20]:
        s.locales[lid].ravaged = "yellow"
    r = check_curias(s)
    assert r["triggered"] is True


def test_apply_curias_advances_levy_marker_to_box_7() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.calendar.current_box = 5
    r = apply_curias(s, 5)
    assert s.calendar.current_box == 7
    # 2 Curias markers placed (boxes 5 and 6)
    assert 5 in r["curias_placed_in_boxes"]
    assert 6 in r["curias_placed_in_boxes"]


def test_apply_curias_at_box_6_only_places_one() -> None:
    s = load_scenario("scenario_f_reconquista")
    s.calendar.current_box = 6
    r = apply_curias(s, 6)
    assert r["curias_placed_in_boxes"] == [6]
    assert s.calendar.current_box == 7


def test_apply_curias_auto_disbands_pedro_and_garcia() -> None:
    """Per Errata 6.2.2: if Pedro Ansurez or Garcia Ordonez on map, Disband."""
    s = load_scenario("scenario_f_reconquista")
    s.lords["pedro_ansurez"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    s.lords["garcia_ordonez"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.calendar.current_box = 5
    r = apply_curias(s, 5)
    assert "pedro_ansurez" in r["auto_disbanded"]
    assert "garcia_ordonez" in r["auto_disbanded"]
    assert s.lords["pedro_ansurez"].cylinder.kind == "calendar"
    assert s.lords["garcia_ordonez"].cylinder.kind == "calendar"


def test_winter_disband_moves_lords_to_mat() -> None:
    """6.3.1: Mustered Lords (no Siege) Disband to their mats."""
    s = load_scenario("scenario_f_reconquista")
    # Alfonso starts at Sahagún (region, no Siege)
    assert s.lords["alfonso"].cylinder.kind == "locale"
    r = winter_disband(s)
    assert "alfonso" in r["disbanded_to_mat"]
    assert s.lords["alfonso"].cylinder.kind == "mat"
    assert s.lords["alfonso"].forces == {}


def test_winter_disband_rodrigo_to_box_9() -> None:
    """6.3.1: Disbanding Rodrigo -> Calendar box 9 (even if Beyond Service)."""
    s = load_scenario("scenario_f_reconquista")
    s.lords["rodrigo_campeador"].cylinder = Cylinder(kind="locale", locale_id="leon")
    r = winter_disband(s)
    assert "rodrigo_campeador" in r["rodrigo_to_box_9"]
    assert s.lords["rodrigo_campeador"].cylinder.kind == "calendar"
    assert s.lords["rodrigo_campeador"].cylinder.box == 9


def test_winter_disband_keeps_lords_at_sieges() -> None:
    """6.3.2: Lords at Siege locales are NOT disbanded by 6.3.1."""
    s = load_scenario("scenario_f_reconquista")
    # Toledo has a Christian Siege marker in Scenario F initial setup
    assert s.locales["toledo"].siege_yellow == 1
    # Move Alfonso to Toledo
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    r = winter_disband(s)
    assert "alfonso" in r["lords_at_sieges_kept"]
    assert s.lords["alfonso"].cylinder.kind == "locale"


def test_winter_disband_discards_board_edge() -> None:
    """6.3.1: 'discard all board-edge Capabilities'."""
    s = load_scenario("scenario_f_reconquista")
    s.decks.board_edge["christian"] = ["C13"]
    r = winter_disband(s)
    assert "C13" in r["board_edge_discarded"]
    assert s.decks.board_edge["christian"] == []
    assert "C13" in s.decks.discard


def test_spring_muster_christian_lords_from_mats() -> None:
    """6.3.3: Christian Lords on mats Muster at free Seats."""
    s = load_scenario("scenario_f_reconquista")
    # Disband Alfonso to mat (synthetic)
    s.lords["alfonso"].cylinder = Cylinder(kind="mat")
    s.lords["alfonso"].forces = {}
    s.calendar.current_box = 8
    r = spring_muster(s)
    # Alfonso should be Mustered at Leon (his preferred Seat)
    mustered = dict(r["christian_mustered"])
    assert mustered.get("alfonso") == "leon"
    assert s.lords["alfonso"].cylinder.kind == "locale"
    assert s.lords["alfonso"].cylinder.locale_id == "leon"
    # Forces restored from static data
    assert s.lords["alfonso"].forces == {"knights": 1, "men_at_arms": 1, "serfs": 1}
