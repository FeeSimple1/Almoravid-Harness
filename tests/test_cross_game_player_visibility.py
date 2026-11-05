"""Cross-game IF-1/IF-2: controller state must not leak through player views."""
import pytest

from almoravid.actions import apply_action
from almoravid.rng import roll_d6_n
from almoravid.scenarios import load_scenario
from almoravid.state import GameState, PendingDecision
from almoravid.views import redacted_view


@pytest.mark.parametrize("side", ["christian", "muslim"])
@pytest.mark.parametrize("hidden_mats", [False, True])
def test_player_view_omits_rng_without_changing_save_or_future_rolls(side, hidden_mats):
    state = load_scenario("scenario_a_toledo_beset", seed=947)
    state.meta.hidden_mats = hidden_mats
    roll_d6_n(state, 11)
    before = state.model_dump_json()
    restored = GameState.model_validate_json(before)
    view = redacted_view(state, side)
    assert "seed" not in view["meta"]
    assert "rng_state" not in view["meta"]
    assert view["history"][0]["args"]["scenario"] == "scenario_a_toledo_beset"
    assert all("seed" not in h["args"] and "rng_state" not in h["args"]
               for h in view["history"])
    assert state.model_dump_json() == before
    assert state.meta.seed == 947 and state.meta.rng_state == 11
    assert roll_d6_n(state, 10) == roll_d6_n(restored, 10)


def capability_state():
    state = load_scenario("scenario_a_toledo_beset", seed=1)
    state.meta.hidden_mats = True
    state.meta.phase = "levy"
    state.meta.levy_step = "muster"
    state.meta.active_player = "christian"
    # Deploy both through the real action path; only the mat card is hidden.
    for card in ("C23", "C3"):
        apply_action(state, {"type": "levy_take_capability", "side": "christian",
                             "lord_id": "alfonso", "card_id": card})
    return state


def test_hidden_capability_is_masked_in_registry_and_deployment_history():
    state = capability_state()
    before = state.model_dump_json()
    view = redacted_view(state, "muslim")
    assert view["lords"]["alfonso"]["capabilities"] is None
    assert "C3" not in [c["card_id"] for c in view["decks"]["capabilities_in_play"]]
    assert "C23" in [c["card_id"] for c in view["decks"]["capabilities_in_play"]]
    assert view["decks"]["board_edge"]["christian"] == state.decks.board_edge["christian"]
    assert view["history"][-1]["args"] == {}
    assert "C3" not in view["history"][-1]["summary"]
    assert state.model_dump_json() == before
    # The owner retains the full card and action, including card parameters.
    own = redacted_view(state, "christian")
    assert "C3" in own["lords"]["alfonso"]["capabilities"]
    assert own["decks"]["capabilities_in_play"] == state.model_dump()["decks"]["capabilities_in_play"]
    assert own["history"][-1]["args"]["card_id"] == "C3"


@pytest.mark.parametrize("kind", ["march_arrival_response", "battle_concede", "storm_concede"])
def test_combat_reveals_registry_and_hides_it_again_afterward(kind):
    state = capability_state()
    state.pending = PendingDecision(kind=kind, waiting_on="muslim",
        payload={"locale_id": state.lords["alfonso"].cylinder.locale_id})
    view = redacted_view(state, "muslim")
    assert "C3" in view["lords"]["alfonso"]["capabilities"]
    assert "C3" in [c["card_id"] for c in view["decks"]["capabilities_in_play"]]
    state.pending = None
    assert "C3" not in [c["card_id"] for c in redacted_view(state, "muslim")["decks"]["capabilities_in_play"]]


def test_open_mats_preserve_opponent_capability_registry():
    state = capability_state()
    state.meta.hidden_mats = False
    view = redacted_view(state, "muslim")
    assert view["decks"]["capabilities_in_play"] == state.model_dump()["decks"]["capabilities_in_play"]
    assert view["history"][-1]["args"]["card_id"] == "C3"
