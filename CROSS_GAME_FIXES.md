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

Six of nine Almoravid findings are fixed. **ALM-03** (forced-Feed sharing),
**ALM-04** (discarding Assets to March Unladen), and **ALM-05** (empty-Lord
cleanup after Capability troop removal) remain open.
