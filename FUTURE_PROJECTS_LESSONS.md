# Levy & Command Harness Development: Bug-Pattern Catalog

**Status:** Lessons learned from building a Python rules harness for
GMT's *Nevsky: Teutons and Rus in Collision, 1240–1242* (Second
Edition). Across 177 probe rounds + ~300 self-play sessions, **114
distinct bugs (SMOKE-001 through SMOKE-114)** were found and fixed.

This document organizes those 114 bugs by audit pattern so engineers
building harnesses for the rest of the Levy & Command series (*Almoravid*,
*Inferno*, *Plantagenet*, *Pendragon*, etc.) can:

1. Recognize each pattern as it appears in their code,
2. Run pre-built audits against the patterns systematically,
3. Write regression tests that prove each pattern is closed,
4. Avoid burning rounds rediscovering the same family of mistakes.

The patterns are ordered roughly by frequency in the Nevsky project.

---

## How to use this document

For each pattern below, you'll find:

- **Pattern name + one-line shape**
- **Detection heuristic** — concrete grep / inspection target
- **Examples from Nevsky** — SMOKE numbers + a brief description
- **Audit checklist** — questions to walk through for your own code
- **Pre-built test ideas** — regression patterns that catch the family

If you implement nothing else from this guide, run the **Audit
checklists** for patterns 1, 2, 8, and 11 — those four account for
**60+ of the 114 Nevsky bugs**.

---

## Pattern 1: State-set-but-unreachable

**Shape:** Code sets a state flag, registers a side-effect, or stores
a target for a later step — but no caller can reach the step that
uses it. The agent gets stuck or the rule silently doesn't fire.

**Detection heuristic:**
```
grep -n "state\.\w*\.\w* = \(True\|<target_id>\)" src/
# For each setter, find readers. Setters with zero readers, OR
# readers gated on a condition that never becomes true given the
# setter's caller, indicate this pattern.
```

**Examples from Nevsky:**

- **SMOKE-093 to SMOKE-100 (cluster):** `apply_losses_rolls` had
  branches for `"storm_attacker"` / `"withdrew"` / etc. loss_states,
  but no caller invoked it for those branches. `routed_units`
  accumulated invisibly across engagements.
- **SMOKE-095:** `clear_routed_pile()` was defined but never called;
  routed_units leaked across the Lord lifecycle.
- **SMOKE-100:** `cmd_sail` accepted `discard_excess_provender` arg
  parallel to `cmd_march`, but the flag's effect — voluntary asset
  discard before Ship-budget check — wasn't implemented for the Sail
  path.
- **SMOKE-106 / SMOKE-107:** Legate Use 2c and Veche Option C both
  set `target.lordship_used = 0` to grant an "extra Muster" during
  Call to Arms, but the Muster handlers required
  `levy_step == "muster"`. The agent literally could not exercise the
  granted Muster.
- **SMOKE-109:** `finalize_plan` set `plan_complete_t = True` but did
  not switch `state.meta.active_player`, leaving Russian's Plan moves
  unreachable.
- **SMOKE-110:** Feed/Pay/Disband didn't auto-fire when actions
  exhausted naturally via simple commands. The next `command_reveal`
  silently skipped the 4.8 cycle.
- **SMOKE-111:** `cmd_march` set `combat_pending` with
  `pending_response_by = defender_side` but kept `active_player` on
  the attacker. legal_moves returned zero moves because side =
  active_player and combat_pending blocked attacker actions.
- **SMOKE-112 / SMOKE-113 / SMOKE-114:** Immediate event resolvers
  raised IllegalAction when the target was unreachable (e.g., R10
  Batu Khan with Andreas permanently removed). Per rule convention
  the event should discard with no effect; pre-fix the agent could
  not progress.

**Audit checklist:**

- [ ] For every action handler that sets state X, identify every
      reader of X. If X is read in a branch gated on condition C,
      verify a caller can put the state into condition C.
- [ ] When a phase transition (Plan → Command, Levy → Campaign, etc.)
      is gated on flags from BOTH sides, ensure both flags can be
      set. Check whose turn it is after the first side's flag flips.
- [ ] After every state-mutating handler, ask: what's the next
      legal action for whoever's turn it now is? If the legal_moves
      enumerator can't surface that action, you have this bug.
