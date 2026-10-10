"""Rules regressions from the Scenario D / seed 42 playtest, 2026-10-10.

Sources: Rules 1.3.1 and 3.4; Scenario D First Levy and setup; Arts of War
C20 Al-Qadir, C21 Sisnando Davidez, C24 Abu Bakr ibn Umar, M10/M12/M16.
Tests build fresh states: old saves with missing setup cards are not migrated.
"""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import (
    _apply_capability_discard,
    _conquer_stronghold,
    _muster_cap_lord_eligible,
    _transport_for_lords,
    compute_final_vp,
)
from almoravid.capabilities import side_has_capability
from almoravid.effective import is_friendly_locale, muster_ineligibility
from almoravid.events import al_qadir_choices, resolve_event
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, GameState
from almoravid.static_data import load_cards
from tests._plan_helpers import step_levy


def first_muster(side="christian"):
    """Reach the real Scenario D first Muster without changing board pieces."""
    s = load_scenario("scenario_d_arrival", seed=42)
    apply_action(s, {"type": "begin_levy"})
    for _ in range(80):
        if s.meta.levy_step == "muster" and s.meta.active_player == side:
            return s
        step_levy(s)
    raise AssertionError("Muster was not reached")


def activate(s, side="muslim", lord="yusuf"):
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = side
    s.meta.active_lord_id = lord
    s.meta.actions_remaining = 3


@pytest.mark.parametrize("side,lord", [("christian", "alfonso"), ("muslim", "al_mustain")])
@pytest.mark.parametrize("action", [
    {"type": "levy_take_vassal", "vassal_index": 0},
    {"type": "levy_transport", "transport": "mule"},
])
def test_first_muster_exception_is_legal_and_spends_lordship(side, lord, action):
    s = first_muster(side)
    move = {**action, "side": side, "lord_id": lord}
    assert move in legal_moves(s)
    assert _muster_cap_lord_eligible(s, lord, side)
    used = s.lords[lord].lordship_used
    assert apply_action(s, move)["lordship_used"] == used + 1


@pytest.mark.parametrize("side,lord", [("christian", "alfonso"), ("muslim", "al_mustain")])
@pytest.mark.parametrize("restriction", ["later_levy", "different_scenario", "event_ban", "newly_arrived"])
def test_first_muster_exception_has_limits(side, lord, restriction):
    s = first_muster(side)
    if restriction == "later_levy":
        s.meta.first_levy_done = True
    elif restriction == "different_scenario":
        s.meta.scenario_letter = "C"
    elif restriction == "event_ban":
        s.meta.muster_banned_this_levy_lord_ids.append(lord)
    else:
        s.lords[lord].just_arrived_this_levy = True
    move = {"type": "levy_transport", "side": side, "lord_id": lord, "transport": "mule"}
    assert move not in legal_moves(s)
    assert not _muster_cap_lord_eligible(s, lord, side)
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(s, move)
    assert s.model_dump() == before


@pytest.mark.parametrize("card", ["M10", "M12", "M16"])
def test_starting_board_edge_cards_are_active_once_and_survive_save_load(card):
    s = load_scenario("scenario_d_arrival", seed=42)
    for state in (s, GameState.model_validate_json(s.model_dump_json())):
        assert side_has_capability(state, "muslim", card)
        matches = [c for c in state.decks.capabilities_in_play if c.card_id == card]
        assert len(matches) == 1
        assert matches[0].owner_lord_id is None
        assert matches[0].scope == "side_wide"
        assert state.decks.board_edge["muslim"].count(card) == 1


def test_yusuf_receives_two_provender_from_starting_double_seat():
    s = load_scenario("scenario_d_arrival", seed=42)
    activate(s)
    before = s.lords["yusuf"].assets.get("prov", 0)
    result = apply_action(s, {"type": "cmd_supply", "side": "muslim", "source_seat": "algeciras"})
    assert result["prov_gained"] == 2
    assert s.lords["yusuf"].assets["prov"] == before + 2


def test_starting_camels_double_only_almoravid_mules():
    s = load_scenario("scenario_d_arrival", seed=42)
    for lid in ("yusuf", "sir", "al_mutamid"):
        s.lords[lid].assets = {"cart": 1, "mule": 2}
    assert _transport_for_lords(s, ["yusuf", "sir", "al_mutamid"]) == (3, 10)


@pytest.mark.parametrize("card", ["M10", "M12", "M16"])
def test_starting_board_edge_card_discard_removes_its_effect(card):
    s = load_scenario("scenario_d_arrival", seed=42)
    # Leave two Muslim Lords: at Campaign start exactly one of the three
    # board-edge cards must be discarded. The player selects this card.
    for lid, lord in s.lords.items():
        if lord.side == "muslim" and lid not in ("yusuf", "al_mutamid"):
            lord.cylinder = Cylinder(kind="calendar", box=16)
    s.decks.board_edge["muslim"] = [c for c in s.decks.board_edge["muslim"] if c != card] + [card]
    s.meta.phase = "campaign"
    _apply_capability_discard(s)
    apply_action(s, {"type": "discard_capabilities", "side": "muslim",
                     "card_ids": [card]})
    assert not side_has_capability(s, "muslim", card)
    assert card not in s.decks.board_edge["muslim"]
    if card == "M12":
        activate(s)
        assert apply_action(s, {"type": "cmd_supply", "side": "muslim",
                                "source_seat": "algeciras"})["prov_gained"] == 1


