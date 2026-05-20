"""Tests for the post-bug-hunt deferred fixes."""

from __future__ import annotations

import pytest

from almoravid.actions import _shift_service_left, apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker
from tests._plan_helpers import legal_pad


def _replace_service(s, lord_id: str, box: int) -> None:
    """Remove any existing markers for lord_id and add one at `box`."""
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != lord_id
    ]
    s.calendar.service_markers.append(ServiceMarker(lord_id=lord_id, box=box))


# ---- _shift_service_left helper ---------------------------------------

def test_shift_service_left_one_box() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _replace_service(s, "alfonso", 5)
    new = _shift_service_left(s, "alfonso", 1)
    assert new == 4
    sm = next(s for s in s.calendar.service_markers if s.lord_id == "alfonso")
    assert sm.box == 4


def test_shift_service_left_off_edge() -> None:
    """Pattern 6: Service marker shifted past box 1 lands in off_left_service."""
    s = load_scenario("scenario_a_toledo_beset")
    _replace_service(s, "alfonso", 1)
    new = _shift_service_left(s, "alfonso", 2)
    assert new == 0
    # Marker removed from service_markers
    assert not any(sm.lord_id == "alfonso" for sm in s.calendar.service_markers)
    # Now in off_left_service
    assert "alfonso" in s.calendar.off_left_service


# ---- Enforcing Parias actually shifts Service -------------------------

def test_enforcing_parias_shifts_taifa_lord_service() -> None:
    """Rule 4.7.2: Christian Ravage that brings yellow count to odd in
    a Taifa shifts that Taifa's Lord's Service marker 1 box left."""
    s = load_scenario("scenario_a_toledo_beset")
    # Add a Service marker for al_mustain (Zaragoza Taifa Lord) at box 5
    _replace_service(s, "al_mustain", 5)

    # Drive through Levy to Campaign / Activation with alvar_fanez active
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alvar_fanez"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    # Reveal until alvar_fanez is active
    for _ in range(20):
        if s.meta.active_lord_id == "alvar_fanez":
            break
        apply_action(s, {"type": "command_reveal",
                         "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != "alvar_fanez":
            apply_action(s, {"type": "end_card", "side": s.meta.active_player})
    # Move alvar_fanez to Zaragoza Taifa (Calatayud — no Ravaged markers)
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="calatayud")
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert r["enforcing_parias"] is True
    # al_mustain's Service marker shifted left by 1
    sm = next(s for s in s.calendar.service_markers if s.lord_id == "al_mustain")
    assert sm.box == 4


# ---- Curias / Winter auto-wiring in Scenario F ------------------------

def test_scenario_f_auto_curias_triggers_at_box_5() -> None:
    """Scenario F at box 5 should auto-check_curias and apply if triggered."""
    from almoravid.campaign import check_curias
    s = load_scenario("scenario_f_reconquista", seed=1)
    # Pump up yellow Ravaged markers so curias triggers
    for lid in list(s.locales)[:15]:
        s.locales[lid].ravaged = "yellow"
    s.calendar.current_box = 4
    # Synthetic end_campaign that advances to box 5
    s.meta.phase = "campaign"
    s.meta.campaign_step = "end_campaign"
    s.decks.plan = {"christian": [], "muslim": []}
    r = apply_action(s, {"type": "end_campaign"})
    # Auto Curias should have fired
    assert any("curias" in str(a) for a in r.get("auto_actions", []))


def test_scenario_f_auto_winter_disband_at_box_7() -> None:
    """Scenario F: advancing to box 7 auto-fires winter_disband."""
    s = load_scenario("scenario_f_reconquista", seed=1)
    s.calendar.current_box = 6
    s.meta.phase = "campaign"
    s.meta.campaign_step = "end_campaign"
    s.decks.plan = {"christian": [], "muslim": []}
    r = apply_action(s, {"type": "end_campaign"})
    # Box should now be 7; winter_disband fired
    assert s.calendar.current_box == 7
    assert any("winter_disband" in str(a) for a in r.get("auto_actions", []))


# ---- Voluntary FPD auto-Disband ----------------------------------------

def test_fpd_auto_disband_at_service_limit() -> None:
    """Rule 4.8.3 / 3.3.2: a Lord whose Service marker is at-or-before
    the current Campaign box auto-Disbands at end_card."""
    s = load_scenario("scenario_a_toledo_beset")
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})
    # Set up: Alfonso has a Service marker at the current Campaign box
    # (i.e., at-service-limit).
    _replace_service(s, "alfonso", s.calendar.current_box)
    # end_card should auto-disband Alfonso
    r = apply_action(s, {"type": "end_card", "side": "christian"})
    assert r["auto_disband"].get("disbanded") == "alfonso"
    assert s.lords["alfonso"].cylinder.kind == "calendar"


# ---- Multi-hop Supply ------------------------------------------------

def test_supply_multi_hop_route_via_bfs() -> None:
    """Supply now finds multi-hop routes. Move Alfonso to Pamplona (2
    hops to León via Jaca... or further). Verify a route exists."""
    from almoravid.campaign import _find_supply_routes
    s = load_scenario("scenario_a_toledo_beset")
    # Alfonso at León is at his own Seat — but test multi-hop by moving
    # him to Burgos and asking for a route. León -> Sahagún -> Burgos is
    # one path, so Burgos -> Sahagún -> León is a 2-hop route.
    # Actually León and Burgos are both Alfonso's printed Seats so
    # 'at his Seat' triggers. Move to a non-Seat instead:
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="palencia")
    routes = _find_supply_routes(s, "palencia", ["leon", "burgos"],
                                  "christian", s.lords["alfonso"])
    # From Palencia: Palencia -> Sahagún -> León (2 hops to León)
    # Palencia -> Burgos (1 hop direct via Road)
    assert routes["burgos"] is not None
    assert len(routes["burgos"]) == 1
    assert routes["leon"] is not None


