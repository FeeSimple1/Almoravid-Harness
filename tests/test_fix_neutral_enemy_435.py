"""Neutral-vs-Enemy Locale fixes (rule 1.3.1) + 4.3.5 March stop.

Playtest session 2026-06-11 (Scenario F self-play audit) findings:

  N1. Ravage and Siege were gated on "not Friendly", which wrongly
      admitted NEUTRAL Locales (unmarked Parias-Taifa Strongholds).
      Rule 1.3.1: "Siege (4.3.5) and Ravage (4.7.2) require an Enemy
      Locale as a target. EXAMPLES: Lords do not Bypass and cannot
      Besiege Neutral Strongholds."
  N2. Supply Routes and Retreat were BLOCKED by Neutral Strongholds
      (4.6.1 / 4.4.3 block on ENEMY Strongholds only).
  N3. March did not stop at an unbesieged/unbypassed EMPTY Enemy
      Stronghold (4.3.5; SoP march.stronghold_stop_rule): the
      mandatory Besiege-or-Bypass choice fired only when Enemy Lords
      had Withdrawn inside. Without the stop, an unoccupied Enemy
      Stronghold could never receive its first Siege marker from a
      lone Lord (cmd_siege's Siegeworks needs Lords >= Capacity).
  N4. A Lord who Bypassed THIS card could March away on the same
      card ("continue any actions ... without leaving that Locale").
  N5. A 4.8.2 end-of-card auto-Disband flipping a Taifa to Parias set
      a RECOGNITION OF NEUTRALITY pending, but end_card advanced the
      active player past it (pending/active desync).
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _clear_lords(s):
    for l in s.lords.values():
        if l.cylinder.kind == "locale":
            l.cylinder = Cylinder(kind="mat")


def _keep_both_sides_on_map(s):
    """Park one Lord per side far away so rule 5.2 (zero Mustered Lords
    -> immediate loss) does not end the game mid-test."""
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sevilla")
    s.lords["al_mutamid"].in_stronghold = False
    if not s.lords["al_mutamid"].forces:
        s.lords["al_mutamid"].forces = {"light_horse": 1}
    s.lords["sancho"].cylinder = Cylinder(kind="locale", locale_id="jaca")
    s.lords["sancho"].in_stronghold = False
    if not s.lords["sancho"].forces:
        s.lords["sancho"].forces = {"knights": 1}


def _activate(s, lord_id, locale_id, actions=3):
    side = s.lords[lord_id].side
    lord = s.lords[lord_id]
    lord.cylinder = Cylinder(kind="locale", locale_id=locale_id)
    lord.in_stronghold = False
    if not lord.forces:
        lord.forces = ({"knights": 1} if side == "christian"
                       else {"light_horse": 1})
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = side
    s.meta.active_lord_id = lord_id
    s.meta.actions_remaining = actions
    return lord


# --------------------------------------------------------------------- N1


def test_ravage_rejected_at_neutral_locale() -> None:
    """Granada (Parias Taifa, no markers) is Neutral: no Ravage target."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _activate(s, "alvar_fanez", "granada")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert ei.value.code == "not_enemy_locale"
    assert not [m for m in legal_moves(s) if m["type"] == "cmd_ravage"]


