"""Ravage-marker bookkeeping at Conquest (1.3.1 / 4.5) and Grow (4.9.2).

Conquest flips a Ravage marker to the NON-conquering (Enemy) side's color:
  - the conqueror's own-color marker flips to Enemy (½VP moves to Enemy);
  - a marker already in the Enemy's color is left unchanged.
Grow reduces Enemy Ravage markers each second-Spring and adjusts VP.
"""
from almoravid.scenarios import load_scenario
from almoravid.campaign import _conquer_stronghold, _apply_grow_harvest_repairs


def _setup():
    return load_scenario("scenario_a_toledo_beset", seed=1)


def test_christian_conquest_flips_own_yellow_to_green() -> None:
    s = _setup()
    loc_id = next(lid for lid, l in s.locales.items() if l.base_type != "region")
    loc = s.locales[loc_id]
    # Force a Muslim-territory stronghold so Christian conquest places
    # Conquered (not the inverse) and our own-color marker is yellow.
    loc.ravaged = "yellow"
    c0, m0 = s.score.christian, s.score.muslim
    r = _conquer_stronghold(s, loc_id, "christian")
    assert loc.ravaged == "green"
    assert r["ravaged_flip"] == ("yellow", "green")
    # ½VP moved from Christian to Muslim (net of the Conquered VP gain).
    assert s.score.muslim == m0 + 0.5
    assert s.score.christian == c0 + r["vp_delta"] - 0.5


def test_conquest_leaves_enemy_color_marker_unchanged() -> None:
    s = _setup()
    loc_id = next(lid for lid, l in s.locales.items() if l.base_type != "region")
    loc = s.locales[loc_id]
    # Christian conquers but the marker is already Enemy (green) color.
    loc.ravaged = "green"
    c0, m0 = s.score.christian, s.score.muslim
    r = _conquer_stronghold(s, loc_id, "christian")
    assert loc.ravaged == "green"          # unchanged
    assert r["ravaged_flip"] is None
    assert s.score.muslim == m0            # no ½VP movement
    assert s.score.christian == c0 + r["vp_delta"]


def test_no_marker_no_flip() -> None:
    s = _setup()
    loc_id = next(lid for lid, l in s.locales.items() if l.base_type != "region")
    loc = s.locales[loc_id]
    loc.ravaged = "none"
    r = _conquer_stronghold(s, loc_id, "christian")
    assert r["ravaged_flip"] is None


def test_grow_reduces_enemy_markers_and_adjusts_vp() -> None:
    s = _setup()
    # Find a second-Spring box (end of 2nd 40 Days of Spring).
    boxes = s.calendar.boxes
    spring_second = None
    for i in range(1, len(boxes)):
        if boxes[i].season == "spring" and boxes[i - 1].season == "spring":
            spring_second = i + 1   # 1-indexed prev_box
            break
    assert spring_second is not None
    # Place 3 green (Muslim) Ravage markers; Christian (then Muslim) Grow
    # reduces ENEMY markers to ceil(3/2)=2 -> removes 1 green.
    region_ids = [lid for lid, l in s.locales.items()][:3]
    for lid in region_ids:
        s.locales[lid].ravaged = "green"
    m0 = s.score.muslim
    out = _apply_grow_harvest_repairs(s, prev_box=spring_second)
    remaining = sum(1 for l in s.locales.values() if l.ravaged == "green")
    assert remaining == 2                       # ceil(3/2)
    assert len(out["grow"]["christian_removed_green"]) == 1
    assert s.score.muslim == m0 - 0.5           # 4.9.2 adjust VP
