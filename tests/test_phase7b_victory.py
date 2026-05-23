"""Phase 7b: final victory determination (rules 5.1 / 5.2 / 5.3)."""

from __future__ import annotations

from almoravid.campaign import (
    check_campaign_victory, compute_final_vp, compute_victory,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_compute_final_vp_counts_taifa_status() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Zero out the board so we can isolate Taifa-status VP.
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    s.taifas_box_vp = 0.0  # isolate Taifa-status VP from the box VP
    taifas = list(s.taifas.values())
    taifas[0].status = "reconquista"  # +3 Christian
    if len(taifas) > 1:
        taifas[1].status = "parias"   # +1 Christian
    for t in taifas[2:]:
        t.status = "independent"
    cvp, mvp = compute_final_vp(s)
    expected_c = 3.0 + (1.0 if len(taifas) > 1 else 0.0)
    assert cvp == expected_c
    assert mvp == 0.0


def test_compute_final_vp_counts_markers() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    for t in s.taifas.values():
        t.status = "independent"
    # One Conquered on a Taifa locale (Christian +1); one Jihad
    # (Muslim +0.5); one yellow Ravaged (+0.5 C); one green (+0.5 M).
    taifa_loc = next(lid for lid, loc in s.locales.items()
                     if loc.territory in s.taifas)
    s.locales[taifa_loc].conquered_markers = 1
    other_taifa_loc = next(lid for lid, loc in s.locales.items()
                           if loc.territory in s.taifas and lid != taifa_loc)
    s.locales[other_taifa_loc].jihad_markers = 1
    cvp, mvp = compute_final_vp(s)
    assert cvp >= 1.0
    assert mvp >= 0.5


def test_campaign_victory_when_side_has_no_lords() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Remove every Muslim Lord from the map.
    for l in s.lords.values():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="calendar", box=8)
    assert check_campaign_victory(s) == "christian"


def test_campaign_victory_takes_precedence_over_vp() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Give Muslims a huge VP lead, but remove all Muslim Lords.
    for loc in s.locales.values():
        loc.jihad_markers = 10
    for l in s.lords.values():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="calendar", box=8)
    verdict = compute_victory(s)
    assert verdict["winner"] == "christian"
    assert "Campaign victory" in verdict["reason"]


def test_end_of_scenario_higher_vp_wins() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Ensure both sides have Lords (no campaign victory).
    assert check_campaign_victory(s) is None
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    for t in s.taifas.values():
        t.status = "independent"
    # Give Muslims 5 Jihad (2.5 VP), Christians nothing.
    loc0 = next(iter(s.locales))
    s.locales[loc0].jihad_markers = 5
    verdict = compute_victory(s)
    assert verdict["winner"] == "muslim"
    assert s.score.winner == "muslim"


def test_tie_is_draw() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    assert check_campaign_victory(s) is None
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    for t in s.taifas.values():
        t.status = "independent"
    s.taifas_box_vp = 0.0  # both sides 0 -> a genuine tie
    verdict = compute_victory(s)
    assert verdict["christian_vp"] == verdict["muslim_vp"]
    assert verdict["winner"] == "draw"


def test_full_game_advance_to_end_sets_winner() -> None:
    """Driving the Calendar to Scenario End populates score.winner."""
    from almoravid.actions import apply_action
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Jump the Calendar marker to just before the Scenario End box.
    end_box = next((b.number for b in s.calendar.boxes
                    if "scenario_end" in b.decorations), None)
    assert end_box is not None, "no scenario_end marker in scenario A"
    # Drive the end-of-Campaign Calendar advance (which performs the
    # scenario_end check) via the end_campaign action.
    s.calendar.current_box = end_box - 1
    s.meta.phase = "campaign"
    s.meta.campaign_step = "end_campaign"
    s.meta.active_player = "christian"
    r = apply_action(s, {"type": "end_campaign", "side": "christian"})
    assert s.meta.phase == "ended"
    assert s.score.winner in ("christian", "muslim", "draw")
    assert "victory" in r


def test_sevilla_reconquista_worth_nine_vp() -> None:
    """1.4.2: Reconquista Sevilla is worth 9 Christian VP, not 3."""
    from almoravid.campaign import compute_final_vp
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    for t in s.taifas.values():
        t.status = "independent"
    s.taifas["sevilla"].status = "reconquista"
    cvp, mvp = compute_final_vp(s)
    assert cvp == 9.0


def test_sevilla_parias_worth_three_vp() -> None:
    from almoravid.campaign import compute_final_vp
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    for t in s.taifas.values():
        t.status = "independent"
    s.taifas["sevilla"].status = "parias"
    cvp, mvp = compute_final_vp(s)
    assert cvp == 3.0
