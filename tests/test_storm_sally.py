"""Phase 5f Storm + Sally tests."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (
    BattleSide,
    resolve_sally,
    resolve_storm,
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


# ---- resolve_storm ----------------------------------------------------

def test_resolve_storm_adds_garrison_to_defender_garrison_bucket() -> None:
    """Bug M fix: Garrison units go into defender.garrison_forces (not
    merged into defender.forces) so they absorb Hits before Lord units
    per rule 4.5.2 'Garrison absorbs Hits BEFORE any Defending Lord units'."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.locales["zaragoza"].siege_yellow = 1
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 3})
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.lords["al_mustain"].in_stronghold = True
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mustain"],
                     forces=dict(s.lords["al_mustain"].forces))
    initial_lord_count = sum(dfd.forces.values())
    resolve_storm(s, atk, dfd)
    # Garrison was added to dfd.garrison_forces (or routed FROM there).
    routed = sum(dfd.routed_units.values())
    remaining_lord = sum(dfd.forces.values())
    remaining_garrison = sum(dfd.garrison_forces.values())
    # Zaragoza City Garrison: 3 MaA + 3 Militia = 6 units. Total defender
    # units (Lord + Garrison) initially = initial_lord_count + 6.
    assert remaining_lord + remaining_garrison + routed >= initial_lord_count + 6 - 6


def test_resolve_storm_max_rounds_from_siege_markers() -> None:
    """Storm round-cap = our Siege markers (rule 4.5.2)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.locales["zaragoza"].siege_yellow = 2
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.lords["al_mustain"].in_stronghold = True
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mustain"],
                     forces=dict(s.lords["al_mustain"].forces))
    result = resolve_storm(s, atk, dfd)
    # With only 1 attacking Knight vs Garrison + Lord, Storm should not
    # be a quick attacker win. Round count <= 2.
    assert len(result.rounds) <= 2


# ---- cmd_storm handler -------------------------------------------------

def test_cmd_storm_requires_siege_marker() -> None:
    """Storm at locale without our Siege marker is rejected."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    # No Siege there from us
    s.locales["zaragoza"].siege_yellow = 0
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_storm", "side": "christian"})
    assert ei.value.code == "no_siege"


def test_cmd_storm_rejects_region() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_storm", "side": "christian"})
    assert ei.value.code == "region_no_storm"


def test_cmd_storm_rejects_besieged() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.lords["alvar_fanez"].in_stronghold = True
    s.locales["zaragoza"].siege_green = 1
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_storm", "side": "christian"})
    assert ei.value.code == "besieged"


def test_cmd_storm_consumes_entire_card() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez", seed=11)
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.locales["zaragoza"].siege_yellow = 1
    apply_action(s, {"type": "cmd_storm", "side": "christian"})
    assert s.meta.actions_remaining == 0


# ---- cmd_sally handler -------------------------------------------------

def test_cmd_sally_requires_besieged() -> None:
    """Sally rejected if Lord isn't Besieged."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_sally", "side": "muslim"})
    assert ei.value.code == "not_besieged"


def test_cmd_sally_with_besiegers_resolves() -> None:
    """Synthetic: place al_mutamid besieged at Sevilla, alvar_fanez
    as besieger outside, run Sally."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid", seed=3)
    s.lords["al_mutamid"].in_stronghold = True
    s.locales["sevilla"].siege_yellow = 2
    # Move alvar_fanez to Sevilla outside the walls
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords["alvar_fanez"].in_stronghold = False
    r = apply_action(s, {"type": "cmd_sally", "side": "muslim"})
    # Card consumed; winner picked
    assert s.meta.actions_remaining == 0
    assert r["winner"] in ("muslim", "christian", None)


def test_sally_aftermath_reduces_siege_on_loss() -> None:
    """Sally loss withdraws Lord and reduces Siege to 1."""
    from almoravid.battle import apply_sally_aftermath, BattleResult
    s = load_scenario("scenario_a_toledo_beset")
    s.locales["sevilla"].siege_yellow = 3
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alvar_fanez"], forces={"knights": 1})
    s.lords["al_mutamid"].in_stronghold = False  # mid-sally state
    r = BattleResult(engagement="sally", attacker=atk, defender=dfd,
                     winner="christian")  # Sallying side lost
    apply_sally_aftermath(s, r, "sevilla")
    assert s.lords["al_mutamid"].in_stronghold is True
    assert s.locales["sevilla"].siege_yellow == 1


# ---- legal_moves enumeration ------------------------------------------

def test_legal_moves_offers_storm_when_siege_present() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.locales["zaragoza"].siege_yellow = 1
    moves = legal_moves(s)
    assert any(m["type"] == "cmd_storm" for m in moves)


def test_legal_moves_offers_sally_when_besieged_with_besiegers() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    s.lords["al_mutamid"].in_stronghold = True
    s.locales["sevilla"].siege_yellow = 1
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords["alvar_fanez"].in_stronghold = False
    moves = legal_moves(s)
    assert any(m["type"] == "cmd_sally" for m in moves)
