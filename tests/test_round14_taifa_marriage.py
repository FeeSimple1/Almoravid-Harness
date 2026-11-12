"""Taifa Marriage's public choices and Calendar shifts (A14-02 and A14-04)."""

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, GameState

M12 = {"type": "play_event", "side": "muslim", "card_id": "M12"}
LORD = "al_mustain"
VASSAL = "al_mustain_v3"


def _position(advanced=False):
    state = load_scenario("scenario_a_toledo_beset", seed=14)
    state.meta.phase = "levy"
    state.meta.levy_step = "muster"
    state.meta.active_player = "muslim"
    state.meta.advanced_vassal_service = advanced
    return state


def _box(state, lid, vid=None):
    return next((m.box for m in state.calendar.service_markers
                 if m.lord_id == lid and m.vassal_id == vid), None)


def _play(state, action):
    assert action in legal_moves(state)
    restored = GameState.model_validate_json(state.model_dump_json())
    result = apply_action(state, action)
    assert apply_action(restored, action) == result
    assert restored.model_dump() == state.model_dump()
    return result


def _muster_vassal(state):
    apply_action(state, {"type": "levy_take_vassal", "side": "muslim",
                         "lord_id": LORD, "vassal_index": 2})


@pytest.mark.parametrize("advanced", [True, False])
def test_taifa_marriage_keeps_the_mustered_vassal_serving(advanced):
    state = _position(advanced=advanced)
    _muster_vassal(state)
    # Save files need not list a Lord's marker before his Vassals' markers.
    state.calendar.service_markers.sort(key=lambda m: m.vassal_id is None)
    assert _box(state, LORD) == 4
    assert _box(state, LORD, VASSAL) == (2 if advanced else None)
    _play(state, {**M12, "payload": {"lord_ids": [LORD]}})
    assert _box(state, LORD) == 5
    assert _box(state, LORD, VASSAL) == (3 if advanced else None)
    assert "M12" not in state.decks.held["muslim"]
    assert state.decks.discard.count("M12") == 1

    state.calendar.current_box = 2
    state.meta.phase, state.meta.levy_step = "campaign", None
    state.meta.campaign_step = "activation"
    state.meta.active_lord_id = LORD
    state.meta.actions_remaining = 3
    _play(state, {"type": "end_card", "side": "muslim"})
    assert state.lords[LORD].forces["light_horse"] == 2
    assert not state.lords[LORD].vassals[2].pennant_down


@pytest.mark.parametrize("before, after", [(0, 1), (16, 17), (17, 17)])
def test_taifa_marriage_uses_the_service_edge_policy(before, after):
    state = _position(advanced=True)
    _muster_vassal(state)
    state.meta.levy_step = "pay"
    marker = next(m for m in state.calendar.service_markers
                  if m.lord_id == LORD and m.vassal_id is None)
    if before == 0:
        state.calendar.service_markers.remove(marker)
        state.calendar.off_left_service.append(LORD)
        next(m for m in state.calendar.service_markers if m.vassal_id == VASSAL).box = 0
    else:
        marker.box = before

    _play(state, {**M12, "payload": {"lord_ids": [LORD]}})
    assert _box(state, LORD) == after
    assert _box(state, LORD, VASSAL) == (1 if before == 0 else 3)
    assert LORD not in state.calendar.off_left_service


@pytest.mark.parametrize("targets, code", [
    pytest.param([LORD, LORD], "bad_arg", id="duplicate"),
    pytest.param(["alfonso"], "not_eligible", id="christian"),
    pytest.param([LORD, "abd_allah"], "not_eligible", id="set-aside-second-target"),
    pytest.param(["not_a_lord"], "not_eligible", id="unknown"),
    pytest.param([LORD, "abu_bakr", "al_mutamid"], "bad_arg", id="too-many"),
    pytest.param([LORD, []], "bad_arg", id="malformed-id"),
    pytest.param(LORD, "bad_arg", id="not-a-list"),
    pytest.param([], "bad_arg", id="empty"),
])
def test_bad_taifa_marriage_choices_leave_the_hold_and_all_markers_intact(targets, code):
    state = _position()
    action = {**M12, "payload": {"lord_ids": targets}}
    for position in (state, GameState.model_validate_json(state.model_dump_json())):
        assert action not in legal_moves(position)
        before = position.model_dump_json()
        with pytest.raises(IllegalAction) as rejected:
            apply_action(position, action)
        assert rejected.value.code == code
        assert position.model_dump_json() == before


def test_taifa_marriage_accepts_distinct_service_and_cylinder_targets():
    state = _position()
    # Abu Bakr was Disbanded beyond the end of the numbered Calendar.
    lid = "abu_bakr"
    lord = state.lords[lid]
    lord.cylinder = Cylinder(kind="calendar", box=17)
    lord.forces, lord.assets = {}, {}
    state.calendar.service_markers = [m for m in state.calendar.service_markers if m.lord_id != lid]
    state.calendar.off_right.append(lid)
    _play(state, {**M12, "payload": {"lord_ids": [LORD, lid]}})
    assert _box(state, LORD) == 5
    assert lord.cylinder.box == 16
    assert lid not in state.calendar.off_right
    assert _box(state, "alfonso") == 4
    assert state.decks.discard.count("M12") == 1


def test_taifa_marriage_still_offers_the_lordship_alternative():
    state = _position()
    _play(state, {**M12, "payload": {"mode": "lordship", "lord_id": LORD}})
    assert state.lords[LORD].lordship_bonus_this_levy == 2
    assert _box(state, LORD) == 4
    assert state.decks.discard.count("M12") == 1
