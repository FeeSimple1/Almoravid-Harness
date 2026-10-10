"""Rules-based regressions found by the Scenario F / seed 73 long playtest.
Run against the tested checkout with:
  PYTHONPATH=/path/to/Almoravid-Harness/src pytest -q test_scenario_f_findings.py
These assertions failed on c446841; fixture histories are omitted, not board data.
"""
import json
from pathlib import Path

import pytest
from almoravid.actions import apply_action
from almoravid.state import GameState

HERE = Path(__file__).resolve().parent / "fixtures" / "scenario_f_seed73"

def load(name):
    return GameState.model_validate_json((HERE / name).read_text())

def marker(state, lord_id):
    return next((m.box for m in state.calendar.service_markers
                 if m.lord_id == lord_id and m.vassal_id is None), None)

@pytest.mark.parametrize("lord_id", ["alfonso", "alvar_fanez"])
def test_winter_keeps_besieger_service(lord_id):
    """6.3.1 exempts siege Lords; both Service markers were in box 9."""
    state = load("before-winter.json")
    assert marker(state, lord_id) == 9
    apply_action(state, {"type": "end_campaign"})
    assert state.lords[lord_id].cylinder.kind == "locale"
    assert marker(state, lord_id) == 9

def test_winter_pay_extends_existing_service():
    """6.3.2 Pay must advance the retained marker, not create it at box 1."""
    state = load("before-winter.json")
    apply_action(state, {"type":"end_campaign"})
    for lord_id in ("alfonso", "alvar_fanez"):
        apply_action(state, {"type":"winter_siege_action","side":"christian",
                            "lord_id":lord_id,"mode":"supply","source_seat":"burgos"})
    apply_action(state, {"type":"winter_siege_pay","side":"christian",
                        "resource":"coin","amount":1,
                        "payer_lord_id":"alfonso","target_lord_id":"alfonso"})
    assert marker(state, "alfonso") == 10

@pytest.mark.parametrize("lord_id", ["al_mutamid", "al_mutawakkil", "al_mundir"])
def test_spring_muster_restores_regular_ready_vassals(lord_id):
    """6.3.3 -> 3.4.1: prepare mats anew, with available Vassals Ready."""
    state = load("withdrawal-before-winter.json")
    apply_action(state, {"type":"end_campaign"})
    lord = state.lords[lord_id]
    assert lord.cylinder.kind == "locale"
    regular = [v for v in lord.vassals if v.id.startswith(lord_id + "_v")]
    assert regular
    assert all(v.ready for v in regular)

def test_returning_lord_can_levy_his_regular_vassal():
    """The unavailable-vassal condition blocks an actual legal Muster choice."""
    state = load("withdrawal-before-winter.json")
    actions = json.loads((HERE / "spring-levy-actions.json").read_text())
    # Includes Winter and the authentic Spring Levy through Christian Muster,
    # stopping just before the Muslim Muster action at action 745.
    for action in actions:
        apply_action(state, action)
    apply_action(state, {"type":"levy_take_vassal","side":"muslim",
                         "lord_id":"al_mutamid","vassal_index":0})

def test_winter_bishoprics_discard_removes_bishops():
    """C22 says discard removes all Bishops; 6.3.1 discards board-edge cards."""
    state = load("withdrawal-before-winter.json")
    apply_action(state, {"type":"end_campaign"})
    assert "C22" not in state.decks.board_edge.get("christian", [])
    assert not [(lid, v.id) for lid, lord in state.lords.items()
                for v in lord.vassals if v.id.startswith("bishop")]
    assert not state.meta.aow_cap_state.get("C22_bishops")

def test_bishoprics_can_place_during_muster():
    """C22 and 3.4.2 permit placing a Ready Bishop at any time."""
    state = load("bishop-levy-placement-before.json")
    assert state.meta.phase == "levy" and state.meta.levy_step == "muster"
    apply_action(state, {"type":"cap_bishoprics","side":"christian",
                         "target_lord_id":"alvar_fanez"})
