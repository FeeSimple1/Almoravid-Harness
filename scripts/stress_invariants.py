"""Invariant-checked self-play stress harness.

A deeper companion to self_play.py / self_play_sweep.py. Where those drive a
single greedy agent and flag harness-level failures, this:

  1. Offers several agent *profiles* (weighted-random move preferences) so
     different regions of the state space get exercised:
       - "survival": keep Lords alive, progress the sequence, reach the late
         game (e.g. Scenario F's Winter sequence around box 7-8);
       - "combat":   prefer Battle / Storm / Sally / Siege and inject the
         opt-in interactive_concede flag so the round-stepped combat drivers
         run;
       - "siege":    keep Lords alive AND maintain Sieges, to reach the
         Winter Siege interactive sequence with active sieges.
  2. Asserts a battery of STATE INVARIANTS after every applied action, and
     checks that legal_moves() never raises. Any violation, handler crash,
     or enumerator/handler mismatch is reported with the triggering move and
     the recent action history (a reproducer).

Exit code is non-zero if any session ends in a failure status, so this is
usable as a CI smoke gate.

Usage:
  python scripts/stress_invariants.py --scenario scenario_f_reconquista \
      --profile siege --seeds 1-10
"""

from __future__ import annotations

import argparse
import json
import random
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

_VALID_CYLINDER_KINDS = {
    "locale", "calendar", "mat", "removed", "set_aside", "off_left",
}
_SIDES = ("christian", "muslim")

# Per-profile action-type weights (higher = preferred). Unlisted types get a
# small default so they are still occasionally chosen.
_PROFILES: dict[str, dict[str, int]] = {
    "survival": {
        "begin_levy": 100, "begin_campaign": 100, "finalize_plan": 95,
        "command_reveal": 90, "end_campaign": 95, "end_card": 40,
        "pass_step": 55, "muster_lord": 95, "levy_take_vassal": 80,
        "levy_take_capability": 75, "aow_shuffle": 65, "aow_draw": 60,
        "pay_lord": 70, "disband_lord": 5, "cmd_march": 55, "cmd_supply": 60,
        "cmd_forage": 55, "cmd_tax": 45, "cmd_ravage": 35, "cmd_siege": 40,
        "cmd_storm": 35, "cmd_sally": 35, "cmd_battle": 30, "cmd_pass": 15,
        "plan_add_card": 50,
    },
    "combat": {
        "begin_levy": 100, "begin_campaign": 100, "finalize_plan": 95,
        "command_reveal": 90, "end_campaign": 80, "end_card": 30,
        "pass_step": 40, "muster_lord": 85, "levy_take_vassal": 70,
        "levy_take_capability": 65, "aow_shuffle": 60, "aow_draw": 55,
        "pay_lord": 55, "disband_lord": 5, "cmd_march": 80, "cmd_battle": 95,
        "cmd_storm": 92, "cmd_sally": 92, "cmd_siege": 85,
        "respond_stand_battle": 95, "battle_concede": 90, "storm_concede": 85,
        "relief_concede": 85, "besiege_or_bypass": 70, "respond_besiege": 70,
        "cmd_supply": 45, "cmd_forage": 40, "cmd_tax": 35, "cmd_ravage": 60,
        "cmd_pass": 15, "plan_add_card": 50,
    },
    "siege": {
        "begin_levy": 100, "begin_campaign": 100, "finalize_plan": 95,
        "command_reveal": 90, "end_campaign": 85, "end_card": 35,
        "pass_step": 50, "muster_lord": 95, "levy_take_vassal": 80,
        "levy_take_capability": 72, "aow_shuffle": 60, "aow_draw": 55,
        "pay_lord": 75, "disband_lord": 3, "cmd_march": 62, "cmd_supply": 65,
        "cmd_forage": 55, "cmd_tax": 45, "cmd_ravage": 58, "cmd_siege": 90,
        "cmd_storm": 8, "cmd_sally": 40, "cmd_battle": 25, "cmd_pass": 15,
        "plan_add_card": 50, "respond_stand_battle": 60, "battle_concede": 70,
        "winter_siege_action": 80, "winter_siege_pay": 70,
        "respond_besiege": 85, "respond_bypass": 20,
    },
}

# Action types that accept the opt-in reactive Concede driver; the combat /
# siege profiles inject it sometimes to exercise the round-stepped path.
_INTERACTIVE_CONCEDE = ("cmd_battle", "cmd_storm", "respond_stand_battle")

_FAILURE_STATUSES = {
    "invariant_violation", "handler_crash", "legal_moves_raised",
    "enumerator_handler_mismatch", "no_legal_moves", "driver_exception",
}


