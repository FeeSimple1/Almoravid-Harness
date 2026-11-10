"""A6-02. Relief Sally applies each Lord's round-specific Strikes."""

import pytest

from almoravid import battle
from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import GameState
from tests.combat_choices import apply_combat_choices
from tests.test_cross_game_avoid_retreat_surrender import place, position, reject_unchanged
from tests.test_cross_game_reaction_privacy import hold

STAND = {"type": "respond_stand_battle", "side": "muslim"}
SALLY = {"type": "relief_sally", "side": "christian", "lord_ids": ["alvar_fanez"]}


def _setup(forces, *, marchers=("alfonso",), sallyers=("alvar_fanez",)):
    state = position(seed=7)
    for lid, units in forces.items():
        place(state, lid, "leon" if lid in marchers else "zamora")
        state.lords[lid].forces = units
        state.lords[lid].in_stronghold = lid in sallyers
    state.locales["zamora"].siege_green = 3
    return state


def _march(state, *followers):
    apply_action(state, {"type": "cmd_march", "side": "christian", "target_locale_id": "zamora",
                         "way_type": "road", "group_lord_ids": list(followers)})


def _round(state, **defender_choice):
    apply_action(state, {"type": "relief_concede", "side": "christian"})
    return apply_action(state, {"type": "relief_concede", "side": "muslim", **defender_choice})


@pytest.fixture
def relief_rounds(monkeypatch):
    rounds = []
    resolve = battle._relief_run_round

    def record_round(state, rs, index):
        result = resolve(state, rs, index)
        rounds.append(result)
        return result

    monkeypatch.setattr(battle, "_relief_run_round", record_round)
    return rounds


def _raw_hits(round_result, step_id):
    return [step.raw_hits for step in round_result.steps if step.step == step_id]


@pytest.mark.parametrize("holder", ["alfonso", "alvar_fanez"])
def test_jabalinas_fires_in_both_relief_lanes(holder, relief_rounds):
    forces = {"alfonso": {"men_at_arms": 2}, "alvar_fanez": {"men_at_arms": 2},
              "al_mutamid": {"men_at_arms": 2, "sergeants": 2, "militia": 2}}
    forces[holder] = {"militia": 1, "serfs": 1, "men_at_arms": 2, "knights": 2}
    state = _setup(forces)
    state.lords[holder].capabilities = ["C7"]
    _march(state)
    apply_combat_choices(state, {**STAND, "interactive_concede": True}, sallyers=SALLY["lord_ids"])
    saved = state.model_dump(mode="json")
    del saved["pending"]["payload"]["rs"]["javelin_rounds"]
    state = GameState.model_validate(saved)
    _round(state)
    expected = [2.0, 0.0] if holder == "alfonso" else [0.0, 2.0]
    assert _raw_hits(relief_rounds[0], "1.b") == expected


def test_each_lord_can_fire_javelins_in_a_different_round_after_reload(relief_rounds):
    state = _setup({"alfonso": {"militia": 1, "men_at_arms": 4},
                    "garcia_ordonez": {"men_at_arms": 4}, "alvar_fanez": {"men_at_arms": 4},
                    "al_mutamid": {"african_horse": 1, "men_at_arms": 3},
                    "al_mundir": {"african_horse": 2, "men_at_arms": 3}},
                   marchers=("alfonso", "garcia_ordonez"))
    state.lords["alfonso"].capabilities = ["C7"]
    state.meta.absorption_policy = {"muslim": "armored_first", "christian": "armored_first"}
    _march(state, "garcia_ordonez")
    stand = next(move for move in legal_moves(state)
                 if move["type"] == "respond_stand_battle" and move.get("interactive_timing"))
    apply_action(state, stand)
    assert apply_action(state, SALLY)["javelin_lords"] == ["alfonso"]
    timing = {"type": "oneround_timing", "side": "christian", "javelin_rounds": {"alfonso": 2}}
    assert timing in legal_moves(state)
    reject_unchanged(state, {**timing, "side": "muslim"}, "not_responder")
    reject_unchanged(state, {**timing, "javelin_rounds": {"al_mundir": 2}}, "bad_arg")
    reject_unchanged(state, {**timing, "javelin_rounds": {"alfonso": True}}, "bad_arg")
    state = GameState.model_validate_json(state.model_dump_json())
    advance = apply_action(state, timing)["advance"]
    assert set(advance["javelin_lords"]) == {"al_mutamid", "al_mundir"}
    apply_action(state, {"type": "oneround_timing", "side": "muslim",
                         "javelin_rounds": {"al_mutamid": 1, "al_mundir": 2}})

    for index in (1, 2, 3):
        state = GameState.model_validate_json(state.model_dump_json())
        assert state.pending.payload["round_idx"] == index
        _round(state)

    assert [_raw_hits(result, "1.a") for result in relief_rounds] == [[1.0], [2.0], [0.0]]
    assert [_raw_hits(result, "1.b") for result in relief_rounds] == [
        [0.0, 0.0], [1.0, 0.0], [0.0, 0.0],
    ]


@pytest.mark.parametrize(("holder", "horse_hits"), [
    ("alfonso", [11.0, 9.0]), ("alvar_fanez", [7.0, 11.0]),
])
@pytest.mark.parametrize("interactive", [False, True])
def test_cantador_has_one_holder_and_a_four_unit_cap(
        holder, horse_hits, interactive, relief_rounds):
    sallyers = ("alvar_fanez", "pedro_ansurez")
    state = _setup({"alfonso": {"knights": 2, "sergeants": 3},
                    "alvar_fanez": {"knights": 1, "sergeants": 1},
                    "pedro_ansurez": {"knights": 2, "sergeants": 2},
                    "al_mutamid": {"men_at_arms": 8}, "al_mundir": {"men_at_arms": 8}},
                   sallyers=sallyers)
    hold(state, "christian", "C8")
    _march(state)
    stand = {**STAND, "interactive_concede": True} if interactive else {
        **STAND, "defender_concede_round": 2,
    }
    apply_action(state, stand)
    apply_action(state, {**SALLY, "lord_ids": list(sallyers)})
    play = {"type": "combat_holds", "side": "christian", "card_id": "C8", "lord_id": holder}
    assert play in legal_moves(state)
    reject_unchanged(state, {**play, "lord_id": "al_mutamid"}, "bad_arg")
    apply_action(state, play)
    state = GameState.model_validate_json(state.model_dump_json())
    apply_action(state, {"type": "combat_holds", "side": "christian"})
    result = apply_action(state, {"type": "combat_holds", "side": "muslim"})
    if interactive:
        _round(state)
        assert state.decks.discard.count("C8") == 1
        result = _round(state, defender_concede=True)

    assert result["rounds"] == 2
    assert _raw_hits(relief_rounds[0], "2.b") == horse_hits
    assert state.decks.discard.count("C8") == 1
    assert state.meta.cantador_lord_id is None
