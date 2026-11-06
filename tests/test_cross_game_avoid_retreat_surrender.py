"""Fourth-audit regressions for Avoid, conceding Retreat, and Surrender."""

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.capabilities import effective_command
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, GameState
from almoravid.views import redacted_view


def position(seed=7):
    state = load_scenario("scenario_f_reconquista", seed=seed)
    for lord in state.lords.values():
        lord.cylinder = Cylinder(kind="mat")
        lord.in_stronghold = False
        lord.assets = {}
        lord.forces = {"men_at_arms": 4}
        lord.routed_units = {}
        lord.capabilities = []
    state.decks.held = {"christian": [], "muslim": []}
    state.decks.this_levy_events = {"christian": [], "muslim": []}
    state.decks.this_campaign_events = {"christian": [], "muslim": []}
    state.decks.capabilities_in_play = []
    state.meta.phase = "campaign"
    state.meta.campaign_step = "activation"
    state.meta.active_player = "christian"
    state.meta.active_lord_id = "alfonso"
    state.meta.actions_remaining = effective_command(state, "alfonso")
    state.pending = None
    return state


def place(state, lid, locale, **assets):
    state.lords[lid].cylinder = Cylinder(kind="locale", locale_id=locale)
    state.lords[lid].assets = assets


def moves(state, kind):
    return [move for move in legal_moves(state) if move["type"] == kind]


def reject_unchanged(state, action, code):
    before = state.model_dump_json()
    with pytest.raises(IllegalAction) as error:
        apply_action(state, action)
    assert error.value.code == code
    assert state.model_dump_json() == before


def approach(**mutamid_assets):
    state = position()
    place(state, "alfonso", "leon")
    place(state, "alvar_fanez", "leon")
    place(state, "sancho", "sahagun")
    place(state, "al_mutamid", "sahagun", **mutamid_assets)
    place(state, "al_mundir", "sahagun", cart=2)
    apply_action(state, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "sahagun", "way_type": "road",
                         "group_lord_ids": ["alvar_fanez"]})
    assert state.pending.kind == "march_arrival_response"
    return state


def avoid(lords):
    return {"type": "respond_avoid_battle", "side": "muslim",
            "target_locale_id": "palencia", "way_type": "road", "lord_ids": lords}


@pytest.mark.parametrize("repeat", ["al_mutamid", "al_mundir"])
def test_duplicate_avoiders_rejected_before_the_swollen_river_window(repeat):
    state = approach(prov=4)
    ids = ["al_mutamid", "al_mundir"]
    reject_unchanged(state, avoid([*ids, repeat]), "bad_subset")
    apply_action(state, avoid(ids))
    result = apply_action(state, {"type": "respond_swollen_river_block", "side": "christian"})
    assert result["discarded_as_spoils"] == {"prov": 2}
    assert state.lords["al_mutamid"].assets == {"prov": 2}
    assert state.lords["al_mundir"].assets == {"cart": 2}


def test_old_save_with_repeated_avoider_can_finish_without_extra_spoils():
    state = approach(prov=4)
    apply_action(state, avoid(["al_mutamid", "al_mundir"]))
    state.pending.payload["avoid_action"]["lord_ids"].append("al_mutamid")
    state = GameState.model_validate_json(state.model_dump_json())
    result = apply_action(state, {"type": "respond_swollen_river_block", "side": "christian"})
    assert result["discarded_as_spoils"] == {"prov": 2}
    assert state.lords["al_mutamid"].assets == {"prov": 2}


