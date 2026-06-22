"""A this_lord missile capability must arm ONLY its holder's units, even on
the pooled (multi-Lord vs single-Lord) battle path — not leak to a
co-located same-side Lord's units (4.4.2 / Arts of War this_lord scope)."""
from __future__ import annotations

from almoravid.battle import (BattleSide, build_strike_rows,
                              battleside_for_lords)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _two_lord_attacker(cap_for_A):
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    A, B = "al_mustain", "al_mundir"
    s.lords[A].forces = {"men_at_arms": 2}
    s.lords[A].capabilities = [cap_for_A] if cap_for_A else []
    s.lords[B].forces = {"men_at_arms": 2}
    s.lords[B].capabilities = []
    for lid in (A, B):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    atk = battleside_for_lords(s, [A, B], "muslim", "attacker", active_lord_id=A)
    return s, atk


def test_crossbow_cap_does_not_leak_to_co_located_lord() -> None:
    s, atk = _two_lord_attacker("M2")          # only al_mustain has Aqqara
    rows = build_strike_rows(s, atk, context="battle")
    xbow = sum(r.count for r in rows if r.kind == "crossbows")
    assert xbow == 2                            # only the holder's 2 MaA
    # Base melee is still pooled across both Lords (4 MaA).
    melee = sum(r.count for r in rows
                if r.kind == "melee" and r.unit_type == "men_at_arms")
    assert melee == 4


def test_no_cap_no_crossbow_rows() -> None:
    s, atk = _two_lord_attacker(None)
    rows = build_strike_rows(s, atk, context="battle")
    assert not any(r.kind == "crossbows" for r in rows)


def test_javelin_budget_is_per_lord_not_pooled() -> None:
    # Two Lords each holding Harbah (M3) with 4 Light Horse each: each Lord
    # gets its own 4-unit Javelin budget (8 total), not a shared 4.
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    A, B = "al_mustain", "al_mundir"
    for lid in (A, B):
        s.lords[lid].forces = {"light_horse": 4}
        s.lords[lid].capabilities = ["M3"]
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    atk = battleside_for_lords(s, [A, B], "muslim", "attacker", active_lord_id=A)
    rows = build_strike_rows(s, atk, context="battle")
    jav = sum(r.count for r in rows if r.kind == "javelins")
    assert jav == 8                             # 4 per Lord, not a shared 4


def test_single_lord_pooled_path_unchanged() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    al = s.lords["al_mustain"]
    al.forces = {"men_at_arms": 3}
    al.capabilities = ["M2"]
    al.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    side = BattleSide(side="muslim", role="attacker", lord_ids=["al_mustain"],
                      forces={"men_at_arms": 3}, capabilities_in_play=["M2"])
    rows = build_strike_rows(s, side, context="battle")
    assert sum(r.count for r in rows if r.kind == "crossbows") == 3
