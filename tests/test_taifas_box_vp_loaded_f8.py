"""Playtest F8: the Taifas-box green 1VP Conquered markers are loaded at
setup into state.taifas_box_vp, so compute_final_vp counts them for the
Muslims (they were silently dropped, flipping Scenario A's winner)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from almoravid.scenarios import load_scenario, list_campaign_scenarios
from almoravid.campaign import compute_final_vp

_DATA = Path(__file__).resolve().parent.parent / "src/almoravid/data/scenarios"


@pytest.mark.parametrize("name", list_campaign_scenarios())
def test_taifas_box_vp_matches_scenario_json(name: str) -> None:
    raw = json.loads((_DATA / f"{name}.json").read_text())
    expected = float((raw.get("taifas_box") or {}).get("conquered_green_1vp", 0))
    s = load_scenario(name)
    assert s.taifas_box_vp == expected


def test_scenario_a_taifas_box_counts_for_muslim_final_vp() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert s.taifas_box_vp == 4.0
    _, mvp = compute_final_vp(s)
    # The 4 green Taifas-box VP are included in the Muslim total.
    assert mvp >= 4.0
