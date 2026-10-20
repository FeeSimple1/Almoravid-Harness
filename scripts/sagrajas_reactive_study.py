"""Historical-reserve follow-up using the existing Almoravid battle engine.

python scripts/sagrajas_reactive_study.py --train-n 100 --test-n 3000 --workers 4
No combat rules or dice rolls are reproduced here: only player choices,
experiment orchestration, and statistical summaries.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sagrajas_study import play as old_play  # noqa: E402
from sagrajas_study import template, wilson  # noqa: E402

from almoravid.battle import (  # noqa: E402
    _pick_flank_target,
    battleside_for_lords,
    resolve_battle,
)

FRONT = {"front_center", "front_left", "front_right"}
AFRICANS = {"yusuf", "sir"}
HORSE = {"knights", "sergeants", "light_horse", "african_horse"}


class ReactiveTiming:
    """Use only current armies and step: no GameState, seed, or RNG access."""

    def __init__(self, javelins=True, wall=True):
        self.javelins = javelins
        self.wall = wall
        self.used = set()
        self.wall_used = False
        self.entries = {}
        self.decisions = []

    def __call__(self, atk, dfd, rnd, step):
        # All experiments are the historical Christians-attack branch.
        assert atk.side == "christian" and dfd.side == "muslim"
        for side in (atk, dfd):
            for lp in side.array:
                if lp.position in FRONT and lp.has_unrouted():
                    self.entries.setdefault(lp.lord_id, rnd)
        if self.javelins and step in ("1.a", "1.b"):
            actor, target = (dfd, atk) if step == "1.a" else (atk, dfd)
            if any(p.position in FRONT and p.has_unrouted() for p in target.array):
                for lp in actor.array:
                    if (lp.position not in FRONT or not lp.has_unrouted()
                            or lp.lord_id in self.used):
                        continue
                    has_jav = lp.forces.get("african_horse", 0) > 0 or (
                        set(lp.capabilities_in_play) & {"C7", "M3", "M6"}
                        and any(lp.forces.get(u, 0) for u in
                                ("militia", "light_horse", "serfs")))
                    if has_jav:
                        lp.javelin_round = rnd
                        self.used.add(lp.lord_id)
                        self.decisions.append(dict(kind="javelins", lord=lp.lord_id,
                                                   round=rnd, step=step, position=lp.position))
        # M7 can be declared after Missiles, just before Christian Horse.
        if self.wall and not self.wall_used and dfd.m7_owned and step == "2.b":
            threatened = set()
            for lp in atk.array:
                if lp.position not in FRONT or not any(lp.forces.get(u, 0) for u in HORSE):
                    continue
                target = next((p for p in dfd.array if p.position == lp.position
                               and p.has_unrouted()), None)
                if target is None:
                    target = _pick_flank_target(dfd, lp.position)
                if (target is not None and target.m7_marked
                        and (target.forces.get("african_foot", 0)
                             + target.forces.get("men_at_arms", 0)) > 0):
                    threatened.add(target.lord_id)
            if threatened:
                dfd.m7_round = rnd
                self.wall_used = True
                self.decisions.append(dict(kind="spear_wall", lords=sorted(threatened),
                                           round=rnd, step=step))


def profiles():
    christians, muslims = [], []
    # The same five Lords and forces throughout; Alfonso remains front center.
    orders = [
        ["alfonso", "alvar_fanez", "garcia_ordonez", "pedro_ansurez", "sancho"],
        ["alfonso", "alvar_fanez", "pedro_ansurez", "garcia_ordonez", "sancho"],
        ["alfonso", "pedro_ansurez", "garcia_ordonez", "alvar_fanez", "sancho"],
    ]
    for oi, order in enumerate(orders):
        for bow in ("default", "front"):
            for absorb in ("weakest_first", "armored_first"):
                christians.append(dict(id=f"c{oi}_{bow}_{absorb[0]}", order=order,
                                       bow=bow, absorb=absorb))
    # EVERY Muslim profile retains all Taifas in Front and both Africans in Reserve.
    taifas = ["abd_allah", "al_mutawakkil", "al_mutamid"]
    for pi, front in enumerate(itertools.permutations(taifas)):
        for reserve in (["yusuf", "sir"], ["sir", "yusuf"]):
            for absorb in ("weakest_first", "armored_first"):
                muslims.append(dict(id=f"m{pi}_{reserve[0]}_{absorb[0]}",
                                    order=[*front, *reserve], absorb=absorb))
    return christians, muslims


def prepare(c, m):
    s = template({"role": "attack"})
    s.meta.absorption_policy = {
        "christian": c["absorb"],
        "muslim": "weakest_first" if m["absorb"] == "wall_guard" else m["absorb"],
    }
    s.meta.array_reserve_priority = {"christian": c["order"][3:], "muslim": m["order"][3:]}
    if c["bow"] == "front":
        candidates = c["order"][1:3]
        target = max(candidates, key=lambda lid: sum(s.lords[lid].forces.get(ut, 0)
                     for ut in ("men_at_arms", "militia", "light_horse", "serfs")))
        s.lords["sancho"].capabilities.remove("C5")
        s.lords[target].capabilities.append("C5")
        for card in s.decks.capabilities_in_play:
            if card.card_id == "C5":
                card.owner_lord_id = target
    return s


def play(prepared, c, m, seed, timing="both", trace=False):
    s = prepared.model_copy(deep=True)
    s.meta.seed = seed
    atk = battleside_for_lords(s, c["order"], "christian", "attacker", active_lord_id="alfonso")
    dfd = battleside_for_lords(s, m["order"], "muslim", "defender")
    assert {p.lord_id for p in dfd.array if p.position == "reserve"} == AFRICANS
    ctrl = ReactiveTiming(timing in ("javelins", "both"), timing in ("wall", "both"))
    if ctrl.javelins:
        # None means not yet declared. A Lord's positive round is set at use.
        atk.oneround_round = dfd.oneround_round = None
    if ctrl.wall:
        dfd.m7_round = None
    def choose_tactics(attacker, defender, rnd, step):
        ctrl(attacker, defender, rnd, step)
        if m["absorb"] == "wall_guard":
            # Owner chooses absorption before the pending dice. Use the
            # harness's existing armored-first policy specifically under
            # Spear Wall, and its weakest-first policy at all other steps.
            guarded = step == "2.b" and defender.m7_round == rnd
            s.meta.absorption_policy["muslim"] = (
                "armored_first" if guarded else "weakest_first")
            if guarded:
                ctrl.decisions.append(dict(kind="absorption", policy="armored_first",
                                           round=rnd, step=step))

    result = resolve_battle(s, atk, dfd, before_strike=choose_tactics)
    assert result.winner in ("christian", "muslim")
    row = dict(seed=seed, winner=result.winner, rounds=len(result.rounds),
               c_unrouted=atk.total_unrouted(), m_unrouted=dfd.total_unrouted(),
               dice=s.meta.rng_state, yusuf_entry=ctrl.entries.get("yusuf", 0),
               sir_entry=ctrl.entries.get("sir", 0),
               yusuf_javelins=next((x["round"] for x in ctrl.decisions
                                    if x.get("lord") == "yusuf"), 0),
               sir_javelins=next((x["round"] for x in ctrl.decisions
                                  if x.get("lord") == "sir"), 0),
               spear_wall=next((x["round"] for x in ctrl.decisions
                                if x["kind"] == "spear_wall"), 0))
    if trace:
        row["decisions"] = ctrl.decisions
        row["round_details"] = [asdict(r) for r in result.rounds]
    return row


def batch(job):
    name, c, m, timing, seeds = job
    state = prepare(c, m)
    return name, [play(state, c, m, seed, timing) for seed in seeds]


def summarize(rows):
    n = len(rows)
    wins = sum(r["winner"] == "muslim" for r in rows)
    return dict(n=n, muslim_wins=wins, muslim_rate=wins/n, ci95=wilson(wins, n),
                 mean_rounds=statistics.mean(r["rounds"] for r in rows),
                 mean_yusuf_javelin_round=statistics.mean(r["yusuf_javelins"] for r in rows
                                                         if r["yusuf_javelins"]) if any(
                     r["yusuf_javelins"] for r in rows) else None,
                 mean_sir_javelin_round=statistics.mean(r["sir_javelins"] for r in rows
                                                       if r["sir_javelins"]) if any(
                     r["sir_javelins"] for r in rows) else None)


def save_rows(path, data):
    first = next(iter(data.values()))[0]
    with path.open("w") as f:
        writer = csv.DictWriter(f, fieldnames=["configuration", *first])
        writer.writeheader()
        for name, rows in data.items():
            writer.writerows(dict(configuration=name, **row) for row in rows)


def run_jobs(pool, jobs, label):
    data = {}
    for i, (name, rows) in enumerate(pool.map(batch, jobs), 1):
        data[name] = rows
        if label != "training" or i % 48 == 0:
            print(f"{label} {i}/{len(jobs)} {name}: M "
                  f"{sum(r['winner']=='muslim' for r in rows)}/{len(rows)}", flush=True)
    return data


def guarded_followup(args, existing=None):
    """A separate matched challenge on fresh seeds, after the main study."""
    original = json.loads((args.out / "results.json").read_text())
    selection = original["selection"]
    cs, ms = profiles()
    # Include the training-best Muslim reply to the selected stronger
    # Christian profile; maximin alone can tie at zero in a small pilot.
    m_response = max(ms, key=lambda m: original["training_scores"][
        f"{selection['c_robust']}__{m['id']}"])["id"]
    chosen_cs = [c for c in cs if c["id"] in
                 {selection["c_default"], selection["c_robust"]}]
    chosen_ms = [m for m in ms if m["id"] in
                 {selection["m_default"], selection["m_vs_default"], m_response}]
    candidates = []
    for m in chosen_ms:
        candidates.append(dict(m, absorb="weakest_first"))
        candidates.append(dict(m, id=m["id"]+"_guard", absorb="wall_guard"))
    seeds = range(40000, 40000 + args.test_n)
    jobs = [(f"{c['id']}__{m['id']}", c, m, "both", seeds)
            for c in chosen_cs for m in candidates]
    # Allows extending a completed cohort without rerolling identical cells.
    # Only this study's caller supplies existing rows; CLI starts fresh.
    data = existing or {}
    for rows in data.values():
        assert [r["seed"] for r in rows] == list(seeds)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        data.update(run_jobs(pool, [job for job in jobs if job[0] not in data], "guarded"))
    data = {job[0]: data[job[0]] for job in jobs}
    save_rows(args.out / "guarded.csv", data)
    effects = {}
    for name, rows in data.items():
        if not name.endswith("_guard"):
            continue
        base = data[name.removesuffix("_guard")]
        deltas = [int(r["winner"] == "muslim") - int(b["winner"] == "muslim")
                  for r, b in zip(rows, base, strict=True)]
        mean = statistics.mean(deltas)
        se = statistics.stdev(deltas)/math.sqrt(len(deltas))
        effects[name] = dict(muslim_delta=mean, paired_ci95=[mean-1.96*se, mean+1.96*se])
    output = dict(n=args.test_n, seed_start=40000, m_response=m_response,
                   christian_profiles=chosen_cs,
                   muslim_profiles=candidates, summaries={k: summarize(v) for k,v in data.items()},
                   effects=effects)
    (args.out / "guarded.json").write_text(json.dumps(output, indent=2)+"\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-n", type=int, default=100)
    ap.add_argument("--test-n", type=int, default=3000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--guarded", action="store_true",
                    help="test conditional armor absorption after the main study")
    ap.add_argument("--out", type=Path, default=ROOT / "studies/sagrajas-reactive")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.guarded:
        guarded_followup(args)
        return
    cs, ms = profiles()
    c0, m0 = cs[0], ms[0]
    # Confirm an observing callback makes no change to the earlier experiment.
    for seed in range(50):
        prev = old_play(template({"role": "attack"}), {"role": "attack"}, seed)
        now = play(prepare(c0, m0), c0, m0, seed, "none")
        assert prev == {key: now[key] for key in prev}
    training_seeds = range(20000, 20000 + args.train_n)
    testing_seeds = range(30000, 30000 + args.test_n)
    assert set(training_seeds).isdisjoint(testing_seeds)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        controls = run_jobs(pool, [(f"timing_{t}", c0, m0, t, testing_seeds)
                                   for t in ("none", "javelins", "wall", "both")], "control")
        save_rows(args.out / "controls.csv", controls)
        jobs = [(f"{c['id']}__{m['id']}", c, m, "both", training_seeds) for c in cs for m in ms]
        training = run_jobs(pool, jobs, "training")
        save_rows(args.out / "training.csv", training)
        scores = {name: summarize(rows)["muslim_rate"] for name, rows in training.items()}
        def score(c, m):
            return scores[f"{c['id']}__{m['id']}"]
        # Pure-strategy maximin within this finite menu, not a solved full game.
        c_robust = min(cs, key=lambda c: max(score(c, m) for m in ms))
        m_robust = max(ms, key=lambda m: min(score(c, m) for c in cs))
        m_vs_default = max(ms, key=lambda m: score(c0, m))
        c_response = min(cs, key=lambda c: score(c, m_robust))
        chosen_cs = list({c["id"]: c for c in [c0, c_robust, c_response]}.values())
        chosen_ms = list({m["id"]: m for m in [m0, m_robust, m_vs_default]}.values())
        selection = dict(c_default=c0["id"], m_default=m0["id"],
                         c_robust=c_robust["id"], m_robust=m_robust["id"],
                         m_vs_default=m_vs_default["id"], c_response=c_response["id"])
        print("selected " + json.dumps(selection), flush=True)
        heldout = run_jobs(pool, [(f"{c['id']}__{m['id']}", c, m, "both", testing_seeds)
                                  for c in chosen_cs for m in chosen_ms], "heldout")
    assert heldout[f"{c0['id']}__{m0['id']}"] == controls["timing_both"]
    save_rows(args.out / "heldout.csv", heldout)
    effects = {}
    baseline = controls["timing_none"]
    for name, rows in {**controls, **heldout}.items():
        deltas = [int(r["winner"] == "muslim") - int(b["winner"] == "muslim")
                  for r, b in zip(rows, baseline, strict=True)]
        mean = statistics.mean(deltas)
        se = statistics.stdev(deltas)/math.sqrt(len(deltas)) if len(deltas)>1 else 0
        effects[name] = dict(muslim_delta=mean, paired_ci95=[mean-1.96*se, mean+1.96*se])
    report = dict(train_n=args.train_n, test_n=args.test_n, training_seed_start=20000,
                   testing_seed_start=30000, christian_profiles=cs, muslim_profiles=ms,
                   selection=selection, training_scores=scores,
                   controls={k: summarize(v) for k,v in controls.items()},
                   heldout={k: summarize(v) for k,v in heldout.items()}, effects=effects)
    (args.out / "results.json").write_text(json.dumps(report, indent=2)+"\n")
    examples = {}
    for seed in testing_seeds:
        row = play(prepare(c0, m0), c0, m0, seed, trace=True)
        examples.setdefault(row["winner"], row)
        if len(examples) == 2:
            break
    (args.out / "examples.json").write_text(json.dumps(examples, indent=2)+"\n")


if __name__ == "__main__":
    main()
