# Sagrajas with reactive reserve tactics — 20 October 2026

**The historical-outcome concern survives this follow-up.** Correct reserve
weapon timing raises Muslim wins from 1.4% to 4.9% without changing the initial
setup. Selected Taifa matchups and reserve order raise that to 14.7% against
the default Christian choices. Against the stronger Christian profile selected
in training, a Muslim reply selected specifically for that opponent wins
2.65% on a separate seed cohort (95% CI 2.03–3.45%).

This is evidence of a strongly Christian-favored historical-reserve scenario
under the tested strategies. It is not proof that the published game is
incorrect: implementation fidelity, scenario setup, and untested decisions
remain possible explanations. The earlier suggestion that mistimed reserve
abilities would explain most of the disparity was too optimistic.

## What stayed fixed

Every game uses the published Christians-attack branch, with Alfonso at Front
center, the three Taifa Lords in Muslim Front, and **both Yusuf and Sir in
Reserve**. No African-forward deployment, extra units, extra events, house
rules, changed protection odds, or historical-outcome weighting is used.
The historical structure is preserved; this is not a claim to reproduce every
position in the Background Book's illustrative diagram.

Setup and battle resolution come from the existing harness. The experiment
selects inputs and uses `resolve_battle`; it does not reproduce combat rules.
Neither side concedes, since conceding loses this minigame. Optional Hidden
Mats and Vassal Service were held off: the preceding study established exact
outcome equivalence for these options in this battle-only setting.

## Reactive choices

- A Lord uses Javelins on the first missile step at which he is actually in
  Front and has an enemy Front target. Each Lord's marker is used once.
- Spear Wall is placed on Yusuf and Sir at battle outset as before, but its
  effect waits until a marked Lord with Armored Foot is about to receive
  Christian Horse Melee. The declaration occurs immediately before that
  strike step, after the current round's missiles and Muslim Horse Melee.
- The decision controller sees current armies and the current round/step,
  not the seed, RNG counter, or future rolls. No future outcomes are sampled
  to choose an in-battle action.
- The separate conditional-absorption probe uses the harness's armored-first
  policy for Muslim units only during that protected Christian Horse step;
  it uses weakest-first at other steps.

These are permitted choices under Rules 4.4.2 and the M7 Spear Wall tips in
`reference/Almoravid Arts of War Reference.txt`. Spear Wall remains one shared
round for its two recipients, not one separate round per Lord.

## Timing alone: same setup, matched seeds

3,000 battles per row, seeds 30000–32999. All rates are **Muslim victories**.
Intervals are Wilson 95% binomial intervals.

| Timing policy | Muslim wins | Win rate and 95% CI |
|---|---:|---:|
| Original Round-1 schedules | 42/3000 | 1.40% (1.04–1.89%) |
| Reactive Javelins only | 144/3000 | 4.80% (4.09–5.62%) |
| Reactive Spear Wall only | 45/3000 | 1.50% (1.12–2.00%) |
| Both reactive | 147/3000 | 4.90% (4.18–5.73%) |

The paired increase for both reactive effects is **3.50 percentage points**
(95% paired interval **2.70–4.30**). That is a real improvement, but much too
small to explain the original disparity. Yusuf's javelins fire in Round 2;
Sir's average use round is 2.036 in this cohort. Reactive Spear Wall is used
in Round 2 or 3. The reserve timing is therefore actually exercised.

## Strategy selection and independent validation

Training compares 12 Christian profiles with 24 Muslim profiles: **288 pairs,
100 seeds each (20000–20099)**. Christian profiles vary three Front
compositions, the second Bowmen card's placement, and the two existing
hit-absorption policies. Muslim profiles vary all six Taifa Front permutations,
both African reserve orders, and those same two absorption policies. All
profiles keep the historical reserve structure and use reactive timing.

Candidates are selected from training, then evaluated on fresh seeds. The
pure-strategy maximin selection is only a selection rule over this finite
menu. It is not a solved game equilibrium. With rare wins and 100 training
seeds, some worst-case estimates tie at zero; the later challenge explicitly
includes the training-best Muslim reply to the selected Christian profile.

The selected stronger Christian profile keeps Alfonso/Álvar/García in Front,
moves C5 Bowmen from Sancho to García, and uses armored-first absorption.
This is a tested combination; its result does not isolate the benefit of
armored-first from the benefit of Bowmen placement.

The Muslim setup selected against default Christians puts al-Mutawakkil at
center, al-Mutamid at left, Abd Allah at right, and advances Sir before Yusuf.
The training-selected reply to the stronger Christians instead puts Abd Allah
at center, al-Mutamid at left, al-Mutawakkil at right, and advances Yusuf first.
Both use weakest-first absorption outside the conditional probe.

Independent validation, 3,000 seeds per pairing:

