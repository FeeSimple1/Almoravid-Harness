"""Cross-game audit R1/R2: recipient eligibility and rejected-action rollback."""
import pytest

from almoravid import actions
from almoravid.rng import roll_d6
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker


def disband_state():
    state = load_scenario("scenario_c_parias_wars", seed=1)
    lord = state.lords["al_mustain"]
    state.meta.phase = "levy"
    state.meta.levy_step = "service_disband"
    state.meta.active_player = "muslim"
    lord.cylinder = Cylinder(kind="locale", locale_id=lord.seats[0])
    state.taifas[lord.home_taifa].status = "independent"
    state.calendar.service_markers = [m for m in state.calendar.service_markers
                                      if m.lord_id != lord.id]
    state.calendar.service_markers.append(ServiceMarker(lord_id=lord.id,
                                                        box=state.calendar.current_box))
    return state


def test_rejected_disband_preserves_references_and_corrected_retry():
    state = disband_state()
    pristine = state.model_copy(deep=True)
    lord = state.lords["al_mustain"]
    taifa = state.taifas[lord.home_taifa]
    history = state.history
    before = state.model_dump_json()
    action = {"type": "disband_lord", "side": "muslim", "lord_id": lord.id,
              "parias_coin_targets": [{"lord_id": "alfonso", "coin": 2}]}
    with pytest.raises(actions.IllegalAction) as error:
        actions.apply_action(state, action)
    assert error.value.code == "bad_parias_total"
    assert state.model_dump_json() == before
    assert state.lords[lord.id] is lord
    assert state.taifas[lord.home_taifa] is taifa
    assert state.history is history
    action["parias_coin_targets"][0]["coin"] = 4
    assert actions.apply_action(state, action) == actions.apply_action(pristine, action)
    assert state.model_dump_json() == pristine.model_dump_json()


def test_pay_rejects_enemy_without_spending_coin():
    state = load_scenario("scenario_a_toledo_beset", seed=1)
    state.meta.phase = "levy"
    state.meta.levy_step = "pay"
    state.meta.active_player = "christian"
    payer, enemy = state.lords["alfonso"], state.lords["al_mustain"]
    payer.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    payer.assets = {"coin": 1}
    enemy.in_stronghold = True
    state.locales["zaragoza"].siege_yellow = 1
    before = state.model_dump_json()
    with pytest.raises(actions.IllegalAction) as error:
        actions.apply_action(state, {"type": "pay_lord", "side": "christian",
            "payer_lord_id": payer.id, "target_lord_id": enemy.id,
            "resource": "coin", "amount": 1})
    assert error.value.code == "wrong_side"
    assert state.model_dump_json() == before


@pytest.mark.parametrize("recipient", ["alfonso", "garcia_ordonez"])
def test_pay_still_accepts_friendly_recipient(recipient):
    state = load_scenario("scenario_a_toledo_beset", seed=1)
    state.meta.phase = "levy"
    state.meta.levy_step = "pay"
    state.meta.active_player = "christian"
    state.lords["alfonso"].assets = {"coin": 1}
    marker = next(m for m in state.calendar.service_markers
                  if m.lord_id == recipient and m.vassal_id is None)
    before = marker.box
    actions.apply_action(state, {"type": "pay_lord", "side": "christian",
        "payer_lord_id": "alfonso", "target_lord_id": recipient,
        "resource": "coin", "amount": 1})
    assert marker.box == before + 1
    assert state.lords["alfonso"].assets.get("coin", 0) == 0


def test_unexpected_failure_restores_dice_and_appended_history(monkeypatch):
    state = load_scenario("scenario_a_toledo_beset", seed=1)
    before = state.model_dump_json()
    history = state.history
    assets = state.lords["alfonso"].assets
    def fail(state, action):
        roll_d6(state)
        state.lords["alfonso"].assets["coin"] = 99
        state.history.append(state.history[0].model_copy(deep=True))
        raise RuntimeError("failure after resolution")
    monkeypatch.setitem(actions._HANDLERS, "audit_failure", fail)
    with pytest.raises(RuntimeError, match="failure after resolution"):
        actions.apply_action(state, {"type": "audit_failure"})
    assert state.model_dump_json() == before
    assert state.history is history
    assert state.lords["alfonso"].assets is assets
