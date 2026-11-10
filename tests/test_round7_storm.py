"""Round 7 Storm regressions through the public dispatcher."""

import pytest

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, GameState
from tests.combat_choices import apply_combat_choices


def _storm_position(seed, locale, siege_markers, *besiegers):
    state = load_scenario("scenario_a_toledo_beset", seed=seed)
    for lord_id in besiegers:
        lord = state.lords[lord_id]
        lord.cylinder = Cylinder(kind="locale", locale_id=locale)
        lord.in_stronghold = False
    for lord in state.lords.values():
        if lord.side == "muslim" and lord.cylinder.locale_id == locale:
            lord.in_stronghold = True
    state.locales["toledo"].siege_yellow = 0
    state.locales[locale].siege_yellow = siege_markers
    state.meta.phase = "campaign"
    state.meta.campaign_step = "activation"
    state.meta.active_player = "christian"
    state.meta.active_lord_id = besiegers[0]
    state.meta.actions_remaining = 3
    state.pending = None
    return state


@pytest.mark.parametrize("holder", ["alvar_fanez", None, "alfonso"])
def test_storm_ballesteros_arms_only_its_front_holder(holder):
    state = _storm_position(7, "zaragoza", 1, "alfonso", "alvar_fanez")
    if holder != "alvar_fanez":
        state.lords["alvar_fanez"].capabilities.remove("C2")
        card = next(cap for cap in state.decks.capabilities_in_play if cap.card_id == "C2")
        if holder is None:
            state.decks.capabilities_in_play.remove(card)
            state.decks.discard.append("C2")
        else:
            state.lords[holder].capabilities.append("C2")
            card.owner_lord_id = holder

    result = apply_combat_choices(state, {"type": "cmd_storm", "side": "christian"})

    assert result["rounds"] == 1
    # Garrison Crossbows hit Alfonso's Armored units before his Serf.
    # His own extra Crossbow Hit changes the later rolls and costs him
    # the remaining unit. Only Ballesteros on his mat grants that Hit.
    alfonso = state.lords["alfonso"]
    assert alfonso.forces == ({} if holder == "alfonso" else {"serfs": 1})
    assert alfonso.cylinder.kind == ("removed" if holder == "alfonso" else "locale")


@pytest.mark.parametrize("advance", [True, False])
def test_storm_routed_front_releases_capacity_after_reload(advance):
    state = _storm_position(1, "huesca", 4, "alfonso", "alvar_fanez", "pedro_ansurez")
    state.lords["alfonso"].forces = {"knights": 1}
    result = apply_combat_choices(state, {
        "type": "cmd_storm", "side": "christian", "interactive_concede": True,
        "reposition_attacker": advance,
    })
    assert result == {"storm": "awaiting_concede", "round": 2}
    assert state.pending.payload["ss"]["a_lord_forces"]["alfonso"] == {}

    step = {"type": "storm_concede", "side": "christian"}
    state = GameState.model_validate_json(state.model_dump_json())
    apply_action(state, step)
    # An empty Front requires Álvar to enter even if optional advances
    # are declined. Pedro remains in Reserve until Round 3.
    ss = state.pending.payload["ss"]
    round_two_front = list(ss["a_front"])
    assert ss["a_reserve"] == ["pedro_ansurez"]

    # Older saves can still include Alfonso in the Front after Round 2.
    ss["a_front"] = ["alfonso", "alvar_fanez"]
    state = GameState.model_validate_json(state.model_dump_json())
    ss = state.pending.payload["ss"]
    apply_action(state, step)

    assert ss["a_front"] == (["alvar_fanez", "pedro_ansurez"] if advance else ["alvar_fanez"])
    assert ss["a_reserve"] == ([] if advance else ["pedro_ansurez"])
    assert round_two_front == ["alvar_fanez"]
