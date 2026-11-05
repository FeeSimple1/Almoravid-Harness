"""A2-04: Game End precedes Harvest/Repairs, Wastage and Reset."""

from __future__ import annotations

import math

import pytest

from almoravid.actions import IllegalAction
from almoravid.campaign import compute_victory
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, GameState
from tests._reset_helpers import apply_action_keeping_reset_cards as apply_action
from tests.test_cross_game_empty_lord import attach


def position(scenario="scenario_f_reconquista", box=4):
    state = load_scenario(scenario, seed=1)
    for lord in state.lords.values():
        lord.cylinder = Cylinder(kind="mat")
        lord.forces = {}
        lord.routed_units = {}
        lord.assets = {}
        lord.capabilities = []
        lord.in_stronghold = False
    for lid, locale in [("alfonso", "leon"), ("al_mutamid", "sevilla")]:
        state.lords[lid].cylinder = Cylinder(kind="locale", locale_id=locale)
        state.lords[lid].forces = {"militia": 1}
    state.decks.capabilities_in_play = []
    for locale in state.locales.values():
        locale.ravaged = "none"
        locale.siege_yellow = locale.siege_green = 0
    state.meta.phase = "campaign"
    state.meta.campaign_step = "end_campaign"
    state.meta.active_player = "christian"
    state.calendar.current_box = box
    state.pending = None
    return state


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("off_calendar", [False, True])
def test_final_campaign_scores_before_any_cleanup(interactive, off_calendar):
    state = position(box=16 if off_calendar else 4)
    if not off_calendar:
        state.calendar.boxes[4].decorations.append("scenario_end")
    lord = state.lords["alfonso"]
    lord.assets = {"cart": 4, "mule": 4, "coin": 2}
    lord.is_lieutenant = True
    state.lords["al_mutamid"].lieutenant_of = lord.id
    state.locales["leon"].siege_yellow = 4
    mats = {lid: lord.model_dump() for lid, lord in state.lords.items()}
    plans = state.decks.plan.copy()
    verdict = compute_victory(state)
    result = apply_action(state, {"type": "end_campaign", "interactive_wastage": interactive})
    assert state.meta.phase == "ended" and state.pending is None
    assert state.calendar.current_box == (16 if off_calendar else 4)
    assert result["victory"] == verdict
    assert {lid: lord.model_dump() for lid, lord in state.lords.items()} == mats
    assert state.locales["leon"].siege_yellow == 4
    assert state.decks.plan == plans


@pytest.mark.parametrize("interactive", [False, True])
def test_final_wastage_cannot_reverse_the_points_winner(interactive):
    state = position("scenario_a_toledo_beset", box=2)
    lord = state.lords["al_mutamid"]
    lord.forces = {"men_at_arms": 2}
    lord.assets = {"prov": 2}
    attach(state, lord.id, "M15", lord.forces.copy())
    state.taifas["sevilla"].status = "independent"
    verdict = compute_victory(state)
    assert verdict["winner"] == "muslim"
    result = apply_action(state, {"type": "end_campaign", "interactive_wastage": interactive})
    assert result["victory"] == verdict and state.pending is None
    assert lord.cylinder.kind == "locale" and "M15" in lord.capabilities
    assert state.taifas["sevilla"].status == "independent"


@pytest.mark.parametrize("asset", ["cart", "mule"])
@pytest.mark.parametrize("count", [2, 4, 7])
@pytest.mark.parametrize("interactive", [False, True])
def test_harvest_changes_wastage_eligibility_before_selection(asset, count, interactive):
    state = position()
    lord = state.lords["alfonso"]
    lord.assets = {asset: count}
    result = apply_action(state, {"type": "end_campaign", "interactive_wastage": interactive})
    harvested = math.ceil(count / 2)
    if interactive and harvested > 1:
        assert state.calendar.current_box == 4 and lord.assets[asset] == harvested
        assert state.pending.payload["eligible"][0]["options"] == [{"asset": asset}]
        state = GameState.model_validate_json(state.model_dump_json())
        result = apply_action(state, {"type": "wastage_choice", "side": "christian"})["advance"]
    assert state.lords[lord.id].assets.get(asset, 0) == harvested - int(harvested > 1)
    assert state.calendar.current_box == 5
    assert tuple(result["grow_harvest_repairs"]["harvest"][0][asset]) == (count, harvested)


def test_grow_repairs_and_reset_survive_two_wastage_sides_and_reload_once():
    state = position(box=2)
    greens = sorted(state.locales)[:4]
    for locale in greens:
        state.locales[locale].ravaged = "green"
    state.locales["leon"].siege_yellow = 4
    for lid in ("alfonso", "al_mutamid"):
        state.lords[lid].assets = {"coin": 3}
    state.lords["alfonso"].is_lieutenant = True
    state.lords["al_mutamid"].lieutenant_of = "alfonso"
    result = apply_action(
        state,
        {
            "type": "end_campaign",
            "interactive_wastage": True,
            "grow_choices": {"green": greens[-2:]},
        },
    )
    assert result["grow_harvest_repairs"]["grow"]["christian_removed_green"] == greens[-2:]
    assert state.locales["leon"].siege_yellow == 3
    assert state.lords["al_mutamid"].lieutenant_of == "alfonso"
    saved = state.model_dump_json()
    with pytest.raises(IllegalAction, match="pending decision"):
        apply_action(state, {"type": "end_campaign"})
    assert state.model_dump_json() == saved
    with pytest.raises(IllegalAction):
        apply_action(
            state,
            {
                "type": "wastage_choice",
                "side": "christian",
                "discards": {"alfonso": {"asset": "loot"}},
            },
        )
    assert state.model_dump_json() == saved
    apply_action(state, {"type": "wastage_choice", "side": "christian"})
    state = GameState.model_validate_json(state.model_dump_json())
    assert state.pending.waiting_on == "muslim"
    result = apply_action(state, {"type": "wastage_choice", "side": "muslim"})["advance"]
    assert state.calendar.current_box == 3
    assert [loc for loc in greens if state.locales[loc].ravaged == "green"] == greens[:2]
    assert state.locales["leon"].siege_yellow == 3
    assert result["grow_harvest_repairs"]["grow"]["christian_removed_green"] == greens[-2:]
    assert not state.lords["alfonso"].is_lieutenant
    assert state.lords["al_mutamid"].lieutenant_of is None
    assert all(state.lords[lid].assets["coin"] == 2 for lid in ("alfonso", "al_mutamid"))
