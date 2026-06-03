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

### Genuine player choices — now exposed as interactive decisions

The rulebook grants the controlling player a free choice at each of these
points. They are now surfaced as PendingDecisions (mirroring the Concede
mechanism), each behind an opt-in flag so that synchronous play, self-play,
and the existing test corpus keep the deterministic default unchanged.

- **4.9.4 Wastage** — `wastage_choice` pending (opt-in `interactive_wastage`
  on `end_campaign`). Christians then Muslims; the owner picks WHICH one
  item each over-stocked Lord discards. Per the rulebook example, ANY single
  Asset (even a count-1 Loot) or a This-Lord Capability is offerable. Omitted
  Lords take the legacy deterministic default (largest Asset stack, else a
  This-Lord card).
- **4.8.1 Greed** — `greed_mule_choice` pending (opt-in `interactive_economy`
  on `end_card`). Each side may discard the unfeedable excess Mules of any
  subset of its eligible Lords before Feed resolves; the default discards
  none (keeps Mules, accepts any Unfed shift).
- **4.8.2 / 6.3.1 voluntary Pay** — `pay_before_disband` pending (opt-in
  `interactive_economy`). After Feed and before the mandatory at-limit
  Disband, Christians then Muslims may Pay (3.2) to shift Service rightward,
  or declare `done`. The default (no voluntary Pay) leaves the mandatory
  Disband intact.
- **4.4.1 "any 1 Round" one-Round effects** — `oneround_timing` pending
  (opt-in `interactive_timing` on the interactive Battle). Before Round 1,
  each owner picks the Round its Javelins (`oneround_round`) and/or M7 Spear
  Wall (`m7_round`) fire; M7 presence and discard are gated to the chosen
  Round in `_battle_one_round`. The default is Round 1 (see DECISION-003).

Synchronous resolution and the deterministic helpers remain the default
when the opt-in flags are absent, so no previously-legal outcome changes.

The one-Round timing prompt is offered only in the open-field interactive
Battle driver; Relief-Sally battles do not surface it, so their M7 / Javelin
effects keep the Round-1 default there (a scope limit, not a rules conflict).

**Scope:** combat (battle.py), commands/economy + end-game (campaign.py),
legal_moves enumeration.
**Revisit:** if a UI wants per-item Wastage prompts or per-Lord Greed
amounts beyond the subset/default options currently enumerated.

## DECISION-005 — Tactical Battle choices: which are player decisions, and how exposed

**Date:** 2026-06-03
**Type:** [INTERPRETATION] / [DEFERRED]
**Trigger:** PR review — "an LLM using the public action interface cannot
fully control tactical choices in a normal field Battle." Audited 4.4.1–.2
against the engine to separate genuine player decisions from
rules-determined resolution.

**Findings (per Rules of Play 4.4.1 REPOSITION/Advance/Center, 4.4.2
Initiative / ASSIGN HITS):**

- **Concede the Field (4.4.2)** — player choice. Exposed: pre-declared
  `*_concede_round` args (DECISION-001) and the reactive `interactive_concede`
  driver, now also for ordinary March-triggered (Stand & Fight) field Battles
  (PR `expose-field-battle-decisions`), at parity with the end-of-card Battle
  and Relief Sally.
- **ASSIGN HITS — "the owner selects which unit will absorb each Hit, Hit by
  Hit" (4.4.2)** — player choice. Exposed as a per-side standing *policy*
  (`weakest_first` / `armored_first`) via the `set_absorption_policy` action
  and the `absorption_policy` arg on combat actions; settable at any time
  (no global pending gate), including between Rounds of an interactive Battle.
  As of this PR it is also surfaced in `legal_moves` during the
  `battle_concede` / `storm_concede` / `relief_concede` decisions so an agent
  can discover it. **[INTERPRETATION]** With only two Protection classes in
  play (armored / unarmored), the two policies span the strategically
  meaningful absorption orders; literal per-Hit ordering beyond that has
  negligible effect and would explode the decision tree, so the policy is
  accepted as a faithful proxy rather than a full Hit-by-Hit prompt. Rule-
  forced cases are still enforced inside resolution regardless of policy:
  Storm Attacker absorbs with Armored first (4.5.2), and the Crossbow firing
  side selects the target (1.3.1).

