# Cross-game audit repairs

The November 4, 2026 cross-game audit identified nine Almoravid defect groups.
This first repair batch addresses audit IDs **R1** and **R2**:

- **R1 — Pay recipient:** ordinary Pay rejects an enemy recipient before
  spending Coin or shifting Service. Paying oneself or a co-located friendly
  Lord still works.
- **R2 — Rejected compound actions:** the public dispatcher restores the
  board, RNG and appended history when resolution raises an exception. This
  prevents a bad Parias distribution from leaving an already-disbanded Lord
  and changed Taifa status. Rollback preserves references held by callers and
  accounts for Pydantic's validated assignment replacing internal dictionaries.

Regression tests cover the original Disband rejection, a corrected retry
against a pristine position, enemy and friendly Pay recipients, retained
object references, and a failure after dice and history changes. The
checkpoint excludes old history entries from traversal so its cost depends
on the current board rather than the length of a campaign transcript.

## Batch 2 — player visibility

- **IF-1 — Predictable dice:** player snapshots omit the seed and RNG counter.
  Controller saves retain both, so save/load and deterministic replay still work.
- **IF-2 — Hidden This-Lord cards:** the global Capability registry now follows
  the same ownership and combat-visibility mask as the Lord mat. Deployment
  history also conceals those private selections. Own cards and side-wide
  Capabilities remain visible; combat reveals the participating mats and cards.

Regression tests exercise both player perspectives with and without Hidden Mats,
unchanged future rolls after viewing, real Capability Levy actions, public
side-wide cards, and visibility before, during, and after combat.

## Transport repair batch — ALM-01 and ALM-02

- **ALM-01 — Conceded Retreat:** Spoils now use the actual Retreat Way and
  Shared Transport of Lords retreating together along that Way. Each Lord's
  own food uses his usable Transport first; remaining capacity can carry a
  co-retreater's Provender without moving it between mats. Lords who Withdraw
  or stay behind do not contribute. C7's paid opt-out and non-conceding
  all-Asset transfers retain their existing effects.
- **ALM-02 — Camels during Avoid:** Avoid and Retreat use M16's effective Mule
  capacity for Yusuf and Sir, including when they lend Transport to allies.
  The bonus does not apply to Carts or other Lords' Mules.

The shared Unladen capacity calculation follows 4.3.2: one Provender per usable
Transport, with no Cart-borne Provender on Passes. The related March check now
also charges Laden cost for two Provender with one Mule and one otherwise empty
Cart across a Pass. A doubled Mule load cannot become Unladen merely because
an unused Cart pads the total Transport count.

Twenty-two new cases cover Road/Pass Retreat, Camels eligibility, shared food
carriage, occupied Transport, excluded donors, non-concession, save/load,
public Approach and Avoid actions, and Pass March cost/rejection rollback.
Twelve fail against the previous main revision; ten preservation cases pass.

Validation: 1,623 tests passed and the complete source Ruff check passed. Both
CI stress commands passed invariant checks for seed 2 and all three profiles:
Toledo Beset's three sessions completed, while Reconquista's three sessions
reached the configured 400-step smoke limit. No full Reconquista completion
claim is made by that bounded sweep.

## Logistics repair batch — ALM-03 and ALM-04

- **ALM-03 — Forced Feed:** Drought and Arid Terrain now use the same 4.8.1
  own-Feed, mandatory sharing, then Unfed sequence as the end-card step. All
  affected Lords consume their own food before sharing. Other same-side Lords
  at the Locale can donate without themselves owing Feed. Partial food is
  consumed before any remaining shortfall causes a Service penalty. Event
  results include shared food and the final consumption/shortfall per Lord.
- **ALM-04 — March Unladen:** `discard_to_unladen: true` discards all moving
  Lords' Loot and only the Provender beyond their shared usable Unladen
  capacity. The handler and menu support ordinary March, chosen groups,
  mandatory Lower Lords, Guadalquivir and African Fleet. The ordinary Laden
  move remains available when affordable. African Fleet still spends the
  entire fresh Command card. Interrupted Marches keep the proposed discards,
  and successful moves report exactly which Assets each Lord discarded.

The newly reachable random-play path also exposed a pre-existing Muster menu
error outside the original audit: it offered empty Seats under Enemy control,
which execution correctly rejected. The menu now uses the executor's shared
Seat validator, preserving legal Friendly and Neutral Seats while excluding
Enemy Seats and Seats with Enemy Lords.

Thirty-one regressions cover both findings and the Seat mismatch. Twenty-eight
fail against the preceding main revision; three preservation cases pass. Two
older tests now set up actual food exhaustion (including allies) and expect
the new discard option when a mandatory Lower Lord's Loot makes March Laden.

