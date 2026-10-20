# Sagrajas harness study — 20 October 2026

The Christians won **98.4%** of default Christians-attack games and **45.9%**
of default Christians-defend games. These are conditional results for the
harness's fixed tactics, **not scenario balance under optimal play**.
Muslim deployment and Christian Bowmen placement made large differences.
The optional rules made no difference to any matched result.

## Method and reproduction

```sh
python -m pip install -e '.[dev]'
python scripts/sagrajas_study.py --n 2000 --seed-start 10000 --workers 4
```

This uses the actual harness: `load_scenario`, `apply_action`,
`battleside_for_lords`, and `resolve_battle`, with its existing SHA-256-seeded
D6 stream. There is no replacement combat model. Default and optional-rule
cells run through the public action interface; tactical cells select inputs
for the same combat resolver. The script asserts exact equality between the
public and internal default paths, including winner, rounds, remaining
unrouted units, and dice consumption.

There are **56,000 completed battles, 246,891 battle rounds, 28 configurations,
and 2,000 seeds per configuration (10000–11999)**. Each configuration uses the
same seed set. A separate 20-seed pilot (100–119) checked the runner and is
excluded. All main results were decisive. Neither side voluntarily concedes,
since conceding loses this battle-only game.

Rates have Wilson 95% binomial confidence intervals. Differences below have
paired 95% normal intervals for the per-seed change in Christian victory
indicator. Dice use diverges after different decisions, so matched seeds are
common random-number streams, not identical die-to-unit assignments.
Intervals describe Monte Carlo uncertainty under each fixed policy; they do
not account for engine limitations or strategy selection. They are not
adjusted for multiple comparisons. Equivalent controls are repeated
verification, not extra independent evidence about balance.

## Published optional rules

Hidden Mats (Rules 1.5.2) explicitly reveals mats in Battle/Storm. Advanced
Vassal Service (3.4.2) governs service duration, with no intervening Levy,
Calendar or feeding in this one-battle minigame. The minigame ends when the
Battle is won (Background Book p46). Neither option changes this contest's
combat mechanics. Bidding for Sides uses campaign victory points and is not
an alternative battle-resolution rule.

| Options | Christian win rate if attacking | Christian win rate if defending |
|---|---:|---:|
| None | 98.40% (97.75%–98.86%) | 45.90% (43.73%–48.09%) |
| Hidden Mats | 98.40% (97.75%–98.86%) | 45.90% (43.73%–48.09%) |
| Vassal Service | 98.40% (97.75%–98.86%) | 45.90% (43.73%–48.09%) |
| Both | 98.40% (97.75%–98.86%) | 45.90% (43.73%–48.09%) |

Every optional-rule run matched its no-option counterpart exactly. The
attack/defend branches are scenario choices, not optional rules: attacking
adds Christian Crusaders, Jabalinas, Slingers and Cantador; defending instead
adds Muslim Saqalibah, Harbah, Andalusians and Feigned Retreat. Thus the
52.5-point gap is not a pure estimate of defender initiative.

Default attacks average 3.73 rounds (median 4; observed range 3–8); default
Christian defenses average 5.08 (median 5; range 3–10).

## Tactical comparisons

Each row changes the indicated choice from that role's default; do not add
these effects together or assume they persist against every counter-strategy.
All entries are **Christian** win percentages with 95% intervals.

| Choice | Christians attack | Christians defend |
|---|---:|---:|
| Default | 98.40% (97.75%–98.86%) | 45.90% (43.73%–48.09%) |
| Muslims put Yusuf and Sir in Front | 56.35% (54.17%–58.51%) | 32.45% (30.43%–34.53%) |
| Move Christian Bowmen C5 from Sancho to García | 99.70% (99.35%–99.86%) | 81.60% (79.84%–83.24%) |
| African-horse Javelins on Round 2 | 95.20% (94.17%–96.05%) | 49.20% (47.01%–51.39%) |
| Spear Wall on Round 2 | 98.35% (97.69%–98.82%) | 50.25% (48.06%–52.44%) |
| Both African Javelins and Spear Wall on Round 2 | 95.05% (94.01%–95.92%) | 53.55% (51.36%–55.73%) |
| Pedro in Front instead of García | 97.95% (97.23%–98.49%) | 48.15% (45.97%–50.34%) |
| Christians absorb with armored units first | 97.70% (96.95%–98.27%) | 47.50% (45.32%–49.69%) |
| Muslims absorb with armored units first | 99.70% (99.35%–99.86%) | 53.35% (51.16%–55.53%) |
| Both absorb with armored units first | 99.20% (98.70%–99.51%) | 57.20% (55.02%–59.35%) |

### What to do with this

- **Muslims: test deploying the African core immediately.** With Christians
  attacking, Muslim wins rise from 1.6% to 43.65%; when Muslims attack,
  they rise from 54.1% to 67.55%. This configuration puts Yusuf, Sir and
  al-Mutamid in Front, with Abd Allah and al-Mutawakkil in Reserve. It brings
  African missiles and Spear Wall recipients into action in Round 1 and
  changes matchups. It is a deployment package, not an isolated estimate
  of any one of those mechanisms.
- **Christians: put Bowmen on a substantial engaged contingent.** C5 on
  García, rather than Sancho's three-unit reserve, raises Christian defensive
  wins by 35.7 points. It uses an explicit setup choice on Background Book
  p46, without adding units or extra cards.
