"""FIX-A (finding L2): Call to Arms (3.5).

The five Fealty-less Lords (Yusuf, Sir, Eudes, Rodrigo al-Sayyid /
Campeador) can enter play ONLY via Call to Arms. These tests exercise
every 3.5.1 / 3.5.2 option, the one-option-per-side limit, and the
enumerator roundtrip.
"""
from __future__ import annotations

import copy

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.effective import is_friendly_locale
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker

STRONG = ("city", "fortress", "town", "castle")


def _to_cta(s, side="christian"):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "call_to_arms")
    assert s.meta.levy_step == "call_to_arms"
    while s.meta.active_player != side:
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    return s


def _friendly_stronghold(s, side):
    for lid, loc in s.locales.items():
        if (loc.base_type in STRONG and loc.siege_yellow == 0
                and loc.siege_green == 0
                and is_friendly_locale(s, lid, side)):
            return lid
    return None


# ---- 3.5.1 Reconcile with Rodrigo ----------------------------------------

def test_reconcile_when_sayyid_on_map():
    s = load_scenario("scenario_d_arrival", seed=3)
    sayyid = s.lords["rodrigo_al_sayyid"]
    sayyid.cylinder = Cylinder(kind="locale", locale_id="valencia")
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers
        if m.lord_id != "rodrigo_al_sayyid"]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="rodrigo_al_sayyid",
                      box=s.calendar.current_box + 3))
    _to_cta(s, "christian")
    vp0 = s.taifas_box_vp
    r = apply_action(s, {"type": "cta_reconcile_rodrigo", "side": "christian"})
    # 1 (Conquered marker) + 3 (boxes ahead) = 4 VP to the Taifas box.
    assert r["vp_to_taifas_box"] == 4.0
    assert s.taifas_box_vp == vp0 + 4.0
    assert s.lords["rodrigo_al_sayyid"].cylinder.kind == "set_aside"
    camp = s.lords["rodrigo_campeador"]
    assert camp.cylinder.kind == "calendar"
    assert camp.cylinder.box == min(16, s.calendar.current_box + 2)
    assert not any(m.lord_id == "rodrigo_al_sayyid"
                   for m in s.calendar.service_markers)


def test_reconcile_unavailable_without_trigger():
    s = load_scenario("scenario_d_arrival", seed=3)
    # al-Sayyid on Calendar (not on map), no Christian Lord removed.
    s.lords["rodrigo_al_sayyid"].cylinder = Cylinder(kind="calendar", box=12)
    _to_cta(s, "christian")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cta_reconcile_rodrigo", "side": "christian"})
    assert ei.value.code == "cta_unavailable"


# ---- 3.5.1 Employ Rodrigo Campeador --------------------------------------

def test_employ_campeador_pays_two_coin_and_musters():
    s = load_scenario("scenario_d_arrival", seed=3)
    camp = s.lords["rodrigo_campeador"]
    camp.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    payer = next(l for l in s.lords.values()
                 if l.side == "christian" and l.cylinder.kind == "locale")
    payer.assets["coin"] = 2
    _to_cta(s, "christian")
    seat = _friendly_stronghold(s, "christian")
    assert seat is not None
    r = apply_action(s, {"type": "cta_employ_rodrigo", "side": "christian",
                         "seat": seat,
                         "payments": [{"lord_id": payer.id, "coin": 2}]})
    assert r["seat"] == seat
    assert camp.cylinder.kind == "locale" and camp.cylinder.locale_id == seat
    assert payer.assets.get("coin", 0) == 0
    assert "rodrigo_campeador" in s.locales[seat].seat_marker_lord_ids


def test_employ_campeador_wrong_payment_total_raises():
    s = load_scenario("scenario_d_arrival", seed=3)
    camp = s.lords["rodrigo_campeador"]
    camp.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    payer = next(l for l in s.lords.values()
                 if l.side == "christian" and l.cylinder.kind == "locale")
    payer.assets["coin"] = 3
    _to_cta(s, "christian")
    seat = _friendly_stronghold(s, "christian")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cta_employ_rodrigo", "side": "christian",
                         "seat": seat,
                         "payments": [{"lord_id": payer.id, "coin": 1}]})
    assert ei.value.code == "bad_payment_total"


