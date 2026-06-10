"""Rule 5.2: a side reduced to zero Mustered Lords on the map at ANY moment
during the Campaign loses immediately. Previously only checked at Campaign
entry and final scoring, so an elimination mid-Campaign was missed.
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder
from tests.test_phase6b_approach import _activate_lord_at_locale


def test_zero_mustered_lords_mid_campaign_ends_game() -> None:
    s = _activate_lord_at_locale("scenario_a_toledo_beset", "alfonso",
                                 "leon", seed=11)
    assert s.meta.phase == "campaign"
    # Eliminate every Muslim Lord from the map (simulate Battle/Disband
    # removals) — leave the Campaign otherwise mid-flight.
    for lo in s.lords.values():
        if lo.side == "muslim":
            lo.cylinder = Cylinder(kind="calendar", box=10)
    # Apply ANY legal Christian action; the post-handler 5.2 check fires.
    mv = next(m for m in legal_moves(s)
              if m["type"] in ("cmd_pass", "end_card"))
    apply_action(s, mv)
    assert s.meta.phase == "ended", "5.2 immediate victory was not triggered"
    # Christian wins (Muslims have no Mustered Lords).
    assert s.score.winner == "christian"


def test_campaign_continues_while_both_sides_have_lords() -> None:
    s = _activate_lord_at_locale("scenario_a_toledo_beset", "alfonso",
                                 "leon", seed=11)
    assert s.meta.phase == "campaign"
    mv = next(m for m in legal_moves(s)
              if m["type"] in ("cmd_pass", "end_card"))
    apply_action(s, mv)
    assert s.meta.phase != "ended"     # both sides still have Lords
