"""Phase 4a capabilities-lookup tests.

Pattern 14 audit gate: scope filters must reject wrong-scope lookups.
"""

from __future__ import annotations

from almoravid.capabilities import (
    any_capability,
    any_lord_with_capability,
    capabilities_for_lord,
    capabilities_for_side,
    lord_has_capability,
    side_has_capability,
)
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay


def test_lord_has_capability_finds_this_lord_card() -> None:
    """Alfonso starts Scenario A with C1 BATTERING RAM on his mat (this_lord)."""
    s = load_scenario("scenario_a_toledo_beset")
    assert lord_has_capability(s, "alfonso", "C1") is True


def test_lord_has_capability_returns_false_for_side_wide_card() -> None:
    """Pattern 14: this_lord helper must reject side_wide cards even if
    they happen to be 'on' the Lord somehow."""
    s = load_scenario("scenario_a_toledo_beset")
    # C8 Cantador is side_wide; force-add to alfonso's caps list and
    # verify the helper still says False.
    s.lords["alfonso"].capabilities.append("C8")
    assert lord_has_capability(s, "alfonso", "C8") is False


def test_any_lord_with_capability() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Alfonso C1 + Álvar Fáñez C2 in Scenario A
    assert any_lord_with_capability(s, "christian", "C1") == ["alfonso"]
    assert any_lord_with_capability(s, "christian", "C2") == ["alvar_fanez"]
    # Wrong side
    assert any_lord_with_capability(s, "muslim", "C1") == []


def test_side_has_capability_with_in_play_card() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Add a side-wide capability in play
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C8", scope="side_wide", owner_side="christian",
    ))
    assert side_has_capability(s, "christian", "C8") is True
    assert side_has_capability(s, "muslim", "C8") is False


def test_side_has_capability_rejects_this_lord_card() -> None:
    """Pattern 14: side_wide helper must reject this_lord cards even if
    they're sitting in capabilities_in_play."""
    s = load_scenario("scenario_a_toledo_beset")
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C1",  # this_lord
        scope="this_lord",
        owner_side="christian",
        owner_lord_id="alfonso",
    ))
    assert side_has_capability(s, "christian", "C1") is False


def test_capabilities_for_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert capabilities_for_lord(s, "alfonso") == ["C1"]
    assert capabilities_for_lord(s, "alvar_fanez") == ["C2"]


def test_capabilities_for_lord_filters_wrong_scope() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Corrupt state: side-wide card snuck onto a Lord's mat
    s.lords["alfonso"].capabilities.append("C8")  # C8 is side_wide
    # Defensive filter strips it
    assert "C8" not in capabilities_for_lord(s, "alfonso")
    assert "C1" in capabilities_for_lord(s, "alfonso")


def test_capabilities_for_side() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C8", scope="side_wide", owner_side="christian",
    ))
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C13", scope="side_wide", owner_side="christian",
    ))
    assert set(capabilities_for_side(s, "christian")) == {"C8", "C13"}
    assert capabilities_for_side(s, "muslim") == []


def test_any_capability_dispatches_by_scope() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # this_lord: works with or without lord_id (with -> exact; without -> any)
    assert any_capability(s, "christian", "C1", lord_id="alfonso") is True
    assert any_capability(s, "christian", "C1", lord_id="alvar_fanez") is False
    assert any_capability(s, "christian", "C1") is True  # any Lord on side
    # side_wide: ignores lord_id
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C8", scope="side_wide", owner_side="christian"))
    assert any_capability(s, "christian", "C8") is True
    assert any_capability(s, "christian", "C8", lord_id="alfonso") is True
    assert any_capability(s, "muslim", "C8") is False


def test_unknown_card_returns_false() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert lord_has_capability(s, "alfonso", "NONEXISTENT") is False
    assert side_has_capability(s, "christian", "NONEXISTENT") is False
    assert any_capability(s, "christian", "NONEXISTENT") is False


def test_unknown_lord_returns_false() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert lord_has_capability(s, "not_a_lord", "C1") is False
    assert capabilities_for_lord(s, "not_a_lord") == []
