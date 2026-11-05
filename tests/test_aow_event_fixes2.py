"""M13 Severed Heads (Ravaging) + C3/M3 Swollen River Avoid-block."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _act(s, lord_id, side):
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = side
    s.meta.active_lord_id = lord_id
    s.meta.actions_remaining = 2


def test_m13_severed_heads_ravaging_jihad() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.this_levy_events["muslim"] = ["M13"]
    al = s.lords["al_mundir"]
    al.cylinder = Cylinder(kind="locale", locale_id="transduero")
    _act(s, "al_mundir", "muslim")
    assert not any(m["type"] == "play_severed_heads" for m in legal_moves(s))
    apply_action(s, {"type": "cmd_ravage", "side": "muslim"})
    assert any(m["type"] == "play_severed_heads" for m in legal_moves(s))
    r = apply_action(s, {"type": "play_severed_heads", "side": "muslim",
                         "mode": "jihad"})
    assert r.get("jihad_added") == 2 or r.get("no_op")
    assert "M13" in s.decks.discard


def test_m13_severed_heads_ravaging_shift() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.this_levy_events["muslim"] = ["M13"]
    al = s.lords["al_mundir"]
    al.cylinder = Cylinder(kind="locale", locale_id="transduero")
    # A Taifa Lord on the Calendar to shift.
    tl = next(l for l in s.lords.values() if l.is_taifa
              and l.id != "al_mundir")
    tl.cylinder = Cylinder(kind="calendar", box=8)
    sm = next((m for m in s.calendar.service_markers if m.lord_id == tl.id), None)
    _act(s, "al_mundir", "muslim")
    apply_action(s, {"type": "cmd_ravage", "side": "muslim"})
    r = apply_action(s, {"type": "play_severed_heads", "side": "muslim",
                         "mode": "shift", "target_lord": tl.id})
    assert r["mode"] == "shift" and r["boxes"] == 2
    assert tl.cylinder.box == 6
    assert "M13" in s.decks.discard


def test_swollen_river_blocks_avoid_into_battle() -> None:
    from tests.test_interactive_approach_battle import _march_into_battle
    state = _march_into_battle()
    state.decks.draw = [cid for cid in state.decks.draw if cid != "C3"]
    state.decks.held["christian"] = ["C3"]
    result = apply_action(state, {"type": "respond_avoid_battle", "side": "muslim",
                                 "target_locale_id": "palencia", "way_type": "road"})
    assert result == {"pending": "swollen_river_block", "waiting_on": "christian"}
    assert state.lords["al_mutamid"].cylinder.locale_id == "sahagun"
    result = apply_action(state, {"type": "respond_swollen_river_block", "side": "christian",
                                 "play": True})
    assert result["swollen_river_played"] == "C3"
    assert "C3" not in state.decks.held["christian"]
    assert state.decks.discard.count("C3") == 1
