"""C1/M1 Hills: eligible profiles improve before overlapping missiles combine."""

from dataclasses import asdict

import pytest

from almoravid import battle
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, GameState
from tests.combat_choices import apply_combat_choices


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("seed", [1, 7])
@pytest.mark.parametrize("caps,base,boosted", [
    (["M3"], 3, 3),                     # Three Javelins: explicitly unaffected.
    (["M4"], 1.5, 3),                   # Bowmen, including Light Horse.
    (["M7"], 2, 3),                     # Two Slingers become x1.5.
    (["M2"], 1, 2),                     # Two Crossbowmen become x1.
    (["M3", "M2"], 3, 3),               # Same Militia have both; x1 once.
    (["M3", "M7"], 3, 4),               # Militia Slingers x1.5, Horse Javelin x1.
])
def test_hills_respects_each_missile_profile_in_public_battle(multi, seed, caps, base, boosted):
    observations = []
    for play in (False, True):
        state = load_scenario("scenario_a_toledo_beset", seed=seed)
        participants = ["alfonso", "al_mutamid"]
        if multi:
            participants += ["alvar_fanez", "al_mustain"]
            state.locales["toledo"].siege_yellow = 0
            state.lords["al_mustain"].forces = {"men_at_arms": 1}
        for lid in participants:
            state.lords[lid].cylinder = Cylinder(kind="locale", locale_id="transduero")
            state.lords[lid].in_stronghold = False
        state.lords["al_mutamid"].forces = {"light_horse": 1, "militia": 2}
        for cid in [*caps, "M1"]:
            for pile in [state.decks.draw, state.decks.discard, *state.decks.held.values()]:
                while cid in pile:
                    pile.remove(cid)
            if cid == "M1":
                state.decks.held.setdefault("muslim", []).append(cid)
            else:
                state.lords["al_mutamid"].capabilities.append(cid)
                state.decks.capabilities_in_play.append(CardInPlay(
                    card_id=cid, scope="this_lord", owner_side="muslim",
                    owner_lord_id="al_mutamid"))
        state.meta.phase, state.meta.campaign_step = "campaign", "activation"
        state.meta.active_player, state.meta.active_lord_id = "christian", "alfonso"
        state.meta.actions_remaining, state.pending = 3, None
        replay = GameState.model_validate_json(state.model_dump_json())
        trace = []
        original = battle._resolve_step

        def observe(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1] == "1.a" and kwargs.get("round_index") == 1:
                trace.append(asdict(result))
            return result

        action = {"type": "cmd_battle", "side": "christian", "attacker_concede_round": 1}
        battle._resolve_step = observe
        try:
            result = apply_combat_choices(state, action, cards=["M1"] if play else [])
        finally:
            battle._resolve_step = original
        assert apply_combat_choices(replay, action, cards=["M1"] if play else []) == result
        assert state.model_dump_json() == replay.model_dump_json()
        observations.append(trace[0]["raw_hits"])
    assert observations == [base, boosted]
