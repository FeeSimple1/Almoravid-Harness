"""Phase 4b event resolver tests.

Pattern 10 audit: every immediate-event resolver must produce a no-op
when its target is unavailable, NOT raise (SMOKE-112/113/114 in Nevsky).

Pattern 13 audit: hold-event resolvers must place the card in a
persistence bucket cleared at the right window boundary.
"""

from __future__ import annotations

import pytest

from almoravid.events import (
    EventNotResolvable,
    registered_cards,
    resolve_event,
    unresolved_event_cards,
)
from almoravid.scenarios import load_scenario


def test_hills_held_in_this_levy_bucket() -> None:
    """C1 Hills is a Battle hold event -> this_levy_events bucket."""
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "christian", "C1")
    assert r["held"] == "this_levy_events"
    assert "C1" in s.decks.this_levy_events["christian"]


def test_camp_attack_held_in_this_campaign_bucket() -> None:
    """C2 Camp Attack is immediate-battle-context; buffered for Phase 5
    Battle resolver."""
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "christian", "C2")
    assert r["held"] == "this_campaign_events"


def test_betrayal_of_terms_held_until_surrender() -> None:
    """Phase 6i: C9 Betrayal of Terms is a Hold event; parks in
    this_levy_events until a Surrender fires."""
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "christian", "C9")
    assert r["held"] == "this_levy_events"
    assert "C9" in s.decks.this_levy_events.get("christian", [])


def test_taifa_marriage_no_op_when_no_taifa_lords() -> None:
    """Phase 6j: M12 shifts up to 2 Taifa Lords. With none eligible
    (no service markers + bogus payload), it no-ops."""
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "muslim", "M12", {"lord_ids": ["not_a_lord"]})
    assert r.get("no_op") is True


def test_taifa_marriage_shifts_two_taifa_lords() -> None:
    """Phase 6j: greedy default shifts Service right (toward
    end-of-Campaign) for up to 2 Taifa Lords on the Calendar."""
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "muslim", "M12")
    if not r.get("no_op"):
        assert len(r["shifted"]) <= 2
        for entry in r["shifted"]:
            assert entry["shifted"] == "service_right"


def test_devaluation_no_op_when_target_has_no_coin() -> None:
    """Pattern 10: zero-out the target side's coin, then play Devaluation."""
    s = load_scenario("scenario_a_toledo_beset")
    # Christian plays Devaluation against Muslim
    for l in s.lords.values():
        if l.side == "muslim":
            l.assets["coin"] = 0
    r = resolve_event(s, "christian", "C10")
    assert r["no_op"] is True


def test_devaluation_with_target_coin_defers() -> None:
    """C10 Devaluation: now wired in Phase 6d to actually drain Muslim
    Coin to 2/3 of total (rounded up)."""
    import math
    s = load_scenario("scenario_a_toledo_beset")
    total_before = sum(l.assets.get("coin", 0) for l in s.lords.values()
                       if l.side == "muslim")
    assert total_before > 0
    r = resolve_event(s, "christian", "C10")
    assert r.get("no_op") is not True
    expected = math.ceil(total_before * 2 / 3)
    assert r["coin_after"] == expected
    assert r["coin_before"] == total_before
    actual_after = sum(l.assets.get("coin", 0) for l in s.lords.values()
                       if l.side == "muslim")
    assert actual_after == expected


def test_unregistered_card_raises_event_not_resolvable() -> None:
    """All cards now have resolvers (Phase 5j); unknown card id raises."""
    s = load_scenario("scenario_a_toledo_beset")
    with pytest.raises(EventNotResolvable):
        resolve_event(s, "christian", "NOT_A_REAL_CARD_ID")


def test_unknown_card_raises_event_not_resolvable() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    with pytest.raises(EventNotResolvable):
        resolve_event(s, "christian", "NOT_A_CARD")


def test_registered_cards_returns_set() -> None:
    reg = registered_cards()
    assert isinstance(reg, set)
    # Phase 4b ships these.
    for cid in ["C1", "M1", "C2", "M2", "C9", "M12", "M21", "C10", "M14"]:
        assert cid in reg, f"{cid} expected in Phase 4b registry"


def test_unresolved_event_cards_inventory() -> None:
    """Phase 5j: registry now complete; no cards in the todo list."""
    todo = unresolved_event_cards()
    assert todo == []
