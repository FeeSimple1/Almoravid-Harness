"""L2b / 3.5.3: "This Levy" Events (e.g. C19 Fitna) apply for the Levy
(banning Muster of named Lords) and their effect clears at the end of
the Levy — and with L13 they are now reachable via the AoW draw."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.scenarios import load_scenario


def test_this_levy_event_sets_muster_ban_and_blocks_muster() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.phase = "levy"
    s.meta.levy_step = "arts_of_war"
    s.meta.active_player = "christian"
    s.meta.first_levy_done = True               # later Levy -> implement
    s.decks.pending_draw["christian"] = ["C19"]  # Fitna ("This Levy")
    r = apply_action(s, {"type": "aow_implement_event", "side": "christian",
                         "card_id": "C19"})
    banned = s.meta.muster_banned_this_levy_lord_ids
    assert len(banned) == 2                      # 2 Taifa Lords banned
    # A banned Lord may not Muster this Levy (3.1.3 / muster handler).
    s.meta.levy_step = "muster"
    s.meta.active_player = "muslim"
    target = banned[0]
    # Put a Levying Lord on the map so muster_lord reaches the ban check.
    levier = next(l.id for l in s.lords.values()
                  if l.side == "muslim" and l.cylinder.kind == "locale"
                  and l.id not in banned)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "muster_lord", "side": "muslim",
                         "lord_id": target, "levying_lord_id": levier,
                         "seat": s.lords[target].seats[0]})
    assert ei.value.code == "muster_banned"


def test_muster_ban_resets_entering_campaign() -> None:
    """The 'This Levy' ban does not leak past the Levy: the Levy ->
    Campaign transition clears muster_banned_this_levy_lord_ids."""
    from almoravid.actions import _advance_step_if_both_done
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.muster_banned_this_levy_lord_ids = ["al_mustain", "abu_bakr"]
    # Drive the last Levy step's both-sides-done transition into Campaign.
    s.meta.phase = "levy"
    s.meta.levy_step = "call_to_arms"   # last Levy step
    s.meta.levy_step_completed_christian = True
    s.meta.levy_step_completed_muslim = True
    _advance_step_if_both_done(s)
    assert s.meta.phase == "campaign"
    assert s.meta.muster_banned_this_levy_lord_ids == []
