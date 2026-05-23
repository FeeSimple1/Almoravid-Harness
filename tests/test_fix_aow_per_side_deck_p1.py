"""P-1 (combat playtest 2026-05-22): each side draws Arts of War cards
from ITS OWN deck (1.9.1 "Each side has its own deck"; 3.1.1 shuffle each
side's unused cards; 3.1.2/3.1.3 draw from the player's own deck).

Regression: decks.draw is a single shared pile. _h_aow_draw only rebuilt
it when empty, so after the Christian player drew (leaving Christian cards
on the pile) the Muslim player drew those leftover *Christian* cards. Now
aow_draw collects+shuffles the acting side's own deck before every draw.
"""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.static_data import load_cards


def _card_side(cid: str) -> str:
    return load_cards()["cards"][cid]["side"]


def _to_arts_of_war(s):
    apply_action(s, {"type": "begin_levy"})
    assert s.meta.levy_step == "arts_of_war"


def test_muslim_draws_muslim_cards_after_christian_draws() -> None:
    """The exact playtest sequence: Christian draws+deploys, passes, then
    the Muslim player draws -- and must get Muslim (M) cards, not the
    Christian leftovers on the shared pile."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    _to_arts_of_war(s)

    # Christian draws two and deploys both (first Levy = Capabilities).
    res_c = apply_action(s, {"type": "aow_draw", "side": "christian"})
    assert all(_card_side(c) == "christian" for c in res_c["drawn"])
    for cid in list(s.decks.pending_draw["christian"]):
        # Deploy each drawn card (lord target only matters for this_lord).
        act = {"type": "aow_deploy_capability", "side": "christian",
               "card_id": cid, "lord_id": "alfonso"}
        apply_action(s, act)
    apply_action(s, {"type": "pass_step", "side": "christian"})

    # Now the Muslim player draws -- must be Muslim cards.
    res_m = apply_action(s, {"type": "aow_draw", "side": "muslim"})
    assert res_m["drawn"], "Muslim drew nothing"
    assert all(_card_side(c) == "muslim" for c in res_m["drawn"]), (
        f"Muslim drew non-Muslim cards: {res_m['drawn']}")
    assert all(_card_side(c) == "muslim" for c in s.decks.pending_draw["muslim"])


def test_aow_draw_rebuilds_acting_side_deck_even_when_pile_nonempty() -> None:
    """Directly: seed the shared pile with the opponent's cards, then have
    the Muslim side draw -- the draw must rebuild to the Muslim deck."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    s.meta.phase = "levy"
    s.meta.levy_step = "arts_of_war"
    s.meta.active_player = "muslim"
    # Stale shared pile holds Christian cards (the bug's precondition).
    s.decks.draw = ["C3", "C4", "C5", "C6"]
    res = apply_action(s, {"type": "aow_draw", "side": "muslim"})
    assert all(_card_side(c) == "muslim" for c in res["drawn"]), res["drawn"]
