"""Phase 5a March (rule 4.3) tests.

Bug-pattern coverage:
  - Pattern 1: every legal_moves March entry is accepted by apply_action.
  - Pattern 4: way_type is honored; agent's choice never silently
    swapped for a parallel Way.
  - Pattern 9: every cited rule (4.3.2 Laden 2 actions, 4.3.2 Cart-
    over-Pass restriction, 4.5.3 Besieged-Lord limits) is actually
    enforced — try to violate each and verify IllegalAction.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad, step_levy


def _setup_alfonso_active(seed: int = 1):
    """Drive Scenario A to a state where Alfonso has an active Command card."""
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})
    return s


def test_march_unladen_costs_one_action() -> None:
    """Alvar Fanez has Cart + 1 Prov (1 Prov < 2 => Unladen)."""
    s = load_scenario("scenario_a_toledo_beset")
    af = s.lords["alvar_fanez"]
    assert af.assets.get("prov", 0) == 1  # Unladen
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alvar_fanez"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})
    before = s.meta.actions_remaining
    # Alvar Fanez at Toledo can march to Talavera, Calatrava, Madrid, Uclés, Zancara (via Road).
    r = apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "calatrava", "way_type": "road"})
    assert r["laden"] is False
    assert r["cost"] == 1
    assert s.meta.actions_remaining == before - 1


def test_march_laden_costs_two_actions() -> None:
    """C4 (4.3.2): Laden when Provender exceeds Transport (a unit carries
    two). Alfonso has Transport 2; give him 3 Provender -> Laden."""
    s = _setup_alfonso_active()
    s.lords["alfonso"].assets["prov"] = 3   # 3 > transport(2) -> Laden
    before = s.meta.actions_remaining
    r = apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "road"})
    assert r["laden"] is True
    assert r["cost"] == 2
    assert s.meta.actions_remaining == before - 2


def test_march_rejects_non_adjacent_target() -> None:
    """Pattern 9: rule 4.3 — March is to an adjacent Locale."""
    s = _setup_alfonso_active()
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "sevilla", "way_type": "road"})
    assert ei.value.code == "not_adjacent"


def test_march_pattern_4_way_type_honored() -> None:
    """Pattern 4: explicit way_type must match the actual Way.

    Alfonso at Sahagún has road neighbors (León, Palencia, Burgos) but
    no Pass neighbors. Marching to León via pass is illegal.
    """
    s = _setup_alfonso_active()
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "pass"})
    assert ei.value.code == "not_adjacent"


def test_march_cart_over_pass_with_prov_is_legal_laden() -> None:
    """C4 (4.3.2): a Cart carrying Provender over a Pass is LEGAL but
    Laden (costs two actions) — not rejected. A single Cart with one
    Provender (no Mule) over a Pass triggers the Laden Pass rule."""
    s = _setup_alfonso_active()
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="pamplona")
    s.lords["alfonso"].assets = {"cart": 1, "prov": 1}  # cart carries prov
    before = s.meta.actions_remaining
    r = apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "jaca", "way_type": "pass"})
    assert r["laden"] is True
    assert r["cost"] == 2
    assert s.meta.actions_remaining == before - 2


def test_besieged_lord_cannot_march() -> None:
    """Rule 4.5.3: Besieged Lord may only Sally / Forage (Gardens) / Pass."""
    s = _setup_alfonso_active()
    # Force Alfonso into a besieged state synthetically.
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.lords["alfonso"].in_stronghold = True
    # Make it a Muslim Siege on a Christian-held Toledo (synthetic).
    s.lords["alfonso"].side  # already christian
    s.locales["toledo"].siege_green = 1  # Muslim-placed
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "talavera", "way_type": "road"})
    assert ei.value.code == "besieged"


def test_march_not_enough_actions() -> None:
    """Laden March needs 2 actions; if only 1 left, reject."""
    s = _setup_alfonso_active()
    s.lords["alfonso"].assets["prov"] = 3   # 3 > transport(2) -> Laden
    # Pass three times to leave 1 action remaining (Alfonso command=4)
    apply_action(s, {"type": "cmd_pass", "side": "christian"})
    apply_action(s, {"type": "cmd_pass", "side": "christian"})
    apply_action(s, {"type": "cmd_pass", "side": "christian"})
    assert s.meta.actions_remaining == 1
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "road"})
    assert ei.value.code == "not_enough_actions"


def test_march_sets_per_card_flags() -> None:
    """Pattern 3 (per-card scope): first_march_used_this_card flag set."""
    s = _setup_alfonso_active()
    assert s.lords["alfonso"].first_march_used_this_card is False
    assert s.lords["alfonso"].moved_fought is False
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road"})
    assert s.lords["alfonso"].first_march_used_this_card is True
    assert s.lords["alfonso"].moved_fought is True


def test_per_card_flag_resets_on_end_card() -> None:
    """Pattern 3: per-card flags must reset on end_card."""
    s = _setup_alfonso_active()
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road"})
    assert s.lords["alfonso"].first_march_used_this_card is True
    apply_action(s, {"type": "end_card", "side": "christian"})
    assert s.lords["alfonso"].first_march_used_this_card is False


def test_legal_moves_enumerates_march_destinations() -> None:
    """Pattern 1: every adjacent Locale via every way_type is offered."""
    s = _setup_alfonso_active()
    moves = legal_moves(s)
    marches = [m for m in moves if m["type"] == "cmd_march"]
    # Sahagún road neighbors: León, Palencia, Burgos
    targets = {(m["target_locale_id"], m["way_type"]) for m in marches}
    assert ("leon", "road") in targets
    assert ("palencia", "road") in targets
    assert ("burgos", "road") in targets


def test_legal_moves_offers_legal_cart_over_pass_with_prov() -> None:
    """Pattern 1/9 mirror, corrected: a Cart-over-Pass March is LEGAL but
    Laden (4.3.2, see test_march_cart_over_pass_with_prov_is_legal_laden),
    so legal_moves MUST advertise it — and it must round-trip. (Regression
    for the menu defect that suppressed this legal central-route March.)"""
    s = _setup_alfonso_active()
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="pamplona")
    s.lords["alfonso"].assets = {"cart": 1, "prov": 1}   # Laden over a Pass
    pass_moves = [m for m in legal_moves(s)
                  if m["type"] == "cmd_march" and m["way_type"] == "pass"
                  and m["target_locale_id"] == "jaca"
                  and "group_lord_ids" not in m]
    assert pass_moves, "legal_moves suppressed a legal Cart-over-Pass March"
    before = s.meta.actions_remaining
    r = apply_action(s, pass_moves[0])
    assert r["laden"] is True and r["cost"] == 2
    assert s.lords["alfonso"].cylinder.locale_id == "jaca"
    assert s.meta.actions_remaining == before - 2


@pytest.mark.parametrize("name", ["scenario_a_toledo_beset", "scenario_d_arrival"])
def test_self_play_with_march_priority_advances_lords(name: str) -> None:
    """Self-play smoke: with March in the action set, the harness still
    runs to ended without stalls."""
    s = load_scenario(name, seed=11)
    priority = [
        "finalize_plan", "pass_step",
        "command_reveal", "cmd_march", "end_card",
        "end_campaign", "cmd_pass", "plan_add_card",
    ]
    for _ in range(3000):
        if s.meta.phase == "ended":
            return
        moves = legal_moves(s)
        assert moves, (
            f"{name}: zero legal moves at phase={s.meta.phase} "
            f"step={s.meta.levy_step} cstep={s.meta.campaign_step} "
            f"active={s.meta.active_player}"
        )
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
    pytest.fail(f"{name}: did not finish within 3000 actions")