Validation: 1,654 tests passed and the source Ruff check passed. The configured
CI stress sweeps reported no invariant failures: all three Toledo Beset profiles
completed; Reconquista completed one profile and reached the 400-step smoke
bound in two profiles.

## Empty-Lord repair batch — ALM-05

Returning Capability troops now immediately Disbands a Mustered Lord when
his final Force leaves under 1.6/3.3.2. M15/M20 and Count/Bishop contingents
share this cleanup. Surviving regular or Routed Forces keep the Lord on map;
Milites retains its printed exception. Calendar placement uses the current
Levy or next Levy as appropriate, including expired Service and box 17.

Disband clears the mat and applies Taifa status, Parias Coin and VP through
the existing rules path. Lords already being removed leave the map before
Capability cleanup, preventing recursive Disband or accidental Calendar
placement. Wastage pauses for Recognition of Neutrality and resumes its
remaining authorized discards exactly once, including after save/load.
Internal continuation choices remain hidden in player views. A final-Lord
Campaign victory resolves before the Calendar advances.

Twenty-eight regressions cover interactive and automatic Wastage, Calendar
timing, surviving Forces, permanent removal, political choices, save/load,
rejected selections, hidden continuations and immediate victory. Eighteen
fail against the preceding main revision; ten preservation cases pass.

Validation: 1,682 tests passed and the source/new-test Ruff check passed.
Both configured CI stress sweeps passed invariant checks. All three Toledo
Beset profiles completed; Reconquista completed one profile and reached the
configured 400-step bound in two profiles.

All nine original Almoravid audit findings are fixed.

## Second audit, batch 1 — A2-04

End Campaign now follows 4.9 in order: Game End, Grow/Harvest, Repairs,
Wastage, then Reset. Final scoring happens before any mat or map cleanup,
with the Campaign marker left in its final box. The reproduced final-Campaign
M15 discard can no longer reverse a Muslim points victory into a Christian
Campaign victory. Harvest changes the mat before Wastage eligibility is checked.

Completed Grow/Harvest and Repairs travel through the Wastage continuation,
including political choices and saved games, so they run once. Explicit Grow
selections survive both sides' Wastage prompts. Reset unstacking waits until
those choices finish, and unrelated End Campaign calls reject while pending.

Nineteen new regressions cover final scoring, Calendar overflow, automatic and
interactive Harvest/Wastage, both Transport types, explicit Grow, Repairs,
save/load, invalid selections and Reset timing. Eighteen fail on the preceding
main revision; one preservation case passes. The full suite passes 1,701 tests,
and source/new-test Ruff checks pass. Both configured invariant stress sweeps
pass: Toledo's three profiles complete; Reconquista completes one profile and
reaches the 400-step bound in two.

Second-audit progress: **1 of 6 Almoravid groups fixed**. A2-01, A2-02, A2-03,
IF2-2 and IF2-3 remain open. The original nine groups remain fixed.

## Second audit, batch 3 — IF2-2 and IF2-3

- **IF2-2 — Hidden Mats timing:** Approach no longer reveals enemy mats
  while Avoid/Withdraw/Stand remains undecided. Committed interactive Battle,
  Storm, Relief Sally and one-Round timing choices reveal their participants.
  Synchronous combat uses transient visibility for its participants, with
  cleanup on return or exception. Uninvolved same-Locale and remote Lords
  remain concealed. Controller saves and unrelated copied states are unchanged.
- **IF2-3 — Unplayed Hold secrecy:** every declared Avoid now waits for the
  Approaching player's reaction, whether or not Swollen River is Held. The
  declaration result and defender's view are identical for both hand states;
  private card IDs are omitted. The owner's menu offers Play only if Held,
  or Decline; Decline resumes the declared Avoid and retains any unplayed
  card. Actual Play consumes and publicly identifies the card exactly once.
  Missing cards, wrong actors and malformed choices reject atomically.

The Avoid declaration is validated before the reaction window is created.
Control passes to its reacting owner, then returns to the pending response or
normal activation. An action-supplied internal flag cannot skip the window.
Saved reaction decisions resume through the same handlers.

Twenty-four new regressions cover both players, open/Hidden Mats, identical
opponent views with/without the Hold, Play/Decline, empty hands, invalid
requests, save/load, interactive timing, bystanders, synchronous combat and
exception cleanup. Twenty-two fail on the preceding main; two preservation
cases pass. Existing Avoid outcome tests now explicitly decline the reaction.
One old Bypass fixture now includes a bypassing Lord so its marker remains
valid across that extra step. The old Swollen River source-inspection test
now checks real public declarations and card play.