def test_avoider_spoils_go_only_to_the_approaching_group_before_remaining_defenders_respond():
    state = approach(loot=4)
    apply_action(state, avoid(["al_mutamid"]))
    result = apply_action(state, {"type": "respond_swollen_river_block", "side": "christian"})
    assert result["discarded_as_spoils"] == {"loot": 4}
    assert result["pending"] == "battle_spoils"
    assert state.pending.payload["source"] == "avoid"
    assert set(state.pending.payload["recipients"]) == {"alfonso", "alvar_fanez"}
    choice = next(m for m in moves(state, "battle_spoils")
                  if m["lord_id"] == "alvar_fanez" and m["amount"] == 4)
    reject_unchanged(state, {**choice, "lord_id": "sancho"}, "bad_arg")
    state = GameState.model_validate_json(state.model_dump_json())
    apply_action(state, choice)
    assert state.lords["alvar_fanez"].assets == {"loot": 4}
    assert state.lords["alfonso"].assets == state.lords["sancho"].assets == {}
    assert state.pending.kind == "march_arrival_response"
    assert state.pending.waiting_on == state.meta.active_player == "muslim"
    assert state.pending.payload["defender_lord_ids"] == ["al_mundir"]


@pytest.mark.parametrize("alfonso_keeps", [0, 1, 2])
def test_conceding_owner_divides_the_shared_transport_after_losses(alfonso_keeps):
    state = position()
    place(state, "alfonso", "leon", cart=2, prov=2)
    place(state, "alvar_fanez", "leon", prov=2)
    place(state, "al_mutamid", "leon")
    apply_action(state, {"type": "cmd_battle", "side": "christian",
                         "attacker_concede_round": 1, "interactive_retreat": True})
    for lord in ("alvar_fanez", "alfonso"):
        apply_action(state, next(m for m in moves(state, "battle_fate")
                                 if m["lord_id"] == lord and m.get("retreat_to") == "sahagun"))
    assert state.pending.kind == "retreat_provender"
    assert state.pending.waiting_on == state.meta.active_player == "christian"
    assert all(state.lords[lid].cylinder.locale_id == "sahagun"
               for lid in ("alfonso", "alvar_fanez"))
    options = moves(state, "retreat_provender")
    assert [m["amount"] for m in options] == [0, 1, 2]
    assert "_retreat_provender_resume" not in redacted_view(
        state, "muslim")["pending"]["payload"]
    reject_unchanged(state, {**options[0], "side": "muslim"}, "not_responder")
    reject_unchanged(state, {**options[0], "amount": 3}, "bad_arg")
    state = GameState.model_validate_json(state.model_dump_json())
    result = apply_action(state, options[alfonso_keeps])
    assert result["provender_kept"] == {"alfonso": alfonso_keeps,
                                       "alvar_fanez": 2 - alfonso_keeps}
    assert state.lords["alfonso"].assets.get("prov", 0) == alfonso_keeps
    assert state.lords["alvar_fanez"].assets.get("prov", 0) == 2 - alfonso_keeps
    assert state.lords["al_mutamid"].assets == {"prov": 2}
    assert state.pending.kind == "severed_heads"
    apply_action(state, {"type": "decline_severed_heads", "side": "muslim"})
    assert state.pending is None and state.meta.active_player == "christian"


def siege(card=None, *, reconquista=False):
    state = position(seed=1)
    target = "cordoba" if reconquista else "jativa"
    place(state, "alfonso", target)
    place(state, "alvar_fanez", target)
    place(state, "al_mutamid", "sevilla")
    state.locales[target].siege_yellow = 4
    state.locales[target].ravaged = "yellow"
    state.taifas[state.locales[target].territory].status = (
        "reconquista" if reconquista else "independent")
    if reconquista:
        state.locales[target].jihad_markers = 1
    if card:
        state.decks.draw = [cid for cid in state.decks.draw if cid != card]
        state.decks.discard = [cid for cid in state.decks.discard if cid != card]
        state.decks.held["christian"] = [card]
    return state


@pytest.mark.parametrize("mozarabes", [False, True])
def test_mozarabes_is_an_optional_before_roll_choice_at_full_siegeworks(mozarabes):
    state = siege("C21", reconquista=True)
    choice = next(m for m in moves(state, "cmd_siege")
                  if m.get("surrender", True) and m.get("mozarabes", False) == mozarabes)
    result = apply_action(state, choice)
    assert result["surrender"]["succeeded"]
    assert result["surrender"]["dice"] == ([] if mozarabes else [5, 1, 5])
    assert ("C21" in state.decks.held["christian"]) != mozarabes
    assert ("C21" in state.decks.discard) == mozarabes


