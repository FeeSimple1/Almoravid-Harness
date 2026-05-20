"""L13: Arts of War draw -> deploy Capabilities (3.1.2, first Levy) or
implement Events (3.1.3, later Levies)."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario


def _arts_of_war(s, first_levy=True):
    s.meta.phase = "levy"
    s.meta.levy_step = "arts_of_war"
    s.meta.active_player = "christian"
    s.meta.first_levy_done = not first_levy
    s.decks.board_edge.setdefault("christian", [])


def test_first_levy_deploys_side_wide_capability_to_edge() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _arts_of_war(s, first_levy=True)
    s.decks.pending_draw["christian"] = ["C15"]   # side_wide
    apply_action(s, {"type": "aow_deploy_capability", "side": "christian",
                     "card_id": "C15"})
    assert "C15" in s.decks.board_edge["christian"]
    assert any(c.card_id == "C15" for c in s.decks.capabilities_in_play)
    assert s.decks.pending_draw["christian"] == []


def test_first_levy_deploys_this_lord_capability_to_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _arts_of_war(s, first_levy=True)
    s.decks.pending_draw["christian"] = ["C1"]    # this_lord
    lid = next(l.id for l in s.lords.values()
               if l.side == "christian" and l.cylinder.kind == "locale")
    apply_action(s, {"type": "aow_deploy_capability", "side": "christian",
                     "card_id": "C1", "lord_id": lid})
    assert "C1" in s.lords[lid].capabilities
    assert s.decks.pending_draw["christian"] == []


def test_pass_step_blocked_until_pending_processed() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _arts_of_war(s, first_levy=True)
    s.decks.pending_draw["christian"] = ["C15"]
    types = {m["type"] for m in legal_moves(s)}
    assert "pass_step" not in types
    assert any(m["type"] == "aow_deploy_capability" for m in legal_moves(s))
    apply_action(s, {"type": "aow_deploy_capability", "side": "christian",
                     "card_id": "C15"})
    types2 = {m["type"] for m in legal_moves(s)}
    assert "pass_step" in types2


def test_later_levy_implements_event_in_draw_order() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _arts_of_war(s, first_levy=False)
    s.decks.pending_draw["christian"] = ["C9", "C2"]   # immediate events
    # Out-of-order rejected.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "aow_implement_event", "side": "christian",
                         "card_id": "C2"})
    assert ei.value.code == "out_of_order"
    # In-order succeeds and pops the queue.
    apply_action(s, {"type": "aow_implement_event", "side": "christian",
                     "card_id": "C9"})
    assert s.decks.pending_draw["christian"] == ["C2"]
    apply_action(s, {"type": "aow_implement_event", "side": "christian",
                     "card_id": "C2"})
    assert s.decks.pending_draw["christian"] == []


def test_first_levy_rejects_event_implementation() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _arts_of_war(s, first_levy=True)
    s.decks.pending_draw["christian"] = ["C9"]
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "aow_implement_event", "side": "christian",
                         "card_id": "C9"})
    assert ei.value.code == "first_levy_caps_only"