| Christian profile | Muslim profile | Muslim wins | Rate and 95% CI |
|---|---|---:|---:|
| Default | Original matchups/order | 147/3000 | 4.90% (4.18–5.73%) |
| Default | Selected vs default Christians | 441/3000 | 14.70% (13.48–16.01%) |
| Selected stronger | Original matchups/order | 6/3000 | 0.20% (0.09–0.44%) |
| Selected stronger | Selected vs default Christians | 52/3000 | 1.73% (1.32–2.27%) |

A second independent cohort, seeds **40000–41999**, tests the targeted Muslim
reply and conditional Spear Wall absorption. It compares all three selected
Muslim deployments against both Christian profiles, with and without the
conditional policy (12 cells of 2,000 games).

| Christian profile | Muslim profile | Normal absorption | Armored-first only under Spear Wall |
|---|---|---:|---:|
| Default | Original | 5.65% (4.72–6.75%) | 6.10% (5.13–7.24%) |
| Default | Reply to stronger Christians | 10.65% (9.37–12.08%) | 11.20% (9.89–12.66%) |
| Default | Selected vs default Christians | 13.50% (12.07–15.07%) | 12.60% (11.22–14.13%) |
| Selected stronger | Original | 0.30% (0.14–0.65%) | 0.25% (0.11–0.58%) |
| Selected stronger | Reply to stronger Christians | 2.65% (2.03–3.45%) | 2.35% (1.77–3.11%) |
| Selected stronger | Selected vs default Christians | 2.00% (1.47–2.71%) | 1.75% (1.26–2.42%) |

None of the six paired conditional-absorption effects clearly differs from
zero at the unadjusted 95% level. It offers no demonstrated remedy here.
The targeted Muslim reply performs better than the other tested deployments
against the stronger Christian profile, but still wins just **53/2000**.
That is approximately one win in 38 games, conditional on this pairing.

## Interpretation and limits

The historical Muslim victory is not extraordinarily rare against all
Christian play: 14.7% is about one in seven. However, tested Christian
counterplay makes it rare again, even after a targeted Muslim reply. This
supports the user's concern about the historical-reserve scenario more than
the initial fixed-policy study did. Correcting the obvious timing problem
was insufficient.

Before attributing the disparity conclusively to the published game, an
independent rules adjudication of representative battles and scenario setup
would be valuable. Passing software tests is not proof that every rule is
encoded correctly. The experiment also leaves many choices unsearched:
Crusader/Bishop/Milites redistribution, other missile-card placements,
per-unit/per-Lord hit allocation, adaptive reserve-to-position matching,
flank absorption, target selection and the timing of individual choices
within a strike step. No claim of optimal or expert-equivalent play is made.
The minigame findings do not establish campaign-game balance or historical
battle probabilities. Routed counters are not converted to human casualties.

Historical comparison uses the outcome already sourced in the preceding
study: Muslim victory and Alfonso's escape, described in the
[Al-Marrakushi translation hosted by De Re Militari](https://deremilitari.org/2013/11/the-battle-of-zallaqa-1086/).
The reserve structure comes from the game's Background Book pp44–46.
History was not used to alter the rules or numerical results.

Confidence intervals measure Monte Carlo uncertainty within fixed policies,
not model error or uncertainty over the best strategy. Matched runs share
random-number streams; decisions change subsequent dice consumption.
Intervals are not adjusted for multiple comparisons. Repeated baseline cells
are verification, not additional independent samples.

## Reproduce and inspect

```sh
python scripts/sagrajas_reactive_study.py --train-n 100 --test-n 3000 --workers 4
python scripts/sagrajas_reactive_study.py --guarded --test-n 2000 --workers 4
```

The principal data comprise **76,800 completed battles and 290,602 battle
rounds**: 12,000 controls, 28,800 training, 12,000 first validation, and 24,000
second validation. Pilot, parity checks and example-log replays are excluded.

- `controls.csv`, `training.csv`, `heldout.csv`, `guarded.csv`: every run.
- `results.json`: profile definitions, selection, main statistics and effects.
- `guarded.json`: second-cohort comparisons and paired absorption effects.
- `examples.json`: representative reactive default games, one per winner.
- `counter_examples.json`: representative stronger-Christian/targeted-Muslim
  games, one per winner, including each engine strike step and timing choices.

Timing columns record reactive declarations; zero means no reactive declaration
was recorded (fixed-schedule controls still retain their Round-1 schedule).

Engine changes add an optional callback before each existing Strike step and
allow one-round timing to remain undecided until declaration. Existing atomic
Sagrajas actions retain their default schedules. The study controller supplies
reactive choices; this does not claim that all such choices are exposed in
the public Sagrajas menu.

Validation: **1,551 tests pass**, lint passes, default/no-op-hook games match
the preceding runner, and both A/F invariant smoke commands succeed. The new
tests verify first-Front Javelin use, single-use timing, immediate Spear Wall
protection, snapshot persistence, unchanged defaults, and conditional
absorption only during the protected Horse step.
