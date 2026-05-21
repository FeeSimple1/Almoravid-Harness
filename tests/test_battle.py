"""Phase 5e Battle resolution tests."""

from __future__ import annotations

import copy

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (
    BattleSide,
    apply_aftermath,
    build_strike_rows,
    resolve_battle,
)
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad, step_levy


def _activate_lord(scenario, lord_id, seed=1):
    s = load_scenario(scenario, seed=seed)
    side = s.lords[lord_id].side
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": side,
                     "plan_kind": "command", "lord_id": lord_id})
    legal_pad(s, side)
    other = "muslim" if side == "christian" else "christian"
    legal_pad(s, other)
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == lord_id:
            return s
        apply_action(s, {"type": "command_reveal", "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != lord_id:
            apply_action(s, {"type": "end_card", "side": s.meta.active_player})
    raise RuntimeError(f"Could not activate {lord_id}")


# ---- resolve_battle direct API ----------------------------------------

def test_resolve_battle_produces_winner_with_strong_attacker() -> None:
    """A heavily over-forced attacker beats a single-Sgt defender."""
    s = load_scenario("scenario_a_toledo_beset", seed=42)
    # Attacker has overwhelming force.
    atk = BattleSide(
        side="christian", role="attacker", lord_ids=["alfonso"],
        forces={"knights": 6, "men_at_arms": 4},
    )
    dfd = BattleSide(
        side="muslim", role="defender", lord_ids=["al_mutamid"],
        forces={"sergeants": 1},
    )
    result = resolve_battle(s, atk, dfd)
    assert result.winner == "christian"


def test_resolve_battle_deterministic_under_seed() -> None:
    """Same seed -> identical Battle outcome."""
    def _run(seed):
        s = load_scenario("scenario_a_toledo_beset", seed=seed)
        atk = BattleSide(
            side="christian", role="attacker", lord_ids=["alfonso"],
            forces={"knights": 1, "men_at_arms": 1, "serfs": 1},
        )
        dfd = BattleSide(
            side="muslim", role="defender", lord_ids=["al_mutamid"],
            forces={"sergeants": 1, "light_horse": 1,
                    "men_at_arms": 1, "militia": 2},
        )
        return resolve_battle(s, atk, dfd)
    r1 = _run(99)
    r2 = _run(99)
    assert r1.winner == r2.winner
    assert len(r1.rounds) == len(r2.rounds)


def test_serfs_auto_remove_on_hit() -> None:
    """Pattern 7 / rule 1.7.1: Serfs have no Protection roll."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    atk = BattleSide(
        side="christian", role="attacker", lord_ids=["alfonso"],
        forces={"knights": 4},  # Strong Missile/Melee
    )
    dfd = BattleSide(
        side="muslim", role="defender", lord_ids=["al_mutamid"],
        forces={"serfs": 4},
    )
    result = resolve_battle(s, atk, dfd)
    # Defender's Serfs should have been removed without Protection rolls.
    # Either all routed or some remain.
    assert dfd.routed_units.get("serfs", 0) > 0


def test_strike_rows_for_alfonso() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    atk = BattleSide(
        side="christian", role="attacker", lord_ids=["alfonso"],
        forces=dict(s.lords["alfonso"].forces),
    )
    rows = build_strike_rows(s, atk, context="battle")
    # Knights melee x2, Men-at-Arms melee x1, Serfs melee x1/2
    kinds = {r.unit_type: (r.kind, r.rate) for r in rows}
    assert kinds["knights"] == ("melee", "x2")
    assert kinds["men_at_arms"] == ("melee", "x1")
    assert kinds["serfs"] == ("melee", "x1/2")


def test_capability_gated_strike_row_requires_card_in_play() -> None:
    """Pattern 7/14: Bowmen row appears only if cap card in play."""
    s = load_scenario("scenario_a_toledo_beset")
    forces = {"light_horse": 2}
    # Without cap
    atk_no = BattleSide(side="christian", role="attacker",
                        lord_ids=["alvar_fanez"], forces=forces,
                        capabilities_in_play=[])
    rows_no = build_strike_rows(s, atk_no)
    assert not any(r.kind == "missiles" and r.rate == "x1/2"
                   for r in rows_no)
    # With C4 Arqueros (Bowmen capability for Light Horse)
    atk_yes = BattleSide(side="christian", role="attacker",
                         lord_ids=["alvar_fanez"], forces=forces,
                         capabilities_in_play=["C4"])
    rows_yes = build_strike_rows(s, atk_yes)
    assert any(r.kind == "missiles" and "C4" in r.card_ids
               for r in rows_yes)


# ---- Pattern 2 mirror gaps: aftermath both winner-attacker and winner-defender

def test_winner_routed_units_roll_protection_not_auto_restore() -> None:
    """4.4.4: the winner does NOT auto-restore all Routed units; each
    rolls vs its unmodified Protection. Knights (Armor 1-4) survive on
    1-4, lost on 5-6. apply_battle_losses with loser_state='winner'."""
    from almoravid.battle import apply_battle_losses, BattleResult
    # Aggregate over seeds: some winner Knights are lost, not all kept.
    total_kept = total_routed = 0
    for seed in range(40):
        s = load_scenario("scenario_a_toledo_beset", seed=seed)
        s.lords["alfonso"].forces = {}
        s.lords["alfonso"].routed_units = {"knights": 4}
        atk = BattleSide(side="christian", role="attacker",
                         lord_ids=["alfonso"], forces={})
        dfd = BattleSide(side="muslim", role="defender",
                         lord_ids=["al_mutamid"], forces={})
        r = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                         winner="christian")
        apply_battle_losses(s, r, {"losers": []})
        total_kept += s.lords["alfonso"].forces.get("knights", 0)
        total_routed += 4
        # routed pile cleared either way
        assert s.lords["alfonso"].routed_units == {}
    # ~4/6 of Knights survive: strictly between none and all.
    assert 0 < total_kept < total_routed


def test_loser_retreat_no_concede_units_need_a_one() -> None:
    """4.4.4: units of a Lord who Retreated WITHOUT Conceding survive
    only on a roll of 1 (harsh). Most are lost."""
    from almoravid.battle import apply_losses_rolls
    total_kept = total = 0
    for seed in range(40):
        s = load_scenario("scenario_a_toledo_beset", seed=seed)
        s.lords["al_mutamid"].forces = {}
        s.lords["al_mutamid"].routed_units = {"sergeants": 6}
        apply_losses_rolls(s, "al_mutamid", "retreated_no_concede")
        total_kept += s.lords["al_mutamid"].forces.get("sergeants", 0)
        total += 6
    # ~1/6 survive.
    assert 0 < total_kept < total // 2


def test_aftermath_marks_lords_moved_fought() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 1})
    from almoravid.battle import BattleResult
    r = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                     winner="christian")
    apply_aftermath(s, r)
    assert s.lords["alfonso"].moved_fought is True
    assert s.lords["al_mutamid"].moved_fought is True


# ---- cmd_battle handler --------------------------------------------------

def test_cmd_battle_requires_enemy_lord_present() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alfonso")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_battle", "side": "christian"})
    assert ei.value.code == "no_enemy"


def test_cmd_battle_accepts_multi_lord_after_deferred_fix() -> None:
    """Deferred fix: multi-Lord Battle is now supported via aggregation."""
    s = _activate_lord("scenario_a_toledo_beset", "alfonso", seed=11)
    # Two Muslim Lords at Sahagun
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    # Move other Christian Lords away to leave alfonso alone on his side
    s.lords["pedro_ansurez"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["garcia_ordonez"].cylinder = Cylinder(kind="locale", locale_id="burgos")
    r = apply_action(s, {"type": "cmd_battle", "side": "christian"})
    assert r["winner"] in ("christian", "muslim", None)
    assert s.meta.actions_remaining == 0


def test_cmd_battle_resolves_and_ends_card() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alfonso", seed=3)
    # Move al-Mutamid to Sahagún for the fight
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    # Move other Christian Lords away to make ours alone
    s.lords["pedro_ansurez"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["garcia_ordonez"].cylinder = Cylinder(kind="locale", locale_id="burgos")
    r = apply_action(s, {"type": "cmd_battle", "side": "christian"})
    # Card used up
    assert s.meta.actions_remaining == 0
    # Both Lords marked moved_fought
    assert s.lords["alfonso"].moved_fought is True
    assert s.lords["al_mutamid"].moved_fought is True
    assert r["winner"] in ("christian", "muslim", None)
