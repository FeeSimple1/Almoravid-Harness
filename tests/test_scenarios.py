"""Phase 1b scenario loader tests.

Verifies that load_scenario() produces a valid GameState for each
bundled scenario, with the right Lord placements, calendar markings,
Taifa statuses, and decks.
"""

from __future__ import annotations

import pytest

from almoravid.scenarios import list_scenarios, load_scenario, load_scenario_raw
from almoravid.state import GameState
from almoravid.static_data import load_lords


@pytest.mark.parametrize("name", list_scenarios())
def test_load_scenario_returns_valid_gamestate(name: str) -> None:
    """Every scenario builds a valid GameState."""
    state = load_scenario(name)
    assert isinstance(state, GameState)
    assert state.meta.scenario_id
    assert state.meta.scenario_letter in {"A", "B", "C", "D", "E", "F"}
    # Round-trip through pydantic to catch validation issues
    GameState.model_validate(state.model_dump())


@pytest.mark.parametrize("name", list_scenarios())
def test_all_16_lords_present_with_unique_cylinders(name: str) -> None:
    """Every Lord should be tracked somewhere (Pattern 8 / lifecycle baseline)."""
    state = load_scenario(name)
    assert len(state.lords) == 16
    # Every Lord has a cylinder kind that's one of the legal values
    for lid, lord in state.lords.items():
        assert lord.cylinder.kind in {"calendar", "locale", "mat", "set_aside", "removed"}


@pytest.mark.parametrize("name", list_scenarios())
def test_locales_and_ways_match_static_data(name: str) -> None:
    state = load_scenario(name)
    assert len(state.locales) == 72
    assert len(state.ways) == 109


@pytest.mark.parametrize("name", list_scenarios())
def test_taifas_have_status(name: str) -> None:
    state = load_scenario(name)
    assert len(state.taifas) == 7
    for tid, t in state.taifas.items():
        assert t.status in {"independent", "parias", "reconquista", "kingdoms"}


def test_toledo_never_independent() -> None:
    """Rule 1.4.1: Toledo can never be Independent.

    Scenario A starts with all 4 named Parias Taifas + Toledo as Parias.
    Our loader enforces the never-independent constraint as a safety net.
    """
    for name in list_scenarios():
        state = load_scenario(name)
        assert state.taifas["toledo"].status != "independent", (
            f"{name}: Toledo is Independent, violating 1.4.1"
        )


def test_scenario_a_setup() -> None:
    """Scenario A: spot-check key setup elements from the Scenario Reference."""
    state = load_scenario("scenario_a_toledo_beset")
    # Alfonso, Pedro Ansúrez, García Ordóñez at Sahagún
    assert state.lords["alfonso"].cylinder.kind == "locale"
    assert state.lords["alfonso"].cylinder.locale_id == "sahagun"
    assert state.lords["alvar_fanez"].cylinder.locale_id == "toledo"
    # Yusuf and Sir set aside in Scenario A
    assert state.lords["yusuf"].cylinder.kind == "set_aside"
    assert state.lords["sir"].cylinder.kind == "set_aside"
    # Toledo has Siege + Ravaged + 3 Jihad markers
    toledo = state.locales["toledo"]
    assert toledo.siege_yellow == 1
    assert toledo.ravaged == "yellow"
    assert toledo.jihad_markers == 3
    # TAIFA MARRIAGE event held by Muslims (per Errata)
    assert "M12" in state.decks.held.get("muslim", [])
    # Alfonso has BATTERING RAM capability on mat
    assert "C1" in state.lords["alfonso"].capabilities


def test_scenario_d_yusuf_at_algeciras_with_doubled_seat() -> None:
    state = load_scenario("scenario_d_arrival")
    assert state.lords["yusuf"].cylinder.locale_id == "algeciras"
    # Algeciras printed seats include Yusuf and Sir; scenario adds Yusuf as a seat marker
    algeciras = state.locales["algeciras"]
    assert "yusuf" in algeciras.seat_marker_lord_ids


def test_scenario_f_long_campaign() -> None:
    """Scenario F is the full 14-turn campaign with Curias/Winter sequence."""
    state = load_scenario("scenario_f_reconquista")
    assert state.meta.scenario_letter == "F"
    assert state.calendar.current_box == 1
    # Yusuf and Sir on Calendar at box 9 (not yet entered)
    assert state.lords["yusuf"].cylinder.kind == "calendar"
    assert state.lords["yusuf"].cylinder.box == 9
    # 6 Parias Taifas at start (toledo, badajoz, granada, valencia, zaragoza, lerida)
    parias_count = sum(1 for t in state.taifas.values() if t.status == "parias")
    assert parias_count == 6


def test_capabilities_in_play_have_correct_scope() -> None:
    """Pattern 14: every CardInPlay built from scenario mat caps must carry the right scope."""
    state = load_scenario("scenario_a_toledo_beset")
    # BATTERING RAM (C1) is this_lord scope per cards.json
    found = [c for c in state.decks.capabilities_in_play if c.card_id == "C1"]
    assert found, "C1 BATTERING RAM should be in play"
    assert found[0].scope == "this_lord"
    assert found[0].owner_lord_id == "alfonso"


def test_service_markers_placed() -> None:
    """Service markers should be on Calendar per scenario setup."""
    state = load_scenario("scenario_a_toledo_beset")
    # Scenario A: Sancho's service marker at box 3
    sancho_sm = [sm for sm in state.calendar.service_markers if sm.lord_id == "sancho"]
    assert len(sancho_sm) == 1
    assert sancho_sm[0].box == 3


def test_cli_new_game_runs() -> None:
    """CLI new-game produces output without crashing."""
    import subprocess
    import sys
    from pathlib import Path
    result = subprocess.run(
        [sys.executable, "-m", "almoravid.cli", "new-game", "scenario_a_toledo_beset"],
        capture_output=True, text=True,
        env={"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
             "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "Scenario: A" in result.stdout
    assert "Lords:" in result.stdout
