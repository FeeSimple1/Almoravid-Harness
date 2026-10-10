"""Original seed-137 rules assertions; fixtures preserve the reached board/RNG.

The board-edge absence check accepts a missing empty-side bucket, not only an
empty list: fixing M15's scope means its acquisition need not create that bucket.
All rule assertions and action payloads otherwise match the original evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from almoravid.actions import (  # noqa: E402
    IllegalAction, _rebuild_aow_deck, _unused_capability_cards, apply_action,
)
from almoravid.legal_moves import legal_moves  # noqa: E402
from almoravid.state import GameState  # noqa: E402

HERE = Path(__file__).parent / "fixtures" / "scenario_f_seed137"
ACTIONS = {int(k): v for k, v in json.loads((HERE / "actions.json").read_text()).items()}


def position(n: int) -> GameState:
    return GameState.model_validate_json(
        (HERE / f"before-{n:04d}.json").read_text()
    )


@pytest.mark.parametrize("n,cid", [(25, "M15"), (350, "M20")])
def test_this_lord_troop_card_goes_on_the_acquiring_lords_mat(n, cid):
    """M15/M20 printed text: 'This Lord', not a side-wide capability."""
    state = position(n)
    action = ACTIONS[n]
    apply_action(state, action)
    assert cid in state.lords[action["lord_id"]].capabilities
    assert cid not in state.decks.board_edge.get("muslim", [])


def test_saqalibah_cannot_grant_troops_to_an_unrelated_lord():
    """Legal branch defers free use until al-Mundir is in play elsewhere."""
    state = GameState.model_validate_json(
        (HERE / "deferred-saqalibah.json").read_text()
    )
    assert state.lords["al_mundir"].capabilities == []
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalAction):
        apply_action(state, {
            "type": "cap_saqalibah", "side": "muslim", "lord_id": "al_mundir"
        })
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("cid", ["M15", "M20"])
def test_discarded_troop_capability_does_not_keep_old_used_flag(cid):
    """Discarded card use must not disable a later new acquisition."""
    state = position(610)
    assert state.meta.aow_cap_state.get(cid + "_used") is True
    apply_action(state, ACTIONS[610])
    assert cid not in state.decks.board_edge.get("muslim", [])
    assert not state.meta.aow_cap_state.get(cid + "_used", False)


def campaign_entry() -> GameState:
    state = position(558)
    assert state.decks.board_edge["christian"] == ["C22", "C18", "C23", "C20"]
    apply_action(state, ACTIONS[558])
    return state


def test_milites_cannot_go_to_ordinary_discard():
    """C18's discard removes the card permanently, not to the used pile.

    A future implementation may defer the player's discard selection instead
    of auto-discarding. Keeping C18 in play pending that choice is also valid;
    putting it into the ordinary discard pile is never valid.
    """
    state = campaign_entry()
    assert "C18" not in state.decks.discard
    assert ("C18" in state.decks.board_edge["christian"]
            or "C18" in state.decks.removed_from_game)


def test_milites_cannot_reenter_draw_pool_after_campaign_boundary():
    state = campaign_entry()
    _rebuild_aow_deck(state, "christian")
    assert "C18" not in state.decks.draw


def test_milites_cannot_reenter_available_capability_pool():
    state = campaign_entry()
    assert "C18" not in _unused_capability_cards(state, "christian")


def test_fueros_menu_does_not_offer_it_to_sancho():
    """C20 explicitly says only Alfonso may Levy and use Fueros."""
    state = position(449)
    assert ACTIONS[449] not in legal_moves(state)


def test_fueros_executor_rejects_sancho_without_spending_lordship():
    state = position(449)
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalAction):
        apply_action(state, ACTIONS[449])
    assert state.model_dump(mode="json") == before


def test_excess_capability_discard_does_not_silently_choose_for_player():
    """Rule 4.0: owner selects cards, Christian first. Passing the last
    Call-to-Arms step did not designate any cards for discard.
    """
    state = position(558)
    cards = list(state.decks.board_edge["christian"])
    apply_action(state, ACTIONS[558])
    assert state.decks.board_edge["christian"] == cards, (
        "Engine selected which three of four different capabilities to discard "
        "without first asking their owner."
    )
