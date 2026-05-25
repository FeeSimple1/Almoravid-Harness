# Levy & Command Rules-Engine: Bug & Hazard Guide
**A shared, contributable reference for everyone building a Python rules
harness for a GMT *Levy & Command* (L&C) game.**

This document combines and supersedes two Nevsky-Harness documents
(`FUTURE_PROJECTS_LESSONS.md`, the 14-pattern catalog, and
`CROSS_PROJECT_LESSONS.md`, the audit-technique summary). It is meant to
travel **between** projects — *Almoravid*, *Inferno*, *Plantagenet*,
*Pendragon*, *Nevsky*, and the next title (working name **Henry**) — and
to be **edited in place by each team** as they confirm, refute, or extend
a pattern against their own engine.

> If you are starting Henry (or any new L&C port): read **Part I** and
> **Part II §1** first, wire up the **enumerator/handler round-trip sweep**
> before you write your tenth handler, and skim the rest. The four
> highest-yield hazards (Patterns 1, 2, 7, 8) accounted for ~60 of
> Nevsky's first 114 bugs.

---

## How to use this document

It is organized as a **hazard catalog** plus the **techniques** that
surface each hazard:

- **Part I — Hazard catalog.** 14 recurring bug patterns. Each entry has a
  one-line *shape*, a *detection heuristic* (a concrete grep or inspection
  target), *examples* (labeled by source project + bug ID), an *audit
  checklist*, and *pre-built test ideas*.
- **Part II — Audit techniques & testing methodology.** The enumerator/
  handler divergence problem and the round-trip sweep, argument-domain
  mismatch, the testing tiers, and why different agent styles find
  different bugs.
- **Part III — Defensive idioms worth porting verbatim.**
- **Part IV — LLM-driven play.** The highest-yield detector for a mature
  harness, including the key-free "model plays it in its own sandbox"
  path.
- **Part V — Cross-project advisory log.** Worked examples of one team
  flagging a bug class to the others, with the template for raising your
  own.
- **Part VI — Recent hazards.** The newest Nevsky findings (validated-
  palette era, R219–R225) that extend Parts I–II.
- **Appendices.** Quick-start audit commands, contribution templates, and
  the per-game findings ledger.

Examples are tagged with their origin (e.g. `[Nevsky SMOKE-100]`,
`[Inferno Advisory #2]`, `[Almoravid Q-001]`). When you confirm a pattern
in your own engine, **add your tag** to that pattern's example list — that
is how this file earns its keep across the series.

---

## How to contribute (read before editing)

This file is shared and append-friendly. Four ways to contribute:

1. **Confirm a pattern.** Found this hazard in your engine? Add a one-line
   example to that pattern, tagged `[<Game> <bug-id>]`. This is the most
   valuable contribution — it turns a Nevsky anecdote into a *family*.
2. **Refute or scope a pattern.** If a pattern doesn't apply to your game
   (different map, no Calendar drift, etc.), note it under the pattern as
   `[<Game>: N/A — reason]`. Negative results save the next team time.
3. **Add a new pattern.** Use the template in **Appendix B**. Give it the
   next Pattern number and add a row to the summary table.
4. **Raise a cross-project advisory.** Found a bug class you think every
   sibling should self-check? Use the advisory template in **Appendix B**
   and append it to **Part V**. That is exactly how Inferno's two
   advisories (§Part V) propagated to Nevsky and Almoravid.

Keep the conventions: bias detection heuristics toward concrete greps;
keep examples one line; cite the rule number when you have it; never
delete another team's example — append.

---

# Part I — The hazard catalog

The 14 patterns, ordered roughly by frequency observed in Nevsky. For
each, the *detection heuristic* is the cheapest way to go looking.

## Pattern 1 — State-set-but-unreachable

**Shape:** Code sets a flag, registers a side-effect, or stores a target
for a later step, but no caller can reach the step that consumes it. The
agent stalls, or the rule silently never fires.

**Detection heuristic:**
```
grep -n "state\.\w*\.\w* = \(True\|<target_id>\)" src/
# For each setter, find its readers. Setters with zero readers — or
# readers gated on a condition that never becomes true given the setter's
# caller — are this pattern.
```

**Examples:**
- `[Nevsky SMOKE-093..100]` `apply_losses_rolls` had branches for
  `storm_attacker` / `withdrew` loss-states that no caller invoked;
  `routed_units` accumulated invisibly across engagements.
- `[Nevsky SMOKE-095]` `clear_routed_pile()` defined but never called.
- `[Nevsky SMOKE-106/107]` Legate-Use-2c and Veche-Option-C set
  `target.lordship_used = 0` to grant an extra Muster during Call to Arms,
  but the Muster handlers required `levy_step == "muster"` — the granted
  Muster was unreachable.
- `[Nevsky SMOKE-109]` `finalize_plan` set `plan_complete_t = True` but did
  not switch `active_player`, leaving the other side's Plan moves
  unreachable. (Also Pattern 11.)
- `[Nevsky SMOKE-110]` Feed/Pay/Disband didn't auto-fire when actions were
  exhausted via simple commands; the next reveal skipped the 4.8 cycle.
- `[Nevsky SMOKE-111]` `cmd_march` set `combat_pending` owed by the
  defender but kept `active_player` on the attacker; `legal_moves`
  returned zero. (Also Pattern 11.)
