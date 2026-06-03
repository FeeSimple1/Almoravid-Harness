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


## DECISION-004 — Adjudication of residual reconciliation items

**Date:** 2026-06-02 (revised)
**Type:** [INTERPRETATION] / [HOUSE RULE]
**Trigger:** Line-by-line reconciliation of the Rules of Play against the
implementation (see RECONCILIATION.md). All clear rules-accuracy GAPS were
fixed (Ravage re-target, Forage Friendly-Stronghold, Supply/Tax dynamic
Seats, FPD Disband sweep, Curias box-6 threshold, Ruined Land Parias Coin,
Scenario D start-Bypass, Crossbows -1 vs Armor, Hills full-Battle duration,
Sally all-Besieged-Lords, Battering Ram). Each previously-documented
deviation was then re-checked against the rulebook for a decisive ruling.

### Resolved with a decisive rulebook ruling (now implemented)

- **4.5.1 Siege / 4.7.3 Tax require a FRESH Command card.** The text "uses
  all the actions of his Command card" is read as needing the card's FULL
  actions available — no cheaper action may precede Siege/Tax on the same
  card. Enforced in `cmd_siege` / `cmd_tax` (code `not_fresh_card`) and in
  legal_moves (the action is gated on
  `actions_remaining == effective_command`).
- **4.4.2 Flanking targets the CLOSEST Front Enemy Lord.** Card/rule text:
  a flanker "Strikes the closest Front Enemy Lord"; a center flanker may
  choose left or right. `_pick_flank_target` is now position-aware
  (front_left → center → right, etc.; center prefers the larger wing).
- **C8 Cantador is confined to the ONE holding Lord, with a COMBINED cap of
  4 across Knights and Sergeants.** Card text: "up to four of *that Lord's*
  Knights and Sergeants units." The prior side-wide budget both (a) let the
  +4 spill onto Lords other than the holder and (b) reset per Strike step,
  so Knights (Horse step) and Sergeants (Foot step) could each draw 4 —
  doubling the bonus to +8. Both were genuine over-credits in multi-Lord
  Battles. Now a per-Round `c8_ctx` shares ONE budget of 4 across the Horse
  and Foot Melee steps and applies it only to the holder = the Front
  Christian Lord with the most eligible units (the placement a rational
  player makes). Single-Lord Battles are unaffected (holder is that Lord).
- **C18 Milites is removed from the game when discarded.** Card text:
  "discard removes the card from the game ... removes Event #C18 Runaway
  Slaves with it." Discarded C18 now goes to `decks.removed_from_game` (not
  the discard pile), and `_rebuild_aow_deck` excludes removed cards, so it
  cannot recycle into a later Campaign's draw deck. (Fixed a real recycling
  bug for multi-Campaign / Scenario F play.)

### Genuine player choices — engine default is a legal branch

The rulebook explicitly grants the controlling player a free choice here;
any legal selection satisfies the rules, so there is no single "correct"
ruling to encode. The engine picks a deterministic, always-legal default.
A future interactive decision layer (the Concede mechanism is the model)
could expose these; doing so changes no outcome that is currently illegal.

- **4.9.4 Wastage** ("the owning player could choose to discard a Mule, the
  Loot, or the card" — rulebook example): the engine auto-discards one
  *legal* item (largest Asset stack, else a This-Lord card). Always a valid
  Wastage discard; only the player's free pick is not modelled.
- **4.8.1 Greed**: discarding excess unfeedable Mules is optional ("Lords
  *may* discard"). The default keeps Mules and accepts any Unfed Service
  shift — a legal branch. The beneficial discard is available via the
  `discard_excess_mules` path on the Feed helpers.
- **4.8.2 / 6.3.1 voluntary Pay (3.2)**: optional Pay during the per-card
  and Winter-Disband sub-steps is not exposed as an action; mandatory
  Disband IS applied. A player choosing not to pre-empt Disband is legal.
- **4.4.1 "any 1 Round" one-Round effects** (M7 Spear Wall, one-round
  Javelins): the owner may choose the Round; the engine defaults to Round 1
  (full-strength, max effect). See DECISION-003. Any Round is legal; Round 1
  is a defensible fixed choice.

**Scope:** combat (battle.py), commands/economy (campaign.py), end-game.
**Revisit:** only if an interactive decision layer is added for the
non-combat player choices above (Wastage / Greed / voluntary Pay) or for
the one-Round timing of M7/Javelins.
