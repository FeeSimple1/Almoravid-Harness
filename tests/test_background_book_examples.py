"""Exact-outcome regression tests transcribed from GMT's *Almoravid*
Background Book, "Examples of Play" (pp. 6-11).

These are gold-standard fidelity anchors: each asserts the precise,
published numbers from a worked example, so the engine is validated
against GMT's own stated results rather than only against our reading
of the rules text.
"""
from __future__ import annotations

from almoravid.campaign import adjust_taifa_status, compute_final_vp
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests.test_fix_call_to_arms import _to_cta


# ---------------------------------------------------------------------------
# Background Book pp.6-7 — "The Conquest of Toledo" (Parias -> Reconquista).
# Stated outcomes: Taifa flips to Reconquista (+2 VP, the 3-vs-1 difference);
# the yellow Ravaged marker at Toledo City flips to green (Christian -1/2,
# Muslim +1/2); al-Mutamid at the Fortress of Calatrava receives 2 Jihad
# markers (Fortress value 2) for Muslim +1 VP (Hostage Populace, 1.4.3).
# ---------------------------------------------------------------------------

def test_bgbook_conquest_of_toledo() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    assert s.taifas["toledo"].status == "parias"

    # Exactly one yellow Ravaged marker in Toledo, at Toledo City.
    for lid in s.taifas["toledo"].locale_ids:
        s.locales[lid].ravaged = "none"
    s.locales["toledo"].ravaged = "yellow"
    # al-Mutamid stands at Calatrava (Fortress, value 2), starting clean.
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="calatrava")
    s.locales["calatrava"].jihad_markers = 0

    christ0, musl0 = s.score.christian, s.score.muslim
    cfin_c0, _ = compute_final_vp(s)

    adjust_taifa_status(s, "toledo", "reconquista")

    # Status flip.
    assert s.taifas["toledo"].status == "reconquista"
    # Ravaged Land: yellow -> green at Toledo City.
    assert s.locales["toledo"].ravaged == "green"
    # Hostage Populace: 2 Jihad at Calatrava (Fortress value 2).
    assert s.locales["calatrava"].jihad_markers == 2
    # Running-score cascade: Christian -1/2 (ravage flip); Muslim +1
    # (Calatrava Jihad) +1/2 (ravage flip) = +1 1/2.
    assert s.score.christian - christ0 == -0.5
    assert s.score.muslim - musl0 == 1.5
    # Final-VP: the Taifa status itself swings the Christians +2
    # (Reconquista 3 VP vs Parias 1 VP), net of the ravage flip (-1/2)
    # = +1 1/2 to the Christian final total.
    cfin_c1, _ = compute_final_vp(s)
    assert cfin_c1 - cfin_c0 == 1.5


# ---------------------------------------------------------------------------
# Background Book p.11 — "Uphold the Dynasties" (Scenario E, Levy of box 9).
# Stated outcome: Yusuf and Sir shift one box ahead (9 -> 10); the Muslim
# side gains 1 1/2 VP total (a 1 VP Conquered marker to the Taifas box plus
# a 1/2 VP Jihad on the map), moving the Muslim score from 8 to 9 1/2.
# ---------------------------------------------------------------------------

def test_bgbook_uphold_the_dynasties_scenario_e() -> None:
    s = load_scenario("scenario_e_alfonso", seed=3)
    assert s.calendar.current_box == 9
    assert s.score.muslim == 8.0
    cb = s.calendar.current_box
    assert s.lords["yusuf"].cylinder.box == cb
    assert s.lords["sir"].cylinder.box == cb

    _to_cta(s, "muslim")
    box0 = s.taifas_box_vp
    _, musl_final0 = compute_final_vp(s)

    from almoravid.events import _jihad_eligible_locales
    elig = _jihad_eligible_locales(s)
    action = {"type": "cta_uphold_dynasties", "side": "muslim"}
    if elig:
        action["jihad_locale"] = elig[0]
    from almoravid.actions import apply_action
    apply_action(s, action)

    # Both Almoravid Lords shift one box ahead (9 -> 10).
    assert s.lords["yusuf"].cylinder.box == min(16, cb + 1)
    assert s.lords["sir"].cylinder.box == min(16, cb + 1)
    # +1 VP Conquered marker banked in the Taifas box.
    assert s.taifas_box_vp == box0 + 1.0
    # +1/2 VP Jihad placed on the map.
    if elig:
        assert s.locales[elig[0]].jihad_markers >= 1
    # Authoritative ledger (compute_final_vp): a net Muslim swing of
    # +1 1/2 (Taifas-box Conquered 1 + on-map Jihad 1/2): 8 -> 9 1/2,
    # exactly as printed in the Background Book.
    _, musl_final1 = compute_final_vp(s)
    assert musl_final0 == 8.0
    assert musl_final1 == 9.5
    assert musl_final1 - musl_final0 == 1.5
