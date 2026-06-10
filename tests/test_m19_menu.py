"""M19 African Fleet Port-to-Port March must be reachable from the menu.

The handler (cmd_march_port_to_port) existed and worked, but legal_moves
never advertised it, so a menu-driven player could not discover it.
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder
from tests.test_phase6h_tier_a import _setup_active_lord


def test_m19_port_to_port_offered_and_round_trips() -> None:
    from almoravid.scenarios import load_scenario
    base = load_scenario("scenario_a_toledo_beset", seed=11)
    ports = [lid for lid, loc in base.locales.items() if loc.has_port]
    assert len(ports) >= 2
    from_port, to_port = ports[0], ports[1]
    s = _setup_active_lord("scenario_a_toledo_beset", "al_mutamid", from_port)
    # Clear Christians from the destination Port.
    for lo in s.lords.values():
        if (lo.side == "christian" and lo.cylinder.kind == "locale"
                and lo.cylinder.locale_id == to_port):
            lo.cylinder = Cylinder(kind="locale", locale_id="leon")
    s.decks.this_levy_events["muslim"] = ["M19"]
    moves = [m for m in legal_moves(s)
             if m["type"] == "cmd_march_port_to_port"]
    assert moves, "M19 Port-to-Port March not advertised in the menu"
    assert any(m["target_locale_id"] == to_port for m in moves)
    mv = next(m for m in moves if m["target_locale_id"] == to_port)
    r = apply_action(s, mv)
    assert r["to"] == to_port
    assert s.lords["al_mutamid"].cylinder.locale_id == to_port


def test_m19_not_offered_without_card() -> None:
    from almoravid.scenarios import load_scenario
    base = load_scenario("scenario_a_toledo_beset", seed=11)
    ports = [lid for lid, loc in base.locales.items() if loc.has_port]
    s = _setup_active_lord("scenario_a_toledo_beset", "al_mutamid", ports[0])
    s.decks.this_levy_events["muslim"] = []      # M19 not held
    assert not [m for m in legal_moves(s)
                if m["type"] == "cmd_march_port_to_port"]
