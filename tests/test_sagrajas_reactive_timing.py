"""The follow-up uses the harness, with legal decisions before future dice."""
import importlib.util
from pathlib import Path

import almoravid.battle as battle

STUDY = Path(__file__).resolve().parents[1] / "scripts/sagrajas_reactive_study.py"
spec = importlib.util.spec_from_file_location("reactive_study", STUDY)
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


def test_undecided_timing_survives_snapshot():
    side = battle.BattleSide(side="muslim", role="defender", lord_ids=["sir"],
                             forces={"african_horse": 1},
                             oneround_round=None, m7_round=None)
    restored = battle.battle_side_from_snapshot(battle.battle_side_to_snapshot(side))
    assert restored.oneround_round is None
    assert restored.m7_round is None


def test_reserves_fire_once_on_actual_entry_not_round_one():
    cs, ms = study.profiles()
    c, m = cs[0], ms[0]
    s = study.prepare(c, m)
    for seed in range(20):
        row = study.play(s, c, m, seed, trace=True)
        for lord in ("yusuf", "sir"):
            fires = [x for x in row["decisions"] if x.get("lord") == lord]
            assert len(fires) == 1
            assert fires[0]["round"] == row[f"{lord}_entry"] >= 2
            assert fires[0]["position"] in study.FRONT
            assert fires[0]["step"] == "1.a"
        wall = [x for x in row["decisions"] if x["kind"] == "spear_wall"]
        assert len(wall) <= 1
        if wall:
            assert wall[0]["round"] >= 2
            assert wall[0]["step"] == "2.b"
            assert set(wall[0]["lords"]) <= study.AFRICANS


def test_wall_declared_before_horse_gets_protection_that_step(monkeypatch):
    cs, ms = study.profiles()
    ctrl = study.ReactiveTiming()
    s = study.prepare(cs[0], ms[0])
    atk = battle.battleside_for_lords(s, cs[0]["order"], "christian", "attacker")
    dfd = battle.battleside_for_lords(s, ms[0]["order"], "muslim", "defender")
    atk.oneround_round = dfd.oneround_round = dfd.m7_round = None
    original = battle._resolve_step
    observed = []

    def observe(state, step, *args, **kwargs):
        rnd = kwargs["round_index"]
        active = "M7" in state.decks.this_levy_events.get("muslim", [])
        observed.append((rnd, step, active))
        if step == "2.b" and ctrl.wall_used and rnd == dfd.m7_round:
            assert active
        return original(state, step, *args, **kwargs)

    monkeypatch.setattr(battle, "_resolve_step", observe)
    battle.resolve_battle(s, atk, dfd, before_strike=ctrl)
    assert ctrl.wall_used
    assert not any(active for rnd, _, active in observed if rnd == 1)
    assert not any(active for rnd, _, active in observed if rnd > dfd.m7_round)
    assert "M7" not in s.decks.this_levy_events.get("muslim", [])


def test_observing_callback_preserves_previous_default_outcomes():
    cs, ms = study.profiles()
    for seed in (3, 25, 67):
        before = study.old_play(study.template({"role": "attack"}), {"role": "attack"}, seed)
        after = study.play(study.prepare(cs[0], ms[0]), cs[0], ms[0], seed, "none")
        assert before == {key: after[key] for key in before}


def test_conditional_absorption_changes_only_the_protected_horse_step(monkeypatch):
    cs, ms = study.profiles()
    guarded = dict(ms[0], absorb="wall_guard")
    original = battle._resolve_step
    guarded_steps = []

    def observe(state, step, *args, **kwargs):
        policy = state.meta.absorption_policy["muslim"]
        if policy == "armored_first":
            assert step == "2.b"
            assert "M7" in state.decks.this_levy_events.get("muslim", [])
            guarded_steps.append(kwargs["round_index"])
        else:
            assert policy == "weakest_first"
        return original(state, step, *args, **kwargs)

    monkeypatch.setattr(battle, "_resolve_step", observe)
    study.play(study.prepare(cs[0], guarded), cs[0], guarded, 0)
    assert len(guarded_steps) == 1
    assert guarded_steps[0] >= 2
