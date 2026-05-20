"""FIX-D T2: Conquest marker placement (1.4.4 / 4.5)."""
from __future__ import annotations
from almoravid.campaign import _conquer_stronghold
from almoravid.scenarios import load_scenario


def _taifa_stronghold(s, status):
    t = next(iter(s.taifas.values()))
    t.status = status
    loc = next(lid for lid in t.locale_ids
               if s.locales[lid].base_type != "region")
    s.locales[loc].conquered_markers = 0
    s.locales[loc].jihad_markers = 0
    return t, loc


def test_muslim_conquest_in_parias_taifa_places_jihad():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _taifa_stronghold(s, "parias")
    val = {"city": 3, "fortress": 2, "town": 1, "castle": 1}[s.locales[loc].base_type]
    r = _conquer_stronghold(s, loc, "muslim")
    assert r["marker"] == "jihad"
    assert s.locales[loc].jihad_markers == val
    assert s.locales[loc].conquered_markers == 0


def test_muslim_conquest_in_reconquista_taifa_places_jihad_and_removes_conquered():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _taifa_stronghold(s, "reconquista")
    s.locales[loc].conquered_markers = 2  # existing Christian Conquered
    r = _conquer_stronghold(s, loc, "muslim")
    assert r["marker"] == "jihad"
    assert s.locales[loc].conquered_markers == 0  # removed
    assert r["removed"].get("conquered") == 2


def test_christian_conquest_places_conquered_and_removes_jihad():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _taifa_stronghold(s, "independent")
    s.locales[loc].jihad_markers = 3  # existing Jihad
    val = {"city": 3, "fortress": 2, "town": 1, "castle": 1}[s.locales[loc].base_type]
    r = _conquer_stronghold(s, loc, "christian")
    assert r["marker"] == "conquered"
    assert s.locales[loc].conquered_markers == val
    assert s.locales[loc].jihad_markers == 0  # all Jihad removed
    assert r["removed"].get("jihad") == 3


def test_conquered_markers_set_to_value_not_stacked():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t, loc = _taifa_stronghold(s, "independent")
    val = {"city": 3, "fortress": 2, "town": 1, "castle": 1}[s.locales[loc].base_type]
    s.locales[loc].conquered_markers = val  # already conquered
    _conquer_stronghold(s, loc, "christian")
    # Re-conquest keeps it at value, doesn't stack to 2*value.
    assert s.locales[loc].conquered_markers == val