Validation: 1,726 tests passed and source/new-test Ruff checks passed. Both
configured invariant stress sweeps passed. All three Toledo profiles completed;
Reconquista completed one profile and reached the 400-step bound in two.

Second-audit progress: **3 of 6 Almoravid groups fixed**. A2-01 (Lost Spoils),
A2-02 (M13) and A2-03 (voluntary Reset discards) remain open. The original
nine groups remain fixed.

## Second audit, batch 4 — A2-01 and A2-02

- **A2-01 — Lost Spoils:** a losing Lord permanently removed by Losses now
  transfers all remaining Assets before mat cleanup, including those kept
  after Withdrawal, Concede or a Retreat exemption. Already transferred Spoils
  are not duplicated. Both sides finish Losses before the remaining captured
  pile is distributed among surviving winning Lords. The Retreat report
  records the additional capture and removal. Parias Coin remains a separate
  award; removed winning Lords do not donate their Assets to the losing side.
- **A2-02 — M13 Severed Heads:** successful Muslim Ravage, actual Christian
  Retreat/no-Retreat elimination and Christian Stronghold Sack now offer
  optional Muslim card play. Pure Withdrawal never triggers M13, including
  Withdrawal followed by Losses removal. Choose 2/4 Jihad, with explicit
  eligible placement, or shift 1/2 distinct Taifa Lords. Calendar cylinders
  shift left and on-map Service right by two boxes, including advanced Vassal
  markers. Every eligible single/pair appears in the menu. Decline preserves
  the Hold; Play consumes it once. Invalid timing/choices reject atomically.

The public reaction appears with or without M13, preserving Hold secrecy.
It suspends any post-combat response and restores it and the previous actor
after Play/Decline, including after save/load. Internal continuations are
absent from both player views. Immediate Campaign victory takes precedence.

Checking M13's Ravage prerequisite exposed missing C19 Caballería Villana
rolls. Muslim Ravage in León/Aragón now requires 1–3, including long-range
Al-Garada. Failure spends the Command/Provender but yields no marker, Rustling,
War Drums, VP or M13 opportunity. Event-placed Ravage remains separate.
The same review removed an unsupported eight-Asset ceiling from successful
Rustling/War Drums rewards: Assets are unlimited under 1.7.1.

Fifty-one new regressions cover both losing sides, prior Spoils, surviving and
removed Withdrawers, multiple winners, unlimited Assets, all M13 rewards,
timing, card secrecy, invalid requests, saved off-turn reactions, suspended
responses, Sack, failed Retreat, normal/long-range Ravage and C19 boundaries.
Existing M13 tests now use actual Ravage timing and assert optionality. The
political-removal test now expects captured Assets in addition to Parias Coin.

Validation: **1,777 tests passed**, with source/new-test Ruff checks passing.
Forty of the new regressions fail against the preceding main revision; eleven
preservation cases pass. Both configured invariant stress sweeps passed:
Toledo Beset completed all three profiles; Reconquista completed one and
reached the configured 400-step bound in the other two, without violations.

Second-audit progress: **5 of 6 Almoravid groups fixed**. A2-03 (voluntary
Reset discards) remains open. The original nine groups remain fixed.

## Second audit, batch 5 — A2-03

Reset now offers Christians and then Muslims their printed 4.9.5 election
to discard any owned Held Events, This-Lord Capabilities or board-edge
Capabilities. This right is independent of Wastage eligibility. Either
player may keep everything. The menu offers single-card choices that keep
the election open plus a finish choice, making every subset reachable;
the public action also accepts batches. Both sides receive the prompt even
with empty hands, and only the owner sees private-card choices.

Holds return unused; Capabilities go through the existing printed cleanup.
Troop contingents return, final-Force loss immediately Disbands the Lord,
and Milites leaves the game while its units stay. Cascade-discarded cards
do not apply their effects twice. A final-Lord Campaign victory stops the
remaining selections and Calendar advance. Political decisions suspend the
remaining authorized choices and restore the correct actor after resolution,
including save/load. Continuation choices remain absent from both player
views and from history until the cards are actually discarded.

Game End still precedes all cleanup. Wastage/Repairs finish before Reset,
then Lieutenants unstack before the first discard election. The Calendar
advances only after both players finish; Grow, Harvest, Repairs, Wastage and
Calendar advance are not repeated by card choices or saved continuations.

