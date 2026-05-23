"""Retreat-relocation bug-class audit (cross-project advisory, 2026-05-22).

P-3: a losing Besieger in a Sally must Retreat normally (RELOCATE off the
     Locale) and the Siege ENDS (4.5.3 "Losing Defenders Retreat normally,
     ending the Siege"). Previously apply_sally_aftermath set a "retreat"
     fate but never called apply_retreat_aftermath, so a surviving losing
     besieger stayed co-located with the winning Besieged Lord.
P-4: Scenario D starts with al-Mustain BESIEGED inside Zaragoza City and one
     yellow Siege marker (Scenario Reference: "Alfonso, Sancho, and one
     yellow Siege on al-Mustain at Zaragoza City"). The data had him as a
     field Lord with no Siege marker -> opposing field Lords co-located.
P-5: CtA auto-Muster must obey 3.4.1 ("place ... at one of his Seats that is
     neither Enemy nor has any Enemy Lords present"); Employing Rodrigo (or
     any CtA Muster) into an Enemy-occupied Stronghold is illegal.
"""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (BattleResult, BattleSide, apply_sally_aftermath)
from almoravid.effective import is_besieged
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _co_located_field_lords(s) -> list[str]:
    by: dict[str, set] = {}
    for lid, l in s.lords.items():
        if l.cylinder.kind == "locale" and not l.in_stronghold:
            by.setdefault(l.cylinder.locale_id, set()).add(l.side)
    return [loc for loc, sides in by.items()
            if "christian" in sides and "muslim" in sides]


# --- P-3 -------------------------------------------------------------------
def test_p3_sally_losing_besieger_relocates_and_siege_ends() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    am = s.lords["al_mustain"]
    am.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    am.in_stronghold = True
    sn = s.lords["sancho"]
    sn.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    sn.in_stronghold = False
    sn.forces = {"knights": 2, "men_at_arms": 2}  # survives losing
    sn.routed_units = {"light_horse": 1}
    s.locales["zaragoza"].siege_yellow = 2
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mustain"], forces=dict(am.forces))
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["sancho"], forces=dict(sn.forces))
    res = BattleResult(engagement="sally", attacker=atk, defender=dfd,
                       winner="muslim", rounds=[])
    apply_sally_aftermath(s, res, "zaragoza")
    # Besieger relocated off zaragoza (Retreat), survived with units.
    assert sn.cylinder.kind == "locale"
    assert sn.cylinder.locale_id != "zaragoza", "losing besieger not relocated"
    assert sn.forces, "besieger should survive with units"
    # Siege ended.
    assert s.locales["zaragoza"].siege_yellow == 0
    # No co-location.
    assert "zaragoza" not in _co_located_field_lords(s)


def test_p3_sally_losing_sallyer_still_withdraws_and_raid_reduces_siege() -> None:
    """Regression guard: the sallyer-loss branch is unchanged (Withdraw
    back inside; Siege -> 1, RAID)."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    am = s.lords["al_mustain"]
    am.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    am.in_stronghold = True
    sn = s.lords["sancho"]
    sn.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    sn.in_stronghold = False
    s.locales["zaragoza"].siege_yellow = 3
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mustain"], forces=dict(am.forces))
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["sancho"], forces=dict(sn.forces))
    res = BattleResult(engagement="sally", attacker=atk, defender=dfd,
                       winner="christian", rounds=[])  # sallyer (muslim) lost
    apply_sally_aftermath(s, res, "zaragoza")
    assert am.in_stronghold is True       # withdrew back inside
    assert s.locales["zaragoza"].siege_yellow == 1   # RAID reduces to 1


# --- P-4 -------------------------------------------------------------------
def test_p4_scenario_d_starts_with_al_mustain_besieged() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    am = s.lords["al_mustain"]
    assert am.cylinder.locale_id == "zaragoza"
    assert am.in_stronghold is True, "al-Mustain must start Besieged inside"
    assert s.locales["zaragoza"].siege_yellow == 1
    assert is_besieged(s, "al_mustain")
    assert "zaragoza" not in _co_located_field_lords(s)


# --- P-5 -------------------------------------------------------------------
def test_p5_cta_muster_rejected_at_enemy_occupied_seat() -> None:
    """Employing Rodrigo at a Friendly Stronghold that has an Enemy Lord
    present is illegal (3.4.1); the enumerator must not offer it and the
    handler must reject it."""
    s = load_scenario("scenario_d_arrival", seed=1)
    # Drive to the Muslim Call-to-Arms step.
    apply_action(s, {"type": "begin_levy"})
    guard = 0
    while not (s.meta.levy_step == "call_to_arms"
               and s.meta.active_player == "muslim") and guard < 120:
        side = s.meta.active_player
        if (s.meta.levy_step == "arts_of_war"
                and not s.meta.aow_draw_done.get(side)):
            apply_action(s, {"type": "aow_draw", "side": side})
            for cid in list(s.decks.pending_draw.get(side, [])):
                apply_action(s, {"type": "aow_deploy_capability", "side": side,
                                 "card_id": cid, "lord_id": "al_mustain"
                                 if side == "muslim" else "alfonso"})
        else:
            apply_action(s, {"type": "pass_step", "side": side})
        guard += 1
    assert s.meta.levy_step == "call_to_arms" and s.meta.active_player == "muslim"
    # Put a Christian (enemy) field Lord at tudela, a Muslim-Friendly seat.
    s.lords["garcia_ordonez"].cylinder = Cylinder(kind="locale",
                                                  locale_id="tudela")
    s.lords["garcia_ordonez"].in_stronghold = False
    # The enumerator must not offer Employing Rodrigo at tudela.
    employ_seats = [m.get("seat") for m in legal_moves(s)
                    if m.get("type") == "cta_employ_rodrigo"]
    assert "tudela" not in employ_seats, employ_seats
    # And the handler must reject it directly.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cta_employ_rodrigo", "side": "muslim",
                         "seat": "tudela",
                         "payments": [{"taifa_box": 3}]})
    assert ei.value.code in ("enemy_lord_present", "not_friendly",
                             "under_siege", "bad_arg")