def test_ravage_still_allowed_at_enemy_locale() -> None:
    """Zaragoza Taifa is Independent in Scenario A: Enemy to Christians."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _activate(s, "alvar_fanez", "calatayud")
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert s.locales["calatayud"].ravaged == "yellow"
    assert r["locale"] == "calatayud"


def test_siege_rejected_at_neutral_stronghold() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _activate(s, "alvar_fanez", "granada")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert ei.value.code == "not_enemy_locale"
    assert not [m for m in legal_moves(s) if m["type"] == "cmd_siege"]


def test_siege_friendly_keeps_friendly_locale_code() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _activate(s, "al_mutamid", "sevilla")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_siege", "side": "muslim"})
    assert ei.value.code == "friendly_locale"


# --------------------------------------------------------------------- N2


def test_retreat_not_blocked_by_neutral_stronghold() -> None:
    from almoravid.battle import _retreat_target_clear
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    # Granada: Neutral Stronghold, no Lords -> clear for either side.
    assert _retreat_target_clear(s, "granada", "christian") is True
    assert _retreat_target_clear(s, "granada", "muslim") is True
    # Zaragoza (Independent Taifa City): Enemy to Christians -> blocked.
    assert _retreat_target_clear(s, "zaragoza", "christian") is False
    assert _retreat_target_clear(s, "zaragoza", "muslim") is True


def test_supply_route_not_blocked_by_neutral_stronghold() -> None:
    from almoravid.campaign import _route_blocked_by_enemy
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    # A route THROUGH Neutral Granada does not break (4.6.1 blocks on
    # ENEMY Strongholds only); through Enemy Zaragoza it does.
    assert _route_blocked_by_enemy(s, ["granada"], "christian") is False
    assert _route_blocked_by_enemy(s, ["zaragoza"], "christian") is True
    assert _route_blocked_by_enemy(s, ["zaragoza"], "muslim") is False


# --------------------------------------------------------------------- N3


def test_march_to_empty_enemy_stronghold_forces_besiege_or_bypass() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _keep_both_sides_on_map(s)
    _activate(s, "alvar_fanez", "calatayud")
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "zaragoza", "way_type": "road"})
    assert s.pending is not None
    assert s.pending.kind == "besiege_or_bypass"
    assert s.pending.waiting_on == "christian"
    types = {m["type"] for m in legal_moves(s)}
    assert types == {"respond_besiege", "respond_bypass"}


def test_besiege_empty_enemy_stronghold_places_first_marker() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _keep_both_sides_on_map(s)
    _activate(s, "alvar_fanez", "calatayud")
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "zaragoza", "way_type": "road"})
    apply_action(s, {"type": "respond_besiege", "side": "christian"})
    assert s.locales["zaragoza"].siege_yellow == 1
    assert s.meta.actions_remaining == 0          # card over -> FPD
    assert s.pending is None


def test_march_to_neutral_stronghold_sets_no_pending() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _keep_both_sides_on_map(s)
    _activate(s, "alvar_fanez", "almeria")
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "granada", "way_type": "pass"})
    assert s.pending is None                      # Neutral: never 4.3.5
    assert s.locales["granada"].siege_yellow == 0
    assert s.locales["granada"].bypass_yellow is False


def test_march_joining_own_bypass_sets_no_pending() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _keep_both_sides_on_map(s)
    s.locales["zaragoza"].bypass_yellow = True
    sancho = s.lords["sancho"]
    sancho.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    sancho.in_stronghold = False
    _activate(s, "alvar_fanez", "calatayud")
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "zaragoza", "way_type": "road"})
    assert s.pending is None                      # joins the Bypass


# --------------------------------------------------------------------- N4


def test_bypassing_lord_cannot_march_away_same_card() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _keep_both_sides_on_map(s)
    _activate(s, "alvar_fanez", "calatayud", actions=3)
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "zaragoza", "way_type": "road"})
    apply_action(s, {"type": "respond_bypass", "side": "christian"})
    assert s.lords["alvar_fanez"].bypassed_this_card is True
    assert s.meta.actions_remaining == 2          # card continues
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "calatayud",
                         "way_type": "road"})
    assert ei.value.code == "bypassed_this_card"
    assert not [m for m in legal_moves(s) if m["type"] == "cmd_march"]
    # The flag is per-card: cleared by end_card (4.8.3).
    apply_action(s, {"type": "end_card", "side": "christian"})
    assert s.lords["alvar_fanez"].bypassed_this_card is False


# --------------------------------------------------------------------- N5


def test_end_card_auto_disband_neutrality_pending_owns_turn() -> None:
    """T4 x 4.8.2: auto-Disband of an Independent Taifa Lord at end of
    the OTHER side's card flips his Taifa to Parias; a side Bypassing a
    now-Neutral Stronghold owes RECOGNITION OF NEUTRALITY — and the
    pending must own the turn (waiting_on == active_player)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _clear_lords(s)
    _keep_both_sides_on_map(s)
    # al_mustain (Zaragoza Taifa Lord) on map, at Service limit.
    am = s.lords["al_mustain"]
    am.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    am.in_stronghold = True
    am.forces = {"light_horse": 1}
    for m in s.calendar.service_markers:
        if m.lord_id == "al_mustain":
            m.box = s.calendar.current_box        # at limit
    # Christian Alfonso Bypassing Zaragoza, ending his card.
    al = _activate(s, "alfonso", "zaragoza", actions=0)
    al.moved_fought = False
    s.locales["zaragoza"].bypass_yellow = True
    apply_action(s, {"type": "end_card", "side": "christian"})
    assert s.pending is not None
    assert s.pending.kind == "neutrality_choice"
    assert s.meta.active_player == s.pending.waiting_on  # no desync
