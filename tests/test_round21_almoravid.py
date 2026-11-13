"""Round 21 Almoravid regressions through listed actions and saved games."""

import pytest

from almoravid.actions import apply_action
from almoravid.events import held_event_ids
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder
from almoravid.views import redacted_view
from playtest_harness import Harness
from tests._plan_helpers import legal_pad
from tests.test_cross_game_avoid_retreat_surrender import reject_unchanged
from tests.test_round19_almoravid import _advance_to, _later_levy, _listed, _replay
from tests.test_round20_almoravid import _draw_events


def _play_saved(state, move, path):
    harness = Harness("scenario_a_toledo_beset")
    harness.state = state
    harness.save(path)
    restored = Harness.load(path)
    menu = harness.legal()
    assert menu == restored.legal()
    index = menu.index(move)
    result = harness.apply(index)
    assert restored.apply(index) == result
    assert state.model_dump_json() == restored.state.model_dump_json()
    assert not harness.findings and not restored.findings
    return result


def _service_markers(state, lord_id):
    return {m.vassal_id: m.box for m in state.calendar.service_markers if m.lord_id == lord_id}


@pytest.mark.parametrize(("card", "seed", "draw", "lord", "kind", "delta"), [
    ("C14", 1, ["C8", "C14"], "sancho", "play_pope_gregory", 2),
    ("C15", 11, ["C15", "C13"], "alfonso", "play_cluniacs", 1),
])
@pytest.mark.parametrize("position", ["basic", "advanced", "cap", "left_lane", "right_lane"])
def test_hold_service_shift_moves_the_lord_and_advanced_vassals(
    tmp_path, card, seed, draw, lord, kind, delta, position,
):
    state = _later_levy(seed, "christian")
    state.meta.advanced_vassal_service = position != "basic"
    _draw_events(state, draw)
    _advance_to(state, "muster", "christian")
    calendar = state.calendar
    own = next(m for m in calendar.service_markers if m.lord_id == lord and m.vassal_id is None)
    starting_box = own.box
    if position != "basic":
        for index in range(2):
            _replay(state, _listed(state, "levy_take_vassal", lord_id=lord, vassal_index=index)[0])
        # Loaders may return the Vassals before their Lord. Preserve that order.
        calendar.service_markers.remove(own)
        if position == "cap":
            own.box = 17
        if position == "left_lane":
            calendar.off_left_service.append(lord)
            starting_box = 0
        elif position == "right_lane":
            calendar.off_right_service.append(lord)
            starting_box = 17
        else:
            calendar.service_markers.append(own)
            starting_box = own.box
    before = _service_markers(state, lord)
    others = [m.model_dump() for m in calendar.service_markers if m.lord_id != lord]
    [move] = _listed(state, kind, lord_id=lord, mode="service_shift_right")
    result = _play_saved(state, move, tmp_path / "pending.json")
    expected = {vid: box + delta for vid, box in before.items() if vid is not None}
    expected[None] = min(17, starting_box + delta)
    assert result["new_service_box"] == expected[None]
    assert _service_markers(state, lord) == expected
    assert [m.model_dump() for m in calendar.service_markers if m.lord_id != lord] == others
    assert lord not in calendar.off_left_service and lord not in calendar.off_right_service
    assert card not in held_event_ids(state, "christian")
    assert state.decks.discard.count(card) == 1 and move not in legal_moves(state)
    reject_unchanged(state, move, "card_not_held")


@pytest.mark.parametrize(("starting_box", "legacy_lane", "expected"), [
    (1, False, 0),
    (17, True, 15),
])
def test_pope_gregory_can_shift_service_left(tmp_path, starting_box, legacy_lane, expected):
    state = _later_levy(1, "christian")
    state.meta.advanced_vassal_service = True
    _draw_events(state, ["C8", "C14"])
    _advance_to(state, "muster", "christian")
    _replay(state, _listed(state, "levy_take_vassal", lord_id="sancho", vassal_index=0)[0])
    calendar = state.calendar
    own = next(m for m in calendar.service_markers if m.lord_id == "sancho" and m.vassal_id is None)
    if legacy_lane:
        calendar.service_markers.remove(own)
        calendar.off_right_service.append("sancho")
    else:
        own.box = starting_box
    [move] = _listed(state, "play_pope_gregory", lord_id="sancho", mode="service_shift_left")
    result = _play_saved(state, move, tmp_path / "pending.json")
    assert result["new_service_box"] == expected
    markers = _service_markers(state, "sancho")
    assert markers["sancho_v1"] == 2
    assert markers.get(None) == (expected or None)
    assert ("sancho" in calendar.off_left_service) == (expected == 0)
    assert "sancho" not in calendar.off_right_service


