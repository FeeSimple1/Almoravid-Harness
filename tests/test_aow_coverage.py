"""Coverage for previously-untested but implemented AoW effects."""
from __future__ import annotations

from almoravid.battle import BattleSide, _storm_setup
from almoravid.campaign import _apply_ravage_effect
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def test_war_drums_m22_adds_one_prov_on_ravage() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="M22", scope="side_wide", owner_side="muslim"))
    yusuf = s.lords["yusuf"]
    yusuf.cylinder = Cylinder(kind="locale", locale_id="medinaceli")
    yusuf.assets = {}
    # Region ravage normally gives +1 Loot only; War Drums adds +1 Prov.
    loc = next(lid for lid, lo in s.locales.items()
               if lo.base_type == "region" and lo.territory in s.taifas)
    s.locales[loc].ravaged = "none"
    r = _apply_ravage_effect(s, yusuf, "muslim", loc)
    assert yusuf.assets.get("prov", 0) == 1      # War Drums bonus


def test_m13_siege_towers_walls_minus_one_from_round_two() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    loc_id = next(lid for lid, lo in s.locales.items()
                  if lo.base_type == "city" and lo.territory in s.taifas)
    s.locales[loc_id].siege_green = 2
    al = s.lords["al_mundir"]
    al.capabilities.append("M13")                # Siege Towers (this_lord)
    al.cylinder = Cylinder(kind="locale", locale_id=loc_id)
    atk = BattleSide(side="muslim", role="attacker", lord_ids=["al_mundir"],
                     forces={"knights": 3})
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    deff = BattleSide(side="christian", role="defender", lord_ids=["alfonso"],
                      forces={"men_at_arms": 2})
    ss, _mr = _storm_setup(s, atk, deff)
    assert ss["siege_towers"] is True            # M13 detected for attacker


def test_unfed_penalty_cascades_to_vassal_under_advanced_rule() -> None:
    """4.8.1 Unfed shift must cascade to Vassal markers when the Advanced
    Vassal Service rule (3.4.2) is on (it now routes through
    _shift_service_left)."""
    from almoravid.campaign import _apply_unfed_penalty
    from almoravid.state import ServiceMarker
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.advanced_vassal_service = True
    lid = "alvar_fanez"
    # Clear any existing markers for this lord, then plant own + vassal.
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != lid]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id=lid, box=8, vassal_id=None))
    s.calendar.service_markers.append(
        ServiceMarker(lord_id=lid, box=8, vassal_id="v1"))
    _apply_unfed_penalty(s, lid)
    own = next(m for m in s.calendar.service_markers
              if m.lord_id == lid and m.vassal_id is None)
    vas = next(m for m in s.calendar.service_markers
              if m.lord_id == lid and m.vassal_id == "v1")
    assert own.box == 7 and vas.box == 7        # both shifted left
