"""Scenario F winter + C22 lifecycle regressions (Rules 6.3 / 3.4.1-.2).

Saved seed-73 positions are covered separately. These small fixtures exercise
both sides, Service-marker variants, normal and advanced Vassals, and every
Bishoprics placement/discard boundary rather than only the original line.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import (
    _apply_capability_discard,
    _available_bishops,
    _remove_bishops,
    spring_muster,
    winter_disband,
)
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, PendingDecision, ServiceMarker, Vassal
from almoravid.static_data import load_lords


def _state():
    s = load_scenario("scenario_f_reconquista", seed=73)
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    return s


def _deploy_bishoprics(s):
    s.decks.board_edge.setdefault("christian", []).append("C22")
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C22", scope="side_wide", owner_side="christian"))


def _place(s, lord="alfonso", bishop="bishop_1"):
    return apply_action(s, {"type": "cap_bishoprics", "side": "christian",
                            "target_lord_id": lord, "bishop_id": bishop})


def _svc(s, lord):
    return next(m.box for m in s.calendar.service_markers
                if m.lord_id == lord and m.vassal_id is None)


def _winter_state():
    s = _state()
    s.calendar.current_box = 6
    s.meta.phase = "campaign"
    s.meta.campaign_step = "end_campaign"
    s.decks.plan = {"christian": [], "muslim": []}
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.locales["toledo"].siege_yellow = 1
    for lord in s.lords.values():
        if lord.cylinder.kind == "locale":
            lord.assets["prov"] = 20
    s.calendar.service_markers = [
        ServiceMarker(lord_id=lid, box=9)
        for lid, lord in s.lords.items() if lord.cylinder.kind == "locale"
    ]
    return s


@pytest.mark.parametrize("advanced", [False, True])
def test_winter_keeps_both_sides_siege_service_and_only_clears_departed(advanced):
    s = _winter_state()
    s.meta.advanced_vassal_service = advanced
    defender = s.lords["al_mustain"]
    defender.cylinder = Cylinder(kind="locale", locale_id="toledo")
    defender.in_stronghold = True
    s.calendar.service_markers.append(ServiceMarker(lord_id=defender.id, box=10))
    retained = {"alfonso", "alvar_fanez", "al_mustain"}
    if advanced:
        for lid in ("alfonso", "al_mustain", "garcia_ordonez"):
            s.calendar.service_markers.append(
                ServiceMarker(lord_id=lid, box=9, vassal_id=f"{lid}_v1"))
    expected = [m.model_dump() for m in s.calendar.service_markers if m.lord_id in retained]
    s.calendar.current_box = 7
    winter_disband(s)
    assert [m.model_dump() for m in s.calendar.service_markers] == expected
    assert defender.in_stronghold
    assert s.lords["garcia_ordonez"].cylinder.kind == "mat"
    assert not s.lords["garcia_ordonez"].vassals


def test_winter_service_off_edge_lanes_keep_siege_lord_only():
    s = _winter_state()
    next(m for m in s.calendar.service_markers if m.lord_id == "alfonso").box = 17
    next(m for m in s.calendar.service_markers if m.lord_id == "garcia_ordonez").box = 17
    s.calendar.off_right_service = ["alfonso", "garcia_ordonez"]
    s.calendar.current_box = 7
    winter_disband(s)
    assert s.calendar.off_right_service == ["alfonso"]
    assert _svc(s, "alfonso") == 17


def test_paid_besiegers_survive_both_winter_boxes_without_service_reset():
    s = _winter_state()
    before = {lid: deepcopy(s.lords[lid].forces) for lid in ("alfonso", "alvar_fanez")}
    apply_action(s, {"type": "end_campaign"})
    seen = []
    while s.meta.phase == "winter":
        p = s.pending
        assert p is not None and p.kind == "winter_siege"
        seen.append(s.calendar.current_box)
        if p.payload["step"] == "besieger_actions":
            action = {"type": "winter_siege_action", "side": p.waiting_on,
                      "lord_id": p.payload["queue"][0], "mode": "pass"}
        else:
            action = {"type": "winter_siege_pay", "side": p.waiting_on, "done": True}
        apply_action(s, action)
    assert set(seen) == {7, 8}
    assert s.calendar.current_box == 9 and s.meta.phase == "levy"
    for lid in before:
        assert s.lords[lid].cylinder.kind == "locale"
        assert s.lords[lid].forces == before[lid]
        assert _svc(s, lid) == 9
    assert s.score.winner is None


@pytest.mark.parametrize("lord_id", ["alfonso", "alvar_fanez", "al_mutamid", "al_mutawakkil"])
def test_spring_uses_normal_initializer_excludes_removed_vassals(lord_id):
    s = _state()
    s.meta.phase = "winter"
    s.calendar.current_box = 8
    lord = s.lords[lord_id]
    lord.cylinder = Cylinder(kind="mat")
    lord.vassals = [Vassal(id="stale", name="Stale", forces={},
                          service_cost=2, ready=False, pennant_down=True)]
    lord.removed_vassal_ids = [f"{lord_id}_v1"]
    lord.lordship_used = 2
    lord.routed_units = {"knights": 1}
    s.calendar.service_markers.append(ServiceMarker(lord_id=lord_id, box=0))
    s.calendar.off_left_service.append(lord_id)
    spring_muster(s)
    static = load_lords()["lords"][lord_id]
    assert lord.cylinder.kind == "locale"
    assert lord.forces == static["forces"]  # no Vassal troops for free
    assert lord.assets == static["assets"]
    assert all(v.ready and not v.pennant_down for v in lord.vassals)
    assert [v.id for v in lord.vassals] == [
        f"{lord_id}_v{i+1}" for i in range(1, len(static["vassals"]))]
    assert lord.removed_vassal_ids == [f"{lord_id}_v1"]
    assert lord.lordship_used == 0 and not lord.just_arrived_this_levy
    assert not lord.routed_units
    assert _svc(s, lord_id) == 8 + lord.service_rating
    assert len([m for m in s.calendar.service_markers if m.lord_id == lord_id]) == 1
    assert lord_id not in s.calendar.off_left_service


def test_spring_does_not_reset_lord_who_stayed_at_siege():
    s = _winter_state()
    s.calendar.current_box = 8
    lord = s.lords["alfonso"]
    lord.vassals[0].ready = False
    snapshot = lord.model_dump()
    markers = [m.model_dump() for m in s.calendar.service_markers if m.lord_id == lord.id]
    spring_muster(s)
    assert lord.model_dump() == snapshot
    assert [m.model_dump() for m in s.calendar.service_markers if m.lord_id == lord.id] == markers


def test_spring_muster_rejects_enemy_controlled_unoccupied_seat():
    s = _state()
    s.calendar.current_box = 8
    lord = s.lords["al_mustain"]
    lord.cylinder = Cylinder(kind="mat")
    s.taifas["zaragoza"].status = "reconquista"
    for other in s.lords.values():
        if other.cylinder.kind == "locale" and other.cylinder.locale_id in lord.seats:
            other.cylinder = Cylinder(kind="calendar", box=10)
    result = spring_muster(s)
    assert lord.id in result["no_free_seat"]
    assert lord.cylinder.kind == "calendar"


@pytest.mark.parametrize("phase,step", [
    ("levy", "arts_of_war"), ("levy", "pay"), ("levy", "service_disband"),
    ("levy", "muster"), ("levy", "call_to_arms"), ("campaign", "plan"),
    ("campaign", "activation"), ("campaign", "end_campaign"),
])
def test_bishoprics_placement_is_free_and_enumerated_throughout_play(phase, step):
    s = _state()
    _deploy_bishoprics(s)
    s.meta.phase = phase
    if phase == "levy":
        s.meta.levy_step = step
    else:
        s.meta.campaign_step = step
    s.meta.active_lord_id = None
    s.meta.actions_remaining = 0
    before_forces = deepcopy(s.lords["alfonso"].forces)
    before_lordship = s.lords["alfonso"].lordship_used
    candidates = [m for m in legal_moves(s) if m["type"] == "cap_bishoprics"]
    assert {m["bishop_id"] for m in candidates} == {"bishop_1", "bishop_2", "bishop_3"}
    assert not any(m["target_lord_id"] == "sancho" for m in candidates)
    for move in candidates:
        apply_action(deepcopy(s), move)
    _place(s, bishop="bishop_2")
    assert s.lords["alfonso"].vassals[-1].ready
    assert s.lords["alfonso"].forces == before_forces
    assert s.lords["alfonso"].lordship_used == before_lordship
    assert s.meta.actions_remaining == 0 and s.meta.active_lord_id is None
    assert s.meta.active_player == "christian"


@pytest.mark.parametrize("active", ["christian", "muslim"])
def test_bishoprics_preserves_pending_decision_and_opponents_turn(active):
    s = _state()
    _deploy_bishoprics(s)
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = active
    s.meta.active_lord_id = "al_mutamid"
    s.meta.actions_remaining = 2
    s.pending = PendingDecision(kind="battle_concede", waiting_on=active, payload={"round": 1})
    pending = s.pending.model_dump()
    if active == "christian":
        assert any(m["type"] == "cap_bishoprics" for m in legal_moves(s))
    _place(s)
    assert s.pending.model_dump() == pending
    assert s.meta.active_player == active
    assert s.meta.active_lord_id == "al_mutamid" and s.meta.actions_remaining == 2


def test_bishop_can_be_added_to_besieged_or_muster_banned_lord_but_not_mustered():
    s = _state()
    _deploy_bishoprics(s)
    s.meta.muster_banned_this_levy_lord_ids = ["alfonso"]
    _place(s)
    # Adding a Ready marker is free; recruiting its troops is a distinct Levy action.
    index = len(s.lords["alfonso"].vassals) - 1
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "levy_take_vassal", "side": "christian",
                         "lord_id": "alfonso", "vassal_index": index})
    assert s.lords["alfonso"].vassals[index].ready


@pytest.mark.parametrize("advanced", [False, True])
def test_bishop_can_be_levied_immediately_without_calendar_service(advanced):
    s = _state()
    s.meta.advanced_vassal_service = advanced
    _deploy_bishoprics(s)
    base = deepcopy(s.lords["alfonso"].forces)
    _place(s, bishop="bishop_2")
    lord = s.lords["alfonso"]
    index = len(lord.vassals) - 1
    move = {"type": "levy_take_vassal", "side": "christian", "lord_id": lord.id,
            "vassal_index": index}
    assert move in legal_moves(s)
    apply_action(s, move)
    assert not lord.vassals[index].ready
    assert lord.forces["knights"] == base.get("knights", 0) + 1
    assert lord.forces["men_at_arms"] == base.get("men_at_arms", 0) + 1
    assert not any(m.vassal_id == "bishop_2" for m in s.calendar.service_markers)


@pytest.mark.parametrize("phase", ["setup", "ended"])
def test_bishoprics_rejected_outside_live_game(phase):
    s = _state()
    _deploy_bishoprics(s)
    s.meta.phase = phase
    assert not any(m["type"] == "cap_bishoprics" for m in legal_moves(s))
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        _place(s)
    assert s.model_dump() == before


@pytest.mark.parametrize("change", [
    {"side": "muslim"}, {"target_lord_id": "sancho"},
    {"target_lord_id": "al_mutamid"}, {"target_lord_id": "eudes"},
    {"target_lord_id": []}, {"bishop_id": "bishop_99"}, {"bishop_id": []},
])
def test_invalid_bishop_placement_is_atomic(change):
    s = _state()
    _deploy_bishoprics(s)
    action = {"type": "cap_bishoprics", "side": "christian", "target_lord_id": "alfonso"}
    action.update(change)
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(s, action)
    assert s.model_dump() == before


def test_three_unique_bishops_maximum_one_per_lord():
    s = _state()
    _deploy_bishoprics(s)
    _place(s, "alfonso", "bishop_2")
    _place(s, "alvar_fanez", "bishop_3")
    with pytest.raises(IllegalAction):
        _place(s, "alfonso", "bishop_1")
    with pytest.raises(IllegalAction):
        _place(s, "pedro_ansurez", "bishop_2")
    _place(s, "pedro_ansurez", "bishop_1")
    assert not _available_bishops(s)
    assert not any(m["type"] == "cap_bishoprics" for m in legal_moves(s))
    with pytest.raises(IllegalAction):
        _place(s, "garcia_ordonez", "bishop_1")


def test_removal_does_not_subtract_troops_for_ready_bishop_or_affect_jaca():
    s = _state()
    _deploy_bishoprics(s)
    _place(s)
    troops = {lid: deepcopy(l.forces) for lid, l in s.lords.items()}
    jaca = s.lords["sancho"].model_dump()
    _remove_bishops(s)
    assert troops == {lid: l.forces for lid, l in s.lords.items()}
    assert s.lords["sancho"].model_dump() == jaca
    assert not s.meta.aow_cap_state.get("C22_bishops")
    assert not any(v.id.startswith("bishop_") for l in s.lords.values() for v in l.vassals)


@pytest.mark.parametrize("boundary", ["winter", "campaign"])
def test_discard_removes_mustered_units_and_reacquisition_has_three_markers(boundary):
    s = _state()
    _deploy_bishoprics(s)
    _place(s, bishop="bishop_2")
    lord = s.lords["alfonso"]
    before = deepcopy(lord.forces)
    apply_action(s, {"type": "levy_take_vassal", "side": "christian", "lord_id": lord.id,
                     "vassal_index": len(lord.vassals) - 1})
    if boundary == "winter":
        lord.cylinder = Cylinder(kind="locale", locale_id="toledo")
        for m in s.calendar.service_markers:
            m.box = 9
        s.calendar.current_box = 7
        winter_disband(s)
    else:
        # One on-map Christian Lord, two edge cards: the last (C22) is discarded.
        for other in s.lords.values():
            if other.side == "christian" and other.id != lord.id:
                other.cylinder = Cylinder(kind="calendar", box=10)
        s.decks.board_edge["christian"] = ["C21", "C22"]
        _apply_capability_discard(s)
    assert {u: n for u, n in lord.forces.items() if n} == {u: n for u, n in before.items() if n}
    assert "C22" not in s.decks.board_edge["christian"]
    assert not any(c.card_id == "C22" for c in s.decks.capabilities_in_play)
    assert not any(v.id.startswith("bishop_") for l in s.lords.values() for v in l.vassals)
    assert not s.meta.aow_cap_state.get("C22_bishops")
    assert _available_bishops(s) == ["bishop_1", "bishop_2", "bishop_3"]
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    _deploy_bishoprics(s)
    _place(s, bishop="bishop_2")
    assert lord.vassals[-1].id == "bishop_2" and lord.vassals[-1].ready


def test_bishop_unit_removal_after_losses_never_negative_and_is_idempotent():
    s = _state()
    _deploy_bishoprics(s)
    _place(s, bishop="bishop_2")
    lord = s.lords["alfonso"]
    lord.vassals[-1].ready = False
    lord.forces = {"knights": 0, "men_at_arms": 0}
    lord.routed_units = {"knights": 1}
    _remove_bishops(s)
    assert all(n >= 0 for n in lord.forces.values())
    assert lord.routed_units["knights"] == 0
    snapshot = s.model_dump()
    _remove_bishops(s)
    assert s.model_dump() == snapshot


def test_disbanded_bishop_becomes_available_without_waiting_for_card_discard():
    s = _state()
    _deploy_bishoprics(s)
    _place(s, bishop="bishop_2")
    s.meta.levy_step = "service_disband"
    next(m for m in s.calendar.service_markers if m.lord_id == "alfonso").box = 1
    apply_action(s, {"type": "disband_lord", "side": "christian", "lord_id": "alfonso"})
    _place(s, "alvar_fanez", "bishop_2")
    assert s.meta.aow_cap_state["C22_bishops"] == ["alvar_fanez"]
