"""CLI state-file flow tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
ENV = {"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"}


def _run(*args, expect_code: int = 0):
    r = subprocess.run(
        [sys.executable, "-m", "almoravid.cli", *args],
        capture_output=True, text=True, env=ENV,
    )
    if expect_code is not None:
        assert r.returncode == expect_code, (
            f"args={args} stderr={r.stderr}")
    return r


def test_new_writes_state_file(tmp_path) -> None:
    state = tmp_path / "g.json"
    r = _run("new", "scenario_a_toledo_beset", "-o", str(state), "--seed", "7")
    assert state.exists()
    data = json.loads(state.read_text())
    assert data["meta"]["scenario_letter"] == "A"
    assert data["meta"]["seed"] == 7


def test_state_summary_one_line(tmp_path) -> None:
    state = tmp_path / "g.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    r = _run("state", str(state))
    assert "Scenario A" in r.stdout
    assert "phase=setup" in r.stdout
    assert "active=christian" in r.stdout


def test_legal_emits_one_action_per_line(tmp_path) -> None:
    state = tmp_path / "g.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    r = _run("legal", str(state))
    lines = [l for l in r.stdout.strip().splitlines() if l]
    assert lines
    # Each line is a JSON action
    for line in lines:
        m = json.loads(line)
        assert "type" in m


def test_do_executes_action_and_writes_state(tmp_path) -> None:
    state = tmp_path / "g.json"
    action = tmp_path / "a.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    action.write_text(json.dumps({"type": "begin_levy"}))
    r = _run("do", str(state), str(action))
    assert "OK" in r.stdout
    # State file overwritten with post-action state
    data = json.loads(state.read_text())
    assert data["meta"]["phase"] == "levy"
    assert data["meta"]["levy_step"] == "arts_of_war"


def test_do_with_output_does_not_overwrite_input(tmp_path) -> None:
    state = tmp_path / "g.json"
    out = tmp_path / "g2.json"
    action = tmp_path / "a.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    action.write_text(json.dumps({"type": "begin_levy"}))
    _run("do", str(state), str(action), "-o", str(out))
    # Input unchanged
    assert json.loads(state.read_text())["meta"]["phase"] == "setup"
    # Output has post-action state
    assert json.loads(out.read_text())["meta"]["phase"] == "levy"


def test_illegal_action_exits_with_code_2(tmp_path) -> None:
    state = tmp_path / "g.json"
    action = tmp_path / "a.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    # Try to pass_step before begin_levy: phase=setup -> bad_phase
    action.write_text(json.dumps({"type": "pass_step", "side": "christian"}))
    r = _run("do", str(state), str(action), expect_code=2)
    assert "illegal_action" in r.stderr
    assert "bad_phase" in r.stderr


def test_malformed_action_json_exits_with_code_2(tmp_path) -> None:
    state = tmp_path / "g.json"
    action = tmp_path / "a.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    action.write_text("not valid JSON {{")
    r = _run("do", str(state), str(action), expect_code=2)
    assert "not valid JSON" in r.stderr


def test_history_shows_entries(tmp_path) -> None:
    state = tmp_path / "g.json"
    action = tmp_path / "a.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    action.write_text(json.dumps({"type": "begin_levy"}))
    _run("do", str(state), str(action))
    r = _run("history", str(state))
    assert "begin_levy" in r.stdout
    # load_scenario also writes a system history entry
    assert "load_scenario" in r.stdout


def test_pending_reports_none_when_no_decision_owed(tmp_path) -> None:
    state = tmp_path / "g.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    r = _run("pending", str(state))
    assert r.stdout.strip() == "none"


def test_view_focus_requires_target(tmp_path) -> None:
    state = tmp_path / "g.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    r = _run("view", str(state), "-m", "focus", expect_code=1)
    assert "--focus-target required" in r.stderr


def test_view_focus_on_lord(tmp_path) -> None:
    state = tmp_path / "g.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    r = _run("view", str(state), "-m", "focus", "--focus-target", "alfonso")
    assert "Alfonso VI" in r.stdout


def test_multi_step_playthrough_via_cli(tmp_path) -> None:
    """End-to-end: drive a few Levy steps through the CLI alone."""
    state = tmp_path / "g.json"
    action = tmp_path / "a.json"
    _run("new", "scenario_a_toledo_beset", "-o", str(state))
    # begin_levy
    action.write_text(json.dumps({"type": "begin_levy"}))
    _run("do", str(state), str(action))

    def _do(act):
        action.write_text(json.dumps(act))
        _run("do", str(state), str(action))

    def _draw_deploy_pass(side):
        # 3.1.2 (first Levy): draw two, deploy each as a Capability, pass.
        _do({"type": "aow_draw", "side": side})
        data = json.loads(state.read_text())
        for cid in list(data["decks"]["pending_draw"].get(side, [])):
            _do({"type": "aow_deploy_capability", "side": side,
                 "card_id": cid})
        _do({"type": "pass_step", "side": side})

    _draw_deploy_pass("christian")
    _draw_deploy_pass("muslim")
    # Should now be at pay step
    data = json.loads(state.read_text())
    assert data["meta"]["levy_step"] == "pay"


def test_scenarios_command_lists_all_six(tmp_path) -> None:
    r = _run("scenarios")
    lines = r.stdout.strip().splitlines()
    # Six campaign scenarios + the Sagrajas battle-only minigame.
    assert len(lines) == 7
    assert any("sagrajas" in ln for ln in lines)


def test_new_with_unknown_scenario_exits_with_code_1(tmp_path) -> None:
    state = tmp_path / "g.json"
    r = _run("new", "scenario_z_not_real", "-o", str(state), expect_code=1)
    assert "scenario_z_not_real" in r.stderr
