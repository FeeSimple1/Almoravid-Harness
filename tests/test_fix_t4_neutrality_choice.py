"""FIX-D / T4 RECOGNITION OF NEUTRALITY OR-choice (rule 1.4.3).

When a Taifa becomes Parias, a side Besieging/Bypassing an Enemy
Stronghold there that just became Neutral CHOOSES either to remove its
Siege/Bypass OR to add Enemy victory markers (= Stronghold Value). The
choice is surfaced via neutrality_choices (no greedy hardcode); the
default when unspecified is the conservative 'remove'.
"""

from __future__ import annotations

from almoravid.campaign import adjust_taifa_status
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _setup_christian_besieger_at_calatayud(s):
    # calatayud is a Castle (Value 1) in the Independent Zaragoza Taifa,
    # with no Muslim Lord present.
    lord = s.lords["alvar_fanez"]
    lord.cylinder = Cylinder(kind="locale", locale_id="calatayud")
    lord.in_stronghold = False
    s.locales["calatayud"].siege_yellow = 2
    s.locales["calatayud"].jihad_markers = 0


def test_t4_add_choice_places_jihad_and_keeps_siege() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup_christian_besieger_at_calatayud(s)
    r = adjust_taifa_status(s, "zaragoza", "parias",
                            neutrality_choices={"calatayud": "add"})
    loc = s.locales["calatayud"]
    # 'add' places Jihad = Castle Value (1) and KEEPS the Siege.
    assert loc.jihad_markers == 1
    assert loc.siege_yellow == 2
    assert ("calatayud", 1) in r["jihad_added"]


def test_t4_default_remove_choice_lifts_siege() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup_christian_besieger_at_calatayud(s)
    r = adjust_taifa_status(s, "zaragoza", "parias")  # default 'remove'
    loc = s.locales["calatayud"]
    assert loc.siege_yellow == 0           # Siege removed
    assert loc.jihad_markers == 0          # no Enemy markers added
    assert any(entry[0] == "calatayud" for entry in r["siege_removed"])
