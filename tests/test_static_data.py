"""Phase 1a static data tests.

Validates that the JSON files under data/static/ load, contain the
expected entity counts (cross-checked against the curated references),
and are referentially consistent with each other.

Bug-pattern invariants tested here:
  - Pattern 4: Ways are unique by (sorted pair, way_type); the
    locale-pair -> way_types map is exposed so Phase 1b lookups can
    handle parallel Ways correctly. (Almoravid has 0 parallel pairs;
    the invariant must still hold so the harness stays robust.)
  - Pattern 14: every Capability card has an explicit scope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "almoravid" / "data" / "static"


@pytest.fixture(scope="module")
def taifas() -> dict:
    return json.loads((STATIC / "taifas.json").read_text())


@pytest.fixture(scope="module")
def locales() -> dict:
    return json.loads((STATIC / "locales.json").read_text())


@pytest.fixture(scope="module")
def ways() -> dict:
    return json.loads((STATIC / "ways.json").read_text())


@pytest.fixture(scope="module")
def lords() -> dict:
    return json.loads((STATIC / "lords.json").read_text())


@pytest.fixture(scope="module")
def cards() -> dict:
    return json.loads((STATIC / "cards.json").read_text())


# ---- Counts (cross-checked against Almoravid reference texts) ----------

def test_seven_muslim_taifas_plus_two_kingdoms(taifas: dict) -> None:
    assert len(taifas["taifas"]) == 7
    assert set(taifas["taifas"].keys()) == {
        "toledo", "badajoz", "zaragoza", "lerida", "valencia", "sevilla", "granada"
    }
    assert taifas["taifas"]["toledo"]["never_independent"] is True
    assert taifas["taifas"]["sevilla"]["vp_multiplier"] == 3
    assert taifas["taifas"]["sevilla"]["status_boxes"] == 3
    assert set(taifas["christian_kingdoms"].keys()) == {"leon", "aragon"}


def test_72_locales(locales: dict) -> None:
    """Map reference: 72 Locales total."""
    assert len(locales["locales"]) == 72


def test_109_ways_72_roads_37_passes(ways: dict) -> None:
    """Map reference: 109 Ways total (72 Roads + 37 Passes)."""
    way_list = ways["ways"]
    assert len(way_list) == 109
    assert sum(1 for w in way_list if w["way_type"] == "road") == 72
    assert sum(1 for w in way_list if w["way_type"] == "pass") == 37


def test_16_lords_9_muslim_7_christian(lords: dict) -> None:
    """Lord reference: 9 Muslim + 7 Christian = 16 Lords."""
    assert len(lords["lords"]) == 16
    by_side: dict[str, int] = {"muslim": 0, "christian": 0}
    for l in lords["lords"].values():
        by_side[l["side"]] += 1
    assert by_side == {"muslim": 9, "christian": 7}


def test_52_cards_26_per_side(cards: dict) -> None:
    """AoW reference: 26 numbered cards per side."""
    by_side: dict[str, int] = {"christian": 0, "muslim": 0}
    for c in cards["cards"].values():
        by_side[c["side"]] += 1
    assert by_side == {"christian": 26, "muslim": 26}


# ---- Referential integrity --------------------------------------------

def test_every_locale_territory_exists(taifas: dict, locales: dict) -> None:
    territories = set(taifas["taifas"]) | set(taifas["christian_kingdoms"])
    for lid, loc in locales["locales"].items():
        assert loc["territory"] in territories, f"{lid}: unknown territory {loc['territory']}"


def test_every_way_endpoint_exists(locales: dict, ways: dict) -> None:
    locale_ids = set(locales["locales"].keys())
    for w in ways["ways"]:
        assert w["a"] in locale_ids, f"way {w}: unknown a"
        assert w["b"] in locale_ids, f"way {w}: unknown b"
        assert w["a"] != w["b"], f"way self-loop: {w}"


def test_every_lord_seat_exists(locales: dict, lords: dict) -> None:
    locale_ids = set(locales["locales"].keys())
    for lid, l in lords["lords"].items():
        for s in l["seats"]:
            assert s in locale_ids, f"lord {lid}: seat {s} not in locales"


def test_seats_match_in_both_directions(locales: dict, lords: dict) -> None:
    """lord.seats and locale.printed_seats must agree."""
    locale_seats: dict[str, list[str]] = {}
    for lid, loc in locales["locales"].items():
        for s in loc["printed_seats"]:
            locale_seats.setdefault(s, []).append(lid)
    for lid, l in lords["lords"].items():
        lord_seats = set(l["seats"])
        reverse = set(locale_seats.get(lid, []))
        assert lord_seats == reverse, (
            f"lord {lid}: seats={sorted(lord_seats)} != reverse-lookup={sorted(reverse)}"
        )


# ---- Bug-pattern invariants -------------------------------------------

def test_pattern_4_no_duplicate_ways(ways: dict) -> None:
    """Pattern 4 (parallel Ways): (sorted pair, way_type) must be unique."""
    seen: set[tuple] = set()
    for w in ways["ways"]:
        key = (tuple(sorted([w["a"], w["b"]])), w["way_type"])
        assert key not in seen, f"duplicate way: {w}"
        seen.add(key)


def test_pattern_4_parallel_way_count(ways: dict) -> None:
    """Document Almoravid's parallel-Way exposure. Should be 0 in 1085-1086 map."""
    pair_types: dict[tuple, set[str]] = {}
    for w in ways["ways"]:
        pair = tuple(sorted([w["a"], w["b"]]))
        pair_types.setdefault(pair, set()).add(w["way_type"])
    parallel = {p: t for p, t in pair_types.items() if len(t) > 1}
    assert parallel == {}, (
        f"Map currently has {len(parallel)} parallel-Way locale-pairs: {parallel}. "
        "If this count changes, update Phase 1b way_type-aware lookups (Pattern 4)."
    )


def test_pattern_14_every_capability_has_scope(cards: dict) -> None:
    """Pattern 14: every Capability half must specify scope (this_lord or side_wide)."""
    for cid, c in cards["cards"].items():
        if c["no_capability"]:
            assert c["capability_scope"] is None
            assert c["capability_name"] is None
        else:
            assert c["capability_scope"] in ("this_lord", "side_wide"), (
                f"{cid}: capability_scope is {c['capability_scope']!r}, must be this_lord or side_wide"
            )
            assert c["capability_name"], f"{cid}: capability has no name"


def test_every_card_has_at_least_one_half(cards: dict) -> None:
    """Sanity: a card with no event AND no capability is meaningless."""
    for cid, c in cards["cards"].items():
        assert not (c["no_event"] and c["no_capability"]), f"{cid}: both halves null"


def test_event_persistence_values(cards: dict) -> None:
    """Pattern 7: event_persistence must be 'immediate' or 'hold' (or null for no_event)."""
    for cid, c in cards["cards"].items():
        if c["no_event"]:
            assert c["event_persistence"] is None
            assert c["event_name"] is None
        else:
            assert c["event_persistence"] in ("immediate", "hold"), (
                f"{cid}: event_persistence={c['event_persistence']!r}"
            )


def test_marshals_have_command_4(lords: dict) -> None:
    """Spot-check Lord ratings: Yusuf and Alfonso are Marshals (Command 4 cards)."""
    assert lords["lords"]["yusuf"]["marshal"] is True
    assert lords["lords"]["alfonso"]["marshal"] is True
    assert lords["lords"]["alfonso"]["command"] == 4
