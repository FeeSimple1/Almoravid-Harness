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
    s.taifas["toledo"].status = "reconquista"
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.lords["al_mutamid"].in_stronghold = False
    s.locales["toledo"].siege_green = 1
    s.locales["toledo"].conquered_markers = 0   # becomes truly Neutral
    s.locales["toledo"].jihad_markers = 0
    # T4: with NO explicit choice, the OR clause is DEFERRED (not applied);
    # the Stronghold is surfaced for a RECOGNITION OF NEUTRALITY decision.
    r = adjust_taifa_status(s, "toledo", "parias")
    assert any(d["locale_id"] == "toledo" and d["side"] == "muslim"
               for d in r["deferred_neutrality"])
    assert s.locales["toledo"].siege_green == 1   # not yet resolved
    # Explicit 'remove' resolves it (conservative); 'add' would place
    # Christian Conquered markers instead.
    s2 = load_scenario("scenario_b_quelling_of_tajo")
    s2.taifas["toledo"].status = "reconquista"
    s2.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s2.lords["al_mutamid"].in_stronghold = False
    s2.locales["toledo"].siege_green = 1
    s2.locales["toledo"].conquered_markers = 0
    s2.locales["toledo"].jihad_markers = 0
    adjust_taifa_status(s2, "toledo", "parias",
                        neutrality_choices={"toledo": "remove"})
    assert s2.locales["toledo"].siege_green == 0


def test_independent_to_parias_christian_lord_at_muslim_stronghold_resolves():
    """Bug C: INDEPENDENT -> PARIAS.
    Per 1.4.3: 'Christian Lord at Muslim Stronghold that would go
    Neutral: either remove Siege/Bypass OR add Jihad (markers = value).'
    Phase 5l: conservative = remove Siege/Bypass.
    """
    s = load_scenario("scenario_a_toledo_beset")
    # Scenario A: the Zaragoza Taifa is Independent. Christian besieges
    # calatayud (a Castle there with no Taifa Lord) -> becomes Neutral.
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="calatayud")
    s.lords["alvar_fanez"].in_stronghold = False
    s.locales["calatayud"].siege_yellow = 1
    s.locales["calatayud"].conquered_markers = 0
    s.locales["calatayud"].jihad_markers = 0
    # T4: deferred without a choice.
    r = adjust_taifa_status(s, "zaragoza", "parias")
    assert any(d["locale_id"] == "calatayud" and d["side"] == "christian"
               for d in r["deferred_neutrality"])
    assert s.locales["calatayud"].siege_yellow == 1
    # Explicit 'add' places Jihad (= Stronghold Value) and keeps Siege.
    s2 = load_scenario("scenario_a_toledo_beset")
    s2.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                                locale_id="calatayud")
    s2.lords["alvar_fanez"].in_stronghold = False
    s2.locales["calatayud"].siege_yellow = 1
    s2.locales["calatayud"].jihad_markers = 0
    s2.locales["calatayud"].conquered_markers = 0
    adjust_taifa_status(s2, "zaragoza", "parias",
                        neutrality_choices={"calatayud": "add"})
    assert s2.locales["calatayud"].jihad_markers > 0
    assert s2.locales["calatayud"].siege_yellow == 1   # kept (chose add)
