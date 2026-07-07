"""Q-007 — 6.3.1 Winter Disband vs Taifa politics.

Beyond-Service Winter removals are unmodified 3.3.1 permanent removals
-> an Independent Taifa Lord's removal flips his Taifa to Parias (with
Parias Coin + 1 VP). The Disband-TO-MAT batch keeps statuses frozen
(explicit 6.3.1 bullet; Spring Muster re-derives them)."""
from __future__ import annotations

from almoravid.campaign import winter_disband
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker


def _stage(s):
    # Isolate: park everyone off-map, then place just the actors.
    for lord in s.lords.values():
        lord.cylinder = Cylinder(kind="calendar", box=16)
    s.calendar.service_markers = []


def test_winter_beyond_service_taifa_lord_flips_to_parias() -> None:
    s = load_scenario("scenario_f_reconquista", seed=1)
    _stage(s)
    s.calendar.current_box = 7
    abd = s.lords["abd_allah"]
    abd.cylinder = Cylinder(kind="locale", locale_id="granada")
    s.taifas["granada"].status = "independent"
    # Beyond Service: marker LEFT of the current box.
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="abd_allah", box=6))
    # An Unbesieged Christian on the map to receive the Parias Coin —
    # at a Siege Locale so Winter Disband keeps him (6.3.2) and the
    # Coin survives the mat-clearing of the to-mat batch.
    alf = s.lords["alfonso"]
    alf.cylinder = Cylinder(kind="locale", locale_id="toledo")
    alf.assets = {}
    s.locales["toledo"].siege_yellow = 1
    vp0 = s.score.christian

    r = winter_disband(s)

    assert "abd_allah" in r["beyond_service_removed"]
    assert abd.cylinder.kind == "removed"
    assert s.taifas["granada"].status == "parias"
    assert r["removal_politics"]["abd_allah"]["parias_coin"]["amount"] == 4
    assert alf.assets.get("coin", 0) == 4
    assert s.score.christian == vp0 + 1.0


def test_winter_disband_to_mat_keeps_status_frozen() -> None:
    """The at-limit (not beyond) Taifa Lord Disbands TO HIS MAT with no
    status adjustment and no Parias Coin — his Coin goes to the Taifas
    box (6.3.1 bullet)."""
    s = load_scenario("scenario_f_reconquista", seed=1)
    _stage(s)
    s.calendar.current_box = 7
    abd = s.lords["abd_allah"]
    abd.cylinder = Cylinder(kind="locale", locale_id="granada")
    s.taifas["granada"].status = "independent"
    # AT limit (box == current): to-mat batch, not Beyond Service.
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="abd_allah", box=7))
    vp0 = s.score.christian

    r = winter_disband(s)

    assert "abd_allah" in r["disbanded_to_mat"]
    assert abd.cylinder.kind == "mat"
    assert s.taifas["granada"].status == "independent"   # frozen
    assert "abd_allah" not in r.get("removal_politics", {})
    assert s.score.christian == vp0
