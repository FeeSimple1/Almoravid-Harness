"""Phase 6k: last 7 Hold-card triggers wired.

Covers C13/M23 Berenguer Ramon (Count-of-Barcelona), C14 Pope Gregory,
C15 Cluniacs, C21 Mozarabes, M19 African Fleet, C25 De Vivar Reconcile.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder

# ---------------------------------------------------------------------------
# C13 / M23 Berenguer Ramon — Count of Barcelona faction toggle
# ---------------------------------------------------------------------------


def test_c13_grants_units_when_count_with_christians() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.count_of_barcelona_side = "christian"
    # Pick a Lord that exists in this scenario.
    target_candidates = [lid for lid in ("sancho", "eudes",
                                          "al_mustain", "al_mundir")
                         if lid in s.lords]
    assert target_candidates, "no Berenguer-eligible Lord in this scenario"
    target = target_candidates[0]
    s.lords[target].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords[target].in_stronghold = False
    s.lords[target].assets = {"coin": 3}
    knights_before = s.lords[target].forces.get("knights", 0)
    maa_before = s.lords[target].forces.get("men_at_arms", 0)
    r = resolve_event(s, "christian", "C13",
                      payload={"target_lord_id": target})
    assert r.get("discarded_no_effect") is not True
    assert r["knights_added"] == 2
    assert r["men_at_arms_added"] == 2
    assert s.lords[target].forces.get("knights", 0) == knights_before + 2
    assert s.lords[target].forces.get("men_at_arms", 0) == maa_before + 2
    assert s.lords[target].assets.get("coin", 0) == 2  # paid 1


def test_c13_discards_no_effect_when_count_with_muslims() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.count_of_barcelona_side = "muslim"
    r = resolve_event(s, "christian", "C13")
    assert r["discarded_no_effect"] is True
    assert "C13" in s.decks.discard


def test_m23_mirrors_c13_when_count_with_christians() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.count_of_barcelona_side = "christian"
    r = resolve_event(s, "muslim", "M23")
    assert r["discarded_no_effect"] is True


# ---------------------------------------------------------------------------
# C14 Pope Gregory — Muster Sancho/Eudes, shift Service, Lordship+2
# ---------------------------------------------------------------------------


def test_c14_pope_gregory_service_shift_right() -> None:
    s = load_scenario("scenario_e_alfonso", seed=1)
    assert "sancho" in s.lords
    s.decks.this_levy_events["christian"] = ["C14"]
    sm = next((m for m in s.calendar.service_markers
               if m.lord_id == "sancho"), None)
    assert sm is not None, "sancho should be on Calendar"
    box_before = sm.box
    r = apply_action(s, {"type": "play_pope_gregory",
                         "side": "christian",
                         "lord_id": "sancho",
                         "mode": "service_shift_right"})
    assert r["new_service_box"] == min(16, box_before + 2)
    assert "C14" in s.decks.discard


def test_c14_pope_gregory_muster_from_calendar() -> None:
    s = load_scenario("scenario_e_alfonso", seed=1)
    assert "sancho" in s.lords
    s.decks.this_levy_events["christian"] = ["C14"]
    s.lords["sancho"].cylinder = Cylinder(kind="calendar")
    r = apply_action(s, {"type": "play_pope_gregory",
                         "side": "christian",
                         "lord_id": "sancho",
                         "mode": "muster_from_calendar"})
    assert "mustered_at" in r
    assert s.lords["sancho"].cylinder.kind == "locale"
    assert "C14" in s.decks.discard


def test_c14_rejects_when_not_held() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "play_pope_gregory",
                         "side": "christian",
                         "lord_id": "sancho",
                         "mode": "service_shift_right"})
    assert ei.value.code == "card_not_held"


# ---------------------------------------------------------------------------
# C15 Cluniacs — any Christian Lord
# ---------------------------------------------------------------------------


def test_c15_cluniacs_service_shift_right_on_alfonso() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.this_levy_events["christian"] = ["C15"]
    sm = next((m for m in s.calendar.service_markers
               if m.lord_id == "alfonso"), None)
    assert sm is not None, "alfonso should be on Calendar"
    box_before = sm.box
    r = apply_action(s, {"type": "play_cluniacs",
                         "side": "christian",
                         "lord_id": "alfonso",
                         "mode": "service_shift_right"})
    assert r["new_service_box"] == min(16, box_before + 1)


def test_c15_cluniacs_rejects_muslim_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.this_levy_events["christian"] = ["C15"]
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "play_cluniacs",
                         "side": "christian",
                         "lord_id": "al_mutamid",
                         "mode": "service_shift_right"})
    assert ei.value.code == "wrong_side"


# ---------------------------------------------------------------------------
# C21 Mozarabes — auto-success Surrender on Reconquista Taifa
# ---------------------------------------------------------------------------


def test_c21_mozarabes_auto_succeeds_surrender() -> None:
    """When Christian holds C21 + the besieged Stronghold is in a
    Reconquista Taifa, the Surrender roll auto-succeeds (card text:
    "Play for a Surrender roll in a Reconquista Taifa to succeed
    automatically").

    A Christian only makes a Surrender roll at an ENEMY Stronghold, so
    the besieged Locale must be Enemy-to-Christian even though its Taifa
    is Reconquista (Christian Territory). The coherent case is a Muslim
    re-conquered (Jihad-marked) Stronghold inside the Taifa: the Jihad
    marker makes the Locale Muslim-Friendly per 1.3.1, overriding the
    Reconquista territory, so it is besiegeable. (The earlier version of
    this test besieged a *city* and silently skipped because a city in a
    Reconquista Taifa is Christian-Friendly and cannot be Sieged.)
    """
    from almoravid.actions import apply_action
    from almoravid.effective import is_friendly_locale
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    target_loc = "cordoba"
    assert target_loc in s.locales
    taifa = s.taifas.get(s.locales[target_loc].territory)
    assert taifa is not None
    taifa.status = "reconquista"
    # Jihad marker -> Enemy-to-Christian Stronghold inside the Reconquista
    # Taifa, so the Christian may Siege it and make a Surrender roll.
    s.locales[target_loc].jihad_markers = 1
    assert not is_friendly_locale(s, target_loc, "christian")
    # Set up Alfonso as besieger, alone (bare Garrison defends).
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=target_loc)
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    for lid, l in s.lords.items():
        if (l.side == "muslim" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == target_loc):
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.locales[target_loc].siege_yellow = 1
    s.decks.this_levy_events["christian"] = ["C21"]
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    from almoravid.capabilities import effective_command
    s.meta.actions_remaining = effective_command(s, "alfonso")  # fresh card; was 1
    r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    assert r["surrender"] is not None, "expected a Surrender roll"
    assert r["surrender"]["succeeded"] is True
    assert r["surrender"]["threshold"] == "auto_mozarabes"
    assert r["surrender"]["dice"] == []          # no dice rolled — auto
    # Auto-success Conquers the Stronghold (Jihad removed, Conquered placed).
    assert r["surrender"]["conquest"] is not None
    assert "C21" in s.decks.discard              # Hold event consumed


# ---------------------------------------------------------------------------
# M19 African Fleet — Port-to-Port March
# ---------------------------------------------------------------------------


def test_m19_african_fleet_moves_lord_between_ports() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    # Find two Muslim-side Ports.
    ports = [lid for lid, loc in s.locales.items() if loc.has_port]
    assert len(ports) >= 2, "not enough Ports in scenario map"
    from_port = ports[0]
    to_port = ports[1]
    # Drive state to a Muslim activation with al_mutamid at from_port.
    from tests.test_phase6h_tier_a import _setup_active_lord
    s2 = _setup_active_lord("scenario_a_toledo_beset", "al_mutamid",
                             from_port)
    # Clear Christians from to_port.
    for lid, l in s2.lords.items():
        if (l.side == "christian" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == to_port):
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    s2.decks.this_levy_events["muslim"] = ["M19"]
    r = apply_action(s2, {"type": "cmd_march_port_to_port",
                          "side": "muslim",
                          "target_locale_id": to_port})
    assert r["to"] == to_port
    assert s2.lords["al_mutamid"].cylinder.locale_id == to_port
    assert "M19" in s2.decks.discard
    assert s2.meta.actions_remaining == 0  # entire card consumed


def test_m19_rejects_non_port_destination() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    ports = [lid for lid, loc in s.locales.items() if loc.has_port]
    assert ports, "no Ports in scenario"
    from tests.test_phase6h_tier_a import _setup_active_lord
    s2 = _setup_active_lord("scenario_a_toledo_beset", "al_mutamid",
                             ports[0])
    s2.decks.this_levy_events["muslim"] = ["M19"]
    # Pick a non-port destination.
    non_port = next(lid for lid, loc in s2.locales.items()
                    if not loc.has_port)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s2, {"type": "cmd_march_port_to_port",
                          "side": "muslim",
                          "target_locale_id": non_port})
    assert ei.value.code == "not_port"