- [ ] For "promise" methods (extra Muster, extra action, etc.),
      trace from the grant through the redemption. Both ends must be
      wired.

**Pre-built test ideas:**

- **Self-play stall test:** Run an automated self-play agent that
  picks the highest-priority legal move. Record any "zero legal
  moves" condition that isn't a game-end. Every one is a
  state-set-but-unreachable bug.
- **Trace-coverage test:** For each state field that's set
  conditionally, write a test that drives the game into a state
  where the field has every possible value AND verify a follow-up
  action reads it. Use coverage instrumentation.

---

## Pattern 2: Mirror gaps

**Shape:** Two similar code paths (loser/winner, attacker/defender,
March/Sail, summer/winter) — one handles a side-effect correctly,
the other forgets. Often the second path was added later as a
copy-paste with the side-effect omitted.

**Detection heuristic:**
```
grep -B 2 -A 10 "<canonical-side-effect>" src/ | less
# Look for places the side-effect appears; then search for sibling
# branches that don't have it.
```

**Examples from Nevsky:**

- **SMOKE-098 / SMOKE-099:** Battle aftermath restored
  `winner.routed_units → forces` (per "winner doesn't suffer Losses").
  Storm aftermath and Sally aftermath had the same shape but the
  restore code was missing.
- **SMOKE-101 (4 sub-bugs):** `apply_ransom` was called by 2 of the
  6 Lord-removal branches across `_h_stand_battle`, `_h_cmd_storm`,
  `_h_cmd_sally`. The other 4 (defender-no-retreat, failed-Sally
  zero-forces, Sally-win zero-forces, Sally-win no-retreat) forgot
  to call ransom.
- **SMOKE-100:** `cmd_march` accepted `discard_excess_provender`;
  the symmetric `cmd_sail` path didn't.
- **SMOKE-103:** Pay-step shift in `_shift_service_right` cascaded
  the shift onto on-Calendar vassal markers under
  `advanced_vassal_service`. Retreat shift in
  `apply_retreat_service_shift` was missing the same cascade.
- **SMOKE-105:** R4 Raven's Rock Walls only fired when Teutonic was
  the Battle attacker. Card text "may play on either Attack or
  Defense" — the Russian-as-attacker case (Teutonic defender Strikes
  vs Russian units) was missed.

**Audit checklist:**

- [ ] For every side-effect that's role-specific (winner/loser,
      attacker/defender, T/R), check that ALL roles where the effect
      applies have the code.
- [ ] For every command that has an entire-card sibling (March/Sail,
      Storm/Sally), check that all auxiliary arg handling and
      cleanup is symmetric.
- [ ] When a card text says "may play if X or Y", verify the
      implementation accepts BOTH X and Y, not just one.

**Pre-built test ideas:**

- For every aftermath function with role-dependent side-effects,
  parameterize a test over all (winner, loser) combinations and
  verify each side-effect.
- For every command pair that should behave symmetrically, write a
  test that exercises both with the same external state and asserts
  the same resulting side-effects.

---

## Pattern 3: Stale per-Lord state flags

**Shape:** A flag on a Lord (`moved_fought`, `in_stronghold`,
`just_arrived_this_levy`, `lordship_used`, capability per-card-use
counters, `routed_units` pile, etc.) is set but not reset at the
correct scope (per-card, per-Levy, per-Campaign, per-lifecycle). It
leaks into future contexts.

**Detection heuristic:**
```
grep -n "lord\.\w*_\(used\|done\|set\|fought\|arrived\)" src/
# For each flag, find: (a) where it's set, (b) where it's read,
# (c) where it's reset. Look for missing reset paths.
```

**Examples from Nevsky:**

- **SMOKE-001:** FPD processed removed Lords whose `moved_fought`
  was stale.
- **SMOKE-035:** `just_arrived_this_levy` not reset on Campaign →
  next Levy transition; Lords kept being blocked from spending
  Lordship.
- **SMOKE-036:** `in_stronghold` not cleared on Lord movement to a
  new Locale; legal_moves and Battle Array misread Lord position.
- **SMOKE-037:** Re-Muster (disbanded → mustered) didn't clear
  stale `in_stronghold`, `first_march_used_this_card`,
  `raiders_used_this_card`.
- **SMOKE-095:** `routed_units` leaked across Lord lifecycle
  (Disband at limit → re-Muster).

