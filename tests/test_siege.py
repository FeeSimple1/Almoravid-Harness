"""Phase 5d Siege (4.5.1) tests."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _activate_lord(scenario, lord_id, seed=1):
    s = load_scenario(scenario, seed=seed)
    side = s.lords[lord_id].side
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    apply_action(s, {"type": "plan_add_card", "side": side,
                     "plan_kind": "command", "lord_id": lord_id})
    for _ in range(6):
        apply_action(s, {"type": "plan_add_card", "side": side,
                         "plan_kind": "pass"})
    other = "muslim" if side == "christian" else "christian"
    for _ in range(7):
        apply_action(s, {"type": "plan_add_card", "side": other,
                         "plan_kind": "pass"})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == lord_id:
            return s
        apply_action(s, {"type": "command_reveal", "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != lord_id:
            apply_action(s, {"type": "end_card", "side": s.meta.active_player})
    raise RuntimeError(f"Could not activate {lord_id}")


def test_siege_places_marker_at_enemy_stronghold() -> None:
    """Christian Lord at Muslim City Zaragoza places yellow Siege marker."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    before = s.locales["zaragoza"].siege_yellow
    r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    # Christian alone at Zaragoza City (capacity 3) -> NO Siegeworks
    assert s.locales["zaragoza"].siege_yellow == before + 1
    assert r["color"] == "yellow"
    assert r["placed"] == 1
    assert r["siegeworks"] is False


def test_siege_at_region_rejected() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert ei.value.code == "region_no_siege"


def test_siege_at_friendly_locale_rejected() -> None:
    """Cannot Siege own Friendly Stronghold."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_siege", "side": "muslim"})
    assert ei.value.code == "friendly_locale"


def test_siege_besieged_lord_rejected() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.lords["alvar_fanez"].in_stronghold = True
    s.locales["zaragoza"].siege_green = 1
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert ei.value.code == "besieged"


def test_siege_cap_at_4() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.locales["zaragoza"].siege_yellow = 4
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert ei.value.code == "siege_cap_reached"


def test_siege_uses_entire_card() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    actions_before = s.meta.actions_remaining
    apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert s.meta.actions_remaining == 0


def test_siegeworks_doubles_marker_at_capacity() -> None:
    """Castle Capacity=1: one Lord meets it -> Siegeworks (+2 markers)."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Calatayud is a Castle (capacity 1) in Independent Zaragoza (Muslim).
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="calatayud")
    before = s.locales["calatayud"].siege_yellow
    r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    # 1 Lord >= capacity 1 -> Siegeworks places +2
    assert r["siegeworks"] is True
    assert r["placed"] == 2
    assert s.locales["calatayud"].siege_yellow == before + 2


def test_legal_moves_offers_siege_at_enemy_stronghold() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    moves = legal_moves(s)
    assert any(m["type"] == "cmd_siege" for m in moves)


def test_legal_moves_no_siege_at_friendly_locale() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    moves = legal_moves(s)
    assert not any(m["type"] == "cmd_siege" for m in moves)
