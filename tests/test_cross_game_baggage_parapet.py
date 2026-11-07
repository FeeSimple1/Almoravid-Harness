"""A3-03. Each retreating Christian Lord chooses his own C7 payment."""

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import GameState
from tests.test_audit_combat_regressions import _combat_state
from tests.test_cross_game_battle_fates import fate_moves
from tests.combat_choices import apply_combat_choices


def begin_retreat(assets, *, locale="transduero", held=True, ally_assets=None):
    forces = {"alfonso": {"men_at_arms": 4}, "al_mutamid": {"men_at_arms": 4}}
    if ally_assets is not None:
        forces["alvar_fanez"] = {"men_at_arms": 4}
    state = _combat_state(forces, locale=locale)
    state.lords["alfonso"].assets = assets
    if ally_assets is not None:
        state.lords["alvar_fanez"].assets = ally_assets
    state.decks.held["christian"] = ["C7"] if held else []
    battle = next(m for m in legal_moves(state) if m["type"] == "cmd_battle")
    result = apply_combat_choices(state, {**battle, "attacker_concede_round": 1},
                                  cards=("C7",) if held else ())
    assert result["pending"] == "battle_fate"
    return state


def retreat_variants(state, lord_id):
    moves = [m for m in fate_moves(state, lord_id) if m["fate"] == "retreat"]
    target, way = moves[0]["retreat_to"], moves[0]["retreat_way"]
    return {m.get("c7_pay"): m for m in moves
            if (m["retreat_to"], m["retreat_way"]) == (target, way)}


@pytest.mark.parametrize("payment, kept", [
    ("coin", {"mule": 1, "loot": 1}),
    ("mule", {"coin": 1, "loot": 1}),
    (None, {"coin": 1, "mule": 1}),
])
def test_choose_an_asset_or_retreat_without_protection(payment, kept):
    state = begin_retreat({"coin": 1, "mule": 1, "loot": 1})
    variants = retreat_variants(state, "alfonso")
    assert variants.keys() == {None, "coin", "mule", "loot"}
    result = apply_action(state, variants[payment])
    entry = result["retreat_summary"]["losers"][0]
    assert state.lords["alfonso"].assets == kept
    if payment is None:
        assert entry["service_shift_boxes"] in (1, 2, 3)
        assert entry["spoils_lost"] == {"loot": 1}
    else:
        assert entry["c7_opt_out_asset"] == payment
        assert entry["service_roll"] is None
        assert entry["service_shift_boxes"] == 0
        assert entry["spoils_lost"] == {}
    assert state.decks.discard.count("C7") == 1


def test_reject_unavailable_or_nonretreat_payment_before_mutation():
    state = begin_retreat({"mule": 1}, locale="leon")
    retreat = retreat_variants(state, "alfonso")[None]
    withdraw = next(m for m in fate_moves(state, "alfonso") if m["fate"] == "withdraw")
    before = state.model_dump_json()
    for invalid in ({**retreat, "c7_pay": "coin"},
                    {**retreat, "c7_pay": ["mule"]},
                    {**withdraw, "c7_pay": "mule"}):
        with pytest.raises(IllegalAction, match="C7 payment"):
            apply_action(state, invalid)
        assert state.model_dump_json() == before


@pytest.mark.parametrize("held, assets", [(True, {}), (False, {"coin": 1})])
def test_no_payment_variant_without_the_event_and_available_asset(held, assets):
    state = begin_retreat(assets, held=held)
    variants = retreat_variants(state, "alfonso")
    assert variants.keys() == {None}
    before = state.model_dump_json()
    with pytest.raises(IllegalAction, match="C7 payment"):
        apply_action(state, {**variants[None], "c7_pay": "coin"})
    assert state.model_dump_json() == before


@pytest.mark.parametrize("legacy", [False, True])
def test_per_lord_payment_is_staged_across_save_and_reload(legacy):
    state = begin_retreat({"coin": 1, "mule": 1}, ally_assets={"loot": 1})
    alfonso = retreat_variants(state, "alfonso")["coin"]
    before_rng = state.meta.rng_state
    apply_action(state, alfonso)
    assert state.meta.rng_state == before_rng
    assert state.lords["alfonso"].assets == {"coin": 1, "mule": 1}
    saved = state.model_dump()
    if legacy:
        # A route chosen on the preceding version has no payment field.
        del saved["pending"]["payload"]["fates"]["alfonso"]["c7_pay"]
    resumed = GameState.model_validate(saved)
    assert retreat_variants(resumed, "alvar_fanez").keys() == {None, "loot"}
    result = apply_action(resumed, retreat_variants(resumed, "alvar_fanez")[None])
    entries = {e["lord_id"]: e for e in result["retreat_summary"]["losers"]}
    assert entries["alfonso"]["c7_opt_out_asset"] == ("mule" if legacy else "coin")
    assert resumed.lords["alfonso"].assets == ({"coin": 1} if legacy else {"mule": 1})
    assert entries["alvar_fanez"]["spoils_lost"] == {"loot": 1}
    assert entries["alvar_fanez"]["service_shift_boxes"] in (1, 2, 3)