**Audit checklist:**

- [ ] List every per-Lord boolean / counter flag. For each, document
      its expected scope: per-action, per-card, per-Levy, per-
      Campaign, per-lifecycle.
- [ ] For each scope, identify the canonical reset point. Verify
      each scope's reset path clears all flags scoped at that level
      and below.
- [ ] Pay special attention to: Disband → re-Muster cycle, Lord
      removal (permanent), Levy → Campaign transition, Campaign →
      Levy transition, end-of-Card FPD.

**Pre-built test ideas:**

- For each flag, write a "round-trip" test: set the flag in a
  realistic context, force the scope transition, verify the flag
  resets.
- Run a long self-play and assert at every transition boundary that
  no per-card flags survive into the next card.

---

## Pattern 4: Parallel Ways edge cases

**Shape:** The map graph supports multiple Ways (Trackway, Waterway,
Sea) between the same pair of locales. The code assumes one Way per
locale-pair and silently picks the first/last one inserted, missing
the agent's intended Way or applying the wrong Way's mechanics.

**Detection heuristic:**
```
grep -n "for w in load_ways\|way_type" src/
# Find every place the code iterates Ways or selects a way_type.
# Anywhere it `break`s on the first match or uses a dict keyed by
# (a, b) without way_type, suspect this pattern.
```

**Examples from Nevsky (in this map: 1 parallel-Way pair —
dorpat↔odenpah trackway+waterway):**

- **SMOKE-047:** Supply Transport-Way compatibility check used the
  last-inserted way_type, so a Boat user blocked a route that had a
  parallel Waterway.
- **SMOKE-067 / SMOKE-068:** `cmd_march` and `_h_avoid_battle`
  ignored agent's `way_type` arg; took the first match.
- **SMOKE-069 / SMOKE-071:** Battle/Sally aftermath Conceded-and-
  Retreated Spoils computed Unladen Transport along the wrong Way
  type.

**Audit checklist:**

- [ ] Identify every locale-pair with > 1 Way in your map data.
- [ ] For every code path that iterates Ways or selects a way_type,
      check whether the agent can specify which Way. If not, add a
      `way_type` arg.
- [ ] Any code keyed by `(a, b) → way_type` (single value) should
      become `(a, b) → set[way_type]`.

**Pre-built test ideas:**

- For each parallel-Way pair, write a test that:
  - Marches/Sails with explicit way_type=trackway,
  - Then with way_type=waterway,
  - Verifies the harness honors the agent's choice.

---

## Pattern 5: Castle / overlay markers on base locales

**Shape:** A Capability or Event places a marker that overlays a
locale's base type with different mechanics (e.g., T17 Stonemasons
converts a Fort/Town to a Castle for Walls/Garrison purposes).
Lookups that hardcode the static type list miss the overlay.

**Detection heuristic:**
```
grep -n "static\[.*\]\[\"type\"\] in (" src/
grep -n "locale.*\(fort\|town\|city\|castle\|bishopric\)" src/
# Anywhere code switches on static locale type and the list omits
# the overlay-introduced category, suspect this pattern.
```

**Examples from Nevsky:**

- **SMOKE-040:** Castle marker didn't flip color on Conquest.
- **SMOKE-054:** Withdraw capacity didn't honor Castle overlay.
- **SMOKE-065 / SMOKE-066:** `_effective_stronghold` returned None
  for Castle-overlay-on-Town; Forage at friendly Castle-on-Town
  rejected in non-Summer.
- **SMOKE-073 / SMOKE-074 / SMOKE-075:** T15 Mindaugas Russian-
  Stronghold check + Storm preview + Siege/Storm gate missed
  Castle-on-Town overlays.
- **SMOKE-076 / SMOKE-077:** Stonemasons / Stone Kremlin mutual
  exclusion: each card's "already has this overlay" check missed
  the OTHER overlay color.

**Audit checklist:**

- [ ] List every overlay marker your game has (Castle, Walls+1, …).
- [ ] For each, list every base-type-aware lookup in your code.
      Check each lookup goes through an `_effective_*` helper that
      honors overlays — never a raw `static[loc]["type"]` switch.
- [ ] Audit overlay placement actions for mutual-exclusion against
      every other overlay type.

**Pre-built test ideas:**

