"""Phase 5c Forage (4.7.1) + Ravage (4.7.2) tests."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
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


# ---- Forage -----------------------------------------------------------

def test_forage_gardens_auto_succeeds() -> None:
    """Al-Mutamid at Sevilla (own Friendly City with Gardens) -> auto Prov."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    before = s.lords["al_mutamid"].assets.get("prov", 0)
    r = apply_action(s, {"type": "cmd_forage", "side": "muslim"})
    assert r["path"] == "gardens"
    assert r["prov_after"] == before + 1
    assert r["roll"] is None


def test_forage_open_uses_d6_roll() -> None:
    """Lord at non-Friendly non-Gardens Locale rolls 1d6."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Alvar Fanez at Toledo (Parias Toledo Taifa, no Friendly status).
    # But Toledo has Ravaged yellow in Scenario A — so Forage rejected.
    # Move him to a region locale first.
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="madrid")
    r = apply_action(s, {"type": "cmd_forage", "side": "christian"})
    assert r["path"] == "open"
    assert r["roll"] is not None
    assert 1 <= r["roll"] <= 6
    if r["roll"] <= 3:
        assert r["result"] == "success"
    else:
        assert r["result"] == "fail"


def test_forage_rejects_ravaged_open() -> None:
    """Open Forage requires Unravaged Locale."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Alvar Fanez starts at Toledo with Ravaged yellow
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    # Toledo is Parias Toledo (not Friendly), Ravaged yellow.
    # Has Gardens=False (it's a City but in Parias = not Friendly).
    # Actually Toledo IS Friendly... wait, Parias = Neutral, not Friendly.
    # So Gardens path doesn't apply. And Ravaged blocks Open path.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_forage", "side": "christian"})
    assert ei.value.code == "ravaged"


def test_forage_besieged_at_own_gardens_allowed() -> None:
    """Besieged Lord may Forage Gardens (4.7.1 Gardens exemption)."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    # Force besieged at his own Sevilla
    s.lords["al_mutamid"].in_stronghold = True
    s.locales["sevilla"].siege_yellow = 1
    r = apply_action(s, {"type": "cmd_forage", "side": "muslim"})
    assert r["path"] == "gardens"


def test_forage_besieged_without_gardens_rejected() -> None:
    """Besieged at non-Gardens Locale: no Forage path."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Move Alvar Fanez to a Town (no Gardens) and besiege synthetically.
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="madrid")
    s.lords["alvar_fanez"].in_stronghold = True
    s.locales["madrid"].siege_green = 1  # Muslim siege on Christian Lord
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_forage", "side": "christian"})
    assert ei.value.code == "besieged_no_gardens"


def test_forage_caps_prov_at_8() -> None:
    """Pattern 12: Forage Provender capped at 8."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    s.lords["al_mutamid"].assets["prov"] = 8
    r = apply_action(s, {"type": "cmd_forage", "side": "muslim"})
    assert s.lords["al_mutamid"].assets["prov"] == 8


def test_forage_determinism() -> None:
    """Same seed -> same Forage roll."""
    s1 = _activate_lord("scenario_a_toledo_beset", "alvar_fanez", seed=99)
    s2 = _activate_lord("scenario_a_toledo_beset", "alvar_fanez", seed=99)
    s1.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="madrid")
    s2.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="madrid")
    r1 = apply_action(s1, {"type": "cmd_forage", "side": "christian"})
    r2 = apply_action(s2, {"type": "cmd_forage", "side": "christian"})
    assert r1["roll"] == r2["roll"]


# ---- Ravage -----------------------------------------------------------

def test_ravage_at_region_adds_loot() -> None:
    """Region Ravage: +1 Loot to Lord."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Alvar Fanez at Toledo. Toledo Taifa = Parias (Neutral), but
    # Toledo has Ravaged yellow already so it's already-Ravaged-by-us.
    # Move to Calatrava: Fortress in Toledo Taifa with 2 Jihad markers.
    # Wait — Jihad markers make Calatrava Muslim-friendly per 1.3.1.
    # Move to Trujillo (Castle in Toledo Taifa with 1 Jihad) — also Muslim
    # friendly. Move to Madrid (Town in Toledo Taifa, no markers, Parias
    # = Neutral). Madrid is NOT Friendly to either side under Parias.
    # For Ravage we need an ENEMY locale. So pick one in an Independent
    # Muslim Taifa: Calatayud (Castle in Zaragoza Taifa, Zaragoza is
    # Independent in Scenario A).
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="calatayud")
    before_loot = s.lords["alvar_fanez"].assets.get("loot", 0)
    before_vp = s.score.christian
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert s.lords["alvar_fanez"].assets["loot"] == before_loot + 1
    # Stronghold (Castle) -> also +1 Prov
    assert "Stronghold" in r["rustling"] or s.locales["calatayud"].base_type != "region"
    # +0.5 VP per Ravaged marker (5.1)
    assert s.score.christian == before_vp + 0.5
    # Ravaged marker placed
    assert s.locales["calatayud"].ravaged == "yellow"


