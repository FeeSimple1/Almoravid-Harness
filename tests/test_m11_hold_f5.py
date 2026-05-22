"""Playtest F5: M11 'Al-Qadir balks at payment' is a HOLD event — held
when drawn (not auto-fired), then played at the Muslim's discretion to
add Jihad (base 1, or 3 with the Yusuf/Sir bonus). The base +1 is
unconditional (the 'Lords. Yusuf or Sir' line governs the Capability)."""
from __future__ import annotations

from almoravid.scenarios import load_scenario
from almoravid.events import resolve_event
from almoravid.actions import apply_action
from almoravid.static_data import load_cards


def test_m11_is_hold_not_immediate() -> None:
    assert load_cards()["cards"]["M11"]["event_persistence"] == "hold"


def test_m11_held_on_draw_not_fired() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    total0 = sum(l.jihad_markers for l in s.locales.values())
    resolve_event(s, "muslim", "M11", {})
    assert "M11" in s.decks.this_levy_events.get("muslim", [])
    assert sum(l.jihad_markers for l in s.locales.values()) == total0  # not fired


def test_play_m11_adds_one_jihad_base() -> None:
    from almoravid.state import Cylinder
    s = load_scenario("scenario_a_toledo_beset")
    resolve_event(s, "muslim", "M11", {})   # hold it
    # M11 requires Yusuf/Sir on map. Put Yusuf in an INDEPENDENT Taifa
    # (no bonus) -> base +1.
    indep = next(t for t in s.taifas.values() if t.status == "independent")
    s.lords["yusuf"].cylinder = Cylinder(kind="locale",
                                         locale_id=indep.locale_ids[0])
    s.lords["yusuf"].in_stronghold = False
    s.meta.phase = "campaign"
    s.meta.active_player = "muslim"
    total0 = sum(l.jihad_markers for l in s.locales.values())
    r = apply_action(s, {"type": "play_al_qadir", "side": "muslim"})
    assert r["jihad_added"] == 1 and r["bonus"] is False
    assert sum(l.jihad_markers for l in s.locales.values()) == total0 + 1
    assert "M11" not in s.decks.this_levy_events.get("muslim", [])


def test_m11_enumerated_when_held() -> None:
    from almoravid.state import Cylinder
    s = load_scenario("scenario_a_toledo_beset")
    resolve_event(s, "muslim", "M11", {})
    s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id="algeciras")
    s.lords["yusuf"].in_stronghold = False
    s.meta.phase = "campaign"
    s.meta.active_player = "muslim"
    from almoravid.legal_moves import legal_moves
    assert any(m.get("type") == "play_al_qadir" for m in legal_moves(s))


def test_m11_not_playable_without_yusuf_or_sir() -> None:
    # Scenario A sets Yusuf/Sir aside -> M11 cannot be played.
    s = load_scenario("scenario_a_toledo_beset")
    resolve_event(s, "muslim", "M11", {})
    s.meta.phase = "campaign"
    s.meta.active_player = "muslim"
    from almoravid.legal_moves import legal_moves
    assert not any(m.get("type") == "play_al_qadir" for m in legal_moves(s))
    import pytest
    from almoravid.actions import IllegalAction
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "play_al_qadir", "side": "muslim"})
    assert ei.value.code == "no_eligible_lord"
