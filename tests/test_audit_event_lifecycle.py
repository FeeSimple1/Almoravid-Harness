"""Audit 06-08/22-24: paid, tracked and correctly scoped Event effects."""
import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.capabilities import side_has_capability
from almoravid.effective import effective_lordship
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker
from almoravid.static_data import load_lords


def _state(side="christian"):
    state = load_scenario("scenario_a_toledo_beset", seed=8)
    state.meta.phase = "levy"
    state.meta.levy_step = "muster"
    state.meta.active_player = side
    return state


def _sancho(state, assets):
    lord = state.lords["sancho"]
    lord.cylinder = Cylinder(kind="locale", locale_id="leon")
    lord.forces = {"knights": 1, "men_at_arms": 1}
    lord.assets = assets
    lord.capabilities = []
    lord.in_stronghold = False
    lord.just_arrived_this_levy = False
    return lord


def test_count_event_without_payment_gives_no_units_or_capability():
    state = _state()
    lord = _sancho(state, {})
    before = dict(lord.forces)
    result = resolve_event(state, "christian", "C13", {"target_lord_id": lord.id})
    assert result["no_op"]
    assert lord.forces == before
    assert "C13" not in lord.capabilities
    assert state.meta.count_of_barcelona_side is None


def test_paid_count_event_tracks_attached_units_and_enemy_event_removes_them():
    state = _state()
    lord = _sancho(state, {})
    donor = state.lords["alfonso"]
    donor.cylinder = Cylinder(kind="locale", locale_id="leon")
    donor.assets = {"mule": 1}
    resolve_event(state, "christian", "C13", {
        "target_lord_id": lord.id, "asset": "mule", "payer_lord_id": donor.id})
    assert donor.assets == {}
    assert lord.capabilities == ["C13"]
    assert lord.forces == {"knights": 3, "men_at_arms": 3}
    assert "C13" not in state.decks.discard
    assert state.meta.aow_cap_state["C13_used"]
    assert state.meta.count_of_barcelona_side == "christian"
    resolve_event(state, "muslim", "M23", {"target_lord_id": "al_mustain"})
    assert lord.forces == {"knights": 1, "men_at_arms": 1}
    assert lord.capabilities == []
    assert not any(c.card_id == "C13" for c in state.decks.capabilities_in_play)
    assert "C13" in state.decks.discard
    assert "C13_units" not in state.meta.aow_cap_state
    assert state.meta.count_of_barcelona_side is None


def test_normal_count_levy_only_holder_can_buy_units_then_wastage_removes_them():
    from almoravid.campaign import _apply_one_wastage
    state = _state()
    lord = _sancho(state, {"coin": 3})
    apply_action(state, {"type": "levy_take_capability", "side": "christian",
                         "lord_id": lord.id, "card_id": "C13"})
    eudes = state.lords["eudes"]
    eudes.cylinder = Cylinder(kind="locale", locale_id="leon")
    eudes.assets = {"coin": 3}
    with pytest.raises(IllegalAction):
        apply_action(state, {"type": "cap_count_barcelona", "side": "christian",
                             "lord_id": eudes.id})
    apply_action(state, {"type": "cap_count_barcelona", "side": "christian",
                         "lord_id": lord.id})
    assert lord.assets["coin"] == 1
    assert lord.forces["knights"] == 3
    _apply_one_wastage(state, lord.id, {"capability": "C13"})
    assert lord.forces == {"knights": 1, "men_at_arms": 1}
    assert state.meta.count_of_barcelona_side is None


@pytest.mark.parametrize("card,lord_id,side", [
    ("C14", "sancho", "christian"), ("C15", "sancho", "christian"),
    ("C16", "sancho", "christian"), ("M21", "al_mustain", "muslim"),
    ("M22", "al_mustain", "muslim"),
])
def test_event_muster_sets_service_vassals_and_muster_segment_restriction(card, lord_id, side):
    state = _state(side)
    lord = state.lords[lord_id]
    lord.cylinder = Cylinder(kind="calendar", box=8)
    lord.vassals = []
    state.calendar.service_markers = [m for m in state.calendar.service_markers
                                      if m.lord_id != lord_id]
    if card in ("C14", "C15"):
        state.decks.held.setdefault(side, []).append(card)
        apply_action(state, {"type": "play_pope_gregory" if card == "C14" else "play_cluniacs",
                             "side": side, "lord_id": lord_id, "mode": "muster_from_calendar"})
    else:
        state.lords["eudes"].cylinder = Cylinder(kind="locale", locale_id="leon")
        resolve_event(state, side, card, {"lord_id": lord_id, "mode": "muster"})
    assert lord.cylinder.kind == "locale"
    own_markers = [m for m in state.calendar.service_markers if m.lord_id == lord_id
                   and m.vassal_id is None]
    assert len(own_markers) == 1
    assert own_markers[0].box == state.calendar.current_box + lord.service_rating
    assert len(lord.vassals) == len(load_lords()["lords"][lord_id]["vassals"])
    assert lord.just_arrived_this_levy
    if card == "C16":
        assert side_has_capability(state, "christian", "C16")
        assert "C16" in state.decks.board_edge["christian"]
        assert "C16" not in state.decks.discard


