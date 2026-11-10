"""DECISION-009 — Crossbow Hit target selection policy (4.4.2).

The firing side selects which Enemy unit rolls Protection for each
Crossbow Hit. Standing policy: 'weakest_first' (default, historical)
or 'armored_first' (the Background Book Játiva play). Storm attackers
must take Hits on Armored units while any remain."""
from __future__ import annotations

import pytest

from almoravid import battle
from almoravid.battle import BattleSide, _resolve_protection_roll
from almoravid.scenarios import load_scenario
from almoravid.state import GameState
from tests.combat_choices import apply_combat_choices
from tests.test_round7_storm import _storm_position


def _target_side():
    return BattleSide(
        side="christian", role="attacker", lord_ids=["alvar_fanez"],
        forces={"knights": 1, "men_at_arms": 1, "serfs": 1, "militia": 1})


@pytest.mark.parametrize(("context", "role"), [
    ("battle", "attacker"), ("battle", "defender"), ("storm", "defender"),
])
def test_default_weakest_first_can_pick_serfs(context, role) -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    tgt = _target_side()
    tgt.role = role
    _, routed = _resolve_protection_roll(
        s, tgt, "missiles", context=context, striker_selects=True,
        striker_minus_armor=1)
    # auto_remove Serfs picked and removed without a die.
    assert routed == "serfs"
    assert s.meta.rng_state == 0


def test_armored_first_picks_lowest_armor_band() -> None:
    """armored_first targets Men-at-Arms (Armor 1-3) before Knights
    (1-4) and before any Unarmored — the Játiva Round 1 selection."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.crossbow_target_policy["muslim"] = "armored_first"
    tgt = _target_side()
    _, routed = _resolve_protection_roll(
        s, tgt, "missiles", context="storm", striker_selects=True,
        striker_minus_armor=1)
    # A die was rolled against the Men-at-Arms (1-2 after -1 Armor):
    # it either stands (routed None) or the MaA routs — never another
    # unit type, and never the free Serfs kill.
    assert routed in (None, "men_at_arms")
    assert s.meta.rng_state == 1
    assert tgt.forces.get("serfs") == 1


@pytest.mark.parametrize(("policy", "first_unit", "last_unit", "next_unit", "expected_rolls"), [
    ("weakest_first", "knights", "men_at_arms", "serfs", 3),
    ("armored_first", "men_at_arms", "knights", "militia", 4),
])
def test_crossbow_policy_selects_within_storm_attackers_armored_units(
    policy, first_unit, last_unit, next_unit, expected_rolls,
):
    state = load_scenario("scenario_a_toledo_beset", seed=1)
    state.meta.crossbow_target_policy["muslim"] = policy
    target = _target_side()
    routed = []
    for _ in range(3):
        _, unit = _resolve_protection_roll(
            state, target, "missiles", context="storm", striker_selects=True,
            striker_minus_armor=1,
        )
        routed.append(unit)
        assert target.forces["serfs"] == target.forces["militia"] == 1

    # Seed 1 rolls 5, 1, 5. Each policy selects its own Armored order.
    assert routed == [first_unit, None, last_unit]
    assert state.meta.rng_state == 3
    _, unit = _resolve_protection_roll(
        state, target, "missiles", context="storm", striker_selects=True,
        striker_minus_armor=1,
    )
    assert unit == next_unit and state.meta.rng_state == expected_rolls


@pytest.mark.parametrize("policy", ["weakest_first", "armored_first"])
def test_public_storm_garrison_crossbows_target_armored_units_after_reload(policy, monkeypatch):
    state = _storm_position(1, "zaragoza", 1, "alfonso")
    state.meta.crossbow_target_policy["muslim"] = policy
    state = GameState.model_validate_json(state.model_dump_json())
    observed = []
    original = battle._resolve_protection_roll

    def observe(current, target, kind, **kwargs):
        before = dict(target.forces)
        before_roll = current.meta.rng_state
        result = original(current, target, kind, **kwargs)
        if kwargs.get("striker_selects") and target.role == "attacker":
            observed.append((before, result[1], current.meta.rng_state - before_roll))
        return result

    monkeypatch.setattr(battle, "_resolve_protection_roll", observe)
    result = apply_combat_choices(state, {"type": "cmd_storm", "side": "christian"})

    assert result["rounds"] == 1
    before, routed, rolls = observed[0]
    assert before == {"knights": 1, "men_at_arms": 1, "serfs": 1}
    assert routed in ("knights", "men_at_arms") and rolls == 1


def test_set_absorption_policy_action_carries_crossbow_key() -> None:
    from almoravid.actions import apply_action
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    r = apply_action(s, {"type": "set_absorption_policy",
                         "side": "muslim",
                         "crossbow_target_policy": "armored_first"})
    assert r["crossbow_target_policy"] == "armored_first"
    assert s.meta.crossbow_target_policy["muslim"] == "armored_first"
    # absorption policy untouched
    assert s.meta.absorption_policy["muslim"] == "weakest_first"
