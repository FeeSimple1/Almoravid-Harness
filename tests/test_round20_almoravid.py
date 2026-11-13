"""Round 20 Almoravid repairs through the public menus and action handlers."""

import pytest

from almoravid.actions import apply_action
from almoravid.events import held_event_ids
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, GameState, HistoryEntry, ServiceMarker
from almoravid.static_data import load_strongholds
from almoravid.views import redacted_view
from playtest_harness import Harness
from tests._plan_helpers import legal_pad
from tests.combat_choices import apply_combat_choices
from tests.test_cross_game_avoid_retreat_surrender import reject_unchanged
from tests.test_cross_game_logistics import place, position, service
from tests.test_fix_pay_321 import _set_marker, _to_pay
from tests.test_round19_almoravid import _advance_to, _later_levy, _listed, _reload, _replay
from tests.test_sortie_436 import _sortie_setup
from tests.test_winter_siege_632 import _enter_winter_box, _setup_besieger


TOLEDO = "scenario_a_toledo_beset"
RECONQUISTA = "scenario_f_reconquista"


def _draw_events(state, cards):
    assert apply_action(state, _listed(state, "aow_draw")[0])["drawn"] == cards
    for card in cards:
        _replay(state, _listed(state, "aow_implement_event", card_id=card)[0])


def _start_card(state, lord):
    # Stage Campaign entry with the native mats and the cards drawn in Levy.
    state.meta.phase, state.meta.levy_step = "campaign", None
    apply_action(state, {"type": "begin_campaign"})
    apply_action(state, {"type": "plan_add_card", "side": "christian",
                         "plan_kind": "command", "lord_id": lord})
    for side in ("christian", "muslim"):
        legal_pad(state, side)
        apply_action(state, {"type": "finalize_plan", "side": side})
    apply_action(state, {"type": "command_reveal", "side": "christian"})


@pytest.mark.parametrize("banned", [True, False])
def test_fitna_limits_al_sumaisir_calendar_muster(banned):
    state = _later_levy(113, "christian", RECONQUISTA)
    assert apply_action(state, _listed(state, "aow_draw")[0])["drawn"] == ["C19", "C2"]
    targets = ["abu_bakr" if banned else "abd_allah", "al_mustain"]
    _replay(state, _listed(state, "aow_implement_event", card_id="C19",
                           payload={"lord_ids": targets})[0])
    apply_action(state, _listed(state, "aow_implement_event", card_id="C2")[0])
    _advance_to(state, "muster", "muslim")
    move = {"type": "play_event", "side": "muslim", "card_id": "M21",
            "payload": {"lord_id": "abu_bakr"}}
    assert "M21" in held_event_ids(state, "muslim")
    assert (move in legal_moves(state)) is not banned
    if banned:
        reject_unchanged(state, move, "muster_banned")
        jihad = next(m for m in _listed(state, "play_event", card_id="M21") if "payload" not in m)
        assert _replay(state, jihad)["jihad_added"] == 2
    else:
        _replay(state, move)
        lord = state.lords["abu_bakr"]
        assert lord.cylinder.locale_id == "valencia" and sum(lord.forces.values()) == 4
    assert "M21" not in held_event_ids(state, "muslim")


@pytest.mark.parametrize("index,unit", [(0, "men_at_arms"), (1, "militia")])
def test_fonsadera_exchange_survives_saves_and_excludes_foot(index, unit):
    state = _later_levy(56, "christian", RECONQUISTA)
    _draw_events(state, ["C18", "C7"])
    _advance_to(state, "muster", "christian")
    _replay(state, _listed(state, "levy_take_capability", lord_id="alfonso", card_id="C23")[0])
    alfonso = state.lords["alfonso"]
    forces = dict(alfonso.forces)
    take = _listed(state, "levy_take_vassal", lord_id="alfonso", vassal_index=index)[0]
    restore = _listed(state, "play_event", card_id="C18", payload={"transport": "mule"})[0]
    muster_control = _reload(state)
    _replay(muster_control, take)
    control_forces = muster_control.lords["alfonso"].forces
    control_forces[unit] -= 1
    _replay(muster_control, restore)
    assert control_forces[unit] == forces.get(unit, 0) + 1

    exchange = _listed(state, "cap_fonsadera", lord_id="alfonso",
                       vassal_index=index, mode="coin")[0]
    _replay(state, exchange)
    assert alfonso.vassals[index].exchanged
    assert take not in legal_moves(state)
    reject_unchanged(state, take, "vassal_not_ready")
    old_save = state.model_dump()
    del old_save["lords"]["alfonso"]["vassals"][index]["exchanged"]
    legacy = GameState.model_validate(old_save)
    assert legacy.lords["alfonso"].vassals[index].exchanged
    for restored in (state, legacy):
        _replay(restored, restore)
        assert restored.lords["alfonso"].forces == forces