- `[Plantagenet immediate-events]` Immediate Arts of War Events (3.1.3) were
  drawn, returned to the deck, and tagged "resolved" with the effect
  "applied by the consumer" — but no caller resolved them and `legal_moves`
  never offered `play_event`, so the effect silently never fired on every
  2nd-or-later Levy. Fix: the draw queues immediates on `pending_events`
  (the Levy can't advance while non-empty), the enumerator offers a
  `play_event` per pending Event, and resolution returns the card to the
  deck and advances. (Also Pattern 10 — the precondition-unmet half.)
- `[Almoravid Advisory #3 under-enum]` Two handlers — `dinars_deposit`
  (Taifas-box deposit, 4.1.4) and `designate_lieutenant` (4.1.3) — were
  fully implemented and accepted by `apply_action`, but the enumerator
  never emitted them, so the action was unreachable through the menu (an
  index-driven player could never select it). Mirror gap on the *offer*
  side; see Part II §1 under-enumeration. Fix added the enumerator entries.

**Audit checklist:**
- [ ] For every handler that sets state X, identify every reader of X. If
      X is read in a branch gated on condition C, verify a caller can put
      the state into C.
- [ ] When a phase transition is gated on flags from **both** sides,
      ensure both flags can be set — check whose turn it is after the
      first flag flips.
- [ ] After every state-mutating handler, ask: what is the next legal
      action for whoever's turn it now is? If the enumerator can't surface
      it, you have this bug.
- [ ] For "promise" mechanics (extra Muster / extra action), trace grant →
      redemption. Both ends must be wired.

**Pre-built test ideas:**
- *Self-play stall test:* run a greedy agent; any "zero legal moves" that
  is not game-end is this bug.
- *Trace-coverage test:* for each conditionally-set field, drive the game
  to a state where the field holds each possible value and assert a
  follow-up action reads it.

## Pattern 2 — Mirror gaps

**Shape:** Two similar code paths (loser/winner, attacker/defender,
March/Sail, summer/winter); one handles a side-effect, the other forgets.
Usually the second path was a later copy-paste with the side-effect
dropped.

**Detection heuristic:**
```
grep -B2 -A10 "<canonical-side-effect>" src/
# Find where the side-effect appears; then look for sibling branches that
# lack it.
```

**Examples:**
- `[Nevsky SMOKE-098/099]` Battle aftermath restored `winner.routed_units
  → forces`; Storm and Sally aftermath had the same shape but missed the
  restore.
- `[Nevsky SMOKE-101 (×4)]` `apply_ransom` was called by 2 of 6
  Lord-removal branches; the other 4 forgot it.
- `[Nevsky SMOKE-100]` `cmd_march` accepted `discard_excess_provender`;
  the symmetric `cmd_sail` path didn't.
- `[Nevsky SMOKE-105]` A "may play on Attack **or** Defense" card fired
  only when one specific side was the attacker.
- `[Plantagenet levy_capability]` The Capability-Levy path placed the card
  on a Lord's mat but the sibling cleanup forgot to remove it from the draw
  pile, so the same card occupied two zones (mat **and** deck). Caught by an
  always-on card-zone invariant (Part III); fixed by removing the Levied
  card from all live deck piles. Mirror gap between "place on mat" and
  "remove from deck."
- `[Almoravid P-3]` The **Battle** aftermath `apply_retreat_aftermath`
  correctly relocated the losing Lord, but the **Sally** path had the same
  shape with the relocation dropped: it early-returned for
  `engagement == "sally"`, applying the Service penalty without moving the
  loser — leaving co-located un-besieged enemies. The exact penalize-but-
  don't-relocate shape of Inferno Advisory #1, in the Battle/Sally mirror.
  Fix in `tests/test_fix_retreat_relocation_p3p4p5.py`.
- `[Almoravid Door B]` Orphaned Siege/Bypass markers were lifted on
  March-out/Disband but the sibling **Sail** (M19) and event-driven
  departure paths (C25 De Vivar, Winter/Curias Disband) forgot — fixed by
  routing every departure through one `_sweep_all_orphaned_markers` backstop
  (see Pattern 8).

**Audit checklist:**
- [ ] For every role-specific side-effect (winner/loser, attacker/
      defender, T/R), confirm **all** applicable roles have the code.
- [ ] For every command with an entire-card sibling (March/Sail, Storm/
      Sally), confirm auxiliary arg-handling and cleanup are symmetric.
- [ ] For "may play if X **or** Y", confirm the implementation accepts
      both, not just one.

**Pre-built test ideas:**
- Parameterize aftermath tests over all (winner, loser) combinations.
- For each symmetric command pair, exercise both from the same external
  state and assert the same side-effects.

## Pattern 3 — Stale per-Lord state flags

**Shape:** A per-Lord flag (`moved_fought`, `in_stronghold`,
`just_arrived_this_levy`, `lordship_used`, per-card-use counters,
`routed_units`) is set but not reset at the right scope and leaks into a
future context.

**Detection heuristic:**
```
grep -n "lord\.\w*_\(used\|done\|set\|fought\|arrived\)" src/
# For each flag find (a) set, (b) read, (c) reset. Missing reset paths are
# the bug.
```

**Examples:**
- `[Nevsky SMOKE-001]` FPD processed removed Lords whose `moved_fought` was
  stale.
- `[Nevsky SMOKE-035]` `just_arrived_this_levy` not reset on Campaign →
  next Levy; Lords stayed blocked from spending Lordship.
- `[Nevsky SMOKE-036]` `in_stronghold` not cleared on movement to a new
  Locale; position misread.
- `[Nevsky SMOKE-037]` Re-Muster (disbanded → mustered) didn't clear stale
  `in_stronghold` / `first_march_used_this_card` / `raiders_used_this_card`.
- `[Almoravid L9b]` `just_arrived_this_levy` was set-but-never-read and
  never reset — the same flag that bit Nevsky at SMOKE-035, surfacing
  independently. Fixed with a per-Levy reset of the flag (and the Muster
  ban it implied) at the Levy→Campaign transition.

**Audit checklist:**
- [ ] List every per-Lord flag/counter and document its scope (per-action,
      per-card, per-Levy, per-Campaign, per-lifecycle).
- [ ] For each scope, identify the canonical reset point and verify it
      clears every flag at that level and below.
- [ ] Be paranoid about: Disband → re-Muster, permanent removal, Levy ↔
      Campaign transitions, end-of-card FPD.

**Pre-built test ideas:**
- Per-flag round-trip: set in a realistic context, force the scope
  transition, assert reset.
- Long self-play: at every transition boundary, assert no per-card flag
  survives into the next card.

## Pattern 4 — Parallel Ways edge cases

**Shape:** The map supports multiple Ways (Trackway, Waterway, Sea)
between the same locale pair. Code assumes one Way per pair and silently
picks the first/last inserted, missing the agent's intended Way or
applying the wrong Way's mechanics.

**Detection heuristic:**
```
grep -n "for w in load_ways\|way_type" src/
# Anywhere it break-s on first match, or keys a dict by (a,b) without
# way_type, suspect this.
```

**Examples (Nevsky map has one parallel-Way pair: dorpat↔odenpah
trackway+waterway):**
- `[Nevsky SMOKE-047]` Supply Transport/Way check used the last-inserted
  way_type; a Boat user blocked a route that had a parallel Waterway.
- `[Nevsky SMOKE-067/068]` `cmd_march` and `_h_avoid_battle` ignored the
  agent's `way_type` arg and took the first match.
- `[Nevsky SMOKE-069/071]` Conceded-and-Retreated Spoils computed Unladen
  Transport along the wrong Way type.

**Audit checklist:**
- [ ] Identify every locale pair with >1 Way in your map data.
- [ ] For every path that iterates Ways or selects a `way_type`, confirm
      the agent can specify which Way; if not, add a `way_type` arg.
- [ ] Any `(a,b) → way_type` (single value) should become `(a,b) →
      set[way_type]`.

**Pre-built test ideas:**
- For each parallel-Way pair: March/Sail with explicit `way_type=trackway`,
  then `=waterway`, and assert the harness honors the choice (cost,
  excess-Provender, Spoils all differ by Way).

## Pattern 5 — Castle / overlay markers on base locales

**Shape:** A Capability or Event overlays a locale's base type with
different mechanics (e.g. Stonemasons converts a Fort/Town to a Castle for
Walls/Garrison). Lookups that hardcode the static type list miss the
overlay.

**Detection heuristic:**
```
grep -n "static\[.*\]\[\"type\"\] in (" src/
grep -n "locale.*\(fort\|town\|city\|castle\|bishopric\)" src/
```

**Examples:**
- `[Nevsky SMOKE-040]` Castle marker didn't flip color on Conquest.
- `[Nevsky SMOKE-054]` Withdraw capacity didn't honor the Castle overlay.
- `[Nevsky SMOKE-065/066]` `_effective_stronghold` returned None for
  Castle-overlay-on-Town; Forage at a friendly Castle-on-Town rejected in
  non-Summer.
- `[Nevsky SMOKE-073..075]` Russian-Stronghold check + Storm preview +
  Siege/Storm gate all missed Castle-on-Town overlays.
- `[Nevsky SMOKE-076/077]` Stonemasons / Stone Kremlin mutual exclusion:
  each card's "already has this overlay" check missed the *other* overlay
  color.

**Audit checklist:**
- [ ] List every overlay marker (Castle, Walls+1, …).
- [ ] For each, confirm every base-type-aware lookup routes through an
      `_effective_*` helper that honors overlays — never a raw
      `static[loc]["type"]` switch.
- [ ] Audit overlay-placement actions for mutual exclusion against every
      other overlay.

**Pre-built test ideas:**
- For each overlay, place it then exercise every mechanic that reads the
  locale's effective type (Withdraw capacity, Forage, Storm walls) and
  assert the overlay is honored.

## Pattern 6 — Off-edge calendar positions

**Shape:** The Calendar has N visible boxes, but markers can drift off the
left or right of the track. Code that hardcodes box 1 / box-max as bounds
(clamping, indexing, iteration) breaks when a marker should land off-edge.

**Detection heuristic:**
```
grep -n "max(1, " src/      # clamp at left edge
grep -n "min(16, " src/     # clamp at right edge (use your box count)
grep -n "boxes\[-1\]" src/  # last-box lookups
grep -n "off_left\|off_right" src/
```

**Examples:**
- `[Nevsky SMOKE-018]` `_disband_at_limit(new_box=0)` silently wrapped to
  the last box via Python negative indexing.
- `[Nevsky SMOKE-057]` Service markers off the right edge live in
  `off_right_service`, not `off_right` (cylinders) — wrong list consulted.
- `[Nevsky SMOKE-058/070]` Shift functions clamped at box 1, denying legal
  off-Calendar landings.
- `[Nevsky SMOKE-062]` Left-shift clamp denied the "shift one box off
  Calendar from box 1 / last box is allowed" allowance from card Tips.

**Audit checklist:**
- [ ] Every shift function should support `off_left` / `off_right` /
      `off_left_service` / `off_right_service`. Read each card's Tip for
      whether it allows off-edge landings.
- [ ] Audit every `_find_*_box` helper to return a sentinel (0 off-left,
      max+1 off-right) and ensure callers handle it.
- [ ] Track cylinders and service markers separately — independent
      off-edge lists.

**Pre-built test ideas:**
- For each shift: landings in box 1 with left shift, last box with right
  shift, off-left with right shift, off-right with left shift.

## Pattern 7 — Card-text fidelity gaps

**Shape:** The implementation differs from the printed Arts-of-War
reference card text — omits a constraint, misreads a qualifier, or
hardcodes a default that doesn't match the rule. (This pattern is not
limited to cards — any place the printed rule text carries a qualifier the
code drops belongs here; see the 5.1 example below.)

**Detection heuristic:**
```
# Read every card's printed text + Tip against its resolver. Underline
# every "Eligibility", "if X only", "in non-Y", "or", "and", numeric bound.
```

**Examples:**
- `[Nevsky SMOKE-029]` Capability Levy ignored printed `capability_
  eligibility` (Lord coats of arms).
- `[Nevsky SMOKE-046]` Sail Ship-requirement lookup ignored printed
  Cogs/Lodya rules.
- `[Nevsky SMOKE-059]` Summer Crusaders Muster gate missed the "only in
  Summer" Tip. (Re-surfaced at the *enumerator* in `[Nevsky SMOKE-162]` —
  see Part VI.)
- `[Nevsky SMOKE-102]` A "furthest right Service" Tip ignored.
- `[Nevsky SMOKE-104]` A Tax card forced a single Transport type vs the
  rule's "any two Transport".
- `[Nevsky SMOKE-108]` A default `asset_order` excluded Ship.
- `[Plantagenet 5.1]` The Campaign-Victory presence test dropped the
  printed "including none in Exile boxes" clause (rule 5.1), so a Lord
  sitting in an Exile box didn't count as present — a faction could be
  ruled eliminated while it still had an Exile reserve. Lesson: a *rules*
  qualifier (not just a card qualifier) is just as easy to drop.
- `[Plantagenet immediate-event disposition]` Rule 3.1.3 says a resolved
  immediate Event "returns to the deck," but the resolver discarded it;
  resolving a drawn Event then double-zoned the card. Card disposition is a
  fidelity constraint too. (Caught by the card-zone invariant — Part III.)
- `[Almoravid Sagrajas resolver]` Four Battle-resolver fidelity gaps the
  Sagrajas minigame exposed: (a) **Javelins**-granting strikes are
  `one_round_only` and must fire in Round 1 only — the code fired them every
  round; (b) Javelin-granting units must be **capped at 4** per Lord; (c)
  **Cantador** (C8) grants "+1 to up to 4 Knights/Serjeants" as a *shared*
  budget, not per-unit (`cantador_budget = [4]`); (d) `StepResolution`
  conflated `rounded_hits` with `units_routed` in log labels. Tests:
  `tests/test_resolver_sagrajas_fixes.py`.
- `[Almoravid L3]` Pay shifted Service to the **LEFT** when rule 3.2.1
  shifts it **RIGHT** — a direction inversion that read the rule backwards
  (critical). A dropped/flipped qualifier on a core mechanic, not a card.
- `[Almoravid F4]` Printed home-Seat pennants were treated as placed Seat
  markers and conferred Friendliness, but per 1.3.1 only *placed* Seat
  markers (Rodrigo / Yusuf-Sir / Cathedrals) do — fixed by splitting
  `printed_seat_lord_ids` from `seat_marker_lord_ids`. Read the rule's
  "placed" qualifier word-by-word.

