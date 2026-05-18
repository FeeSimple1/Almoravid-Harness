"""Enumerator/handler round-trip sweep.

CROSS_PROJECT_LESSONS.md §2 audit pattern:
  For every scenario, drive 50 steps and verify EVERY action the
  enumerator emits would be accepted by the handler if applied.

This is the single highest-yield divergence catch per the Nevsky
retrospective. The cheaper variant (test_every_legal_move_apply_succeeds
in test_legal_moves.py) only checks the initial state; this sweep
drives the state forward and re-checks at each step.

Per CROSS_PROJECT_LESSONS.md §7 'source-marker regression tests': SMOKE
markers in source modules are asserted present so a future silent
refactor that removes a filter (and the comment) fails CI immediately.
"""

from __future__ import annotations

import copy

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import list_scenarios, load_scenario


@pytest.mark.parametrize("name", list_scenarios())
def test_enumerator_handler_roundtrip_sweep(name: str) -> None:
    """For each scenario, drive 50 steps and at each step verify every
    enumerated action is accepted by apply_action on a snapshot.

    This is the sweep recommended in CROSS_PROJECT_LESSONS.md §2:
      'Couple this with source-marker regression tests... Cheap
       insurance: a future refactor that removes the filter also
       removes the comment, and CI fails immediately.'
    """
    s = load_scenario(name, seed=13)
    priority = [
        "finalize_plan", "pass_step",
        "command_reveal", "cmd_march", "end_card",
        "end_campaign", "cmd_pass", "plan_add_card",
    ]
    for step in range(50):
        if s.meta.phase == "ended":
            break
        moves = legal_moves(s)
        assert moves, (
            f"{name} step {step}: zero legal moves at "
            f"phase={s.meta.phase} levy={s.meta.levy_step} "
            f"campaign={s.meta.campaign_step} active={s.meta.active_player}"
        )
        # Every offered move must be accepted on a snapshot.
        for move in moves:
            snap = copy.deepcopy(s)
            try:
                apply_action(snap, move)
            except IllegalAction as e:
                pytest.fail(
                    f"{name} step {step}: enumerator emitted illegal "
                    f"{move['type']}: {e.code} ({e}). "
                    f"State: phase={s.meta.phase} "
                    f"levy={s.meta.levy_step} "
                    f"campaign={s.meta.campaign_step} "
                    f"active={s.meta.active_player}. "
                    f"Move: {move}"
                )
        # Advance one step using priority-pick.
        chosen = None
        for pt in priority:
            for m in moves:
                if m["type"] == pt:
                    chosen = m
                    break
            if chosen:
                break
        if chosen is None:
            chosen = moves[0]
        apply_action(s, chosen)


# ---- Source-marker regression tests (CROSS_PROJECT_LESSONS.md §7) -----


def test_cross_project_lessons_referenced_in_brief() -> None:
    """BRIEF references CROSS_PROJECT_LESSONS.md so the architectural
    lessons stay visible to the next contributor."""
    import inspect
    from pathlib import Path
    brief = Path(__file__).resolve().parent.parent / "BRIEF.md"
    text = brief.read_text()
    assert "CROSS_PROJECT_LESSONS.md" in text


def test_legal_moves_has_defensive_try_except_marker() -> None:
    """CROSS_PROJECT_LESSONS.md §1 idiom: enumerator wraps static-data
    lookups in try/except. The comment marker is asserted present so a
    silent refactor (delete the wrap, delete the comment) fails CI."""
    import inspect

    from almoravid import legal_moves as lm
    src = inspect.getsource(lm)
    assert "CROSS_PROJECT_LESSONS.md §1" in src, (
        "The defensive try/except wrap in legal_moves was removed without "
        "removing the marker. Re-add per CROSS_PROJECT_LESSONS.md §1."
    )


def test_pattern_10_marker_in_events_source() -> None:
    """Pattern 10 no-target-no-op marker must remain in events.py source."""
    import inspect

    from almoravid import events
    src = inspect.getsource(events)
    assert "Pattern 10" in src, (
        "Pattern 10 marker removed from events.py — if the no-target-no-op "
        "discipline was actually removed, those resolvers will raise on "
        "missing targets again (SMOKE-112/113/114 family from Nevsky)."
    )


def test_pattern_14_marker_in_capabilities_source() -> None:
    """Pattern 14 scope-filter marker must remain in capabilities.py."""
    import inspect

    from almoravid import capabilities
    src = inspect.getsource(capabilities)
    assert "Pattern 14" in src
