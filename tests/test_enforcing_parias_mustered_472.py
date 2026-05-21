"""4.7.2 Enforcing Parias: the Service-shift on an odd Christian Ravage
marker in a Taifa applies only IF the Taifa Lord is Mustered."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.state import Cylinder, ServiceMarker
from tests.test_forage_ravage import _activate_lord


def _svc_box(s, lord_id):
    return next((m.box for m in s.calendar.service_markers
                 if m.lord_id == lord_id and m.vassal_id is None), None)


def test_no_shift_when_taifa_lord_not_mustered() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="calatayud")
    # Zaragoza Taifa Lord = al_mustain; take him OFF the map.
    al = s.lords["al_mustain"]
    assert al.home_taifa == "zaragoza"
    al.cylinder = Cylinder(kind="calendar", box=6)
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "al_mustain"]
    s.calendar.service_markers.append(ServiceMarker(lord_id="al_mustain", box=6))
    before = _svc_box(s, "al_mustain")
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert r["enforcing_parias"] is True
    # Not Mustered -> Service marker unchanged.
    assert _svc_box(s, "al_mustain") == before


def test_shift_when_taifa_lord_mustered() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="calatayud")
    al = s.lords["al_mustain"]
    al.cylinder = Cylinder(kind="locale", locale_id=al.home_taifa
                           if al.home_taifa in s.locales else "zaragoza")
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "al_mustain"]
    s.calendar.service_markers.append(ServiceMarker(lord_id="al_mustain", box=6))
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert r["enforcing_parias"] is True
    assert _svc_box(s, "al_mustain") == 5   # shifted 1 box left
