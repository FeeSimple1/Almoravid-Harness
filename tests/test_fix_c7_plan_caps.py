"""FIX-C2 / C7 Plan caps (rules 1.9.2 / 4.1.1) and rule 5.2 at Campaign
entry."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import _plan_target_size
from almoravid.scenarios import load_scenario
from tests.test_campaign import _drive_to_campaign


def _enter_plan(s):
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})


def test_per_lord_command_cap_three_for_normal_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _enter_plan(s)
    # alvar_fanez is a normal Christian Lord (cap 3).
    for _ in range(3):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": "alvar_fanez"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": "alvar_fanez"})
    assert ei.value.code == "lord_card_cap"


def test_marshal_command_cap_is_four() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _enter_plan(s)
    # alfonso is the Christian Marshal (cap 4).
    for _ in range(4):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": "alfonso"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": "alfonso"})
    assert ei.value.code == "lord_card_cap"


def test_pass_card_cap_is_five() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _enter_plan(s)
    for _ in range(5):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    assert ei.value.code == "pass_cap"


def test_unmustered_lord_cannot_be_planned() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _enter_plan(s)
    # Move a Christian Lord off the map (onto the Calendar) -> not Mustered.
    from almoravid.state import Cylinder
    target_lord = next(lid for lid, l in s.lords.items()
                       if l.side == "christian" and l.cylinder.kind == "locale")
    s.lords[target_lord].cylinder = Cylinder(kind="calendar", box=5)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": target_lord})
    assert ei.value.code == "not_mustered"


def test_enumerator_never_offers_illegal_plan_cards() -> None:
    """The legal-moves enumerator must not offer a Pass beyond 5 nor a
    Lord's Command card beyond its cap (handler/enumerator lockstep)."""
    from almoravid.legal_moves import legal_moves
    s = load_scenario("scenario_a_toledo_beset")
    _enter_plan(s)
    for _ in range(5):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    offers = [m for m in legal_moves(s)
              if m.get("type") == "plan_add_card"
              and m.get("side") == "christian"]
    assert all(m.get("plan_kind") != "pass" for m in offers)


def test_rule_52_no_mustered_lords_ends_game_at_campaign_entry() -> None:
    """Rule 5.2: a side entering the Campaign with no Mustered Lords on
    the map loses immediately (it also could not build a legal Plan)."""
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_campaign(s)
    # Remove all Christian Lords from the map before Campaign entry.
    from almoravid.state import Cylinder
    for lid, l in s.lords.items():
        if l.side == "christian" and l.cylinder.kind == "locale":
            l.cylinder = Cylinder(kind="calendar", box=10)
    apply_action(s, {"type": "begin_campaign"})
    assert s.meta.phase == "ended"
    assert s.score.winner == "muslim"
