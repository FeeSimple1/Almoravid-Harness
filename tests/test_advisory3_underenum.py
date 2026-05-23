"""Advisory #3 (§1 under-enumeration): working handlers must be reachable
from the legal-move menu, or a menu-driven (LLM) player can never use them.

Found by an enumerator/handler cross-check: dinars_deposit (4.1.4) and
designate_lieutenant (4.1.3) had working handlers but NO menu entry. These
tests assert the menu now offers them when (and only when) legal — negative
+ positive, per Advisory §9 ("assert the enumerator does not offer the bad
move, not just that the handler rejects it").
"""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.campaign import _is_marshal
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _plan_state(scenario="scenario_d_arrival", seed=1):
    s = load_scenario(scenario, seed=seed)
    s.meta.phase = "campaign"
    s.meta.campaign_step = "plan"
    return s


# --- dinars_deposit (4.1.4) ----------------------------------------------
def test_dinars_offered_for_taifa_lord_with_coin() -> None:
    s = _plan_state()
    tl = "al_mutamid"   # a Muslim Taifa Lord
    # Place him on-map, Unbesieged, with Coin (4.1.4 eligibility).
    s.lords[tl].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords[tl].in_stronghold = False
    s.lords[tl].assets["coin"] = 2
    moves = [m for m in legal_moves(s)
             if m["type"] == "dinars_deposit" and m["lord_id"] == tl]
    assert moves, "dinars_deposit should be offered for a Taifa Lord with Coin"
    r = apply_action(s, moves[0])
    assert r["deposited"] == 2


def test_dinars_not_offered_without_coin() -> None:
    s = _plan_state()
    for lid, l in s.lords.items():
        if l.side == "muslim":
            l.assets.pop("coin", None)
    assert not [m for m in legal_moves(s) if m["type"] == "dinars_deposit"]


# --- designate_lieutenant (4.1.3) ----------------------------------------
def test_designate_lieutenant_offered_for_two_colocated_nonmarshals() -> None:
    s = _plan_state()
    nonmar = [lid for lid, l in s.lords.items()
              if l.side == "christian" and not _is_marshal(lid, "christian")]
    a, b = nonmar[0], nonmar[1]
    for lid in (a, b):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="toledo")
        s.lords[lid].in_stronghold = False
        s.lords[lid].lieutenant_of = None
    pairs = [m for m in legal_moves(s)
             if m["type"] == "designate_lieutenant"
             and m["lord_id"] in (a, b) and m["commander_id"] in (a, b)]
    assert len(pairs) == 2, f"both directions expected, got {pairs}"
    apply_action(s, pairs[0])
    assert s.lords[pairs[0]["lord_id"]].lieutenant_of == pairs[0]["commander_id"]


def test_designate_lieutenant_excludes_marshal_and_other_locales() -> None:
    s = _plan_state()
    marshal = next(lid for lid, l in s.lords.items()
                   if l.side == "christian" and _is_marshal(lid, "christian"))
    other = next(lid for lid, l in s.lords.items()
                 if l.side == "christian" and not _is_marshal(lid, "christian"))
    # Co-locate the Marshal with one non-Marshal: no valid pair (Marshal
    # can be neither Lower Lord nor Lieutenant, 4.1.3).
    for lid in (marshal, other):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="toledo")
        s.lords[lid].in_stronghold = False
    # Move every OTHER christian away from toledo.
    for lid, l in s.lords.items():
        if l.side == "christian" and lid not in (marshal, other):
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    pairs = [m for m in legal_moves(s) if m["type"] == "designate_lieutenant"
             and "toledo" == s.lords[m["lord_id"]].cylinder.locale_id]
    assert pairs == [], f"Marshal must not form a Lieutenant pair: {pairs}"
