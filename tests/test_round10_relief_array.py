"""Relief Sally follows the normal Front and Reserve geometry."""

import pytest

from almoravid import battle
from almoravid.actions import apply_action
from almoravid.state import GameState
from almoravid.static_data import load_lords
from tests.combat_choices import apply_combat_choices
from tests.test_cross_game_avoid_retreat_surrender import place, position


def _approach(*, mounted=False, full_defenders=False):
    state = position(seed=1 if mounted else 7)
    marchers = ["alfonso", "alvar_fanez"]
    if mounted:
        marchers += ["garcia_ordonez", "sancho"]
    for lid in marchers:
        place(state, lid, "leon")
        state.lords[lid].forces = {"knights": 1} if mounted else {"men_at_arms": 1}
    defenders = ["al_mustain", "al_mutamid"]
    if full_defenders:
        defenders += ["abu_bakr", "al_mundir"]
    native = load_lords()["lords"]
    for lid in defenders:
        place(state, lid, "zamora")
        if full_defenders:
            state.lords[lid].forces = dict(native[lid]["forces"])
        else:
            state.lords[lid].forces = {"militia": 1} if mounted else {"light_horse": 1}
    place(state, "pedro_ansurez", "zamora")
    state.lords["pedro_ansurez"].forces = {"men_at_arms": 1}
    state.lords["pedro_ansurez"].in_stronghold = True
    state.locales["zamora"].siege_green = 2
    apply_action(state, {
        "type": "cmd_march", "side": "christian", "target_locale_id": "zamora",
        "way_type": "road", "group_lord_ids": marchers[1:],
    })
    return state


def _stand(state, **options):
    return apply_combat_choices(state, {
        "type": "respond_stand_battle", "side": "muslim", **options,
    }, sallyers=["pedro_ansurez"])


def _round(state, *, conceder=None):
    receipt = apply_action(state, {
        "type": "relief_concede", "side": "christian",
        "attacker_concede": conceder == "attacker",
    })
    if conceder != "attacker":
        receipt = apply_action(state, {
            "type": "relief_concede", "side": "muslim",
            "defender_concede": conceder == "defender",
        })
    return receipt


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("mounted", [False, True])
def test_relief_strikes_use_opposed_lords_and_exclude_reserves(monkeypatch, interactive, mounted):
    state = _approach(mounted=mounted)
    strikes = []
    original = battle._resolve_step

    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.step == ("2.b" if mounted else "2.a") and kwargs["round_index"] == 1:
            strikes.append((result.raw_hits, result.rounded_hits))
        return result

    monkeypatch.setattr(battle, "_resolve_step", observe)
    conceder = "defender" if mounted else "attacker"
    if interactive:
        _stand(state, interactive_concede=True)
        state = GameState.model_validate_json(state.model_dump_json())
        result = _round(state, conceder=conceder)
    else:
        result = _stand(state, **{f"{conceder}_concede_round": 1})
    assert result["rounds"] == 1
    # Two defending Light Horse face separate Lords, so each half-Hit
    # rounds up. Three Front Knights Strike for six, with Sancho in Reserve.
    assert strikes[0] == ((6.0, 6) if mounted else (1.0, 2))


def test_relief_reserve_advances_after_front_rout_from_a_saved_round(monkeypatch):
    state = _approach(mounted=True, full_defenders=True)
    _stand(state, interactive_concede=True)
    _round(state)
    assert state.pending.kind == "relief_concede"
    assert state.pending.payload["round_idx"] == 2
    snapshot = state.pending.payload["rs"]
    assert snapshot["lf"]["M"] == {
        "alfonso": {}, "alvar_fanez": {}, "garcia_ordonez": {}, "sancho": {"knights": 1},
    }
    assert next(lp for lp in snapshot["marchers"]["array"] if lp["lord_id"] == "sancho")[
        "position"
    ] == "reserve"

    original = battle._resolve_step
    fronts = []

    def observe(*args, **kwargs):
        if args[1] == "1.a":
            fronts.extend((lp.lord_id, lp.position) for lp in args[5].array
                          if lp.has_unrouted())
        return original(*args, **kwargs)

    monkeypatch.setattr(battle, "_resolve_step", observe)
    restored = GameState.model_validate_json(state.model_dump_json())
    # Older saves have the same per-Lord Forces/Routed maps without slots.
    legacy = restored.model_copy(deep=True)
    for key in ("marchers", "sallyers", "def_front", "def_rear"):
        row = legacy.pending.payload["rs"][key]
        if row is not None:
            row["array"] = None
    result = _round(restored, conceder="defender")
    assert fronts and set(fronts) == {("sancho", "front_center")}
    fronts.clear()
    assert result == _round(legacy, conceder="defender")
    assert restored.lords == legacy.lords
    assert restored.meta.rng_state == legacy.meta.rng_state
    assert fronts and set(fronts) == {("sancho", "front_center")}
