"""6.3.2 Winter Siege interactive mini-sequence (Scenario F).

Per Winter box: besieging Lords each take one Supply/Ravage/pass; then
all Siege-Locale Lords Feed; then Christian/Muslim Pay; then at-limit
Disband. Boxes 7 then 8, ending in the box-9 Spring Levy.
"""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.campaign import _enter_winter_box, _siege_locale_lords
from almoravid.state import Cylinder, ServiceMarker


def _clear_all_lords_off_map(s):
    # Simulate post-Winter-Disband: only siege Lords remain on map.
    for l in s.lords.values():
        if l.cylinder.kind == "locale":
            l.cylinder = Cylinder(kind="mat")


def test_no_siege_winter_resolves_automatically_to_box9() -> None:
    s = load_scenario("scenario_f_reconquista")
    _clear_all_lords_off_map(s)
    # No Siege markers anywhere -> entering Winter box 7 fully resolves.
    r = _enter_winter_box(s, 7)
    assert s.pending is None
    assert s.calendar.current_box == 9
    assert s.meta.phase == "levy"


def _setup_besieger(s, loc="calatayud"):
    _clear_all_lords_off_map(s)
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id=loc)
    al.in_stronghold = False
    al.forces = {"knights": 1}
    al.assets = {}
    s.locales[loc].siege_yellow = 1   # Christian besieging
    return al, loc


def test_besieger_pending_then_pay_then_box8_then_box9() -> None:
    s = load_scenario("scenario_f_reconquista")
    al, loc = _setup_besieger(s)
    r = _enter_winter_box(s, 7)
    # Besieger action pending, waiting on Christian (Alfonso).
    assert s.pending is not None
    assert s.pending.kind == "winter_siege"
    assert s.pending.payload["step"] == "besieger_actions"
    assert s.pending.payload["queue"] == ["alfonso"]
    assert s.pending.waiting_on == "christian"
    # Alfonso passes his one Winter-Siege action.
    apply_action(s, {"type": "winter_siege_action", "side": "christian",
                     "lord_id": "alfonso", "mode": "pass"})
    # Now Feed has run and we're in the Pay step (Christian first).
    assert s.pending.payload["step"] == "pay"
    assert s.pending.payload["pay_side"] == "christian"
    # Christian done -> Muslim.
    apply_action(s, {"type": "winter_siege_pay", "side": "christian",
                     "done": True})
    assert s.pending.payload["pay_side"] == "muslim"
    # Muslim done -> at-limit Disband, then box 8 (no sieges left there),
    # then box-9 Spring Levy.
    apply_action(s, {"type": "winter_siege_pay", "side": "muslim",
                     "done": True})
    assert s.pending is None
    assert s.calendar.current_box == 9
    assert s.meta.phase == "levy"


def test_besieger_ravage_places_marker() -> None:
    s = load_scenario("scenario_f_reconquista")
    al, loc = _setup_besieger(s)
    _enter_winter_box(s, 7)
    apply_action(s, {"type": "winter_siege_action", "side": "christian",
                     "lord_id": "alfonso", "mode": "ravage"})
    assert s.locales[loc].ravaged == "yellow"   # Christian Ravage placed


def test_at_limit_besieger_disbanded_when_not_paid() -> None:
    s = load_scenario("scenario_f_reconquista")
    al, loc = _setup_besieger(s)
    # Alfonso's Service marker AT the Winter box limit (box 7).
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(ServiceMarker(lord_id="alfonso", box=7))
    _enter_winter_box(s, 7)
    apply_action(s, {"type": "winter_siege_action", "side": "christian",
                     "lord_id": "alfonso", "mode": "pass"})
    apply_action(s, {"type": "winter_siege_pay", "side": "christian",
                     "done": True})
    apply_action(s, {"type": "winter_siege_pay", "side": "muslim",
                     "done": True})
    # At-limit (box 7) -> Disbanded to the Calendar (off the Locale).
    assert s.lords["alfonso"].cylinder.kind != "locale"


def test_winter_siege_in_legal_moves() -> None:
    s = load_scenario("scenario_f_reconquista")
    _setup_besieger(s)
    _enter_winter_box(s, 7)
    from almoravid.legal_moves import legal_moves
    moves = legal_moves(s)
    kinds = {(m["type"], m.get("mode")) for m in moves}
    assert ("winter_siege_action", "pass") in kinds
    assert ("winter_siege_action", "ravage") in kinds


def test_pay_dodges_mandatory_disband() -> None:
    """Load-bearing ordering: Pay (3.2) precedes the mandatory at-limit
    Disband, so paying to advance Service keeps a besieger on the map."""
    s = load_scenario("scenario_f_reconquista")
    al, loc = _setup_besieger(s)
    al.assets = {"coin": 2, "prov": 4}   # Provender so Feed never goes Unfed
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(ServiceMarker(lord_id="alfonso", box=7))
    _enter_winter_box(s, 7)
    # Box 7: pass, pay 1 Coin to shift Service 7->8 (dodges box-7 limit).
    apply_action(s, {"type": "winter_siege_action", "side": "christian",
                     "lord_id": "alfonso", "mode": "pass"})
    apply_action(s, {"type": "winter_siege_pay", "side": "christian",
                     "payer_lord_id": "alfonso", "resource": "coin",
                     "amount": 1, "target_lord_id": "alfonso"})
    apply_action(s, {"type": "winter_siege_pay", "side": "christian",
                     "done": True})
    apply_action(s, {"type": "winter_siege_pay", "side": "muslim",
                     "done": True})
    # Now in box 8 (still besieging); pay again 8->9 to dodge box-8 limit.
    assert s.calendar.current_box == 8
    assert s.lords["alfonso"].cylinder.kind == "locale"
    apply_action(s, {"type": "winter_siege_action", "side": "christian",
                     "lord_id": "alfonso", "mode": "pass"})
    apply_action(s, {"type": "winter_siege_pay", "side": "christian",
                     "payer_lord_id": "alfonso", "resource": "coin",
                     "amount": 1, "target_lord_id": "alfonso"})
    apply_action(s, {"type": "winter_siege_pay", "side": "christian",
                     "done": True})
    apply_action(s, {"type": "winter_siege_pay", "side": "muslim",
                     "done": True})
    # Survived both Winter boxes -> still on the map at box 9.
    assert s.calendar.current_box == 9
    assert s.lords["alfonso"].cylinder.kind == "locale"


def test_end_campaign_into_box7_enters_winter_siege() -> None:
    """End Campaign advancing into box 7 (Scenario F) runs Winter Disband
    and then enters the interactive Winter Siege (does NOT return to the
    ordinary Levy)."""
    s = load_scenario("scenario_f_reconquista")
    # Leave a Christian besieger so Winter Disband keeps him and Winter
    # Siege pauses for his action.
    for l in s.lords.values():
        if l.cylinder.kind == "locale" and l.id != "alfonso":
            l.cylinder = Cylinder(kind="mat")
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id="calatayud")
    al.in_stronghold = False
    al.forces = {"knights": 1}
    al.assets = {"prov": 2}
    s.locales["calatayud"].siege_yellow = 1
    s.meta.phase = "campaign"
    s.meta.campaign_step = "end_campaign"
    s.calendar.current_box = 6
    s.decks.plan = {"christian": [], "muslim": []}
    apply_action(s, {"type": "end_campaign"})
    assert s.calendar.current_box == 7
    assert s.meta.phase == "winter"
    assert s.pending is not None and s.pending.kind == "winter_siege"
    assert "alfonso" in s.pending.payload["queue"]
