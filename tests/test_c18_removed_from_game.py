"""C18 Milites is removed from the game when discarded (AoW reference:
"discard removes the card from the game ... removes Event #C18 Runaway
Slaves with it"). It must NOT recycle into a later Campaign's draw deck.
"""
from __future__ import annotations

from almoravid.actions import _rebuild_aow_deck
from almoravid.campaign import winter_disband
from almoravid.scenarios import load_scenario


def test_c18_discard_removes_from_game_and_blocks_recycle() -> None:
    s = load_scenario("scenario_f_reconquista")
    # Ensure C18 Milites is sitting at the Christian board edge.
    s.decks.board_edge.setdefault("christian", [])
    if "C18" not in s.decks.board_edge["christian"]:
        s.decks.board_edge["christian"].append("C18")

    res = winter_disband(s)

    assert "C18" in s.decks.removed_from_game
    assert "C18" not in s.decks.discard
    assert "C18" in res["board_edge_removed_from_game"]

    # A fresh deck rebuild for the next Campaign must exclude C18 entirely.
    _rebuild_aow_deck(s, "christian")
    assert "C18" not in s.decks.draw
