"""Self-play driver for Almoravid.

Drives a single playthrough end-to-end using a greedy priority-weighted
agent. Designed for both interactive use and the sweep in
self_play_sweep.py.

Strategy:
  1. Get legal_moves(state).
  2. Pick the highest-priority action type that has at least one move.
  3. Within that type, prefer moves that haven't been repeated recently
     (anti-loop). The anti-loop counter penalizes a (type, lord_id,
     locale_id) signature each time it's chosen.
  4. apply_action; on IllegalAction try the next best move.
  5. Stop on phase=ended OR max_steps OR repeated stall.

CROSS_PROJECT_LESSONS §4: this is the 'greedy' agent style — finds
the no-target-no-op family and lifecycle leaks. A future 'strategic'
agent style with combat preference would surface different bugs.

Usage:
  python scripts/self_play.py --scenario scenario_a_toledo_beset --seed 1
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

# Allow direct execution from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from almoravid.actions import IllegalAction, apply_action  # noqa: E402
from almoravid.legal_moves import legal_moves  # noqa: E402
from almoravid.scenarios import list_scenarios, load_scenario  # noqa: E402
from almoravid.state import GameState  # noqa: E402


# Priority weights for action selection. Higher = preferred. Tuned so
# the agent makes "progress" actions first and falls back to fillers
# only when nothing better is available.
_PRIORITY = {
    # Lifecycle / progress
    "begin_levy": 100,
    "begin_campaign": 100,
    "finalize_plan": 95,
    "command_reveal": 92,
    "end_card": 75,
    "end_campaign": 100,
    "pass_step": 60,

    # Levy actions
    "muster_lord": 80,
    "pay_lord": 50,
    "disband_lord": 30,
    "levy_take_vassal": 75,
    "levy_take_capability": 70,
    "aow_shuffle": 65,
    "aow_draw": 60,

    # Campaign commands
    "cmd_march": 70,
    "cmd_supply": 65,
    "cmd_forage": 60,
    "cmd_tax": 55,
    "cmd_ravage": 50,
    "cmd_siege": 45,
    "cmd_storm": 40,
    "cmd_sally": 40,
    "cmd_battle": 35,
    "cmd_pass": 20,

    # Plan-step filler — pick command entries over passes when offered
    "plan_add_card": 50,  # tie-broken below
}


def _signature(move: dict[str, Any]) -> tuple:
    """Loose identity tuple for anti-loop tracking."""
    return (
        move.get("type"),
        move.get("lord_id"),
        move.get("target_locale_id"),
        move.get("source_seat"),
    )


def step_self_play(
    scenario: str,
    *,
    seed: int = 1,
    max_steps: int = 20_000,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run one playthrough. Returns a summary dict."""
    state = load_scenario(scenario, seed=seed)
    sig_counts: Counter = Counter()
    action_type_counts: Counter = Counter()
    repeats = 0
    steps_taken = 0

    for step in range(max_steps):
        if state.meta.phase == "ended":
            break
        moves = legal_moves(state)
        if not moves:
            return _result(state, scenario, seed, steps_taken,
                            action_type_counts, status="no_legal_moves",
                            details={"phase": state.meta.phase,
                                     "levy_step": state.meta.levy_step,
                                     "campaign_step": state.meta.campaign_step,
                                     "active": state.meta.active_player})

        # Order moves by priority and anti-loop penalty.
        def _score(m):
            base = _PRIORITY.get(m["type"], 0)
            penalty = sig_counts.get(_signature(m), 0) * 5
            # Within plan_add_card, prefer 'command' over 'pass'
            if m.get("type") == "plan_add_card":
                if m.get("plan_kind") == "pass":
                    base -= 3
            return base - penalty
        moves.sort(key=_score, reverse=True)

        chosen = None
        last_err: Exception | None = None
        for m in moves:
            try:
                # Use a sentinel: try apply on the actual state. On
                # IllegalAction, move to the next candidate.
                apply_action(state, m)
                chosen = m
                break
            except IllegalAction as e:
                last_err = e
                continue
        if chosen is None:
            return _result(state, scenario, seed, steps_taken,
                            action_type_counts, status="enumerator_handler_mismatch",
                            details={"last_error": str(last_err) if last_err else None,
                                     "tried": [m["type"] for m in moves]})
        sig_counts[_signature(chosen)] += 1
        action_type_counts[chosen["type"]] += 1
        steps_taken += 1
        if sig_counts[_signature(chosen)] > 200:
            repeats += 1
            if repeats > 5:
                return _result(state, scenario, seed, steps_taken,
                                action_type_counts, status="loop_detected",
                                details={"signature": list(_signature(chosen))})
        if verbose and step % 50 == 0:
            print(f"  step {step:5d}: phase={state.meta.phase} "
                  f"levy={state.meta.levy_step} "
                  f"campaign={state.meta.campaign_step} "
                  f"active={state.meta.active_player} "
                  f"chose {chosen['type']}", file=sys.stderr)

    return _result(state, scenario, seed, steps_taken, action_type_counts,
                    status=("completed" if state.meta.phase == "ended"
                            else "max_steps_reached"))


def _result(state: GameState, scenario: str, seed: int, steps: int,
             counts: Counter, *, status: str,
             details: dict | None = None) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "seed": seed,
        "status": status,
        "steps": steps,
        "final_phase": state.meta.phase,
        "final_box": state.calendar.current_box,
        "final_vp_christian": state.score.christian,
        "final_vp_muslim": state.score.muslim,
        "action_counts": dict(counts.most_common()),
        "details": details or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="scenario_a_toledo_beset",
                        choices=list_scenarios())
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=20_000)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    try:
        result = step_self_play(args.scenario, seed=args.seed,
                                 max_steps=args.max_steps,
                                 verbose=args.verbose)
    except Exception as e:
        result = {"scenario": args.scenario, "seed": args.seed,
                  "status": "driver_exception",
                  "exception_type": type(e).__name__,
                  "exception_msg": str(e)[:300],
                  "traceback": traceback.format_exc(limit=20)}
    print(json.dumps(result, indent=2))
    # Non-zero exit if the harness crashed (driver_exception) — agent
    # gaps are zero-exit because they're not bugs.
    return 1 if result.get("status") == "driver_exception" else 0


if __name__ == "__main__":
    sys.exit(main())
