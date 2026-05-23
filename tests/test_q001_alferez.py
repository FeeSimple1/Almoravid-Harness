"""Q-001 resolution: Alférez (C15 Capability half) wired correctly.

Adjudication: scope = this_lord (the cards-data 'side_wide' was the bug);
eligible bearers = a FIXED set of four Christian captains {Pedro Ansúrez,
García Ordóñez, Álvar Fáñez, Rodrigo Campeador} (Arts of War ref C15/C8/C24
'Lords.' line; not a Command-rating predicate). The bearer may spend 1
Command action to stack/unstack as a Lieutenant outside the Plan step
(4.1.3 exception).
"""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.capabilities import (CHRISTIAN_CAPTAINS_FOUR,
                                    capability_eligible_lords,
                                    lord_has_capability)
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def test_c15_scope_is_this_lord_and_eligibility_is_the_four_captains() -> None:
    from almoravid.static_data import load_cards
    assert load_cards()["cards"]["C15"]["capability_scope"] == "this_lord"
    assert capability_eligible_lords("C15") == CHRISTIAN_CAPTAINS_FOUR
    # Shared with C8 Hueste and C24 García Jiménez (identical card lists).
    assert capability_eligible_lords("C8") == CHRISTIAN_CAPTAINS_FOUR
    assert capability_eligible_lords("C24") == CHRISTIAN_CAPTAINS_FOUR
    # Rodrigo eligibility binds to the Christian (Campeador) cylinder only.
    assert "rodrigo_campeador" in CHRISTIAN_CAPTAINS_FOUR
    assert "rodrigo_al_sayyid" not in CHRISTIAN_CAPTAINS_FOUR


def test_levy_offers_c15_only_to_eligible_captains() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    # García & Pedro (captains) start at Sahagún (Friendly); Alfonso too.
    assert [m for m in legal_moves(s) if m["type"] == "levy_take_capability"
            and m["card_id"] == "C15" and m["lord_id"] == "garcia_ordonez"]
    assert not [m for m in legal_moves(s) if m["type"] == "levy_take_capability"
                and m["card_id"] == "C15" and m["lord_id"] == "alfonso"]


def test_levy_take_c15_rejected_for_non_captain_handler() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "levy_take_capability", "side": "christian",
                         "lord_id": "alfonso", "card_id": "C15"})
    assert ei.value.code == "lord_not_eligible"


def _bearer_with_alferez(commander_at_same=True):
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    av = s.lords["alvar_fanez"]                 # an eligible captain
    av.capabilities.append("C15")
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C15", scope="this_lord", owner_side="christian",
        owner_lord_id="alvar_fanez"))
    av.cylinder = Cylinder(kind="locale", locale_id="toledo")
    av.in_stronghold = False
    if commander_at_same:
        g = s.lords["garcia_ordonez"]
        g.cylinder = Cylinder(kind="locale", locale_id="toledo")
        g.in_stronghold = False
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alvar_fanez"
    s.meta.actions_remaining = 2
    return s


def test_alferez_toggle_stack_then_unstack_offered_and_applies() -> None:
    s = _bearer_with_alferez()
    assert lord_has_capability(s, "alvar_fanez", "C15")
    stack = [m for m in legal_moves(s) if m["type"] == "toggle_lieutenant"]
    assert stack == [{"type": "toggle_lieutenant", "side": "christian",
                      "mode": "stack", "commander_id": "garcia_ordonez"}]
    apply_action(s, stack[0])
    assert s.lords["alvar_fanez"].lieutenant_of == "garcia_ordonez"
    # Now stacked -> only unstack is offered.
    unstk = [m for m in legal_moves(s) if m["type"] == "toggle_lieutenant"]
    assert unstk == [{"type": "toggle_lieutenant", "side": "christian",
                      "mode": "unstack"}]
    apply_action(s, unstk[0])
    assert s.lords["alvar_fanez"].lieutenant_of is None


def test_alferez_not_offered_to_alfonso_marshal_as_target() -> None:
    # Marshal (Alfonso) cannot be a Lieutenant/Lower Lord (4.1.3), so the
    # bearer may not stack onto him even when co-located.
    s = _bearer_with_alferez(commander_at_same=False)
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="toledo")
    s.lords["alfonso"].in_stronghold = False
    targets = [m.get("commander_id") for m in legal_moves(s)
               if m["type"] == "toggle_lieutenant" and m["mode"] == "stack"]
    assert "alfonso" not in targets
