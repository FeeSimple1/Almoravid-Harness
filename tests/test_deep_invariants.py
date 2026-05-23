"""Deep invariant sweep (CI-sized). Drives greedy AND random self-play
across scenarios/seeds and asserts state invariants after EVERY action —
catches silent corruption a plain completion sweep misses. The full
260-session version lives in the manual deep-test; this is the fast gate.
"""
from __future__ import annotations

import random

import pytest

from almoravid.scenarios import load_scenario, list_scenarios
from almoravid.legal_moves import legal_moves
from almoravid.actions import apply_action, IllegalAction

_PRI = {"begin_levy": 100, "begin_campaign": 100, "finalize_plan": 95,
        "command_reveal": 92, "end_card": 75, "end_campaign": 100,
        "muster_lord": 80, "cmd_march": 70, "pass_step": 60}


def _invariants(s) -> list[str]:
    errs = []
    for lid, l in s.lords.items():
        if l.cylinder.kind == "locale" and l.cylinder.locale_id not in s.locales:
            errs.append(f"{lid}: bad locale")
        if any(v < 0 for v in l.forces.values()):
            errs.append(f"{lid}: negative forces")
        if any(v < 0 for v in l.assets.values()):
            errs.append(f"{lid}: negative assets")
        if len(l.capabilities) > 2:
            errs.append(f"{lid}: >2 this-lord caps")
    for lid, loc in s.locales.items():
        if not (0 <= loc.siege_yellow <= 4) or not (0 <= loc.siege_green <= 4):
            errs.append(f"{lid}: siege out of range")
        if loc.conquered_markers and loc.jihad_markers:
            errs.append(f"{lid}: both Conquered AND Jihad")
        if loc.ravaged not in ("none", "yellow", "green"):
            errs.append(f"{lid}: bad ravaged")
    for m in s.calendar.service_markers:
        if not (0 <= m.box <= 17):
            errs.append(f"svc {m.lord_id} out of range")
    if s.taifas_box_coin < 0 or s.taifas_box_vp < 0 or s.meta.actions_remaining < 0:
        errs.append("negative counter")
    if s.pending is not None and s.pending.waiting_on != s.meta.active_player:
        errs.append("pending/active desync")
    # P-3 (Retreat-relocation bug class): no two opposing FIELD Lords
    # (both OUTSIDE a Stronghold) may share a Locale. Besieged-inside vs
    # besiegers-outside is legal (the inside Lord is in_stronghold). An
    # Approach (march_arrival_response) co-locates Lords transiently until
    # the defender Avoids/Withdraws/Stands, so assert only when nothing is
    # pending (settled state).
    if s.pending is None:
        by_loc: dict[str, set] = {}
        for lid, l in s.lords.items():
            if l.cylinder.kind == "locale" and not l.in_stronghold:
                by_loc.setdefault(l.cylinder.locale_id, set()).add(l.side)
        for loc_id, sides in by_loc.items():
            if "christian" in sides and "muslim" in sides:
                errs.append(f"{loc_id}: opposing field Lords co-located")
    return errs


def _drive(scenario, seed, mode, opts=None, max_steps=6000):
    s = load_scenario(scenario, seed=seed)
    if opts:
        for k, v in opts.items():
            setattr(s.meta, k, v)
    rng = random.Random(seed * 31 + (0 if mode == "greedy" else 1))
    assert not _invariants(s), f"{scenario}/{seed}: bad start state"
    for _ in range(max_steps):
        if s.meta.phase == "ended":
            break
        moves = legal_moves(s)
        assert moves, (f"{scenario}/{seed}/{mode}: zero legal moves at "
                       f"phase={s.meta.phase}")
        if mode == "greedy":
            moves.sort(key=lambda m: _PRI.get(m["type"], 0), reverse=True)
            chosen = moves[0]
        else:
            chosen = rng.choice(moves)
        try:
            apply_action(s, chosen)
        except IllegalAction as e:
            pytest.fail(f"{scenario}/{seed}/{mode}: legal_moves offered a "
                        f"rejected action {chosen.get('type')} ({e.code})")
        errs = _invariants(s)
        assert not errs, (f"{scenario}/{seed}/{mode}: invariant broken after "
                          f"{chosen.get('type')}: {errs[:3]}")


@pytest.mark.parametrize("scenario", list_scenarios())
@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("mode", ["greedy", "random"])
def test_invariants_hold_under_self_play(scenario, seed, mode) -> None:
    _drive(scenario, seed, mode)


@pytest.mark.parametrize("seed", [1, 2])
def test_invariants_with_optional_rules_on(seed) -> None:
    # Exercise Advanced Vassal Service + Hidden Mats under random play.
    _drive("scenario_f_reconquista", seed, "random",
           opts={"advanced_vassal_service": True, "hidden_mats": True})