- **Time Javelins to the deployment.** Delaying Yusuf/Sir to Round 2 helps
  Muslim defenders modestly, but hurts Muslim attackers. In the default
  defense both African Lords start in Reserve; when attacking, Yusuf must
  start at Front center and can use his missiles immediately. A blanket
  Round-2 policy is not a general recommendation. Lords still in Reserve on
  their preselected round do not fire in this experiment.
- **Do not assume armored-first absorption is best.** For Muslim attackers,
  it increases Christian wins from 45.9% to 53.35%. Preserving combat output
  and surviving more individual Hits are different objectives. These are
  the harness's named ordering policies, not a search over every per-Hit
  choice. The Christian armored-first effect is inconclusive here.
- **Christians choosing attack did better with these setups.** The option
  includes additional troops/cards, so this does not establish that attacking
  is always tactically superior. No minimax strategy or equilibrium was
  computed.

Selected paired effects on the **Christian** win rate:

| Change | Difference and paired 95% interval |
|---|---:|
| Muslim African Front, Christians attacking | -42.05 pp (-44.26 to -39.84) |
| Muslim African Front, Christians defending | -13.45 pp (-16.29 to -10.61) |
| Christian Bowmen forward, Christians defending | +35.70 pp (+33.10 to +38.30) |
| African Javelins R2, Christians attacking | -3.20 pp (-4.19 to -2.21) |
| Muslim armored-first, Christians defending | +7.45 pp (+4.70 to +10.20) |

## Historical comparison

The historical result was a Muslim coalition victory over Alfonso VI at
Sagrajas/Zallaqa in 1086. Al-Marrakushi's later account (written in 1224), in
a translation hosted by the Society for Medieval Military History, describes
Christian cavalry attacking, their subsequent defeat, and Alfonso escaping.
A 2025 Al al-Bayt University historical study also identifies Yusuf's victory.

- [Al-Marrakushi translation, De Re Militari](https://deremilitari.org/2013/11/the-battle-of-zallaqa-1086/)
- [Al al-Bayt University study abstract](https://www.aabu.edu.jo/en/collegesandinstitutes/arts/departments/history/pages/researchesdetails.aspx?itemid=7084)
- Game setup/tactical historical interpretation: `source/Almoravid_BackgroundBook_FINAL-Web.pdf`, pp44–46.

The historical outcome occurs in **32/2000 (1.6%)** default Christians-attack
runs, or **873/2000 (43.65%)** with the tested African-forward deployment.
The latter is a counterfactual deployment: the game's historical narrative
puts the Taifa forces first and the African core behind them, followed by
a counterattack. The experiment does not show that the historical deployment
was a mistake. Fixed automatic choices, timing and matchups do not capture
all human decisions available in the game, much less an actual battlefield.
The later medieval account and the Background Book differ in tactical detail;
there is no sufficiently precise historical probability to calibrate against.

One real battle is not a statistical sample of counterfactual repeats.
A rare simulated historical result can indicate poor default tactics or
model limitations; it is not a reason to alter rules to force a Muslim win.
The result cannot establish the game's balance under expert play.

We compare victory direction only. Unrouted game units are **not historical
casualty counts**: these runs stop at the battle-only victory and do not turn
routed counters into killed soldiers. No army-size or casualty conversion is
attempted. Campaign consequences such as control of Toledo are outside this
minigame's victory condition.

## Exact tactical inputs and limitations

Default Christian Front, center/left/right: Alfonso, Álvar Fáñez, García;
reserves: Pedro, Sancho. Default Muslim defense Front: Abd Allah,
al-Mutawakkil, al-Mutamid; reserves: Yusuf, Sir. Default Muslim attack Front:
Yusuf, Abd Allah, al-Mutawakkil; reserves: al-Mutamid, Sir. Reserve advance,
flank targeting and center filling keep the harness's standard policies.
Spear Wall marks Yusuf and Sir (the harness selects the two largest
armored-foot contingents). Default Javelins and Spear Wall use Round 1.
Other setup/card assignments are those in `build_sagrajas` and its role
handlers. The two named default hit policies are `weakest_first`.

The script calls the harness's resolver directly for deployment/timing
comparisons because the public Sagrajas action fixes those defaults. It does
not implement battle rules. All tactical schedules are fixed in advance;
reactive per-Lord timing, complete card/vassal allocation search, per-Hit
choices, event withholding and opponent best responses remain untested.

Before the study, a regression exposed an actual engine error: multi-Lord
combat unioned every Lord's missile cards into every other Lord's profile.
The study uses the corrected ownership scope. African Horse already had
native Javelins; a contrary limitation note was stale and has been corrected.
A small per-Lord round field enables independent Javelin timing through the
same resolver and survives snapshots. No combat odds were adjusted to fit
history. These results describe this corrected version, not the old commit.

Validation: **1,546 tests passed**, source/study lint passed, and both required
scenario A/F invariant smoke commands returned successfully. Two F sessions
reached their 400-step observation budget; that is not a completed campaign.
The three new regressions cover card ownership, native African Javelins and
independent Javelin timing. Original fixed-seed long-battle tests were
recalibrated after the ownership correction.

Data: `battles.csv` contains every main run; `results.json` contains all
configurations, rates and intervals; `examples.json` contains full harness
strike-step logs for the first default Christian and Muslim victory in the
seed sequence (10000 and 10010, respectively).
