"""Cross-project Advisory #2 — the illegal co-location bug class.

Door B (marker lifecycle): a Siege/Bypass marker must be cleared whenever a
Stronghold becomes free of the owning side's Lords, on EVERY departure path
(RoP 4.3.5/4.3.6/4.4.1). A global backstop (_sweep_all_orphaned_markers) runs
after every action so paths the per-handler sweeps missed (M19 Sail, event
removal, Winter/Curias Disband) cannot leave an orphan.

Door C (placement): every on-board placement path must Muster only at a free
Seat (3.4.1 "neither Enemy nor has any Enemy Lords present"); the event
auto-Musters (M21/M22/C16) used seats[0] blindly and could drop a Lord onto
an enemy-occupied Seat (co-location with no battle).
"""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _co_located(s) -> list[str]:
    by: dict[str, set] = {}
    for lid, l in s.lords.items():
        if l.cylinder.kind == "locale" and not l.in_stronghold:
            by.setdefault(l.cylinder.locale_id, set()).add(l.side)
    return [loc for loc, sides in by.items()
            if "christian" in sides and "muslim" in sides]


# --- Door B ---------------------------------------------------------------
def test_doorB_backstop_clears_orphan_after_sail_M19() -> None:
    """A sole besieger that sails away via M19 leaves no orphaned Siege
    marker — the post-action backstop clears it (origin free of Muslims)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # al_mutamid is the only Muslim at sevilla; give it a (notional) Siege.
    s.locales["sevilla"].siege_green = 2
    assert not [lid for lid, l in s.lords.items()
                if l.side == "muslim" and l is not s.lords["al_mutamid"]
                and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == "sevilla"]
    s.decks.this_levy_events["muslim"] = ["M19"]
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "muslim"
    s.meta.active_lord_id = "al_mutamid"
    s.meta.actions_remaining = 2
    apply_action(s, {"type": "cmd_march_port_to_port", "side": "muslim",
                     "target_locale_id": "valencia"})
    assert s.lords["al_mutamid"].cylinder.locale_id == "valencia"
    assert s.locales["sevilla"].siege_green == 0      # orphan cleared


def test_doorB_backstop_keeps_live_siege() -> None:
    """The backstop must NOT clear a live Siege: a besieger still present
    keeps his marker."""
    from almoravid.campaign import _sweep_all_orphaned_markers
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Álvar besieges Toledo at setup (siege_yellow=1, Álvar present).
    assert s.locales["toledo"].siege_yellow == 1
    assert s.lords["alvar_fanez"].cylinder.locale_id == "toledo"
    _sweep_all_orphaned_markers(s)
    assert s.locales["toledo"].siege_yellow == 1      # still besieged


# --- Door C ---------------------------------------------------------------
def test_doorC_c16_does_not_muster_onto_enemy_seat() -> None:
    """C16 Bernard auto-Muster must not place a Lord at a Seat occupied by
    an Enemy Lord (3.4.1) — it no-ops instead of co-locating."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.lords["sancho"].cylinder = Cylinder(kind="calendar",
                                          box=s.calendar.current_box)
    assert s.lords["sancho"].seats == ["jaca"]
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id="jaca")
    s.lords["al_mustain"].in_stronghold = False
    s.decks.this_levy_events["christian"] = ["C16"]
    r = resolve_event(s, "christian", "C16",
                      payload={"mode": "muster", "lord_id": "sancho"})
    assert r.get("no_op") is True
    assert s.lords["sancho"].cylinder.kind == "calendar"   # not placed
    assert "jaca" not in _co_located(s)


def test_doorC_m21_does_not_muster_onto_enemy_seat() -> None:
    """M21 Al-Sumaisir Muster branch must skip an enemy-occupied Seat;
    with the seat blocked it falls through to the Jihad branch (no
    co-location)."""
    s = load_scenario("scenario_d_arrival", seed=1)
    # Pick a Muslim Taifa Lord on the Calendar with a single Seat, then
    # occupy that Seat with a Christian Lord.
    tl = next((l for l in s.lords.values()
               if l.is_taifa and l.side == "muslim"
               and l.cylinder.kind == "calendar" and l.seats), None)
    assert tl is not None, "need a Calendar Taifa Lord with a Seat"
    seat = tl.seats[0]
    # Put a Christian Lord on that Seat.
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=seat)
    s.lords["alfonso"].in_stronghold = False
    s.decks.this_levy_events["muslim"] = ["M21"]
    before = tl.cylinder.kind
    resolve_event(s, "muslim", "M21", payload={"lord_id": tl.id})
    # The Taifa Lord was NOT placed onto the enemy-occupied Seat.
    assert not (s.lords[tl.id].cylinder.kind == "locale"
                and s.lords[tl.id].cylinder.locale_id == seat)
    assert seat not in _co_located(s)
