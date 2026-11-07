"""A3-01. Losing players elect their own Lords' fates after combat."""

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder, GameState
from tests.test_audit_combat_regressions import _combat_state
from tests.test_concede_field_battle import _sally_setup
from tests.combat_choices import apply_combat_choices


def fate_moves(state, lord_id=None):
    return [
        m for m in legal_moves(state)
        if m["type"] == "battle_fate" and (lord_id is None or m["lord_id"] == lord_id)
    ]


def start_leon_battle(interactive=False):
    state = _combat_state(
        {"alfonso": {"men_at_arms": 4}, "al_mutamid": {"men_at_arms": 4}}, locale="leon",
    )
    battle = next(m for m in legal_moves(state) if m["type"] == "cmd_battle")
    if interactive:
        apply_combat_choices(state, {**battle, "interactive_concede": True})
        result = apply_action(state, {
            "type": "battle_concede", "side": "christian", "attacker_concede": True,
        })
    else:
        result = apply_combat_choices(state, {**battle, "attacker_concede_round": 1})
    assert result["winner"] == "muslim"
    assert result["pending"] == "battle_fate"
    return state


@pytest.mark.parametrize("interactive", [False, True])
def test_losing_owner_can_choose_a_later_retreat_route_from_leon(interactive):
    state = start_leon_battle(interactive)
    assert state.pending.waiting_on == state.meta.active_player == "christian"
    assert state.lords["alfonso"].cylinder.locale_id == "leon"
    assert not state.lords["alfonso"].in_stronghold
    moves = fate_moves(state, "alfonso")
    assert {m["fate"] for m in moves} == {"withdraw", "retreat", "removed"}
    assert {m["retreat_to"] for m in moves if m["fate"] == "retreat"} == {
        "astorga", "zamora", "sahagun",
    }
    chosen = next(m for m in moves if m.get("retreat_to") == "sahagun")
    saved = state.model_dump_json()
    for invalid, code in (
        ({**chosen, "side": "muslim"}, "not_responder"),
        ({**chosen, "retreat_way": "pass"}, "bad_arg"),
        ({**chosen, "lord_id": "al_mutamid"}, "bad_arg"),
        ({"type": "end_card", "side": "christian"}, "pending_decision"),
    ):
        with pytest.raises(IllegalAction) as error:
            apply_action(state, invalid)
        assert error.value.code == code
        assert state.model_dump_json() == saved

    result = apply_action(state, chosen)
    entry = result["retreat_summary"]["losers"][0]
    assert entry["retreat_to"] == state.lords["alfonso"].cylinder.locale_id == "sahagun"
    assert entry["service_shift_boxes"] in (1, 2, 3)
    assert not state.lords["alfonso"].in_stronghold


def test_owner_can_assign_last_stronghold_slot_and_resume_saved_decisions():
    state = _combat_state({
        "alfonso": {"men_at_arms": 4}, "alvar_fanez": {"men_at_arms": 4},
        "al_mutamid": {"men_at_arms": 4},
    }, locale="zamora")
    apply_combat_choices(state, {"type": "cmd_battle", "side": "christian",
                         "attacker_concede_round": 1, "interactive_retreat": True})
    first = next(m for m in fate_moves(state, "alvar_fanez") if m["fate"] == "withdraw")
    rng = state.meta.rng_state
    apply_action(state, first)
    assert state.meta.rng_state == rng
    assert not state.lords["alvar_fanez"].in_stronghold
    state = GameState.model_validate_json(state.model_dump_json())
    assert state.pending.payload["withdraw_slots"] == 0
    assert not fate_moves(state, "alvar_fanez")
    moves = fate_moves(state, "alfonso")
    assert moves and all(m["fate"] != "withdraw" for m in moves)
    stale = {**first, "lord_id": "alfonso"}
    saved = state.model_dump_json()
    with pytest.raises(IllegalAction, match="illegal fate"):
        apply_action(state, stale)
    assert state.model_dump_json() == saved
    result = apply_action(state, next(m for m in moves if m.get("retreat_to") == "astorga"))
    assert result["fates"]["alvar_fanez"] == {"fate": "withdraw"}
    assert state.lords["alvar_fanez"].in_stronghold
    assert state.lords["alfonso"].cylinder.locale_id == "astorga"


