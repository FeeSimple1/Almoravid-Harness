"""Phase 3b tests for forces.json, strongholds.json, battle skeleton."""

from __future__ import annotations

import pytest

from almoravid.battle import (
    BattleSide,
    StrikeRow,
    build_strike_rows,
    resolve_battle,
)
from almoravid.scenarios import load_scenario
from almoravid.static_data import load_forces, load_strongholds


# ---- forces.json --------------------------------------------------------

def test_forces_eight_units() -> None:
    f = load_forces()
    horse = set(f["horse"].keys())
    foot = set(f["foot"].keys())
    assert horse == {"knights", "sergeants", "african_horse", "light_horse"}
    assert foot == {"men_at_arms", "african_foot", "militia", "serfs"}


def test_knights_double_strike_in_battle_single_in_storm() -> None:
    """Quick Reference: Knights Melee x2 Battle, x1 Storm."""
    f = load_forces()
    k = f["horse"]["knights"]
    assert k["strikes_battle"] == [{"kind": "melee", "rate": "x2"}]
    assert k["strikes_storm"] == [{"kind": "melee", "rate": "x1"}]
    assert k["protection"] == {"type": "armored", "range": [1, 4]}


def test_serfs_auto_remove() -> None:
    """Serfs have no Protection roll — auto-remove on Hit (1.7.1)."""
    f = load_forces()
    assert f["foot"]["serfs"]["protection"]["type"] == "auto_remove"


def test_men_at_arms_garrison_crossbows_select_target() -> None:
    """Pattern 7: Garrison MaA Crossbows include -1 vs Armor and target selection."""
    f = load_forces()
    mga = f["foot"]["men_at_arms"]["strikes_by_garrison"]
    assert len(mga) == 1
    g = mga[0]
    assert g["kind"] == "crossbows"
    assert g["minus_armor"] == 1
    assert g["firing_side_selects_target"] is True


def test_militia_garrison_bowmen_no_target_select() -> None:
    """Quick Reference Table 1 footnote: Garrison Militia are REGULAR
    Bowmen — no -1 vs Armor, no target selection."""
    f = load_forces()
    mg = f["foot"]["militia"]["strikes_by_garrison"]
    assert len(mg) == 1
    assert mg[0]["kind"] == "bowmen"
    assert "minus_armor" not in mg[0]
    assert "firing_side_selects_target" not in mg[0]


def test_capability_card_ids_present() -> None:
    """Pattern 14 mirror: every capability-gated strike lists the card_ids
    that grant it, so the Phase 4 resolver can audit which cards apply."""
    f = load_forces()
    for category in ("horse", "foot"):
        for ut, unit in f[category].items():
            for cap_row in unit.get("strikes_by_capability", []):
                assert "card_ids" in cap_row, (
                    f"{category}.{ut}: capability strike row missing card_ids "
                    f"-- Pattern 14 audit hook"
                )
                assert cap_row["card_ids"], f"{ut}: empty card_ids list"


# ---- strongholds.json ---------------------------------------------------

def test_four_stronghold_types() -> None:
    s = load_strongholds()
    assert set(s["strongholds"].keys()) == {"city", "fortress", "town", "castle"}


def test_city_has_3_capacity_3_value() -> None:
    s = load_strongholds()["strongholds"]
    assert s["city"]["capacity"] == 3
    assert s["city"]["value"] == 3
    assert s["city"]["gardens"] is True
    assert s["city"]["surrender_dice"] == 3


def test_town_capacity_2_per_errata_correction() -> None:
    """Map reference v13: 'Towns Cap 1' was an error; corrected to Cap 2."""
    assert load_strongholds()["strongholds"]["town"]["capacity"] == 2


def test_gardens_only_at_city_fortress() -> None:
    """Rule 4.7.1: Gardens at Cities and Fortresses only."""
    s = load_strongholds()["strongholds"]
    assert s["city"]["gardens"] is True
    assert s["fortress"]["gardens"] is True
    assert s["town"]["gardens"] is False
    assert s["castle"]["gardens"] is False


# ---- battle skeleton ----------------------------------------------------

def test_build_strike_rows_for_alfonso() -> None:
    state = load_scenario("scenario_a_toledo_beset")
    alfonso = state.lords["alfonso"]
    side = BattleSide(
        side="christian",
        role="attacker",
        lord_ids=["alfonso"],
        forces=dict(alfonso.forces),
        capabilities_in_play=alfonso.capabilities,
    )
    rows = build_strike_rows(state, side, context="battle")
    # Alfonso brings 1K (x2 melee), 1MA (x1 melee), 1Sf (x1/2 melee)
    assert any(r.unit_type == "knights" and r.kind == "melee" and r.rate == "x2"
               for r in rows)
    assert any(r.unit_type == "men_at_arms" and r.kind == "melee" and r.rate == "x1"
               for r in rows)
    assert any(r.unit_type == "serfs" and r.kind == "melee" and r.rate == "x1/2"
               for r in rows)


def test_resolve_battle_runs() -> None:
    """Phase 5e: resolve_battle runs rounds and selects a winner."""
    state = load_scenario("scenario_a_toledo_beset")
    alfonso = state.lords["alfonso"]
    al_mutamid = state.lords["al_mutamid"]
    atk = BattleSide(side="christian", role="attacker", lord_ids=["alfonso"],
                     forces=dict(alfonso.forces), capabilities_in_play=[])
    dfd = BattleSide(side="muslim", role="defender", lord_ids=["al_mutamid"],
                     forces=dict(al_mutamid.forces), capabilities_in_play=[])
    result = resolve_battle(state, atk, dfd)
    assert result.engagement == "battle"
    assert result.attacker.side == "christian"
    assert result.defender.side == "muslim"
    # At least one round resolved; either a winner emerges or capped out.
    assert len(result.rounds) >= 1