def test_c9_can_be_held_after_surrender_without_revealing_card_ownership():
    views = []
    for card in (None, "C9"):
        state = siege(card)
        choice = next(m for m in moves(state, "cmd_siege") if m.get("interactive_surrender"))
        result = apply_action(state, choice)
        assert result["surrender"]["succeeded"] and result["surrender"]["dice"] == [5]
        views.append(redacted_view(state, "muslim")["pending"])
        options = moves(state, "betrayal_of_terms")
        assert {m["mode"] for m in options} == ({"decline", "single", "double"} if card
                                                else {"decline"})
        if not card:
            reject_unchanged(state, {**options[0], "mode": "double"}, "card_not_held")
        apply_action(state, next(m for m in options if m["mode"] == "decline"))
        assert state.pending is None and state.meta.active_player == "christian"
        assert state.decks.held["christian"] == (["C9"] if card else [])
        assert state.lords["alfonso"].assets == state.lords["alvar_fanez"].assets == {}
    assert views[0] == views[1]


def test_failed_surrender_neither_plays_c9_nor_opens_its_response():
    state = siege("C9")
    state.locales["jativa"].ravaged = "none"  # Threshold 4, seed 1 rolls 5.
    result = apply_action(state, {"type": "cmd_siege", "side": "christian",
                                  "interactive_surrender": True, "c9_mode": "double"})
    assert result["surrender"] == {"dice": [5], "threshold": 4, "succeeded": False}
    assert state.pending is None and state.decks.held["christian"] == ["C9"]


@pytest.mark.parametrize(("mode", "expected_spoils"),
                         [("single", {"coin": 1, "prov": 2}),
                          ("double", {"coin": 2, "prov": 4})])
def test_c9_spoils_and_jihad_are_owned_choices(mode, expected_spoils):
    state = siege("C9")
    apply_action(state, next(m for m in moves(state, "cmd_siege")
                             if m.get("interactive_surrender")))
    choose = next(m for m in moves(state, "betrayal_of_terms") if m["mode"] == mode)
    reject_unchanged(state, {**choose, "side": "muslim"}, "not_responder")
    result = apply_action(state, choose)
    assert result["spoils"] == expected_spoils
    assert result["pending"] == "battle_spoils"
    assert "C9" not in state.decks.held["christian"] and "C9" in state.decks.discard
    jihad_before = {lid: loc.jihad_markers for lid, loc in state.locales.items()}
    for asset, count in expected_spoils.items():
        award = next(m for m in moves(state, "battle_spoils")
                     if m["lord_id"] == "alvar_fanez" and m["asset"] == asset
                     and m["amount"] == count)
        apply_action(state, award)
        state = GameState.model_validate_json(state.model_dump_json())
    assert state.lords["alvar_fanez"].assets == expected_spoils
    assert state.lords["alfonso"].assets == {}
    assert {lid: loc.jihad_markers for lid, loc in state.locales.items()} == jihad_before
    if mode == "double":
        assert state.pending.kind == "betrayal_jihad"
        assert state.pending.waiting_on == state.meta.active_player == "muslim"
        choose = next(m for m in moves(state, "betrayal_jihad")
                      if m["target_locale_id"] == "talavera")
        reject_unchanged(state, {**choose, "side": "christian"}, "not_responder")
        reject_unchanged(state, {**choose, "target_locale_id": "atlantic"}, "bad_target")
        assert apply_action(state, choose)["jihad_placed"] == {"talavera": 1}
        jihad_before["talavera"] += 1
    assert {lid: loc.jihad_markers for lid, loc in state.locales.items()} == jihad_before
    assert state.pending is None and state.meta.active_player == "christian"
