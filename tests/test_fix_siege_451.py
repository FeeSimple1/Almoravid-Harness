"""FIX-B: Siege 4.5.1 order/markers — Surrender (vs existing markers,
ravaged locale-capped at 1) BEFORE Siegeworks; Siegeworks +1 max 4."""
from __future__ import annotations
from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests.test_siege import _activate_lord


def test_surrender_checked_against_existing_markers_not_post_siegeworks():
    """Surrender threshold uses markers ALREADY there, before any
    Siegeworks marker this action is added."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    # Castle (value 1, capacity 1): 1 die, threshold = existing siege.
    loc = "calatayud"
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.locales[loc].siege_yellow = 0
    s.locales[loc].ravaged = "none"
    # With 0 markers, threshold=0 -> a d6 can never be <=0 -> never
    # surrenders, so Siegeworks fires (+1 at capacity 1).
    r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert r["surrender"]["succeeded"] is False
    assert r["surrender"]["threshold"] == 0
    assert s.locales[loc].siege_yellow == 1  # siegeworks added after


def test_ravaged_counts_at_locale_capped_one():
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    loc = "calatayud"
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.locales[loc].siege_yellow = 3
    s.locales[loc].ravaged = "yellow"  # besieger's ravage at THIS locale
    r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    # threshold = min(4,3) + min(1, ravaged_here=1) = 4
    assert r["surrender"]["threshold"] == 4


def test_no_surrender_when_enemy_lord_inside():
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    loc = "zaragoza"
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.locales[loc].siege_yellow = 4
    # Put a Muslim Lord inside the stronghold.
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.lords["al_mustain"].in_stronghold = True
    r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert r["surrender"] is None  # no surrender attempted
