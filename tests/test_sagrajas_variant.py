"""Integration checks for the user-authorized BGG Sagrajas variant."""
from collections import Counter

import pytest
from typer.testing import CliRunner

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (
    _build_c8_ctx,
    _build_strike_rows_for_position,
    battleside_for_lords,
)
from almoravid.cli import app
from almoravid.legal_moves import legal_moves
from almoravid.render import render_summary
from almoravid.scenarios import list_campaign_scenarios, list_scenarios, load_scenario
from almoravid.state import GameState


def test_variant_setup_and_muslim_parity():
    assert "sagrajas_variant" in list_scenarios()
    assert "sagrajas_variant" not in list_campaign_scenarios()
    s = load_scenario("sagrajas_variant")
    original = load_scenario("sagrajas")
    christians = {lid: lord for lid, lord in s.lords.items()
                  if lord.side == "christian" and lord.cylinder.kind == "locale"}
    assert set(christians) == {"alfonso", "garcia_ordonez", "pedro_ansurez"}
    total = Counter()
    for lord in christians.values():
        total.update(lord.forces)
        assert not lord.capabilities and not lord.vassals
    assert total == {"knights": 7, "sergeants": 6, "light_horse": 2,
                     "men_at_arms": 9, "militia": 1}
    assert s.lords["alfonso"].forces == {
        "knights": 3, "sergeants": 2, "men_at_arms": 3, "militia": 1}
    for lid in ("garcia_ordonez", "pedro_ansurez"):
        assert s.lords[lid].forces == {
            "knights": 2, "sergeants": 2, "light_horse": 1, "men_at_arms": 3}
    for lid, lord in s.lords.items():
        if lord.side == "muslim":
            assert lord == original.lords[lid]
    assert s.decks.this_levy_events == {"christian": ["C8"], "muslim": ["M7"]}
    assert [c.card_id for c in s.decks.capabilities_in_play] == ["M4", "M5"]
    assert not s.decks.board_edge.get("christian")
    atk = battleside_for_lords(s, list(christians), "christian", "attacker",
                               active_lord_id="alfonso")
    assert all(lp.position != "reserve" for lp in atk.array)
    for lp in atk.array:
        assert all(row.kind == "melee"
                   for row in _build_strike_rows_for_position(s, atk, lp))


@pytest.mark.parametrize("action_type", ["sagrajas_attack", "sagrajas_defend"])
def test_variant_cannot_gain_standard_role_bonuses(action_type):
    s = load_scenario("sagrajas_variant")
    before = s.model_dump()
    assert legal_moves(s) == [{"type": "resolve_battle", "side": "christian"}]
    with pytest.raises(IllegalAction, match="Who-Attacks"):
        apply_action(s, {"type": action_type, "side": "christian"})
    assert s.model_dump() == before


@pytest.mark.parametrize("seed", [0, 1, 2, 13, 25])
@pytest.mark.parametrize("options", [False, True])
def test_variant_saved_game_resolves_with_optional_rules(seed, options):
    s = load_scenario("sagrajas_variant", seed=seed)
    s.meta.hidden_mats = options
    s.meta.advanced_vassal_service = options
    restored = GameState.model_validate_json(s.model_dump_json())
    assert restored.meta.cantador_lord_id == "alfonso"
    assert "GermanBrau1 variant" in render_summary(restored)
    action = {"type": "resolve_battle", "side": "christian"}
    result = apply_action(restored, action)
    assert result == apply_action(s, action)
    assert restored.model_dump() == s.model_dump()
    assert result["winner"] in ("christian", "muslim")
    assert restored.meta.phase == "ended" and restored.pending is None
    assert restored.meta.cantador_lord_id is None
    assert not legal_moves(restored)
    assert {lord.side for lord in restored.lords.values()
            if lord.cylinder.kind == "locale"} <= {result["winner"]}


def test_cantador_stays_with_alfonso_even_when_another_lord_is_stronger():
    s = load_scenario("sagrajas_variant")
    atk = battleside_for_lords(s, ["alfonso", "garcia_ordonez", "pedro_ansurez"],
                               "christian", "attacker", active_lord_id="alfonso")
    dfd = battleside_for_lords(s, ["al_mutamid", "yusuf"], "muslim", "defender")
    atk.array[0].forces = {"knights": 1}
    assert _build_c8_ctx(s, atk, dfd, 1)["holder_id"] == id(atk.array[0])
    atk.array[0].position = "routed"
    assert _build_c8_ctx(s, atk, dfd, 1)["budget"] == 0


def test_variant_cli_round_trip(tmp_path):
    runner = CliRunner()
    state_file = tmp_path / "variant.json"
    action_file = tmp_path / "action.json"
    assert "sagrajas_variant" in runner.invoke(app, ["scenarios"]).stdout
    result = runner.invoke(app, ["new", "sagrajas_variant", "--seed", "13",
                                 "--output", str(state_file)])
    assert result.exit_code == 0, result.output
    view = runner.invoke(app, ["view", str(state_file)])
    assert view.exit_code == 0 and "unofficial" in view.stdout
    action_file.write_text('{"type": "resolve_battle", "side": "christian"}')
    result = runner.invoke(app, ["do", str(state_file), str(action_file)])
    assert result.exit_code == 0, result.output
    state = GameState.model_validate_json(state_file.read_text())
    assert state.meta.phase == "ended"
    assert state.meta.scenario_id == "sagrajas_variant"


def test_original_setup_is_isolated_from_variant():
    before = load_scenario("sagrajas", seed=13)
    load_scenario("sagrajas_variant", seed=13)
    assert load_scenario("sagrajas", seed=13).model_dump() == before.model_dump()
    assert before.meta.cantador_lord_id is None
    assert before.meta.sagrajas_role is None
    assert len([lord for lord in before.lords.values()
                if lord.side == "christian" and lord.cylinder.kind == "locale"]) == 5