def check_invariants(state: GameState) -> list[str]:
    """Return a list of invariant-violation messages (empty if healthy)."""
    errs: list[str] = []
    for lid, lord in state.lords.items():
        for key, val in lord.assets.items():
            if isinstance(val, int) and val < 0:
                errs.append(f"negative asset {lid}.{key}={val}")
        for key, val in lord.forces.items():
            if isinstance(val, int) and val < 0:
                errs.append(f"negative force {lid}.{key}={val}")
        kind = lord.cylinder.kind
        if kind not in _VALID_CYLINDER_KINDS:
            errs.append(f"bad cylinder kind {lid}={kind}")
        if (kind == "calendar" and lord.cylinder.box is not None
                and not 1 <= lord.cylinder.box <= 17):
            errs.append(f"calendar box out of range {lid}={lord.cylinder.box}")
        if kind == "locale" and lord.cylinder.locale_id not in state.locales:
            errs.append(f"unknown locale {lid}={lord.cylinder.locale_id}")
    # Advanced Vassal Service (3.4.2): Vassal markers must be in range and
    # not reference an off-map / removed Lord whose own marker is gone.
    if state.meta.advanced_vassal_service:
        for marker in state.calendar.service_markers:
            vid = getattr(marker, "vassal_id", None)
            if vid is None:
                continue
            if (marker.box is not None and not 0 <= marker.box <= 17):
                errs.append(f"vassal marker box out of range "
                            f"{marker.lord_id}/{vid}={marker.box}")
    # At most one (Lord, not Vassal) Service marker per Lord.
    marker_counts: Counter = Counter()
    for marker in state.calendar.service_markers:
        if getattr(marker, "vassal_id", None) is None:
            marker_counts[marker.lord_id] += 1
    for lid, count in marker_counts.items():
        if count > 1:
            errs.append(f"duplicate service marker {lid} x{count}")
    for lid, loc in state.locales.items():
        for field in ("siege_yellow", "siege_green"):
            val = getattr(loc, field, 0)
            if not 0 <= val <= 4:
                errs.append(f"siege marker out of range {lid}.{field}={val}")
        if getattr(loc, "ravaged", "none") not in ("none", "yellow", "green"):
            errs.append(f"bad ravaged state {lid}={loc.ravaged}")
    for side in _SIDES:
        score = getattr(state.score, side)
        if score != score or abs(score) > 1e6:  # NaN or runaway
            errs.append(f"insane score {side}={score}")
    if (state.pending is not None
            and state.pending.waiting_on not in _SIDES):
        errs.append(f"pending waiting_on={state.pending.waiting_on}")
    if not 1 <= state.calendar.current_box <= 17:
        errs.append(f"current_box out of range={state.calendar.current_box}")
    return errs


