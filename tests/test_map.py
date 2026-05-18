"""Q-002 map classifier tests."""

from __future__ import annotations

from almoravid.map import (
    christian_kingdom_locales,
    has_pass,
    has_road,
    is_port,
    is_region,
    neighbors_via,
    only_accessible_via_pass,
    taifa_locales,
    way_classes_per_locale,
)


def test_way_classes_covers_every_locale() -> None:
    """Every Locale appears in the classifier, even isolated ones."""
    classes = way_classes_per_locale()
    # 72 Locales per Map reference v13
    assert len(classes) == 72


def test_toledo_has_only_roads() -> None:
    """Toledo is a Road hub; no Passes touch it."""
    assert has_road("toledo") is True
    assert has_pass("toledo") is False


def test_pamplona_jaca_pass() -> None:
    """Pyrenees Pass: Pamplona — Jaca."""
    assert "jaca" in neighbors_via("pamplona", "pass")
    assert "pamplona" in neighbors_via("jaca", "pass")
    # And there's no Road between them
    assert "jaca" not in neighbors_via("pamplona", "road")


def test_zaragoza_is_a_port() -> None:
    """Zaragoza has a river port per Map reference."""
    assert is_port("zaragoza") is True


def test_leon_is_not_a_port() -> None:
    assert is_port("leon") is False


def test_only_accessible_via_pass_finds_pass_only_locales() -> None:
    """Tormes (region) has only Passes per Map Part 3 — Transduero — Tormes
    and Tormes — Coria, no Roads incident on it."""
    classes = way_classes_per_locale()
    assert classes["tormes"] == frozenset({"pass"})
    assert only_accessible_via_pass("tormes") is True


def test_toledo_not_pass_only() -> None:
    assert only_accessible_via_pass("toledo") is False


def test_christian_kingdom_locales() -> None:
    cks = set(christian_kingdom_locales())
    # León kingdom: 17 locales; Aragón: 2 — 19 total
    assert len(cks) == 19
    assert "leon" in cks
    assert "burgos" in cks
    assert "jaca" in cks  # Aragón
    assert "pamplona" in cks  # Aragón


def test_taifa_locales_for_zaragoza() -> None:
    locs = set(taifa_locales("zaragoza"))
    expected = {"medinaceli", "calatayud", "tudela", "huesca", "zaragoza",
                "iberico", "albarracin", "alpuente"}
    assert locs == expected


def test_is_region_classifier() -> None:
    assert is_region("sahagun") is True
    assert is_region("toledo") is False  # City
    assert is_region("zamora") is False  # Castle


def test_neighbors_via_road_for_burgos() -> None:
    """Burgos road neighbors: Sahagún, Palencia, Najera."""
    nbrs = set(neighbors_via("burgos", "road"))
    assert "sahagun" in nbrs
    assert "palencia" in nbrs
    assert "najera" in nbrs


def test_neighbors_via_pass_distinct_from_road() -> None:
    """Pyrenees passes are NOT roads."""
    pass_nbrs = set(neighbors_via("jaca", "pass"))
    road_nbrs = set(neighbors_via("jaca", "road"))
    assert pass_nbrs & road_nbrs == set(), (
        f"Almoravid 1085-1086 has no parallel (a,b) way-pairs; "
        f"jaca conflict: {pass_nbrs & road_nbrs}"
    )
