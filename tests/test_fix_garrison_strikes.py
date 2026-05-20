"""FIX-B S3: Garrison adds Strikes in Storm (4.5.2 GARRISON FORCES)."""
from __future__ import annotations
from almoravid.battle import BattleSide, build_strike_rows, _step_hits
from almoravid.scenarios import load_scenario


def test_garrison_contributes_missile_strikes_in_storm():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Defender with NO Lord forces but a City garrison (3 MaA + 3 Militia).
    dfd = BattleSide(side="muslim", role="defender", lord_ids=["al_mutamid"],
                     forces={})
    dfd.garrison_forces = {"men_at_arms": 3, "militia": 3}
    rows = build_strike_rows(s, dfd, context="storm")
    # MaA crossbows (3 x1/2 = 1.5) + Militia bowmen (3 x1/2 = 1.5) = 3.0
    raw, by_kind = _step_hits(rows, "missile", None)
    assert raw == 3.0
    assert by_kind.get("crossbows", 0) == 1.5
    assert by_kind.get("bowmen", 0) == 1.5
    # And melee: MaA 3 x1 + Militia 3 x1/2 = 4.5
    raw_m, _ = _step_hits(rows, "melee", "foot")
    assert raw_m == 4.5


def test_garrison_strikes_only_in_storm_not_battle():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    dfd = BattleSide(side="muslim", role="defender", lord_ids=["al_mutamid"],
                     forces={})
    dfd.garrison_forces = {"men_at_arms": 2, "militia": 1}
    rows_battle = build_strike_rows(s, dfd, context="battle")
    # In Battle, garrison_forces contribute nothing (Storm-only).
    raw, _ = _step_hits(rows_battle, "missile", None)
    assert raw == 0.0
