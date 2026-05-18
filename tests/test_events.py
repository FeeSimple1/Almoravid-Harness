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


def test_betrayal_of_terms_no_op_when_no_siege() -> None:
    """Pattern 10: C9 Betrayal of Terms with no active Siege -> no-op."""
    s = load_scenario("scenario_b_quelling_of_tajo")  # no Siege markers
    # Sanity: confirm no Siege markers in this scenario
    for loc in s.locales.values():
        assert loc.siege_yellow == 0
        assert loc.siege_green == 0
    r = resolve_event(s, "christian", "C9")
    assert r["no_op"] is True
    assert "C9" in s.decks.discard


def test_betrayal_of_terms_active_when_siege_present() -> None:
    """Same card, with a Siege marker on the map, defers to Phase 5
    instead of no-op."""
    s = load_scenario("scenario_a_toledo_beset")  # Toledo has siege_yellow=1
    r = resolve_event(s, "christian", "C9")
    assert r.get("no_op") is not True
    assert r.get("deferred") == "phase_5"


def test_taifa_marriage_no_op_on_invalid_target() -> None:
    """Pattern 10: TAIFA MARRIAGE with bogus taifa_id no-ops."""
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "muslim", "M12", {"taifa_id": "not_a_taifa"})
    assert r["no_op"] is True


def test_taifa_marriage_with_valid_target_defers() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    r = resolve_event(s, "muslim", "M12", {"taifa_id": "toledo"})
    assert r.get("no_op") is not True
    assert r["target_taifa"] == "toledo"


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
    s = load_scenario("scenario_a_toledo_beset")
    # Muslim Lords have coin in this scenario
    r = resolve_event(s, "christian", "C10")
    assert r.get("no_op") is not True
    assert r["target_lord_ids"]  # non-empty


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
