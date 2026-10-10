# Scenario D playtest fixes — 2026-10-10

Repairs for the six defect categories found in the Scenario D / seed 42 game
on `9131a76d12dbbdde8838e06ae7a8412e6cbae546`.

## Changes

1. **Friendly-territory recapture (Rules 1.3.1; Errata 4.5.1).** Conquest now
   distinguishes the underlying Territory from the captured Stronghold's
   marker-overridden allegiance. A Muslim recapture in an Independent Taifa,
   or a Christian recapture in a Kingdom/Reconquista Taifa, removes enemy
   markers without creating new ones. Enemy Seat/Cathedral markers are
   removed in all conquest branches. Both sides' marker VP are adjusted,
   including loss of the former owner's points. Repeated conquest cannot
   duplicate points. Own Siege and Bypass markers clear.
2. **Scenario D starting capabilities.** M10 Andalusians, M12 Al-Yazirat
   al-Hadra, and M16 Camels now have authoritative `CardInPlay` records in
   addition to their board-edge entries. Yusuf's double Seat supplies two
   Provender, and the existing combat/transport effects can find their cards.
   This repairs fresh scenario setup; it does not migrate old saved games.
3. **Scenario D First Levy.** Alfonso and al-Mustain may participate in the
   first Muster despite their siege. The exception does not apply in later
   Levies or other scenarios and does not override Event bans or the ban on
   newly arrived Lords participating. Menus and handlers share one gate.
4. **C20 Al-Qadir player choice (Arts of War Reference, C20 Event).** The
   Christian player explicitly selects the individual Jihad markers. The
   legal-action menu enumerates same-Locale and split-Locale choices within
   one eligible Taifa. Missing/invalid targets are rejected without consuming
   the held card or changing the state; there is no greedy default.
5. **Muster bans (C24 and other Events banning Muster 'of or by' a Lord).**
   A banned Lord cannot levy Transport, Vassals, or Capabilities, recruit
   another Lord, or participate in free Muster effects. The shared gate also
   covers free Fonsadera exchanges, including the direct action endpoint.
6. **C21 Sisnando Davidez (Arts of War Reference, C21 Capability).** Only
   Alfonso may Levy it; it goes to the board edge and consumes no personal
   capability slot. The effect looks up the side-wide card, is available
   during Levy rather than Campaign, and is free once per Levy. Target
   occupancy, Siege/Bypass exclusion, and Alfonso's presence remain required.

## Public action payloads

Play held Al-Qadir and remove both markers at Ucles:

```json
{"type":"play_event","side":"christian","card_id":"C20",
 "payload":{"locale_ids":["ucles","ucles"]}}
```

Split the two markers within the same eligible Taifa:

```json
{"type":"play_event","side":"christian","card_id":"C20",
 "payload":{"locale_ids":["calatrava","ucles"]}}
```

`payload.locale_id` is also supported when all required markers come from
one selected Locale. A single-item `locale_ids` list is legal only when that
eligible Taifa has just one Jihad remaining. The card never removes markers
from two Taifas, an Independent Taifa, or a Taifa containing a Muslim Lord.
No-target play returns `choice_required` when eligible choices exist.

Sisnando's free, optional action during Levy:

```json
{"type":"cap_sisnando","side":"christian","target_locale":"ucles"}
```

## Regression coverage

`tests/test_playtest_oct10_regressions.py` covers all six categories, both
Muster menus and execution, first-Levy limits, save/load and discard of
starting cards, supply and transport effects, symmetric reconquest and VP,
Al-Qadir target combinations and atomic rejection, Event bans on paid/free
Muster, and Sisnando's scope/eligibility/timing/once-per-Levy behavior.

The original eleven playtest assertions were reproduced before patching.
Ten saved-position checks pass after patching without changing their calls.
The eleventh concerned a save already missing its starting capability
records: the corrected supply behavior is tested from fresh Scenario D setup
rather than adding a legacy-save migration.

Older tests were corrected where they encoded the reported defects: automatic
Al-Qadir targets, personal/Campaign Sisnando use, extra Conquered markers in
friendly Reconquista territory, omitted former-owner VP deductions, and M8
Supply calculated without Scenario D's starting double-Seat capability.

The former game's exact final-state fingerprint is not a regression target:
it records the buggy rules and its combat, choices, and logistics can diverge
under the repaired implementation. Use the rules tests and fresh self-play.

## Verification results

- Before changes: all 11 original rules assertions reproduced their failures.
- Focused corrected-rule suite: 94 passed, including 52 new regression cases.
- Complete suite: 1,392 passed locally (Python 3.13).
- Additional invariant-checked self-play: 15 completed sessions, 11,525 actions;
  nine Scenario D runs (seeds 1, 2, 42; survival/combat/siege profiles) and
  six Scenario F runs (seeds 1, 2; all three profiles). No reported crashes,
  stalls, enumerator/handler dead ends, or invariant violations.