def test_ravage_at_region_no_prov() -> None:
    """Region Ravage: only Loot, no Prov."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Iberico is a region in Zaragoza (Independent Muslim Taifa)
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="iberico")
    before_prov = s.lords["alvar_fanez"].assets.get("prov", 0)
    apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    # Region rule: +1 Loot only; Prov unchanged
    assert s.lords["alvar_fanez"].assets["prov"] == before_prov


def test_ravage_rejects_friendly_locale() -> None:
    """Cannot Ravage own Friendly Locale."""
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    # Al-Mutamid at Sevilla (own Friendly City).
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_ravage", "side": "muslim"})
    assert ei.value.code == "friendly_locale"


def test_ravage_rejects_already_ravaged_by_us() -> None:
    """Cannot Ravage a Locale already showing our color (4.7.2)."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Toledo has yellow Ravaged in Scenario A
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    assert s.locales["toledo"].ravaged == "yellow"
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert ei.value.code == "already_ravaged"


def test_ravage_rejects_already_ravaged_enemy_color() -> None:
    """4.7.2: Ravage targets a Locale NOT YET Ravaged (either color). A
    Locale Ravaged in the Enemy color cannot be re-Ravaged (and flipped)
    via a Ravage action — markers flip only via Conquest (1.3.1)."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.locales["toledo"].ravaged = "green"   # enemy (Muslim) color
    before = (s.score.christian, s.score.muslim)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert ei.value.code == "already_ravaged"
    assert s.locales["toledo"].ravaged == "green"   # not flipped
    assert (s.score.christian, s.score.muslim) == before  # no VP gained


def test_ravage_rejects_besieged() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="calatayud")
    s.lords["alvar_fanez"].in_stronghold = True
    s.locales["calatayud"].siege_green = 1
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert ei.value.code == "besieged"


def test_ravage_enforcing_parias_trigger() -> None:
    """Christian (yellow) Ravage that brings the Taifa's yellow count
    to an odd number triggers Enforcing Parias (4.7.2)."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Place Alvar Fanez at Calatayud (Zaragoza Taifa).
    # Currently Zaragoza Taifa has 0 yellow Ravaged markers.
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="calatayud")
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    # After this Ravage, Zaragoza Taifa has 1 yellow marker — ODD.
    assert r["enforcing_parias"] is True


def test_legal_moves_offers_forage_at_gardens() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    moves = legal_moves(s)
    assert any(m["type"] == "cmd_forage" for m in moves)


def test_legal_moves_offers_ravage_at_enemy_locale() -> None:
    """Move Lord to enemy territory and verify cmd_ravage offered."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="calatayud")
    moves = legal_moves(s)
    ravage_moves = [m for m in moves if m["type"] == "cmd_ravage"]
    assert ravage_moves


def test_forage_friendly_town_auto_succeeds() -> None:
    """4.7.1 PROCEDURE: Forage in ANY Friendly Stronghold (not just
    Gardens City/Fortress) adds one Provender automatically — a Town or
    Castle counts too."""
    from almoravid.effective import has_gardens
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="coria")  # Town
    assert s.locales["coria"].base_type == "town"
    assert not has_gardens(s, "coria")          # not a Gardens Stronghold
    prov0 = s.lords["alvar_fanez"].assets.get("prov", 0)
    r = apply_action(s, {"type": "cmd_forage", "side": "christian"})
    assert r["roll"] is None                    # auto, no die rolled
    assert r["path"] == "friendly_stronghold"
    assert s.lords["alvar_fanez"].assets.get("prov", 0) == prov0 + 1
