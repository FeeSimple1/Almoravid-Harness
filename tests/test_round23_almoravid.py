"""Owner-selected Ravaged placement through native Arts of War draws."""

from itertools import combinations

import pytest

from almoravid.effective import is_friendly_locale
from almoravid.map import neighbors_via
from almoravid.state import CardInPlay
from playtest_harness import Harness
from tests.test_round22_almoravid import (
    RECONQUISTA,
    TAJO,
    _advance,
    _idle_campaign,
    _moves,
    _opening,
    _reject,
    _replay,
)

PORTS = ("algeciras", "jerez", "huelva", "cartagena")
FRONTIER = (
    "gormaz", "calahorra", "jaca", "talavera", "cuenca", "guadalajara",
    "muradal", "la_mancha", "jucar", "zancara",
)
CASES = (
    ("C17", RECONQUISTA, 30, "christian", "yellow", PORTS),
    ("M24", TAJO, 8, "muslim", "green", FRONTIER),
)


def _draw_event(scenario, seed, side, card):
    harness = Harness(scenario, seed=seed)
    _opening(harness)
    _idle_campaign(harness)
    _advance(harness, lambda: harness.state.decks.pending_draw.get(side, [])[:1] == [card],
             ("aow_draw", "aow_implement_event", "pass_step"))
    assert harness.state.meta.active_player == side
    assert not harness.findings
    return harness


@pytest.fixture(params=CASES, ids=("genoa_pisa", "al_maghawir"))
def drawn_event(request):
    card, scenario, seed, side, marker, eligible = request.param
    return _draw_event(scenario, seed, side, card), card, side, marker, eligible


def test_every_ravaged_pair_is_offered_and_an_alternate_survives_reload(drawn_event, tmp_path):
    harness, card, side, marker, eligible = drawn_event
    state = harness.state
    raw = _moves(harness, "aow_implement_event")
    expected = set(combinations(eligible, 2))
    assert {(m["side"], m["card_id"]) for m in raw} == {(side, card)}
    assert len(raw) == len(expected)
    assert {tuple(m["payload"]["locale_ids"]) for m in raw} == expected
    # The validated palette actually applies every pair to a copy.
    menu = harness.legal()
    assert all(m in menu for m in raw) and not harness.findings
    chosen = eligible[-2:]
    assert chosen != eligible[:2]
    move = next(m for m in raw if m["payload"]["locale_ids"] == list(chosen))
    initial_locales = {lid: loc.ravaged for lid, loc in state.locales.items()}
    lords = {lid: lord.model_dump() for lid, lord in state.lords.items()}
    service = state.calendar.model_dump()
    score = state.score.model_dump()
    score[side] += 1
    pending = state.decks.pending_draw[side][1:]
    result = _replay(harness, move, tmp_path)
    assert result["event_result"]["ravaged"] == list(chosen)
    assert result["pending_remaining"] == pending == state.decks.pending_draw[side]
    assert state.decks.discard.count(card) == 1
    assert state.pending is None and state.meta.severed_heads_trigger is None
    assert state.meta.active_player == side and state.meta.levy_step == "arts_of_war"
    assert {lid: loc.ravaged for lid, loc in state.locales.items()} == {
        **initial_locales, **dict.fromkeys(chosen, marker),
    }
    assert {lid: lord.model_dump() for lid, lord in state.lords.items()} == lords
    assert state.calendar.model_dump() == service and state.score.model_dump() == score

    next_event = _moves(harness, "aow_implement_event")
    if card == "M24":
        assert pending == ["M12"]
        assert {m["card_id"] for m in next_event} == {"M12"}
        _replay(harness, next_event[0], tmp_path)
        assert "M12" in state.decks.held[side]
    else:
        assert not pending and not next_event


