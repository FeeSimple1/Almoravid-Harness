"""FIX-E / E1 GROW, E2 HARVEST, E3 REPAIRS (rules 4.9.2-4.9.3) and
FIX-D / T6 Curias Taifas-box deduction (rule 6.2.2 / 5.1)."""

from __future__ import annotations

from almoravid.campaign import _apply_grow_harvest_repairs, apply_curias
from almoravid.scenarios import load_scenario


def _ravage_n(s, color: str, n: int) -> None:
    locs = list(s.locales.values())[:n]
    for loc in locs:
        loc.ravaged = color


def test_grow_halves_both_colors_second_spring() -> None:
    """End of second Spring (box 2): each side reduces ENEMY Ravage
    markers to half (round up) -> remove floor(n/2)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for loc in s.locales.values():
        loc.ravaged = "none"
    _ravage_n(s, "green", 5)      # Muslim markers -> Christian removes 2
    # tag a separate disjoint set yellow
    ylocs = [loc for loc in s.locales.values() if loc.ravaged == "none"][:4]
    for loc in ylocs:
        loc.ravaged = "yellow"    # Christian markers -> Muslim removes 2
    out = _apply_grow_harvest_repairs(s, prev_box=2)
    green_left = sum(1 for loc in s.locales.values() if loc.ravaged == "green")
    yellow_left = sum(1 for loc in s.locales.values() if loc.ravaged == "yellow")
    assert green_left == 3   # ceil(5/2)
    assert yellow_left == 2  # ceil(4/2)
    assert out["grow"] is not None


def test_grow_does_not_run_outside_second_spring() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for loc in s.locales.values():
        loc.ravaged = "none"
    _ravage_n(s, "green", 4)
    out = _apply_grow_harvest_repairs(s, prev_box=1)  # first Spring
    assert out["grow"] is None
    assert sum(1 for loc in s.locales.values()
               if loc.ravaged == "green") == 4


def test_harvest_halves_carts_and_mules_second_summer() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lid = next(l.id for l in s.lords.values()
               if l.cylinder.kind == "locale")
    s.lords[lid].assets["cart"] = 3
    s.lords[lid].assets["mule"] = 4
    out = _apply_grow_harvest_repairs(s, prev_box=4)  # second Summer
    assert s.lords[lid].assets.get("cart") == 2   # ceil(3/2)
    assert s.lords[lid].assets.get("mule") == 2   # ceil(4/2)
    assert out["harvest"]


def test_repairs_removes_one_from_3or4_stacks_not_winter() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    locs = list(s.locales.values())
    locs[0].siege_yellow = 4
    locs[1].siege_green = 3
    locs[2].siege_yellow = 2   # untouched
    out = _apply_grow_harvest_repairs(s, prev_box=3)  # Summer (not Winter)
    assert locs[0].siege_yellow == 3
    assert locs[1].siege_green == 2
    assert locs[2].siege_yellow == 2


def test_repairs_skipped_in_winter() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    locs = list(s.locales.values())
    locs[0].siege_yellow = 4
    out = _apply_grow_harvest_repairs(s, prev_box=7)  # Winter
    assert locs[0].siege_yellow == 4   # unchanged
    assert out["repairs"] == []


def test_t6_curias_reduces_taifas_box_not_christian_score() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.taifas_box_vp = 5.0
    s.score.christian = 7.0
    apply_curias(s, 5)   # box 5 places TWO Curias markers
    assert s.taifas_box_vp == 3.0       # 5 - 2
    assert s.score.christian == 7.0     # unchanged
