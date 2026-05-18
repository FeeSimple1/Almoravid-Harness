"""Pre-fix tests: expose the mirror-gap bugs in adjust_taifa_status."""

from almoravid.campaign import adjust_taifa_status
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_reconquista_to_independent_muslim_lord_loses_siege():
    """Bug A: RECONQUISTA -> INDEPENDENT.
    Per 1.4.3: 'Muslim Lord at Christian Stronghold that goes Muslim:
    remove Siege/Bypass.'
    The Muslim Lord was besieging a Reconquista Stronghold; when the
    Taifa flips back to Independent the Stronghold becomes Muslim-
    friendly, and the Muslim Lord's siege markers should clear.
    """
    s = load_scenario("scenario_b_quelling_of_tajo")
    # Set up: Toledo Taifa Reconquista; Muslim Lord besieging Toledo
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.lords["al_mutamid"].in_stronghold = False
    s.locales["toledo"].siege_green = 2
    r = adjust_taifa_status(s, "toledo", "independent")
    assert s.locales["toledo"].siege_green == 0, (
        f"Bug A: Muslim Lord's Siege at newly-Muslim Stronghold should "
        f"have been removed; got siege_green={s.locales['toledo'].siege_green}"
    )


def test_reconquista_to_parias_muslim_lord_at_christian_stronghold_resolves():
    """Bug B: RECONQUISTA -> PARIAS.
    Per 1.4.3: 'Muslim Lord at Christian Stronghold that would go Neutral:
    either remove Siege/Bypass OR add Christian Conquered (= value).'
    Phase 5l: conservative choice is remove Siege/Bypass.
    """
    s = load_scenario("scenario_b_quelling_of_tajo")
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.lords["al_mutamid"].in_stronghold = False
    s.locales["toledo"].siege_green = 1
    r = adjust_taifa_status(s, "toledo", "parias")
    # Conservative resolution: Siege removed (the OR clause).
    assert s.locales["toledo"].siege_green == 0, (
        "Bug B: Muslim Lord siege_green at Christian Stronghold should "
        "have been resolved per 1.4.3 RECONQUISTA->PARIAS OR clause."
    )


def test_independent_to_parias_christian_lord_at_muslim_stronghold_resolves():
    """Bug C: INDEPENDENT -> PARIAS.
    Per 1.4.3: 'Christian Lord at Muslim Stronghold that would go
    Neutral: either remove Siege/Bypass OR add Jihad (markers = value).'
    Phase 5l: conservative = remove Siege/Bypass.
    """
    s = load_scenario("scenario_a_toledo_beset")
    # Scenario A: Zaragoza is Independent. Christian besieges it.
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    s.lords["alvar_fanez"].in_stronghold = False
    s.locales["zaragoza"].siege_yellow = 1
    r = adjust_taifa_status(s, "zaragoza", "parias")
    assert s.locales["zaragoza"].siege_yellow == 0, (
        "Bug C: Christian Lord's Siege at newly-Neutral Stronghold should "
        "have been resolved per 1.4.3 INDEPENDENT->PARIAS OR clause."
    )