@pytest.mark.parametrize("side,locale,territory_status,conquered,jihad", [
    ("muslim", "aledo", "independent", 1, 0),
    ("christian", "jaca", None, 1, 0),
    ("christian", "ucles", "reconquista", 0, 2),
])
def test_friendly_territory_recapture_removes_enemy_markers_and_vp(side, locale, territory_status, conquered, jihad):
    s = load_scenario("scenario_d_arrival", seed=42)
    loc = s.locales[locale]
    if territory_status:
        s.taifas[loc.territory].status = territory_status
    loc.conquered_markers = conquered
    loc.jihad_markers = jihad
    loc.ravaged = "none"
    loc.seat_marker_lord_ids = ["alfonso" if side == "muslim" else "yusuf"]
    s.score.christian, s.score.muslim = compute_final_vp(s)
    before = (s.score.christian, s.score.muslim)
    result = _conquer_stronghold(s, locale, side)
    assert result["marker"] == "removed"
    assert result["vp_delta"] == 0
    assert loc.conquered_markers == loc.jihad_markers == 0
    assert loc.seat_marker_lord_ids == []
    assert is_friendly_locale(s, locale, side)
    assert not is_friendly_locale(s, locale, "christian" if side == "muslim" else "muslim")
    assert (s.score.christian, s.score.muslim) == compute_final_vp(s)
    enemy_index = 0 if side == "muslim" else 1
    assert compute_final_vp(s)[enemy_index] == before[enemy_index] - conquered - jihad * 0.5


def test_recapture_removes_cathedral_even_in_independent_taifa():
    s = load_scenario("scenario_d_arrival", seed=42)
    s.taifas["sevilla"].status = "independent"
    loc = s.locales["sevilla"]
    loc.conquered_markers = 3
    loc.seat_marker_lord_ids = ["alfonso"]
    s.cathedral_seat_locales = ["sevilla"]
    _conquer_stronghold(s, "sevilla", "muslim")
    assert not s.cathedral_seat_locales
    assert loc.conquered_markers == 0
    assert not loc.seat_marker_lord_ids


@pytest.mark.parametrize("status,side,marker", [
    ("independent", "christian", "conquered"),
    ("parias", "christian", "conquered"),
    ("parias", "muslim", "jihad"),
    ("reconquista", "muslim", "jihad"),
])
def test_enemy_or_neutral_conquest_places_correct_markers_without_double_scoring(status, side, marker):
    s = load_scenario("scenario_d_arrival", seed=42)
    s.taifas["toledo"].status = status
    loc = s.locales["ucles"]
    loc.conquered_markers = loc.jihad_markers = 0
    loc.ravaged = "none"
    s.score.christian, s.score.muslim = compute_final_vp(s)
    result = _conquer_stronghold(s, "ucles", side)
    assert result["marker"] == marker
    assert (s.score.christian, s.score.muslim) == compute_final_vp(s)
    before = (s.score.christian, s.score.muslim)
    _conquer_stronghold(s, "ucles", side)
    assert (s.score.christian, s.score.muslim) == before


def qadir_position():
    s = load_scenario("scenario_d_arrival", seed=42)
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    s.decks.held.setdefault("christian", []).append("C20")
    for loc in s.locales.values():
        loc.jihad_markers = 0
    s.locales["ucles"].jihad_markers = 2
    s.locales["calatrava"].jihad_markers = 3
    s.locales["trujillo"].jihad_markers = 1
    return s


@pytest.mark.parametrize("selection", [["ucles", "ucles"], ["ucles", "calatrava"], ["trujillo", "calatrava"]])
def test_qadir_honors_selected_markers_and_changes_no_others(selection):
    s = qadir_position()
    move = {"type": "play_event", "side": "christian", "card_id": "C20",
            "payload": {"locale_ids": sorted(selection)}}
    assert move in legal_moves(s)
    before = {lid: loc.jihad_markers for lid, loc in s.locales.items()}
    score_before = s.score.muslim
    result = apply_action(s, move)
    for lid, count in before.items():
        assert s.locales[lid].jihad_markers == count - selection.count(lid)
    assert result["jihad_removed"] == 2
    assert s.score.muslim == score_before - 1
    assert "C20" not in s.decks.held["christian"]
    assert s.decks.discard.count("C20") == 1


@pytest.mark.parametrize("payload", [{}, {"locale_ids": []}, {"locale_ids": ["missing", "ucles"]},
    {"locale_ids": ["trujillo", "trujillo"]}, {"locale_ids": ["ucles"]},
    {"locale_ids": ["ucles", "ucles", "ucles"]}, {"locale_ids": "ucles"},
    {"locale_ids": [1, 2]}, {"locale_ids": [["ucles"]]},
    {"locale_ids": ["ucles", "ucles"], "locale_id": "ucles"}])
