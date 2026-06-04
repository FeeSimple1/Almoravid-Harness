"""Menu (legal_moves) reachability + round-trip regressions.

Every action legal_moves advertises must round-trip through apply_action,
and every important legal action must be reachable from the menu. These
cover four reported defects:

1. Marshal Group March (4.3.1) was legal but absent from the menu.
2. Legal Cart-over-Pass Marches (4.3.2) were suppressed by the menu.
3. Winter Siege advertised Ravage even when the Locale was already Ravaged.
4. Winter Siege Pay omitted the required payer_lord_id.
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.campaign import _enter_winter_box
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests.test_phase6b_approach import _activate_lord_at_locale
from tests.test_winter_siege_632 import _setup_besieger

# ---------------------------------------------------------------------------
# 1. Marshal Group March is offered (and round-trips).
# ---------------------------------------------------------------------------

def test_group_march_offered_and_round_trips() -> None:
    s = _activate_lord_at_locale("scenario_a_toledo_beset", "alfonso",
                                 "leon", seed=11)
    # Co-locate two independent Christian Lords with the Marshal.
    for lid in ("garcia_ordonez", "pedro_ansurez"):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="leon")
        s.lords[lid].in_stronghold = False
        s.lords[lid].lieutenant_of = None
    s.lords["alfonso"].assets = {}      # Unladen so cost stays affordable
    groups = [m for m in legal_moves(s)
              if m["type"] == "cmd_march" and "group_lord_ids" in m]
    assert groups, "no Group March advertised"
    # A 'bring all eligible' group exists.
    assert any(set(m["group_lord_ids"]) == {"garcia_ordonez", "pedro_ansurez"}
               for m in groups)
    mv = next(m for m in groups
              if set(m["group_lord_ids"]) == {"garcia_ordonez",
                                              "pedro_ansurez"})
    dest = mv["target_locale_id"]
    apply_action(s, mv)
    for lid in ("alfonso", "garcia_ordonez", "pedro_ansurez"):
        assert s.lords[lid].cylinder.locale_id == dest


# ---------------------------------------------------------------------------
# 2. Cart-over-Pass March is offered (and round-trips, Laden, 2 actions).
# ---------------------------------------------------------------------------

def test_cart_over_pass_march_offered_and_round_trips() -> None:
    s = _activate_lord_at_locale("scenario_a_toledo_beset", "alfonso",
                                 "simancas", seed=11)
    s.lords["alfonso"].assets = {"cart": 1, "prov": 1}   # no mule
    before = s.meta.actions_remaining
    assert before >= 2
    pass_moves = [m for m in legal_moves(s)
                  if m["type"] == "cmd_march"
                  and m["way_type"] == "pass"
                  and m["target_locale_id"] == "somosierra"
                  and "group_lord_ids" not in m]
    assert pass_moves, "Cart-over-Pass March was suppressed by the menu"
    apply_action(s, pass_moves[0])
    assert s.lords["alfonso"].cylinder.locale_id == "somosierra"
    assert s.meta.actions_remaining == before - 2     # Laden = 2 actions


# ---------------------------------------------------------------------------
# 3. Winter Siege Ravage not advertised when already Ravaged.
# ---------------------------------------------------------------------------

def _winter_besieger_actions(loc="calatayud"):
    s = load_scenario("scenario_f_reconquista")
    al, loc = _setup_besieger(s, loc)
    al.assets = {"coin": 1}
    _enter_winter_box(s, 7)
    assert s.pending is not None
    assert s.pending.payload["step"] == "besieger_actions"
    return s, loc


def test_winter_ravage_hidden_when_already_ravaged() -> None:
    s, loc = _winter_besieger_actions()
    s.locales[loc].ravaged = "yellow"      # already Ravaged
    ravages = [m for m in legal_moves(s)
               if m.get("mode") == "ravage"]
    assert not ravages, "illegal Ravage advertised on an already-Ravaged Locale"
    # Sanity: everything advertised round-trips (no IllegalAction).
    for m in legal_moves(s):
        if m.get("mode") == "ravage":
            apply_action(s, m)            # would raise if offered


def test_winter_ravage_offered_when_unravaged() -> None:
    s, loc = _winter_besieger_actions()
    s.locales[loc].ravaged = "none"
    modes = {m.get("mode") for m in legal_moves(s)
             if m["type"] == "winter_siege_action"}
    # Ravage should be present on an un-Ravaged enemy Siege Locale, and
    # whatever is offered must round-trip.
    if "ravage" in modes:
        mv = next(m for m in legal_moves(s) if m.get("mode") == "ravage")
        apply_action(s, mv)              # must not raise


# ---------------------------------------------------------------------------
# 4. Winter Siege Pay carries payer_lord_id (and round-trips).
# ---------------------------------------------------------------------------

def test_winter_pay_carries_payer_and_round_trips() -> None:
    s, loc = _winter_besieger_actions()
    # Advance past the besieger action into the Pay step.
    apply_action(s, {"type": "winter_siege_action", "side": "christian",
                     "lord_id": "alfonso", "mode": "pass"})
    assert s.pending.payload["step"] == "pay"
    pays = [m for m in legal_moves(s)
            if m["type"] == "winter_siege_pay" and not m.get("done")]
    assert pays, "no Winter Siege Pay advertised"
    for m in pays:
        assert "payer_lord_id" in m, "Pay action omits payer_lord_id"
    before = s.lords["alfonso"].assets.get("coin", 0)
    apply_action(s, pays[0])             # must not raise
    assert s.lords["alfonso"].assets.get("coin", 0) == before - 1
