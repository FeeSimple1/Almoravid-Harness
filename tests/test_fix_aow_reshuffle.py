"""3.1.1: each Levy, collect and shuffle ALL unused cards into the draw
deck, excluding Held Events, in-play Capabilities, and pending cards.
Used immediate Events (in discard) are recycled."""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay


def _aow(s):
    s.meta.phase = "levy"
    s.meta.levy_step = "arts_of_war"
    s.meta.active_player = "christian"


def test_reshuffle_recycles_discarded_immediate_and_excludes_in_play() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _aow(s)
    # C9 is a Christian immediate event used last Levy -> sits in discard.
    s.decks.discard = ["C9"]
    # C15 deployed as a side-wide Capability (in play) -> excluded.
    s.decks.board_edge["christian"] = ["C15"]
    s.decks.capabilities_in_play = [CardInPlay(
        card_id="C15", scope="side_wide", owner_side="christian",
        owner_lord_id=None)]
    # C20 held this Levy -> excluded.
    s.decks.this_levy_events["christian"] = ["C20"]
    apply_action(s, {"type": "aow_shuffle", "side": "christian"})
    draw = set(s.decks.draw)
    assert "C9" in draw           # recycled immediate Event
    assert "C15" not in draw      # Capability in play
    assert "C20" not in draw      # Held Event
    # Deck holds only Christian cards.
    from almoravid.static_data import load_cards
    cards = load_cards()["cards"]
    assert all(cards[c]["side"] == "christian" for c in draw)