def test_losing_owner_can_remove_a_lord_with_legal_retreats():
    state = start_leon_battle()
    state.lords["alfonso"].assets = {"loot": 2}
    result = apply_action(state, next(m for m in fate_moves(state) if m["fate"] == "removed"))
    assert result["retreat_summary"]["losers"][0]["spoils_lost"] == {"loot": 2}
    assert state.lords["alfonso"].cylinder.kind == "removed"
    assert state.lords["al_mutamid"].assets["loot"] == 2


def test_approach_defenders_cannot_retreat_along_the_approach_way():
    state = _combat_state(
        {"alfonso": {"men_at_arms": 4}, "al_mutamid": {"men_at_arms": 4}},
        side="muslim", active="al_mutamid", locale="leon",
    )
    state.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="zamora")
    state.lords["al_mutamid"].assets = {}
    apply_action(state, {"type": "cmd_march", "side": "muslim", "target_locale_id": "leon",
                         "way_type": "road"})
    stand = next(m for m in legal_moves(state) if m["type"] == "respond_stand_battle")
    apply_combat_choices(state, {**stand, "defender_concede_round": 1})
    moves = fate_moves(state, "alfonso")
    assert {m["retreat_to"] for m in moves if m["fate"] == "retreat"} == {"astorga", "sahagun"}
    saved = state.model_dump_json()
    chosen = next(m for m in moves if m.get("retreat_to") == "sahagun")
    with pytest.raises(IllegalAction, match="illegal fate"):
        apply_action(state, {**chosen, "retreat_to": "zamora"})
    assert state.model_dump_json() == saved
    apply_action(state, chosen)
    assert state.lords["alfonso"].cylinder.locale_id == "sahagun"


@pytest.mark.parametrize("interactive", [False, True])
def test_relief_sally_reserves_withdrawal_for_the_sallying_lord(interactive):
    state = _combat_state({
        "alfonso": {"men_at_arms": 4}, "alvar_fanez": {"men_at_arms": 4},
        "al_mutamid": {"men_at_arms": 4},
    }, locale="zamora", inside=("alvar_fanez",))
    state.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    state.lords["alfonso"].assets = {}
    state.locales["zamora"].siege_green = 3
    apply_action(state, {"type": "cmd_march", "side": "christian", "target_locale_id": "zamora",
                         "way_type": "road"})
    stand = next(m for m in legal_moves(state) if m["type"] == "respond_stand_battle")
    if interactive:
        apply_combat_choices(state, {**stand, "interactive_concede": True},
                             sallyers=("alvar_fanez",))
        result = apply_action(state, {
            "type": "relief_concede", "side": "christian", "attacker_concede": True,
        })
    else:
        result = apply_combat_choices(state, {**stand, "attacker_concede_round": 1},
                                      sallyers=("alvar_fanez",))
    assert result["pending"] == "battle_fate"
    moves = fate_moves(state)
    assert {m["lord_id"] for m in moves} == {"alfonso"}
    assert {m["fate"] for m in moves} == {"retreat", "removed"}
    retreat = next(m for m in moves if m["fate"] == "retreat")
    assert retreat["retreat_to"] == "leon"
    result = apply_action(state, retreat)
    by_lord = {e["lord_id"]: e for e in result["retreat_summary"]["losers"]}
    assert by_lord["alvar_fanez"]["fate"] == "withdraw"
    assert "service_roll" not in by_lord["alvar_fanez"]
    assert state.lords["alvar_fanez"].in_stronghold
    assert state.lords["alvar_fanez"].cylinder.locale_id == "zamora"
    assert state.locales["zamora"].siege_green == 1


def test_losing_sally_besieger_owns_the_retreat_prompt():
    state = _sally_setup()
    sally = next(m for m in legal_moves(state) if m["type"] == "cmd_sally")
    result = apply_combat_choices(state, {**sally, "defender_concede_round": 1})
    assert result["pending"] == "battle_fate"
    assert state.meta.active_player == "christian"
    retreat = next(m for m in fate_moves(state, "alvar_fanez") if m["fate"] == "retreat")
    apply_action(state, retreat)
    assert state.lords["alvar_fanez"].cylinder.locale_id == retreat["retreat_to"]
    assert state.locales["sevilla"].siege_yellow == 0
