"""A3-02/04. Battle Spoils are allocated by the winner after Losses."""

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder, GameState
from almoravid.views import redacted_view
from tests.test_audit_combat_regressions import _combat_state
from tests.test_concede_field_battle import _storm_setup
from tests.test_cross_game_battle_fates import fate_moves
from tests.combat_choices import apply_combat_choices


def muslim_attack(forces):
    state = _combat_state(forces, side="muslim", active="al_mutamid")
    for lord_id in forces:
        state.lords[lord_id].assets = {}
    return state


@pytest.mark.parametrize("interactive", [False, True])
def test_spoils_survive_the_removal_of_a_winning_lord(interactive):
    state = muslim_attack({
        "al_mutamid": {"militia": 1}, "al_mundir": {"men_at_arms": 4},
        "alfonso": {"men_at_arms": 4},
    })
    state.lords["alfonso"].assets = {"loot": 2}
    result = apply_combat_choices(state, {
        "type": "cmd_battle", "side": "muslim", "defender_concede_round": 1,
        "interactive_retreat": interactive,
    })
    if interactive:
        result = apply_action(state, next(m for m in fate_moves(state) if m["fate"] == "retreat"))
    assert result["winner"] == "muslim"
    assert state.lords["al_mutamid"].cylinder.kind == "removed"
    assert state.lords["al_mundir"].assets == {"loot": 2}
    assert result["spoils_awarded"] == {"al_mundir": {"loot": 2}}
    assert state.pending.kind == "severed_heads"  # Only one surviving recipient.


def test_winner_can_split_spoils_and_resume_the_command_side_after_save():
    state = _combat_state({
        "alfonso": {"men_at_arms": 4}, "al_mutamid": {"men_at_arms": 4},
        "al_mundir": {"men_at_arms": 4},
    }, locale="leon")
    state.lords["alfonso"].assets = {"loot": 4}
    for lid in ("al_mutamid", "al_mundir"):
        state.lords[lid].assets = {}
    distant = state.lords["al_mustain"]
    distant.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    battle = next(m for m in legal_moves(state) if m["type"] == "cmd_battle")
    apply_combat_choices(state, {**battle, "interactive_concede": True})
    apply_action(state, {"type": "battle_concede", "side": "christian", "attacker_concede": True})
    retreat = next(m for m in fate_moves(state) if m.get("retreat_to") == "sahagun")
    result = apply_action(state, retreat)
    assert result["pending"] == "battle_spoils"
    assert state.pending.waiting_on == state.meta.active_player == "muslim"
    assert state.pending.payload["pool"] == {"loot": 4}
    assert "_battle_spoils_resume" not in redacted_view(state, "christian")["pending"]["payload"]
    moves = [m for m in legal_moves(state) if m["type"] == "battle_spoils"]
    assert {(m["lord_id"], m["amount"]) for m in moves} == {
        ("al_mutamid", 1), ("al_mutamid", 4), ("al_mundir", 1), ("al_mundir", 4),
    }
    assert state.lords["al_mundir"].assets == state.lords["al_mutamid"].assets == {}
    choice = {**moves[0], "lord_id": "al_mundir", "amount": 3}
    before = state.model_dump_json()
    for invalid, code in (
        ({**choice, "side": "christian"}, "not_responder"),
        ({**choice, "lord_id": "al_mustain"}, "bad_arg"),
        ({**choice, "asset": "coin"}, "bad_arg"),
        ({**choice, "amount": 5}, "bad_arg"),
        ({**choice, "amount": True}, "bad_arg"),
        ({"type": "end_card", "side": "muslim"}, "pending_decision"),
    ):
        with pytest.raises(IllegalAction) as error:
            apply_action(state, invalid)
        assert error.value.code == code
        assert state.model_dump_json() == before

    rng = state.meta.rng_state
    result = apply_action(state, choice)
    assert result["remaining_spoils"] == {"loot": 1}
    state = GameState.model_validate_json(state.model_dump_json())
    last = next(m for m in legal_moves(state) if m.get("lord_id") == "al_mutamid")
    result = apply_action(state, last)
    assert result["pending"] == "severed_heads"
    assert result["remaining_spoils"] == {}
    assert state.lords["al_mundir"].assets == {"loot": 3}
    assert state.lords["al_mutamid"].assets == {"loot": 1}
    apply_action(state, {"type": "decline_severed_heads", "side": "muslim"})
    assert state.pending is None and state.meta.active_player == "christian"
    assert state.meta.rng_state == rng


def test_loss_of_conceding_transport_donor_increases_spoils():
    state = muslim_attack({
        "alfonso": {"militia": 1}, "alvar_fanez": {"men_at_arms": 4},
        "al_mutamid": {"men_at_arms": 5}, "al_mundir": {"men_at_arms": 4},
    })
    state.lords["alfonso"].assets = {"cart": 2, "coin": 1}
    state.lords["alvar_fanez"].assets = {"prov": 2, "loot": 1}
    result = apply_combat_choices(state, {
        "type": "cmd_battle", "side": "muslim", "defender_concede_round": 1,
    })
    entries = {e["lord_id"]: e for e in result["retreat_summary"]["losers"]}
    assert entries["alfonso"]["removed_by_losses"]
    assert entries["alvar_fanez"]["spoils_lost"] == {"prov": 2, "loot": 1}
    assert state.lords["alvar_fanez"].assets == {}
    assert result["spoils"] == {"cart": 2, "coin": 1, "loot": 1, "prov": 2}


def test_sack_spoils_use_only_surviving_besiegers():
    state = _storm_setup(seed=42, siege=4)
    weak, strong = state.lords["alvar_fanez"], state.lords["alfonso"]
    weak.forces, weak.assets = {"militia": 1}, {}
    strong.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    strong.in_stronghold = False
    strong.forces, strong.assets = {"knights": 7, "men_at_arms": 7}, {}
    storm = next(m for m in legal_moves(state) if m["type"] == "cmd_storm")
    result = apply_combat_choices(state, storm)
    assert result["winner"] == "christian"
    assert weak.cylinder.kind == "removed"
    assert result["sack"]["recipients"] == ["alfonso"]
    assert result["spoils_awarded"] == {"alfonso": result["sack"]["spoils"]}
    assert strong.assets["loot"] == result["sack"]["spoils"]["loot"]
    assert strong.assets["prov"] == result["sack"]["spoils"]["prov"]
