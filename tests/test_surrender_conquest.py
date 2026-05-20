"""Phase 5i Surrender + Conquest tests."""

from __future__ import annotations

import pytest

from almoravid.actions import apply_action
from almoravid.campaign import _conquer_stronghold
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad


def test_conquer_stronghold_christian_places_conquered_markers() -> None:
    """1.4.4 Conquest: Christian conquers Muslim City -> +3 Conquered + 3 VP."""
    s = load_scenario("scenario_a_toledo_beset")
    s.locales["zaragoza"].siege_yellow = 4
    vp_before = s.score.christian
    r = _conquer_stronghold(s, "zaragoza", "christian")
    assert r["marker"] == "conquered"
    assert r["value"] == 3  # City
    assert r["vp_delta"] == 3.0
    assert s.locales["zaragoza"].conquered_markers >= 3
    assert s.locales["zaragoza"].siege_yellow == 0  # Siege removed
    assert s.score.christian == vp_before + 3.0


def test_conquer_stronghold_castle_value_1() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.locales["calatayud"].siege_yellow = 1
    r = _conquer_stronghold(s, "calatayud", "christian")
    assert r["value"] == 1
    assert r["vp_delta"] == 1.0


def test_conquer_region_no_op() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    r = _conquer_stronghold(s, "sahagun", "christian")
    assert r.get("no_op") is True


def test_muslim_reconquers_reconquista_taifa_places_jihad() -> None:
    """Muslim reconquering a yellow-Conquered Stronghold in a
    Reconquista Taifa places Jihad markers (1/2 VP each)."""
    s = load_scenario("scenario_b_quelling_of_tajo")
    # Toledo Taifa is Reconquista in Scenario B; Toledo has 3 yellow Conquered.
    assert s.taifas["toledo"].status == "reconquista"
    assert s.locales["toledo"].conquered_markers == 3
    s.locales["toledo"].siege_green = 4
    vp_before = s.score.muslim
    r = _conquer_stronghold(s, "toledo", "muslim")
    assert r["marker"] == "jihad"
    assert r["vp_delta"] == 0.5 * 3  # Jihad = 0.5 VP * City value 3
    assert s.locales["toledo"].jihad_markers >= 3
    assert s.locales["toledo"].siege_green == 0
    assert s.score.muslim == vp_before + 1.5


def test_cmd_siege_with_no_defender_attempts_surrender() -> None:
    """When no Besieged Lord is inside, cmd_siege auto-rolls Surrender."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alvar_fanez"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="calatayud")
    # No Muslim Lord at Calatayud -> Surrender check rolls
    r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert r["surrender"] is not None
    assert "dice" in r["surrender"]
