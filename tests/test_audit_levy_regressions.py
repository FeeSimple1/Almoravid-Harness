"""Audit 03/18-21: full Muster mats, Lordship gates, and atomic choices."""
from __future__ import annotations

import pytest

from almoravid.actions import (
    IllegalAction,
    _disband_vassals_for_side,
    _initialize_mustered_lord,
    _rebuild_aow_deck,
    _unused_capability_cards,
    apply_action,
)
from almoravid.events import _jihad_eligible_locales
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker
from almoravid.static_data import load_lords


def _levy(step="muster", side="christian"):
    state = load_scenario("scenario_b_quelling_of_tajo", seed=2)
    state.meta.phase = "levy"
    state.meta.levy_step = step
    state.meta.active_player = side
    state.meta.levy_step_completed_christian = False
    state.meta.levy_step_completed_muslim = False
    return state


def _muster_garcia(state):
    state.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    garcia = state.lords["garcia_ordonez"]
    garcia.cylinder = Cylinder(kind="calendar", box=state.calendar.current_box)
    # Fix the die result through a legal guaranteed Fealty range; the
    # regression concerns the successful Muster's complete mat.
    garcia.fealty = 6
    result = apply_action(state, {
        "type": "muster_lord", "side": "christian",
        "lord_id": garcia.id, "levying_lord_id": "alfonso", "seat": "najera",
    })
    assert result["success"]
    return garcia


def test_normal_muster_places_printed_ready_vassals_and_base_forces():
    state = _levy()
    lord = _muster_garcia(state)
    printed = load_lords()["lords"][lord.id]
    assert len(lord.vassals) == len(printed["vassals"]) == 2
    assert all(v.ready and not v.pennant_down for v in lord.vassals)
    assert lord.forces == printed["forces"]
    assert lord.assets == printed["assets"]
    # On his next Muster segment the new markers actually recruit troops.
    lord.just_arrived_this_levy = False
    before = dict(lord.forces)
    apply_action(state, {"type": "levy_take_vassal", "side": "christian",
                         "lord_id": lord.id, "vassal_index": 0})
    for unit, count in lord.vassals[0].forces.items():
        assert lord.forces[unit] == before.get(unit, 0) + count


def test_call_for_crusade_initializes_eudes_vassals():
    state = _levy("call_to_arms")
    state.lords["eudes"].cylinder = Cylinder(
        kind="calendar", box=state.calendar.current_box)
    apply_action(state, {"type": "cta_call_crusade", "side": "christian"})
    lord = state.lords["eudes"]
    assert len(lord.vassals) == len(load_lords()["lords"]["eudes"]["vassals"])
    assert lord.vassals and all(v.ready for v in lord.vassals)


@pytest.mark.parametrize("action", [
    {"type": "levy_transport", "transport": "mule"},
    {"type": "levy_take_vassal", "vassal_index": 0},
    {"type": "levy_take_capability", "card_id": "C18"},
])
def test_newly_mustered_lord_cannot_spend_lordship(action):
    state = _levy()
    lord = _muster_garcia(state)
    before = state.model_dump()
    with pytest.raises(IllegalAction) as exc:
        apply_action(state, {**action, "side": "christian", "lord_id": lord.id})
    assert exc.value.code == "levier_just_arrived"
    assert state.model_dump() == before
    assert not any(move.get("lord_id") == lord.id and
                   move["type"] in ("levy_transport", "levy_take_vassal",
                                    "levy_take_capability")
                   for move in legal_moves(state))


def test_muster_before_segment_can_spend_lordship_when_segment_begins():
    state = _levy("arts_of_war")
    _initialize_mustered_lord(state, "garcia_ordonez", "najera")
    assert not state.lords["garcia_ordonez"].just_arrived_this_levy
    state.meta.levy_step = "muster"
    apply_action(state, {"type": "levy_transport", "side": "christian",
                         "lord_id": "garcia_ordonez", "transport": "mule"})


def test_removed_vassal_stays_removed_after_lord_disbands_and_remusters():
    state = _levy()
    state.meta.advanced_vassal_service = True
    lord = _muster_garcia(state)
    removed_id = lord.vassals[0].id
    state.calendar.service_markers.append(ServiceMarker(
        lord_id=lord.id, vassal_id=removed_id, box=state.calendar.current_box - 1))
    _disband_vassals_for_side(state, "christian")
    assert removed_id in lord.removed_vassal_ids
    apply_action(state, {"type": "disband_lord", "side": "christian",
                         "lord_id": lord.id, "auto_service_disband": True,
                         "force_at_service_limit": True})
    _initialize_mustered_lord(state, lord.id, "najera")
    assert removed_id not in [v.id for v in lord.vassals]
    assert len(lord.vassals) == 1


def test_removed_milites_neither_offered_nor_accepted():
    state = _levy()
    state.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    state.decks.removed_from_game.append("C18")
    assert "C18" not in _unused_capability_cards(state, "christian")
    assert not any(m["type"] == "levy_take_capability" and m["card_id"] == "C18"
                   for m in legal_moves(state))
    before = state.model_dump()
    with pytest.raises(IllegalAction) as exc:
        apply_action(state, {"type": "levy_take_capability", "side": "christian",
                             "lord_id": "alfonso", "card_id": "C18"})
    assert exc.value.code == "card_not_available"
    assert state.model_dump() == before


