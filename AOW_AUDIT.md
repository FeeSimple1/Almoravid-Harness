# Arts of War — Card-by-Card Audit

A card-by-card reconciliation of all 52 Arts of War cards (each with an
Event half and a Capability half) against the official reference
(`reference/Almoravid Arts of War Reference.txt`), the card metadata
(`src/almoravid/data/static/cards.json`), the implementation, and tests.

**Method.** Four parallel passes (Christian Events, Muslim Events,
Christian Capabilities, Muslim Capabilities). Each card half was compared
to the reference effect text *and* its "Tips" nuances; every claim was
grep-grounded against code and tests. The highest-impact findings were
then re-verified by hand before fixing or recording here.

**Headline.** The Event halves are in good shape — nearly all implemented
and tested, with a handful of partial/wrong cases. The **Capability halves
are not**: roughly a third of capability *effects* are dead data — correct
metadata and (sometimes) eligibility, but no rules effect wired up. This
is the single largest fidelity gap in the project and is a deliberate
scope decision for the owner (a feature build-out), not a quick fix.

---

## RESOLUTION (2026-06-21 follow-up): every gap above is now implemented

The dead-data capability cluster and the partial/wrong event cases below
have all been implemented and tested. The 18 previously-unimplemented
capability effects, the 4 partial capabilities, the partial/wrong events,
the eligibility-gating gap, and the metadata-flag inconsistencies are
CLOSED. Summary of what was added (each with regression tests):

- Levy Jihad removal: **C20 Fueros**, **C21 Sisnando Davidez**.
- Muster-units: **C13/M23 Count of Barcelona**, **C18 Milites**,
  **M15 Saqalibah**, **M20 Al-Rum**, **C22 Bishoprics**.
- Exchange: **C23 Fonsadera**.
- Combat: **C24 Garcia Jimenez** (+2 Storm rounds), **M17 Arrada**
  (+3 Missile Hits at -2 Armor in Storm/Sally).
- March/Supply: **M19 Guadalquivir** (network March), **M12 Al-Yazirat
  al-Hadra** (double Supply Source), **Adalides (C3/C10)** + **War Drums
  (M22)** "Bypass without stopping".
- Deck: **C25/M25 El Cid** + **M8 Dawud(b)** (play named Events from deck),
  **C26/M26 Al-Faraj** (force enemy Held discard).
- Events: **C9 Betrayal** OR-choice; **M13 Severed Heads** Ravaging trigger;
  **C3/M3 Swollen River** Avoid-block; **C26 Freebooter** Reconcile clause;
  **C5/M16 Drought** Camels opt-out; **M16 Camels** Mules-double;
  **M25/M26 Freebooter** event; **C13/M23 Berenguer Ramon** discard removes
  the Count's granted units + own-side eligibility.
- Cross-cutting: eligibility gating for the restricted combat/Rodrigo/Yusuf
  caps (`_CAPABILITY_ELIGIBLE_LORDS`); `event_persistence` metadata flags
  corrected to match card text (the reader `_is_immediate` was unused, so
  cosmetic-only); added coverage tests for previously-untested effects.

The sections below are retained as the original audit record.

---

## Fixed in this pass (5)

Contained bugs in already-implemented features — verified by hand, fixed,
and covered by `tests/test_aow_audit_fixes.py`.

1. **M6 Feigned Retreat — dead in real play (bucket mismatch).** The
   resolver parked M6 in `this_campaign_events`, but the Battle/Sally
   Round-2 reorder readers and `_discard_round1_events` only consult
   `this_levy_events` (where the sibling one-Round Holds C8/M7 live). So
   via the real `resolve_event` path the Round-2 melee reorder never fired
   and never discarded; the two existing tests passed only because they
   injected `this_levy_events` directly, bypassing the resolver. FIX: M6
   now routes to `this_levy_events` like C8 Cantador / M7 Spear Wall.

2. **C9 / M7 Slingers — 3-per-Lord cap ignored.** `forces.json` carries
   `max_per_lord:3` on the slingers cap row, but `build_strike_rows`
   only enforced the javelin budget; 5 Militia fired 5 Slingers. FIX:
   added a per-Lord slinger budget of 3 in both strike-row builders.

3. **C7/M3/M6 Javelins & C9/M7 Slingers — no Storm halving (4.5.2).** The
   capability missile rows fired at x1 in Storm; rule 4.5.2 makes Javelins
   and Slingers x1/2 in Storm. FIX: cap rows of kind javelins/slingers are
   halved when `context=="storm"`.

