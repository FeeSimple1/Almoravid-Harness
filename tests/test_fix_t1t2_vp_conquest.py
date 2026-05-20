"""FIX-D / T1 Sevilla VP weighting (1.4.2/5.1), T2 Muslim Conquest Jihad
(1.4.4), confirming the current implementation is rules-correct."""

from __future__ import annotations

from almoravid.campaign import _conquer_stronghold, compute_final_vp
from almoravid.scenarios import load_scenario


def test_t1_sevilla_reconquista_worth_nine() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for tf in s.taifas.values():
        tf.status = "independent"
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    s.taifas_box_vp = 0.0
    s.taifas["sevilla"].status = "reconquista"
    cvp, mvp = compute_final_vp(s)
    # Sevilla Reconquista = 9 Christian VP (3 markers x 3).
    assert cvp == 9.0


def test_t1_sevilla_parias_worth_three_vs_other_taifa_one() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for tf in s.taifas.values():
        tf.status = "independent"
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    s.taifas_box_vp = 0.0
    s.taifas["sevilla"].status = "parias"
    s.taifas["toledo"].status = "parias"
    cvp, _ = compute_final_vp(s)
    assert cvp == 4.0   # Sevilla 3 + Toledo 1


def test_t2_muslim_conquest_in_taifa_places_jihad_removes_christian() -> None:
    """Muslim Conquest of a Stronghold in a Parias/Reconquista Taifa
    places Jihad (1 per Value), removing Christian Conquered + Seat
    markers there (1.4.4)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Pick a City in a Taifa, make it Reconquista with a Christian
    # Conquered marker + Christian Seat marker.
    loc_id = next(lid for lid, loc in s.locales.items()
                  if loc.base_type == "city" and loc.territory in s.taifas)
    loc = s.locales[loc_id]
    s.taifas[loc.territory].status = "reconquista"
    loc.conquered_markers = 3
    loc.jihad_markers = 0
    loc.seat_marker_lord_ids = ["alfonso"]   # Christian Seat
    r = _conquer_stronghold(s, loc_id, "muslim")
    assert r["marker"] == "jihad"
    assert loc.jihad_markers == 3            # City value 3
    assert loc.conquered_markers == 0        # Christian Conquered removed
    assert "alfonso" not in loc.seat_marker_lord_ids  # Christian Seat removed


def test_t2_christian_conquest_removes_jihad_places_conquered() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    loc_id = next(lid for lid, loc in s.locales.items()
                  if loc.base_type == "city" and loc.territory in s.taifas)
    loc = s.locales[loc_id]
    s.taifas[loc.territory].status = "reconquista"
    loc.jihad_markers = 2
    loc.conquered_markers = 0
    r = _conquer_stronghold(s, loc_id, "christian")
    assert r["marker"] == "conquered"
    assert loc.conquered_markers == 3        # City value
    assert loc.jihad_markers == 0            # Jihad removed
