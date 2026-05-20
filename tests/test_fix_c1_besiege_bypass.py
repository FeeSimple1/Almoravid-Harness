"""FIX-C / C1 Besiege-or-Bypass after Withdraw (rule 4.3.5)."""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, PendingDecision


def _setup_withdraw_pending(s, seed=1):
    """Christian Lord (alvar_fanez) Approaching Muslim al_mustain at
    zaragoza (a Muslim City, Friendly to Muslims). Pending = the Muslim
    defender's march-arrival response."""
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="zaragoza")
    s.lords["alvar_fanez"].in_stronghold = False
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale",
                                              locale_id="zaragoza")
    s.lords["al_mustain"].in_stronghold = False
    s.meta.active_lord_id = "alvar_fanez"
    s.meta.actions_remaining = 2
    s.locales["zaragoza"].siege_yellow = 0
    s.locales["zaragoza"].bypass_yellow = False
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": "zaragoza", "from_locale_id": "calatayud",
                 "via_way_type": "road", "active_lord_id": "alvar_fanez",
                 "active_side": "christian",
                 "defender_lord_ids": ["al_mustain"]})
    s.meta.active_player = "muslim"


def test_withdraw_triggers_besiege_or_bypass_pending() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup_withdraw_pending(s)
    apply_action(s, {"type": "respond_withdraw", "side": "muslim"})
    assert s.lords["al_mustain"].in_stronghold is True
    assert s.pending is not None
    assert s.pending.kind == "besiege_or_bypass"
    assert s.pending.waiting_on == "christian"
    assert s.meta.active_player == "christian"


def test_besiege_places_marker_and_ends_card() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup_withdraw_pending(s)
    apply_action(s, {"type": "respond_withdraw", "side": "muslim"})
    apply_action(s, {"type": "respond_besiege", "side": "christian"})
    assert s.locales["zaragoza"].siege_yellow == 1   # Christian Siege
    assert s.pending is None
    assert s.meta.actions_remaining == 0             # card ends -> FPD
    # al_mustain inside with a Christian Siege marker is now Besieged.
    from almoravid.effective import is_besieged
    assert is_besieged(s, "al_mustain") is True


def test_bypass_places_marker_and_card_continues() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup_withdraw_pending(s)
    apply_action(s, {"type": "respond_withdraw", "side": "muslim"})
    apply_action(s, {"type": "respond_bypass", "side": "christian"})
    assert s.locales["zaragoza"].bypass_yellow is True
    assert s.pending is None
    assert s.meta.actions_remaining == 2             # card continues
    from almoravid.effective import is_bypassed, is_besieged
    assert is_bypassed(s, "al_mustain") is True
    assert is_besieged(s, "al_mustain") is False


def test_enumerator_offers_only_besiege_and_bypass_when_pending() -> None:
    from almoravid.legal_moves import legal_moves
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup_withdraw_pending(s)
    apply_action(s, {"type": "respond_withdraw", "side": "muslim"})
    types = {m["type"] for m in legal_moves(s)}
    assert types == {"respond_besiege", "respond_bypass"}
