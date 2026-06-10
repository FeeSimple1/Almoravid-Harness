"""C25 De Vivar Hold event (Arts of War ref C25; rule 3.5.1).

Defects fixed:
  - unreachable from the menu (never offered in Call to Arms);
  - no turn/phase gate (the handler accepted the play during setup and even
    on the Muslim turn);
  - wrong procedure: it marked al-Sayyid 'removed' instead of set-aside and
    never placed Rodrigo Campeador on the Calendar.
Card text: play during Christian Call to Arms only, if al-Sayyid is on the
map; Reconcile per 3.5.1 but for exactly 1 VP regardless of his Service.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker
from tests._plan_helpers import step_levy


def _to_cta(s, side="christian"):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "call_to_arms")
    assert s.meta.levy_step == "call_to_arms"
    while s.meta.active_player != side:
        step_levy(s)
    return s


def _sayyid_on_map(s, box_ahead=3):
    sayyid = s.lords["rodrigo_al_sayyid"]
    sayyid.cylinder = Cylinder(kind="locale", locale_id="valencia")
    sayyid.in_stronghold = False
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers
        if m.lord_id != "rodrigo_al_sayyid"]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="rodrigo_al_sayyid",
                      box=s.calendar.current_box + box_ahead))


def test_c25_offered_in_menu_and_reconciles_correctly() -> None:
    s = load_scenario("scenario_d_arrival", seed=3)
    _sayyid_on_map(s, box_ahead=3)
    s.decks.this_levy_events["christian"] = ["C25"]
    _to_cta(s, "christian")
    # Discoverable in the Call-to-Arms menu.
    assert any(m["type"] == "play_de_vivar_reconcile"
               for m in legal_moves(s)), "C25 not advertised in Call to Arms"
    vp0 = s.taifas_box_vp
    r = apply_action(s, {"type": "play_de_vivar_reconcile",
                         "side": "christian"})
    assert r["reconciled"] is True
    assert r["muslim_vp_delta"] == 1.0           # exactly 1 VP (not 1+ahead)
    assert s.taifas_box_vp == vp0 + 1.0
    # al-Sayyid is set ASIDE (not removed) per 3.5.1.
    assert s.lords["rodrigo_al_sayyid"].cylinder.kind == "set_aside"
    # Campeador placed on the Calendar two boxes ahead.
    camp = s.lords["rodrigo_campeador"]
    assert camp.cylinder.kind == "calendar"
    assert camp.cylinder.box == min(16, s.calendar.current_box + 2)
    assert "C25" in s.decks.discard


def test_c25_rejected_outside_call_to_arms() -> None:
    s = load_scenario("scenario_d_arrival", seed=3)
    _sayyid_on_map(s)
    s.decks.this_levy_events["christian"] = ["C25"]
    # Still in setup — no turn/phase gate would let this through before.
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "play_de_vivar_reconcile",
                         "side": "christian"})


def test_c25_rejected_when_sayyid_not_on_map() -> None:
    s = load_scenario("scenario_d_arrival", seed=3)
    s.lords["rodrigo_al_sayyid"].cylinder = Cylinder(kind="calendar", box=5)
    s.decks.this_levy_events["christian"] = ["C25"]
    _to_cta(s, "christian")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "play_de_vivar_reconcile",
                         "side": "christian"})
    assert ei.value.code == "not_on_map"


def test_c25_not_offered_without_card() -> None:
    s = load_scenario("scenario_d_arrival", seed=3)
    _sayyid_on_map(s)
    s.decks.this_levy_events["christian"] = []        # C25 not held
    _to_cta(s, "christian")
    assert not any(m["type"] == "play_de_vivar_reconcile"
                   for m in legal_moves(s))