- For each overlay, write a test that places the overlay, then
  exercises every game-mechanic that reads the locale's effective
  type (Withdraw capacity, Forage eligibility, Storm walls, etc.)
  and asserts the overlay is honored.

---

## Pattern 6: Off-edge calendar positions

**Shape:** The Calendar has 16 visible boxes, but the rules allow
markers to drift "off the left" or "off the right" of the track.
Code that hardcodes box 1 / 16 as bounds (clamping, indexing,
iteration) silently breaks when markers should land off-edge.

**Detection heuristic:**
```
grep -n "max(1, " src/  # clamp at left edge
grep -n "min(16, " src/  # clamp at right edge
grep -n "boxes\[15\]\|boxes\[-1\]" src/  # last-box lookups
grep -n "off_left\|off_right" src/  # check coverage
```

**Examples from Nevsky:**

- **SMOKE-018:** `_disband_at_limit(new_box=0)` silently wrapped to
  box 16 via Python's negative-index.
- **SMOKE-057:** Service markers off right edge lived in
  `off_right_service`, NOT `off_right` (which is for cylinders);
  the wrong list was being consulted.
- **SMOKE-058 / SMOKE-070:** `_shift_service` and
  `apply_retreat_service_shift` clamped at box 1, denying legal
  off-Calendar landings.
- **SMOKE-062:** `_shift_service` left-shift clamp denied the
  "shift one box off Calendar from box 1 or box 16 is allowed"
  allowance from R10/T12/T18 Tips.

**Audit checklist:**

- [ ] Every shift function should support landing in off_left,
      off_right, off_left_service, off_right_service. Read each
      card's Tip for whether it allows off-edge landings.
- [ ] Audit every `_find_*_box` helper to return a sentinel (0 for
      off-left, 17 for off-right) and ensure callers handle it.
- [ ] Separate cylinder and service tracking — they have
      independent off-edge lists.

**Pre-built test ideas:**

- For each shift function, test landings in: box 1 with left shift,
  box 16 with right shift, off-left with right shift, off-right
  with left shift.
- Round-trip: place a marker on off-edge, shift it back on-Calendar,
  verify position is correct.

---

## Pattern 7: Card-text fidelity gaps

**Shape:** The implementation differs from the printed AoW
Reference card text. Usually omits a constraint, misinterprets a
qualifier, or hardcodes a default that doesn't match the rule.

**Detection heuristic:**
```
# Read every card's printed text + Tip against its resolver.
# Look for: "Eligibility", "if X only", "in non-Y", "or", "AND",
# numerical bounds.
```

**Examples from Nevsky:**

- **SMOKE-029:** Capability Levy ignored `capability_eligibility`
  (printed Lord coats of arms).
- **SMOKE-046:** Sail Ship requirements lookup ignored printed
  Cogs/Lodya rules.
- **SMOKE-048:** Supply Transport-count rule wasn't enforced.
- **SMOKE-050:** Sally defenders received Siegeworks as Walls per
  4.5.3 — missing.
- **SMOKE-052:** R12/R14 Russian Raiders multi-use-per-card flag
  not honored.
- **SMOKE-053:** T13 Heinrich Curia hold disbanded Heinrich
  permanently instead of via 3.3.2 at-limit Disband.
- **SMOKE-059:** Summer Crusaders Muster gate missed "only in
  Summer" Tip.
- **SMOKE-060:** T11 Crusade Summer auto-free-Muster missing.
- **SMOKE-083:** T18 Swedish Crusade ignored event_eligibility
  target list.
- **SMOKE-102:** T1 Grand Prince ignored "furthest right Service"
  Tip.
- **SMOKE-104:** R17 Veliky Knyaz Tax forced single Transport type
  vs rule "any two Transport".
- **SMOKE-108:** T2 Torzhok default asset_order excluded Ship.

**Audit checklist:**

- [ ] For each card, read the printed text + Tip word-by-word
      against the resolver. Underline every qualifier, conjunction,
      eligibility constraint, and numerical bound.
- [ ] Pay close attention to: "either / or" (allow both), "and"
      (require both), "may" (optional), "must" (required), "if
      Defending" (role gate), "in non-Winter" (season gate).
- [ ] For each constraint, write a test that violates it and
      asserts IllegalAction.

**Pre-built test ideas:**