def test_vassal_marker_alone_does_not_qualify_the_lord_for_a_shift():
    state = _later_levy(11, "christian")
    state.meta.advanced_vassal_service = True
    _draw_events(state, ["C15", "C13"])
    _advance_to(state, "muster", "christian")
    _replay(state, _listed(state, "levy_take_vassal", lord_id="alfonso", vassal_index=0)[0])
    state.calendar.service_markers = [
        m for m in state.calendar.service_markers
        if m.lord_id != "alfonso" or m.vassal_id is not None
    ]
    move = {"type": "play_cluniacs", "side": "christian", "lord_id": "alfonso",
            "mode": "service_shift_right"}
    assert move not in legal_moves(state)
    reject_unchanged(state, move, "no_service_marker")


def _avoid_decision(bearer):
    state = _later_levy(0, "muslim")
    state.meta.hidden_mats = True
    _draw_events(state, ["M4", "M3"])
    _advance_to(state, "muster", "christian")
    if bearer is not None:
        _replay(state, _listed(state, "levy_take_capability", lord_id=bearer, card_id="C10")[0])
    # Stage the defenders' map positions and a load for Alfonso to leave as Spoils.
    state.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="jerez")
    state.lords["alfonso"].assets["loot"] = 1
    state.lords["garcia_ordonez"].cylinder = Cylinder(kind="locale", locale_id="jerez")
    state.meta.phase, state.meta.levy_step = "campaign", None
    apply_action(state, {"type": "begin_campaign"})
    apply_action(state, {"type": "plan_add_card", "side": "muslim",
                         "plan_kind": "command", "lord_id": "al_mutamid"})
    for side in ("christian", "muslim"):
        legal_pad(state, side)
        apply_action(state, {"type": "finalize_plan", "side": side})
    for side in ("christian", "muslim"):
        apply_action(state, {"type": "command_reveal", "side": side})
    _replay(state, _listed(state, "cmd_march", target_locale_id="jerez", way_type="road")[0])
    while state.pending and state.pending.kind in ("swollen_river_march", "arid_terrain_choice"):
        _replay(state, _listed(state, state.pending.kind, play=False)[0])
    assert state.pending.kind == "march_arrival_response"
    [avoid] = _listed(state, "respond_avoid_battle", target_locale_id="algeciras", way_type="road")
    # The public action permits selecting a subset of the defenders.
    _replay(state, {**avoid, "lord_ids": ["alfonso"]})
    assert state.pending.kind == "swollen_river_block"
    return state


@pytest.mark.parametrize(("bearer", "play", "avoids"), [
    ("alfonso", True, True),
    ("garcia_ordonez", True, True),
    ("pedro_ansurez", True, False),
    (None, True, False),
    ("alfonso", False, True),
])
def test_swollen_river_checks_adalides_at_the_avoid_origin(tmp_path, bearer, play, avoids):
    state = _avoid_decision(bearer)
    [move] = _listed(state, "respond_swollen_river_block", play=play,
                     interactive_concede=True if play else None)
    reject_unchanged(state, {**move, "side": "christian"}, "not_responder")
    result = _play_saved(state, move, tmp_path / "pending.json")
    assert "M4" in held_event_ids(state, "muslim")
    assert ("M3" in held_event_ids(state, "muslim")) == (not play)
    assert state.decks.discard.count("M3") == int(play)
    if avoids:
        assert result["avoided_to"] == "algeciras" and result["lord_ids"] == ["alfonso"]
        assert result.get("swollen_river_cancelled") == ("M3" if play else None)
        assert result["discarded_as_spoils"] == {"loot": 1}
        assert result["spoils_distribution"] == {"al_mutamid": {"loot": 1}}
        assert "loot" not in state.lords["alfonso"].assets
        assert state.lords["alfonso"].moved_fought
        assert state.lords["alfonso"].cylinder.locale_id == "algeciras"
        assert state.pending.kind == "march_arrival_response"
        assert state.pending.payload["defender_lord_ids"] == ["garcia_ordonez"]
        if bearer:
            assert redacted_view(state, "muslim")["lords"][bearer]["capabilities"] is None
    else:
        assert result["swollen_river_played"] == "M3"
        assert state.pending.kind == "combat_holds"
        assert state.lords["alfonso"].cylinder.locale_id == "jerez"
        assert state.lords["alfonso"].assets["loot"] == 1
