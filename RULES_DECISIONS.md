# Rules Decisions

Per the BRIEF (Rules Accuracy Trumps Simplification), the harness
must implement the rules faithfully. Any deviation must be either
fixed before merge OR explicitly adjudicated by the user and
recorded here as a `[HOUSE RULE]`.

This file is append-only. Once a decision is recorded, it stays
recorded unless explicitly revisited.

## Entry format

```
## DECISION-NNN — short title

**Date:** YYYY-MM-DD
**Type:** [HOUSE RULE] | [INTERPRETATION] | [DEFERRED]
**Trigger:** Q-NNN from RULES_QUESTIONS.md, or PR / playtest reference

**Decision:** ...
**Reasoning:** ...
**Scope:** affects <code area>
**Revisit:** never | when X changes
```

## DECISION-001 — Open-field Battle Concede the Field is pre-declared per side

**Date:** 2026-06-02
**Type:** [INTERPRETATION]
**Trigger:** PR — open-field Battle Concede (4.4.2) was unimplemented in the
live action flow (only the Storm's Attacker-only concede was wired).

**Decision:** In an open-field Battle, either side may Concede the Field
(4.4.2). The choice is pre-declared per side via the optional action
arguments `attacker_concede_round` and `defender_concede_round` (1-based
Round numbers; omit = never Concede), honoured at the start of that Round
by `resolve_battle`. This mirrors the Storm's existing pre-declared
`concede_after_round`. The conceding side's Strikes are halved that Round
(pursuit) and it loses at Round end; Concede is checked before Rout when
deciding the winner.

**Reasoning:** `resolve_battle` resolves a whole Battle in one synchronous
call, so a fully interactive per-Round "Attacker then Defender may declare"
prompt would require making the resolver re-entrant — a large refactor. The
Storm already established pre-declaration as the project's accepted
abstraction for concede, so Battles follow the same model for consistency
and lower risk. Unlike the Storm (Attacker only, Round 2+), a Battle allows
EITHER side to Concede, from Round 1, per 4.4.2.

**Scope:** `resolve_battle` (src/almoravid/battle.py); the `cmd_battle`,
`respond_stand_battle` (standard Approach Battle), and Sagrajas resolve
handlers (src/almoravid/campaign.py). NOT yet wired: the Relief-Sally
resolver (`resolve_relief_sally`) and the internal besieged-Lord sally
path, which use separate resolvers — concede there is a future enhancement.
The pre-declared (vs interactive) model is the only simplification.

**Revisit:** when `resolve_battle` is made re-entrant (would allow a true
interactive per-Round Attacker-then-Defender concede prompt), or when
Relief-Sally concede is needed.