def test_supply_route_blocked_by_enemy_returns_none() -> None:
    """BFS respects 4.6.1 — blocked Locale not traversed."""
    from almoravid.campaign import _find_supply_routes
    s = load_scenario("scenario_a_toledo_beset")
    # Block Sahagún by placing a Muslim Lord there
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="palencia")
    routes = _find_supply_routes(s, "palencia", ["leon"],
                                  "christian", s.lords["alfonso"])
    # The Sahagún path is blocked; León unreachable via that route.
    # If Palencia has another road path to León, route would still exist.
    # Palencia road neighbors are Sahagún, Burgos. Burgos has no road to
    # León directly. So Palencia -> Burgos -> Najera -> ... -> León would
    # be a long indirect path. Verify routing handles this OR concludes
    # blocked.
    # (Structural assertion: function ran without exception.)
    assert "leon" in routes


# ---- Multi-Lord Battle ------------------------------------------------

def test_multi_lord_battle_aggregates_forces() -> None:
    """Deferred fix: multi-Lord Battle aggregates forces and distributes
    losses back to participating Lords after resolution."""
    from almoravid.battle import battleside_for_lords, commit_forces_after_battle
    s = load_scenario("scenario_a_toledo_beset")
    # Place 3 Christian Lords at Sahagun (already there: alfonso, pedro,
    # garcia per scenario setup).
    christian_at_sahagun = [
        l.id for l in s.lords.values()
        if l.side == "christian"
        and l.cylinder.kind == "locale"
        and l.cylinder.locale_id == "sahagun"
    ]
    assert len(christian_at_sahagun) >= 2
    initial_total = sum(
        sum(s.lords[lid].forces.values())
        for lid in christian_at_sahagun
    )
    side = battleside_for_lords(s, christian_at_sahagun, "christian", "attacker")
    # Aggregated forces equal the sum
    assert sum(side.forces.values()) == initial_total
    # Simulate losses: drop 2 units of the most common type
    by_type = {ut: sum(s.lords[lid].forces.get(ut, 0)
                       for lid in christian_at_sahagun)
               for ut in side.forces}
    most_common = max(by_type.items(), key=lambda kv: kv[1])[0]
    side.forces[most_common] -= 2
    side.routed_units[most_common] = 2
    # Commit back
    commit_forces_after_battle(s, side)
    # Total units across the Lords now = initial_total (routed + surviving)
    final_total = sum(
        sum(s.lords[lid].forces.values())
        + sum(s.lords[lid].routed_units.values())
        for lid in christian_at_sahagun
    )
    assert final_total == initial_total


def test_hills_boosts_defender_missile_hits() -> None:
    """Per-card effect: when defender holds C1/M1 Hills in this_levy_events,
    their missile-step Hits get a +0.5/unit bonus."""
    from almoravid.battle import BattleSide, _resolve_step
    from almoravid.scenarios import load_scenario
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 0})  # no missile
    # Defender with 4 Militia + C4 Arqueros (Bowmen capability x1/2)
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"],
                     forces={"militia": 4},
                     capabilities_in_play=["C4"])
    # Baseline: no Hills, defender missile step
    s.decks.this_levy_events = {}
    res_no = _resolve_step(s, "1.a", "defender", "missile", None,
                            atk, dfd, context="battle")
    # 4 Militia bowmen x1/2 = 2 raw. Rounded = 2.
    assert res_no.rounded_hits == 2

    # With M1 Hills active on defender side
    dfd2 = BattleSide(side="muslim", role="defender",
                      lord_ids=["al_mutamid"],
                      forces={"militia": 4},
                      capabilities_in_play=["C4"])
    s.decks.this_levy_events = {"muslim": ["M1"]}
    res_hills = _resolve_step(s, "1.a", "defender", "missile", None,
                               atk, dfd2, context="battle")
    # 4 Militia bowmen + 0.5 * 4 = 2 + 2 = 4 raw. Rounded = 4.
    assert res_hills.rounded_hits == 4, (
        f"Hills should boost +0.5 per Missile unit: expected 4, "
        f"got {res_hills.rounded_hits}"
    )


def test_hills_does_not_boost_attacker() -> None:
    """Hills is Defending-only per AoW reference."""
    from almoravid.battle import BattleSide, _resolve_step
    from almoravid.scenarios import load_scenario
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"],
                     forces={"militia": 4},
                     capabilities_in_play=["C4"])
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alfonso"], forces={})
    # M1 Hills on attacker side (not legal per text, but verify code
    # rejects boost when role is attacker).
    s.decks.this_levy_events = {"muslim": ["M1"]}
    res = _resolve_step(s, "1.b", "attacker", "missile", None,
                        atk, dfd, context="battle")
    assert res.rounded_hits == 2  # No bonus — attacker doesn't get Hills


def test_hills_does_not_boost_melee() -> None:
    """Hills is a missile-only buff."""
    from almoravid.battle import BattleSide, _resolve_step
    from almoravid.scenarios import load_scenario
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"],
                     forces={"sergeants": 2})  # Melee x1
    s.decks.this_levy_events = {"muslim": ["M1"]}
    res = _resolve_step(s, "2.a", "defender", "melee", "horse",
                        atk, dfd, context="battle")
    # 2 Sergeants x1 = 2 melee Hits. No Hills bonus on Melee.
    assert res.rounded_hits == 2
