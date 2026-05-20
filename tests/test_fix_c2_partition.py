"""FIX-C / C2 Approach partition (rule 4.3.4): the Inactive side may
split its Lords across Avoid / Withdraw / Battle."""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.map import neighbors_via
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, PendingDecision


def _setup(s):
    muslims = ["al_mustain", "abu_bakr", "abd_allah"]
    for lid in muslims:
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
        s.lords[lid].in_stronghold = False
        s.lords[lid].assets = {}
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="zaragoza")
    s.lords["alvar_fanez"].in_stronghold = False
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_lord_id = "alvar_fanez"
    s.meta.actions_remaining = 2
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": "zaragoza", "from_locale_id": "calatayud",
                 "via_way_type": "road", "active_lord_id": "alvar_fanez",
                 "active_side": "christian", "defender_lord_ids": muslims})
    s.meta.active_player = "muslim"
    return muslims


def test_partition_avoid_then_withdraw_then_stand() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    muslims = _setup(s)
    # Pick a road neighbor of zaragoza that isn't the approach origin.
    avoid_to = next(n for n in neighbors_via("zaragoza", "road")
                    if n != "calatayud")
    # 1) al_mustain Avoids.
    r1 = apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                          "target_locale_id": avoid_to, "way_type": "road",
                          "lord_ids": ["al_mustain"]})
    assert s.lords["al_mustain"].cylinder.locale_id == avoid_to
    assert s.pending is not None
    assert s.pending.kind == "march_arrival_response"
    assert set(s.pending.payload["defender_lord_ids"]) == {"abu_bakr",
                                                            "abd_allah"}
    # 2) abu_bakr Withdraws inside zaragoza.
    r2 = apply_action(s, {"type": "respond_withdraw", "side": "muslim",
                          "lord_ids": ["abu_bakr"]})
    assert s.lords["abu_bakr"].in_stronghold is True
    # Still pending: abd_allah owes a response.
    assert s.pending.kind == "march_arrival_response"
    assert s.pending.payload["defender_lord_ids"] == ["abd_allah"]
    # 3) abd_allah Stands — Battle resolves; the pending clears.
    apply_action(s, {"type": "respond_stand_battle", "side": "muslim"})
    assert (s.pending is None
            or s.pending.kind == "besiege_or_bypass")


def test_all_withdraw_triggers_besiege_or_bypass() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    muslims = _setup(s)
    # Whole group Withdraws (default: no lord_ids subset).
    apply_action(s, {"type": "respond_withdraw", "side": "muslim"})
    # All three inside; Approach fully resolved -> Besiege-or-Bypass.
    assert all(s.lords[m].in_stronghold for m in muslims)
    assert s.pending is not None
    assert s.pending.kind == "besiege_or_bypass"
    assert s.pending.waiting_on == "christian"
