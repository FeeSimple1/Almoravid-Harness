"""GROW (4.9.2) Ravage-marker removal is a player choice (DECISION-008).

Each side SELECTS which Enemy Ravage markers to reduce; the per-Taifa
Ravaged distribution feeds Surrender (4.5.1) / Enforcing Parias (4.7.2), so
the choice matters. grow_choices exposes it; default stays deterministic.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction
from almoravid.campaign import _apply_grow_harvest_repairs
from almoravid.scenarios import load_scenario


def test_grow_choices_removes_the_selected_marker() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for loc in s.locales.values():
        loc.ravaged = "none"
    greens = list(s.locales)[:3]
    for lid in greens:
        s.locales[lid].ravaged = "green"          # 3 -> Christian removes 1
    pick = sorted(greens)[2]                       # default would take [0]
    out = _apply_grow_harvest_repairs(
        s, prev_box=2, grow_choices={"green": [pick]})
    assert s.locales[pick].ravaged == "none"
    assert out["grow"]["christian_removed_green"] == [pick]
    assert all(s.locales[g].ravaged == "green"
               for g in greens if g != pick)


def test_grow_choices_validates_count() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for loc in s.locales.values():
        loc.ravaged = "none"
    greens = list(s.locales)[:3]
    for lid in greens:
        s.locales[lid].ravaged = "green"
    with pytest.raises(IllegalAction):
        _apply_grow_harvest_repairs(
            s, prev_box=2, grow_choices={"green": greens[:2]})  # too many
