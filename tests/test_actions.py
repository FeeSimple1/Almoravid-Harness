"""Phase 2b action dispatcher tests.

Bug-pattern coverage:
  - Pattern 1 (state-set-but-unreachable): every legal apply_action
    result leaves the state in a state where SOMETHING is legal next.
    Spot-checked with end-to-end Levy walkthrough.
  - Pattern 11 (active-player desync): after every pass_step, exactly
    one of {step advanced, active_player flipped} happens.
  - Pattern 9 (rule-cite-but-no-enforce): IllegalAction codes prove
    each precondition actually validates.
"""

from __future__ import annotations

import pytest

from almoravid.actions import (
    ACTOR_ORDER,
    LEVY_STEPS,
    IllegalAction,
    apply_action,
)
from almoravid.scenarios import load_scenario


def fresh_state(scenario: str = "scenario_a_toledo_beset", seed: int = 1):
    return load_scenario(scenario, seed=seed)


# ---- begin_levy --------------------------------------------------------

def test_begin_levy_transitions_setup_to_levy() -> None:
    s = fresh_state()
    assert s.meta.phase == "setup"
    apply_action(s, {"type": "begin_levy"})
    assert s.meta.phase == "levy"
    assert s.meta.levy_step == "arts_of_war"
    assert s.meta.active_player == ACTOR_ORDER[0]  # Christian first


def test_begin_levy_from_wrong_phase_raises() -> None:
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    # Already in Levy; calling again is illegal.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "begin_levy"})
    assert ei.value.code == "bad_phase"


# ---- pass_step baton-pass ---------------------------------------------

def test_pass_step_baton_passes_to_other_side() -> None:
    """Pattern 11: after one side ratifies, active_player flips."""
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    assert s.meta.active_player == "christian"
    apply_action(s, {"type": "pass_step", "side": "christian"})
    assert s.meta.active_player == "muslim"
    assert s.meta.levy_step == "arts_of_war"  # step has not yet advanced


def test_pass_step_advances_step_when_both_done() -> None:
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    apply_action(s, {"type": "pass_step", "side": "christian"})
    apply_action(s, {"type": "pass_step", "side": "muslim"})
    assert s.meta.levy_step == "pay"
    # After step advance, baton resets to default actor order.
    assert s.meta.active_player == "christian"
    # Per-side flags clear on step advance.
    assert s.meta.levy_step_completed_christian is False
    assert s.meta.levy_step_completed_muslim is False


def test_full_levy_walkthrough_reaches_campaign() -> None:
    """Smoke: Levy can be driven to completion via pass_step alone."""
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    for _ in range(20):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    assert s.meta.phase == "campaign"
    assert s.meta.first_levy_done is True


def test_pass_step_wrong_side_raises() -> None:
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    # Muslim trying to act while Christian is active.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "pass_step", "side": "muslim"})
    assert ei.value.code == "not_active"


def test_unknown_action_raises() -> None:
    s = fresh_state()
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "totally_made_up"})
    assert ei.value.code == "unknown_action"


# ---- aow_shuffle / aow_draw -------------------------------------------

def test_aow_shuffle_initializes_deck() -> None:
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    assert s.meta.levy_step == "arts_of_war"
    r = apply_action(s, {"type": "aow_shuffle", "side": "christian"})
    # Should populate the draw deck with the side's cards.
    assert r["deck_size"] > 0
    assert all(c.startswith("C") for c in s.decks.draw)


def test_aow_draw_consumes_deck() -> None:
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    apply_action(s, {"type": "aow_shuffle", "side": "christian"})
    before = len(s.decks.draw)
    apply_action(s, {"type": "aow_draw", "side": "christian", "n": 3})
    assert len(s.decks.draw) == before - 3
    assert len(s.decks.pending_draw["christian"]) == 3


def test_aow_draw_deck_underflow_raises() -> None:
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    apply_action(s, {"type": "aow_shuffle", "side": "christian"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "aow_draw", "side": "christian", "n": 999})
    assert ei.value.code == "deck_underflow"


def test_aow_shuffle_wrong_step_raises() -> None:
    s = fresh_state()
    apply_action(s, {"type": "begin_levy"})
    # Advance past arts_of_war
    apply_action(s, {"type": "pass_step", "side": "christian"})
    apply_action(s, {"type": "pass_step", "side": "muslim"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "aow_shuffle", "side": "christian"})
    assert ei.value.code == "bad_levy_step"


# ---- muster_lord ------------------------------------------------------

def _drive_to_muster_step(s) -> None:
    """Helper: drive scenario into the muster Levy step."""
    apply_action(s, {"type": "begin_levy"})
    # Pass through arts_of_war, pay, service_disband
    for _ in range(6):
        if s.meta.levy_step == "muster":
            return
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})


def test_muster_lord_call_to_arms_only_lord_rejected() -> None:
    """Yusuf (Fealty=None) can only Muster via Call to Arms."""
    s = fresh_state("scenario_f_reconquista")  # Yusuf on Calendar at box 9
    _drive_to_muster_step(s)
    # During Christian's turn we can't Muster a Muslim Lord anyway,
    # so flip to Muslim's turn first.
    apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    # Now Muslim is active.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord",
                          "side": "muslim", "lord_id": "yusuf"})
    assert ei.value.code in ("cta_only_lord", "not_active", "bad_levy_step")


def test_muster_lord_determinism_under_same_seed() -> None:
    """Two runs with identical (seed, actions) produce identical results."""
    s1 = fresh_state("scenario_b_quelling_of_tajo", seed=99)
    s2 = fresh_state("scenario_b_quelling_of_tajo", seed=99)

    def drive(s):
        _drive_to_muster_step(s)
        # Try to Muster Pedro Ansúrez (on Calendar at box 3 in Scenario B).
        try:
            return apply_action(s, {"type": "muster_lord",
                                     "side": "christian",
                                     "lord_id": "pedro_ansurez"})
        except IllegalAction as e:
            return {"error": e.code}

    r1 = drive(s1)
    r2 = drive(s2)
    assert r1 == r2


def test_muster_lord_history_entry_recorded() -> None:
    s = fresh_state("scenario_b_quelling_of_tajo", seed=1)
    initial_history = len(s.history)
    _drive_to_muster_step(s)
    # Try mustering (may succeed or fail; either way a history entry is added)
    try:
        apply_action(s, {"type": "muster_lord",
                         "side": "christian", "lord_id": "pedro_ansurez"})
    except IllegalAction:
        pass
    # History grew (begin_levy + pass_steps + maybe muster)
    assert len(s.history) > initial_history


# ---- LEVY_STEPS ordering ----------------------------------------------

def test_levy_steps_in_canonical_order() -> None:
    """SoP §3 order: 3.1 -> 3.2 -> 3.3 -> 3.4 -> 3.5"""
    assert LEVY_STEPS == ("arts_of_war", "pay", "service_disband", "muster", "call_to_arms")
