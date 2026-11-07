"""IF2-2/3: reveal combat only after commitment; keep unused Holds secret."""

from __future__ import annotations

import pytest

from almoravid import battle
from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder, GameState
from almoravid.views import redacted_view
from tests.test_phase6b_approach import _activate_lord_at_locale
from tests.combat_choices import apply_combat_choices


def approach(side="christian", hidden=True):
    attacker, defender = (
        ("alfonso", "al_mutamid") if side == "christian" else ("al_mutamid", "alfonso")
    )
    state = _activate_lord_at_locale("scenario_a_toledo_beset", attacker, "leon", seed=11)
    state.meta.hidden_mats = hidden
    state.lords[attacker].assets = {}
    state.lords[defender].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    state.lords[defender].in_stronghold = False
    apply_action(
        state,
        {"type": "cmd_march", "side": side, "target_locale_id": "sahagun", "way_type": "road"},
    )
    return state, attacker, defender


def hold(state, side, card):
    state.decks.draw = [cid for cid in state.decks.draw if cid != card]
    state.decks.discard = [cid for cid in state.decks.discard if cid != card]
    state.decks.held[side] = [card]


def avoid(state, defender, **extra):
    return apply_action(
        state,
        {
            "type": "respond_avoid_battle",
            "side": state.lords[defender].side,
            "target_locale_id": "palencia",
            "way_type": "road",
            **extra,
        },
    )


@pytest.mark.parametrize("side", ["christian", "muslim"])
@pytest.mark.parametrize("hidden", [False, True])
def test_approach_keeps_enemy_mats_hidden_until_battle_is_chosen(side, hidden):
    state, attacker, defender = approach(side, hidden)
    saved = state.model_dump_json()
    for viewer, enemy in [(side, defender), (state.lords[defender].side, attacker)]:
        view = redacted_view(state, viewer)
        for key in ("forces", "assets", "routed_units", "capabilities", "vassals"):
            expected = None if hidden else state.model_dump()["lords"][enemy][key]
            assert view["lords"][enemy][key] == expected
        own = attacker if viewer == side else defender
        assert view["lords"][own]["forces"] == state.lords[own].forces
    assert state.model_dump_json() == saved


@pytest.mark.parametrize("side", ["christian", "muslim"])
@pytest.mark.parametrize("hidden", [False, True])
def test_reaction_window_and_defender_view_do_not_reveal_whether_card_is_held(side, hidden):
    empty, attacker, defender = approach(side, hidden)
    card = "C3" if side == "christian" else "M3"
    held = empty.model_copy(deep=True)
    hold(held, side, card)
    assert (
        avoid(empty, defender)
        == avoid(held, defender)
        == {"pending": "swollen_river_block", "waiting_on": side}
    )
    viewer = state_side = empty.lords[defender].side
    assert redacted_view(empty, viewer) == redacted_view(held, viewer)
    assert "blocker_card" not in redacted_view(held, viewer)["pending"]["payload"]
    assert redacted_view(held, side)["pending"]["payload"]["blocker_card"] == card
    assert empty.meta.active_player == held.meta.active_player == side
    assert legal_moves(empty) == [
        {"type": "respond_swollen_river_block", "side": side, "play": False}
    ]
    assert {move["play"] for move in legal_moves(held)} == {True, False}
    for state in (empty, held):
        before = state.model_dump_json()
        saved = GameState.model_validate_json(before)
        first = apply_action(
            state, {"type": "respond_swollen_river_block", "side": side, "play": False}
        )
        second = apply_action(
            saved, {"type": "respond_swollen_river_block", "side": side, "play": False}
        )
        assert first == second and state.model_dump_json() == saved.model_dump_json()
        assert state.lords[defender].cylinder.locale_id == "palencia"
        assert state.meta.active_player == side
    assert card in held.decks.held[side] and card not in empty.decks.held.get(side, [])
    assert redacted_view(empty, state_side) == redacted_view(held, state_side)


@pytest.mark.parametrize("side", ["christian", "muslim"])
def test_playing_card_is_public_consumes_it_once_and_blocks_the_avoid(side):
    state, _, defender = approach(side)
    card = "C3" if side == "christian" else "M3"
    hold(state, side, card)
    avoid(state, defender)
    saved = state.model_dump_json()
    with pytest.raises(IllegalAction):
        apply_action(
            state,
            {
                "type": "respond_swollen_river_block",
                "side": state.lords[defender].side,
                "play": True,
            },
        )
    assert state.model_dump_json() == saved
    result = apply_action(
        state, {"type": "respond_swollen_river_block", "side": side, "play": True}
    )
    assert result["swollen_river_played"] == card
    assert card not in state.decks.held[side] and state.decks.discard.count(card) == 1
    assert state.lords[defender].cylinder.locale_id != "palencia"
    assert card in redacted_view(state, state.lords[defender].side)["decks"]["discard"]