def test_employ_campeador_not_ready_raises():
    s = load_scenario("scenario_d_arrival", seed=3)
    s.lords["rodrigo_campeador"].cylinder = Cylinder(kind="set_aside")
    _to_cta(s, "christian")
    seat = _friendly_stronghold(s, "christian")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cta_employ_rodrigo", "side": "christian",
                         "seat": seat,
                         "payments": [{"lord_id": "sancho", "coin": 2}]})
    assert ei.value.code == "not_ready"


# ---- 3.5.1 Call for Crusade ----------------------------------------------

def test_call_for_crusade_musters_eudes_and_sets_pending():
    s = load_scenario("scenario_d_arrival", seed=3)
    eudes = s.lords["eudes"]
    eudes.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    # Make Pamplona Christian-Friendly + free of Siege.
    s.locales["pamplona"].seat_marker_lord_ids = []
    s.locales["pamplona"].conquered_markers = 0
    s.locales["pamplona"].jihad_markers = 0
    s.locales["pamplona"].siege_yellow = 0
    s.locales["pamplona"].siege_green = 0
    assert is_friendly_locale(s, "pamplona", "christian")
    _to_cta(s, "christian")
    r = apply_action(s, {"type": "cta_call_crusade", "side": "christian"})
    assert eudes.cylinder.kind == "locale"
    assert eudes.cylinder.locale_id == "pamplona"
    assert r["muslim_jihad_pending"] is True
    assert s.meta.cta_crusade_jihad_pending is True


# ---- 3.5.2 Employ Rodrigo al-Sayyid --------------------------------------

def test_employ_al_sayyid_pays_three_from_taifa_box():
    s = load_scenario("scenario_d_arrival", seed=3)
    sayyid = s.lords["rodrigo_al_sayyid"]
    sayyid.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    s.taifas_box_coin = 5
    _to_cta(s, "muslim")
    seat = _friendly_stronghold(s, "muslim")
    assert seat is not None
    r = apply_action(s, {"type": "cta_employ_rodrigo", "side": "muslim",
                         "seat": seat,
                         "payments": [{"taifa_box": 3}]})
    assert r["coin_paid"] == 3
    assert s.taifas_box_coin == 2
    assert sayyid.cylinder.kind == "locale" and sayyid.cylinder.locale_id == seat


# ---- 3.5.2 Invite the Almoravids -----------------------------------------

def test_invite_almoravids_musters_and_places_eudes():
    s = load_scenario("scenario_d_arrival", seed=3)
    sir = s.lords["sir"]
    sir.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    # Eudes set aside so Invite places him on the Calendar.
    s.lords["eudes"].cylinder = Cylinder(kind="set_aside")
    _to_cta(s, "muslim")
    r = apply_action(s, {"type": "cta_invite_almoravids", "side": "muslim",
                         "lord_id": "sir"})
    assert sir.cylinder.kind == "locale"
    assert r["seat"] is not None
    assert s.lords["eudes"].cylinder.kind == "calendar"
    assert r["eudes_calendar_box"] == min(16, s.calendar.current_box + 2)


# ---- 3.5.2 Uphold the Dynasties ------------------------------------------

def test_uphold_dynasties_shifts_both_and_banks_vp():
    s = load_scenario("scenario_d_arrival", seed=3)
    cb = s.calendar.current_box
    s.lords["yusuf"].cylinder = Cylinder(kind="calendar", box=cb)
    s.lords["sir"].cylinder = Cylinder(kind="calendar", box=cb)
    _to_cta(s, "muslim")
    vp0 = s.taifas_box_vp
    from almoravid.events import _jihad_eligible_locales
    elig = _jihad_eligible_locales(s)
    action = {"type": "cta_uphold_dynasties", "side": "muslim"}
    if elig:
        action["jihad_locale"] = elig[0]
    r = apply_action(s, action)
    assert s.lords["yusuf"].cylinder.box == min(16, cb + 1)
    assert s.lords["sir"].cylinder.box == min(16, cb + 1)
    assert s.taifas_box_vp == vp0 + 1.0
    if elig:
        assert s.locales[elig[0]].jihad_markers >= 1


# ---- 3.5.2 Call upon an Emir ---------------------------------------------