**Audit checklist:**
- [ ] For each card, read printed text + Tip word-by-word against the
      resolver. Flag every qualifier, conjunction, eligibility constraint,
      numeric bound.
- [ ] Watch "either/or" (allow both), "and" (require both), "may"
      (optional), "must" (required), "if Defending" (role gate), "in
      non-Winter" (season gate).
- [ ] **Apply the same word-by-word read to rules text, not just cards** —
      victory conditions, presence tests, and disposition rules ("return to
      deck" vs "discard") carry droppable qualifiers too. **And to mechanic
      *direction*** — Almoravid L3 shifted Service the wrong way.
- [ ] For each constraint, write a "violate it" test asserting
      IllegalAction.

**Pre-built test ideas:**
- One test class per card, one test method per qualifier. If a test is
  hard to write, re-read the card — the implementation probably conflated
  two rules.

## Pattern 8 — Lifecycle leaks on Lord removal / disband

**Shape:** When a Lord is permanently removed or Disbanded, some
associated state (vassals, capabilities, calendar markers, stack
pointers) isn't cleaned up. Future reads return stale references.

**Detection heuristic:**
```
grep -n "_remove_lord_permanently\|_disband_at_limit" src/
# Verify each clears: forces, assets, vassals, capabilities, calendar
# markers (cylinder + service + vassal), stack pointers (lieutenant_of,
# has_lower_lord), routed_units, off-map triggers (Legate auto-removal).
```

**Examples:**
- `[Nevsky SMOKE-033]` Marshal/Lieutenant stack pointers not cleared; a
  surviving Marshal still believed it had a Lower Lord.
- `[Nevsky SMOKE-038]` Vassal Service markers not removed from the Calendar
  on disband.
- `[Nevsky SMOKE-087/088]` Permanent removal and at-limit Disband didn't
  trigger Legate auto-removal.
- `[Nevsky SMOKE-095]` `routed_units` not cleared on permanent removal.
- `[Almoravid Door B / P-2 / F7]` Siege/Bypass markers orphaned on Disband,
  March-out, combat-elimination, and **Sail** (M19) departures. Centralized
  into `_sweep_all_orphaned_markers(state)`, called at the end of **every**
  `apply_action` (`actions.py`), so no departure path can leave a stale
  marker — including the **empty-besieged-Stronghold** case (the lift rule
  applies even when no defender remains inside). C8 Lieutenant / Lower-Lord
  stack pointers also cleared on disband. See Advisory #2 Door B (Part V).

**Audit checklist:**
- [ ] Tabulate every persistent piece of Lord-attached state vs which
      removal/disband paths must clear which fields.
- [ ] Audit each removal handler against the table — be paranoid.
- [ ] Include OFF-MAP triggers (Legate at this Lord's locale, Marshal
      stack, Vassal markers on the Calendar).
- [ ] A single end-of-`apply_action` orphan-sweep backstop (Almoravid) is
      cheap insurance against the whole family — but still fix the root
      path so the sweep stays a backstop, not the only cleaner.

**Pre-built test ideas:**
- "Remove every Lord in turn" stress test asserting full state consistency
  (no dangling references, stale flags, or orphaned markers).

## Pattern 9 — Rule-cite-but-no-enforce

**Shape:** A comment cites a rule (the constraint was *in mind*) but the
actual validation code is missing.

**Detection heuristic:**
```
grep -rn "per [0-9]\+\.[0-9]\+\|rule [0-9]\+\.[0-9]\+\|[0-9]\.[0-9]\." src/
# Read each cited rule; verify the code below the comment implements it.
# Special suspicion: "should"/"must" with no following `raise IllegalAction`.
```

**Examples:**
- `[Nevsky SMOKE-041]` Marshal-group gate cited "4.3.1" but didn't enforce
  it; non-Marshals could bring co-marchers.
- `[Nevsky SMOKE-046/048]` Sail Ship requirements cited 4.7.3 but weren't
  validated.
- `[Nevsky SMOKE-081]` Field Organ + Bridge target validation cited but not
  implemented.

**Audit checklist:**
- [ ] Grep every `rule N.N.N` comment; confirm the code 2–30 lines below
      enforces it, not just gestures at it.
- [ ] **Treat narrative "the consumer applies this" / "applied elsewhere"
      comments as the same hazard** — a comment that defers the work to a
      caller that never does it is an unenforced rule (see Plantagenet
      immediate events, Pattern 1).

**Pre-built test ideas:**
- For each cited rule, a "violate it" test asserting IllegalAction.

## Pattern 10 — No-target-no-op events

**Shape:** An immediate event has an implied "if target unavailable" → no
effect, discard. The resolver raises IllegalAction instead, making the
card unresolvable (and, post-Pattern-11 fixes, potentially deadlocking).

**Detection heuristic:**
```
grep -nA20 'def _resolve_[RT][0-9]' src/<engine>/events.py | \
    grep -E 'state\.lords\[|state\.locales\[|state\.assets\['
# For each, confirm an upstream "if target not in state.lords" guard.
```

**Examples:**
- `[Nevsky SMOKE-112]` "Bountiful Harvest" raised when no Ravaged marker
  existed.
- `[Nevsky SMOKE-113]` "Batu Khan" raised when its target Lord was
  off-Calendar.
- `[Nevsky SMOKE-114]` "Osilian Revolt" raised when no eligible Service
  marker existed.
- `[Plantagenet immediate-events]` Five immediate Events whose printed text
  reads "No effect if …" raised IllegalAction when their precondition was
  unmet: Dubious Clarence (Y26, needs Edward IV + Clarence on map), French
  Troops (L22, a Lord at a Port), Tudor Banners (L32, Henry Tudor at a
  Friendly Stronghold), Warwick's Propaganda (L23/L24, Yorkist-Favoured
  Strongholds), L'Universelle Aragne (L27, Yorkist Mustered Vassals). Drawn
  *randomly* during Arts of War (3.1.3), the precondition often fails, so
  the no-op path is the common path, not the exception. Fixed to resolve
  "as far as able" (no effect when the precondition fails; reject only a
  malformed *decision*). Selection Events also size to availability
  ("select 3 … or all if fewer").

**Audit checklist:**
- [ ] For each immediate event, identify all targets it can act on.
- [ ] Per Tip, decide whether the rule requires a target or "no target = no
      effect" (most "On Calendar, shift X" cards are the latter).
- [ ] Add a pre-flight returning `{"no_op": True, "side_effects": [...]}`.
      **Preserve any unconditional side-effect** (block the step, advance a
      marker) even on the no-op path — see Part V / Pattern note.
- [ ] **Distinguish "precondition unmet" (no-op) from "the player's chosen
      decision is illegal" (reject).** A randomly-drawn Event must no-op
      when it cannot act regardless of choice, but should still reject a
      malformed decision when it *can* act (Plantagenet).

**Pre-built test ideas:**
- For each "if available" event, remove all valid targets and assert the
  event no-ops (and that any unconditional side-effect still fires).

## Pattern 11 — Active-player / turn-order desync

**Shape:** A transition changes whose move is next but forgets to update
`state.meta.active_player`. The enumerator keys off `active_player`, so the
correct side's moves aren't surfaced (often zero moves).

**Detection heuristic:**
```
grep -n "state.meta.active_player\s*=" src/
# For every state mutator that changes whose turn it is, confirm it also
# updates active_player to the rule-defined next actor.
```

**Examples:**
- `[Nevsky SMOKE-109]` `finalize_plan` didn't switch active_player when only
  one side had finalized.
- `[Nevsky SMOKE-111]` `cmd_march` set combat_pending owed by the defender
  but didn't switch active_player; legal_moves returned 0.

**Audit checklist:**
- [ ] For every action that ends a step / triggers a response / passes the
      baton, verify active_player afterward.
