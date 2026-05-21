"""T4 (1.4.3 RECOGNITION OF NEUTRALITY) as an interactive pending
decision: when a Taifa goes Parias and a side is Besieging a now-Neutral
Enemy Stronghold, that side chooses remove-Siege vs add-Enemy-markers."""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.campaign import (
    _maybe_set_neutrality_pending, adjust_taifa_status,
)
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _setup(s):
    # Christian besieges calatayud (a Castle in the Independent Zaragoza
    # Taifa, no Muslim Lord there). On ->Parias it becomes truly Neutral,
    # so the RECOGNITION OF NEUTRALITY OR-choice belongs to the Christian.
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="calatayud")
    s.lords["alvar_fanez"].in_stronghold = False
    s.locales["calatayud"].siege_yellow = 1
    s.locales["calatayud"].jihad_markers = 0
    s.locales["calatayud"].conquered_markers = 0
    s.meta.phase = "levy"
    s.meta.active_player = "muslim"   # disbanding side (Taifa Lord)


def test_neutrality_pending_set_and_enumerated() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup(s)
    r = adjust_taifa_status(s, "zaragoza", "parias")  # deferred OR-choice
    set_it = _maybe_set_neutrality_pending(s, r, resume_active="muslim")
    assert set_it is True
    assert s.pending.kind == "neutrality_choice"
    assert s.pending.waiting_on == "christian"   # the besieging side
    assert s.meta.active_player == "christian"
    types = {m["type"] for m in legal_moves(s)}
    assert types == {"respond_neutrality_choice"}


def test_neutrality_choice_add_places_jihad_and_restores_turn() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup(s)
    r = adjust_taifa_status(s, "zaragoza", "parias")
    _maybe_set_neutrality_pending(s, r, resume_active="muslim")
    apply_action(s, {"type": "respond_neutrality_choice",
                     "side": "christian",
                     "choices": {"calatayud": "add"}})
    assert s.pending is None
    assert s.locales["calatayud"].jihad_markers > 0      # enemy markers added
    assert s.locales["calatayud"].siege_yellow == 1      # Siege kept
    assert s.meta.active_player == "muslim"             # turn restored


def test_neutrality_choice_remove_lifts_siege() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _setup(s)
    r = adjust_taifa_status(s, "zaragoza", "parias")
    _maybe_set_neutrality_pending(s, r, resume_active="muslim")
    apply_action(s, {"type": "respond_neutrality_choice",
                     "side": "christian",
                     "choices": {"calatayud": "remove"}})
    assert s.pending is None
    assert s.locales["calatayud"].siege_yellow == 0
    assert s.locales["calatayud"].jihad_markers == 0
    assert s.meta.active_player == "muslim"
