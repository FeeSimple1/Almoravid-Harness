"""Regression tests for the rules-fidelity bugs surfaced by the
clause-by-clause reconciliation matrix audit (see RECONCILIATION_MATRIX.md).

Each test pins a specific Rules-of-Play clause that the audit found
incorrect or unimplemented:

  * 4.5.4  — Jihad added at a Muslim Siege removes all Siege markers.
  * 4.3.6  — only a Marshal or a (real, upper) Lieutenant may Sortie a group.
  * 6.3.3  — a stranded Spring-Muster Taifa Lord adjusts Taifa status + Coin.
  * 1.9.1  — M14/M18 Ribat Monks: Christian Ravage rolls 1-3 for effect.
"""
from __future__ import annotations

import almoravid.rng as rng
from almoravid.actions import apply_action
from almoravid.campaign import spring_muster
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


# ---------------------------------------------------------------------------
# 4.5.4 — Jihad added at a Muslim Siege removes all (green) Siege markers.
# ---------------------------------------------------------------------------

def test_add_jihad_clears_muslim_siege_454() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    loc = next(iter(s.locales.values()))
    loc.siege_green = 3
    loc.siege_yellow = 0
    before = loc.jihad_markers
    loc.add_jihad(1)
    assert loc.jihad_markers == before + 1
    assert loc.siege_green == 0          # 4.5.4: Muslim Siege removed


