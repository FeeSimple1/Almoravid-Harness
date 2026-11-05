"""ALM-05 regressions for Capability troop loss and immediate 1.6 Disband."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction
from almoravid.capabilities import discard_capability
from almoravid.state import CardInPlay, GameState, ServiceMarker
from almoravid.views import redacted_view
from tests._reset_helpers import apply_action_keeping_reset_cards as apply_action
from tests.test_cross_game_logistics import place, position

CARDS = [("M15", "men_at_arms"), ("M20", "knights")]


def attach(state, lid, card, forces):
    lord = state.lords[lid]
    lord.capabilities.append(card)
    state.decks.draw = [c for c in state.decks.draw if c != card]
    state.decks.discard = [c for c in state.decks.discard if c != card]
    state.decks.capabilities_in_play.append(
        CardInPlay(card_id=card, scope="this_lord", owner_side=lord.side, owner_lord_id=lid)
    )
    state.meta.aow_cap_state[card + "_units"] = {"lord": lid, **forces}
    state.meta.aow_cap_state[card + "_used"] = True


def empty_position(card="M15", unit="men_at_arms", *, ally=True):
    state = position("al_mutamid", "sevilla")
    state.meta.campaign_step = "end_campaign"
    state.meta.active_lord_id = None
    state.calendar.current_box = 2
    for locale in state.locales.values():
        locale.ravaged = "none"
    lord = state.lords["al_mutamid"]
    lord.forces = {unit: 2}
    lord.routed_units = {}
    lord.capabilities = []
    lord.assets = {"prov": 2}
    lord.in_stronghold = False
    state.locales["sevilla"].seat_marker_lord_ids.append(lord.id)
    state.taifas["sevilla"].status = "independent"
    if ally:
        place(state, "yusuf", "tangier")
    attach(state, lord.id, card, {unit: 2})
    return state


def begin_wastage(state):
    result = apply_action(state, {"type": "end_campaign", "interactive_wastage": True})
    assert result["pending"] == "wastage_choice"
    assert state.pending.waiting_on == "muslim"


def discard_personal_card(state, card="M15", **extra):
    return apply_action(
        state,
        {
            "type": "wastage_choice",
            "side": "muslim",
            "discards": {"al_mutamid": {"capability": card}, **extra},
        },
    )


@pytest.mark.parametrize("card,unit", CARDS)
def test_public_wastage_disbands_the_last_capability_troops_with_all_cleanup(card, unit):
    state = empty_position(card, unit)
    lord = state.lords["al_mutamid"]
    rating = lord.service_rating
    score = state.score.christian
    begin_wastage(state)
    discard_personal_card(state, card)
    assert lord.cylinder.kind == "calendar" and lord.cylinder.box == 3 + rating
    assert not lord.forces and not lord.assets and not lord.capabilities and not lord.vassals
    assert lord.id not in state.locales["sevilla"].seat_marker_lord_ids
    assert not any(m.lord_id == lord.id for m in state.calendar.service_markers)
    assert card + "_units" not in state.meta.aow_cap_state
    assert card + "_used" not in state.meta.aow_cap_state
    assert state.decks.discard.count(card) == 1
    assert not any(c.card_id == card for c in state.decks.capabilities_in_play)
    assert state.taifas["sevilla"].status == "parias" and state.score.christian == score + 1
    assert state.lords["alfonso"].assets["coin"] == rating
    assert state.meta.phase == "levy" and state.calendar.current_box == 3
    before = state.model_dump_json()
    discard_capability(state, card)
    assert state.model_dump_json() == before


@pytest.mark.parametrize("card,unit", CARDS)
@pytest.mark.parametrize("phase", ["levy", "campaign"])
@pytest.mark.parametrize("box", [2, 15])
def test_empty_lord_uses_at_limit_placement_even_with_expired_service(card, unit, phase, box):
    state = empty_position(card, unit)
    state.meta.phase = phase
    state.calendar.current_box = box
    state.calendar.service_markers = [ServiceMarker(lord_id="al_mutamid", box=1)]
    lord = state.lords["al_mutamid"]
    discard_capability(state, card)
    target = box + lord.service_rating + int(phase == "campaign")
    assert lord.cylinder.kind == "calendar" and lord.cylinder.box == min(target, 17)
    assert (lord.id in state.calendar.off_right) == (target > 16)
    assert state.meta.phase == phase


@pytest.mark.parametrize("card,unit", CARDS)
@pytest.mark.parametrize("survivor", ["regular", "routed"])
def test_a_surviving_force_keeps_the_lord_mustered(card, unit, survivor):
    state = empty_position(card, unit)
    lord = state.lords["al_mutamid"]
    if survivor == "regular":
        lord.forces["militia"] = 1
    else:
        lord.routed_units["militia"] = 1
    before = state.calendar.model_dump()
    discard_capability(state, card)
    assert lord.cylinder.kind == "locale" and state.calendar.model_dump() == before
    assert state.taifas["sevilla"].status == "independent"
    assert sum(lord.forces.values()) + sum(lord.routed_units.values()) == 1


@pytest.mark.parametrize("card,unit", CARDS)
@pytest.mark.parametrize("beyond", [False, True])
def test_an_explicit_disband_does_not_reenter_capability_disband(card, unit, beyond):
    state = empty_position(card, unit)
    state.meta.phase = "levy"
    state.meta.levy_step = "service_disband"
    state.meta.active_player = "muslim"
    state.calendar.service_markers = [ServiceMarker(lord_id="al_mutamid", box=1 if beyond else 2)]
    result = apply_action(
        state, {"type": "disband_lord", "side": "muslim", "lord_id": "al_mutamid"}
    )
    assert result["permanent"] == beyond
    assert state.lords["al_mutamid"].cylinder.kind == ("removed" if beyond else "calendar")
    assert state.decks.discard.count(card) == 1
    assert sum(h.action == "disband_lord" for h in state.history) == 1


def test_milites_discard_preserves_its_printed_troop_exception():
    state = empty_position("C18", "knights")
    lord = state.lords["al_mutamid"]
    before = dict(lord.forces)
    discard_capability(state, "C18")
    assert lord.forces == before and lord.cylinder.kind == "locale"
    assert "C18" in state.decks.removed_from_game


@pytest.mark.parametrize(
    "card,lid,locale", [("C13", "sancho", "jaca"), ("M23", "al_mustain", "zaragoza")]
)
def test_count_contingent_removal_uses_the_same_empty_lord_rule(card, lid, locale):
    state = empty_position()
    lord = place(state, lid, locale)
    lord.forces = {"knights": 1, "men_at_arms": 1}
    lord.capabilities = []
    attach(state, lid, card, dict(lord.forces))
    state.meta.count_of_barcelona_side = lord.side
    discard_capability(state, card)
    assert lord.cylinder.kind == "calendar" and not lord.forces
    assert state.meta.count_of_barcelona_side is None
    assert state.decks.discard.count(card) == 1


@pytest.mark.parametrize("card,unit", CARDS)
def test_last_mustered_lord_loss_ends_campaign_before_calendar_advance(card, unit):
    state = empty_position(card, unit, ally=False)
    begin_wastage(state)
    result = discard_personal_card(state, card)
    assert state.meta.phase == "ended" and state.calendar.current_box == 2
    assert result["victory"]["winner"] == "christian"
    assert state.pending is None


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("choice", ["remove", "add"])
def test_wastage_preserves_neutrality_choice_and_resumes_once_after_save_load(interactive, choice):
    state = empty_position()
    lord = state.lords["al_mutamid"]
    lord.in_stronghold = True
    place(state, "alfonso", "sevilla")
    state.locales["sevilla"].siege_yellow = 1
    state.locales["sevilla"].jihad_markers = 0
    state.locales["sevilla"].conquered_markers = 0
    state.lords["yusuf"].assets = {"prov": 3}
    if interactive:
        begin_wastage(state)
        discard_personal_card(state, yusuf={"asset": "prov"})
    else:
        # The default picks the last personal card when no Asset stack is >1.
        lord.assets = {}
        attach(state, lord.id, "M1", {})
        apply_action(state, {"type": "end_campaign"})
    assert state.pending.kind == "neutrality_choice" and state.pending.waiting_on == "christian"
    assert state.calendar.current_box == 2 and state.meta.active_player == "christian"
    assert state.lords["yusuf"].assets["prov"] == 3
    public = redacted_view(state, "christian")
    assert "_wastage_resume" not in public["pending"]["payload"]
    assert "_end_campaign_resume" not in public["pending"]["payload"]
    saved = state.model_dump_json()
    state = GameState.model_validate_json(saved)
    apply_action(
        state,
        {"type": "respond_neutrality_choice", "side": "christian", "choices": {"sevilla": choice}},
    )
    assert state.pending is None and state.meta.phase == "levy"
    assert state.calendar.current_box == 3
    assert state.lords["yusuf"].assets["prov"] == 2
    assert state.locales["sevilla"].siege_yellow == int(choice == "add")
    assert state.locales["sevilla"].jihad_markers == (3 if choice == "add" else 0)


def test_invalid_later_discard_is_rejected_before_a_political_pause():
    state = empty_position()
    state.lords["al_mutamid"].in_stronghold = True
    place(state, "alfonso", "sevilla")
    state.locales["sevilla"].siege_yellow = 1
    state.lords["yusuf"].assets = {"prov": 3}
    begin_wastage(state)
    before = state.model_dump_json()
    with pytest.raises(IllegalAction):
        discard_personal_card(state, yusuf={"asset": "cart"})
    assert state.model_dump_json() == before
    assert state.lords["al_mutamid"].cylinder.kind == "locale"