def test_fonsadera_resets_when_the_lord_musters_again():
    state = _later_levy(56, "christian", RECONQUISTA)
    _draw_events(state, ["C18", "C7"])
    _advance_to(state, "muster", "christian")
    apply_action(state, _listed(state, "levy_take_capability", lord_id="alfonso", card_id="C23")[0])
    apply_action(state, _listed(state, "cap_fonsadera", lord_id="alfonso",
                                vassal_index=0, mode="coin")[0])
    state.meta.levy_step = "service_disband"
    _set_marker(state, "alfonso", state.calendar.current_box)
    _replay(state, _listed(state, "disband_lord", lord_id="alfonso")[0])
    assert state.lords["alfonso"].vassals == []
    state.decks.held.setdefault("christian", []).append("C15")
    remuster = _listed(state, "play_cluniacs", mode="muster_from_calendar", lord_id="alfonso")[0]
    _replay(state, remuster)
    assert state.lords["alfonso"].vassals[0].available_to_muster


def test_swollen_river_reaction_resumes_or_blocks_same_march():
    state = _later_levy(0, "muslim")
    _draw_events(state, ["M4", "M3"])
    _start_card(state, "alfonso")
    march = _listed(state, "cmd_march", target_locale_id="leon", way_type="road")[0]
    reject_unchanged(state, {**march, "target_locale_id": "sevilla"}, "not_adjacent")
    empty = _reload(state)
    empty.decks.held["muslim"].remove("M3")
    # Isolate the live reaction from the earlier draw history.
    state.history.clear()
    empty.history.clear()
    lord = state.lords["alfonso"]
    origin, actions, assets = lord.cylinder.locale_id, state.meta.actions_remaining, dict(lord.assets)
    assert _replay(state, march) == _replay(empty, march)
    assert redacted_view(state, "christian") == redacted_view(empty, "christian")
    assert "_march_resume" not in redacted_view(state, "muslim")["pending"]["payload"]
    play = _listed(state, "swollen_river_march", play=True)[0]
    decline = _listed(state, "swollen_river_march", play=False)[0]
    reject_unchanged(empty, play, "card_not_held")
    reject_unchanged(state, {**play, "side": "christian"}, "not_responder")
    reject_unchanged(state, {"type": "end_card", "side": "muslim"}, "pending_decision")
    assert lord.cylinder.locale_id == origin and state.meta.actions_remaining == actions

    unblocked = _reload(state)
    _replay(unblocked, decline)
    assert unblocked.lords["alfonso"].cylinder.locale_id == "leon"
    assert unblocked.meta.actions_remaining == actions - 1
    assert unblocked.pending.kind == "arid_terrain_choice"
    assert "M3" in held_event_ids(unblocked, "muslim")
    assert _replay(state, play)["swollen_river_blocked"]
    assert state.decks.discard.count("M3") == 1 and "M4" in held_event_ids(state, "muslim")
    assert lord.cylinder.locale_id == origin and lord.assets == assets
    assert state.meta.actions_remaining == actions and not _listed(state, "cmd_march")
    reject_unchanged(state, march, "swollen_river_blocked")
    assert _listed(state, "cmd_forage")


def test_swollen_river_decline_preserves_the_unladen_discard_election():
    state = position(actions=1)
    state.lords["alfonso"].assets = {"loot": 1}
    state.decks.held["muslim"] = ["M3"]
    march = _listed(state, "cmd_march", target_locale_id="leon", discard_to_unladen=True)[0]
    _replay(state, march)
    result = _replay(state, _listed(state, "swollen_river_march", play=False)[0])
    assert result["cost"] == 1 and result["discarded_for_march"] == {"alfonso": {"loot": 1}}


def test_adalides_at_march_origin_cancels_played_swollen_river():
    state = position()
    place(state, "garcia_ordonez", "sahagun")
    state.lords["garcia_ordonez"].capabilities.append("C10")
    state.decks.capabilities_in_play.append(
        CardInPlay(card_id="C10", scope="this_lord", owner_side="christian",
                   owner_lord_id="garcia_ordonez"))
    state.decks.held["muslim"] = ["M3"]
    _replay(state, _listed(state, "cmd_march", target_locale_id="leon")[0])
    result = _replay(state, _listed(state, "swollen_river_march", play=True)[0])
    assert result["swollen_river_cancelled"] == "M3" and result["to"] == "leon"
    assert state.meta.swollen_river_blocked_card_lord_id is None
    assert state.decks.discard.count("M3") == 1