**Deferred (genuine player choices, currently resolved deterministically,
arise only in MULTI-LORD arrays):**

- **Strike order, Lord by Lord within a step (4.4.2 Initiative)** — the
  Striking side chooses the order; engine strikes in a fixed order.
- **Flanking absorb-before-opposed (4.4.2)** — "A Flanking Lord may absorb
  Hits from a Flanked Lord, at the owner's option"; engine decides
  deterministically.
- **REPOSITION / Advance — add a Reserve Lord to the Front (4.4.1; Storm
  REPOSITION)** — "Attacker then Defender may add one Lord from Reserve to
  the Front"; engine does not surface the optional commitment.
- **Center fill, left-or-right (4.4.2 Center)** — when a Front-center
  position is empty, the owner picks which side Lord slides in; engine
  picks deterministically.

**Decision:** Treat hit allocation as adequately exposed (policy + now
discoverable). The four multi-Lord array/order choices are **[DEFERRED]**:
they only affect Battles with multiple Lords per side and Reserves, and
exposing them interactively is a larger Array-driver change. Recorded here
so the omission is explicit rather than silent. No "true tie" winner
tie-break is a player choice (a real tie clears the field per 4.4 / the
Sagrajas resolver); the only tie-like choices are the multi-Lord
center/Reserve picks above.

**Scope:** combat (battle.py `_resolve_protection_roll` absorb policy),
campaign.py (`_apply_absorption_policy`, `set_absorption_policy`, interactive
battle drivers), legal_moves enumeration.
**Revisit:** when full multi-Lord Array control (Reserve commitment, per-step
Strike order, Flanking absorb option, center fill) is built.

## DECISION-006 — Multi-Lord Array placement choices are now player-controlled

**Date:** 2026-06-03
**Type:** [INTERPRETATION]
**Trigger:** Follow-up to DECISION-005 — implement the multi-Lord Array
choices that DECISION-005 had marked [DEFERRED].

**Decision:** The Array placement choices the rules grant the owner (4.4.2
Reposition / Flanking) are exposed as per-side standing policies in
`state.meta`, set via the `set_array_tactics` action (and surfaced in
`legal_moves` during the `battle_concede` / `storm_concede` /
`relief_concede` decisions). They are consumed by `_reposition_array` and
`_pick_flank_target`, and may be changed between Rounds (no pending gate),
so control is reactive in practice. Defaults reproduce the prior
deterministic behaviour, so no previously-legal outcome changes unless a
side sets a policy.

- **Flanking direction (4.4.2 "center may choose left or right")** —
  `array_flank_choice` = `left` | `right` | `larger` (default). A CENTER
  Front Lord with no directly-opposed Enemy Flanks the chosen side (falls
  back to the larger Enemy when the chosen side is absent). Left/right
  Flankers remain rule-forced to the closest Enemy (center, then far).
- **Center fill (4.4.2 Center)** — `array_center_fill` = `left` (default)
  | `right`. Picks which side Front Lord slides into an empty Front-center.
- **Reserve Advance (4.4.2 Advance)** — `array_reserve_priority`, an ordered
  list of lord_ids deciding which Reserve Lord Advances first into an empty
  Front slot (center-most first). All unrouted Reserves still Advance into
  empty Front positions (Advance itself is mandatory in Battle); only the
  assignment order is the owner's choice.

**Strike order (4.4.2 Initiative) — resolved as a non-choice.** "Striking
Lords choose the order of Strike, Lord by Lord." In this engine all Hits
aimed at the same target Lord (directly-opposed + Flanking strikers) are
summed in halves and rounded ONCE per target (B2, DECISION rule 4.4.2 TOTAL
HITS), and different targets resolve independently, so permuting the
striking Lords' order cannot change the result. Proven by
`test_strike_order_is_outcome_independent`. No prompt is needed.

