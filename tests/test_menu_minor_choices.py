"""Menu reachability for two optional actions the executor already
supported but legal_moves never advertised:

  - Surrender decline-to-roll (4.5.1): the Besieger MAY roll OR decline.
  - Multi-Seat Supply in one action (4.6.1 Important).
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder
from tests.test_phase6h_tier_a import _setup_active_lord


def test_surrender_decline_offered_and_round_trips() -> None:
    s = _setup_active_lord("scenario_a_toledo_beset", "alvar_fanez",
                           "zaragoza")
    s.locales["zaragoza"].siege_yellow = 1        # already Besieging
    for lo in s.lords.values():
        if (lo.side == "muslim" and lo.cylinder.kind == "locale"
                and lo.cylinder.locale_id == "zaragoza"):
            lo.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    sieges = [m for m in legal_moves(s) if m["type"] == "cmd_siege"]
    assert any(m.get("surrender") is False for m in sieges), \
        "decline-to-roll Surrender not advertised"
    assert any("surrender" not in m for m in sieges)   # default (roll) too
    decline = next(m for m in sieges if m.get("surrender") is False)
    apply_action(s, decline)                       # must not raise


def test_multi_seat_supply_offered_and_round_trips() -> None:
    s = _setup_active_lord("scenario_f_reconquista", "alfonso", "leon")
    s.lords["alfonso"].assets = {"mule": 2}        # covers leon(0)+burgos(2)
    supplies = [m for m in legal_moves(s)
                if m["type"] == "cmd_supply" and "source_seats" in m]
    assert supplies, "multi-Seat Supply not advertised"
    mv = next(m for m in supplies if len(m["source_seats"]) >= 2)
    before = s.lords["alfonso"].assets.get("prov", 0)
    r = apply_action(s, mv)
    assert set(r["source_seats"]) == set(mv["source_seats"])
    assert s.lords["alfonso"].assets.get("prov", 0) == before + len(mv["source_seats"])
