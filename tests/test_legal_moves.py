"""Phase 2c legal-moves tests.

Enforces Pattern 1 (state-set-but-unreachable): for any non-terminal
state, legal_moves returns at least one action. The self-play smoke
test drives every scenario with a greedy first-legal-move agent and
asserts the loop terminates only at the campaign phase.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import (list_scenarios, load_scenario,
                                  list_campaign_scenarios)
from tests._plan_helpers import step_levy


def test_initial_state_offers_begin_levy() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    moves = legal_moves(s)
    assert moves, "initial state should offer at least begin_levy"
    assert {"type": "begin_levy"} in moves


def test_arts_of_war_step_offers_mandatory_draw_not_pass() -> None:
    """3.1.2/3.1.3: a side must draw before passing the AoW step."""
    s = load_scenario("scenario_a_toledo_beset")
    apply_action(s, {"type": "begin_levy"})
    moves = legal_moves(s)
    types = {m["type"] for m in moves}
    assert "aow_draw" in types
    assert "aow_shuffle" in types
    assert "pass_step" not in types          # mandatory draw first


def test_after_shuffle_draw_is_offered() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    apply_action(s, {"type": "begin_levy"})
    apply_action(s, {"type": "aow_shuffle", "side": "christian"})
    moves = legal_moves(s)
    draw_moves = [m for m in moves if m["type"] == "aow_draw"]
    assert draw_moves, "draw should be offered after shuffle"
    # The draw is the fixed count-2 Levy draw (no chosen n).
    assert all("n" not in m for m in draw_moves)


def test_muster_step_enumerates_calendar_lords() -> None:
    """Scenario B has Pedro Ansúrez and García Ordóñez on Calendar at box 3."""
    s = load_scenario("scenario_b_quelling_of_tajo")
    apply_action(s, {"type": "begin_levy"})
    # Drive to muster step
    for _ in range(8):
        if s.meta.levy_step == "muster":
            break
        step_levy(s)
    moves = legal_moves(s)
    muster_moves = [m for m in moves if m["type"] == "muster_lord"]
    # At least Christian Calendar Lords with free Seats should be offered.
    if s.meta.active_player == "christian":
        lord_ids = {m["lord_id"] for m in muster_moves}
        assert "pedro_ansurez" in lord_ids or "garcia_ordonez" in lord_ids


@pytest.mark.parametrize("name", list_campaign_scenarios())
def test_self_play_reaches_campaign(name: str) -> None:
    """Pattern 1: greedy first-legal-move agent reaches campaign phase
    via Levy without any zero-moves stall."""
    s = load_scenario(name, seed=42)
    for action_count in range(200):
        if s.meta.phase == "campaign":
            return  # success
        moves = legal_moves(s)
        assert moves, (
            f"{name}: zero legal moves at phase={s.meta.phase} "
            f"step={s.meta.levy_step} active={s.meta.active_player} "
            f"after {action_count} actions"
        )
        chosen = next((m for m in moves if m["type"] == "pass_step"), moves[0])
        try:
            apply_action(s, chosen)
        except IllegalAction as e:  # pragma: no cover
            pytest.fail(
                f"{name}: legal_moves returned an action that apply_action "
                f"rejected: {chosen} (code={e.code})"
            )
    pytest.fail(f"{name}: did not reach campaign after 200 actions")


@pytest.mark.parametrize("name", list_scenarios())
def test_every_legal_move_apply_succeeds(name: str) -> None:
    """Pattern 9 mirror: every action legal_moves returns must be
    accepted by apply_action without IllegalAction (in a fresh state)."""
    import copy
    s = load_scenario(name, seed=7)
    if s.meta.phase == "setup":
        apply_action(s, {"type": "begin_levy"})
    moves = legal_moves(s)
    for m in moves:
        s_copy = copy.deepcopy(s)
        try:
            apply_action(s_copy, m)
        except IllegalAction as e:
            pytest.fail(f"{name}: legal_moves -> apply_action mismatch on {m}: {e.code}")
