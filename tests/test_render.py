"""Phase 1c render tests."""

from __future__ import annotations

import pytest

from almoravid.render import render_focus, render_summary, render_verbose
from almoravid.scenarios import list_scenarios, load_scenario


@pytest.mark.parametrize("name", list_scenarios())
def test_summary_renders(name: str) -> None:
    state = load_scenario(name)
    out = render_summary(state)
    assert isinstance(out, str)
    assert len(out) > 0
    # Header carries the essentials
    assert state.meta.scenario_letter in out
    assert state.meta.active_player in out


@pytest.mark.parametrize("name", list_scenarios())
def test_verbose_is_superset_of_summary(name: str) -> None:
    state = load_scenario(name)
    summary = render_summary(state)
    verbose = render_verbose(state)
    # Verbose contains the summary header
    first_line = summary.splitlines()[0]
    assert first_line in verbose
    # And adds more lines
    assert len(verbose.splitlines()) > len(summary.splitlines())


def test_focus_on_lord() -> None:
    state = load_scenario("scenario_a_toledo_beset")
    out = render_focus(state, "alfonso")
    assert "Alfonso VI" in out
    assert "alfonso" in out
    assert "Vassals:" in out
    assert "Froila Bermudez" in out


def test_focus_on_locale() -> None:
    state = load_scenario("scenario_a_toledo_beset")
    out = render_focus(state, "toledo")
    assert "Toledo" in out
    assert "Siege-Y" in out  # Scenario A starts with a Siege on Toledo
    assert "Ravaged" in out
    assert "Neighbors:" in out


def test_focus_unknown_target_raises() -> None:
    state = load_scenario("scenario_a_toledo_beset")
    with pytest.raises(ValueError, match="Unknown focus target"):
        render_focus(state, "not_a_real_thing")


def test_summary_includes_taifa_statuses() -> None:
    state = load_scenario("scenario_b_quelling_of_tajo")
    out = render_summary(state)
    assert "Tol=R" in out  # Toledo Reconquista in Scenario B


def test_summary_includes_locale_markers() -> None:
    state = load_scenario("scenario_d_arrival")
    out = render_summary(state)
    assert "Locale markers:" in out
    # Scenario D has Conquered yellow at Toledo
    assert "Toledo" in out
    assert "Conq" in out


def test_verbose_includes_calendar_decorations() -> None:
    state = load_scenario("scenario_a_toledo_beset")
    out = render_verbose(state)
    assert "Calendar:" in out
    assert "Box  1" in out or "Box 1" in out
    assert "scenario_end" in out  # Scenario End marker at box 3


def test_cli_view_summary_runs(tmp_path) -> None:
    """`almoravid view state.json` renders the summary."""
    import subprocess
    import sys
    from pathlib import Path
    env = {"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
           "PATH": "/usr/bin:/bin"}
    state_file = tmp_path / "state.json"
    # Initialize state first
    r = subprocess.run(
        [sys.executable, "-m", "almoravid.cli", "new",
         "scenario_a_toledo_beset", "-o", str(state_file)],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    # Now view it
    r = subprocess.run(
        [sys.executable, "-m", "almoravid.cli", "view", str(state_file)],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    assert "Scenario A" in r.stdout
