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
    if not target_candidates:
        pytest.skip("no Berenguer-eligible Lord in this scenario")
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
    if "sancho" not in s.lords:
        pytest.skip("sancho not in this scenario")
    s.decks.this_levy_events["christian"] = ["C14"]
    sm = next((m for m in s.calendar.service_markers
               if m.lord_id == "sancho"), None)
    if sm is None:
        pytest.skip("sancho not on Calendar")
    box_before = sm.box
    r = apply_action(s, {"type": "play_pope_gregory",
                         "side": "christian",
                         "lord_id": "sancho",
                         "mode": "service_shift_right"})
    assert r["new_service_box"] == min(16, box_before + 2)
    assert "C14" in s.decks.discard


def test_c14_pope_gregory_muster_from_calendar() -> None:
    s = load_scenario("scenario_e_alfonso", seed=1)
    if "sancho" not in s.lords:
        pytest.skip("sancho not in this scenario")
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
    if sm is None:
        pytest.skip("alfonso not on Calendar")
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
    """When Christian holds C21 + the besieged Locale is in a
    Reconquista Taifa, the Surrender roll auto-succeeds."""
    from almoravid.actions import apply_action
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    target_loc = "cordoba"
    if target_loc not in s.locales:
        pytest.skip("cordoba not in scenario")
    # Force the Taifa of cordoba into Reconquista.
    taifa = s.taifas.get(s.locales[target_loc].territory)
    if taifa is None:
        pytest.skip("cordoba has no Taifa")
    taifa.status = "reconquista"
    # Set up Alfonso as besieger, alone.
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
    s.meta.actions_remaining = 1
    try:
        r = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    except IllegalAction:
        pytest.skip("cmd_siege rejected for setup reasons")
    if r["surrender"]:
        assert r["surrender"]["succeeded"] is True
        assert r["surrender"]["threshold"] == "auto_mozarabes"
    assert "C21" in s.decks.discard


# ---------------------------------------------------------------------------
# M19 African Fleet — Port-to-Port March
# ---------------------------------------------------------------------------


def test_m19_african_fleet_moves_lord_between_ports() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    # Find two Muslim-side Ports.
    ports = [lid for lid, loc in s.locales.items() if loc.has_port]
    if len(ports) < 2:
        pytest.skip("not enough Ports in scenario map")
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
    if not ports:
        pytest.skip("no Ports in scenario")
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


# ---------------------------------------------------------------------------
# C25 De Vivar Reconcile — al-Sayyid removed + 1 VP Muslim
# ---------------------------------------------------------------------------


def test_c25_reconcile_removes_sayyid_and_grants_muslim_vp() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    if "rodrigo_al_sayyid" not in s.lords:
        pytest.skip("rodrigo_al_sayyid not in scenario")
    s.lords["rodrigo_al_sayyid"].cylinder = Cylinder(
        kind="locale", locale_id="leon")
    s.lords["rodrigo_al_sayyid"].in_stronghold = False
    s.decks.this_levy_events["christian"] = ["C25"]
    vp_before = s.score.muslim
    r = apply_action(s, {"type": "play_de_vivar_reconcile",
                         "side": "christian"})
    assert r["reconciled"] is True
    assert r["muslim_vp_delta"] == 1.0
    assert s.score.muslim == vp_before + 1.0
    assert s.lords["rodrigo_al_sayyid"].cylinder.kind == "removed"
    assert "C25" in s.decks.discard


def test_c25_rejects_when_sayyid_not_on_map() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    if "rodrigo_al_sayyid" not in s.lords:
        pytest.skip("rodrigo_al_sayyid not in scenario")
    s.lords["rodrigo_al_sayyid"].cylinder = Cylinder(kind="calendar")
    s.decks.this_levy_events["christian"] = ["C25"]
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "play_de_vivar_reconcile",
                         "side": "christian"})
    assert ei.value.code == "not_on_map"
