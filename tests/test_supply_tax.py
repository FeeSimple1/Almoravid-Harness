"""Phase 5b Supply (4.6) + Tax (4.7.3) tests."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad


def _activate_lord(scenario: str, lord_id: str, seed: int = 1):
    """Drive scenario to a state where `lord_id` has the active Command card."""
    s = load_scenario(scenario, seed=seed)
    side = s.lords[lord_id].side
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    apply_action(s, {"type": "plan_add_card", "side": side,
                     "plan_kind": "command", "lord_id": lord_id})
    legal_pad(s, side)
    other = "muslim" if side == "christian" else "christian"
    legal_pad(s, other)
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    # Reveal cards in order until our Lord is the active one
    for _ in range(20):
        if s.meta.active_lord_id == lord_id:
            return s
        apply_action(s, {"type": "command_reveal", "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != lord_id:
            apply_action(s, {"type": "end_card", "side": s.meta.active_player})
    raise RuntimeError(f"Could not activate {lord_id} in {scenario}")


# ---- Supply ------------------------------------------------------------

def test_supply_at_own_seat_no_transport_needed() -> None:
    """Al-Mutamid at Sevilla (own Seat). Supply +1 Prov, no Transport."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    prov_before = s.lords["al_mutamid"].assets.get("prov", 0)
    mule_before = s.lords["al_mutamid"].assets.get("mule", 0)
    cart_before = s.lords["al_mutamid"].assets.get("cart", 0)
    r = apply_action(s, {"type": "cmd_supply", "side": "muslim",
                          "source_seat": "sevilla"})
    assert s.lords["al_mutamid"].assets["prov"] == prov_before + 1
    # No Transport consumed (rule 4.6.1 'at own Seat needs no Transport').
    assert s.lords["al_mutamid"].assets.get("mule", 0) == mule_before
    assert s.lords["al_mutamid"].assets.get("cart", 0) == cart_before
    assert r["transport"] is None


def test_supply_rejects_besieged_lord() -> None:
    """Rule 4.2.1 / 4.6: Besieged Lord cannot Supply."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    # Synthetically besiege al-Mutamid at Sevilla
    s.lords["al_mutamid"].in_stronghold = True
    s.locales["sevilla"].siege_yellow = 1  # Christian-placed Siege
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_supply", "side": "muslim",
                         "source_seat": "sevilla"})
    assert ei.value.code == "besieged"


def test_supply_rejects_not_own_seat() -> None:
    """Cannot Supply from a Seat that isn't yours."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_supply", "side": "muslim",
                         "source_seat": "valencia"})  # Abu Bakr's Seat
    assert ei.value.code == "bad_seat"


def test_supply_no_reachable_seat() -> None:
    """If Lord is not at a Seat and no Road-adjacent Seat exists, reject."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Alvar Fanez starts at Toledo; his Seat is Burgos. Toledo is NOT
    # Road-adjacent to Burgos. So Supply has no route.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_supply", "side": "christian"})
    assert ei.value.code == "no_supply_route"


def test_supply_caps_provender_at_8() -> None:
    """Pattern 12: Asset cap of 8 (rule 1.7.3)."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    s.lords["al_mutamid"].assets["prov"] = 8
    r = apply_action(s, {"type": "cmd_supply", "side": "muslim",
                          "source_seat": "sevilla"})
    assert s.lords["al_mutamid"].assets["prov"] == 8  # Capped
    assert r["prov_after"] == 8


def test_supply_consumes_one_action() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    before = s.meta.actions_remaining
    apply_action(s, {"type": "cmd_supply", "side": "muslim",
                     "source_seat": "sevilla"})
    assert s.meta.actions_remaining == before - 1


# ---- Tax --------------------------------------------------------------

def test_tax_at_own_seat_adds_coin_and_consumes_card() -> None:
    """Rule 4.7.3: +1 Coin, uses entire card."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    coin_before = s.lords["al_mutamid"].assets.get("coin", 0)
    actions_before = s.meta.actions_remaining
    assert actions_before > 0
    r = apply_action(s, {"type": "cmd_tax", "side": "muslim"})
    assert s.lords["al_mutamid"].assets["coin"] == coin_before + 1
    # Entire card spent
    assert s.meta.actions_remaining == 0
    assert r["actions_consumed"] == actions_before


def test_tax_rejects_when_not_at_own_seat() -> None:
    """Alvar Fanez at Toledo, Seat is Burgos -> not_at_own_seat."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_tax", "side": "christian"})
    assert ei.value.code == "not_at_own_seat"


def test_tax_rejects_besieged_lord() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    s.lords["al_mutamid"].in_stronghold = True
    s.locales["sevilla"].siege_yellow = 1
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_tax", "side": "muslim"})
    assert ei.value.code == "besieged"


def test_tax_caps_coin_at_8() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    s.lords["al_mutamid"].assets["coin"] = 8
    apply_action(s, {"type": "cmd_tax", "side": "muslim"})
    assert s.lords["al_mutamid"].assets["coin"] == 8


# ---- legal_moves enumeration --------------------------------------------

def test_legal_moves_offers_supply_at_seat() -> None:
    """Pattern 1: Supply move surfaced when Lord at his own Seat."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    moves = legal_moves(s)
    supply_moves = [m for m in moves if m["type"] == "cmd_supply"]
    assert any(m["source_seat"] == "sevilla" for m in supply_moves)


def test_legal_moves_offers_tax_at_own_seat() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    moves = legal_moves(s)
    assert any(m["type"] == "cmd_tax" for m in moves)


def test_legal_moves_no_tax_when_not_at_seat() -> None:
    """Alvar Fanez at Toledo (not his Seat) -> no Tax offered."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    moves = legal_moves(s)
    assert not any(m["type"] == "cmd_tax" for m in moves)


def test_legal_moves_no_supply_when_no_reachable_seat() -> None:
    """Pattern 1/9 mirror: if no Supply route, no Supply move offered."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    moves = legal_moves(s)
    assert not any(m["type"] == "cmd_supply" for m in moves)
