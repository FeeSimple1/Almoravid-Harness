"""Scope, lifetime and player-choice coverage for the seed-137 repairs.

Authority: Rules 3.3, 3.4.4, 4.0, 4.9.4, 6.3.1; Arts of War C18/C20/M15/M20.
Saved live-game positions are tested separately. These small constructed boards
isolate additional boundaries and invalid-action atomicity.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from almoravid.actions import IllegalAction, _rebuild_aow_deck, _unused_capability_cards, apply_action
from almoravid.campaign import (
    _apply_capability_discard, _apply_one_wastage, _apply_wastage, winter_disband,
)
from almoravid.capabilities import (
    MUSLIM_TAIFA_SIX, capability_eligible_lords, discard_capability,
    lord_has_capability, side_has_capability,
)
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, GameState
from almoravid.static_data import load_cards

TROOP_CARDS = [("M15", "cap_saqalibah", "men_at_arms"),
               ("M20", "cap_al_rum", "knights")]


def muster_state():
    s = load_scenario("scenario_a_toledo_beset", seed=137)
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "muslim"
    s.lords["al_mutamid"].assets["coin"] = 4
    return s


def acquire(s, cid, owner="al_mutamid"):
    return apply_action(s, {"type": "levy_take_capability", "side": "muslim",
                            "lord_id": owner, "card_id": cid})


def deploy_edge(s, side, cards):
    s.decks.board_edge[side] = list(cards)
    for cid in cards:
        s.decks.capabilities_in_play.append(CardInPlay(
            card_id=cid, scope="side_wide", owner_side=side))


def campaign_excess():
    s = muster_state()
    for lid, lord in s.lords.items():
        if lid not in ("alfonso", "al_mutamid"):
            lord.cylinder = Cylinder(kind="calendar", box=9)
    deploy_edge(s, "christian", ["C22", "C18", "C20"])
    deploy_edge(s, "muslim", ["M10", "M12", "M16"])
    s.meta.phase = "campaign"
    _apply_capability_discard(s)
    return s


def assert_rejected_unchanged(s, action):
    before = s.model_dump(mode="json")
    with pytest.raises(IllegalAction):
        apply_action(s, action)
    assert s.model_dump(mode="json") == before


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
def test_acquisition_and_menu_are_personal(cid, action, unit):
    s = muster_state()
    before = s.lords["al_mutamid"].forces.get(unit, 0)
    acquire(s, cid)
    assert load_cards()["cards"][cid]["capability_scope"] == "this_lord"
    assert capability_eligible_lords(cid) == MUSLIM_TAIFA_SIX
    assert lord_has_capability(s, "al_mutamid", cid)
    assert not side_has_capability(s, "muslim", cid)
    record = next(c for c in s.decks.capabilities_in_play if c.card_id == cid)
    assert record.scope == "this_lord" and record.owner_lord_id == "al_mutamid"
    choices = [m for m in legal_moves(s) if m["type"] == action]
    assert choices == [{"type": action, "side": "muslim", "lord_id": "al_mutamid"}]
    apply_action(s, choices[0])
    assert s.lords["al_mutamid"].forces.get(unit, 0) == before + 2
    assert_rejected_unchanged(s, choices[0])


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
def test_nonowner_cannot_use_personal_troop_card(cid, action, unit):
    s = muster_state()
    acquire(s, cid)
    assert_rejected_unchanged(s, {"type": action, "side": "muslim", "lord_id": "al_mustain"})


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
@pytest.mark.parametrize("owner", ["yusuf", "sir", "rodrigo_al_sayyid"])
def test_non_taifa_lords_cannot_levy_troop_cards(cid, action, unit, owner):
    s = muster_state()
    s.lords[owner].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    assert_rejected_unchanged(s, {"type": "levy_take_capability", "side": "muslim",
                                  "lord_id": owner, "card_id": cid})
    assert not any(m.get("card_id") == cid and m.get("lord_id") == owner
                   for m in legal_moves(s))


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
def test_troop_card_counts_toward_two_personal_capability_limit(cid, action, unit):
    s = muster_state()
    acquire(s, "M1")
    acquire(s, "M2")
    s.lords["al_mutamid"].lordship_used = 0
    assert_rejected_unchanged(s, {"type": "levy_take_capability", "side": "muslim",
                                  "lord_id": "al_mutamid", "card_id": cid})


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
def test_drawn_troop_card_uses_same_scope_and_eligibility(cid, action, unit):
    s = muster_state()
    s.meta.levy_step = "arts_of_war"
    s.meta.first_levy_done = False
    s.decks.pending_draw["muslim"] = [cid]
    apply_action(s, {"type": "aow_deploy_capability", "side": "muslim",
                     "card_id": cid, "lord_id": "al_mutamid"})
    assert lord_has_capability(s, "al_mutamid", cid)
    assert cid not in s.decks.board_edge.get("muslim", [])


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
@pytest.mark.parametrize("boundary", ["wastage", "legacy_wastage", "winter", "at_limit", "beyond_limit"])
def test_discard_clears_contingent_and_allows_new_holder(cid, action, unit, boundary):
    s = muster_state()
    acquire(s, cid)
    before = s.lords["al_mutamid"].forces.get(unit, 0)
    apply_action(s, {"type": action, "side": "muslim", "lord_id": "al_mutamid"})
    if boundary == "wastage":
        _apply_one_wastage(s, "al_mutamid", {"capability": cid})
        assert s.lords["al_mutamid"].forces.get(unit, 0) == before
    elif boundary == "legacy_wastage":
        acquire(s, "M1")
        s.lords["al_mutamid"].assets = {}
        _apply_wastage(s)  # M15/M20 sorts after M1, deterministic legacy choice.
        assert s.lords["al_mutamid"].forces.get(unit, 0) == before
    elif boundary == "winter":
        s.calendar.current_box = 7
        for marker in s.calendar.service_markers:
            marker.box = 9
        winter_disband(s)
    else:
        s.meta.levy_step = "service_disband"
        s.calendar.current_box = 2
        for marker in s.calendar.service_markers:
            if marker.lord_id == "al_mutamid":
                marker.box = 2 if boundary == "at_limit" else 1
        apply_action(s, {"type": "disband_lord", "side": "muslim", "lord_id": "al_mutamid"})
    assert not s.meta.aow_cap_state.get(cid + "_used")
    assert cid + "_units" not in s.meta.aow_cap_state
    assert not any(c.card_id == cid for c in s.decks.capabilities_in_play)
    assert cid in s.decks.discard
    assert cid not in s.decks.board_edge.get("muslim", [])
    # New acquisition by a different Taifa Lord is a new one-time benefit.
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "muslim"
    s.pending = None
    lord = s.lords["al_mustain"]
    lord.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    lord.lordship_used = 0
    lord.assets["coin"] = 3
    start = lord.forces.get(unit, 0)
    acquire(s, cid, owner=lord.id)
    apply_action(s, {"type": action, "side": "muslim", "lord_id": lord.id})
    assert lord.forces.get(unit, 0) == start + 2


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
def test_winter_keeps_siege_lords_personal_card_and_used_status(cid, action, unit):
    s = muster_state()
    acquire(s, cid)
    apply_action(s, {"type": action, "side": "muslim", "lord_id": "al_mutamid"})
    lord = s.lords["al_mutamid"]
    s.locales[lord.cylinder.locale_id].siege_green = 1
    s.calendar.current_box = 7
    for marker in s.calendar.service_markers:
        marker.box = 9
    before = deepcopy(lord.forces)
    winter_disband(s)
    assert lord_has_capability(s, lord.id, cid)
    assert s.meta.aow_cap_state[cid + "_used"] is True
    assert lord.forces == before


@pytest.mark.parametrize("cid,action,unit", TROOP_CARDS)
@pytest.mark.parametrize("used", [True, False])
def test_discard_is_idempotent_and_does_not_remove_unrecruited_units(cid, action, unit, used):
    s = muster_state()
    acquire(s, cid)
    if used:
        apply_action(s, {"type": action, "side": "muslim", "lord_id": "al_mutamid"})
        s.lords["al_mutamid"].forces[unit] = 1  # partial casualties
    before = deepcopy(s.lords["al_mutamid"].forces)
    discard_capability(s, cid)
    expected = deepcopy(before)
    if used:
        expected[unit] = 0
    assert s.lords["al_mutamid"].forces == expected
    after = s.model_dump(mode="json")
    discard_capability(s, cid)
    assert s.model_dump(mode="json") == after
    assert s.decks.discard.count(cid) == 1


def test_excess_choices_are_christian_first_and_every_card_is_selectable():
    s = campaign_excess()
    assert s.meta.campaign_step == "capability_discard"
    assert s.pending.waiting_on == s.meta.active_player == "christian"
    assert s.pending.payload["discard_required"] == 2
    assert s.decks.board_edge["christian"] == ["C22", "C18", "C20"]
    choices = [m for m in legal_moves(s) if m["type"] == "discard_capabilities"]
    assert {m["card_ids"][0] for m in choices} == {"C22", "C18", "C20"}
    for move in choices:
        apply_action(s.model_copy(deep=True), move)
    # Deliberately keep the last card, not the first.
    apply_action(s, {"type": "discard_capabilities", "side": "christian", "card_ids": ["C22"]})
    assert s.pending.waiting_on == "christian" and s.pending.payload["discard_required"] == 1
    apply_action(s, {"type": "discard_capabilities", "side": "christian", "card_ids": ["C18"]})
    assert s.decks.board_edge["christian"] == ["C20"]
    assert s.pending.waiting_on == s.meta.active_player == "muslim"
    apply_action(s, {"type": "discard_capabilities", "side": "muslim", "card_ids": ["M10", "M12"]})
    assert s.decks.board_edge["muslim"] == ["M16"]
    assert s.pending is None and s.meta.campaign_step == "plan"
    assert s.meta.active_player == "christian"
    apply_action(s, {"type": "plan_add_card", "side": "christian", "lord_id": "alfonso"})


@pytest.mark.parametrize("cards", [[], "C22", [1], ["C22", "C22"], ["M10"], ["C7"],
                                   ["C22", "C18", "C20"], ["C22", "not-a-card"]])
def test_invalid_discard_selections_are_atomic(cards):
    s = campaign_excess()
    assert_rejected_unchanged(s, {"type": "discard_capabilities", "side": "christian", "card_ids": cards})


@pytest.mark.parametrize("action", [
    {"type": "plan_add_card", "side": "christian", "lord_id": "alfonso"},
    {"type": "finalize_plan", "side": "christian"},
    {"type": "begin_campaign"},
    {"type": "end_campaign"},
    {"type": "cmd_pass", "side": "christian"},
    {"type": "discard_capabilities", "side": "muslim", "card_ids": ["M10"]},
])
def test_pending_discard_cannot_be_bypassed(action):
    assert_rejected_unchanged(campaign_excess(), action)


def test_choice_roundtrip_persists_exactly_and_keeps_personal_cards():
    s = campaign_excess()
    s.lords["al_mutamid"].capabilities = ["M15", "M20"]
    restored = GameState.model_validate_json(s.model_dump_json())
    actions = [
        {"type": "discard_capabilities", "side": "christian", "card_ids": ["C22", "C20"]},
        {"type": "discard_capabilities", "side": "muslim", "card_ids": ["M10", "M16"]},
    ]
    for a in actions:
        apply_action(s, a)
        apply_action(restored, a)
    assert restored == s
    assert s.lords["al_mutamid"].capabilities == ["M15", "M20"]
    assert s.decks.board_edge["christian"] == ["C18"]
    assert "C18" not in s.decks.removed_from_game


@pytest.mark.parametrize("boundary", ["campaign", "winter"])
def test_milites_removal_is_permanent_but_its_units_stay(boundary):
    s = campaign_excess()
    lord = s.lords["alfonso"]
    lord.forces["light_horse"] = 3
    before = deepcopy(lord.forces)
    if boundary == "campaign":
        apply_action(s, {"type": "discard_capabilities", "side": "christian", "card_ids": ["C18"]})
    else:
        s.pending = None
        s.calendar.current_box = 7
        s.locales[lord.cylinder.locale_id].siege_yellow = 1
        for marker in s.calendar.service_markers:
            marker.box = 9
        winter_disband(s)
    assert lord.forces == before
    assert "C18" in s.decks.removed_from_game and "C18" not in s.decks.discard
    _rebuild_aow_deck(s, "christian")
    assert "C18" not in s.decks.draw
    assert "C18" not in _unused_capability_cards(s, "christian")


@pytest.mark.parametrize("owner", ["sancho", "eudes", "pedro_ansurez", "garcia_ordonez",
                                   "alvar_fanez", "rodrigo_campeador"])
def test_fueros_only_alfonso_can_levy(owner):
    s = muster_state()
    s.meta.active_player = "christian"
    s.lords[owner].cylinder = Cylinder(kind="locale", locale_id="leon")
    assert_rejected_unchanged(s, {"type": "levy_take_capability", "side": "christian",
                                  "lord_id": owner, "card_id": "C20"})


def fueros_state():
    s = muster_state()
    s.meta.active_player = "christian"
    s.taifas["toledo"].status = "reconquista"
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.locales["toledo"].jihad_markers = 2
    s.locales["toledo"].siege_yellow = 0
    deploy_edge(s, "christian", ["C20"])
    return s


@pytest.mark.parametrize("step", ["arts_of_war", "pay", "service_disband", "muster", "call_to_arms"])
def test_fueros_is_a_free_once_per_levy_choice(step):
    s = fueros_state()
    s.meta.levy_step = step
    choices = [m for m in legal_moves(s) if m["type"] == "cap_fueros" and m["target_locale"] == "toledo"]
    assert {m["count"] for m in choices} == {1, 2}
    used = s.lords["alfonso"].lordship_used
    apply_action(s, {"type": "cap_fueros", "side": "christian", "target_locale": "toledo", "count": 1})
    assert s.locales["toledo"].jihad_markers == 1
    assert s.lords["alfonso"].lordship_used == used
    assert_rejected_unchanged(s, {"type": "cap_fueros", "side": "christian", "target_locale": "toledo"})
    s.meta.turn_index += 1
    assert any(m["type"] == "cap_fueros" for m in legal_moves(s))


@pytest.mark.parametrize("phase", ["campaign", "winter", "ended"])
def test_fueros_not_usable_outside_levy(phase):
    s = fueros_state()
    s.meta.phase = phase
    s.meta.campaign_step = "activation"
    s.meta.active_lord_id = "alfonso"
    assert_rejected_unchanged(s, {"type": "cap_fueros", "side": "christian", "target_locale": "toledo"})
    assert not any(m["type"] == "cap_fueros" for m in legal_moves(s))