@pytest.mark.parametrize("command", ["cmd_encamp", "cmd_sortie"])
def test_swollen_river_can_block_march_from_bypass(command):
    if command == "cmd_sortie":
        state, _ = _sortie_setup()
    else:
        state = position(locale="calatrava")
        state.locales["calatrava"].bypass_yellow = True
    state.decks.held["muslim"] = ["M3"]
    move = _listed(state, command)[0]
    actions = state.meta.actions_remaining
    _replay(state, move)
    continued = _reload(state)
    _replay(continued, _listed(continued, "swollen_river_march", play=False)[0])
    if command == "cmd_sortie":
        assert continued.pending.kind == "march_arrival_response"
    else:
        assert continued.locales["calatrava"].siege_yellow == 1
    _replay(state, _listed(state, "swollen_river_march", play=True)[0])
    assert state.meta.actions_remaining == actions
    assert not _listed(state, command)
    reject_unchanged(state, move, "swollen_river_blocked")


def test_surprise_follows_arid_and_forces_a_free_first_storm_round():
    state = _later_levy(5, "christian")
    _draw_events(state, ["C6", "C18"])
    _start_card(state, "alvar_fanez")
    state.meta.actions_remaining = 1
    state.decks.held.setdefault("muslim", []).append("M4")
    march = _listed(state, "cmd_march", target_locale_id="calatrava", way_type="road")[0]
    _replay(state, march)
    _replay(state, _listed(state, "swollen_river_march", play=False)[0])
    assert state.pending.kind == "arid_terrain_choice"
    here = state.locales["calatrava"]
    assert here.siege_yellow == 0 and "C6" in held_event_ids(state, "christian")
    _replay(state, _listed(state, "arid_terrain_choice", play=True)[0])
    assert state.pending.kind == "surprise_choice" and state.meta.actions_remaining == 0
    play = _listed(state, "surprise_choice", play=True)[0]
    decline = _listed(state, "surprise_choice", play=False)[0]
    retained = _reload(state)
    assert _replay(retained, decline)["arid_terrain_played"] == "M4"
    assert retained.pending.kind == "besiege_or_bypass" and retained.locales[here.id].siege_yellow == 0
    assert "C6" in held_event_ids(retained, "christian")

    assert _replay(state, play)["storm_required"] == here.id
    assert here.siege_yellow == 2 and state.decks.discard.count("C6") == 1
    assert {m["type"] for m in legal_moves(state)} == {"cmd_storm"}
    reject_unchanged(state, {"type": "end_card", "side": "christian"}, "surprise_storm_required")
    reject_unchanged(state, march, "surprise_storm_required")
    storm = _listed(state, "cmd_storm", interactive_concede=True)[0]
    apply_combat_choices(state, storm)
    assert state.pending.kind == "storm_concede"
    payload = state.pending.payload
    assert payload["rounds_done"] == 1 and payload["round_idx"] == 2
    walls = load_strongholds()["strongholds"][here.base_type]["walls_range"]
    assert payload["ss"]["walls_range"] == [walls[0], walls[1] - 1]
    result = _replay(state, _listed(state, "storm_concede", attacker_concede=True)[0])
    assert result["rounds"] == 1 and result["actions_consumed"] == 0
    assert state.meta.surprise_storm_pending_locale_id is None
    assert _listed(state, "end_card")


def test_stale_surprise_from_an_older_card_does_not_lock_the_current_card():
    state = position(locale="calatrava")
    state.locales["calatrava"].siege_yellow = 2
    state.meta.surprise_storm_pending_locale_id = "calatrava"
    state.history.extend([
        HistoryEntry(turn_index=0, actor="christian", action="cmd_march",
                     summary="christian Surprise (C6) at calatrava: placed 2 Siege"),
        HistoryEntry(turn_index=0, actor="christian", action="end_card"),
        HistoryEntry(turn_index=0, actor="christian", action="command_reveal"),
    ])
    state = _reload(state)
    assert state.meta.surprise_storm_pending_locale_id is None
    assert _listed(state, "end_card")


@pytest.mark.parametrize("legacy_hold", [False, True])
def test_surprise_public_prompt_does_not_reveal_card(legacy_hold):
    state = _later_levy(5, "christian")
    _draw_events(state, ["C6", "C18"])
    _start_card(state, "alvar_fanez")
    control = _reload(state)
    control.decks.held["christian"].remove("C6")
    state.history.clear()
    control.history.clear()
    if legacy_hold:
        # Exercise a saved legacy Hold in the same public position.
        state.decks.held["christian"].remove("C6")
        state.decks.this_campaign_events["christian"] = ["C6"]
    for position_ in (state, control):
        _replay(position_, _listed(position_, "cmd_march", target_locale_id="calatrava")[0])
        _replay(position_, _listed(position_, "swollen_river_march", play=False)[0])
        _replay(position_, _listed(position_, "arid_terrain_choice", play=False)[0])
    assert redacted_view(state, "muslim") == redacted_view(control, "muslim")
    assert not _listed(control, "surprise_choice", play=True)
    reject_unchanged(control, _listed(state, "surprise_choice", play=True)[0], "card_not_held")


