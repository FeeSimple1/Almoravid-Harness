"""Phase 5j event resolver tests — full registry coverage."""

from __future__ import annotations

import pytest

from almoravid.events import resolve_event, unresolved_event_cards
from almoravid.scenarios import load_scenario


def test_no_unresolved_event_cards() -> None:
    """Phase 5j: every card with an event half now has a resolver."""
    assert unresolved_event_cards() == []


def test_indulgences_no_op_when_no_christian_lord_on_map() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Remove all Christian Lords from the map
    for l in s.lords.values():
        if l.side == "christian":
            from almoravid.state import Cylinder
            l.cylinder = Cylinder(kind="set_aside")
    r = resolve_event(s, "christian", "C11")
    assert r["no_op"] is True


def test_indulgences_records_intent_with_target() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "christian", "C11",
                     {"target_lord_id": "alfonso"})
    assert r.get("no_op") is not True
    assert r["target"] == "alfonso"


def test_berenguer_ramon_immediate_in_phase_6k() -> None:
    """Phase 6k: C13 is now Immediate — discards no-effect when Count
    of Barcelona is with Muslims, else grants units to a target Lord."""
    s = load_scenario("scenario_a_toledo_beset")
    # Default count_of_barcelona_side is "christian", so the units-
    # granting branch fires (not the discard-no-effect branch).
    r = resolve_event(s, "christian", "C13")
    assert r.get("held") is None
    assert "C13" in s.decks.discard


def test_pope_gregory_holds_in_levy_bucket() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "christian", "C14")
    assert r["held"] == "this_levy_events"


def test_all_phase5j_resolvers_callable_without_raise() -> None:
    """Pattern 10: every resolver returns without raising."""
    s = load_scenario("scenario_a_toledo_beset")
    # Sample of cards across categories
    for cid in ("C11", "C12", "C13", "C16", "C19", "C25", "C26",
                "M8", "M9", "M11", "M15", "M19", "M22"):
        r = resolve_event(s, "christian" if cid.startswith("C") else "muslim",
                          cid)
        assert isinstance(r, dict)


def test_generic_immediate_discards_card() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    resolve_event(s, "muslim", "M15")
    assert "M15" in s.decks.discard
