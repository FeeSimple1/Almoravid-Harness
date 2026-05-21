"""4.3.6 SORTIE: a Lord inside a Bypassed Friendly Stronghold uses 1
March action to Approach the Bypassing Enemy in the same Locale."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _sortie_setup(seed=3):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    here = "leon"   # Christian-friendly City
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id=here)
    al.in_stronghold = True
    al.moved_fought = False
    al.forces = {"knights": 2}
    enemy = s.lords["al_mustain"]
    enemy.cylinder = Cylinder(kind="locale", locale_id=here)
    enemy.in_stronghold = False
    enemy.forces = {"sergeants": 1}
    # Muslim is Bypassing the Christian Stronghold.
    s.locales[here].bypass_green = True
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    s.meta.actions_remaining = 3
    return s, here


def test_sortie_sets_approach_pending_against_bypassing_enemy() -> None:
    s, here = _sortie_setup()
    r = apply_action(s, {"type": "cmd_sortie", "side": "christian"})
    assert r["sortie"] == here
    assert "al_mustain" in r["defenders"]
    assert s.lords["alfonso"].in_stronghold is False
    assert s.lords["alfonso"].moved_fought is True
    assert s.meta.actions_remaining == 2
    assert s.pending is not None
    assert s.pending.kind == "march_arrival_response"
    assert s.pending.waiting_on == "muslim"


def test_sortie_then_stand_resolves_battle() -> None:
    s, here = _sortie_setup()
    apply_action(s, {"type": "cmd_sortie", "side": "christian"})
    # Bypassing Muslim stands and fights.
    apply_action(s, {"type": "respond_stand_battle", "side": "muslim"})
    assert s.pending is None   # Battle resolved, Approach cleared


def test_sortie_requires_enemy_bypass_marker() -> None:
    s, here = _sortie_setup()
    s.locales[here].bypass_green = False   # not Bypassed
    try:
        apply_action(s, {"type": "cmd_sortie", "side": "christian"})
        assert False, "expected IllegalAction (not bypassed)"
    except Exception as e:
        assert "Bypassed" in str(e) or "not_bypassed" in str(e)


def test_sortie_in_legal_moves() -> None:
    s, here = _sortie_setup()
    from almoravid.legal_moves import legal_moves
    moves = legal_moves(s)
    assert any(m.get("type") == "cmd_sortie" for m in moves)
