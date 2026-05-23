"""M9 Emir al-Muslimin (Arts of War ref M9): Yusuf, if closer than any
Christian (shortest chain of adjacent spaces) to a Jihad-eligible Locale
(1.4.4), may use his ENTIRE Command card to add 1 Jihad there. Co-location
with a Christian counts as NOT closer.
"""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import _emir_jihad_targets
from almoravid.events import _jihad_eligible_locales
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def _setup_yusuf(at_locale, christian_at=None, scenario="scenario_d_arrival"):
    s = load_scenario(scenario, seed=1)
    y = s.lords["yusuf"]
    y.capabilities.append("M9")
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="M9", scope="this_lord", owner_side="muslim",
        owner_lord_id="yusuf"))
    y.cylinder = Cylinder(kind="locale", locale_id=at_locale)
    y.in_stronghold = False
    # Park all Christians far away (leon) unless told otherwise.
    for l in s.lords.values():
        if l.side == "christian" and l.cylinder.kind == "locale":
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    if christian_at is not None:
        s.lords["alfonso"].cylinder = Cylinder(kind="locale",
                                               locale_id=christian_at)
        s.lords["alfonso"].in_stronghold = False
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "muslim"
    s.meta.active_lord_id = "yusuf"
    s.meta.actions_remaining = 2
    return s


def test_emir_adds_jihad_and_consumes_entire_card() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    tgt = _jihad_eligible_locales(s)[0]
    s = _setup_yusuf(at_locale=tgt)
    assert tgt in _emir_jihad_targets(s)
    moves = [m for m in legal_moves(s) if m["type"] == "cmd_emir_jihad"
             and m["jihad_locale"] == tgt]
    assert moves, "cmd_emir_jihad should be offered"
    before = s.locales[tgt].jihad_markers
    apply_action(s, {"type": "cmd_emir_jihad", "side": "muslim",
                     "jihad_locale": tgt})
    assert s.locales[tgt].jihad_markers == before + 1
    assert s.meta.actions_remaining == 0   # entire Command card


def test_emir_not_closer_when_christian_co_located() -> None:
    s0 = load_scenario("scenario_d_arrival", seed=1)
    tgt = _jihad_eligible_locales(s0)[0]
    s = _setup_yusuf(at_locale=tgt, christian_at=tgt)   # christian on target
    assert tgt not in _emir_jihad_targets(s)
    assert not [m for m in legal_moves(s)
                if m["type"] == "cmd_emir_jihad" and m["jihad_locale"] == tgt]


def test_emir_rejected_without_capability() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    tgt = _jihad_eligible_locales(s)[0]
    s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id=tgt)
    s.lords["yusuf"].in_stronghold = False
    for l in s.lords.values():
        if l.side == "christian" and l.cylinder.kind == "locale":
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "muslim"
    s.meta.active_lord_id = "yusuf"
    s.meta.actions_remaining = 2
    # No M9 capability deployed -> not offered, and handler rejects.
    assert not [m for m in legal_moves(s) if m["type"] == "cmd_emir_jihad"]
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_emir_jihad", "side": "muslim",
                         "jihad_locale": tgt})
    assert ei.value.code == "no_capability"
