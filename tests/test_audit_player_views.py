"""Audit regressions: combat Mats stay visible and unused Plans stay private."""
import pytest

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import HistoryEntry, PendingDecision, PlanEntry
from almoravid.views import redacted_view
from tests.test_interactive_approach_battle import _march_into_battle


def test_approach_mats_remain_visible_during_interactive_battle():
    state = _march_into_battle()
    state.meta.hidden_mats = True
    apply_action(state, {"type": "respond_stand_battle", "side": "muslim",
                         "interactive_concede": True})
    assert state.pending.kind == "battle_concede"
    view = redacted_view(state, "christian")
    assert view["lords"]["al_mutamid"]["forces"] == state.lords["al_mutamid"].forces
    assert "hidden_mat" not in view["lords"]["al_mutamid"]


@pytest.mark.parametrize("kind,key", [("battle_concede", "here"),
    ("storm_concede", "here"), ("relief_concede", "locale_id")])
def test_interactive_combat_reveals_mats_until_pending_cleared(kind, key):
    state = load_scenario("scenario_a_toledo_beset")
    state.meta.hidden_mats = True
    lord = state.lords["al_mutamid"]
    state.pending = PendingDecision(kind=kind, waiting_on="christian",
                                   payload={key: lord.cylinder.locale_id})
    assert redacted_view(state, "christian")["lords"][lord.id]["forces"] == lord.forces
    state.pending = None
    assert redacted_view(state, "christian")["lords"][lord.id]["forces"] is None


@pytest.mark.parametrize("hidden_mats", [True, False])
@pytest.mark.parametrize("viewer,opponent", [("christian", "muslim"),
                                            ("muslim", "christian")])
def test_private_cards_and_history_do_not_reveal_enemy_future_plan(hidden_mats, viewer, opponent):
    state = load_scenario("scenario_a_toledo_beset")
    state.meta.hidden_mats = hidden_mats
    own = "alfonso" if viewer == "christian" else "al_mutamid"
    enemy = "al_mutamid" if viewer == "christian" else "alfonso"
    card = "M12" if opponent == "muslim" else "C14"
    state.decks.plan[viewer] = [PlanEntry(kind="command", lord_id=own)]
    state.decks.plan[opponent] = [PlanEntry(kind="pass"),
                                PlanEntry(kind="command", lord_id=enemy)]
    setattr(state.meta, f"plan_index_{opponent}", 1)
    state.decks.pending_draw[opponent] = [card]
    state.decks.held[opponent] = [card]
    state.decks.draw = ["C1", "C2"]
    for action, args, summary in [
        ("plan_add_card", {"lord_id": enemy}, f"adds command for {enemy}"),
        ("aow_draw", {}, f"draws {card}"),
        ("aow_implement_event", {"card_id": card}, f"holds {card}"),
    ]:
        state.history.append(HistoryEntry(turn_index=1, actor=opponent,
                                         action=action, args=args, summary=summary))
    state.history.append(HistoryEntry(turn_index=1, actor=opponent,
                                     action="command_reveal", summary="reveals pass"))
    before = state.model_dump()
    view = redacted_view(state, viewer)
    assert view["decks"]["plan"][viewer] == before["decks"]["plan"][viewer]
    assert view["decks"]["plan"][opponent] == [{"kind": "pass", "lord_id": None}, None]
    assert view["decks"]["pending_draw"][opponent] is None
    assert view["decks"]["held"][opponent] is None
    assert view["decks"]["draw"] is None
    for entry in view["history"][-4:-1]:
        assert entry["args"] == {}
        assert enemy not in entry["summary"]
        assert card not in entry["summary"]
    assert view["history"][-1]["summary"] == "reveals pass"
    assert state.model_dump() == before


def test_implicit_drawn_card_id_is_not_leaked_through_history():
    state = load_scenario("scenario_a_toledo_beset")
    state.meta.first_levy_done = True
    state.meta.phase = "levy"
    state.meta.levy_step = "arts_of_war"
    state.meta.active_player = "christian"
    state.decks.pending_draw["christian"] = ["C18"]
    apply_action(state, {"type": "aow_implement_event", "side": "christian"})
    assert "C18" in state.decks.held["christian"]
    view = redacted_view(state, "muslim")
    assert "C18" not in view["history"][-1]["summary"]
    assert view["history"][-1]["args"] == {}