- One test class per card, with one test method per qualifier in
  the printed text. Skip and re-read the card if the test seems
  hard to write — that often means the implementation conflated two
  rules.

---

## Pattern 8: Lifecycle leaks on Lord removal / disband

**Shape:** When a Lord is permanently removed or Disbanded, some
piece of associated state (vassals, capabilities, calendar markers,
stack pointers, etc.) isn't cleaned up. Future state reads return
stale references.

**Detection heuristic:**
```
grep -n "_remove_lord_permanently\|_disband_at_limit" src/
# Verify each handler clears ALL fields on the Lord: forces, assets,
# vassals, capabilities, calendar markers (cylinder + service +
# vassal markers), stack pointers (lieutenant_of, has_lower_lord),
# routed_units, side-effect triggers (Legate auto-removal, etc.).
```

**Examples from Nevsky:**

- **SMOKE-033:** Marshal/Lieutenant stack pointers not cleared on
  Lord removal; surviving Marshal still believed it had a Lower
  Lord.
- **SMOKE-038:** Vassal Service markers not removed from Calendar
  on disband.
- **SMOKE-087 / SMOKE-088:** Permanent Lord removal and
  `_disband_at_limit` didn't trigger Legate auto-removal per 1.4.1.
- **SMOKE-095:** `routed_units` pile not cleared on permanent
  removal.

**Audit checklist:**

- [ ] List every persistent piece of state attached to a Lord.
      Tabulate which removal/disband paths must clear which fields.
- [ ] Audit each removal handler against the table — be paranoid.
- [ ] Include OFF-MAP triggers (Legate at this Lord's locale,
      Marshal stack on this Lord, Vassal markers on the Calendar).

**Pre-built test ideas:**

- Build "remove every Lord in turn" stress test that asserts the
  full state remains consistent (no dangling references, no stale
  flags, no orphaned markers).

---

## Pattern 9: Rule-cite-but-no-enforce

**Shape:** A comment in the source cites a rule, suggesting the
constraint exists in mind, but the actual validation/enforcement
code is missing.

**Detection heuristic:**
```
grep -rn "per [0-9]\+\.[0-9]\+\|rule [0-9]\+\.[0-9]\+\|4\.[0-9]\." src/
# Read each cited rule. Verify the code BELOW the comment actually
# implements the rule.
```

**Examples from Nevsky:**

- **SMOKE-041:** Marshal gate cited "4.3.1 Marshal may take a group
  March" but didn't enforce it; non-Marshal could bring co-marchers.
- **SMOKE-046 / SMOKE-048:** Sail Ship requirements cited 4.7.3 but
  weren't validated.
- **SMOKE-049 / SMOKE-067:** Way-type constraint cited but agent's
  way_type arg ignored.
- **SMOKE-081:** Field Organ + Bridge target validation cited but
  not implemented.

**Audit checklist:**

- [ ] Grep for every `rule N.N.N` citation in comments. For each,
      verify the code 2-30 lines below implements the cited
      constraint, not just gestures at it.
- [ ] Special suspicion: comments that say "should" or "must" but
      no `if … raise IllegalAction(…)` follows.

**Pre-built test ideas:**

- For each cited rule, write a "violate it" test that constructs
  the rule-violating state and asserts IllegalAction is raised.

---

## Pattern 10: No-target-no-op events

**Shape:** An immediate event card has an implied "if target is
unavailable" branch (the event has no effect, discard). The
resolver raises IllegalAction instead, making the card
unresolvable.

**Detection heuristic:**
```
# For every immediate-event resolver:
# 1. Identify the target it shifts/targets.
# 2. Check what happens if the target is removed / off-edge / not
#    on Calendar / etc.
# 3. If the resolver raises, ensure the rule says it should — many
#    immediate events should silently no-op.
```

**Examples from Nevsky:**

- **SMOKE-112:** T14 / R18 Bountiful Harvest raised when no
  Ravaged marker existed.
- **SMOKE-113:** R10 Batu Khan raised when Andreas off-Calendar.
- **SMOKE-114:** R9 Osilian Revolt raised when no eligible Service
  marker at box >= 2.

**Audit checklist:**

- [ ] For each immediate event, identify ALL targets it can act on.
- [ ] Per card Tip, determine whether the rule requires a target or
      whether absence-of-target = no effect. Most "On Calendar,
      shift X" cards follow the latter convention.
