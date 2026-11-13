"""Greed and Pay views preserve screened mats across saved economy windows."""

import pytest

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import GameState
from almoravid.views import redacted_view
from tests._plan_helpers import legal_pad, step_levy

END = {"type": "end_card", "side": "christian", "interactive_economy": True}


def _play(state, move):
    assert move in legal_moves(state)
    return apply_action(state, move)


def _alfonso_with_vassal(index, hidden):
    state = load_scenario("scenario_a_toledo_beset", seed=14)
    state.meta.hidden_mats = hidden
    apply_action(state, {"type": "begin_levy"})
    for _ in range(30):
        if state.meta.levy_step == "muster":
            break
        step_levy(state)
    assert state.meta.levy_step == "muster"
    _play(state, {"type": "levy_take_vassal", "side": "christian", "lord_id": "alfonso",
                  "vassal_index": index})
    _play(state, {"type": "levy_transport", "side": "christian", "lord_id": "alfonso",
                  "transport": "mule"})
    for _ in range(30):
        if state.meta.phase != "levy":
            break
        step_levy(state)
    assert state.meta.phase == "campaign"
    apply_action(state, {"type": "begin_campaign"})
    _play(state, {"type": "plan_add_card", "side": "christian",
                  "plan_kind": "command", "lord_id": "alfonso"})
    for side in ("christian", "muslim"):
        legal_pad(state, side)
        _play(state, {"type": "finalize_plan", "side": side})
    _play(state, {"type": "command_reveal", "side": "christian"})
    # Prior food expenditure is the same in both audit positions.
    state.lords["alfonso"].assets.update(prov=0, loot=0)
    _play(state, {"type": "cmd_march", "side": "christian", "target_locale_id": "leon",
                  "way_type": "road"})
    return state


def _legacy_pay_view(state, eligible, hidden):
    """Older Pay saves keep the original Greed record, even on the other turn."""
    legacy = GameState.model_validate_json(state.model_dump_json())
    legacy.pending.payload["eligible"] = eligible
    before = legacy.model_dump_json()
    restored = GameState.model_validate_json(before)
    view = redacted_view(restored, "muslim")
    if hidden:
        assert "eligible" not in view["pending"]["payload"]
    else:
        assert view["pending"]["payload"]["eligible"] == eligible
    assert redacted_view(restored, "christian")["pending"]["payload"]["eligible"] == eligible
    assert restored.model_dump_json() == before
    return restored


@pytest.mark.parametrize("hidden", [False, True])
def test_opponent_greed_and_pay_views_only_differ_with_open_mats(hidden):
    states = [_alfonso_with_vassal(i, hidden) for i in (0, 1)]
    before = [redacted_view(state, "muslim") for state in states]
    assert (before[0] == before[1]) is hidden
    for expected_units, state in zip((6, 5), states, strict=True):
        _play(state, END)
        assert state.pending.kind == "greed_mule_choice"
        eligible = state.pending.payload["eligible"]
        assert eligible[0]["units"] == expected_units
        snapshot = state.model_dump_json()
        resumed = GameState.model_validate_json(snapshot)
        owner = redacted_view(resumed, "christian")
        assert owner["pending"]["payload"]["eligible"] == eligible
        assert owner["lords"]["alfonso"]["forces"] == state.lords["alfonso"].forces
        opponent = redacted_view(resumed, "muslim")
        assert (opponent["lords"]["alfonso"]["forces"] is None) is hidden
        assert ("eligible" in opponent["pending"]["payload"]) is not hidden
        assert resumed.model_dump_json() == snapshot
        keep = {"type": "greed_mule_choice", "side": "christian", "discard_lords": []}
        result = _play(state, keep)
        assert _play(resumed, keep) == result
        assert resumed.model_dump_json() == state.model_dump_json()
        assert state.pending.kind == "pay_before_disband"
        assert "eligible" not in state.pending.payload
        assert state.pending.payload["feed_result"]["unfed"] == ["alfonso"]
        assert state.lords["alfonso"].assets["mule"] == 2
        for side in ("christian", "muslim"):
            assert state.pending.waiting_on == side
            legacy = _legacy_pay_view(state, eligible, hidden)
            done = {"type": "pay_before_disband", "side": side, "done": True}
            assert _play(legacy, done) == _play(state, done)
            assert legacy.model_dump_json() == state.model_dump_json()
        assert state.pending is None


def test_hidden_opponent_views_match_through_both_pay_turns():
    states = [_alfonso_with_vassal(i, True) for i in (0, 1)]
    moves = [
        END,
        {"type": "greed_mule_choice", "side": "christian", "discard_lords": []},
        {"type": "pay_before_disband", "side": "christian", "done": True},
    ]
    for move in moves:
        for state in states:
            _play(state, move)
        assert redacted_view(states[0], "muslim") == redacted_view(states[1], "muslim")
