"""Round 8 public combat choices and remaining Hits after Rout."""

import pytest

from almoravid import battle
from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, GameState
from almoravid.static_data import load_lords
from almoravid.views import redacted_view
from tests.combat_choices import apply_combat_choices
from tests.test_array_residuals import _two_lord_battle
from tests.test_cross_game_reaction_privacy import hold
from tests.test_round7_storm import _storm_position


def _finish_holds(state):
    while state.pending is not None and state.pending.kind == "combat_holds":
        apply_action(state, {"type": "combat_holds", "side": state.pending.waiting_on})


@pytest.mark.parametrize("front", ["al_mustain", "al_mutamid"])
@pytest.mark.parametrize("interactive", [False, True])
def test_defender_selects_storm_front_before_dice_and_after_reload(front, interactive, monkeypatch):
    state = _storm_position(1, "zaragoza", 2, "alfonso")
    state.lords["al_mustain"].forces = {"militia": 1}
    state.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    state.lords["al_mutamid"].in_stronghold = True
    state.meta.hidden_mats = True
    hold(state, "christian", "C8")
    # The explicit choice also works when storage order puts the other Lord first.
    if front == "al_mustain":
        state.lords = dict(reversed(state.lords.items()))
    before_roll = state.meta.rng_state
    actions_remaining = state.meta.actions_remaining
    apply_action(state, {"type": "cmd_storm", "side": "christian",
                         "interactive_concede": interactive})
    _finish_holds(state)
    assert state.pending.kind == "storm_front" and state.meta.active_player == "muslim"
    assert state.meta.rng_state == before_roll
    assert state.meta.actions_remaining == actions_remaining
    assert state.decks.held["christian"] == ["C8"]
    assert {move["lord_id"] for move in legal_moves(state)} == {"al_mustain", "al_mutamid"}
    for viewer in ("christian", "muslim"):
        view = redacted_view(state, viewer)
        assert "_storm_front_resume" not in view["pending"]["payload"]
        assert not any(view["lords"][lid].get("hidden_mat")
                       for lid in ("alfonso", "al_mustain", "al_mutamid"))
    assert redacted_view(state, "muslim")["lords"]["alvar_fanez"]["hidden_mat"]

    state = GameState.model_validate_json(state.model_dump_json())
    replay = GameState.model_validate_json(state.model_dump_json())
    observed = []
    original = battle._storm_run_round

    def observe(current, attacker, defender, context, number):
        initial_front = list(context["d_front"])
        result = original(current, attacker, defender, context, number)
        observed.append((initial_front, next(step.rounded_hits for step in result.steps
                                            if step.step == "2.a")))
        return result

    monkeypatch.setattr(battle, "_storm_run_round", observe)
    choice = next(move for move in legal_moves(state) if move["lord_id"] == front)
    assert apply_action(state, choice) == apply_action(replay, choice)
    assert state.model_dump_json() == replay.model_dump_json()
    assert observed[0] == ([front], 5 if front == "al_mustain" else 6)


def test_storm_front_rejects_wrong_owners_targets_and_unrelated_actions_atomically():
    state = _storm_position(1, "zaragoza", 1, "alfonso")
    state.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    state.lords["al_mutamid"].in_stronghold = True
    apply_action(state, {"type": "cmd_storm", "side": "christian"})
    _finish_holds(state)
    before = state.model_dump_json()
    for action in (
        {"type": "storm_front", "side": "christian", "lord_id": "al_mustain"},
        {"type": "storm_front", "side": "muslim", "lord_id": "alfonso"},
        {"type": "storm_front", "side": "muslim", "lord_id": "yusuf"},
        {"type": "cmd_pass", "side": "christian"},
    ):
        with pytest.raises(IllegalAction):
            apply_action(state, action)
        assert state.model_dump_json() == before


@pytest.mark.parametrize("kind", ["cmd_battle", "cmd_sally", "cmd_storm"])
@pytest.mark.parametrize("holder", ["alfonso", "alvar_fanez"])
def test_cantador_holder_choice_is_offered_and_saved_for_each_combat(kind, holder):
    state = _storm_position(1, "zaragoza", 1, "alfonso", "alvar_fanez")
    if kind == "cmd_battle":
        state.lords["al_mustain"].in_stronghold = False
    elif kind == "cmd_sally":
        for lord_id in ("alfonso", "alvar_fanez", "al_mustain"):
            state.lords[lord_id].cylinder = Cylinder(kind="locale", locale_id="zamora")
            state.lords[lord_id].in_stronghold = lord_id != "al_mustain"
        state.locales["zaragoza"].siege_yellow = 0
        state.locales["zamora"].siege_green = 1
    hold(state, "christian", "C8")
    apply_action(state, {"type": kind, "side": "christian", "interactive_concede": True})
    choices = [move for move in legal_moves(state) if move.get("card_id") == "C8"]
    assert {move["lord_id"] for move in choices} == {"alfonso", "alvar_fanez"}
    choice = next(move for move in choices if move["lord_id"] == holder)
    before = state.model_dump_json()
    for bad in ("al_mustain", "pedro_ansurez"):
        with pytest.raises(IllegalAction):
            apply_action(state, {**choice, "lord_id": bad})
        assert state.model_dump_json() == before
    apply_action(state, choice)
    state = GameState.model_validate_json(state.model_dump_json())
    assert state.meta.cantador_lord_id == holder
    assert "C8" in state.decks.this_levy_events["christian"]
    _finish_holds(state)
    if kind != "cmd_storm":
        assert state.meta.cantador_lord_id == holder
        assert state.pending.kind == "battle_concede"