@pytest.mark.parametrize("resource", ["coin", "loot", "taifa_coin"])
def test_pay_caps_each_resource_spent_and_validated_menu(tmp_path, resource):
    harness = Harness(TOLEDO, seed=1)
    state = harness.state
    _to_pay(state)
    side, lid = ("muslim", "al_mutamid") if resource == "taifa_coin" else ("christian", "alfonso")
    if resource == "taifa_coin":
        apply_action(state, {"type": "pass_step", "side": "christian"})
        state.taifas_box_coin = 3
    else:
        state.lords[lid].assets[resource] = 3
    _set_marker(state, lid, 16)
    menu = harness.legal()
    pay = next(m for m in menu if m["type"] == "pay_lord" and m["resource"] == resource
               and m["target_lord_id"] == lid and m.get("payer_lord_id", lid) == lid)
    reject_unchanged(state, {**pay, "amount": 3}, "pay_exceeds_service_limit")
    path = str(tmp_path / "partial.json")
    harness.save(path)
    reloaded = Harness.load(path)
    assert harness.apply(menu.index(pay)) == reloaded.apply(reloaded.legal().index(pay))
    assert service(state, lid) == 17
    stock = state.taifas_box_coin if resource == "taifa_coin" else state.lords[lid].assets[resource]
    assert stock == 2 and pay not in harness.legal()
    reject_unchanged(state, pay, "pay_exceeds_service_limit")
    assert not harness.findings and not reloaded.findings


def test_capped_payer_can_pay_colocated_lord():
    state = _to_pay(load_scenario(TOLEDO))
    place(state, "alfonso", "leon", coin=2)
    place(state, "garcia_ordonez", "leon")
    _set_marker(state, "alfonso", 17)
    _set_marker(state, "garcia_ordonez", 16)
    pay = _listed(state, "pay_lord", resource="coin", payer_lord_id="alfonso",
                  target_lord_id="garcia_ordonez")[0]
    assert _replay(state, pay)["service_box"] == 17
    assert state.lords["alfonso"].assets["coin"] == 1 and pay not in legal_moves(state)


@pytest.mark.parametrize("legacy_lane", [True, False])
def test_pay_at_lord_cap_can_move_an_advanced_vassal(legacy_lane):
    state = _to_pay(load_scenario(TOLEDO))
    lord = state.lords["alfonso"]
    lord.assets["coin"] = 3
    state.meta.advanced_vassal_service = True
    _set_marker(state, lord.id, 17)
    if legacy_lane:
        state.calendar.service_markers = [m for m in state.calendar.service_markers
                                          if m.lord_id != lord.id]
        state.calendar.off_right_service.append(lord.id)
    vassal = lord.vassals[0]
    vassal.ready = False
    vassal_marker = ServiceMarker(lord_id=lord.id, vassal_id=vassal.id, box=16)
    state.calendar.service_markers.append(vassal_marker)
    pay = _listed(state, "pay_lord", resource="coin", target_lord_id=lord.id,
                  payer_lord_id=lord.id)[0]
    reject_unchanged(state, {**pay, "amount": 2}, "pay_exceeds_service_limit")
    _replay(state, pay)
    assert service(state, lord.id) == vassal_marker.box == 17
    assert lord.assets["coin"] == 2 and pay not in legal_moves(state)


@pytest.mark.parametrize("kind", ["pay_before_disband", "winter_siege_pay"])
def test_campaign_and_winter_pay_share_the_service_limit(kind):
    if kind == "pay_before_disband":
        state = position()
        state.lords["alfonso"].assets = {"coin": 3}
        _set_marker(state, "alfonso", 16)
        apply_action(state, {"type": "end_card", "side": "christian", "interactive_economy": True})
    else:
        state = load_scenario(RECONQUISTA)
        lord, _ = _setup_besieger(state)
        lord.assets = {"coin": 3, "prov": 1}
        _set_marker(state, "alfonso", 16)
        _enter_winter_box(state, 7)
        apply_action(state, _listed(state, "winter_siege_action", mode="pass")[0])
    pay = _listed(state, kind, resource="coin", target_lord_id="alfonso",
                  payer_lord_id="alfonso")[0]
    reject_unchanged(state, {**pay, "amount": 2}, "pay_exceeds_service_limit")
    _replay(state, pay)
    assert pay not in legal_moves(state) and state.lords["alfonso"].assets["coin"] == 2