def test_invalid_ravaged_choices_reject_without_changing_the_draw(drawn_event):
    harness, card, side, marker, eligible = drawn_event
    state = harness.state
    first, second, third = eligible[:3]
    other = "muslim" if side == "christian" else "christian"
    action = {"type": "aow_implement_event", "side": side, "card_id": card}
    _reject(harness, action, "choice_required")
    _reject(harness, {**action, "side": other,
                      "payload": {"locale_ids": [first, second]}}, "not_active")
    if card == "M24":
        _reject(harness, {**action, "card_id": "M12"}, "out_of_order")
    for payload in ([], "", False, {"locale_id": first}, {"locale_ids": first},
                    {"locale_ids": [first, None]}, {"locale_ids": [first, {}]}):
        _reject(harness, {**action, "payload": payload}, "bad_arg")
    neutral = "denia"
    assert not any(is_friendly_locale(state, neutral, s) for s in ("christian", "muslim"))
    if card == "C17":
        excluded = "sevilla"
        assert state.lords["al_mutamid"].cylinder.locale_id == excluded
        assert state.locales[excluded].has_port
    else:
        excluded = "burgos"
        assert is_friendly_locale(state, excluded, "christian")
        assert not any(is_friendly_locale(state, n, "muslim")
                       for way in ("road", "pass") for n in neighbors_via(excluded, way))
    for selected in ([], [first], [first, first], [first, second, third],
                     [first, "unknown_locale"], [first, neutral], [first, excluded]):
        _reject(harness, {**action, "payload": {"locale_ids": selected}}, "bad_target")

    # A choice listed before an eligibility change must be revalidated.
    if card == "C17":
        lord = state.lords["al_mutamid"]
        lord.cylinder.locale_id = first
        lord.in_stronghold = True
        _reject(harness, {**action, "payload": {"locale_ids": [first, second]}}, "bad_target")
        lord.cylinder.locale_id = excluded
        lord.in_stronghold = False
    state.locales[first].ravaged = marker
    _reject(harness, {**action, "payload": {"locale_ids": [first, second]}}, "bad_target")
    assert all(first not in m["payload"]["locale_ids"]
               for m in _moves(harness, "aow_implement_event"))
    reversed_pair = [third, second]
    result = harness.apply({**action, "payload": {"locale_ids": reversed_pair}})
    assert result["event_result"]["ravaged"] == reversed_pair
    assert not harness.findings


@pytest.mark.parametrize("count", [0, 1, 2])
def test_forced_ravaged_outcome_has_one_action_and_bare_call_is_legal(drawn_event, count, tmp_path):
    harness, card, side, marker, eligible = drawn_event
    state = harness.state
    for lid in eligible[count:]:
        state.locales[lid].ravaged = marker
    action = {"type": "aow_implement_event", "side": side, "card_id": card}
    menu = _moves(harness, "aow_implement_event")
    selected = list(eligible[:count])
    assert menu == ([{**action, "payload": {"locale_ids": selected}}] if selected else [action])
    score = getattr(state.score, side)
    before = {lid: loc.ravaged for lid, loc in state.locales.items()}
    path = tmp_path / "forced.json"
    harness.save(path)
    loaded = Harness.load(path)
    assert loaded.legal() == harness.legal()
    bare = loaded.apply(action)["event_result"]
    listed = harness.apply(menu[0])["event_result"]
    assert bare == listed
    assert loaded.state.locales == state.locales and loaded.state.score == state.score
    assert listed.get("ravaged", []) == selected
    assert bool(listed.get("no_op")) == (count == 0)
    assert {lid: loc.ravaged for lid, loc in state.locales.items()} == {
        **before, **dict.fromkeys(selected, marker),
    }
    assert getattr(state.score, side) == score + 0.5 * count
    assert state.decks.discard.count(card) == 1


def test_caballeria_villana_blocks_all_al_maghawir_choices(tmp_path):
    harness = _draw_event(TAJO, 8, "muslim", "M24")
    state = harness.state
    # Stage the blocking Capability while keeping one copy of the card.
    for zone in (state.decks.draw, state.decks.discard):
        if "C19" in zone:
            zone.remove("C19")
    state.decks.board_edge.setdefault("christian", []).append("C19")
    state.decks.capabilities_in_play.append(
        CardInPlay(card_id="C19", scope="side_wide", owner_side="christian"),
    )
    action = {"type": "aow_implement_event", "side": "muslim", "card_id": "M24"}
    assert _moves(harness, "aow_implement_event") == [action]
    _reject(harness, {**action, "payload": {"locale_ids": ["jucar", "zancara"]}}, "bad_target")
    score_before = state.score.model_dump()
    ravaged_before = {lid: loc.ravaged for lid, loc in state.locales.items()}
    result = _replay(harness, action, tmp_path)
    assert result["event_result"]["no_op"]
    assert result["event_result"]["note"] == "blocked by C19 Caballeria Villana"
    assert state.score.model_dump() == score_before
    assert {lid: loc.ravaged for lid, loc in state.locales.items()} == ravaged_before
    assert result["pending_remaining"] == ["M12"]
