"""Vassal expiry preserves the Calendar phase and box-zero Pay window."""

import pytest

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import GameState

ALFONSO = "alfonso"
VELA = "alfonso_v2"
END_CARD = {"type": "end_card", "side": "christian"}


def _vela_position(advanced=True):
    state = load_scenario("scenario_f_reconquista", seed=14)
    state.meta.advanced_vassal_service = advanced
    state.meta.phase = "levy"
    state.meta.levy_step = "muster"
    state.meta.active_player = "christian"
    move = {"type": "levy_take_vassal", "side": "christian",
            "lord_id": ALFONSO, "vassal_index": 1}
    assert move in legal_moves(state)
    apply_action(state, move)
    return state


def _campaign(state):
    state.meta.phase = "campaign"
    state.meta.levy_step = None
    state.meta.campaign_step = "activation"
    state.meta.active_lord_id = ALFONSO
    state.meta.actions_remaining = 3


def _service(state, vassal=None):
    return next((m.box for m in state.calendar.service_markers
                 if m.lord_id == ALFONSO and m.vassal_id == vassal), None)


def _replay(state, transition):
    saved = GameState.model_validate_json(state.model_dump_json())
    result = transition(state)
    assert transition(saved) == result
    assert saved.model_dump() == state.model_dump()


@pytest.mark.parametrize("phase, last_forces, return_box", [
    ("campaign", True, 7), ("levy", True, 6), ("campaign", False, None),
])
def test_vassal_expiry_disbands_empty_lord_using_the_actual_phase(phase, last_forces, return_box):
    state = _vela_position()
    lord = state.lords[ALFONSO]
    vassal = lord.vassals[1]
    assert vassal.id == VELA and _service(state, VELA) == 2
    # In the casualty checkpoint only Vela's native Forces remain.
    native_forces = {unit: count - vassal.forces.get(unit, 0)
                     for unit, count in lord.forces.items() if count > vassal.forces.get(unit, 0)}
    if last_forces:
        lord.forces = dict(vassal.forces)
    state.calendar.current_box = 2
    if phase == "campaign":
        _campaign(state)
        action = END_CARD
    else:
        state.meta.levy_step = "service_disband"
        action = {"type": "pass_step", "side": "christian"}

    assert action in legal_moves(state)
    _replay(state, lambda position: apply_action(position, action))
    lord = state.lords[ALFONSO]
    assert _service(state, VELA) is None
    if last_forces:
        assert lord.cylinder.kind == "calendar"
        assert lord.cylinder.box == return_box
        assert not lord.forces and not lord.assets
        assert _service(state) is None
    else:
        assert lord.cylinder.kind == "locale"
        assert lord.forces == native_forces
        assert lord.vassals[1].pennant_down


def _arid_terrain_march(advanced=True):
    state = _vela_position(advanced=advanced)
    lord = state.lords[ALFONSO]
    # Supplies are exhausted and the opponent Holds Arid Terrain.
    lord.assets["prov"] = 0
    lord.assets.pop("loot", None)
    lord.assets["coin"] = 2  # Coin from earlier earnings.
    state.decks.held.setdefault("muslim", []).append("M4")
    _campaign(state)
    march = {"type": "cmd_march", "side": "christian",
             "target_locale_id": "palencia", "way_type": "road"}
    assert march in legal_moves(state)
    apply_action(state, march)
    apply_action(state, {"type": "arid_terrain_choice", "side": "muslim", "play": True})
    if state.pending is not None and state.pending.kind == "arid_terrain_choice":
        apply_action(state, {"type": "arid_terrain_choice", "side": "christian",
                             "discard_lords": []})
    assert _service(state) == 3
    assert _service(state, VELA) == (1 if advanced else None)
    return state


@pytest.mark.parametrize("payments", [0, 1, 2])
def test_box_zero_vassal_can_receive_pay_until_the_disband_step(payments):
    state = _arid_terrain_march()
    apply_action(state, {**END_CARD, "interactive_economy": True})
    while state.pending.kind == "greed_mule_choice":
        apply_action(state, {"type": "greed_mule_choice", "side": state.pending.waiting_on,
                             "discard_lords": []})
    assert state.pending.kind == "pay_before_disband"
    assert _service(state) == 2 and _service(state, VELA) == 0
    # The marker and its Forces both persist in a saved Pay decision.
    lord = state.lords[ALFONSO]
    assert lord.forces["sergeants"] == lord.forces["militia"] == 1
    assert VELA not in lord.removed_vassal_ids

    def finish_pay(position):
        pay = {"type": "pay_before_disband", "side": "christian", "resource": "coin",
               "amount": 1, "payer_lord_id": ALFONSO, "target_lord_id": ALFONSO}
        for _ in range(payments):
            assert pay in legal_moves(position)
            apply_action(position, pay)
        assert _service(position, VELA) == payments
        return tuple(apply_action(position, {"type": "pay_before_disband", "side": side,
                                             "done": True})
                     for side in ("christian", "muslim"))

    _replay(state, finish_pay)
    lord = state.lords[ALFONSO]
    vassal = lord.vassals[1]
    assert _service(state) == 2 + payments
    assert _service(state, VELA) == (2 if payments == 2 else None)
    assert (VELA in lord.removed_vassal_ids) == (payments == 0)
    assert vassal.pennant_down == (payments == 1)
    assert lord.forces.get("sergeants", 0) == lord.forces.get("militia", 0) == int(payments == 2)


def test_basic_rules_keep_vassal_forces_without_separate_service():
    state = _arid_terrain_march(advanced=False)
    apply_action(state, END_CARD)
    assert _service(state, VELA) is None
    assert VELA not in state.lords[ALFONSO].removed_vassal_ids
    assert state.lords[ALFONSO].forces["sergeants"] == state.lords[ALFONSO].forces["militia"] == 1
