"""Repeated Sagrajas play using the harness, not a separate combat model.

Run: python scripts/sagrajas_study.py --n 2000 --workers 4
All tactical cells use battle.resolve_battle; default/option cells also
exercise actions.apply_action. Round-1/2 schedules are precommitted choices.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from almoravid.actions import apply_action  # noqa: E402
from almoravid.battle import battleside_for_lords, resolve_battle  # noqa: E402
from almoravid.scenarios import load_scenario  # noqa: E402


def configurations():
    cells = []
    for role in ("attack", "defend"):
        for hidden, service in [(False, False), (True, False),
                                (False, True), (True, True)]:
            cells.append(dict(name=f"{role}_default_h{int(hidden)}v{int(service)}",
                              role=role, public=True, hidden=hidden, service=service))
        # Factorial: each side independently chooses how to absorb Hits.
        for c in ("weakest_first", "armored_first"):
            for m in ("weakest_first", "armored_first"):
                cells.append(dict(name=f"{role}_soak_{c[0]}{m[0]}", role=role,
                                  c_policy=c, m_policy=m))
        # Change one tactic from the weak/weak default at a time.
        cells.extend([
            dict(name=f"{role}_javelins_r2", role=role, javelins=2),
            dict(name=f"{role}_wall_r2", role=role, wall=2),
            dict(name=f"{role}_both_r2", role=role, javelins=2, wall=2),
            dict(name=f"{role}_africans_front", role=role, africans_front=True),
            dict(name=f"{role}_pedro_front", role=role, pedro_front=True),
            dict(name=f"{role}_bowmen_front", role=role, bowmen_front=True),
        ])
    return cells


def template(cfg):
    s = load_scenario("sagrajas")
    s.meta.hidden_mats = cfg.get("hidden", False)
    s.meta.advanced_vassal_service = cfg.get("service", False)
    apply_action(s, {"type": f"sagrajas_{cfg['role']}", "side": "christian"})
    s.meta.absorption_policy = {"christian": cfg.get("c_policy", "weakest_first"),
                                "muslim": cfg.get("m_policy", "weakest_first")}
    # Background Book p46: Bowmen can go on any TWO Christian Lords.
    if cfg.get("bowmen_front"):
        s.lords["sancho"].capabilities.remove("C5")
        s.lords["garcia_ordonez"].capabilities.append("C5")
        for card in s.decks.capabilities_in_play:
            if card.card_id == "C5":
                card.owner_lord_id = "garcia_ordonez"
    return s


def play(s, cfg, seed, trace=False):
    s = s.model_copy(deep=True)
    s.meta.seed = seed
    if cfg.get("public"):
        result = apply_action(s, {"type": "resolve_battle", "side": s.pending.waiting_on})
        return dict(seed=seed, winner=result["winner"], rounds=result["rounds"],
                    c_unrouted=sum(sum(lord.forces.values()) for lord in s.lords.values()
                                   if lord.side == "christian"),
                    m_unrouted=sum(sum(lord.forces.values()) for lord in s.lords.values()
                                   if lord.side == "muslim"), dice=s.meta.rng_state)
    rosters = {side: [lid for lid, lord in s.lords.items()
                      if lord.side == side and lord.cylinder.kind == "locale"]
               for side in ("christian", "muslim")}
    if cfg.get("africans_front"):
        rosters["muslim"] = ["yusuf", "sir", "al_mutamid", "abd_allah", "al_mutawakkil"]
    if cfg.get("pedro_front"):
        rosters["christian"] = ["alfonso", "alvar_fanez", "pedro_ansurez",
                                  "garcia_ordonez", "sancho"]
    attacking = "christian" if cfg["role"] == "attack" else "muslim"
    defending = "muslim" if attacking == "christian" else "christian"
    atk = battleside_for_lords(s, rosters[attacking], attacking, "attacker",
                               active_lord_id="alfonso" if attacking == "christian" else "yusuf")
    dfd = battleside_for_lords(s, rosters[defending], defending, "defender")
    mus = atk if attacking == "muslim" else dfd
    mus.m7_round = cfg.get("wall", 1)
    # Delay only the African Lords' own Javelins; Christian/Harbah timing stays R1.
    for lp in mus.array:
        if lp.lord_id in ("yusuf", "sir"):
            lp.javelin_round = cfg.get("javelins", 1)
    result = resolve_battle(s, atk, dfd)
    by_side = {atk.side: atk, dfd.side: dfd}
    row = dict(seed=seed, winner=result.winner, rounds=len(result.rounds),
               c_unrouted=by_side["christian"].total_unrouted(),
               m_unrouted=by_side["muslim"].total_unrouted(), dice=s.meta.rng_state)
    if trace:
        row["round_details"] = [asdict(r) for r in result.rounds]
    return row


def batch(args):
    cfg, seeds = args
    s = template(cfg)
    return cfg["name"], [play(s, cfg, seed) for seed in seeds]


def wilson(wins, n):
    z = 1.959963984540054
    p = wins / n
    den = 1 + z*z/n
    mid = (p + z*z/(2*n)) / den
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return [mid-half, mid+half]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed-start", type=int, default=10000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "studies/sagrajas")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    configs = configurations()
    seeds = range(args.seed_start, args.seed_start + args.n)
    results = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for name, rows in pool.map(batch, [(cfg, seeds) for cfg in configs]):
            results[name] = rows
            print(f"{name}: C {sum(r['winner']=='christian' for r in rows)}/{args.n}", flush=True)
    summaries = {}
    for name, rows in results.items():
        wins = sum(r["winner"] == "christian" for r in rows)
        assert all(r["winner"] in ("christian", "muslim") for r in rows)
        summaries[name] = dict(n=len(rows), christian_wins=wins,
                               christian_rate=wins/len(rows), ci95=wilson(wins, len(rows)),
                               mean_rounds=statistics.mean(r["rounds"] for r in rows),
                               median_rounds=statistics.median(r["rounds"] for r in rows),
                               mean_c_unrouted=statistics.mean(r["c_unrouted"] for r in rows),
                               mean_m_unrouted=statistics.mean(r["m_unrouted"] for r in rows))
    # Exact same-seed equivalence for public action vs internal driver and all options.
    for role in ("attack", "defend"):
        base = results[f"{role}_default_h0v0"]
        assert base == results[f"{role}_soak_ww"]
        for hidden, service in [(1,0), (0,1), (1,1)]:
            assert base == results[f"{role}_default_h{hidden}v{service}"]
    effects = {}
    for name, rows in results.items():
        role = name.split("_")[0]
        ref = results[f"{role}_default_h0v0"]
        delta = [int(r["winner"]=="christian") - int(b["winner"]=="christian")
                 for r,b in zip(rows, ref, strict=True)]
        mean = statistics.mean(delta)
        se = statistics.stdev(delta)/math.sqrt(len(delta)) if len(delta)>1 else 0
        effects[name] = dict(delta_c_win=mean, paired_ci95=[mean-1.96*se, mean+1.96*se],
                              changed_winners=sum(d != 0 for d in delta))
    output = dict(n_per_cell=args.n, seed_start=args.seed_start,
                   configurations=configs, summary=summaries, effects=effects)
    (args.out / "results.json").write_text(json.dumps(output, indent=2)+"\n")
    with (args.out / "battles.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=["configuration", *next(iter(results.values()))[0]])
        writer.writeheader()
        for name, rows in results.items():
            writer.writerows(dict(configuration=name, **row) for row in rows)
    examples = {}
    cfg = next(c for c in configs if c["name"] == "attack_soak_ww")
    for seed in seeds:
        r = play(template(cfg), cfg, seed, trace=True)
        examples.setdefault(r["winner"], r)
        if len(examples) == 2:
            break
    (args.out / "examples.json").write_text(json.dumps(examples, indent=2)+"\n")


if __name__ == "__main__":
    main()