def run_playthrough(
    scenario: str,
    *,
    seed: int = 1,
    profile: str = "survival",
    max_steps: int = 25_000,
    inject_interactive: bool = True,
    meta_opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Drive one invariant-checked playthrough. Returns a summary dict whose
    `status` is 'completed', 'max_steps', or one of the failure statuses.
    `meta_opts` sets GameState.meta fields after load (e.g.
    advanced_vassal_service=True) so optional rules can be stress-tested."""
    weights = _PROFILES[profile]
    # Deterministic, reproducible RNG: a STABLE per-profile offset
    # (never hash(), which Python salts per process).
    profile_offset = {"survival": 0, "combat": 1, "siege": 2}.get(profile, 9)
    rng = random.Random(seed * 104_729 + profile_offset * 7_919 + 3)
    state = load_scenario(scenario, seed=seed)
    if meta_opts:
        for _k, _v in meta_opts.items():
            setattr(state.meta, _k, _v)
    pending_census: Counter = Counter()
    action_census: Counter = Counter()
    recent: list[str] = []
    max_box = state.calendar.current_box

    for step in range(max_steps):
        if state.meta.phase == "ended":
            return _summary(state, scenario, seed, profile, "completed", step,
                            max_box, action_census, pending_census)
        if state.pending is not None:
            pending_census[state.pending.kind] += 1
        try:
            moves = legal_moves(state)
        except Exception as exc:  # noqa: BLE001
            return _summary(state, scenario, seed, profile, "legal_moves_raised",
                            step, max_box, action_census, pending_census,
                            extra={"error": repr(exc),
                                   "traceback": traceback.format_exc(limit=15),
                                   "recent": recent[-20:]})
        if not moves:
            return _summary(state, scenario, seed, profile, "no_legal_moves",
                            step, max_box, action_census, pending_census,
                            extra={"levy_step": state.meta.levy_step,
                                   "campaign_step": state.meta.campaign_step,
                                   "active": state.meta.active_player,
                                   "pending": (state.pending.kind
                                               if state.pending else None),
                                   "recent": recent[-20:]})
        moves.sort(key=lambda m: weights.get(m["type"], 10) + rng.random() * 8,
                   reverse=True)

        applied: dict[str, Any] | None = None
        rejected: list[tuple[str, str | None]] = []
        for move in moves:
            candidate = dict(move)
            if (inject_interactive and move["type"] in _INTERACTIVE_CONCEDE
                    and rng.random() < 0.6):
                candidate["interactive_concede"] = True
            try:
                apply_action(state, candidate)
                applied = candidate
                break
            except IllegalAction as exc:
                rejected.append((move["type"], getattr(exc, "code", None)))
                continue
            except Exception as exc:  # noqa: BLE001
                return _summary(state, scenario, seed, profile, "handler_crash",
                                step, max_box, action_census, pending_census,
                                extra={"move": candidate, "error": repr(exc),
                                       "traceback": traceback.format_exc(limit=20),
                                       "recent": recent[-20:]})
        if applied is None:
            return _summary(state, scenario, seed, profile,
                            "enumerator_handler_mismatch", step, max_box,
                            action_census, pending_census,
                            extra={"levy_step": state.meta.levy_step,
                                   "campaign_step": state.meta.campaign_step,
                                   "rejected": rejected[:30],
                                   "recent": recent[-20:]})

        action_census[applied["type"]] += 1
        recent.append(applied["type"])
        max_box = max(max_box, state.calendar.current_box)
        violations = check_invariants(state)
        if violations:
            return _summary(state, scenario, seed, profile,
                            "invariant_violation", step, max_box,
                            action_census, pending_census,
                            extra={"move": applied,
                                   "violations": violations[:12],
                                   "recent": recent[-20:]})

    return _summary(state, scenario, seed, profile, "max_steps", max_steps,
                    max_box, action_census, pending_census)


def _summary(state: GameState, scenario: str, seed: int, profile: str,
             status: str, steps: int, max_box: int, actions: Counter,
             pendings: Counter, *, extra: dict[str, Any] | None = None,
             ) -> dict[str, Any]:
    out: dict[str, Any] = {
        "scenario": scenario, "seed": seed, "profile": profile,
        "status": status, "steps": steps, "max_box": max_box,
        "final_phase": state.meta.phase,
        "vp": [state.score.christian, state.score.muslim],
        "pending_kinds": dict(pendings),
        "action_counts": dict(actions.most_common()),
    }
    if extra:
        out.update(extra)
    return out


def _parse_seeds(spec: str) -> list[int]:
    seeds: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            seeds.extend(range(int(lo), int(hi) + 1))
        elif part:
            seeds.append(int(part))
    return seeds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="scenario_f_reconquista",
                        choices=list_scenarios())
    parser.add_argument("--profile", default="all",
                        choices=[*_PROFILES, "all"])
    parser.add_argument("--seeds", default="1-5",
                        help="e.g. '1-10' or '1,3,7'")
    parser.add_argument("--max-steps", type=int, default=25_000)
    parser.add_argument("--json", action="store_true",
                        help="emit one JSON object per session")
    args = parser.parse_args()

    seeds = _parse_seeds(args.seeds)
    profiles = list(_PROFILES) if args.profile == "all" else [args.profile]
    status_counts: Counter = Counter()
    failures: list[dict[str, Any]] = []

    for profile in profiles:
        for seed in seeds:
            try:
                result = run_playthrough(args.scenario, seed=seed,
                                         profile=profile,
                                         max_steps=args.max_steps)
            except Exception as exc:  # noqa: BLE001
                result = {"scenario": args.scenario, "seed": seed,
                          "profile": profile, "status": "driver_exception",
                          "error": repr(exc),
                          "traceback": traceback.format_exc(limit=15)}
            status_counts[result["status"]] += 1
            if result["status"] in _FAILURE_STATUSES:
                failures.append(result)
            if args.json:
                print(json.dumps(result))
            else:
                print(f"  {profile:<9} seed {seed:<4} -> {result['status']:<28}"
                      f" box={result.get('max_box')} steps={result.get('steps')}")

    if not args.json:
        print(f"\n=== stress summary ({sum(status_counts.values())} sessions) ===")
        for status, count in status_counts.most_common():
            print(f"  {status:<30} {count}")
        if failures:
            print(f"\n!!! {len(failures)} FAILURE(S) !!!")
            for fail in failures[:5]:
                print(f"  {fail['profile']} seed={fail['seed']}: "
                      f"{fail['status']} — "
                      f"{fail.get('violations') or fail.get('error') or fail.get('rejected')}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
