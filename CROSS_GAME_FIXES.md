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

Four of nine Almoravid findings are fixed; the other five remain open.