def test_call_emir_musters_taifa_lord():
    s = load_scenario("scenario_d_arrival", seed=3)
    # Find a Taifa Lord on the Calendar with a printed Seat, sit Yusuf there.
    tl = next((l for l in s.lords.values()
               if l.is_taifa and l.seats and l.cylinder.kind == "calendar"),
              None)
    if tl is None:
        pytest.skip("no Calendar Taifa Lord with a Seat in this scenario")
    seat = tl.seats[0]
    # Ensure the Seat is Muslim-Friendly + free of Siege.
    s.taifas[s.locales[seat].territory].status = "independent"
    s.locales[seat].siege_yellow = 0
    s.locales[seat].siege_green = 0
    s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id=seat)
    _to_cta(s, "muslim")
    free = [seat] if not any(
        o.cylinder.kind == "locale" and o.cylinder.locale_id == seat
        and o.side != tl.side for o in s.lords.values()) else []
    if not free:
        pytest.skip("seat blocked by enemy presence")
    r = apply_action(s, {"type": "cta_call_emir", "side": "muslim",
                         "taifa_lord_id": tl.id, "mode": "muster",
                         "seat": seat})
    assert r["mode"] == "muster"
    assert s.lords[tl.id].cylinder.kind == "locale"
    # Mustering a Taifa Lord adjusts his Taifa to Independent.
    assert s.taifas[tl.home_taifa].status == "independent"


# ---- one-option-per-side limit -------------------------------------------

def test_one_option_per_side():
    s = load_scenario("scenario_d_arrival", seed=3)
    eudes = s.lords["eudes"]
    eudes.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    s.locales["pamplona"].siege_yellow = 0
    s.locales["pamplona"].siege_green = 0
    s.locales["pamplona"].seat_marker_lord_ids = []
    s.locales["pamplona"].conquered_markers = 0
    _to_cta(s, "christian")
    apply_action(s, {"type": "cta_call_crusade", "side": "christian"})
    # Christian is now done; trying another Christian option raises
    # (either cta_used or not_active depending on baton).
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "cta_reconcile_rodrigo", "side": "christian"})


# ---- crusade Jihad follow-up ---------------------------------------------

def test_crusade_jihad_added_by_muslim():
    s = load_scenario("scenario_d_arrival", seed=3)
    eudes = s.lords["eudes"]
    eudes.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    s.locales["pamplona"].siege_yellow = 0
    s.locales["pamplona"].siege_green = 0
    s.locales["pamplona"].seat_marker_lord_ids = []
    s.locales["pamplona"].conquered_markers = 0
    _to_cta(s, "christian")
    apply_action(s, {"type": "cta_call_crusade", "side": "christian"})
    assert s.meta.active_player == "muslim"
    from almoravid.events import _jihad_eligible_locales
    elig = _jihad_eligible_locales(s)
    if not elig:
        pytest.skip("no Jihad-eligible Locale")
    tgt = elig[0]
    j0 = s.locales[tgt].jihad_markers
    apply_action(s, {"type": "cta_add_crusade_jihad", "side": "muslim",
                     "jihad_locale": tgt})
    assert s.locales[tgt].jihad_markers == j0 + 1
    assert s.meta.cta_crusade_jihad_pending is False


# ---- enumerator roundtrip ------------------------------------------------

def test_cta_enumerator_moves_are_applyable():
    s = load_scenario("scenario_d_arrival", seed=3)
    # Make several options live.
    cb = s.calendar.current_box
    s.lords["rodrigo_campeador"].cylinder = Cylinder(kind="calendar", box=cb)
    s.lords["eudes"].cylinder = Cylinder(kind="calendar", box=cb)
    payer = next(l for l in s.lords.values()
                 if l.side == "christian" and l.cylinder.kind == "locale")
    payer.assets["coin"] = 5
    _to_cta(s, "christian")
    moves = [m for m in legal_moves(s)
             if m["type"].startswith("cta_")]
    assert moves, "expected some Call to Arms options"
    for m in moves:
        snap = copy.deepcopy(s)
        # Should not raise IllegalAction.
        apply_action(snap, m)


def test_pass_step_does_nothing_in_cta():
    s = load_scenario("scenario_d_arrival", seed=3)
    _to_cta(s, "christian")
    apply_action(s, {"type": "pass_step", "side": "christian"})
    apply_action(s, {"type": "pass_step", "side": "muslim"})
    # Both passed -> Levy ends, phase advances to campaign.
    assert s.meta.phase == "campaign"