- [ ] Add a pre-flight check that returns `{"no_op": True, ...}`
      when no rule-valid target exists.

**Pre-built test ideas:**

- For each event with implied "if available" semantics, write a
  test that removes all valid targets and asserts the event no-ops.

---

## Pattern 11: Active-player / turn-order desync

**Shape:** A state transition changes whose move is "next" but
forgets to update `state.meta.active_player` (or your equivalent).
The legal-moves enumerator uses active_player as its key, so the
correct side's moves aren't surfaced.

**Detection heuristic:**
```
grep -n "state.meta.active_player\s*=" src/
# For every place active_player is changed, ensure it matches the
# rule-defined next-actor.
# For every state mutator that changes whose turn it is, verify the
# mutator also updates active_player.
```

**Examples from Nevsky:**

- **SMOKE-109:** `finalize_plan` didn't switch active_player to
  the other side when only one had finalized.
- **SMOKE-111:** `cmd_march` set combat_pending owed by defender
  but didn't switch active_player; legal_moves returned 0.

**Audit checklist:**

- [ ] For every action that ends a step / triggers a response /
      passes the baton, verify active_player is set correctly
      afterward.
- [ ] Pay extra attention to multi-side ratification points:
      "Both sides must finalize before…", "Defender must respond
      to attacker's…", "T then R do X".

**Pre-built test ideas:**

- For each baton-passing handler, write a test that calls it as one
  side and asserts active_player is the other.
- Run self-play and instrument: every call to legal_moves that
  returns 0 moves while not in a terminal state is a desync bug.

---

## Pattern 12: Cap / floor not enforced uniformly

**Shape:** A numerical cap (e.g., per-Asset 8-cap, per-side VP cap
of 17.5, off-edge clamp at 0) is enforced in some code paths but
not others. The agent can accumulate beyond the cap through the
unguarded path.

**Detection heuristic:**
```
grep -n "min(8, \|max(0, \|17\.5\|VP_CAP" src/
# Make sure every asset-add and every VP-mutation funnels through
# the capping logic.
```

**Examples from Nevsky:**

- **SMOKE-025:** VP cap of 17.5 (Rule 5.3) never enforced — sides
  could exceed.
- **SMOKE-027:** Liberation could produce negative VP (no floor).
- **SMOKE-032:** Spoils transfers ignored 1.7.3 per-asset 8-cap.

**Audit checklist:**

- [ ] List every cap/floor constraint in the rules. Identify ALL
      code paths that modify the underlying value. Verify each path
      goes through the cap/floor enforcement.
- [ ] Add defense-in-depth: also clamp at "read" time
      (`determine_scenario_winner` does this for the VP cap).

**Pre-built test ideas:**

- Stress test that drives a side to the cap from many directions
  and asserts the cap holds.

---

## Pattern 13: Per-window once-only flags not reset

**Shape:** A flag tracks "this side has acted once this Call to Arms
/ this Card / this Levy". The set is wired but the reset at the
window boundary is missing.

**Detection heuristic:**
```
grep -n "acted_this_call_to_arms\|once_per_card\|_used_this_card" src/
```

**Examples from Nevsky:**

- **SMOKE-090:** `_h_legate_arrives` didn't consume the once-per-
  CtA slot.
- **SMOKE-092:** R8/R9 Sea-Trade fired multiple times per Call to
  Arms because the per-card flag wasn't reset at CtA boundary.

**Audit checklist:**

- [ ] Identify every "once-per-window" rule. Find the set point
      and the reset point. Verify they're both wired.
- [ ] Window boundaries that often need explicit reset:
      Card → next Card, Levy step → next Levy step, Levy → Campaign,
      Campaign → Levy.

---

## Pattern 14: Capability scope mismatches (this-lord vs side-wide)

**Shape:** A Capability card has two scopes — `this_lord` (tucked
under one specific Lord) vs `side_wide` (in `capabilities_in_play`).
Lookup helpers that don't filter by scope can fire a side-wide card
through a `this-lord` lookup or vice versa.

**Detection heuristic:**
```
grep -n "this_lord_capabilities\|capabilities_in_play" src/
# Verify each lookup filters cards by their canonical scope from
# cards.json.
```

**Examples from Nevsky:**