@pytest.mark.parametrize("available,accepted", [(1, False), (2, True)])
def test_employ_rodrigo_aggregates_duplicate_payers(available, accepted):
    state = _levy("call_to_arms")
    state.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    state.lords["alfonso"].assets["coin"] = available
    state.lords["rodrigo_campeador"].cylinder = Cylinder(
        kind="calendar", box=state.calendar.current_box)
    action = {"type": "cta_employ_rodrigo", "side": "christian", "seat": "leon",
              "payments": [{"lord_id": "alfonso", "coin": 1},
                           {"lord_id": "alfonso", "coin": 1}]}
    before = state.model_dump()
    if accepted:
        apply_action(state, action)
        assert state.lords["alfonso"].assets.get("coin", 0) == 0
        assert state.lords["rodrigo_campeador"].cylinder.locale_id == "leon"
    else:
        with pytest.raises(IllegalAction) as exc:
            apply_action(state, action)
        assert exc.value.code == "no_coin"
        assert state.model_dump() == before


def test_uphold_invalid_jihad_is_atomic_and_can_be_retried():
    state = _levy("call_to_arms", "muslim")
    for lid in ("yusuf", "sir"):
        state.lords[lid].cylinder = Cylinder(
            kind="calendar", box=state.calendar.current_box)
    targets = _jihad_eligible_locales(state)
    assert targets
    before = state.model_dump()
    action = {"type": "cta_uphold_dynasties", "side": "muslim",
              "jihad_locale": "not_a_locale"}
    with pytest.raises(IllegalAction) as exc:
        apply_action(state, action)
    assert exc.value.code == "bad_jihad_target"
    assert state.model_dump() == before
    apply_action(state, {**action, "jihad_locale": targets[0]})
    assert state.taifas_box_vp == before["taifas_box_vp"] + 1
    assert state.meta.cta_option_used_muslim


def test_invalid_muster_seat_does_not_spend_lordship_or_rng():
    state = _levy()
    state.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    before = state.model_dump()
    with pytest.raises(IllegalAction) as exc:
        apply_action(state, {"type": "muster_lord", "side": "christian",
                             "lord_id": "garcia_ordonez",
                             "levying_lord_id": "alfonso", "seat": "not_a_seat"})
    assert exc.value.code == "bad_seat"
    assert state.model_dump() == before


@pytest.mark.parametrize("card_id,lord_id,scope", [
    ("C13", "sancho", "this_lord"), ("C18", "alfonso", "side_wide"),
])
def test_levying_discarded_capability_moves_it_out_of_unused_piles(card_id, lord_id, scope):
    state = _levy()
    state.lords[lord_id].cylinder = Cylinder(kind="locale", locale_id="leon")
    state.decks.discard = [card_id, "M25"]
    state.decks.draw = [card_id, "C25"]
    result = apply_action(state, {"type": "levy_take_capability", "side": "christian",
                                 "lord_id": lord_id, "card_id": card_id})
    assert result["scope"] == scope
    assert state.decks.discard == ["M25"]
    assert state.decks.draw == ["C25"]
    destination = (state.lords[lord_id].capabilities if scope == "this_lord"
                   else state.decks.board_edge["christian"])
    assert destination.count(card_id) == 1
    assert sum(c.card_id == card_id for c in state.decks.capabilities_in_play) == 1


def test_shuffle_recycles_own_discards_once_and_preserves_opponent_pile():
    from almoravid.campaign import _card_available_in_deck
    state = _levy("arts_of_war")
    state.decks.discard = ["C25", "C25", "M25"]
    assert not _card_available_in_deck(state, "christian", "C25")
    _rebuild_aow_deck(state, "christian")
    assert state.decks.draw.count("C25") == 1
    assert state.decks.discard == ["M25"]
    assert _card_available_in_deck(state, "christian", "C25")
    _rebuild_aow_deck(state, "muslim")
    assert state.decks.draw.count("M25") == 1
    assert not state.decks.discard


@pytest.mark.parametrize("lord_id,expected", [("sancho", "this_lord:sancho"),
                                              (None, "unassigned_discarded")])
def test_first_levy_deploy_routes_pending_card_to_one_destination(lord_id, expected):
    state = _levy("arts_of_war")
    state.lords["sancho"].cylinder = Cylinder(kind="locale", locale_id="leon")
    state.decks.pending_draw["christian"] = ["C13"]
    # Old saves could retain a recycled card in draw and/or discard.
    state.decks.draw = ["C13", "C25"]
    state.decks.discard = ["C13", "M25"]
    result = apply_action(state, {"type": "aow_deploy_capability", "side": "christian",
                                 "card_id": "C13", "lord_id": lord_id})
    assert result["deployed"] == expected
    assert "C13" not in state.decks.pending_draw["christian"]
    assert state.decks.draw == ["C25"]
    assert "M25" in state.decks.discard
    assert state.decks.discard.count("C13") == (0 if lord_id else 1)
    assert state.lords["sancho"].capabilities.count("C13") == (1 if lord_id else 0)