4. **C20 Al-Qadir (event) — removed Jihad across multiple Taifas.** The
   handler flattened all eligible Taifas and removed 2 markers across them;
   the card says "any two Jihad markers **within a single** eligible
   Taifa." FIX: removal is confined to one Taifa (the one with the most
   Jihad available).

5. **C4/M4 Arid Terrain — under-fed a group March.** Only the active Lord
   was force-fed; the card ("Feed 2 Marching Lords" / "that Lord or any two
   Lords Marching as a group") requires feeding the group. FIX: feeds the
   active Lord plus group-March members, capped at 2.

---

## Unimplemented capability effects — DEAD DATA (owner decision)

These capabilities have card metadata (and sometimes eligibility) but **no
rules effect** is implemented; greps find only the same-ID *event* half or
an eligibility entry. Implementing them is a substantial build-out (new
actions, new combat hooks, new Levy mechanics) and should be scoped
deliberately. Verified absent in `src/almoravid/` at audit time.

| Card | Capability | Reference effect | Why it matters |
|---|---|---|---|
| C13 | Count of Barcelona | Pay 2 Coin once → Muster 2 Knights + 2 MaA until discarded | No card-Muster action; the C13 *event* even injects the units permanently instead (see Partials) |
| C18 | Milites | Christian Lords pay 1 Asset → Muster ≤3 of the card's units each | Only the discard-removes-from-game rider exists; units appear only via scenario setup |
| C19 | Caballería Villana | Muslim Ravage in Kingdoms must roll 1-3 for effect; blocks al-Maghawir | Christian counterpart to Ribat Monks; Muslim Ravage in León/Aragón is unconstrained |
| C20 | Fueros | Each Levy, remove ≤2 Jihad from a Reconquista Taifa Locale Alfonso is closer to | (distinct from the C20 *event*, which is fixed above) |
| C21 | Sisnando Davídez | Each Levy, remove ≤1 Jihad from a Locale with no Lord of either side | name collision: "C21" in code is the Mozárabes *event* |
| C22 | Bishoprics | Add 1 Bishop (Ready Vassal) to ≤3 Christian Lords ≠ Sancho; discard removes all | setup hard-codes raw units, not Bishop Vassals; no in-game add action |
| C23 | Fonsadera | During Muster, exchange Ready non-Bishop Vassals for 1 Coin OR 3 Transport each | no exchange action exists |
| C24 | García Jiménez | This Lord's Storm may go 2 extra Rounds | `_storm_setup` max_rounds = max(1, siege); never +2 |
| C25 | El Cid | Rodrigo may play Swollen River/Surprise/Camp Attack/Cantador/Baggage Parapet from deck | all "C25" code is the De Vivar *event* |
| C26 | Al-Faraj | Rodrigo at/adjacent to a Muslim Lord forces Muslims to discard 1 random Held card | all "C26" code is the Freebooter *event* |
| M12 | Al-Yazirat al-Hadra | Flip Yusuf & Sir Seat markers to 2 Seats; Locale = 2 Supply Sources | only the Taifa Marriage *event* exists; scenarios pre-place seats |
| M15 | Saqalibah | This Lord may Muster 2 MaA (once, free) | only hard-coded inside the Sagrajas scenario script |
| M17 | Arrada (Catapults) | This Lord at Storm/Sally adds 3 Missile Hits/Round, −2 Enemy Armor | no Storm/Sally hook |
| M19 | Guadalquivir | Taifa Lords March directly among Ports + 5 named Sevilla Cities/Towns, normal cost | only the African Fleet *event* (one-shot, Ports-only, whole card) is coded — materially different |
| M20 | Al-Rûm | This Lord pays 1 Coin once → Muster 2 Knights | only the Mudéjares *event* exists |
| M23 | Count of Barcelona | This Lord pays 2 Coin once → Muster 2 Knights + 2 MaA until discarded | only the Berenguer Ramon *event* exists |
| M25 | El Cid | Rodrigo al-Sayyid may play 5 named Events from deck | unimplemented |
| M26 | Al-Faraj | Rodrigo al-Sayyid forces Christians to discard 1 random Held card | unimplemented |

Partial capability effects (one sub-effect works, others missing):

| Card | Capability | Implemented | Missing |
|---|---|---|---|
| C3/C10 | Adalides | "ignore Swollen River" | "Bypass without stopping" (March on same card after Bypass) |
| M8 | Dawud ibn Aisha | (a) Supply +1 Prov | (b) play Feigned Retreat/Spear Wall/Camp Attack from deck in Battle |
| M16 | Camels | (a) discard to ignore Arid Terrain | (a) ignore Drought; (b) Yusuf/Sir Mules count double for move & Supply |
| M22 | War Drums | Ravage +1 Prov (Yusuf/Sir/Lieutenants) | "Bypass without stopping" |

---

## Partial / wrong implemented features — recorded, not yet fixed

These are coded but diverge from the card; left for a follow-up so each can
get a proper fix + test (none are silent combat-math errors):

- **C9 Betrayal of Terms (event)** — always applies the *double-Spoils +
  Muslim Jihad* branch; the player's alternative ("take Spoils as if Sack",
  single, no Jihad) is not selectable. It's an "OR" choice.
