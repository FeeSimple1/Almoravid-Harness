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
