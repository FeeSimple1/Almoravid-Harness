"""Phase 5h end-of-card Feed (4.8.1) tests."""

from __future__ import annotations

import math

import pytest

from almoravid.actions import apply_action
from almoravid.campaign import _feed_lord
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_feed_lord_no_op_when_not_moved_fought() -> None:
    """A Lord that didn't Move/Fight doesn't Feed (rule 4.8.1)."""
    s = load_scenario("scenario_a_toledo_beset")
    s.lords["alfonso"].moved_fought = False
    prov_before = s.lords["alfonso"].assets.get("prov", 0)
    r = _feed_lord(s, "alfonso")
    assert r.get("skipped") == "did_not_move_fight"
    assert s.lords["alfonso"].assets["prov"] == prov_before


def test_feed_lord_consumes_prov_when_moved_fought() -> None:
    """ceil((units + mules) / 6) Provender consumed."""
    s = load_scenario("scenario_a_toledo_beset")
    alf = s.lords["alfonso"]
    alf.moved_fought = True
    units = sum(alf.forces.values())
    mules = alf.assets.get("mule", 0)
    expected_needed = math.ceil((units + mules) / 6)
    prov_before = alf.assets.get("prov", 0)
    r = _feed_lord(s, "alfonso")
    assert r["needed"] == expected_needed
    expected_consumed = min(prov_before, expected_needed)
    assert r["use_prov"] == expected_consumed


def test_feed_lord_falls_through_to_loot() -> None:
    """If Prov insufficient, Loot covers the rest."""
    s = load_scenario("scenario_a_toledo_beset")
    alf = s.lords["alfonso"]
    alf.moved_fought = True
    alf.assets["prov"] = 0
    alf.assets["loot"] = 5
    r = _feed_lord(s, "alfonso")
    # All needed consumed from Loot
    assert r["use_prov"] == 0
    assert r["use_loot"] == r["needed"]


def test_feed_lord_unfed_shifts_service_left() -> None:
    """Unfed: Service marker shifts 1 box left (4.8.1 penalty)."""
    from almoravid.state import ServiceMarker
    s = load_scenario("scenario_a_toledo_beset")
    alf = s.lords["alfonso"]
    alf.moved_fought = True
    alf.assets["prov"] = 0
    alf.assets["loot"] = 0
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=4))
    r = _feed_lord(s, "alfonso")
    assert r["unfed_penalty"] is True
    sm = next(s for s in s.calendar.service_markers if s.lord_id == "alfonso")
    assert sm.box == 3  # Shifted left


def test_end_card_clears_moved_fought_after_feed() -> None:
    """Per-card reset includes moved_fought (Pattern 3)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    for _ in range(6):
        apply_action(s, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "pass"})
    for _ in range(7):
        apply_action(s, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})
    # March to set moved_fought
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road"})
    assert s.lords["alfonso"].moved_fought is True
    apply_action(s, {"type": "end_card", "side": "christian"})
    # After end_card: moved_fought reset, Prov consumed
    assert s.lords["alfonso"].moved_fought is False