@pytest.mark.parametrize("side", ["christian", "muslim"])
def test_empty_hand_cannot_fabricate_a_block_and_rejected_retry_is_atomic(side):
    state, _, defender = approach(side)
    avoid(state, defender)
    before = state.model_dump_json()
    with pytest.raises(IllegalAction) as error:
        apply_action(state, {"type": "respond_swollen_river_block", "side": side, "play": True})
    assert error.value.code == "not_held" and state.model_dump_json() == before
    apply_action(state, {"type": "respond_swollen_river_block", "side": side, "play": False})
    assert state.lords[defender].cylinder.locale_id == "palencia"


@pytest.mark.parametrize("value", ["false", None, 1])
def test_bad_play_values_reject_without_consuming_a_card(value):
    state, _, defender = approach()
    hold(state, "christian", "C3")
    avoid(state, defender)
    before = state.model_dump_json()
    with pytest.raises(IllegalAction) as error:
        apply_action(
            state, {"type": "respond_swollen_river_block", "side": "christian", "play": value}
        )
    assert error.value.code == "bad_arg" and state.model_dump_json() == before


def test_invalid_declared_avoid_rejects_before_reaction_and_internal_flag_cannot_skip_window():
    state, _, defender = approach()
    hold(state, "christian", "C3")
    before = state.model_dump_json()
    with pytest.raises(IllegalAction):
        avoid(state, defender, target_locale_id="leon")
    assert state.model_dump_json() == before
    avoid(state, defender, _resolved_block=True)
    assert state.pending.kind == "swollen_river_block"
    assert state.lords[defender].cylinder.locale_id == "sahagun"


@pytest.mark.parametrize("timing", [False, True])
def test_committed_battle_reveals_only_participants_and_rehides_afterward(timing):
    state, attacker, defender = approach()
    bystander = state.lords["alvar_fanez"]
    bystander.cylinder = Cylinder(kind="locale", locale_id="sahagun")
    bystander.in_stronghold = True
    if timing:
        state.decks.this_levy_events["muslim"] = ["M7"]
    apply_combat_choices(
        state,
        {
            "type": "respond_stand_battle",
            "side": "muslim",
            "interactive_concede": True,
            "interactive_timing": timing,
        },
    )
    assert state.pending.kind == ("oneround_timing" if timing else "battle_concede")
    saved = GameState.model_validate_json(state.model_dump_json())
    for viewer, enemy in [("christian", defender), ("muslim", attacker)]:
        assert redacted_view(saved, viewer)["lords"][enemy]["forces"] == saved.lords[enemy].forces
    assert redacted_view(saved, "muslim")["lords"][bystander.id]["forces"] is None
    state.pending = None
    assert redacted_view(state, "muslim")["lords"][attacker]["forces"] is None


@pytest.mark.parametrize("engagement", ["battle", "storm", "relief"])
@pytest.mark.parametrize("fail", [False, True])
def test_actual_combat_scope_is_limited_to_state_participants_and_always_ends(
    engagement, fail, monkeypatch
):
    state, attacker, defender = approach()
    remote = state.lords["alvar_fanez"]
    remote.cylinder = Cylinder(kind="locale", locale_id="toledo")
    atk = battle.battleside_for_lords(state, [attacker], "christian", "attacker")
    dfd = battle.battleside_for_lords(state, [defender], "muslim", "defender")
    called = []

    def inspect():
        called.append(True)
        assert (
            redacted_view(state, "muslim")["lords"][attacker]["forces"]
            == state.lords[attacker].forces
        )
        assert (
            redacted_view(state, "christian")["lords"][defender]["forces"]
            == state.lords[defender].forces
        )
        assert redacted_view(state, "muslim")["lords"][remote.id]["forces"] is None
        copied = GameState.model_validate_json(state.model_dump_json())
        assert redacted_view(copied, "muslim")["lords"][attacker]["forces"] is None
        if fail:
            raise RuntimeError("stop combat inspection")

    if engagement == "battle":

        def run():
            return battle.resolve_battle(
                state, atk, dfd, max_rounds=1, before_strike=lambda *args: inspect()
            )
    else:
        name = "_storm_run_round" if engagement == "storm" else "_relief_run_round"
        original = getattr(battle, name)

        def observe(*args, **kwargs):
            inspect()
            return original(*args, **kwargs)

        monkeypatch.setattr(battle, name, observe)

        def run():
            if engagement == "storm":
                return battle.resolve_storm(state, atk, dfd, max_rounds=1)
            return battle.resolve_relief_sally(
                state,
                [attacker],
                [],
                [defender],
                besieger_side="muslim",
                locale_id="sahagun",
                max_rounds=1,
            )

    if fail:
        with pytest.raises(RuntimeError, match="stop combat inspection"):
            run()
    else:
        run()
    assert called
    assert redacted_view(state, "muslim")["lords"][attacker]["forces"] is None