def test_add_jihad_leaves_christian_siege_454() -> None:
    """A Christian (yellow) Siege is NOT a 'Muslim Siege' — untouched."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    loc = next(iter(s.locales.values()))
    loc.siege_yellow = 2
    loc.siege_green = 0
    loc.add_jihad(2)
    assert loc.siege_yellow == 2
    assert loc.jihad_markers >= 2


def test_event_jihad_path_clears_muslim_siege_454() -> None:
    """The events `_add_jihad` distribution path also honours 4.5.4."""
    from almoravid.events import _add_jihad, _jihad_eligible_locales
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    elig = _jihad_eligible_locales(s)
    assert elig, "scenario should have an eligible Jihad Locale"
    target = elig[0]
    s.locales[target].siege_green = 4
    placed = _add_jihad(s, 1, {"jihad_targets": [target]})
    assert placed and placed.get(target, 0) >= 1
    assert s.locales[target].siege_green == 0


# ---------------------------------------------------------------------------
# 4.3.6 / 4.3.1 — group Sortie leadership: Marshal or real Lieutenant only.
# ---------------------------------------------------------------------------

def _group_sortie_setup(seed: int = 3):
    """Two non-Marshal Christian Lords inside a Bypassed Friendly City.
    `alvar_fanez` is the upper Lord (the Lieutenant); `pedro_ansurez`
    is his Lower Lord. A Muslim is Bypassing the City."""
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    here = "leon"
    upper, lower = s.lords["alvar_fanez"], s.lords["pedro_ansurez"]
    for L in (upper, lower):
        L.cylinder = Cylinder(kind="locale", locale_id=here)
        L.in_stronghold = True
        L.moved_fought = False
        L.forces = {"knights": 1}
    # Designate the Lieutenant relationship (internal flag marks the LOWER).
    lower.is_lieutenant = True
    lower.lieutenant_of = "alvar_fanez"
    enemy = s.lords["al_mustain"]
    enemy.cylinder = Cylinder(kind="locale", locale_id=here)
    enemy.in_stronghold = False
    enemy.forces = {"sergeants": 1}
    s.locales[here].bypass_green = True
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.actions_remaining = 3
    return s, here


def test_lieutenant_upper_lord_may_sortie_group_436() -> None:
    s, here = _group_sortie_setup()
    s.meta.active_lord_id = "alvar_fanez"        # the real Lieutenant
    r = apply_action(s, {"type": "cmd_sortie", "side": "christian",
                         "group_lord_ids": ["pedro_ansurez"]})
    assert r["sortie"] == here
    assert s.lords["alvar_fanez"].in_stronghold is False
    assert s.lords["pedro_ansurez"].in_stronghold is False


def test_lower_lord_may_not_sortie_group_436() -> None:
    """The Lower Lord (internal is_lieutenant=True) must NOT lead a group.
    This is the exact inversion the audit caught."""
    s, here = _group_sortie_setup()
    s.meta.active_lord_id = "pedro_ansurez"      # the Lower Lord
    try:
        apply_action(s, {"type": "cmd_sortie", "side": "christian",
                         "group_lord_ids": ["alvar_fanez"]})
        assert False, "expected rejection: Lower Lord cannot lead a group"
    except Exception as e:
        assert "not_group_leader" in str(e) or "Marshal or Lieutenant" in str(e)


# ---------------------------------------------------------------------------
# 6.3.3 — stranded Spring-Muster Taifa Lord adjusts status + Parias Coin.
# ---------------------------------------------------------------------------

def test_spring_muster_stranded_taifa_lord_goes_parias_633() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    tl = s.lords["al_mustain"]
    taifa = tl.home_taifa
    assert s.taifas[taifa].status == "independent"
    # Put the Taifa Lord on his mat (Disbanded to mat in Winter).
    tl.cylinder = Cylinder(kind="mat")
    tl.in_stronghold = False
    # Occupy every one of his Seats with an enemy Christian Lord so he
    # has NO free Seat at Spring Muster.
    blocker = s.lords["alfonso"]
    seats = list(tl.seats)
    assert seats
    blocker.cylinder = Cylinder(kind="locale", locale_id=seats[0])
    # Ensure an Unbesieged Christian Lord exists to receive Parias Coin.
    rcv = s.lords["garcia_ordonez"]
    rcv.cylinder = Cylinder(kind="locale", locale_id="leon")
    rcv.in_stronghold = False
    coin_before = rcv.assets.get("coin", 0)
    christ_vp_before = s.score.christian

    res = spring_muster(s)

    assert "al_mustain" in res["no_free_seat"]
    assert tl.cylinder.kind == "calendar"
    assert s.taifas[taifa].status == "parias"           # 6.3.3 -> 1.4.1
    assert s.score.christian == christ_vp_before + 1.0   # +1 VP Parias
    total_coin = sum(L.assets.get("coin", 0) for L in s.lords.values()
                     if L.side == "christian")
    assert total_coin >= coin_before + 1                 # Parias Coin paid


# ---------------------------------------------------------------------------
# M14 / M18 Ribat Monks — Christian Ravage must roll 1-3 for effect (1.9.1).
# ---------------------------------------------------------------------------

def _ravage_setup(seed: int = 1, target: str = "medinaceli"):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    # al_mustain (Zaragoza Taifa Lord) holds Ribat Monks.
    s.lords["al_mustain"].capabilities.append("M14")
    rav = s.lords["alvar_fanez"]
    rav.cylinder = Cylinder(kind="locale", locale_id=target)
    rav.in_stronghold = False
    s.locales[target].ravaged = "none"
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alvar_fanez"
    s.meta.actions_remaining = 2
    return s, target


def test_ribat_monks_blocks_ravage_on_high_roll(monkeypatch) -> None:
    s, target = _ravage_setup()
    monkeypatch.setattr(rng, "roll_d6", lambda state: 5)
    vp_before = s.score.christian
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert r.get("no_effect") is True
    assert r["ribat_monks_roll"] == 5
    assert s.locales[target].ravaged == "none"           # no marker placed
    assert s.score.christian == vp_before                 # no VP
    assert s.meta.actions_remaining == 1                  # action still spent


def test_ribat_monks_allows_ravage_on_low_roll(monkeypatch) -> None:
    s, target = _ravage_setup()
    monkeypatch.setattr(rng, "roll_d6", lambda state: 2)
    vp_before = s.score.christian
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert r.get("no_effect") is not True
    assert r["ribat_monks_roll"] == 2
    assert s.locales[target].ravaged == "yellow"          # marker placed
    assert s.score.christian == vp_before + 0.5


def test_ravage_without_ribat_monks_makes_no_roll() -> None:
    s, target = _ravage_setup()
    s.lords["al_mustain"].capabilities.clear()            # no Ribat Monks
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert r["ribat_monks_roll"] is None
    assert s.locales[target].ravaged == "yellow"


def test_ribat_monks_eligibility_is_taifa_muslim_only() -> None:
    from almoravid.capabilities import capability_eligible_lords
    elig = capability_eligible_lords("M14")
    assert elig is not None
    assert "al_mustain" in elig
    assert "yusuf" not in elig and "sir" not in elig       # not Taifa Lords
    assert capability_eligible_lords("M18") == elig
