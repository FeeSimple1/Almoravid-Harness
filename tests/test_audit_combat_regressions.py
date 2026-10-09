"""Audit 01/02/09-12: combat preserves the Rules of Play 4.4/4.5 state."""

from unittest.mock import patch

import pytest

import almoravid.battle as B
from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests.test_phase7f_battle_array import _retreat_setup


def _combat_state(forces, *, side="christian", active="alfonso",
                  locale="transduero", inside=()):
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for lo in s.lords.values():
        lo.cylinder = Cylinder(kind="removed")
    for lid, units in forces.items():
        lo = s.lords[lid]
        lo.cylinder = Cylinder(kind="locale", locale_id=locale)
        lo.in_stronghold = lid in inside
        lo.forces = dict(units)
        lo.capabilities = []
        lo.routed_units = {}
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = side
    s.meta.active_lord_id = active
    s.meta.actions_remaining = 1
    return s


def _finish_interactive(s, result):
    while s.pending and s.pending.kind == "battle_concede":
        result = apply_action(s, {"type": "battle_concede",
                                 "side": s.pending.waiting_on})
    return result


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("multi_attacker", [False, True])
def test_unequal_battle_arrays_commit_casualties(interactive, multi_attacker):
    s = _combat_state({"alfonso": {"serfs": 1},
                       "alvar_fanez": {"serfs": 1},
                       "al_mustain": {"sergeants": 2}},
                      side="christian" if multi_attacker else "muslim",
                      active="alfonso" if multi_attacker else "al_mustain")
    with patch.object(B, "roll_d6", return_value=6), \
            patch("almoravid.rng.roll_d6", return_value=6):
        result = apply_action(s, {"type": "cmd_battle",
                                 "side": s.meta.active_player,
                                 "interactive_concede": interactive})
        result = _finish_interactive(s, result)
    assert result["winner"] == "muslim"
    for lid in ("alfonso", "alvar_fanez"):
        assert s.lords[lid].forces == {}
        assert s.lords[lid].routed_units == {}


@pytest.mark.parametrize("interactive", [False, True])
def test_sally_commits_every_besieger(interactive):
    s = _combat_state({"al_mustain": {"men_at_arms": 4},
                       "alfonso": {"serfs": 1},
                       "alvar_fanez": {"serfs": 1}},
                      side="muslim", active="al_mustain", locale="zaragoza",
                      inside=("al_mustain",))
    s.locales["zaragoza"].siege_yellow = 1
    with patch.object(B, "roll_d6", return_value=6), \
            patch("almoravid.rng.roll_d6", return_value=6):
        result = apply_action(s, {"type": "cmd_sally", "side": "muslim",
                                 "interactive_concede": interactive})
        result = _finish_interactive(s, result)
    assert result["winner"] == "muslim"
    for lid in ("alfonso", "alvar_fanez"):
        assert s.lords[lid].forces == {}
        assert s.lords[lid].routed_units == {}


def test_baggage_parapet_keeps_remaining_assets_and_skips_service_roll():
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    result = _retreat_setup(s)
    s.decks.this_levy_events["christian"] = ["C7"]
    with patch.object(B, "roll_d6") as roll:
        summary = B.apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry["c7_opt_out"] is True
    assert entry["spoils_lost"] == {}
    assert entry["service_shift_boxes"] == 0
    assert s.lords["alfonso"].assets == {"coin": 3, "loot": 1,
                                           "prov": 5, "mule": 1}
    assert s.lords["al_mutamid"].assets == {}
    roll.assert_not_called()


@pytest.mark.parametrize("fate", ["winner", "retreated_no_concede",
                                  "storm_attacker", "withdrew"])
def test_legacy_routed_serfs_cannot_recover(fate):
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.lords["alfonso"].forces = {}
    s.lords["alfonso"].routed_units = {"serfs": 1}
    with patch.object(B, "roll_d6", return_value=1) as roll:
        B.apply_losses_rolls(s, "alfonso", fate)
    assert s.lords["alfonso"].forces == {}
    assert s.lords["alfonso"].routed_units == {}
    roll.assert_not_called()