- **M13 Severed Heads (event)** — only the Christians-Retreat → +4 Jihad
  sub-option fires (auto). The Ravaging trigger, the Sacked trigger, and
  the "for 2 Lords" cylinder-shift sub-option are missing.
- **C13 / M23 Berenguer Ramon (event)** — the "Count with Christians →
  discard" branch is a no-effect discard; per the card it should remove the
  Count-of-Barcelona capability's granted forces. C13's grant path also
  injects units permanently instead of via the capability, and never sets
  `meta.count_of_barcelona_side`. M23's eligible-Lord list wrongly includes
  Christian-side lords.
- **C3 Swollen River (event)** — only the block-March branch exists; the
  "block Avoid Battle (→ Battle, no Asset discard)" branch is missing.
- **C26 Freebooter (event)** — mandatory Disband works; the optional
  "Reconcile with Rodrigo for 1 VP" clause is deferred.
- **C5 Drought (event)** — the "Muslims may discard Camels to cancel"
  opt-out is not offered (C4's is).
- **M25/M26 Freebooter event half** — `cards.json` marks both
  `no_event:true`; the reference describes a Muslim Freebooter event
  (mirror of C26). Needs a rules check: genuinely capability-only, or a
  missing event half?

---

## Cross-cutting

- **Eligibility not gated for most combat capabilities.** Only a few cards
  are in `_CAPABILITY_ELIGIBLE_LORDS`. Combat caps restricted by card text
  to "Taifa Muslim or Rodrigo al-Sayyid" (M1, M2, M3/M6, M4/M5, M7, M13,
  M17) can currently be Levied/deployed to any Muslim Lord (incl.
  Yusuf/Sir). Low gameplay impact today but a fidelity gap.
- **Pooled multi-Lord missile caps may over-apply.** `battleside_for_lords`
  unions all Lords' capabilities into one pooled BattleSide; on the pooled
  (non-`array`) path a this-Lord missile cap held by one Lord would grant
  its row to every Lord's pooled units. The per-position path is correct.
  Worth a targeted test to confirm which path real multi-Lord battles take.
- **Metadata persistence flags.** `cards.json` `event_persistence` is
  `immediate` for several "Hold:" cards (C2, C6, C9, C18, M2, M18, M19) and
  `hold` for the immediate C5. Behavior is currently correct because the
  resolvers hardcode the bucket, but the flags are inconsistent — and M6
  (now fixed) shows the failure mode this class can cause.

---

## Untested-but-believed-correct (add coverage)

UPDATE 2026-07-05: the capability-effect half of this list is now covered —
C2 target selection (tests/test_crossbow_target_policy.py), C4/C5 + C7
firing in combat and C6 Round-2 trigger (tests/test_bgbook_jativa_storm.py,
tests/test_missile_overlap_dedup.py), C1/M1 Battering Ram reroll +
counts-as-2, M13 Siege Towers gating, M22 War Drums extra Prov
(tests/test_aow_coverage_backfill.py). STILL OPEN (event halves): M3, M4,
M5 (Muslim path), M8 remove-Conquered branch, M9 +4 Kingdom branch, M10
Fatwa, M20 +1/+2 branches, M24 placement path, C16 Muster-from-Calendar
mode, C23 service mode.

Also note: the "Pooled multi-Lord missile caps may over-apply" item under
Cross-cutting is CLOSED for every path — Battle (d4f4ec3), Storm
(cap_groups), Sally + Relief lanes and the pooled-staleness clamp
(2026-07-05, tests/test_sally_relief_cap_scope.py).
