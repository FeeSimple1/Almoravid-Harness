"""Second audit A2-01/A2-02: Losses Spoils and optional M13 timing."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (
    BattleResult,
    BattleSide,
    _transfer_retreat_spoils,
    apply_battle_losses,
    apply_retreat_aftermath,
)
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, GameState, PendingDecision, ServiceMarker
from almoravid.views import redacted_view
from tests.combat_choices import apply_combat_choices


def _base(seed=1, held=True):
    state = load_scenario("scenario_a_toledo_beset", seed=seed)
    for lord in state.lords.values():
        lord.cylinder = Cylinder(kind="mat")
        lord.forces = {}
        lord.routed_units = {}
        lord.assets = {}
        lord.capabilities = []
        lord.in_stronghold = False
    state.decks.capabilities_in_play = []
    state.decks.board_edge = {"christian": [], "muslim": []}
    state.decks.this_levy_events = {"christian": [], "muslim": []}
    state.decks.this_campaign_events = {"christian": [], "muslim": []}
    state.decks.held = {"christian": [], "muslim": ["M13"] if held else []}
    state.decks.draw = [cid for cid in state.decks.draw if cid != "M13"]
    state.pending = None
    state.meta.phase = "campaign"
    state.meta.campaign_step = "activation"
    state.meta.active_player = "muslim"
    state.meta.active_lord_id = "al_mutamid"
    state.meta.actions_remaining = 2
    for lid, locale in (("al_mutamid", "transduero"), ("alfonso", "leon"),
                        ("alvar_fanez", "zamora")):
        state.lords[lid].cylinder = Cylinder(kind="locale", locale_id=locale)
        state.lords[lid].forces = {"men_at_arms": 4}
    state.locales["transduero"].ravaged = "none"
    return state


def _ravage(state):
    return apply_action(state, {"type": "cmd_ravage", "side": "muslim"})


def _designate_ravaging_lieutenant(state):
    lower = state.lords["abu_bakr"]
    lower.cylinder = state.lords["al_mutamid"].cylinder.model_copy()
    lower.forces = {"men_at_arms": 1}
    state.meta.campaign_step = "plan"
    apply_action(state, {"type": "designate_lieutenant", "side": "muslim",
                         "lord_id": lower.id, "commander_id": "al_mutamid"})
    state.meta.campaign_step = "activation"


def _retreat(state, christian_active=False):
    state.lords["alfonso"].cylinder.locale_id = "transduero"
    if christian_active:
        state.meta.active_player = "christian"
        state.meta.active_lord_id = "alfonso"
    return apply_combat_choices(state, {
        "type": "cmd_battle", "side": state.meta.active_player,
        "attacker_concede_round" if christian_active else "defender_concede_round": 1,
    })


def _play(state, **choices):
    return apply_action(state, {"type": "play_severed_heads", "side": "muslim", **choices})


def _decline(state):
    return apply_action(state, {"type": "decline_severed_heads", "side": "muslim"})


@pytest.mark.parametrize("loser_side", ["christian", "muslim"])
@pytest.mark.parametrize("fate,conceded", [("withdraw", False), ("retreat", True),
                                         ("retreat", False)])
def test_losses_removal_captures_all_residual_assets(monkeypatch, loser_side, fate, conceded):
    state = _base()
    state.taifas["sevilla"].status = "parias"
    loser_id, winner_id = (("alfonso", "al_mutamid") if loser_side == "christian"
                           else ("al_mutamid", "alfonso"))
    loser, winner = state.lords[loser_id], state.lords[winner_id]
    loser.forces = {}
    loser.routed_units = {"militia": 1}
    loser.assets = {"coin": 3, "mule": 1, "prov": 2, "loot": 1}
    winner.assets = {}
    taken = _transfer_retreat_spoils(state, loser, fate, conceded, [winner_id])
    summary = {"losers": [{"lord_id": loser_id, "fate": fate, "spoils_lost": taken}]}
    attacker = BattleSide(side=winner.side, role="attacker", forces={}, lord_ids=[winner_id])
    defender = BattleSide(side=loser.side, role="defender", forces={}, lord_ids=[loser_id],
                          conceded=conceded)
    result = BattleResult(engagement="battle", attacker=attacker, defender=defender,
                          winner=winner.side)
    monkeypatch.setattr("almoravid.battle.roll_d6", lambda _: 6)
    apply_battle_losses(state, result, summary)
    assert loser.cylinder.kind == "removed"
    assert loser.assets == {}
    assert winner.assets == {"coin": 3, "mule": 1, "prov": 2, "loot": 1}
    assert summary["losers"][0]["removed_by_losses"] is True
    assert summary["losers"][0]["spoils_lost"] == winner.assets


def test_losses_spoils_are_unlimited_and_ignore_removed_winners(monkeypatch):
    state = _base()
    state.taifas["sevilla"].status = "parias"
    state.lords["al_mutamid"].forces = {}
    state.lords["al_mutamid"].routed_units = {"militia": 1}
    survivor = state.lords["al_mundir"]
    survivor.cylinder = Cylinder(kind="locale", locale_id="transduero")
    survivor.forces = {"men_at_arms": 1}
    survivor.assets = {"coin": 7}
    loser = state.lords["alfonso"]
    loser.forces = {}
    loser.routed_units = {"militia": 1}
    loser.assets = {"coin": 3, "mule": 1}
    result = BattleResult(
        engagement="battle", winner="muslim",
        attacker=BattleSide(side="muslim", role="attacker", forces={},
                            lord_ids=["al_mutamid", "al_mundir"]),
        defender=BattleSide(side="christian", role="defender", forces={}, lord_ids=["alfonso"]))
    monkeypatch.setattr("almoravid.battle.roll_d6", lambda _: 6)
    apply_battle_losses(state, result, {"losers": [{"lord_id": "alfonso", "fate": "withdraw"}]})
    assert survivor.assets == {"coin": 10, "mule": 1}
    assert state.lords["al_mutamid"].assets == {}


def test_surviving_withdrawer_keeps_assets(monkeypatch):
    state = _base()
    loser = state.lords["alfonso"]
    loser.forces = {}
    loser.routed_units = {"militia": 1}
    loser.assets = {"coin": 3}
    result = BattleResult(
        engagement="battle", winner="muslim",
        attacker=BattleSide(side="muslim", role="attacker", forces={}, lord_ids=["al_mutamid"]),
        defender=BattleSide(side="christian", role="defender", forces={}, lord_ids=["alfonso"]))
    monkeypatch.setattr("almoravid.battle.roll_d6", lambda _: 1)
    apply_battle_losses(state, result, {"losers": [{"lord_id": "alfonso", "fate": "withdraw"}]})
    assert loser.forces == {"militia": 1}
    assert loser.assets == {"coin": 3}
    assert state.lords["al_mutamid"].assets == {}


def test_real_withdraw_then_losses_removal_captures_spoils_without_m13():
    state = _base(seed=1)
    state.lords["al_mutamid"].cylinder.locale_id = "leon"
    state.lords["alfonso"].forces = {"militia": 1}
    state.lords["alfonso"].assets = {"coin": 3, "mule": 1, "prov": 1}
    before = sum(loc.jihad_markers for loc in state.locales.values())
    result = apply_combat_choices(state, {"type": "cmd_battle", "side": "muslim"})
    assert result["retreat_summary"]["losers"][0]["fate"] == "withdraw"
    assert state.lords["alfonso"].cylinder.kind == "removed"
    assert state.lords["al_mutamid"].assets == {"coin": 3, "mule": 1, "prov": 1}
    assert sum(loc.jihad_markers for loc in state.locales.values()) == before
    assert "M13" in state.decks.held["muslim"]
    assert state.pending is None or state.pending.kind != "severed_heads"


def test_m13_rejects_before_ravage_atomically():
    state = _base()
    assert all(m["type"] != "play_severed_heads" for m in legal_moves(state))
    before = state.model_dump()
    with pytest.raises(IllegalAction):
        _play(state, mode="jihad")
    assert state.model_dump() == before


@pytest.mark.parametrize("held", [False, True])
def test_ravage_opportunity_is_optional_and_restores_activation(held):
    state = _base(held=held)
    _ravage(state)
    assert state.pending.kind == "severed_heads"
    assert state.pending.payload["jihad_count"] == 2
    assert state.meta.actions_remaining == 1
    assert "M13" not in state.decks.discard
    _decline(state)
    assert state.pending is None
    assert state.meta.active_player == "muslim"
    assert state.decks.held["muslim"] == (["M13"] if held else [])
    assert all(m["type"] != "play_severed_heads" for m in legal_moves(state))


def test_ravage_card_ownership_does_not_leak_in_response_or_opponent_view():
    held, empty = _base(), _base(held=False)
    assert _ravage(held) == _ravage(empty)
    assert redacted_view(held, "christian") == redacted_view(empty, "christian")
    assert legal_moves(empty) == [{"type": "decline_severed_heads", "side": "muslim"}]


@pytest.mark.parametrize("trigger,count", [("ravage", 2), ("combat", 4)])
def test_m13_explicit_jihad_placement(trigger, count):
    state = _base()
    _ravage(state) if trigger == "ravage" else _retreat(state)
    target = "toledo"
    state.taifas[state.locales[target].territory].status = "parias"
    before = state.locales[target].jihad_markers
    result = _play(state, mode="jihad", payload={"jihad_targets": [target] * count})
    assert result["jihad_added"] == count
    assert state.locales[target].jihad_markers == before + count
    assert state.decks.held["muslim"] == []
    assert state.decks.discard.count("M13") == 1
    assert state.pending is None


@pytest.mark.parametrize("calendar_box,service_box,expected", [(8, 6, (6, 8)),
                                                             (1, 16, (0, 17)),
                                                             (17, 17, (15, 17))])
def test_combat_allows_two_lords_calendar_left_service_right_with_vassals(
        calendar_box, service_box, expected):
    state = _base()
    _retreat(state)
    state.lords["al_mundir"].cylinder = Cylinder(kind="calendar", box=calendar_box)
    state.meta.advanced_vassal_service = True
    state.calendar.service_markers = [
        ServiceMarker(lord_id="al_mutamid", box=service_box),
        ServiceMarker(lord_id="al_mutamid", box=service_box, vassal_id="v1")]
    choice = {"type": "play_severed_heads", "side": "muslim", "mode": "shift",
              "target_lords": ["al_mundir", "al_mutamid"]}
    assert choice in legal_moves(state)
    result = apply_action(state, choice)
    assert len(result["shifted"]) == 2
    assert state.lords["al_mundir"].cylinder.box == expected[0]
    assert all(m.box == expected[1] for m in state.calendar.service_markers)


def test_ravage_shifts_on_map_service_and_legacy_single_target():
    state = _base()
    _ravage(state)
    state.calendar.service_markers = [ServiceMarker(lord_id="al_mutamid", box=6)]
    _play(state, mode="shift", target_lord="al_mutamid")
    assert state.calendar.service_markers[0].box == 8


@pytest.mark.parametrize("choice", [
    {"mode": "shift", "target_lords": ["al_mutamid", "al_mundir"]},
    {"mode": "shift", "target_lords": ["alfonso"]},
    {"mode": "shift", "target_lords": ["al_mundir"]},
    {"mode": "shift", "target_lords": ["al_mutamid", "al_mutamid"]},
    {"mode": "shift", "target_lords": []},
    {"mode": "other"},
    {"mode": "jihad", "payload": {"jihad_targets": ["leon"]}},
    {"mode": "jihad", "payload": {"jihad_targets": ["toledo"] * 3}},
    {"mode": "jihad", "payload": ["toledo"]},
])
def test_invalid_m13_choices_are_atomic(choice):
    state = _base()
    _ravage(state)
    before = state.model_dump()
    with pytest.raises(IllegalAction):
        _play(state, **choice)
    assert state.model_dump() == before


def test_no_jihad_targets_keeps_card_and_window():
    state = _base()
    for taifa in state.taifas.values():
        taifa.status = "independent"
    _ravage(state)
    before = state.model_dump()
    assert _play(state, mode="jihad")["no_op"] is True
    assert state.model_dump() == before
    assert not any(m.get("mode") == "jihad" for m in legal_moves(state))


@pytest.mark.parametrize("play", [False, True])
def test_reaction_resumes_christian_turn_after_save_load(play):
    state = _base()
    _retreat(state, christian_active=True)
    assert state.meta.active_player == "muslim"
    assert state.pending.kind == "severed_heads"
    assert "_severed_heads_resume" not in redacted_view(state, "muslim")["pending"]["payload"]
    state = GameState.model_validate_json(state.model_dump_json())
    _play(state, mode="shift", target_lord="al_mutamid") if play else _decline(state)
    assert state.meta.active_player == "christian"
    assert state.meta.active_lord_id == "alfonso"
    assert state.meta.actions_remaining == 0
    assert state.pending is None


def test_reaction_preserves_nested_response_and_hides_continuation():
    from almoravid.campaign import _open_severed_heads_window
    state = _base()
    state.meta.active_player = "christian"
    original = PendingDecision(kind="besiege_or_bypass", waiting_on="christian",
                               payload={"private_test_value": "not visible"})
    state.pending = original
    state.meta.severed_heads_trigger = "combat"
    assert _open_severed_heads_window(state)
    for side in ("christian", "muslim"):
        assert "private_test_value" not in str(redacted_view(state, side)["pending"])
    state = GameState.model_validate_json(state.model_dump_json())
    _decline(state)
    assert state.pending == original
    assert state.meta.active_player == "christian"


@pytest.mark.parametrize("action", [
    {"type": "end_card", "side": "muslim"},
    {"type": "cmd_pass", "side": "muslim"},
    {"type": "decline_severed_heads", "side": "christian"},
    {"type": "play_severed_heads", "side": "christian"},
])
def test_m13_window_rejects_unrelated_actions_or_wrong_responder(action):
    state = _base()
    _ravage(state)
    before = state.model_dump()
    with pytest.raises(IllegalAction):
        apply_action(state, action)
    assert state.model_dump() == before


def test_cannot_play_m13_without_card():
    state = _base(held=False)
    _ravage(state)
    before = state.model_dump()
    with pytest.raises(IllegalAction):
        _play(state, mode="jihad")
    assert state.model_dump() == before


def test_no_retreat_elimination_qualifies_but_terminal_victory_skips_window(monkeypatch):
    from almoravid.campaign import _open_severed_heads_window
    state = _base()
    state.lords["alfonso"].cylinder.locale_id = "transduero"
    monkeypatch.setattr("almoravid.battle._retreat_target_clear", lambda *_: False)
    result = BattleResult(
        engagement="battle", winner="muslim",
        attacker=BattleSide(side="muslim", role="attacker", forces={}, lord_ids=["al_mutamid"]),
        defender=BattleSide(side="christian", role="defender", forces={}, lord_ids=["alfonso"]))
    summary = apply_retreat_aftermath(state, result)
    assert summary["losers"][0]["fate"] == "removed"
    assert state.meta.severed_heads_trigger == "combat"
    assert state.decks.held["muslim"] == ["M13"]
    state.meta.phase = "ended"
    assert not _open_severed_heads_window(state)
    assert getattr(state.meta, "severed_heads_trigger", None) is None


@pytest.mark.parametrize("roll", [1, 3, 4, 6])
def test_caballeria_failed_ravage_does_not_allow_m13_or_war_drums(monkeypatch, roll):
    state = _base()
    state.decks.capabilities_in_play = [
        CardInPlay(card_id="C19", scope="side_wide", owner_side="christian"),
        CardInPlay(card_id="M22", scope="side_wide", owner_side="muslim")]
    _designate_ravaging_lieutenant(state)
    monkeypatch.setattr("almoravid.rng.roll_d6", lambda _: roll)
    result = _ravage(state)
    assert result["caballeria_roll"] == roll
    assert state.meta.actions_remaining == 1
    if roll > 3:
        assert result["no_effect"] is True
        assert state.locales["transduero"].ravaged == "none"
        assert state.lords["al_mutamid"].assets == {}
        assert state.pending is None
    else:
        assert state.locales["transduero"].ravaged == "green"
        assert state.lords["al_mutamid"].assets == {"loot": 1, "prov": 1}
        assert state.pending.kind == "severed_heads"


def test_christian_stronghold_sack_opens_greater_reward():
    state = _base(seed=2)
    state.lords["al_mutamid"].cylinder.locale_id = "leon"
    state.lords["al_mutamid"].forces = {"knights": 6, "men_at_arms": 6}
    state.lords["alfonso"].in_stronghold = True
    state.lords["alfonso"].forces = {"militia": 1}
    state.locales["leon"].siege_green = 3
    result = apply_combat_choices(state, {"type": "cmd_storm", "side": "muslim"})
    assert result["sack"] is not None
    assert state.pending.kind == "severed_heads"
    assert state.pending.payload["jihad_count"] == 4
    assert state.pending.payload["lord_count"] == 2
    assert state.decks.held["muslim"] == ["M13"]


@pytest.mark.parametrize("roll", [3, 4])
def test_long_range_ravage_obeys_caballeria_and_m13_timing(monkeypatch, roll):
    state = _base()
    state.lords["al_mutamid"].capabilities = ["M24"]
    state.lords["al_mutamid"].assets = {"prov": 1}
    state.decks.capabilities_in_play = [
        CardInPlay(card_id="M24", scope="this_lord", owner_side="muslim",
                   owner_lord_id="al_mutamid"),
        CardInPlay(card_id="C19", scope="side_wide", owner_side="christian")]
    monkeypatch.setattr("almoravid.rng.roll_d6", lambda _: roll)
    result = apply_action(state, {"type": "cmd_cabalgadas", "side": "muslim",
                                  "target_locale": "palencia"})
    assert result["caballeria_roll"] == roll
    assert state.meta.actions_remaining == 0
    assert state.lords["al_mutamid"].assets.get("prov", 0) == (1 if roll <= 3 else 0)
    assert bool(state.pending) == (roll <= 3)
    if state.pending:
        assert state.pending.kind == "severed_heads"
        assert state.pending.payload["jihad_count"] == 2
    assert state.locales["palencia"].ravaged == ("green" if roll <= 3 else "none")


def test_caballeria_only_rolls_in_kingdoms(monkeypatch):
    state = _base()
    state.lords["al_mutamid"].cylinder.locale_id = "toledo"
    state.locales["toledo"].conquered_markers = 1
    state.locales["toledo"].ravaged = "none"
    state.decks.capabilities_in_play = [
        CardInPlay(card_id="C19", scope="side_wide", owner_side="christian")]

    def unexpected_roll(_):
        pytest.fail("C19 must not roll outside León/Aragón")

    monkeypatch.setattr("almoravid.rng.roll_d6", unexpected_roll)
    result = _ravage(state)
    assert result["caballeria_roll"] is None
    assert state.pending.kind == "severed_heads"


def test_event_placed_ravage_does_not_trigger_m13():
    from almoravid.events import resolve_event
    state = _base()
    selected = ["calahorra", "jaca"]
    result = resolve_event(state, "muslim", "M24", {"locale_ids": selected})
    assert result["ravaged"] == selected
    assert getattr(state.meta, "severed_heads_trigger", None) is None
    assert state.pending is None
    assert state.decks.held["muslim"] == ["M13"]


def test_surviving_christian_withdrawal_does_not_trigger_m13():
    state = _base(seed=23)
    state.lords["al_mutamid"].cylinder.locale_id = "leon"
    state.lords["alfonso"].forces = {"militia": 1}
    before = sum(loc.jihad_markers for loc in state.locales.values())
    result = apply_combat_choices(state, {"type": "cmd_battle", "side": "muslim"})
    assert result["retreat_summary"]["losers"][0]["fate"] == "withdraw"
    assert state.lords["alfonso"].cylinder.kind == "locale"
    assert state.lords["alfonso"].in_stronghold is True
    assert sum(loc.jihad_markers for loc in state.locales.values()) == before
    assert state.decks.held["muslim"] == ["M13"]
    assert state.pending.kind == "besiege_or_bypass"


@pytest.mark.parametrize("locale,war_drums,expected_prov", [
    ("transduero", False, 8), ("transduero", True, 9), ("palencia", True, 10)])
def test_ravage_and_war_drums_do_not_cap_assets_at_eight(locale, war_drums, expected_prov):
    state = _base()
    state.lords["al_mutamid"].cylinder.locale_id = locale
    state.lords["al_mutamid"].assets = {"loot": 8, "prov": 8}
    if war_drums:
        _designate_ravaging_lieutenant(state)
        state.decks.capabilities_in_play = [
            CardInPlay(card_id="M22", scope="side_wide", owner_side="muslim")]
    _ravage(state)
    assert state.lords["al_mutamid"].assets == {"loot": 9, "prov": expected_prov}
