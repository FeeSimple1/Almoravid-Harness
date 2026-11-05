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

The other seven Almoravid findings remain open.
