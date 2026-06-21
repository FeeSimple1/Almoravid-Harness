"""C20 Fueros + C21 Sisnando Davidez: Levy-segment Jihad-removal caps."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def _activation(s, lord_id="alfonso"):
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = lord_id
    s.meta.actions_remaining = 2


def test_fueros_removes_two_jihad_when_alfonso_closer() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Make a Reconquista Taifa with Jihad at its City; put Alfonso there,
    # all Muslim Lords off-map so Alfonso is trivially closer.
    t = next(iter(s.taifas.values()))
    t.status = "reconquista"
    loc_id = t.locale_ids[0]
    s.locales[loc_id].jihad_markers = 3
    for L in s.lords.values():
        if L.side == "muslim":
            L.cylinder = Cylinder(kind="calendar", box=1)
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="C20", scope="side_wide", owner_side="christian"))
    _activation(s)
    assert any(m["type"] == "cap_fueros" for m in legal_moves(s))
    r = apply_action(s, {"type": "cap_fueros", "side": "christian",
                         "target_locale": loc_id})
    assert r["jihad_removed"] == 2
    assert s.locales[loc_id].jihad_markers == 1
    # Once per turn: no longer offered.
    assert not any(m["type"] == "cap_fueros" for m in legal_moves(s))


def test_fueros_not_offered_when_muslim_co_located() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    t = next(iter(s.taifas.values()))
    t.status = "reconquista"
    loc_id = t.locale_ids[0]
    s.locales[loc_id].jihad_markers = 2
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="C20", scope="side_wide", owner_side="christian"))
    # A Muslim Lord co-located => Alfonso not "closer".
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    _activation(s)
    assert loc_id not in __import__("almoravid.campaign", fromlist=["_fueros_targets"])._fueros_targets(s)


def test_sisnando_removes_one_jihad_from_empty_locale() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Pick a locale with no lords, clear sieges, add a jihad.
    occupied = {L.cylinder.locale_id for L in s.lords.values()
                if L.cylinder.kind == "locale"}
    loc_id = next(lid for lid, loc in s.locales.items()
                  if lid not in occupied and loc.territory in s.taifas)
    loc = s.locales[loc_id]
    loc.jihad_markers = 2
    loc.siege_yellow = loc.siege_green = 0
    loc.bypass_yellow = loc.bypass_green = False
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["alfonso"].capabilities.append("C21")
    _activation(s)
    assert any(m["type"] == "cap_sisnando" and m["target_locale"] == loc_id
               for m in legal_moves(s))
    r = apply_action(s, {"type": "cap_sisnando", "side": "christian",
                         "target_locale": loc_id})
    assert r["jihad_removed"] == 1
    assert loc.jihad_markers == 1


def test_sisnando_skips_besieged_locale() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    occupied = {L.cylinder.locale_id for L in s.lords.values()
                if L.cylinder.kind == "locale"}
    loc_id = next(lid for lid, loc in s.locales.items()
                  if lid not in occupied and loc.territory in s.taifas)
    loc = s.locales[loc_id]
    loc.jihad_markers = 1
    loc.siege_yellow = 1   # besieged => ineligible
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["alfonso"].capabilities.append("C21")
    _activation(s)
    from almoravid.campaign import _sisnando_targets
    assert loc_id not in _sisnando_targets(s)