@pytest.mark.parametrize("card,lord_id,side", [
    ("C14", "sancho", "christian"), ("C15", "alfonso", "christian"),
    ("M12", "al_mutamid", "muslim"),
])
def test_lordship_bonus_adds_actions_then_expires_on_real_end_campaign(card, lord_id, side):
    state = _state(side)
    lord = state.lords[lord_id]
    lord.cylinder = Cylinder(kind="locale", locale_id="leon" if side == "christian" else "sevilla")
    lord.in_stronghold = False
    base = lord.lordship_rating
    lord.lordship_used = base
    state.decks.held.setdefault(side, []).append(card)
    if card == "M12":
        apply_action(state, {"type": "play_event", "side": side, "card_id": card,
                             "payload": {"mode": "lordship", "lord_id": lord_id}})
    else:
        apply_action(state, {"type": "play_pope_gregory" if card == "C14" else "play_cluniacs",
                             "side": side, "lord_id": lord_id, "mode": "lordship_plus_2"})
    assert lord.lordship_rating == base
    assert effective_lordship(state, lord_id) == base + 2
    apply_action(state, {"type": "levy_transport", "side": side, "lord_id": lord_id,
                         "transport": "mule"})
    assert lord.lordship_used == base + 1
    # Remove Wastage choices so the real phase-ending action can finish.
    for each in state.lords.values():
        each.assets = {}
        each.capabilities = []
    state.meta.phase = "campaign"
    state.meta.campaign_step = "end_campaign"
    apply_action(state, {"type": "end_campaign"})
    assert state.meta.phase == "levy"
    assert effective_lordship(state, lord_id) == base
    assert lord.lordship_bonus_this_levy == 0
    assert lord.lordship_used == 0


def test_christian_freebooter_performs_full_at_limit_disband_not_removal():
    state = _state()
    lid = "rodrigo_al_sayyid"
    lord = state.lords[lid]
    lord.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    lord.forces = {"knights": 2}
    lord.assets = {"coin": 2}
    state.locales["zaragoza"].seat_marker_lord_ids.append(lid)
    state.calendar.service_markers.append(ServiceMarker(lord_id=lid, box=1))
    result = resolve_event(state, "christian", "C26")
    assert result["disbanded"] == lid
    assert lord.cylinder.kind == "calendar"
    assert lord.cylinder.box == state.calendar.current_box + lord.service_rating
    assert not lord.forces and not lord.assets
    assert not any(m.lord_id == lid for m in state.calendar.service_markers)
    assert lid not in state.locales["zaragoza"].seat_marker_lord_ids
    assert lid not in state.calendar.off_left_service


@pytest.mark.parametrize("card", ["M25", "M26"])
def test_muslim_freebooter_converts_rodrigo_already_on_calendar(card):
    state = _state("muslim")
    state.lords["rodrigo_campeador"].cylinder = Cylinder(kind="calendar", box=4)
    state.taifas_box_vp = 2
    result = resolve_event(state, "muslim", card, {"swap_to_al_sayyid": True})
    assert result["swapped_to_al_sayyid"]
    assert state.taifas_box_vp == 1
    assert state.lords["rodrigo_al_sayyid"].cylinder == Cylinder(kind="calendar", box=4)
    assert state.lords["rodrigo_campeador"].cylinder.kind == "set_aside"


def test_bernard_service_branch_compulsorily_installs_cathedrals():
    state = _state()
    before = next(m.box for m in state.calendar.service_markers if m.lord_id == "alfonso")
    result = resolve_event(state, "christian", "C16", {"lord_id": "alfonso"})
    assert result["new_service_box"] == before + 1
    assert side_has_capability(state, "christian", "C16")
    assert "C16" in state.decks.board_edge["christian"]
    assert "C16" not in state.lords["alfonso"].capabilities
    assert "C16" not in state.decks.discard
