"""Phase 5g Real Levy mechanics tests."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import ServiceMarker
from tests._plan_helpers import step_levy


def _drive_to_levy_step(s, step: str) -> None:
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            return
        if s.meta.levy_step == step:
            return
        step_levy(s)


# ---- 3.2 Pay -------------------------------------------------------

def test_pay_lord_consumes_coin_and_shifts_service() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Al-Mutamid has 3 Coin and a Service marker at box 6 in Scenario A
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="al_mutamid", box=6))
    _drive_to_levy_step(s, "pay")
    # Drive to Muslim's turn
    while s.meta.active_player != "muslim":
        step_levy(s)
    coin_before = s.lords["al_mutamid"].assets["coin"]
    apply_action(s, {"type": "pay_lord", "side": "muslim",
                     "payer_lord_id": "al_mutamid",
                     "target_lord_id": "al_mutamid",
                     "resource": "coin", "amount": 1})
    assert s.lords["al_mutamid"].assets["coin"] == coin_before - 1
    sm = next(s for s in s.calendar.service_markers if s.lord_id == "al_mutamid")
    # 3.2.1: Coin shifts Service RIGHTWARD (ahead, away from Disband).
    assert sm.box == 7


def test_pay_lord_rejects_no_coin() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.lords["alfonso"].assets["coin"] = 0
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=4))
    _drive_to_levy_step(s, "pay")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "pay_lord", "side": "christian",
                          "payer_lord_id": "alfonso",
                          "target_lord_id": "alfonso",
                          "resource": "coin", "amount": 1})
    assert ei.value.code == "no_coin"


# ---- 3.3 Disband ---------------------------------------------------

def test_disband_at_limit_goes_to_calendar_and_clears_state() -> None:
    """3.3.2 At Service Limit (marker box == Levy box): Disband to the
    Calendar (service_rating boxes right) and clear all cleanup fields
    (Pattern 8)."""
    from almoravid.state import ServiceMarker
    s = load_scenario("scenario_a_toledo_beset")
    s.lords["alfonso"].moved_fought = True
    s.lords["alfonso"].lordship_used = 2
    s.lords["alfonso"].first_march_used_this_card = True
    _drive_to_levy_step(s, "service_disband")
    # Force Alfonso AT the limit (marker on the current Levy box).
    cur = s.calendar.current_box
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=cur))
    while s.meta.active_player != "christian":
        step_levy(s)
    r = apply_action(s, {"type": "disband_lord", "side": "christian",
                         "lord_id": "alfonso"})
    assert r["permanent"] is False
    assert s.lords["alfonso"].cylinder.kind == "calendar"
    assert s.lords["alfonso"].cylinder.box == cur + s.lords["alfonso"].service_rating
    assert s.lords["alfonso"].forces == {}
    assert s.lords["alfonso"].assets == {}
    assert s.lords["alfonso"].vassals == []
    assert s.lords["alfonso"].in_stronghold is False
    assert s.lords["alfonso"].moved_fought is False
    assert s.lords["alfonso"].lordship_used == 0
    assert s.lords["alfonso"].first_march_used_this_card is False
    assert not any(m.lord_id == "alfonso"
                   for m in s.calendar.service_markers)


def test_disband_beyond_limit_permanently_removes() -> None:
    """3.3.1 Beyond Service Limit (marker box < Levy box): permanent
    removal (cylinder kind='removed')."""
    from almoravid.state import ServiceMarker
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "service_disband")
    cur = s.calendar.current_box
    # Put the Levy marker ahead so Alfonso's marker is to the LEFT.
    s.calendar.current_box = cur + 2
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=cur))
    while s.meta.active_player != "christian":
        step_levy(s)
    r = apply_action(s, {"type": "disband_lord", "side": "christian",
                         "lord_id": "alfonso"})
    assert r["permanent"] is True
    assert s.lords["alfonso"].cylinder.kind == "removed"


def test_disband_rejects_lord_right_of_marker() -> None:
    """A Lord whose Service marker is RIGHT of the Levy marker is not
    subject to Disband (3.3)."""
    from almoravid.state import ServiceMarker
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "service_disband")
    cur = s.calendar.current_box
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=cur + 2))
    while s.meta.active_player != "christian":
        step_levy(s)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "disband_lord", "side": "christian",
                         "lord_id": "alfonso"})
    assert ei.value.code == "not_at_limit"


# ---- 3.4 Lordship spending ---------------------------------------

def test_levy_take_vassal_adds_forces_and_spends_lordship() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "muster")
    alf = s.lords["alfonso"]
    assert alf.lordship_used == 0
    knights_before = alf.forces.get("knights", 0)
    # Vassal index 0 is Froila Bermudez (1K + 1S + 1MA)
    r = apply_action(s, {"type": "levy_take_vassal", "side": "christian",
                         "lord_id": "alfonso", "vassal_index": 0})
    assert alf.lordship_used == 1
    assert alf.forces["knights"] == knights_before + 1
    assert alf.vassals[0].ready is False


def test_levy_take_vassal_rejects_when_lordship_exhausted() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "muster")
    s.lords["alfonso"].lordship_used = s.lords["alfonso"].lordship_rating
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "levy_take_vassal", "side": "christian",
                         "lord_id": "alfonso", "vassal_index": 0})
    assert ei.value.code == "lordship_exhausted"


def test_levy_take_capability_from_board_edge() -> None:
    """3.4.4: Levy a this_lord-scope Capability from the side's UNUSED
    Arts of War deck onto a Lord's mat.

    M8 (Dawud ibn Aisha, "Lords: Yusuf or Sir") is a this_lord-scope
    Muslim Capability. It starts UNUSED in Scenario D (not in play /
    held / pending), so it is selectable for a 3.4.4 Levy and tucks
    under Yusuf's mat. (Under the corrected model a board-edge card is
    already deployed and is NOT re-selectable.)
    """
    s = load_scenario("scenario_d_arrival")
    cards = load_cards_local()["cards"]
    target_card = "M8"
    assert not cards[target_card]["no_capability"]
    assert cards[target_card]["capability_scope"] == "this_lord"
    from almoravid.actions import _unused_capability_cards
    assert target_card in _unused_capability_cards(s, "muslim")
    _drive_to_levy_step(s, "muster")
    while s.meta.active_player != "muslim":
        step_levy(s)
    # Yusuf is mustered at Algeciras in Scenario D; ensure he can spend
    # Lordship (reset the per-card counter for a clean assertion).
    assert s.lords["yusuf"].cylinder.kind == "locale"
    s.lords["yusuf"].lordship_used = 0
    r = apply_action(s, {"type": "levy_take_capability", "side": "muslim",
                         "lord_id": "yusuf", "card_id": target_card})
    assert r["scope"] == "this_lord"
    assert target_card in s.lords["yusuf"].capabilities
    # Now deployed -> no longer in the unused pool.
    assert target_card not in _unused_capability_cards(s, "muslim")


def load_cards_local():
    from almoravid.static_data import load_cards
    return load_cards()


# ---- legal_moves -------------------------------------------------

def test_legal_moves_offers_pay_when_coin_and_service() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=4))
    _drive_to_levy_step(s, "pay")
    moves = legal_moves(s)
    assert any(m["type"] == "pay_lord"
               and m.get("target_lord_id") == "alfonso"
               and m.get("resource") == "coin"
               for m in moves)


def test_legal_moves_offers_disband_only_for_at_or_beyond_limit() -> None:
    """3.3: only Lords at/beyond the Service limit are offered Disband.
    At scenario start every mustered Lord's marker is ahead, so none
    are offered; forcing one to the limit makes it appear."""
    from almoravid.state import ServiceMarker
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "service_disband")
    while s.meta.active_player != "christian":
        step_levy(s)
    assert not [m for m in legal_moves(s) if m["type"] == "disband_lord"]
    cur = s.calendar.current_box
    s.calendar.service_markers = [m for m in s.calendar.service_markers
                                  if m.lord_id != "alfonso"]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="alfonso", box=cur))
    dm = [m for m in legal_moves(s) if m["type"] == "disband_lord"]
    assert any(m["lord_id"] == "alfonso" for m in dm)
    # pass_step must NOT be offered while a mandatory Disband is pending.
    assert not [m for m in legal_moves(s)
                if m["type"] == "pass_step" and m["side"] == "christian"]


def test_legal_moves_offers_take_vassal_during_muster() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _drive_to_levy_step(s, "muster")
    moves = legal_moves(s)
    assert any(m["type"] == "levy_take_vassal" for m in moves)