**Residual [DEFERRED] (genuinely unmodelled, narrow):**
- **Flanking absorb-before-opposed (4.4.2: "A Flanking Lord may absorb Hits
  from a Flanked Lord, at the owner's option")** — the per-pair model
  assigns each target's Hits to that target Lord's own forces; using a
  Flanking Lord to soak Hits for the Flanked Lord would require redirecting
  Hits between Lords and is not modelled.
- **Storm REPOSITION optional commitment (4.4.1: "Attacker then Defender
  MAY add one Lord from Reserve to the Front, up to Stronghold Capacity")**
  — Storm Reserve commitment is governed by the coarse `reposition_attacker`
  / `reposition_defender` flags and takes the first Reserve (`pop(0)`),
  rather than a per-Round optional + which-Reserve owner choice. (Battle
  Advance is correctly mandatory; this is Storm-specific.)

**Scope:** state.py (GameMeta array_* policies), battle.py
(`_reposition_array`, `_pick_flank_target`, `_battle_one_round`,
`_resolve_step_per_pair`), campaign.py (`set_array_tactics`), legal_moves
enumeration.
**Revisit:** if the two residuals above are modelled, or if a fully reactive
per-Round Array-placement prompt is preferred over standing policies.

## DECISION-007 — The two DECISION-006 Array residuals are now implemented

**Date:** 2026-06-03
**Type:** [INTERPRETATION]
**Trigger:** Follow-up to DECISION-006 — implement its two [DEFERRED]
residuals (Flanking absorb-before-opposed; Storm REPOSITION optional /
which-Reserve commitment).

**1. Flanking absorb-before-opposed (4.4.2 APPLY HITS).** Rule: "Hits apply
to the Forces of the opposed, Flanked, or Flanking Enemy Lord. A Player with
a Flanking Lord selects either the Flanking or directly opposed Lord to take
Hits." Exposed as the per-side policy `array_flank_absorb` =
`opposed` (default) | `flanking`, set via `set_array_tactics` and surfaced in
`legal_moves`. In the per-pair resolver (`_resolve_step_per_pair`), when the
target side's policy is `flanking` AND the Hits are aimed at a *directly-
opposed* Lord AND that side has a Flanking Lord (a Front Lord whose Front
position is not opposed by an unrouted enemy), the Hits are redirected to
that Flanking Lord (`_pick_flank_absorber`; the largest qualifying Flanker
when several exist). Default `opposed` reproduces prior behaviour exactly.

  *Scope note:* the redirect applies only to a directly-opposed Lord's Hits
  (the rule's "either the Flanking or directly opposed Lord"); Hits an
  Attacker generates by Flanking still land on the chosen Flank target. The
  "apply remaining Hits to a NEW Flanking situation mid-step" clause (a Lord
  Routing to expose a neighbour) remains the existing per-target model and
  is unchanged.

**2. Storm REPOSITION (4.4.1).** Rule: "In each Storm Round after the first,
Attacker then Defender may add one Lord from Reserve to the Front, up to
Stronghold Capacity." Two choices are now exposed:
  - WHICH Reserve Advances — `_storm_run_round` consults the side's
    `array_reserve_priority` (the same per-side ordered lord_id policy used
    for Battle Advance) via `_storm_reserve_pick`, instead of always the
    first Reserve (`pop(0)`).
  - WHETHER to add (the optional "may") — `cmd_storm` now reads
    `reposition_attacker` as well as the existing `reposition_defender`
    (default True for both), threaded through the synchronous and
    interactive Storm paths. The forced commit when a side's Front is wiped
    ("If all Front Lords Routed, a Reserve Lord must move to Front") still
    fires regardless of the flag.

  *Scope note:* both flags are supplied on the storming side's `cmd_storm`
  action (consistent with how `reposition_defender` already worked); a fully
  separate reactive Defender REPOSITION sub-turn is not modelled.

**Strike order** remains a proven non-choice (DECISION-006).

**Scope:** state.py (`array_flank_absorb`), battle.py (`_pick_flank_absorber`,
`_resolve_step_per_pair`, `_storm_reserve_pick`, `_storm_run_round`),
campaign.py (`set_array_tactics`, `cmd_storm`, `_begin_interactive_storm`),
legal_moves enumeration, state.schema.json.
**Revisit:** if a fully reactive per-Round Array / REPOSITION prompt (each
owner deciding live, with mid-step new-Flanking Hit spill) is preferred over
the standing-policy exposure.
