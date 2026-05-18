"""Phase 3a Campaign tests: Plan, Activation, Pass-command, end-of-Campaign."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import PLAN_SIZE_BY_SEASON, _plan_target_size
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import list_scenarios, load_scenario


def _drive_to_campaign(s) -> None:
    """Walk through Levy via pass_step until phase=campaign."""
    apply_action(s, {"type": "begin_levy"})
    for _ in range(20):
        if s.meta.phase != "levy":
            return
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})


def test_begin_campaign_enters_plan_step() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    assert s.meta.campaign_step == "plan"
    assert s.meta.active_player == "christian"
    assert "christian" in s.decks.plan
    assert "muslim" in s.decks.plan


def test_plan_size_by_season() -> None:
    assert PLAN_SIZE_BY_SEASON["spring"] == 7
    assert PLAN_SIZE_BY_SEASON["summer"] == 8
    assert PLAN_SIZE_BY_SEASON["autumn"] == 7
    # Scenario A begins at box 1 (spring) -> target 7
    s = load_scenario("scenario_a_toledo_beset")
    assert _plan_target_size(s) == 7


def test_plan_add_card_rejects_overfull_plan() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    target = _plan_target_size(s)
    # Fill Christian plan to target with pass cards
    for _ in range(target):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    assert ei.value.code == "plan_full"


def test_plan_add_command_rejects_wrong_side_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": "yusuf"})
    assert ei.value.code == "wrong_side"


def test_finalize_plan_rejects_short_plan() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "pass"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "finalize_plan", "side": "christian"})
    assert ei.value.code == "plan_size_mismatch"


def test_both_finalize_advances_to_activation() -> None:
    """Pattern 11: both sides must ratify before step advances."""
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    target = _plan_target_size(s)
    for _ in range(target):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
        apply_action(s, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    # After only one side finalizes, still in plan step
    assert s.meta.campaign_step == "plan"
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    # Both finalized; activation step
    assert s.meta.campaign_step == "activation"
    assert s.meta.active_player == "christian"


def test_command_reveal_pass_card_auto_passes() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    target = _plan_target_size(s)
    for _ in range(target):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
        apply_action(s, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    r = apply_action(s, {"type": "command_reveal", "side": "christian"})
    assert r["auto_pass"] is True
    assert s.meta.active_lord_id is None
    # Baton flipped to Muslim
    assert s.meta.active_player == "muslim"


def test_command_reveal_active_lord_with_actions() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    target = _plan_target_size(s)
    # Christian plans Alfonso command first, then 6 passes
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    for _ in range(target - 1):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    for _ in range(target):
        apply_action(s, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    r = apply_action(s, {"type": "command_reveal", "side": "christian"})
    assert r["auto_pass"] is False
    assert s.meta.active_lord_id == "alfonso"
    # Alfonso's command rating is 4 (Marshal)
    assert s.meta.actions_remaining == 4


def test_cmd_pass_consumes_action() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    target = _plan_target_size(s)
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    for _ in range(target - 1):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    for _ in range(target):
        apply_action(s, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})
    assert s.meta.actions_remaining == 4
    apply_action(s, {"type": "cmd_pass", "side": "christian"})
    assert s.meta.actions_remaining == 3
    apply_action(s, {"type": "cmd_pass", "side": "christian"})
    assert s.meta.actions_remaining == 2


def test_end_card_clears_per_card_flags() -> None:
    """Pattern 3: per-card flags must reset on end_card."""
    s = load_scenario("scenario_a_toledo_beset")
    # Alfonso starts on map; pre-flag him
    s.lords["alfonso"].first_march_used_this_card = True
    s.lords["alfonso"].lordship_used = 2
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    target = _plan_target_size(s)
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    for _ in range(target - 1):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    for _ in range(target):
        apply_action(s, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})
    apply_action(s, {"type": "end_card", "side": "christian"})
    assert s.lords["alfonso"].first_march_used_this_card is False
    assert s.lords["alfonso"].lordship_used == 0


def test_end_campaign_advances_calendar_and_returns_to_levy() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    target = _plan_target_size(s)
    for _ in range(target):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
        apply_action(s, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    # Reveal all pass cards
    for _ in range(target * 2):
        if s.meta.campaign_step != "activation":
            break
        apply_action(s, {"type": "command_reveal",
                         "side": s.meta.active_player})
    assert s.meta.campaign_step == "end_campaign"
    prev_box = s.calendar.current_box
    apply_action(s, {"type": "end_campaign"})
    # Scenario A box 1 -> box 2 (still inside scenario_a span 1-3)
    assert s.calendar.current_box == prev_box + 1
    # And we're back in Levy
    assert s.meta.phase == "levy"
    assert s.meta.turn_index == 1


@pytest.mark.parametrize("name", list_scenarios())
def test_self_play_drives_through_one_full_turn(name: str) -> None:
    """Pattern 1: Levy -> Campaign -> (Levy or ended) loop has no stalls.

    Greedy first-legal-move agent. For scenarios with a Scenario End
    marker right after the first Campaign, the loop should reach 'ended'.
    """
    s = load_scenario(name, seed=13)
    for step in range(2000):
        if s.meta.phase == "ended":
            return  # success
        moves = legal_moves(s)
        assert moves, (
            f"{name}: zero legal moves at "
            f"phase={s.meta.phase} levy_step={s.meta.levy_step} "
            f"campaign_step={s.meta.campaign_step} active={s.meta.active_player} "
            f"after {step} actions"
        )
        # Pick move that progresses fastest:
        # - prefer finalize_plan / pass_step / end_card / end_campaign
        priority = [
            "finalize_plan", "pass_step", "command_reveal",
            "end_card", "end_campaign", "cmd_pass",
            "begin_levy", "begin_campaign", "plan_add_card",
        ]
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
        try:
            apply_action(s, chosen)
        except IllegalAction as e:
            pytest.fail(
                f"{name}: legal_moves -> apply_action mismatch on {chosen}: "
                f"{e.code}"
            )
    pytest.fail(f"{name}: did not finish within 2000 actions")
