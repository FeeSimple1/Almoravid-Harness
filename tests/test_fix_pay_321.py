"""FIX-A: Pay (3.2.1/3.2.2) faithful behavior — rightward shift,
Coin/Loot/Taifa-Coin, same-Locale targeting."""
from __future__ import annotations
import pytest
from almoravid.actions import IllegalAction, apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker


def _to_pay(s):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "pay")
    return s


def _set_marker(s, lid, box):
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if not (m.lord_id == lid and m.vassal_id is None)]
    s.calendar.service_markers.append(ServiceMarker(lord_id=lid, box=box))


def test_coin_shifts_rightward():
    s = load_scenario("scenario_a_toledo_beset")
    _set_marker(s, "alfonso", 4)
    s.lords["alfonso"].assets["coin"] = 2
    _to_pay(s)
    r = apply_action(s, {"type": "pay_lord", "side": "christian",
                         "payer_lord_id": "alfonso",
                         "target_lord_id": "alfonso",
                         "resource": "coin", "amount": 2})
    assert r["service_box"] == 6  # 4 + 2 rightward
    assert s.lords["alfonso"].assets.get("coin", 0) == 0


def test_loot_requires_friendly_locale_free_of_siege():
    s = load_scenario("scenario_a_toledo_beset")
    _set_marker(s, "alfonso", 4)
    # Put Alfonso on a non-Friendly (Muslim) Locale with Loot.
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords["alfonso"].assets = {"loot": 1}
    _to_pay(s)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "pay_lord", "side": "christian",
                         "payer_lord_id": "alfonso",
                         "target_lord_id": "alfonso",
                         "resource": "loot", "amount": 1})
    assert ei.value.code == "not_friendly_locale"


def test_loot_at_friendly_locale_shifts_right():
    s = load_scenario("scenario_a_toledo_beset")
    _set_marker(s, "alfonso", 3)
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["alfonso"].assets = {"loot": 1}
    _to_pay(s)
    r = apply_action(s, {"type": "pay_lord", "side": "christian",
                         "payer_lord_id": "alfonso",
                         "target_lord_id": "alfonso",
                         "resource": "loot", "amount": 1})
    assert r["service_box"] == 4


def test_coin_can_target_another_lord_same_locale():
    s = load_scenario("scenario_a_toledo_beset")
    # Two Christian Lords co-located; payer's Coin shifts the other's marker.
    others = [lid for lid, l in s.lords.items()
              if l.side == "christian" and lid != "alfonso"]
    other = others[0]
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords[other].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["alfonso"].assets["coin"] = 1
    _set_marker(s, other, 5)
    _to_pay(s)
    r = apply_action(s, {"type": "pay_lord", "side": "christian",
                         "payer_lord_id": "alfonso",
                         "target_lord_id": other,
                         "resource": "coin", "amount": 1})
    assert r["service_box"] == 6
    assert s.lords["alfonso"].assets.get("coin", 0) == 0


def test_coin_other_lord_must_be_same_locale():
    s = load_scenario("scenario_a_toledo_beset")
    others = [lid for lid, l in s.lords.items()
              if l.side == "christian" and lid != "alfonso"]
    other = others[0]
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords[other].cylinder = Cylinder(kind="locale", locale_id="burgos")
    s.lords["alfonso"].assets["coin"] = 1
    _set_marker(s, other, 5)
    _to_pay(s)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "pay_lord", "side": "christian",
                         "payer_lord_id": "alfonso", "target_lord_id": other,
                         "resource": "coin", "amount": 1})
    assert ei.value.code == "not_same_locale"


def test_taifa_box_coin_shifts_unbesieged_muslim():
    s = load_scenario("scenario_a_toledo_beset")
    s.taifas_box_coin = 2
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords["al_mutamid"].in_stronghold = False
    _set_marker(s, "al_mutamid", 6)
    _to_pay(s)
    while s.meta.active_player != "muslim":
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    r = apply_action(s, {"type": "pay_lord", "side": "muslim",
                         "target_lord_id": "al_mutamid",
                         "resource": "taifa_coin", "amount": 2})
    assert r["service_box"] == 8
    assert s.taifas_box_coin == 0
