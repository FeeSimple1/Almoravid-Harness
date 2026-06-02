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

**Scope:** all Battle-family resolvers and their handlers
(src/almoravid/battle.py, src/almoravid/campaign.py):
- open-field Battle — `resolve_battle`, via `cmd_battle`,
  `respond_stand_battle` (standard Approach Battle), and Sagrajas;
- besieged-Lord Sally (4.5.3) — `resolve_sally`, via `cmd_sally`;
- Relief Sally (4.4.1) — `resolve_relief_sally`, via the relief-sally
  branch of `respond_stand_battle` (relieving side = Marcher + Sallyer
  lanes = Attacker; besieger = Defender; the conceded flag is set on the
  per-lane sides for Strike-halving AND on the pooled result sides for
  the aftermath's "Conceded then Retreated" treatment).
The Storm's Attacker-only concede (4.5.2) is unchanged (already correct).
The pre-declared (vs fully interactive) model is the only simplification.

**Revisit:** when `resolve_battle` / `resolve_relief_sally` are made
re-entrant (would allow a true interactive per-Round Attacker-then-Defender
concede prompt instead of the pre-declared rounds).


## DECISION-002 — Reactive (round-stepped) Concede via an interactive mode

**Date:** 2026-06-02
**Type:** [INTERPRETATION]
**Trigger:** Follow-up to DECISION-001 — the pre-declared concede commits the
Round up front and cannot be decided reactively after watching earlier
Rounds, which 4.4.2 ("at the start of each Round … may declare") permits.

**Decision:** Add a true reactive Concede the Field as an opt-in interactive
mode. With `interactive_concede` on the battle action, the Battle is resolved
one Round at a time: at the start of each Round it pauses on a
`battle_concede` PendingDecision (waiting on the active side), and the
response declares this Round's `attacker_concede` / `defender_concede`. The
driver therefore decides Concede reactively, having seen the prior Rounds.
The synchronous default path (with pre-declared concede, DECISION-001) is
unchanged, so existing tests and self-play are unaffected. The two paths
share `_battle_one_round` and a single per-engagement aftermath, and
interactive-no-concede is verified byte-identical (same RNG, same result)
to the synchronous resolution.

**Scope:** ALL four Battle-family resolvers now support interactive
reactive concede, each via its own per-Round pending decision:
- open-field Battle (`cmd_battle`) and besieged-Lord Sally (`cmd_sally`)
  -> `battle_concede` (either side, from Round 1);
- Storm (`cmd_storm`) -> `storm_concede` (S10 Attacker-only, Round 2+);
- Relief Sally (`respond_stand_battle`) -> `relief_concede` (either side,
  from Round 1).
The per-Lord lane state of Storm (`_storm_setup`/`_storm_run_round`/
`_storm_finalize`) and Relief Sally (`_ReliefState` with lane-name-keyed
Forces/Routed) was refactored into serializable contexts shared by the
synchronous and interactive paths, so the two cannot diverge; interactive-
no-concede is verified result-identical to synchronous across seeds. The
pre-declared `*_concede_round` arguments (DECISION-001) remain on the
synchronous path. The harness surfaces each per-Round choice in legal_moves;
self-play never opts into interactive mode.

**Revisit:** never (full reactive coverage achieved).


## DECISION-003 — one_round_only Strikes fire on Round 1 (owner round-choice)

**Date:** 2026-06-02
**Type:** [HOUSE RULE]
**Trigger:** Rules-accuracy audit (sweep for simplifications at the expense
of accuracy).

**Decision:** Strikes flagged `one_round_only` (Javelins / Harbah C7/M3/M6
"any 1 Battle Round") fire on Round 1 — full-strength, before any Rout — and
are dropped thereafter, rather than letting the owner choose which Round.

**Reasoning:** The rules let the owner pick the single Round; Round 1 is the
maximal-effect choice a rational player picks in the overwhelming majority of
cases, so the deviation is minimal. Modeling owner round-choice is a
per-combat policy on the Javelins-marker subsystem (a broader piece of work,
also tracked in RULES_QUESTIONS). This is the ONLY remaining simplification
the audit found that trades any rules accuracy.

**Scope:** `_resolve_step` one_round_only handling (src/almoravid/battle.py).
Everything else flagged with "simplification/stub/approximate/not-yet"
comments was verified to be STALE wording over code that is actually
rules-complete (per-Lord losses, C8 shared cap, C10 Taifas-box drain, full
Table-4 Conquest, Enforcing-Parias shift, multi-Lord Battle, M10 Evade,
C21 Surrender auto-success); those comments were corrected.

**Also fixed by the audit (not a deviation — a genuine bug):** M16/M17
Revolt "no Muster of OR BY <Lord>" — the ban now also blocks the named Lord
from acting as the Levying Lord (it previously only blocked being Mustered).

**Revisit:** when the Javelins-marker subsystem gains owner round-choice.


## DECISION-004 — Residual simplifications after the full rulebook reconciliation

**Date:** 2026-06-02
**Type:** [INTERPRETATION] / [HOUSE RULE]
**Trigger:** Line-by-line reconciliation of the Rules of Play against the
implementation (see RECONCILIATION.md). All clear rules-accuracy GAPS found
were fixed (Ravage re-target, Forage Friendly-Stronghold, Supply/Tax dynamic
Seats, FPD Disband sweep, Curias box-6 threshold, Ruined Land Parias Coin,
Scenario D start-Bypass, Crossbows -1 vs Armor, Hills full-Battle duration,
Sally all-Besieged-Lords, Battering Ram). The items below remain as
deliberate, documented deviations — they are choice-model abstractions or
ambiguous readings, not wrong-outcome bugs.

**Interactive-choice abstractions** (the engine resolves deterministically
instead of prompting the controlling player; reactive interaction exists for
Concede via the opt-in interactive_concede mechanism but not for these):
- 4.9.4 Wastage: the discarded Asset/Capability is auto-picked (largest
  Asset stack, else a This-Lord card) rather than chosen by the player.
- 4.8.1 Greed: the optional discard of Mules in excess of those Fed is not
  offered as a choice.
- 4.8.2 / 6.3.1: voluntary Pay (3.2) during the per-card Feed/Pay/Disband and
  the Winter-Disband Pay sub-step are not exposed as actions (mandatory
  Disband IS applied; a player cannot pre-empt it by paying).

**Defensible per-card defaults** (rules grant "any 1 Round"/owner choice;
the engine uses a fixed sensible default):
- M7 Spear Wall and one-round Javelins fire in Round 1 (see DECISION-003).
- C8 Cantador's +4 is a single side-wide budget spent in Front order rather
  than confined to the one Lord holding the card; bounded at +4 either way.
  (C8 is modelled as a this_levy_events hold, with no per-Lord owner.)
- 4.4.2 Flanking targets the largest unopposed enemy Front Lord rather than
  the positionally "closest"; affects only which enemy a flanker is routed
  against in a multi-Lord Battle.

**Ambiguous reading:**
- 4.5.1 Siege / 4.7.3 Tax "use all actions of his Command card" is read as
  "ends the card" (consumes remaining actions) rather than "requires a fresh
  card"; a Lord may thus take a cheaper action first and then Siege/Tax.

**Edge case:**
- 3.1.1: C18 Milites "removed" permanence is not separately tracked (C18 is
  modelled as a board-edge Capability + immediate Event); it does not
  re-enter the draw deck in normal play.

**Scope:** combat (battle.py), commands/economy (campaign.py), end-game.
**Revisit:** when an interactive decision layer is added for non-combat
choices (Wastage/Pay/Greed), or per-Lord capability ownership is tracked
(C8), or Battle Array geometry is modelled for Flanking adjacency.
