"""Resource elections during ordinary and interactive Feed (4.8.1)."""

import pytest

from almoravid.actions import IllegalAction
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import GameState
from tests.test_interactive_economy import _reveal_alfonso_card, apply_action

END = {"type": "end_card", "side": "christian"}
FEED = {"type": "feed_resource_choice", "side": "christian"}


def _march_with_mixed_food():
    state = load_scenario("scenario_a_toledo_beset", seed=14)
    _reveal_alfonso_card(state)
    state.lords["alfonso"].assets.update(prov=1, loot=1)
    apply_action(state, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "road"})
    return state


@pytest.mark.parametrize("spend_loot", [False, True])
def test_end_card_can_spend_loot_or_keep_it(spend_loot):
    state = _march_with_mixed_food()
    move = {**END, "feed_loot": {"alfonso": 1}} if spend_loot else END
    assert move in legal_moves(state)
    fed = apply_action(state, move)["feed"]["fed"][0]
    assert fed["use_loot"] == int(spend_loot)
    assert fed["use_prov"] == int(not spend_loot)
    assets = state.lords["alfonso"].assets
    assert (assets["prov"], assets["loot"]) == (int(spend_loot), int(not spend_loot))


def test_feed_owners_can_choose_after_reload_before_pay():
    state = _march_with_mixed_food()
    muslim = state.lords["al_mutamid"]
    muslim.moved_fought = True
    muslim.assets.update(prov=1, loot=1)
    interactive = {**END, "interactive_economy": True}
    assert interactive in legal_moves(state)
    apply_action(state, interactive)
    saved = state.model_dump_json()
    state = GameState.model_validate_json(saved)
    assert state.pending.kind == "feed_resource_choice"
    assert state.pending.waiting_on == "christian"
    for invalid in ({**FEED, "feed_loot": {"al_mutamid": 1}},
                    {**FEED, "feed_loot": {"alfonso": 2}},
                    {"type": "pay_before_disband", "side": "christian", "done": True}):
        with pytest.raises(IllegalAction):
            apply_action(state, invalid)
        assert state.model_dump_json() == saved
    christian = {**FEED, "feed_loot": {"alfonso": 1}}
    assert christian in legal_moves(state)
    apply_action(state, christian)
    assert state.pending.waiting_on == "muslim"
    assert state.lords["alfonso"].assets["loot"] == 1
    state = GameState.model_validate_json(state.model_dump_json())
    apply_action(state, {**FEED, "side": "muslim"})
    assert state.pending.kind == "pay_before_disband"
    assert state.lords["alfonso"].assets["prov"] == 1
    assert state.lords["alfonso"].assets["loot"] == 0
    assert state.lords["al_mutamid"].assets["prov"] == 0
    assert state.lords["al_mutamid"].assets["loot"] == 1
    for side in ("christian", "muslim"):
        apply_action(state, {"type": "pay_before_disband", "side": side, "done": True})
    assert state.pending is None


def test_sharing_can_spend_a_mix_from_the_donor():
    state = _march_with_mixed_food()
    alfonso = state.lords["alfonso"]
    alfonso.assets.update(prov=0, loot=0, mule=4)  # two food needed
    donor = state.lords["alvar_fanez"]
    donor.cylinder = alfonso.cylinder.model_copy()
    donor.assets.update(prov=2, loot=2)
    move = {**END, "feed_loot": {"alvar_fanez": 1}}
    assert move in legal_moves(state)
    assert apply_action(state, move)["feed"]["shared"] == [
        {"to": "alfonso", "from": "alvar_fanez", "asset": asset, "amount": 1}
        for asset in ("prov", "loot")
    ]
    assert (donor.assets["prov"], donor.assets["loot"]) == (1, 1)
