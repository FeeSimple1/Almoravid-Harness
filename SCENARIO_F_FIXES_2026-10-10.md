# Scenario F winter and Bishoprics fixes — October 10, 2026

Baseline: `c4468413f486fa7361ade8467ee90f352ebcc323`.
The Scenario F / seed 73 playtest exposed four rules defects. All nine
original saved-position assertions fail on that baseline and pass with this
patch. The board/RNG fixtures (history omitted only) are committed under
`tests/fixtures/scenario_f_seed73/`.

## Changes

1. **Winter Service retention (Rules of Play 6.3.1–6.3.2).**
   Winter removes Service only for Lords actually Disbanded or removed.
   Besieging and Besieged Lords retain their own and advanced Vassal Service
   markers, including off-edge Service bookkeeping. Paying a retained Lord
   advances the existing marker rather than creating a marker at box 1.
   Departing Lords' Vassal markers are cleared with their mats.

2. **Spring Muster (6.3.3 → 3.4.1; Errata, 3.4.1).**
   Spring uses the shared ordinary-Muster initializer and free-Seat check.
   It restores printed Forces/Assets, available Ready Vassals, and one new
   Lord Service marker; it does not grant Vassal troops or resurrect
   permanently removed Vassals. Lords still at siege are not reinitialized.
   Enemy-controlled Seats remain prohibited even when no enemy Lord is there.

3. **Bishoprics discard (Arts of War Reference C22; Lords Reference,
   Special Vassals → Bishops).**
   Both winter and Campaign-entry board-edge discard remove special Bishop
   markers, their Mustered units, and allocation state. A Ready Bishop has
   added no troops and removes none. Cleanup is idempotent and cannot create
   negative forces. Sancho's ordinary Bishop of Jaca is not a special Bishop
   and is unaffected. Availability is derived from the actual markers, so
   reacquiring the card is not blocked by stale allocation history.

4. **Bishoprics timing (3.4.2; Arts of War Reference C22).**
   Free Ready-marker placement is no longer restricted to Command activations.
   It is available during Levy, planning, and pending responses without
   spending an action or changing the active player/pending decision. The
   player can choose the printed Bishop via `bishop_id`; the menu lists each
   choice. Recruiting its troops remains a separate ordinary Muster action,
   with normal eligibility restrictions. C22 Bishops are correctly exempt
   from advanced Vassal Service. See `ACTIONS.md` for the action format.

## Verification

- **47 new regression cases:** nine original saved-position cases and 38
  targeted cases covering both siege sides, normal/advanced Service, Spring
  Muster initialization and legal Seats, marker choice, invalid-action
  atomicity, troop cleanup, reacquisition, and out-of-turn/pending placement.
- **1,439 tests pass** on Python 3.13, without changing older test expectations.
- **18 additional completed self-play sessions / 14,192 accepted actions:**
  Scenario D and F, seeds 1, 2, 73, survival/combat/siege profiles. No reported
  crashes, stalls, or invariant violations. Six Scenario F sessions reached
  the Scenario End marker in box 15; the three combat profiles ended earlier.
- **Original siege-line continuation:** replayed the first 726 accepted
  actions from a fresh seed-73 game, without the withdrawal workaround.
  Both Alfonso and Álvar remain at Talavera after both winter periods with
  Service in box 9. The continuation made 859 total accepted actions and its
  exact final state replays. It later ended in an ordinary box-9 Campaign
  defeat; this is not presented as a full-length or rules-exhaustive game.
- The 18 stress sessions are regression checks, not proof of complete rules
  fidelity; their structural checks would not by themselves catch the four
  semantic defects repaired here.

GitHub verification is a separate gate before the tested source branch is
published and merged. No temporary publishing workflow belongs in `main`.