- **SMOKE-016:** `any_capability` was hardened to filter by
  `capability_scope` so a misplaced card doesn't fire through the
  wrong path.

**Audit checklist:**

- [ ] Audit every `has_*_capability` helper. Each must filter by
      the card's canonical scope from your card data.
- [ ] Audit Capability Levy paths to ensure cards always go into
      the correct list per scope.

---

## Recommended testing methodology for Levy & Command

Based on what found bugs in Nevsky:

### Tier 1 — Static probing (covered ~70% of bugs)

Pick a code area (one command, one event, one phase transition).
Read the rules + harness side-by-side. Look for:
- Comments citing rules without enforcement (Pattern 9)
- Branches in switch-like structures (Pattern 1, 2)
- State flags set but not reset (Pattern 3)
- Lookups by static type that miss overlays (Pattern 5)
- Off-edge calendar positions (Pattern 6)

Run this for every Command, every Event, every Capability, every
Phase. Budget: ~150 rounds for a Nevsky-sized game.

### Tier 2 — Self-play sweep (covered ~20% of bugs)

Build a greedy agent that:
1. Queries `legal_moves` each step
2. Picks the highest-priority action with concrete args
3. Has fallback chains for "moves that look legal but fail"
4. Populates event-specific args from current state

Run 6 scenarios × 50 seeds. Triage any:
- "no_legal_moves" outcome that isn't game-end → Pattern 1 or 11
- Unhandled IllegalAction → Pattern 7 or 9
- Run that doesn't terminate → Pattern 1

### Tier 3 — Rule diff (small marginal returns after Tier 1+2)

Read the printed reference word-by-word against the code one final
time. Focus on rare events and edge-case cards. Budget: ~6 hours
for a thorough sweep at this stage.

### Tier 4 — Property-based testing (not yet attempted in Nevsky)

Use Hypothesis or similar to fuzz:
- Force counts (random 0-8 of each unit type)
- Asset amounts (random within cap)
- Calendar positions (random across all 16 boxes + 4 off-edges)
- Random Lord assignments to Locales

Then run a small number of plausible action sequences and assert
invariants. Likely surfaces bugs in rare state combinations.

---

## Summary by SMOKE count

Of 114 SMOKEs in Nevsky:

| Pattern | Count | Examples |
|---|---|---|
| 1. State-set-but-unreachable | 23 | 093–100, 106, 107, 109–114 |
| 2. Mirror gaps | 11 | 098, 099, 100, 101 (×4), 103, 105 |
| 3. Stale per-Lord flags | 8 | 001, 035, 036, 037, 095 |
| 4. Parallel Ways edge cases | 6 | 047, 067, 068, 069, 071 |
| 5. Castle / overlay markers | 9 | 040, 054, 065, 066, 073–077 |
| 6. Off-edge calendar | 7 | 018, 057, 058, 062, 070 |
| 7. Card-text fidelity gaps | 16 | 029, 046, 048, 050, 052, 053, 056, 059, 060, 083, 102, 104, 108 |
| 8. Lifecycle leaks | 6 | 033, 038, 087, 088, 095 |
| 9. Rule-cite-but-no-enforce | 8 | 041, 046, 048, 049, 067, 081 |
| 10. No-target-no-op events | 3 | 112, 113, 114 |
| 11. Active-player desync | 2 | 109, 111 |
| 12. Cap / floor not uniform | 4 | 025, 027, 032 |
| 13. Per-window once-only flags | 2 | 090, 092 |
| 14. Capability scope | 1 | 016 |
| (other / one-off) | ~8 | scenario-specific |

Patterns 1, 2, 7, 8 alone account for ~60 of the 114. Prioritize
those audits first.

---

## Final note: this is iterative

Each new probing approach surfaces a new family of bugs. In Nevsky:
- Pass 1 (manual rule diff): found ~85 bugs.
- Pass 2 + self-play (integration): found 14 more.
- Self-play with smart event-arg population: found 6 more.

Expect the same in your project: budget for multiple passes, with
different techniques per pass. The bugs you don't find with technique
N are mostly found by technique N+1.

---

*Generated from `Nevsky-Harness` repo, 177 probe rounds + 300 self-
play sessions, SMOKE-001 through SMOKE-114. See
`SMOKE_TEST_FINDINGS.md` in the repo for the full per-round log.*