def test_qadir_rejects_missing_or_invalid_selection_atomically(payload):
    s = qadir_position()
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "play_event", "side": "christian", "card_id": "C20", "payload": payload})
    assert s.model_dump() == before


def test_qadir_shorthand_and_single_remaining_marker():
    s = qadir_position()
    apply_action(s, {"type": "play_event", "side": "christian", "card_id": "C20",
                     "payload": {"locale_id": "ucles"}})
    assert s.locales["ucles"].jihad_markers == 0
    s = qadir_position()
    s.locales["ucles"].jihad_markers = s.locales["calatrava"].jihad_markers = 0
    assert ["trujillo"] in al_qadir_choices(s)
    result = apply_action(s, {"type": "play_event", "side": "christian", "card_id": "C20",
                             "payload": {"locale_ids": ["trujillo"]}})
    assert result["jihad_removed"] == 1


@pytest.mark.parametrize("obstacle", ["muslim_present", "independent", "different_taifas", "no_markers"])
def test_qadir_enforces_taifa_eligibility(obstacle):
    s = qadir_position()
    selection = ["ucles", "ucles"]
    if obstacle == "muslim_present":
        s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    elif obstacle == "independent":
        s.taifas["toledo"].status = "independent"
    elif obstacle == "different_taifas":
        s.taifas["valencia"].status = "parias"
        s.locales["jativa"].jihad_markers = 1
        selection = ["ucles", "jativa"]
    else:
        for loc in s.locales.values():
            loc.jihad_markers = 0
    assert sorted(selection) not in al_qadir_choices(s)
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "play_event", "side": "christian", "card_id": "C20",
                         "payload": {"locale_ids": selection}})
    assert s.model_dump() == before


@pytest.mark.parametrize("action", [
    {"type": "levy_transport", "transport": "mule"},
    {"type": "levy_take_vassal", "vassal_index": 0},
    {"type": "levy_take_capability", "card_id": "M11"},
])
def test_c24_blocks_all_yusuf_levy_actions_and_the_menu(action):
    s = first_muster("muslim")
    resolve_event(s, "christian", "C24")
    assert "yusuf" in s.meta.muster_banned_this_levy_lord_ids
    move = {**action, "side": "muslim", "lord_id": "yusuf"}
    assert move not in legal_moves(s)
    assert not _muster_cap_lord_eligible(s, "yusuf", "muslim")
    before = s.model_dump()
    with pytest.raises(IllegalAction) as caught:
        apply_action(s, move)
    assert caught.value.code == "muster_banned"
    assert s.model_dump() == before
    s.meta.muster_banned_this_levy_lord_ids.clear()
    assert muster_ineligibility(s, "yusuf") is None


def test_muster_ban_also_blocks_free_fonsadera():
    s = first_muster()
    s.decks.capabilities_in_play.append(CardInPlay(card_id="C23", scope="side_wide", owner_side="christian"))
    s.decks.board_edge.setdefault("christian", []).append("C23")
    s.meta.muster_banned_this_levy_lord_ids.append("pedro_ansurez")
    move = {"type": "cap_fonsadera", "side": "christian", "lord_id": "pedro_ansurez", "vassal_index": 0, "mode": "coin"}
    assert move not in legal_moves(s)
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(s, move)
    assert s.model_dump() == before


def test_sisnando_is_alfonso_only_and_uses_no_personal_slot():
    assert load_cards()["cards"]["C21"]["capability_scope"] == "side_wide"
    s = first_muster()
    menu = legal_moves(s)
    alf = {"type": "levy_take_capability", "side": "christian", "lord_id": "alfonso", "card_id": "C21"}
    pedro = {**alf, "lord_id": "pedro_ansurez"}
    assert alf in menu
    assert pedro not in menu
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(s, pedro)
    assert s.model_dump() == before
    caps = s.lords["alfonso"].capabilities[:]
    assert len(caps) == 2
    apply_action(s, alf)
    assert s.lords["alfonso"].capabilities == caps
    assert side_has_capability(s, "christian", "C21")
    assert "C21" in s.decks.board_edge["christian"]


def test_sisnando_works_in_levy_once_not_campaign_and_returns_next_levy():
    s = first_muster()
    apply_action(s, {"type": "levy_take_capability", "side": "christian", "lord_id": "alfonso", "card_id": "C21"})
    move = {"type": "cap_sisnando", "side": "christian", "target_locale": "ucles"}
    assert move in legal_moves(s)
    before_actions = s.meta.actions_remaining
    before_lordship = s.lords["alfonso"].lordship_used
    apply_action(s, move)
    assert s.locales["ucles"].jihad_markers == 1
    assert s.meta.actions_remaining == before_actions
    assert s.lords["alfonso"].lordship_used == before_lordship
    assert move not in legal_moves(s)
    before = s.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(s, move)
    assert s.model_dump() == before
    s.meta.turn_index += 1
    assert move in legal_moves(s)
    activate(s, "christian", "alfonso")
    assert move not in legal_moves(s)
    with pytest.raises(IllegalAction):
        apply_action(s, move)
