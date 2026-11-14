"""Bernard Service and Cathedrals player-choice regressions."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import compute_final_vp
from almoravid.effective import is_friendly_locale
from almoravid.events import _jihad_eligible_locales
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder, ServiceMarker
from playtest_harness import Harness

RECONQUISTA = "scenario_f_reconquista"
TAJO = "scenario_b_quelling_of_tajo"


def _moves(harness, kind, **fields):
    return [move for move in legal_moves(harness.state)
            if move["type"] == kind and all(move.get(key) == value for key, value in fields.items())]


def _choose(harness, kind, **fields):
    return harness.apply(_moves(harness, kind, **fields)[0])


def _advance(harness, stop, priorities):
    for _ in range(110):
        if stop():
            return
        menu = legal_moves(harness.state)
        move = next(move for kind in priorities for move in menu if move["type"] == kind
                    and (kind != "reset_discard" or move.get("card_ids") == []))
        harness.apply(move)
    pytest.fail("Scenario did not reach the expected phase")


def _opening(harness, *, take_vassal=False):
    _choose(harness, "begin_levy")
    meta = harness.state.meta
    priorities = ("aow_draw", "aow_deploy_capability", "pass_step")
    if take_vassal:
        _advance(harness, lambda: (meta.levy_step, meta.active_player) == ("muster", "christian"),
                 priorities)
        _choose(harness, "levy_take_vassal", lord_id="alfonso", vassal_index=0)
    _advance(harness, lambda: meta.phase == "campaign", priorities)


def _plans(harness, first_lord=None):
    if first_lord:
        _choose(harness, "plan_add_card", side="christian", plan_kind="command",
                lord_id=first_lord)
    for side in ("christian", "muslim"):
        while not _moves(harness, "finalize_plan", side=side):
            choices = (_moves(harness, "plan_add_card", side=side, plan_kind="pass")
                       or _moves(harness, "plan_add_card", side=side, plan_kind="command"))
            harness.apply(choices[0])
        _choose(harness, "finalize_plan", side=side)


def _idle_campaign(harness):
    _plans(harness)
    _advance(harness, lambda: harness.state.meta.phase == "levy",
             ("command_reveal", "end_card", "end_campaign", "reset_discard"))


def _bernard(advanced):
    harness = Harness(RECONQUISTA, seed=9)
    harness.state.meta.advanced_vassal_service = advanced
    _opening(harness, take_vassal=True)
    _idle_campaign(harness)
    assert _choose(harness, "aow_draw")["drawn"] == ["C7", "C16"]
    _choose(harness, "aow_implement_event", card_id="C7")
    return harness


def _service(harness, lord_id="alfonso"):
    return {m.vassal_id or "lord": m.box for m in harness.state.calendar.service_markers
            if m.lord_id == lord_id}


def _replay(harness, move, tmp_path):
    path = tmp_path / "checkpoint.json"
    harness.save(path)
    loaded = Harness.load(path)
    menu = harness.legal()
    assert loaded.legal() == menu and move in menu
    result = harness.apply(menu.index(move))
    assert loaded.apply(menu.index(move)) == result
    assert loaded.state.model_dump_json() == harness.state.model_dump_json()
    assert not harness.findings and not loaded.findings
    return result


def _reject(harness, action, code):
    before = harness.state.model_dump_json()
    with pytest.raises(IllegalAction) as exc:
        apply_action(harness.state, action)
    assert exc.value.code == code
    assert harness.state.model_dump_json() == before


@pytest.mark.parametrize("advanced", [False, True])
def test_bernard_extends_froilas_service_in_native_campaign(advanced, tmp_path):
    harness = _bernard(advanced)
    state = harness.state
    menu = _moves(harness, "aow_implement_event", card_id="C16")
    assert {m["payload"]["mode"] for m in menu} == {"service_right", "muster"}
    move = next(m for m in menu if m["payload"] == {"mode": "service_right", "lord_id": "alfonso"})
    assert _service(harness) == ({"lord": 4, "alfonso_v1": 3} if advanced else {"lord": 4})
    assert _replay(harness, move, tmp_path)["event_result"]["new_service_box"] == 5
    assert _service(harness) == ({"lord": 5, "alfonso_v1": 4} if advanced else {"lord": 5})
    assert state.decks.board_edge["christian"].count("C16") == 1
    assert sum(card.card_id == "C16" for card in state.decks.capabilities_in_play) == 1
    assert "C16" not in state.decks.discard
    assert not _moves(harness, "aow_implement_event", card_id="C16")
    if advanced:
        priorities = ("aow_draw", "aow_implement_event", "pass_step", "disband_lord")
        _advance(harness, lambda: state.meta.phase == "campaign", priorities)
        _idle_campaign(harness)
        assert state.calendar.current_box == 3
        _advance(harness, lambda: (state.meta.levy_step, state.meta.active_player)
                 == ("service_disband", "christian"), priorities)
        while not _moves(harness, "pass_step"):
            _choose(harness, "disband_lord")
        forces = dict(state.lords["alfonso"].forces)
        _replay(harness, _moves(harness, "pass_step")[0], tmp_path)
        assert _service(harness)["alfonso_v1"] == 4
        assert state.lords["alfonso"].forces == forces
        assert not state.lords["alfonso"].vassals[0].pennant_down


@pytest.mark.parametrize("own_box", [0, 16, 17])
def test_bernard_shifts_vassal_even_at_calendar_edge(own_box, tmp_path):
    harness = _bernard(True)
    state = harness.state
    own = next(m for m in state.calendar.service_markers
               if m.lord_id == "alfonso" and m.vassal_id is None)
    calendar = state.calendar
    if own_box == 0 or own_box == 17:
        calendar.service_markers.remove(own)
        lane = calendar.off_left_service if own_box == 0 else calendar.off_right_service
        lane.append("alfonso")
    else:
        own.box = own_box
    other = ServiceMarker(lord_id="alvar_fanez", box=3, vassal_id="alvar_fanez_v1")
    calendar.service_markers.append(other)
    move = _moves(harness, "aow_implement_event", card_id="C16",
                  payload={"mode": "service_right", "lord_id": "alfonso"})[0]
    _reject(harness, {**move, "payload": {"lord_id": "alfonso_v1"}}, "bad_target")
    result = _replay(harness, move, tmp_path)["event_result"]
    assert result["new_service_box"] == min(17, own_box + 1)
    assert _service(harness) == {"lord": min(17, own_box + 1), "alfonso_v1": 4}
    assert "alfonso" not in calendar.off_left_service and other.box == 3


def test_bernard_muster_alternative_is_listed_and_installs_cathedrals():
    harness = _bernard(True)
    move = next(m for m in _moves(harness, "aow_implement_event", card_id="C16")
                if m["payload"]["mode"] == "muster")
    result = harness.apply(move)["event_result"]
    lord_id, seat = move["payload"]["lord_id"], move["payload"]["seat"]
    assert result["mustered"] == lord_id and result["seat"] == seat
    assert _service(harness)["alfonso_v1"] == 3
    assert harness.state.decks.board_edge["christian"].count("C16") == 1


def _cathedrals():
    harness = Harness(TAJO, seed=2)
    _opening(harness)
    assert "C16" in harness.state.decks.board_edge["christian"]
    _plans(harness, first_lord="alfonso")
    _choose(harness, "command_reveal", side="christian")
    assert harness.state.lords["alfonso"].cylinder.locale_id == "toledo"
    return harness


@pytest.mark.parametrize("target", ["trujillo", "talavera"])
def test_cathedrals_waits_for_muslim_choice_then_resumes_alfonso(target, tmp_path):
    harness = _cathedrals()
    state = harness.state
    before_vp = compute_final_vp(state)
    before_jihad = {lid: loc.jihad_markers for lid, loc in state.locales.items()}
    actions = state.meta.actions_remaining
    targets = set(_jihad_eligible_locales(state))
    assert {"trujillo", "talavera"} <= targets
    assert is_friendly_locale(state, "talavera", "christian")

    move = _moves(harness, "place_cathedral_seat")[0]
    _reject(harness, {**move, "jihad_targets": [target]}, "bad_arg")
    result = _replay(harness, move, tmp_path)
    assert result["cathedral_seat"] == "toledo" and result["pending"] == "cathedral_jihad"
    assert state.pending.waiting_on == state.meta.active_player == "muslim"
    assert "alfonso" in state.locales["toledo"].seat_marker_lord_ids
    assert compute_final_vp(state) == (before_vp[0] + 1, before_vp[1])
    assert {lid: loc.jihad_markers for lid, loc in state.locales.items()} == before_jihad
    menu = harness.legal()
    assert {m["type"] for m in menu} == {"cathedral_jihad"}
    assert {m["side"] for m in menu} == {"muslim"}
    assert {m["target_locale_id"] for m in menu} == targets
    assert "Muslims choose where to add 1 Jihad" in harness.briefing("summary")
    choice = next(m for m in menu if m["target_locale_id"] == target)
    _reject(harness, {**choice, "side": "christian"}, "not_responder")
    for invalid in ("toledo", "atlantic", ["talavera"], None):
        _reject(harness, {**choice, "target_locale_id": invalid}, "bad_target")
    _reject(harness, {"type": "end_card", "side": "christian"}, "pending_decision")
    _reject(harness, {**move, "jihad_targets": [target]}, "pending_decision")

    assert _replay(harness, choice, tmp_path)["jihad_placed"] == {target: 1}
    before_jihad[target] += 1
    assert {lid: loc.jihad_markers for lid, loc in state.locales.items()} == before_jihad
    assert compute_final_vp(state) == (before_vp[0] + 1, before_vp[1] + 0.5)
    assert is_friendly_locale(state, target, "muslim")
    assert is_friendly_locale(state, "talavera", "christian") == (target == "trujillo")
    assert state.pending is None
    assert state.meta.active_player == "christian" and state.meta.active_lord_id == "alfonso"
    assert state.meta.campaign_step == "activation" and state.meta.actions_remaining == actions
    _reject(harness, choice, "no_pending")


def test_cathedrals_without_a_jihad_destination_keeps_the_christian_activation():
    harness = _cathedrals()
    state = harness.state
    for taifa in state.taifas.values():
        taifa.status = "independent"
    assert not _jihad_eligible_locales(state)
    cvp, mvp = compute_final_vp(state)
    result = _choose(harness, "place_cathedral_seat")
    assert result["cathedral_seat"] == "toledo" and "pending" not in result
    assert state.pending is None and state.meta.active_player == "christian"
    assert compute_final_vp(state) == (cvp + 1, mvp)


@pytest.mark.parametrize("marker", ["siege_green", "bypass_green"])
def test_cathedral_jihad_opens_the_gates_for_a_muslim_lord(marker):
    harness = _cathedrals()
    state = harness.state
    lord = state.lords["al_mutamid"]
    lord.cylinder = Cylinder(kind="locale", locale_id="talavera")
    lord.in_stronghold = False
    target = state.locales["talavera"]
    setattr(target, marker, True if marker == "bypass_green" else 2)
    _choose(harness, "place_cathedral_seat")
    _choose(harness, "cathedral_jihad", target_locale_id="talavera")
    assert not getattr(target, marker)
    assert is_friendly_locale(state, "talavera", "muslim")


def test_cathedral_seat_persists_after_discarding_cathedrals():
    harness = _cathedrals()
    state = harness.state
    _choose(harness, "place_cathedral_seat")
    _choose(harness, "cathedral_jihad", target_locale_id="talavera")
    _advance(harness, lambda: state.pending is not None and state.pending.kind == "reset_discard",
             ("command_reveal", "end_card", "end_campaign"))
    _choose(harness, "reset_discard", side="christian", card_ids=["C16"])
    assert "C16" not in state.decks.board_edge["christian"]
    assert "toledo" in state.cathedral_seat_locales
    assert "alfonso" in state.locales["toledo"].seat_marker_lord_ids