- [ ] Extra attention to multi-side ratification ("both sides must
      finalize", "defender responds to attacker", "T then R do X").

**Pre-built test ideas:**
- For each baton-passing handler, assert active_player flips to the other
  side.
- Instrument self-play: any `legal_moves` returning 0 outside terminal is a
  desync.

## Pattern 12 — Cap / floor not enforced uniformly

**Shape:** A numeric cap or floor (per-Asset 8-cap, per-side VP cap,
off-edge clamp at 0) is enforced in some paths but not others; the agent
accumulates past it through the unguarded path.

**Detection heuristic:**
```
grep -n "min(8, \|max(0, \|VP_CAP" src/
# Confirm every asset-add and every VP-mutation funnels through the
# capping logic.
```

**Examples:**
- `[Nevsky SMOKE-025]` VP cap never enforced — sides could exceed.
- `[Nevsky SMOKE-027]` Liberation could produce negative VP (no floor).
- `[Nevsky SMOKE-032]` Spoils transfers ignored the per-asset 8-cap.

**Audit checklist:**
- [ ] List every cap/floor; confirm every mutation path enforces it.
- [ ] Defense-in-depth: also clamp at *read* time (e.g. the
      winner-determination function clamps the VP cap).

**Pre-built test ideas:**
- Stress test driving a side to the cap from many directions; assert it
  holds.

## Pattern 13 — Per-window once-only flags not reset

**Shape:** A flag tracks "acted once this Call to Arms / Card / Levy". The
set is wired; the reset at the window boundary is missing.

**Detection heuristic:**
```
grep -n "acted_this_call_to_arms\|once_per_card\|_used_this_card" src/
```

**Examples:**
- `[Nevsky SMOKE-090]` Legate-arrives didn't consume the once-per-CtA slot.
- `[Nevsky SMOKE-092]` Sea-Trade fired multiple times per CtA because the
  flag wasn't reset at the CtA boundary.
- `[Nevsky SMOKE-132]` Per-Levy "already drew AoW" flag — the *reset* (not
  the set) was the bug; only a multi-Levy sweep caught it. See Part VI.

**Audit checklist:**
- [ ] For every once-per-window rule, confirm **both** the set and the
      reset are wired.
- [ ] Audit the reset as deliberately as the set; write a regression test
      that spans **at least two** of the relevant windows.

## Pattern 14 — Capability scope mismatches (this-lord vs side-wide)

**Shape:** A Capability has two scopes — `this_lord` (tucked under one
Lord) vs `side_wide` (in `capabilities_in_play`). Lookup helpers that
don't filter by scope can fire a side-wide card through a this-lord lookup
or vice versa. The *data* can also carry the wrong scope, which is the same
bug one layer up.

**Detection heuristic:**
```
grep -n "this_lord_capabilities\|capabilities_in_play" src/
# Verify each lookup filters by the card's canonical scope from card data.
# Also audit the card DATA: a card with the wrong scope value fires through
# the wrong path even when every helper is correct.
```

**Examples:**
- `[Nevsky SMOKE-016]` `any_capability` hardened to filter by
  `capability_scope` so a misplaced card can't fire through the wrong path.
- `[Almoravid Q-001]` **Alférez (C15)** carried `side_wide` scope in the
  card data when the rule scopes it `this_lord` (eligible only to the four
  Christian captains — Pedro Ansúrez, García Ordóñez, Álvar Fáñez, Rodrigo
  Campeador). The data scope *was* the bug. Fixed to `this_lord` with an
  explicit eligibility set (`capabilities.CHRISTIAN_CAPTAINS_FOUR`); helper
  `capability_eligible_lords(card_id)` / `_scope_of()` returns `[]` for
  side-wide cards. Test: `tests/test_q001_alferez.py`.
- `[Almoravid Q-002]` **M24 Al-Garada** (Muslim Cabalgadas) — same shape:
  resolved to `this_lord`, eligible to seven Lords
  (`capabilities.MUSLIM_RAIDERS_SEVEN` = six Taifa Lords + Rodrigo
  al-Sayyid, **not** Yusuf/Sir). The M24 Tips entry confirmed the scope.
- `[Almoravid Q-003 (open)]` The Bowmen/Javelin metadata cards (C4/C5,
  M4/M5, M3/M6) carry `capability_scope = None` and so can't be Levied in
  the campaign game (the resolver applies them via `forces.json` card_ids);
  flagged as the same scope-*data* class as Q-001/Q-002, tracked open.

**Audit checklist:**
- [ ] Audit every `has_*_capability` helper — each must filter by canonical
      scope.
- [ ] Audit Capability-Levy paths so cards always land in the correct list.
- [ ] **Audit the card data's scope value itself** — a wrong `scope` in
      data fires the right card through the wrong path even with perfect
      helpers (Almoravid Q-001/Q-002).

---

## Hazard summary table

Counts are from the Nevsky run (first 114 SMOKEs, before the validated-
palette era). Add your game's counts as columns.

| # | Pattern | Nevsky count | Plantagenet | Almoravid | Highest-yield? |
|---|---|---|---|---|---|
| 1 | State-set-but-unreachable | 23 | ✓ | ✓ (under-enum) | ★ |
| 2 | Mirror gaps | 11 | ✓ | ✓ (P-3, Door B) | ★ |
| 3 | Stale per-Lord flags | 8 | | ✓ (L9b) | |
| 4 | Parallel Ways edge cases | 6 | | | |
| 5 | Castle / overlay markers | 9 | | | |
| 6 | Off-edge calendar | 7 | | | |
| 7 | Card-text fidelity gaps | 16 | ✓ | ✓ (Sagrajas, L3, F4) | ★ |
| 8 | Lifecycle leaks on removal | 6 | | ✓ (Door B) | ★ |
| 9 | Rule-cite-but-no-enforce | 8 | ✓ | | |
| 10 | No-target-no-op events | 3 | ✓ | | |
| 11 | Active-player desync | 2 | | | |
| 12 | Cap / floor not uniform | 4 | | | |
| 13 | Per-window once-only flags | 2 | | | |
| 14 | Capability scope mismatch | 1 | | ✓✓ (Q-001, Q-002) | |
| — | other / one-off | ~8 | reversed victory-winner polarity (see Part V) | wrong-winner F8 + inverted-shift L3 + Sagrajas terminal cap (Part II §9) | |

Patterns 1, 2, 7, 8 alone accounted for ~60 of the 114. Prioritize those
audits first. Almoravid's standout contribution is **Pattern 14** (it
supplied the first two non-Nevsky examples, both *data*-scope bugs) and a
strong **Part II §9** confirmation (a real wrong-winner, F8).

---

# Part II — Audit techniques & testing methodology

## §1 The central problem: the enumerator and the handler diverge

Almost every L&C harness separates an action **enumerator** (emits the
palette of currently-legal actions — `legal_moves.py` in Nevsky) from
per-action **handlers** (validate and apply — `_h_*` functions). **These
two will drift apart over time.** Every `IllegalAction` a handler can raise
is a candidate for a missing pre-filter in the enumerator. This is the
single most productive lens in this whole document.

There are two failure directions:

- **Over-enumeration** — the menu offers a move the handler rejects. A
  scripted agent shrugs and picks another; an index-driven LLM *cannot*,
  and burns the move. `[Nevsky SMOKE-118]` (levy_capability ignored
  eligibility / cap-2 / duplicate rules), `[Nevsky SMOKE-122]` (cmd_ravage
  enumerated unconditionally while the handler rejects own-territory /
  conquered / friendly / already-ravaged). `[Plantagenet Phase 5v]` a
  full-game smoke surfaced three handler-only rules un-mirrored in the
  enumerator: Yorkists-Block-Parliament (Y7) gating Levy-Vassal, Rising
  Wages (L9) coin gate on Levy-Troops, Owain Glyndwr (Y25) barring
  Lancastrian March into Wales. `[Almoravid Advisory #3]` audited the whole
  raise-list and found **zero over-enumeration** — enumerator and handlers
  were already in lockstep (a clean result worth recording: the audit is
  worth running even when it passes).
- **Under-enumeration** — a legal move is never offered; the agent can't
  do something the rules allow. `[Nevsky SMOKE-130]` (couldn't Withdraw
  into an own-conquered Stronghold). `[Plantagenet command-enum]` the
  Command enumerator never offered (a) Marches into enemy contact — it
  skipped any enemy-occupied or enemy-adjacent destination, so *attacking*
  Marches that resolve an Intercept/Approach/Battle were unreachable
  through the menu; (b) Group Marches (only solo Marches were emitted); and
  (c) own-location Parley, which sat behind a shared `friendly_here`
  early-return that correctly gated Tax/Supply but wrongly caught Parley.
  All three were accepted by the handlers; an LLM had to hand-build them.
  `[Almoravid Advisory #3]` the under-enumeration direction was where
  Almoravid's gaps lived: `dinars_deposit` (4.1.4) and
  `designate_lieutenant` (4.1.3) had working handlers but **no menu entry**
  (Pattern 1); the C14/C15 Hold-events were likewise un-offered. All fixed
  by adding the enumerator entries. **Watch for an over-broad shared guard
  that catches a sibling action with looser requirements** (Plantagenet),
  and for *whole handlers the enumerator simply forgot* (Almoravid).

### The cheap audit
```bash
grep -n 'raise IllegalAction' src/<engine>/campaign.py | \
    sed -E 's/^([0-9]+):.*"([^"]+)".*/\1\t\2/'
```
Walk the list. For each pre-check raise (own-territory, eligibility,
capacity, friendly-locale, season, …), grep the enumerator for the
corresponding pre-filter. Misses are very likely bugs. **Walk it in both
directions:** also list every handler `*_HANDLERS` key and confirm the
enumerator can emit each one (Almoravid's gaps were whole handlers the
menu never offered, which the raise-list walk alone would miss).

### The round-trip sweep (build this early)

A deterministic sweep that replays **every** action shape the enumerator
emits through the handler on a deep copy and fails on any `bad_*` /
`missing_arg` / `ineligible_*` / over-enum code:

```python
def test_enumerator_handler_roundtrip():
    for scenario in ALL_SCENARIOS:
        s = load_scenario(scenario, seed=1)
        for _ in range(50):
            for move in legal_moves(s, with_previews=False):
                snapshot = s.model_copy(deep=True)
                try:
                    apply_action(snapshot, move)
                except IllegalAction as e:
                    pytest.fail(f"enumerator emitted illegal {move['type']}: "
                                f"{e.code} ({e.message}) in {scenario}")
            apply_action(s, pick_first(legal_moves(s)))  # advance under any policy
```

This is the highest-value test in the suite. It is RNG-safe **only if your
RNG lives in the state** (see Part IV §the-RNG-prerequisite); a module-
global RNG makes the deep-copy probe perturb the real game. `[Almoravid]`
ships exactly this (`tests/test_enumerator_handler_roundtrip.py`), RNG-safe
via `meta.seed` + `meta.rng_state`.

> **But it only checks legality, not outcome — see §9.** A round-trip /
> smoke sweep that asserts "no IllegalAction + invariants hold" will pass a
> *wrongly scored* game. It validates that moves are legal and the board
> stays legal; it does not validate that the right side wins. Plantagenet
> shipped a reversed victory-winner for many rounds under a green full-game
> smoke for exactly this reason — and Almoravid shipped a wrong-winner (F8)
> under a green suite until an LLM playtest reasoned about the result.

### The defensive idiom: suppress over offer

When you mirror a handler pre-check into the enumerator, wrap static-data
loads in try/except so a load failure **suppresses** the option rather than
crashing the enumerator. Bias toward "miss a legal move" over "offer a
phantom-legal move" — the consumer trusts the palette.

```python
ravage_ok = False
if active.location is not None:
    try:
        static_loc = load_locales().get(active.location)
        loc_state = state.locales.get(active.location)
        if static_loc is not None and loc_state is not None:
            if (static_loc.get("territory") != side
                    and loc_state.russian_conquered == 0
                    and loc_state.teutonic_conquered == 0
                    and not _is_friendly_locale(state, active.location, side)
                    and not loc_state.russian_ravaged
                    and not loc_state.teutonic_ravaged):
                ravage_ok = True
    except (ImportError, KeyError, AttributeError, FileNotFoundError):
        ravage_ok = False
if ravage_ok:
    out.append({"type": "cmd_ravage", ...})
```

