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


# --- C14 Pope Gregory / C15 Cluniacs Hold-event plays (under-enum) -------
import copy as _copy
from almoravid.actions import IllegalAction


def _christian_levy_muster(scenario="scenario_a_toledo_beset", seed=1):
    """A state on the Christian side mid-Levy (muster step), where Hold
    events are playable 'any time'."""
    s = load_scenario(scenario, seed=seed)
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    return s


def test_c14_pope_gregory_offered_when_held_with_correct_modes() -> None:
    s = _christian_levy_muster()
    s.decks.this_levy_events["christian"] = ["C14"]
    # Put Sancho on the Calendar so muster_from_calendar is applicable.
    from almoravid.state import Cylinder, ServiceMarker
    s.lords["sancho"].cylinder = Cylinder(kind="calendar",
                                          box=s.calendar.current_box)
    if not any(m.lord_id == "sancho" for m in s.calendar.service_markers):
        s.calendar.service_markers.append(
            ServiceMarker(lord_id="sancho", box=s.calendar.current_box))
    moves = [m for m in legal_moves(s) if m["type"] == "play_pope_gregory"]
    modes = {(m["lord_id"], m["mode"]) for m in moves}
    assert ("sancho", "muster_from_calendar") in modes
    assert ("sancho", "service_shift_right") in modes
    assert ("sancho", "lordship_plus_2") in modes
    # Only Sancho/Eudes are valid C14 targets.
    assert all(m["lord_id"] in ("sancho", "eudes") for m in moves)
    # Every offered C14 play is accepted by the handler (no over-enum).
    for m in moves:
        apply_action(_copy.deepcopy(s), m)


def test_c14_not_offered_when_not_held() -> None:
    s = _christian_levy_muster()
    s.decks.this_levy_events["christian"] = []
    assert not [m for m in legal_moves(s) if m["type"] == "play_pope_gregory"]


def test_c15_cluniacs_offered_for_any_christian_when_held() -> None:
    s = _christian_levy_muster()
    s.decks.this_levy_events["christian"] = ["C15"]
    moves = [m for m in legal_moves(s) if m["type"] == "play_cluniacs"]
    assert moves, "C15 should be offered when held"
    targets = {m["lord_id"] for m in moves}
    # At least one on-map Christian Lord is a target; all targets Christian.
    assert all(s.lords[lid].side == "christian" for lid in targets)
    for m in moves:
        apply_action(_copy.deepcopy(s), m)   # no over-enumeration


def test_c14_muster_mode_absent_when_no_free_seat() -> None:
    """If the target's only Seat is enemy-occupied, the muster mode must
    NOT be offered (mirrors the handler's 3.4.1 free-Seat gate)."""
    s = _christian_levy_muster(scenario="scenario_d_arrival")
    s.decks.this_levy_events["christian"] = ["C14"]
    from almoravid.state import Cylinder
    s.lords["sancho"].cylinder = Cylinder(kind="calendar",
                                          box=s.calendar.current_box)
    assert s.lords["sancho"].seats == ["jaca"]
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id="jaca")
    s.lords["al_mustain"].in_stronghold = False
    modes = {(m["lord_id"], m["mode"]) for m in legal_moves(s)
             if m["type"] == "play_pope_gregory"}
    assert ("sancho", "muster_from_calendar") not in modes
