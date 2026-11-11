"""A6-03. Arrada follows its living holder in a Sally or Storm."""

import pytest

from almoravid import battle
from almoravid.actions import apply_action
from almoravid.state import GameState
from tests.combat_choices import apply_combat_choices
from tests.test_cross_game_avoid_retreat_surrender import place, position


@pytest.fixture
def missile_steps(monkeypatch):
    steps = []
    resolve = battle._resolve_step

    def record_step(*args, **kwargs):
        step = resolve(*args, **kwargs)
        if step.step in ("1.a", "1.b"):
            steps.append(step)
        return step

    monkeypatch.setattr(battle, "_resolve_step", record_step)
    return steps


def _concede(state, attacker, defender, *, role="defender"):
    action = {"type": state.pending.kind, "side": attacker}
    if role == "attacker":
        return apply_action(state, {**action, "attacker_concede": True})
    apply_action(state, action)
    return apply_action(state, {**action, "side": defender, "defender_concede": True})


@pytest.mark.parametrize(("interactive", "array", "conceder"), [
    (False, False, "defender"), (True, False, "attacker"),
    (False, True, "attacker"), (True, True, "defender"),
])
def test_ordinary_sally_applies_arrada_to_the_holders_target(
        interactive, array, conceder, missile_steps):
    state = position(seed=7)
    for lid in ("alfonso", "al_mutamid"):
        place(state, lid, "zaragoza")
    state.lords["alfonso"].forces = {"knights": 4}
    state.lords["al_mutamid"].in_stronghold = True
    state.lords["al_mutamid"].capabilities = ["M17"]
    state.taifas["zaragoza"].status = "independent"
    state.locales["zaragoza"].siege_yellow = 1
    state.meta.active_player = "muslim"
    state.meta.active_lord_id = "al_mutamid"
    if array:
        # The card is on the left Lord, who faces Álvar's Knights.
        place(state, "al_mundir", "zaragoza")
        place(state, "alvar_fanez", "zaragoza")
        state.lords["al_mundir"].in_stronghold = True
        state.lords["alfonso"].forces = {"men_at_arms": 4}
        state.lords["alvar_fanez"].forces = {"knights": 4}
        state.meta.active_lord_id = "al_mundir"

    action = {"type": "cmd_sally", "side": "muslim", "interactive_concede": interactive}
    if interactive:
        apply_action(state, action)
        state = GameState.model_validate_json(state.model_dump_json())
        result = _concede(state, "muslim", "christian", role=conceder)
    else:
        result = apply_action(state, {**action, f"{conceder}_concede_round": 1})

    assert result["rounds"] == 1
    assert [(step.step, step.rounded_hits) for step in missile_steps] == [
        ("1.a", 0), ("1.b", 2 if conceder == "attacker" else 3),
    ]
    # Seed 7 cancels one Hit with Siegeworks. Knights then fail one
    # Armor roll under Arrada's reduced 1–2 range.
    assert missile_steps[-1].losses == {"knights": 1}


@pytest.mark.parametrize("holder", ["sallyer", "marcher", "routed_sallyer"])
def test_relief_arrada_requires_an_unrouted_sallyer(holder, missile_steps):
    state = position(seed=1 if holder == "routed_sallyer" else 7)
    place(state, "al_mundir", "tudela")
    place(state, "alfonso", "zaragoza")
    for lid in ("al_mutamid", "al_mustain"):
        place(state, lid, "zaragoza")
        state.lords[lid].in_stronghold = True
    state.meta.active_player, state.meta.active_lord_id = "muslim", "al_mundir"
    state.taifas["zaragoza"].status = "independent"
    state.locales["zaragoza"].siege_yellow = 1
    state.lords["al_mundir" if holder == "marcher" else "al_mutamid"].capabilities = ["M17"]
    if holder == "routed_sallyer":
        # The owner sends the Rearguard's Missiles to the flanking holder,
        # who Routs before the Sallyers fire.
        place(state, "alvar_fanez", "zaragoza")
        state.lords["alvar_fanez"].forces = {"men_at_arms": 2}
        state.lords["alvar_fanez"].capabilities = ["C2"]
        state.lords["al_mutamid"].forces = {"militia": 1}
        apply_action(state, {"type": "set_array_tactics", "side": "muslim",
                             "flank_absorb": "flanking"})

    apply_action(state, {"type": "cmd_march", "side": "muslim",
                         "target_locale_id": "zaragoza", "way_type": "road"})
    apply_combat_choices(state, {"type": "respond_stand_battle", "side": "christian",
                                 "interactive_concede": True},
                         sallyers=["al_mutamid", "al_mustain"])
    _concede(state, "muslim", "christian")

    if holder == "routed_sallyer":
        assert any(step.step == "1.a" and step.losses == {"militia": 1}
                   for step in missile_steps)
    # Marchers strike first, then the Sallyers. The second Sallyer keeps
    # the lane live in the Rout case.
    assert [step.rounded_hits for step in missile_steps if step.step == "1.b"] == [
        0, 3 if holder == "sallyer" else 0,
    ]


def test_relief_besieger_does_not_fire_arrada(missile_steps):
    state = position(seed=7)
    place(state, "alfonso", "leon")
    place(state, "alvar_fanez", "zamora")
    place(state, "al_mutamid", "zamora")
    state.lords["alvar_fanez"].in_stronghold = True
    state.lords["al_mutamid"].capabilities = ["M17"]
    state.locales["zamora"].siege_green = 1
    apply_action(state, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "zamora", "way_type": "road"})
    apply_combat_choices(state, {"type": "respond_stand_battle", "side": "muslim",
                                 "defender_concede_round": 1}, sallyers=["alvar_fanez"])
    assert [step.rounded_hits for step in missile_steps if step.step == "1.a"] == [0]


def test_arrada_fires_from_defending_reserve_during_christian_storm(missile_steps):
    state = position(seed=7)
    for lid in ("alfonso", "al_mustain", "al_mutamid"):
        place(state, lid, "zaragoza")
        state.lords[lid].in_stronghold = lid != "alfonso"
    state.taifas["zaragoza"].status = "independent"
    state.locales["zaragoza"].siege_yellow = 1
    state.lords["al_mutamid"].capabilities = ["M17"]
    apply_action(state, {"type": "cmd_storm", "side": "christian"})
    apply_action(state, {"type": "storm_front", "side": "muslim", "lord_id": "al_mustain"})
    # Al-Mustain starts in Front. Arrada adds to the Garrison's three Hits.
    assert missile_steps[0].step == "1.a"
    assert missile_steps[0].rounded_hits == 6


def test_arrada_stops_after_its_storm_holder_routs(missile_steps):
    state = position(seed=7)
    for lid in ("al_mutamid", "al_mundir"):
        place(state, lid, "zamora")
    state.lords["al_mutamid"].forces = {"militia": 1}
    state.lords["al_mutamid"].capabilities = ["M17"]
    state.meta.active_player, state.meta.active_lord_id = "muslim", "al_mutamid"
    state.locales["zamora"].siege_green = 2

    apply_action(state, {"type": "cmd_storm", "side": "muslim", "interactive_concede": True})
    state = GameState.model_validate_json(state.model_dump_json())
    assert state.pending.kind == "storm_concede"
    assert state.pending.payload["ss"]["a_lord_routed"]["al_mutamid"] == {"militia": 1}
    apply_action(state, {"type": "storm_concede", "side": "muslim"})
    assert [step.rounded_hits for step in missile_steps if step.step == "1.b"] == [3, 0]