@pytest.mark.parametrize("actor_role", ["attacker", "defender"])
@pytest.mark.parametrize("dice,penalty", [([1, 6], 0), ([6, 1], 1)])
def test_walls_and_siegeworks_cancel_the_rolled_hit_kind(actor_role, dice, penalty):
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    target = B.BattleSide("muslim", "defender", ["al_mutamid"],
                          {"men_at_arms": 5})
    with patch.object(B, "roll_d6", side_effect=dice), \
            patch.object(B, "_resolve_protection_roll", return_value=(True, None)) as hit:
        B._apply_step_cancellation_and_hits(
            s, actor_role, target, {"crossbows": 1, "bowmen": 1}, 2,
            (1, 3), 3, "storm", None, B.StepResolution("1.b", actor_role))
    assert hit.call_count == 1
    assert hit.call_args.kwargs["striker_minus_armor"] == penalty


def test_battle_runs_past_six_rounds_until_actual_rout():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    atk = B.BattleSide("christian", "attacker", ["alfonso"], {"men_at_arms": 1})
    dfd = B.BattleSide("muslim", "defender", ["al_mutamid"], {"men_at_arms": 1})
    # Both cancel the two Hits per round for seven rounds; the next Hit
    # finally routs the attacker in round eight.
    with patch.object(B, "roll_d6", side_effect=[1] * 14 + [6]):
        result = B.resolve_battle(s, atk, dfd)
    assert len(result.rounds) == 8
    assert result.winner == "muslim"


def test_interactive_battle_offers_round_eight_and_then_concedes():
    s = _combat_state({"alfonso": {"men_at_arms": 1},
                       "al_mutamid": {"men_at_arms": 1}})
    with patch.object(B, "roll_d6", return_value=1):
        apply_action(s, {"type": "cmd_battle", "side": "christian",
                         "interactive_concede": True})
        for _ in range(7):
            move = next(m for m in legal_moves(s) if m["type"] == "battle_concede"
                        and not m.get("attacker_concede") and not m.get("defender_concede"))
            apply_action(s, move)
        assert s.pending.kind == "battle_concede"
        assert s.pending.payload["round_idx"] == 8
        assert s.meta.actions_remaining == 1
        move = next(m for m in legal_moves(s) if m["type"] == "battle_concede"
                    and m.get("attacker_concede"))
        result = apply_action(s, move)
    assert result["winner"] == "muslim"
    assert result["rounds"] == 8
    assert s.meta.actions_remaining == 0


def test_unlimited_battle_timing_menu_accepts_round_eight():
    s = _combat_state({"alfonso": {"men_at_arms": 1},
                       "al_mutamid": {"men_at_arms": 1}})
    s.decks.this_levy_events["muslim"] = ["M7"]
    apply_action(s, {"type": "cmd_battle", "side": "christian",
                     "interactive_concede": True, "interactive_timing": True})
    assert s.pending.kind == "oneround_timing"
    assert s.pending.payload["max_rounds"] is None
    assert any(m["type"] == "oneround_timing" for m in legal_moves(s))
    apply_action(s, {"type": "oneround_timing", "side": "muslim", "m7_round": 8})
    assert s.pending.kind == "battle_concede"
    assert s.pending.payload["defender"]["m7_round"] == 8


def test_multi_lord_sally_array_keeps_siegeworks_protection():
    s = _combat_state({"al_mustain": {"men_at_arms": 4},
                       "alfonso": {"serfs": 1},
                       "alvar_fanez": {"serfs": 1}})
    atk = B.battleside_for_lords(s, ["al_mustain"], "muslim", "attacker")
    dfd = B.battleside_for_lords(s, ["alfonso", "alvar_fanez"],
                                "christian", "defender", front_limit=1)
    with patch.object(B, "roll_d6", return_value=1) as roll:
        B._resolve_step(s, "2.d", "attacker", "melee", "foot", atk, dfd,
                        walls_range=(1, 1), round_index=1)
    assert roll.call_count == 4
    assert dfd.forces == {"serfs": 2}
    assert dfd.routed_units == {}


def test_relief_sally_continues_past_six_rounds():
    s = _combat_state({"alfonso": {"men_at_arms": 1},
                       "alvar_fanez": {"men_at_arms": 1},
                       "al_mutamid": {"men_at_arms": 2}}, locale="sevilla")
    s.locales["sevilla"].siege_green = 1
    with patch.object(B, "roll_d6", return_value=1):
        result, _ = B.resolve_relief_sally(
            s, ["alfonso"], ["alvar_fanez"], ["al_mutamid"],
            besieger_side="muslim", locale_id="sevilla", attacker_concede_round=8)
    assert len(result.rounds) == 8
    assert result.winner == "muslim"
