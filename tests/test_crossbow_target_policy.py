"""DECISION-009 — Crossbow Hit target selection policy (4.4.2).

The firing side selects which Enemy unit rolls Protection for each
Crossbow Hit. Standing policy: 'weakest_first' (default, historical)
or 'armored_first' (the Background Book Játiva play)."""
from __future__ import annotations

from almoravid.battle import BattleSide, _resolve_protection_roll
from almoravid.scenarios import load_scenario


def _target_side():
    return BattleSide(
        side="christian", role="attacker", lord_ids=["alvar_fanez"],
        forces={"knights": 1, "men_at_arms": 1, "serfs": 1, "militia": 1})


def test_default_weakest_first_picks_serfs() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    tgt = _target_side()
    _, routed = _resolve_protection_roll(
        s, tgt, "missiles", context="storm", striker_selects=True,
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
