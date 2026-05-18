"""Strategic agent — combat-weighted self-play.

Per CROSS_PROJECT_LESSONS §4: the greedy agent avoids combat; the
strategic agent leans into it, so it exercises cmd_battle / cmd_storm
/ cmd_sally / cmd_siege paths that greedy skips. Different bug class.

Same step_self_play shape as scripts/self_play.py with different
priority weights.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from almoravid.actions import IllegalAction, apply_action  # noqa: E402
from almoravid.legal_moves import legal_moves  # noqa: E402
from almoravid.scenarios import list_scenarios, load_scenario  # noqa: E402
from almoravid.state import GameState  # noqa: E402


# Strategic priorities — combat first, then progress, then filler.
_PRIORITY = {
    # Combat — highest priority when available
    "cmd_battle": 95,
    "cmd_storm": 92,
    "cmd_sally": 90,
    "cmd_siege": 88,
    "cmd_ravage": 80,

    # Aggressive movement
    "cmd_march": 78,

    # Asset building
    "cmd_supply": 60,
    "cmd_forage": 58,
    "cmd_tax": 55,

    # Lifecycle / progress (only fires when no aggressive option)
    "begin_levy": 100,
    "begin_campaign": 100,
    "finalize_plan": 65,
    "command_reveal": 65,
    "end_card": 45,
    "end_campaign": 100,
    "pass_step": 30,

    # Levy actions
    "muster_lord": 70,
    "pay_lord": 25,
    "disband_lord": 15,
    "levy_take_vassal": 65,
    "levy_take_capability": 60,
    "aow_shuffle": 50,
    "aow_draw": 45,

    "plan_add_card": 35,
    "cmd_pass": 5,
}


def _signature(move: dict[str, Any]) -> tuple:
    return (
        move.get("type"),
        move.get("lord_id"),
        move.get("target_locale_id"),
        move.get("source_seat"),
    )


def step_strategic(scenario: str, *, seed: int = 1,
                    max_steps: int = 20_000, verbose: bool = False
                    ) -> dict[str, Any]:
    state = load_scenario(scenario, seed=seed)
    sig_counts: Counter = Counter()
    action_type_counts: Counter = Counter()
    steps_taken = 0
    loop_repeats = 0

    for step in range(max_steps):
        if state.meta.phase == "ended":
            break
        moves = legal_moves(state)
        if not moves:
            return _result(state, scenario, seed, steps_taken,
                            action_type_counts,
                            status="no_legal_moves",
                            details={"phase": state.meta.phase,
                                     "levy_step": state.meta.levy_step,
                                     "campaign_step": state.meta.campaign_step,
                                     "active": state.meta.active_player})

        def _score(m):
            base = _PRIORITY.get(m["type"], 0)
            penalty = sig_counts.get(_signature(m), 0) * 5
            # Plan: prefer command entries for OWN side over passes,
            # and prefer Lords that aren't already in the plan
            if m.get("type") == "plan_add_card":
                if m.get("plan_kind") == "pass":
                    base -= 5
                else:
                    # Bonus for commanding Marshals (Yusuf, Alfonso) — they
                    # get more actions per card.
                    if m.get("lord_id") in ("yusuf", "alfonso"):
                        base += 3
            return base - penalty
        moves.sort(key=_score, reverse=True)

        chosen = None
        last_err = None
        for m in moves:
            try:
                apply_action(state, m)
                chosen = m
                break
            except IllegalAction as e:
                last_err = e
                continue
        if chosen is None:
            return _result(state, scenario, seed, steps_taken,
                            action_type_counts,
                            status="enumerator_handler_mismatch",
                            details={"last_error": str(last_err) if last_err else None,
                                     "tried": [m["type"] for m in moves]})

        sig_counts[_signature(chosen)] += 1
        action_type_counts[chosen["type"]] += 1
        steps_taken += 1
        if sig_counts[_signature(chosen)] > 300:
            loop_repeats += 1
            if loop_repeats > 5:
                return _result(state, scenario, seed, steps_taken,
                                action_type_counts,
                                status="loop_detected",
                                details={"signature": list(_signature(chosen))})
        if verbose and step % 50 == 0:
            print(f"  step {step:5d}: phase={state.meta.phase} "
                  f"levy={state.meta.levy_step} "
                  f"campaign={state.meta.campaign_step} "
                  f"active={state.meta.active_player} "
                  f"chose {chosen['type']}({chosen.get('lord_id') or ''})",
                  file=sys.stderr)

    return _result(state, scenario, seed, steps_taken, action_type_counts,
                    status=("completed" if state.meta.phase == "ended"
                            else "max_steps_reached"))


def _result(state, scenario, seed, steps, counts, *, status, details=None):
    return {
        "scenario": scenario, "seed": seed,
        "status": status, "steps": steps,
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
        result = step_strategic(args.scenario, seed=args.seed,
                                 max_steps=args.max_steps,
                                 verbose=args.verbose)
    except Exception as e:
        result = {"scenario": args.scenario, "seed": args.seed,
                  "status": "driver_exception",
                  "exception_type": type(e).__name__,
                  "exception_msg": str(e)[:300],
                  "traceback": traceback.format_exc(limit=20)}
    print(json.dumps(result, indent=2))
    return 1 if result.get("status") == "driver_exception" else 0


if __name__ == "__main__":
    sys.exit(main())
