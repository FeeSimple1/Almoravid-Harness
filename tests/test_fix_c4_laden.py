"""FIX-C / C4 Laden transport-carrying + Cart-over-Pass (rule 4.3.2)."""

from __future__ import annotations

from almoravid.campaign import _is_laden
from almoravid.scenarios import load_scenario


def _lord(s, **assets):
    l = s.lords["alfonso"]
    l.assets = dict(assets)
    return l


def test_provender_fitting_one_per_transport_is_not_laden() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # 2 Provender on 2 Transport (1 each) -> NOT Laden.
    assert _is_laden(_lord(s, prov=2, cart=1, mule=1)) is False


def test_provender_exceeding_transport_is_laden() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # 3 Provender on 2 Transport -> a unit carries two -> Laden.
    assert _is_laden(_lord(s, prov=3, cart=1, mule=1)) is True


def test_any_loot_is_laden() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    assert _is_laden(_lord(s, loot=1)) is True


def test_cart_with_one_prov_over_pass_is_laden() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord = _lord(s, prov=1, cart=1)            # no Mule -> Cart carries it
    assert _is_laden(lord, way_type="road") is False  # fits 1-per-unit
    assert _is_laden(lord, way_type="pass") is True   # Cart over Pass


def test_mule_carries_prov_over_pass_not_laden() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # 1 Provender on a Mule over a Pass -> Mules cross Passes freely.
    assert _is_laden(_lord(s, prov=1, mule=1), way_type="pass") is False