def test_defending_christians_choose_their_cantador_holder():
    state = _storm_position(1, "zaragoza", 1, "alfonso", "alvar_fanez")
    state.lords["al_mustain"].in_stronghold = False
    state.meta.active_player = "muslim"
    state.meta.active_lord_id = "al_mustain"
    hold(state, "christian", "C8")
    apply_action(state, {"type": "cmd_battle", "side": "muslim", "interactive_concede": True})
    apply_action(state, {"type": "combat_holds", "side": "muslim"})
    choices = [move for move in legal_moves(state) if move.get("card_id") == "C8"]
    assert {move["lord_id"] for move in choices} == {"alfonso", "alvar_fanez"}
    choice = next(move for move in choices if move["lord_id"] == "alvar_fanez")
    before = state.model_dump_json()
    with pytest.raises(IllegalAction):
        apply_action(state, {**choice, "side": "muslim"})
    assert state.model_dump_json() == before
    apply_action(state, choice)
    _finish_holds(state)
    assert state.pending.kind == "battle_concede"
    assert state.meta.cantador_lord_id == "alvar_fanez"


@pytest.mark.parametrize(("holder", "expected"), [("alfonso", 3), ("alvar_fanez", 3),
                                                     ("pedro_ansurez", 2)])
def test_storm_cantador_bonus_belongs_to_its_selected_front_lord(holder, expected):
    state = load_scenario("scenario_a_toledo_beset", seed=1)
    state.decks.this_levy_events["christian"] = ["C8"]
    state.meta.cantador_lord_id = holder
    assert battle._storm_melee_hits(
        state, {}, {"alfonso": {"knights": 1}, "alvar_fanez": {"sergeants": 1}}, [],
        side_is_christian=True, round_idx=1,
    ) == expected


@pytest.mark.parametrize(("step_type", "unit_class", "seed", "forces", "caps"), [
    ("melee", "horse", 1, {"knights": 1}, []),
    ("missile", None, 10, {"men_at_arms": 3}, ["C2"]),
])
def test_remaining_hits_retarget_and_keep_their_crossbow_penalty(
    step_type, unit_class, seed, forces, caps,
):
    state, attacker, defender, _, _ = _two_lord_battle(seed)
    attacker.array[0].forces = forces
    attacker.array[0].capabilities_in_play = caps
    center, flank = defender.array
    center.forces = {"serfs": 1}
    flank.forces = {"knights": 1}
    result = battle._resolve_step_per_pair(
        state, "2.b" if step_type == "melee" else "1.b", "attacker", step_type, unit_class,
        attacker, defender, round_index=1,
    )
    assert result.rounded_hits == 2
    assert result.losses == {"serfs": 1, "knights": 1}
    assert not center.forces and not flank.forces


def test_remaining_hits_ignore_reserve_when_the_front_row_routs():
    state, attacker, defender, _, _ = _two_lord_battle()
    center, reserve = defender.array
    center.forces = {"serfs": 1}
    reserve.position = "reserve"
    result = battle._resolve_step_per_pair(
        state, "2.b", "attacker", "melee", "horse", attacker, defender, round_index=1,
    )
    assert result.losses == {"serfs": 1}
    assert reserve.forces == {"sergeants": 3}


def test_public_battle_carries_hits_to_the_new_flank(monkeypatch):
    state = _storm_position(1, "transduero", 1, "alfonso", "alvar_fanez")
    state.locales["transduero"].siege_yellow = 0
    for lord_id in ("al_mustain", "al_mutamid"):
        state.lords[lord_id].cylinder = Cylinder(kind="locale", locale_id="transduero")
        state.lords[lord_id].in_stronghold = False
    state.lords["alvar_fanez"].forces = {"men_at_arms": 1}
    state.lords["alvar_fanez"].capabilities.remove("C2")
    state.decks.capabilities_in_play = [c for c in state.decks.capabilities_in_play if c.card_id != "C2"]
    state.decks.discard.append("C2")
    state.lords["al_mustain"].forces = {"militia": 1}
    state.lords["al_mutamid"].forces = {"men_at_arms": 1, "militia": 2}
    alfonso = state.lords["alfonso"]
    for vassal in load_lords()["lords"]["alfonso"]["vassals"]:
        marker = next(v for v in alfonso.vassals if v.name == vassal["name"])
        marker.ready = marker.pennant_down = False
        for unit, count in vassal["forces"].items():
            alfonso.forces[unit] = alfonso.forces.get(unit, 0) + count
    observed = []
    original = battle._resolve_step_per_pair

    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[1] == "2.b" and kwargs.get("round_index") == 1:
            observed.append(result)
        return result

    monkeypatch.setattr(battle, "_resolve_step_per_pair", observe)
    apply_combat_choices(state, {"type": "cmd_battle", "side": "christian",
                                  "attacker_concede_round": 2})
    assert observed[0].rounded_hits == 6
    assert observed[0].losses.get("men_at_arms", 0) + observed[0].losses.get("militia", 0) > 1
