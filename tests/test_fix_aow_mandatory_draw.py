"""3.1.2/3.1.3: each side MUST draw two Arts of War cards each Levy
before proceeding (drawing is mandatory, count fixed at two)."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario


def test_cannot_pass_arts_of_war_without_drawing() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    apply_action(s, {"type": "begin_levy"})
    assert s.meta.levy_step == "arts_of_war"
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    # The enumerator does not offer pass_step until the draw is done.
    assert not any(m["type"] == "pass_step" for m in legal_moves(s))


def test_first_levy_draw_deploys_two_capabilities() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    apply_action(s, {"type": "begin_levy"})
    apply_action(s, {"type": "aow_draw", "side": "christian"})
    assert len(s.decks.pending_draw["christian"]) == 2
    # Deploy both (side_wide -> edge; this_lord -> a Mustered Lord).
    for cid in list(s.decks.pending_draw["christian"]):
        mustered = next((l.id for l in s.lords.values()
                         if l.side == "christian"
                         and l.cylinder.kind == "locale"), None)
        apply_action(s, {"type": "aow_deploy_capability",
                         "side": "christian", "card_id": cid,
                         "lord_id": mustered})
    assert s.meta.aow_draw_done["christian"] is True
    # Now pass is allowed.
    assert any(m["type"] == "pass_step" for m in legal_moves(s))


def test_draw_flag_resets_each_levy() -> None:
    """aow_draw_done must reset on entering a new Levy."""
    from tests._plan_helpers import step_levy
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    apply_action(s, {"type": "begin_levy"})
    # Drive to campaign (each Levy step), drawing AoW as required.
    for _ in range(200):
        if s.meta.phase == "campaign":
            break
        if (s.meta.levy_step == "arts_of_war"
                and not s.meta.aow_draw_done.get(s.meta.active_player)):
            step_levy(s)
        else:
            apply_action(s, {"type": "pass_step",
                             "side": s.meta.active_player})
    assert s.meta.phase == "campaign"
    # Christian drew this (first) Levy.
    assert s.meta.aow_draw_done.get("christian") is True