Thirty-six new regressions cover both sides, all three card locations,
arbitrary subsets, legacy Holds, Milites, troop loss and Disband, cascades,
Campaign victory, political pauses, privacy, invalid requests, save/load,
timing and final scoring. Twenty fail on the preceding main; sixteen
rejection/preservation cases pass. Older Wastage/Winter playthrough fixtures
now explicitly keep their cards through a shared Reset-response helper.
One Winter fixture now retains an opposing Mustered Lord through Reset so
it does not already satisfy Campaign victory. Stress reports include the
victory reason, allowing the depth assertion's documented early-Campaign
victory exception to work after the additional decisions change play order.

Validation: **1,813 tests passed**; source/new-test Ruff checks passed. Both
configured invariant stress sweeps passed. Toledo Beset completed all three
profiles; Reconquista completed one and reached the configured 400-step
bound in the other two, without violations.

Second-audit progress: **all 6 Almoravid groups fixed**. All nine findings
from the original audit remain fixed.

## Third audit, batch 1 — A3-05

Interactive Battle, Approach Battle, Sally, and Relief Sally now give each
player their own Concede choice. The attacker answers first in each round.
A pass hands the choice to the defender without rolling dice. The first
concession starts that round with Pursuit and ends combat after the round.
Two passes resolve a normal round. This updates the prompt ownership
described in DECISION-002. Referees can use the scripted round arguments.

Only the current owner's concession appears in the legal menu. An opponent
declaration or an out-of-order response rejects without changing state.
After the battle, the original Command side resumes control. Legacy saves
with a single Concede prompt resume with the attacker in the saved round.

Regressions cover both owners, save and reload, card control, and parity
with synchronous resolution. All **1,819 tests passed**, and source Ruff
checks passed. Both configured stress sweeps passed their invariant checks.
Four sessions completed and two reached the configured 400-step bound.

Follow-up for the Retreat work — a losing Relief Sally Lord can Retreat
along the Approach Way. The same seeded case reproduces on preceding main.

Third-audit progress is **one of five Almoravid groups** and **14 of 23 overall**.

## Third audit, batch 2 — A3-01

The losing player chooses each eligible Lord's fate and Retreat Way after
combat. The legal menu opens the choice for field Battle, Approach Battle,
Sally, and Relief Sally. Choices can be saved and resumed before movement,
Losses, and Service are applied. Selecting a Withdrawal reserves a slot
before the next Lord chooses. Scripted calls can use immediate resolution.

Losing Relief Sally Lords Withdraw into their Stronghold. Their mandatory
slots are reserved before Marchers can elect Withdrawal. In the Zamora
regression, the losing Marcher Retreats to León and the Sallying Lord returns
inside the castle, leaving one Siege marker.

Eight seeded regressions fail on preceding main and pass here. All **1,827
tests passed**, and the source and new tests passed Ruff. Both configured
self-play sweeps passed their invariant checks. Four sessions completed
and two reached the configured 400-step bound.

Third-audit progress is **two of five Almoravid groups** and **15 of 23 overall**.

## Third audit, batch 3 — A3-03

The Retreat menu offers Baggage Parapet payments from each eligible
Christian Lord's own Assets. A chosen payment spends one Asset and skips
that Lord's Retreat Spoils and Service shift. The player can also Retreat
without paying. Choices are staged until all fates are selected and survive
save and reload. Scripted resolution and fate selections saved before the
payment field existed use the prior automatic payment order.

Eight regressions fail on preceding main and pass here. All **1,835 tests
passed**, and the source and new tests passed Ruff. Both configured self-play
sweeps passed their invariant checks. Four sessions completed and two reached
the configured 400-step bound.

Third-audit progress is **three of five Almoravid groups** and **16 of 23 overall**.

## Third audit, batch 4 — A3-02 and A3-04

Battle, Sally, Relief Sally, and successful Storms finish Losses before
awarding Spoils. Captured Assets are held for surviving winning Lords at
the Locale. A dead Lord can neither receive Spoils nor contribute Transport
to a conceding Retreat. Losses forfeitures join the same captured pool.

When multiple recipients remain, the winning player can split the pool in
any legal amounts. The allocation saves and resumes, rejects foreign mats
and overdraws, and completes before Severed Heads or the next Command
decision. Single-recipient, scripted, and campaign-ending settlements
allocate automatically.

Five seeded regressions fail on preceding main and pass here. All **1,840
tests passed**, and the source and new tests passed Ruff. Both configured
self-play sweeps passed their invariant checks. Four sessions completed
and two reached the configured 400-step bound.

All **five Almoravid groups** from the third audit are fixed. Overall
progress is **18 of 23 groups**.