## §2 Argument-domain mismatch is its own failure mode

Matching argument **names** between enumerator and handler is not enough —
the enumerator can emit a value from the wrong **domain** while the field
name looks right.

`[Nevsky SMOKE-119]` the `stand_battle` option emitted `{"concede": side}`
(`"teutonic"`/`"russian"`) but the handler expected `{"concede":
"attacker"|"defender"}` (battle role). Names matched; domains didn't; every
concede was rejected with `bad_concede`. The round-trip sweep in §1 catches
this if it asserts on `bad_*` codes.

## §3 Define each rules predicate once; never re-derive it inline

`[Nevsky SMOKE-130]`, the most portable single lesson: the harness had a
correct `_is_friendly_locale` (own-conquered Strongholds count as
Friendly), but the Withdraw handler couldn't call it directly during an
Approach (the attacker's presence makes the strict test fail), so it
*re-derived* a Friendly check inline — and silently dropped the
own-conquered clause. **Re-derived predicates lose conditions.** If a
concept (Friendly, Eligible, Besieged, Laden) is defined once, every site
must call that function or a documented variant. When a caller needs a
relaxed form ("Friendly ignoring the attacker's presence"), make it an
explicit parameter or sibling helper — keep the full condition set in one
place. `[Almoravid F4]` reinforces from the data side: "Friendly via Seat
marker" had to distinguish *printed* Seats from *placed* Seat markers
(1.3.1); the fix split the two fields so the one Friendliness predicate
reads only placed markers.

## §4 Auto-resolved player choices are silent fidelity bugs

`[Nevsky R198]` wasn't a crash — the harness *decided for the player* where
the rules grant a choice. Casualty absorption ("which unit takes this Hit")
was hard-coded weakest-first; the rulebook says the owner picks. These
never fail a test (the auto-choice is usually optimal) — they show up as
lost agency and rare edge-case divergence. **Audit:** grep the rulebook for
"the owner/player chooses / may / decides" and confirm each is a decision
the harness surfaces. Expose it as an optional action argument that
*defaults to the sensible auto-choice* so nothing changes unless the player
asserts a preference. `[Almoravid L7]` surfaces such a choice explicitly:
which Christian Lord(s) receive Parias Coin on an Independent-Taifa Disband
is a minor player choice, exposed via `parias_coin_targets` (totals/VP
unaffected by the distribution) rather than silently auto-assigned.

## §5 Tightening a "must do X first" rule can deadlock

`[Nevsky SMOKE-131]` "you may not advance the Levy step while you still owe
implementation of drawn cards" is correct, and the first attempt
*deadlocked* the game: consumers relied on advance as a universal escape
hatch, and some drawn cards (immediate Events with no valid target) could
not be cleared because their resolvers raised rather than no-op-discarded.
"Must clear it first" + "can't be cleared" = hard deadlock. Two principles:
(1) before enforcing "complete X before Y," verify X can *always* be
completed from any reachable state; (2) if some cases can't yet guarantee
that, **scope** the new rule to the cases that can and leave the rest
permissive until the clearing path exists. Ship the safe subset.

> `[Plantagenet immediate-events]` confirms this from the other direction:
> Plantagenet *added* a "you may not advance the Levy while immediate Events
> are unresolved" guard (`events_pending`) — and made it safe by first
> guaranteeing every immediate Event can always be resolved, including the
> "No effect if …" no-op path (Pattern 10). The guard and the always-
> clearable no-op were shipped together, never the guard alone.

## §6 The testing tiers (what found bugs, in order of yield)

**Tier 1 — Static probing (~70% of Nevsky bugs).** Pick one area (a
command, an event, a phase transition); read rules + harness side by side
looking for Patterns 1, 2, 3, 5, 6, 9. Run for every command, event,
capability, phase. Budget ~150 rounds for a Nevsky-sized game. `[Almoravid]`
the clause-by-clause rulebook audit (item families L/C/B/S/T/E) was this
tier and produced the bulk of its ~50 fixes (e.g. L3 inverted shift, S2
inverted Surrender/Siegeworks order, T6 Curias scoring).

**Tier 2 — Self-play sweep (~20%).** A greedy agent that queries
`legal_moves`, picks the highest-priority concrete-arg action, with
fallback chains. Run 6 scenarios × 50 seeds. Triage any non-terminal
"no_legal_moves" (Pattern 1/11), unhandled IllegalAction (Pattern 7/9), or
non-terminating run (Pattern 1).

**Tier 3 — Rule diff (small marginal returns after 1+2).** Final
word-by-word read of the printed reference, focusing on rare events and
edge-case cards.

**Tier 4 — Property-based testing (Hypothesis).** Fuzz force counts, asset
amounts, calendar positions, Lord placements; run short action sequences
and assert invariants. Catches accumulator overflow, calendar off-by-one,
and "unreachable" state shapes that turn out reachable. Worth running even
when agent sweeps are clean.

## §7 Different agent styles surface different bug classes

No single consumer of `legal_moves` finds everything:

- **Greedy** (fast state-delta heuristic) avoids combat → finds the
  no-target-no-op family and lifecycle leaks; blind to combat shapes.
- **Strategic** (weights combat high) actually opens and stands battles →
  found the levy-capability and concede-arg gaps. `[Almoravid]` an
  aggressive/combat-seeking policy is what walked Lords into the Approach
  and Sally states that exposed P-3/P-4/P-5 (the greedy first-legal stepper
  never reached them — see Advisory #1).
- **LLM strict-follow** can't pivot off an illegal suggestion → every
  phantom-legal move surfaces loudly. Found cmd_ravage over-enum in a
  single playthrough. `[Plantagenet]` a key-free ChatGPT playthrough found
  the three Command under-enumerations that the scripted full-game smoke
  never flagged. `[Almoravid]` an independent ChatGPT playthrough found the
  Sagrajas terminal-cap bug (winner=None at the 6-Round cap); a separate
  Cowork-chat playthrough of Scenario A filed 8 findings including the
  wrong-winner F8.
- **Property tests** catch invariant violations no agent will produce.

**Recommendation for a new port:** wire at least two styles — greedy
(breadth) plus either strategic (combat depth) or an LLM strict-follow
wrapper (enumerator correctness). Over 200 sessions × all scenarios × 50
seeds the marginal cost is small and the yield is meaningfully higher.

## §8 A clean sweep means "no bugs on the trajectories you currently take"

`[Nevsky SMOKE-133]` (the enumerator offered a Muster for a Lord an event
had blocked) was years old and had passed every sweep — until an unrelated
change (a draw cap) shifted one game's trajectory into the state that
reached it. A green sweep is "no bugs on the paths my agents happen to
walk," not "no bugs." Flush the rest with **trajectory diversity**:
multiple agent styles, LLM play, many seeds, and **re-run the full sweep
after every change** (a change elsewhere can expose a latent bug here).
`[Almoravid P-4]` is a sharp case: Scenario D's *data* placed al-Mustain as
a field Lord with no Siege marker — an illegal co-location latent in the
scenario file that only the newly-added invariant (run under an aggressive
policy) surfaced. A pre-existing illegal *starting* state had passed every
prior sweep because nothing checked for it.

## §9 A legality-clean sweep does not validate outcome correctness

A distinct axis from §8. §8 is "you didn't walk the buggy trajectory"; §9
is "you walked it but never checked the thing that was wrong." Round-trip
and full-game smoke sweeps typically assert two things: no enumerated move
is rejected, and board invariants hold at every step. **Neither asserts
that the game ends with the correct winner or score.** Terminal scoring,
victory-condition polarity, and tie-breaks are computed *once at the end*
and are invisible to legality+invariant checks.

`[Plantagenet 5.1]` the Campaign-Victory check returned the **losing** side
as the winner (an inverted conditional). This survived every full-game
smoke run because the smoke asserted only "no IllegalAction + invariants
clean." A directed LLM playthrough flagged it immediately, because the model
reasons about the *result* ("I have no Lords left, why did the engine say I
won?"), not just legality.

`[Almoravid F8]` independently confirms this, from a *data-load* angle: the
Taifas-box green 1-VP Conquered markers were never loaded into
`state.taifas_box_vp`, so `compute_final_vp` dropped them (4 Muslim VP in
Scenario A) and **reported the WRONG WINNER**. The whole pytest suite was
green — no move was illegal, no invariant tripped — because nothing asserted
*who won* against the board. An independent LLM playtest caught it by
reasoning about the result. `[Almoravid L3]` is the polarity cousin: Pay
shifted Service the wrong *direction* (3.2.1), which silently mis-scores
service/disband outcomes. `[Almoravid Sagrajas]` a third face: a Battle that
hit the resolver's default 6-Round cap returned `winner=None`, leaving the
"loser" un-removed and co-located — a terminal-resolution bug fixed with a
higher `max_rounds=24` plus a defensive strength tiebreak (the cap must not
*decide* the result).

**Audit / methodology:**
- [ ] For every victory/scoring rule, add a test that *constructs or drives
      to* the triggering state and asserts the **correct** winner/score —
      not merely that the game ended. (Almoravid:
      `tests/test_taifas_box_vp_loaded_f8.py`, `tests/test_phase7b_victory.py`.)
- [ ] Test both polarities of each binary victory condition (side A
      eliminated → B wins; side B eliminated → A wins; both → draw).
- [ ] **Audit data-load paths into the scoring state** — a score input that
      is never loaded (Almoravid F8) mis-scores just as surely as a flipped
      conditional (Plantagenet 5.1).
- [ ] In LLM play, have the model judge the *reported result* against the
      board, not only the legality of each move — outcome bugs hide behind
      clean legality.

---

# Part III — Defensive idioms worth porting verbatim

- **try/except around static-data loads in the enumerator.** Suppress over
  offer (Part II §1).
- **Source-marker regression tests.** One line per finding; CI catches
  silent refactors that drop a filter (the filter and its comment vanish
  together):
  ```python
  def test_smoke_NNN_marker_present_in_source():
      import inspect, <engine>.<module> as m
      assert "SMOKE-NNN" in inspect.getsource(m)
  ```
  `[Almoravid]` uses the same idiom with `Pattern 14` / `Q-001` markers in
  `capabilities.py` so a refactor can't silently drop the scope filter.
- **Deterministic seeded RNG threaded through `state.meta.rng_state`.**
  Bit-for-bit reproducible sessions; every failing seed replays exactly.
  This is also the prerequisite for the validated-palette / round-trip
  deep-copy probe (Part IV). `[Plantagenet]` confirmed: the RNG lives in
  the state as `seed` + `rng_state`. `[Almoravid]` confirmed: `meta.seed`
  + an atomic `meta.rng_state`, a SHA-256-keyed `random.Random` rebuilt per
  roll (no module global), which is what makes the deepcopy-probe validated
  palette and round-trip sweep safe.
- **Append-only findings log** (`SMOKE_TEST_FINDINGS.md` / Almoravid's
  `VERIFICATION_LOG.md`). Every round appends; nothing overwrites. The audit
  history *is* the file.
- **One shared placement-eligibility gate.** Centralize "is this Seat
  free / legal?" so every door (Muster, Legate-place, Veche-place) uses the
  same check — one audit then covers all doors (`[Nevsky Door C]`, Part V).
  `[Plantagenet Door C]` confirmed: all placement paths route through a
  single free-and-enemy-free-Seat helper. `[Almoravid Door C]` confirmed:
  M22/M21/C16 (and follow-up C14 Pope Gregory / C15 Cluniacs) used
  `seats[0]` blindly; all now route through `_free_seats_for`, so one audit
  covered every Muster/event placement door.
- **Co-location invariant, always on.** See Part V; cheap permanent guard
  against an entire illegal-board-state class. `[Almoravid]` ships it in
  `tests/test_deep_invariants.py::_invariants`, keyed on the per-unit
  `in_stronghold` flag (besieged-inside vs besiegers-outside stays legal)
  and excluding the mid-combat locale via `if s.pending is None`.
- **Card-zone invariant, always on.** `[Plantagenet]` an always-on check
  that *every Arts of War card occupies exactly one zone* (no card in two
  deck piles; no card in a deck pile **and** on a Lord's mat) caught a
  Capability-Levy mirror gap (Pattern 2). Cheap, permanent, and finds a
  whole family of card-lifecycle slips.
- **End-of-`apply_action` orphan-marker sweep.** `[Almoravid]`
  `_sweep_all_orphaned_markers(state)` runs after every applied action as a
  backstop against the lifecycle-leak family (Pattern 8), covering every
  departure path including the empty-besieged-Stronghold case. Keep the root
  fix too, so the sweep stays a net rather than the only cleaner.

---

# Part IV — LLM-driven play

## §The single biggest finding

After ~188 rounds of scripted auditing on Nevsky, **every full LLM
playthrough found a fresh, real bug** that the scripted sweeps had not.
Once scripted sweeps go clean they stop finding bugs — not because the bugs
are gone, but because greedy/strategic agents optimize a heuristic and only
construct the states that heuristic steers toward. An LLM plays
*positionally* and tries rules-legal-but-unusual things: defending a
Stronghold from inside it, marching a second Lord into an existing siege,
choosing casualty absorption, drawing/advancing in an off sequence. **Once
your sweeps are clean, treat an LLM full-game playthrough as a first-class
part of the rotation, not a demo. Budget one per scenario.**

`[Plantagenet]` strongly confirms this: with a green test suite *and* a
green full-game smoke sweep, successive key-free ChatGPT playthroughs each
surfaced a fresh real defect the scripted regime missed.

`[Almoravid]` confirms it twice. With a green suite, (1) an independent
Cowork-chat playthrough of Scenario A (rulebook open) filed **8 findings**
(F1–F8), including the **wrong-winner F8** that no legality+invariant check
could see (Part II §9); and (2) an independent **key-free ChatGPT**
playthrough via the model-agnostic `playtest_harness.py` ran Scenario F to
a clean end (zero findings — a useful negative) and then found the
**Sagrajas terminal-cap** bug (defend seeds 57/96, `winner=None` at the
6-Round cap → co-location). None required exotic play — just a model that
*attacks*, *reasons about the result*, and plays edge sequences.

The bug hotspot in those games was **combat/siege state-transition
predicates** and **terminal scoring**. Scripted agents avoid sieges and
never check who won, so these sit undetected. Enumerate every combat/siege
handler's pre-checks and confirm each is exercised by a test that **sets up
the besieged / conquered / joined-siege position directly** — don't wait
for an agent to wander in.

## §The interface design that worked

- **Hidden-info filter at the boundary.** Strip the opponent's hand, plan,
  and face-down state before serializing. Don't trust the model to ignore
  visible info — don't show it.
- **Pre-filter `legal_moves` to the active side.** Same palette a
  strict-follow agent receives.
- **Curated ~3 KB briefing** beats dumping the rulebook into the prompt:
  state, phase, recent history, plus on-demand lookups for cards/strategy/
  rules.
- **3-strike retry + safe phase-appropriate fallback** (`advance_step` /
  `cmd_pass` / `end_card` / `legate_skip`). Don't deadlock, crash, or stall
  on one hallucination. (But heed §5 of Part II — the fallback can't be the
  *only* escape hatch if a "must clear X first" rule can block it.)
- **Post-game self-critique loop.** Hand the transcript back with "what
  would you do differently?" — surfaces strategy and rule-edge cases that
  didn't crash but felt wrong.

## §The key-free path: the model plays it in its own sandbox

The highest-leverage, lowest-friction setup: zip the repo, upload it to a
ChatGPT (or equivalent) **Project**, and let the model **run the harness in
its own Python sandbox** — no API key, no network. The model calls
`show()` to see the active side's briefing + a numbered legal-action list,
decides, calls `apply(N)`, loops. A baked-in helper validates every offered
action against your executor on a throwaway copy, so the model is **never
shown an illegal move**, and any filtered move is logged as a bug. A
*different model walking different trajectories* is what surfaces bugs
scripted sweeps miss. `[Plantagenet]` independently confirmed the whole
path. `[Almoravid]` confirmed it too: a model-agnostic `playtest_harness.py`
(needs only pydantic) exposes `show()`/`legal()`/`apply()` and a validated
palette; an uploaded zip let ChatGPT play Scenario F to a clean finish and
flag the Sagrajas seeds 57/96 bug from its own sandbox.

What your harness must expose (the contract — most L&C engines already have
all of it):

1. `load_scenario(id, seed) -> state` + a `SCENARIO_IDS` collection,
   deterministic from the seed.
2. `briefing_for_side(state, side) -> str` — natural-language, hidden-info
   filtered.
3. `legal_actions_for_side(state, side) -> list[dict]` — every legal
   action, **concrete** (expand templated/parameterized moves) and
   hidden-info-filtered.
4. `apply_action(state, action)` — applies in place; raises a typed
   `IllegalAction` on an illegal move.
5. `is_terminal(state) -> bool` (+ optional `determine_winner`).
6. Small adapters: `active_side(state)`, `deep_copy(state)`.

> **Note on engine-shaped contracts.** The generic helper assumes
> `{"type","args"}` actions and a `side` argument. Both `[Plantagenet]` and
> `[Almoravid]` diverged on the exact shape and adapted cleanly — Almoravid
> wraps its engine in a thin `Harness` class (`.show()`, `.legal()`,
> `.apply(int_or_dict)`). The contract is a shape to hit, not a literal API.

### §Classify the helper's rejections, or player mistakes masquerade as engine bugs

When the model can submit a *raw* action dict (not just a menu index), a
rejected apply has three very different meanings, and conflating them
poisons the findings log:

- **Vouched move rejected** (an index pick, or a raw dict that exactly
  matches a current menu entry) → a genuine enumerator/handler divergence
  (over-enumeration). **Notable.**
- **Off-menu move *accepted*** (a raw dict the menu never offered, that the
  handler applies) → **under-enumeration** — the menu missed a legal move.
  **Notable**, and easy to miss because nothing errored.
- **Off-menu move rejected** (a raw/stale/mis-built action the player
  composed that wasn't on the current menu) → an ordinary *player* mistake,
  **not** an engine defect.

`[Plantagenet]` first logged *every* rejected apply as a notable
over-enumeration, polluting the report with phantom engine bugs; fixed by
classifying on whether the submitted action matched the current validated
menu. `[Almoravid]` hit the *index-staleness* corner of the same hazard:
the `Harness.apply()` method clears `self._last_menu` after every applied
action (`# state changed; require a fresh legal() before apply(index)`), so
a model can't replay a stale index against a changed board and have it
misread as an engine bug. **If your sandbox lets the model build raw
actions or pick by index, build this classification in from the start.**

### The RNG prerequisite (the one real architectural check)

The validated palette and the round-trip sweep work by
`deep_copy(state) → apply candidate → discard`. That is only safe if the
**RNG is part of the state**, so mutating the copy can't perturb the real
game's dice.

- **RNG in state** (a `seed` + an incrementing/atomic counter, each roll a
  pure function of them — Nevsky `meta.rng_state`; Plantagenet `seed` +
  `rng_state`; Almoravid `meta.seed` + `meta.rng_state` via a SHA-256-keyed
  `random.Random`): a structural deep copy isolates it perfectly. Keep
  validation on.
- **RNG is a module global** (`random.random()`): a deep copy will **not**
  isolate it; validation would advance the real dice. Either refactor the
  RNG into the state (strongly recommended — it also unlocks reproducibility
  and lookahead) or disable the validated palette and rely on apply-time
  catching (you lose the "never show an illegal move" guarantee).

If you build one thing before LLM play, make it state-resident RNG.

### The co-location invariant to bake in

Run after every applied action; return violation strings. The canonical
L&C invariant (confirmed across engines): **no Locale holds opposing
mustered units, both outside a Stronghold, with no Approach/Battle
pending.** Key it on the **per-unit in-Stronghold flag** (not the presence
of a Siege marker — besieged-inside vs besiegers-outside is legal), and
**exclude the locale where combat is mid-resolution** (a March creates
contact one step before the defender responds — that co-location is legal
and transient; everyone false-positives on it first). Add edition-specific
ones (VP within cap, markers in bounds) as you learn your failure modes.
`[Plantagenet]` ships co-location + influence-cap + lord-status + card-zone
as one always-on battery. `[Almoravid]` ships the co-location check keyed on
`in_stronghold` and gated by `s.pending is None`, and it earned its keep
immediately — the new invariant surfaced **three** real bugs (P-3 Sally
relocation, P-4 illegal Scenario-D start data, P-5 CtA auto-Muster onto an
enemy-occupied Seat) that prior legality sweeps had passed.

---

# Part V — Cross-project advisory log

This is where one team tells the others "self-check for this bug class."
Each advisory below is a worked example; the template is in Appendix B.

## Advisory — No-op-on-missing-target must preserve unconditional side-effects

*Raised by Nevsky during the playthrough era.* Some immediate events have a
side-effect that fires **unconditionally** (block the Levy step, advance a
marker) plus a target-dependent one. The no-op path (Pattern 10) must
preserve the unconditional half, and must return a `side_effects` list so
downstream bookkeeping / replays know what fired:

```python
def _resolve_R11(state, args):
    target = args.get("target")
    if target is None or target not in state.lords \
            or state.lords[target].state != "mustered":
        state.meta.levy_blocked_this_lord = True       # unconditional half
        return {"no_op": True, "reason": "no eligible target",
                "side_effects": ["levy_blocked_this_lord"]}
    ...  # normal resolution
```

**Plantagenet result: confirmed and extended.** Plantagenet's immediate
Events (Pattern 10) are all of the "no effect if precondition unmet" kind;
none carried an unconditional side-effect, but the resolution path returns
a `{"no_effect": reason}` result for the same replay/bookkeeping purpose,
and the engine distinguishes "precondition unmet → no-op" from "the player's
chosen decision is illegal → reject."

**Almoravid result: N/A so far.** Almoravid's Hold/immediate events that
were audited (e.g. M11 Al-Qadir, reclassified as a *Hold* event in F5 so it
is held on draw rather than auto-fired) did not surface the unconditional-
side-effect-plus-no-op shape; no distinct finding. Recorded as not-yet-
exercised rather than absent.

## Advisory #1 (from Inferno) — Retreat that penalizes but doesn't relocate

*Raised by Inferno-Harness.* A Retreat that applied the Service-shift
penalty but never relocated the loser produced illegal co-located
un-besieged enemies. Recommendation to every sibling engine: self-check all
Retreat paths + add the co-location invariant.

**Nevsky result: clean.** Both Battle and Sally aftermath relocate the
loser with full destination rules. Two transferable lessons reinforced:
- **The invariant is worth having even when you pass it.** Nevsky had no
  co-location check; it added one.
- **Greedy/first-legal stepping is a cold-path blind spot.** **Run the
  co-location invariant under an aggressive/concede-willing policy, not just
  greedy.**

**Almoravid result: FIXED — Almoravid actually had the bug.** Battle
`apply_retreat_aftermath` relocated correctly, but the **Sally** besieger-
loss path had the exact penalize-but-don't-relocate shape — it early-
returned for `engagement == "sally"`, applying the penalty without moving
the loser (**P-3**). Adding the co-location invariant *and running it under
an aggressive policy* (heeding Nevsky's second lesson) also surfaced two
more co-location bugs the cold path had hidden: **P-4** (Scenario D's data
placed al-Mustain as a field Lord with no Siege marker — an illegal
*starting* state) and **P-5** (a Call-to-Arms auto-Muster onto an enemy-
occupied Seat). Tests: `tests/test_fix_retreat_relocation_p3p4p5.py`. This
advisory paid off directly: Inferno's flag found a real Almoravid bug.

## Advisory #2 (from Inferno) — The co-location bug *class* (three doors)

*Raised by Inferno-Harness.* Reframed the single bug as a class with three
independent doors: **Door A** (Retreat relocates), **Door B** (siege/flag
cleared on departure, *including* the empty-besieged-Stronghold case),
**Door C** (placement onto a contested Seat).

**Nevsky result:** Door A clean; Door B had a residual empty-Stronghold
variant (fixed); Door C clean (one shared free-Seat gate). Meta-lesson: the
highest-yield artifact is the co-location invariant run under an aggressive
policy.

**Almoravid result: Door A OK; Doors B & C FIXED; inside-placement N/A.**
- **Door A** — VERIFIED OK (Battle relocates; the Sally gap was the
  separate P-3 above).
- **Door B** — FIXED. Orphaned Siege/Bypass markers were lifted on some
  departures but not on Sail (M19), event-driven departures (C25 De Vivar),
  or Winter/Curias Disband. Centralized into `_sweep_all_orphaned_markers`,
  invoked at the end of **every** `apply_action`, and made to cover the
  **empty-besieged-Stronghold** case. *Lesson reinforced: a marker-lifecycle
  sweep must run on every departure path AND cover the empty-Stronghold
  case.* Test: `tests/test_advisory2_doors_bc.py`.
- **Door C** — FIXED. `M22`/`M21`/`C16` (and follow-up `C14` Pope Gregory /
  `C15` Cluniacs) used `seats[0]` blindly, allowing a Muster onto a
  contested/occupied Seat. All now route through one `_free_seats_for`
  helper that excludes enemy-occupied/Conquered Seats — one audit covered
  every door.
- **Inside-placement sub-case** — N/A: Almoravid has no "Muster into a
  Besieged Stronghold" exception, so that door doesn't exist here.

## Advisory #3 (from Plantagenet) — Legality-clean sweeps don't validate winner/scoring

*Raised by Plantagenet-Harness.* A round-trip / full-game smoke sweep that
asserts "no enumerated move is rejected + board invariants hold" will
happily play a game to a **wrongly scored** end-state, because terminal
victory/scoring logic is computed once at the end and is invisible to
legality+invariant checks (Part II §9). Plantagenet shipped a **reversed
5.1 Campaign-Victory winner** for many rounds under a fully green full-game
smoke; a directed LLM playthrough caught it in one game by reasoning about
the *result*.

**Recommendation to siblings:** for every victory/scoring rule, add a test
that drives to (or constructs) the triggering state and asserts the
**correct** winner/score — and test *both polarities* of each binary
condition. Do not rely on legality+invariant sweeps to catch outcome bugs.
In LLM play, ask the model to judge the *reported result* against the board.

**Almoravid result: confirmed (independently and from a new angle).** Before
this advisory was written, Almoravid had already shipped a real wrong-winner
under a green suite: **F8** — the Taifas-box green 1-VP Conquered markers
were never loaded into `state.taifas_box_vp`, so `compute_final_vp` dropped
4 Muslim VP in Scenario A and **reported the wrong winner**. Every test
passed (no illegal move, no invariant trip); an independent LLM playtest
caught it by reasoning about the result. This adds a **new failure mode** to
the advisory: the scoring bug was a *missing data-load into the score
state*, not a flipped conditional — so the self-check must also **audit
every data path that feeds the terminal score**, not only the comparison
logic. Companions: **L3** (Pay shifted Service the wrong *direction*, 3.2.1)
and the **Sagrajas terminal cap** (`winner=None` when the resolver hit its
default Round cap). Almoravid now has directed outcome tests
(`tests/test_taifas_box_vp_loaded_f8.py`, `tests/test_phase7b_victory.py`).

---

# Part VI — Recent hazards (validated-palette era, Nevsky R219–R225)

These extend Parts I–II and came out of the key-free LLM-sandbox play
(Part IV §key-free). They are the freshest evidence and the most directly
reusable for a new port.

## §1 The validated action palette (the safety net that is also a detector)

Probe each concrete candidate by applying it to a deep copy; keep only
those the handler accepts; **log every filtered candidate as an
over-enumeration diagnostic**. This makes the LLM-facing menu safe (never
shows an illegal move) *and* surfaces the root enumerator gap to fix. It is
a net, not a substitute — fix the root (mirror the check in the enumerator)
and add a negative test asserting the *enumerator does not offer* the bad
move, not only that the handler rejects it. RNG-safe only with
state-resident RNG (Part IV).

Make the same validated palette the **default** in any CLI/agent path, not
just the LLM helper — and keep the index the menu prints and the index
`apply N` resolves against the *same* validated list, or they drift.
`[Nevsky R224]` `[Plantagenet]` `[Almoravid]` confirmed: the validated
palette is the agent-facing default. Almoravid's `playtest_harness.legal()`
deep-copy-probes each candidate and logs rejects as `over_enumeration`
findings, and `apply()` re-derives the menu so the printed index and the
applied index never drift.

## §2 Templated / non-concrete moves crash index-driven players

`[Nevsky SMOKE-160]` An action emitted as a *template*
(`{"type":"cmd_sail","args_template":{...}}`) instead of concrete args: an
index-driven model picks it by position, the apply path builds an action
with no `args`, and the handler raises `missing_arg`. **Enumerate concrete
moves** — one per legal destination/target — with real args. When the
handler's feasibility depends on a budget (here, Ship capacity for the Sail
cargo), **mirror that budget in the enumerator** so you never offer a
guaranteed-illegal concrete move.

`[Plantagenet]` confirmed for genuinely free constructions (the 4.1 Plan):
the menu surfaces the *template* but the helper expands it to a concrete,
ready-to-apply **default** so an index pick always applies. Template *and* a
concrete default — not template alone.

## §3 Repeatable no-ops trap automated drivers

`[Nevsky SMOKE-161]` Actions that are *always available but do nothing*
(shuffle a deck that already has cards; "discard this-Levy events" when
there are none) let a naive driver spin forever. **Offer a no-op-capable
action only when it changes state.**

## §4 Handler-only rules re-surface as enumerator over-enum

`[Nevsky SMOKE-162]` A seasonal/eligibility rule correctly enforced by the
handler (Summer Crusaders may Muster only in Summer, with their gating
Capability) was **not** mirrored in the enumerator, so the move was offered
out of season and rejected. This is Pattern 7 re-appearing on the
enumerator side — **every handler pre-check is also an enumerator pre-
filter** (Part II §1). When you fix a card-text gap in a handler,
immediately check the enumerator for the same constraint. `[Plantagenet
Phase 5v]` confirmed three at once. `[Almoravid]` is the inverse-direction
companion: its audit of the same lens found the enumerator *under*-
enumerating whole handlers (`dinars_deposit`, `designate_lieutenant`, C14/
C15 Hold-events) rather than over-enumerating — same lens, opposite gap.

## §Throughline

The bugs that survive a mature scripted-sweep regime live in the
rarely-walked corners — deep siege states, player-choice points,
mandatory-sequence edges, templated/no-op interface moves, latent
enumerator gaps a shifted trajectory reaches, illegal *starting* data no
prior sweep checked (Almoravid P-4), and **terminal scoring logic that
legality sweeps never check** (Plantagenet 5.1; Almoravid F8). LLM full-game
play (ideally key-free, in the model's own sandbox) is the cheapest way to
walk those corners *and* the only cheap way to catch an outcome bug, because
the model reasons about the result. The discipline that makes its findings
safe to fix is the one in Parts I–II: **mirror every handler check in the
enumerator (both directions), define each predicate once, validate the
palette, assert outcomes (not just legality), and re-run the full battery on
every change before merge.**

---

# Appendix A — Quick-start audit commands

```bash
# A1. Enumerator/handler divergence — list every handler rejection.
grep -n 'raise IllegalAction' src/<engine>/campaign.py | \
    sed -E 's/^([0-9]+):.*"([^"]+)".*/\1\t\2/'
# A1b. ...and the inverse: every handler key the enumerator must be able to emit.
grep -nE '"\w+":\s*_h_' src/<engine>/campaign.py
# A2. State-set-but-unreachable — setters; then find readers per setter.
grep -n "state\.\w*\.\w* = \(True\|<target_id>\)" src/
# A3. Rule-cite-but-no-enforce — every rule citation in comments.
grep -rn "per [0-9]\+\.[0-9]\+\|rule [0-9]\+\.[0-9]\+" src/
# A4. Off-edge calendar clamps.
grep -n "max(1, \|min(16, \|boxes\[-1\]" src/
# A5. Lifecycle cleanup on removal/disband.
grep -n "_remove_lord_permanently\|_disband_at_limit\|_sweep_all_orphaned" src/
# A6. Capability scope filtering — AND the scope values in card data.
grep -n "this_lord_capabilities\|capabilities_in_play\|capability_scope" src/
# A7. No-target-no-op events — resolvers that index state without a guard.
grep -nA20 'def _resolve_[RT][0-9]' src/<engine>/events.py | \
    grep -E 'state\.lords\[|state\.locales\[|state\.assets\['
# A8. Once-per-window flags — confirm both set and reset.
grep -n "acted_this_call_to_arms\|once_per_card\|_used_this_card" src/
# A9. Victory/scoring polarity — read every winner-determination return
#     AND every data-load into the score state (Almoravid F8).
grep -rn 'result.*:.*win\|"result"\|determine_winner\|def _victory\|taifas_box_vp\|compute_final_vp' src/
```

The first build-out task for a new port: the **round-trip sweep** from
Part II §1 and the **co-location invariant** from Part IV. Those two catch
the largest share of the families above on autopilot. Add **outcome
assertions** (Part II §9 / Appendix A9) the moment a victory rule exists.

---

# Appendix B — Contribution templates

## B1. New hazard pattern
```markdown
## Pattern NN — <name>
**Shape:** <one-line description of the bug shape>
**Detection heuristic:**
\`\`\`
<grep / inspection target>
\`\`\`
**Examples:**
- `[<Game> <bug-id>]` <one-line description>
**Audit checklist:**
- [ ] <question to walk through your code>
**Pre-built test ideas:**
- <regression pattern that catches the family>
```
Add a row to the **Hazard summary table** with the new number.

## B2. Cross-project advisory
```markdown
## Advisory #N (from <Game>) — <one-line title>
*Raised by <Game>-Harness.* <What the bug was, why it matters, what the
class is.>
**Recommendation to siblings:** <the concrete self-check.>
**<Your-Game> result:** <clean | fixed in RNNN | N/A — reason>, with
<lessons reinforced>.
```

## B3. Per-game findings ledger
Each team fills one row. "Patterns hit" lists the Pattern numbers from
Part I confirmed in that engine.

| Game | Engine status | Bugs found | Patterns hit | LLM-play used? | RNG in state? | Notes |
|---|---|---|---|---|---|---|
| Nevsky | mature (200+ rounds) | 162 SMOKEs | 1–14 (esp. 1,2,7,8) | yes — scripted + key-free sandbox | yes (`meta.rng_state`) | source of this guide |
| Inferno | active | — | raised Advisories #1, #2 (co-location class) | — | — | retreat-relocation + 3-door co-location class |
| Almoravid | mature (full clause-by-clause rulebook audit; 7 scenarios + Sagrajas battle minigame; advanced rules 6.1 Bidding / 1.5.2 Hidden Mats / 3.4.2 Advanced Vassal Service; 1008 passing tests) | ~50+ rules-audit items (L/C/B/S/T/E) + 8 LLM findings (F1–F8) + P-1..P-5 co-location + Q-001/Q-002 scope + Sagrajas terminal-cap | 2 (P-3, Door B), 3 (L9b), 7 (Sagrajas, L3, F4), 8 (Door B), 14 (Q-001, Q-002) + under-enum (Part II §1) + wrong-winner/outcome (Part II §9) | yes — Cowork-chat (Scenario A, 8 findings incl. F8) + key-free ChatGPT sandbox (Scenario F clean; found Sagrajas cap bug) | yes (`meta.seed` + `meta.rng_state`, SHA-256-keyed) | confirmed Advisory #1 (had the bug — Sally path P-3) and #2 (Doors B & C fixed, inside-placement N/A); confirmed Advisory #3 (wrong-winner F8 from a missing score data-load + inverted-shift L3); first non-Nevsky Pattern-14 examples, both data-scope bugs; always-on co-location invariant keyed on `in_stronghold`, gated by `pending is None` |
| Plantagenet | mature (full Levy + Campaign + Battle; Wars-of-the-Roses grand campaign with Succession) | several rounds; see repo `SMOKE_TEST_FINDINGS.md` | 1, 2, 7, 9, 10 + over/under-enum (Part II §1) + reversed-victory polarity (Part II §9) | yes — scripted full-game smoke + key-free ChatGPT sandbox | yes (`seed` + `rng_state`) | raised Advisory #3 (legality ≠ outcome); Advisories #1/#2 N/A (no relocating Retreat, no persistent siege marker); always-on co-location + influence-cap + lord-status + card-zone invariants |
| Pendragon | — | — | — | — | — | — |
| Henry (next) | not started | — | — | — | — | start with Part I + Part II §1 |

---

## Provenance & changelog

- Combines `FUTURE_PROJECTS_LESSONS.md` (14-pattern catalog) and
  `CROSS_PROJECT_LESSONS.md` (audit techniques + Inferno advisories) from
  the Nevsky-Harness repo, plus the validated-palette/LLM-sandbox lessons
  from Nevsky R219–R225.
- **Plantagenet contribution:** confirmed Patterns 1, 2, 7, 9, 10 and the
  over/under-enumeration families with tagged examples; added the card-zone
  invariant idiom (Part III); added Part II §9 (legality ≠ outcome) and
  Part IV §"classify the helper's rejections"; recorded Plantagenet results
  on Advisories #1/#2 and raised **Advisory #3**; filled the Appendix B3
  ledger row.
- **Almoravid contribution (this revision):** confirmed Patterns 2 (P-3
  Sally relocation; Door B Sail mirror), 3 (L9b stale `just_arrived` flag),
  7 (Sagrajas resolver fidelity; L3 inverted Service-shift direction; F4
  printed-vs-placed Seat markers), 8 (Door B orphan-sweep), and **14**
  (Q-001 Alférez + Q-002 Al-Garada — the first two non-Nevsky examples,
  both *card-data* scope bugs), plus the under-enumeration family (Part II
  §1: whole handlers the menu forgot) and a strong **Part II §9** outcome
  confirmation (F8 wrong winner from a missing score data-load — a new
  failure mode for Advisory #3). Recorded Almoravid results on Advisories
  #1 (had the bug — P-3/P-4/P-5), #2 (Doors B & C fixed; inside-placement
  N/A), and the no-op advisory (N/A so far); added the end-of-`apply_action`
  orphan-sweep idiom (Part III); confirmed the key-free ChatGPT-sandbox path
  and state-resident RNG; filled the Appendix B3 ledger row. Source data:
  the Almoravid-Harness repo, `VERIFICATION_LOG.md` + 1008-test suite +
  `tests/test_advisory2_doors_bc.py` / `test_advisory3_underenum.py` /
  `test_fix_retreat_relocation_p3p4p5.py` / `test_q001_alferez.py` /
  `test_resolver_sagrajas_fixes.py` / `test_taifas_box_vp_loaded_f8.py` +
  independent Cowork-chat (Scenario A) and key-free ChatGPT (Scenario F /
  Sagrajas) playthroughs.
- Source data: Nevsky-Harness, ~225 probe rounds + ~300 self-play sessions
  per batch + multiple key-free LLM full-game playthroughs; SMOKE-001
  through SMOKE-162.
- This file is intended to live **outside any single repo** and to be
  edited by every L&C team. When you contribute, add your tags (Part I),
  advisories (Part V), and a ledger row (Appendix B3).

*Maintained as a shared artifact for the Levy & Command harness community.*
