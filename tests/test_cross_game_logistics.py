"""ALM-03/04: mandatory event-Feed sharing and optional Unladen March."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.capabilities import effective_command
from almoravid.events import resolve_event
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, GameState, ServiceMarker


def position(lid="alfonso", locale="sahagun", actions=2):
    state = load_scenario("scenario_f_reconquista", seed=7)
    for lord in state.lords.values():
        lord.cylinder = Cylinder(kind="mat")
        lord.in_stronghold = False
        lord.lieutenant_of = None
        lord.is_lieutenant = False
        lord.assets = {}
        lord.forces = {"militia": 6}
        lord.moved_fought = False
    state.decks.held = {"christian": [], "muslim": []}
    state.decks.this_levy_events = {"christian": [], "muslim": []}
    state.decks.this_campaign_events = {"christian": [], "muslim": []}
    state.decks.capabilities_in_play = []
    state.meta.phase = "campaign"
    state.meta.campaign_step = "activation"
    state.meta.active_player = state.lords[lid].side
    state.meta.active_lord_id = lid
    state.meta.actions_remaining = actions
    state.pending = None
    place(state, lid, locale)
    enemy = "yusuf" if state.lords[lid].side == "christian" else "alfonso"
    place(state, enemy, "sevilla" if enemy == "yusuf" else "leon")
    return state


def place(state, lid, locale, **assets):
    lord = state.lords[lid]
    lord.cylinder = Cylinder(kind="locale", locale_id=locale)
    lord.assets = dict(assets)
    if not any(m.lord_id == lid and m.vassal_id is None for m in state.calendar.service_markers):
        state.calendar.service_markers.append(ServiceMarker(lord_id=lid, box=6))
    return lord


def service(state, lid):
    return next(m.box for m in state.calendar.service_markers
                if m.lord_id == lid and m.vassal_id is None)


def cap(state, cid):
    side = "muslim" if cid.startswith("M") else "christian"
    state.decks.capabilities_in_play.append(
        CardInPlay(card_id=cid, scope="side_wide", owner_side=side))


@pytest.mark.parametrize("side,first,second,event", [
    ("muslim", "yusuf", "sir", "C5"),
    ("christian", "alfonso", "garcia_ordonez", "M5"),
])
@pytest.mark.parametrize("asset", ["prov", "loot"])
@pytest.mark.parametrize("donor_first", [False, True])
def test_drought_feeds_own_forces_then_shares_before_unfed(
        side, first, second, event, asset, donor_first):
    state = position(first)
    place(state, first, "sahagun")
    place(state, second, "sahagun")
    donor = state.lords[first if donor_first else second]
    donor.assets = {asset: 2}
    before = {lid: service(state, lid) for lid in [first, second]}
    result = resolve_event(state, "christian" if side == "muslim" else "muslim", event)
    assert {x["lord_id"] for x in result["fed_lords"]} == {first, second}
    assert all(not x["unfed_penalty"] and x["consumed"] == 1 for x in result["fed_lords"])
    assert all(x["short"] == 0 for x in result["fed_lords"])
    assert donor.assets.get(asset, 0) == 0
    assert all(service(state, lid) == before[lid] for lid in before)
    assert not any(state.lords[lid].moved_fought for lid in before)


def test_drought_uses_unselected_ally_without_feeding_him():
    state = position()
    place(state, "garcia_ordonez", "sahagun")
    donor = place(state, "pedro_ansurez", "sahagun", prov=2)
    result = resolve_event(state, "muslim", "M5")
    assert {r["lord_id"] for r in result["fed_lords"]} == {"alfonso", "garcia_ordonez"}
    assert all(not r["unfed_penalty"] for r in result["fed_lords"])
    assert donor.assets["prov"] == 0 and not donor.moved_fought
    assert sum(s["amount"] for r in result["fed_lords"] for s in r["shared"]) == 2


def test_partial_shared_feed_consumes_food_and_applies_one_unfed_penalty():
    state = position()
    state.lords["alfonso"].forces = {"militia": 7}
    place(state, "garcia_ordonez", "sahagun", prov=1)
    place(state, "pedro_ansurez", "sahagun", loot=1)
    before = service(state, "alfonso")
    result = resolve_event(state, "muslim", "M5")
    alfonso = next(r for r in result["fed_lords"] if r["lord_id"] == "alfonso")
    garcia = next(r for r in result["fed_lords"] if r["lord_id"] == "garcia_ordonez")
    assert alfonso["needed"] == 2 and alfonso["consumed"] == 1 and alfonso["short"] == 1
    assert alfonso["unfed_penalty"] and not garcia["unfed_penalty"]
    assert service(state, "alfonso") == before - 1
    assert state.lords["pedro_ansurez"].assets["loot"] == 0


@pytest.mark.parametrize("donor_locale", ["leon", "sahagun"])
def test_arid_single_march_shares_only_at_destination(donor_locale):
    state = position(actions=1)
    place(state, "pedro_ansurez", donor_locale, prov=1)
    state.decks.held["muslim"] = ["M4"]
    before = service(state, "alfonso")
    result = apply_action(state, {"type": "cmd_march", "side": "christian",
                                 "target_locale_id": "leon", "way_type": "road"})
    fed = result["forced_feed"][0]
    assert fed["unfed_penalty"] == (donor_locale != "leon")
    assert service(state, "alfonso") == before - (donor_locale != "leon")
    assert state.lords["pedro_ansurez"].assets.get("prov", 0) == (donor_locale != "leon")


def test_arid_group_feeds_both_own_mats_before_sharing():
    state = position(actions=1)
    place(state, "garcia_ordonez", "sahagun", cart=2, prov=2)
    state.decks.held["muslim"] = ["M4"]
    result = apply_action(state, {"type": "cmd_march", "side": "christian",
                                 "target_locale_id": "leon", "way_type": "road",
                                 "group_lord_ids": ["garcia_ordonez"]})
    assert len(result["forced_feed"]) == 2
    assert all(r["consumed"] == 1 and not r["unfed_penalty"] for r in result["forced_feed"])
    assert state.lords["garcia_ordonez"].assets["prov"] == 0


def test_drought_cannot_share_from_enemy_or_another_locale():
    state = position()
    place(state, "garcia_ordonez", "burgos", prov=2)
    place(state, "yusuf", "sahagun", prov=2)
    result = resolve_event(state, "muslim", "M5")
    alfonso = next(r for r in result["fed_lords"] if r["lord_id"] == "alfonso")
    assert alfonso["unfed_penalty"]
    assert state.lords["yusuf"].assets["prov"] == 2


def test_one_action_march_menu_exposes_discard_and_reports_assets_lost():
    state = position(actions=1)
    state.lords["alfonso"].assets = {"loot": 1, "coin": 2}
    base = {"type": "cmd_march", "side": "christian",
            "target_locale_id": "leon", "way_type": "road"}
    discard = {**base, "discard_to_unladen": True}
    moves = legal_moves(state)
    assert discard in moves and base not in moves
    before = state.model_dump_json()
    with pytest.raises(IllegalAction, match="March costs 2"):
        apply_action(state, base)
    assert state.model_dump_json() == before
    result = apply_action(state, discard)
    assert result["cost"] == 1 and not result["laden"]
    assert result["discarded_for_march"] == {"alfonso": {"loot": 1}}
    assert state.lords["alfonso"].assets == {"coin": 2}
    assert GameState.model_validate_json(state.model_dump_json()) == state


@pytest.mark.parametrize("lid,origin,target,way,assets,camels,kept,dropped", [
    ("alfonso", "sahagun", "leon", "road", {"cart": 2, "prov": 3}, False, 2, 1),
    ("alfonso", "somosierra", "madrid", "pass", {"cart": 1, "mule": 1, "prov": 2}, False, 1, 1),
    ("alfonso", "somosierra", "madrid", "pass", {"cart": 2, "prov": 2}, False, 0, 2),
    ("yusuf", "somosierra", "madrid", "pass", {"mule": 1, "prov": 3}, True, 2, 1),
    ("alfonso", "sahagun", "leon", "road", {"prov": 1}, False, 0, 1),
])
def test_unladen_discard_respects_way_shared_capacity_and_camels(
        lid, origin, target, way, assets, camels, kept, dropped):
    state = position(lid, origin, actions=1)
    state.lords[lid].assets = assets.copy()
    if camels:
        cap(state, "M16")
    move = {"type": "cmd_march", "side": state.lords[lid].side,
            "target_locale_id": target, "way_type": way, "discard_to_unladen": True}
    if not any(assets.get(k, 0) for k in ("cart", "mule", "loot")):
        # With no Transport, ordinary March already discards all food.
        move.pop("discard_to_unladen")
    assert move in legal_moves(state)
    result = apply_action(state, move)
    assert result["cost"] == 1 and result["discarded_for_march"][lid] == {"prov": dropped}
    assert state.lords[lid].assets.get("prov", 0) == kept


def test_player_can_keep_laden_assets_or_discard_with_two_actions():
    state = position()
    state.lords["alfonso"].assets = {"loot": 1}
    base = {"type": "cmd_march", "side": "christian",
            "target_locale_id": "leon", "way_type": "road"}
    discard = {**base, "discard_to_unladen": True}
    assert base in legal_moves(state) and discard in legal_moves(state)
    control = state.model_copy(deep=True)
    assert apply_action(state, base)["cost"] == 2
    assert state.lords["alfonso"].assets["loot"] == 1
    assert apply_action(control, discard)["cost"] == 1
    assert control.lords["alfonso"].assets.get("loot", 0) == 0


def test_group_discard_includes_mandatory_lower_lord_and_shared_transport():
    state = position(actions=1)
    place(state, "garcia_ordonez", "sahagun", cart=2)
    lower = place(state, "pedro_ansurez", "sahagun", prov=3, loot=1)
    lower.lieutenant_of = "garcia_ordonez"
    move = {"type": "cmd_march", "side": "christian", "target_locale_id": "leon",
            "way_type": "road", "group_lord_ids": ["garcia_ordonez"], "discard_to_unladen": True}
    assert move in legal_moves(state)
    result = apply_action(state, move)
    assert result["discarded_for_march"] == {lower.id: {"loot": 1, "prov": 1}}
    assert lower.cylinder.locale_id == "leon" and lower.assets == {"prov": 2}


@pytest.mark.parametrize("kind", ["guadalquivir", "fleet"])
def test_special_march_menu_preserves_both_asset_choices(kind):
    state = position("al_mutamid", "sevilla")
    state.lords["al_mutamid"].assets = {"loot": 1}
    if kind == "guadalquivir":
        cap(state, "M19")
        state.meta.actions_remaining = 1
        atype = "cmd_guadalquivir"
    else:
        state.decks.held["muslim"] = ["M19"]
        state.meta.actions_remaining = effective_command(state, "al_mutamid")
        atype = "cmd_march_port_to_port"
    moves = [m for m in legal_moves(state) if m["type"] == atype]
    move = next(m for m in moves if m.get("discard_to_unladen"))
    full_card = state.meta.actions_remaining
    result = apply_action(state, move)
    assert result["discarded_for_march"] == {"al_mutamid": {"loot": 1}}
    assert result["cost"] == (full_card if kind == "fleet" else 1)


def test_swollen_river_interruption_keeps_proposed_discards():
    state = position(actions=1)
    state.lords["alfonso"].assets = {"loot": 1}
    state.decks.held["muslim"] = ["M3"]
    result = apply_action(state, {"type": "cmd_march", "side": "christian",
                                 "target_locale_id": "leon", "way_type": "road",
                                 "discard_to_unladen": True})
    assert not result["moved"] and result["swollen_river_blocked"]
    assert state.lords["alfonso"].assets["loot"] == 1
    assert state.lords["alfonso"].cylinder.locale_id == "sahagun"


@pytest.mark.parametrize("bad", ["true", 1, None])
def test_invalid_discard_flag_rejects_without_mutating_assets(bad):
    state = position()
    state.lords["alfonso"].assets = {"loot": 1}
    before = state.model_dump_json()
    with pytest.raises(IllegalAction, match="discard_to_unladen"):
        apply_action(state, {"type": "cmd_march", "side": "christian",
                             "target_locale_id": "leon", "way_type": "road",
                             "discard_to_unladen": bad})
    assert state.model_dump_json() == before


@pytest.mark.parametrize("blocked_by", ["enemy_control", "enemy_lord", "none"])
def test_muster_menu_uses_the_same_free_seat_gate_as_execution(blocked_by):
    state = position("pedro_ansurez")
    state.meta.phase = "levy"
    state.meta.levy_step = "muster"
    recruit = state.lords["garcia_ordonez"]
    recruit.cylinder = Cylinder(kind="calendar", box=state.calendar.current_box)
    seat = recruit.seats[0]
    if blocked_by == "enemy_control":
        state.locales[seat].conquered_markers = 1
    elif blocked_by == "enemy_lord":
        place(state, "yusuf", seat)
    moves = [m for m in legal_moves(state) if m["type"] == "muster_lord"
             and m["lord_id"] == recruit.id]
    assert bool(moves) == (blocked_by == "none")
    if moves:
        apply_action(state, moves[0])
