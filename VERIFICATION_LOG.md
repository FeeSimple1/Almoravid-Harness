# Rules Faithfulness Verification Log

Tracks the clause-by-clause audit of the harness against the official
Rules of Play (`reference/Almoravid_Rules_of_Play.txt`, extracted from
`source/Almoravid+Rules+of+Play+-+LIVING+RULES+(1).pdf`), the official
Errata, and printed card/component text. Per BRIEF "Rules Faithfulness
Is Non-Optional", no simplifications are permitted; every divergence is
either fixed or logged as a Q-NNN for user adjudication.

Status legend: VERIFIED (matches rules) | FIXED (diverged, corrected) |
Q-NNN (needs user adjudication, see RULES_QUESTIONS.md).

## Static data
- Forces (forces.json) — VERIFIED against Quick Reference Table 1
  (textual extraction of the image-only Player Aid Forces chart),
  cross-checked vs Almoravid Reference info.rtf. All 8 unit types'
  strikes (battle/storm), strikes-by-capability (Ballesteros/Aqqara,
  Arqueros/Alrama, Jabalinas/Harbah, Slingers), strikes-by-garrison,
  protection (armor/evade/auto-remove) match. Note: the .rtf omitted
  African Horse's Melee x1/2 secondary strike; Quick Reference Table 1
  and the engine include it (confirmed correct).
- Strongholds (strongholds.json) — VERIFIED against Quick Reference
  Table 2. City/Fortress/Town/Castle capacity, value, walls_range,
  garrison composition + capabilities, surrender dice, and Sack spoils
  all match.

## Subsystems
(in progress — audited section by section below)

## Audit findings (2026-05-20, rulebook-grounded) — disposition tracker

Severity → status. FIX = unambiguous rules violation, correcting.
ADJ = needs user adjudication (logged in RULES_QUESTIONS.md). OK = verified correct.

### Levy (§3)
- L1 Muster never places/advances Service marker (3.4.1) — FIX (critical).
- L2 Call to Arms (3.5) entirely unimplemented; Fealty-less Lords can't enter — FIX (critical).
- L3 Pay shifts Service LEFT; rules shift RIGHT (3.2.1) — FIX (critical, inverted).
- L4 Pay-with-Coin missing same-Locale/Taifa-Coin/multi-Coin targeting (3.2.1) — FIX.
- L5 Pay-with-Loot (3.2.2) missing — FIX.
- L6 Disband doesn't split Beyond-Service permanent-removal (3.3.1) vs At-Limit to-Calendar (3.3.2); no eligibility gate — FIX (critical).
- L7 Independent-Taifa-Lord Disband → Parias + Coin + VP not triggered (3.3 Important) — FIX.
- L8 Muster ignores Friendly/Unbesieged + Ready(box<=levy) gating (3.4.1) — FIX.
- L9 Muster greedy seat default + no failed-roll retry via Lordship (3.4.1) — FIX (seat=player choice) / ADJ retry.
- L10 Muster of Taifa Lord → Independent adjust (3.4.1) — FIX.
- L11 Levy Transport (3.4.3) missing (incl. return lost Serf) — FIX.
- L12 Vassal-associated Forces placed at Muster instead of withheld (3.4.1) — VERIFY/FIX.
- L13 AoW draw: Capability-deploy (3.1.2) vs Event-implement (3.1.3) not modeled; pending_draw dumped — FIX.

### Campaign / March (§4.0-4.3)
- C1 Besiege-or-Bypass mandatory choice after Withdraw (4.3.5) missing; Bypass markers never created — FIX (critical).
- C2 Approach cannot partition defenders (avoid some / withdraw some / fight rest) (4.3.4) — FIX.
- C3 Marshal Group March (4.3.1) unimplemented (only Lieutenant Lower-Lord moves) — FIX.
- C4 Laden simplified: ignores transport-carrying, mishandles Cart-over-Pass-with-1-Prov as illegal vs legal-laden (4.3.2) — FIX.
- C5 Avoid-Battle discard-to-Unladen + Spoils transfer (4.3.4) missing — FIX.
- C6 Campaign-start Capability excess discard (4.0) missing — FIX.
- C7 Plan: no per-Lord card cap 3/4 (1.9.2/4.1.1), no 5-Pass cap, accepts un-Mustered Lords — FIX (critical).
- C8 Lieutenant/Lower-Lord disband-orphan cleanup (4.1.3) — FIX (low).
- C9 Lieutenant+Lower-Lord may not Withdraw into Castle (4.1.3 note) — FIX (low).

### Battle (§4.4)
- B1 4.4.4 Losses rolls entirely missing (per-Routed-unit survival); winner restores ALL routed automatically — FIX (critical).
- B2 Flanking: rounds per-position instead of summing Flanking+opposed then rounding once (4.4.2) — FIX.
- B3 Pursuit marker mechanics / Concede-as-per-Round-action not run inside resolve_battle (4.4.2) — FIX/ADJ.
- B4 _battle_over uses all-units vs all-Lords; per-pair Reserve-only side spins to max_rounds — FIX.
- B5 Hit-assignment target selection greedy (4.4.2 ASSIGN HITS = owner choice) — ADJ (architecture).
- B6 Relief Sally array geometry (4.4.1) simplified — FIX.

### Siege/Storm/Sally (§4.5)
- S1 Siegeworks adds +2 markers; rule = +1 max 4 (4.5.1) — FIX (critical).
- S2 Surrender/Siegeworks order inverted; Surrender counts post-placement markers (4.5.1) — FIX (critical).
- S3 Garrison never Strikes in Storm (4.5.2) — FIX (critical).
- S4 Storm round-cap defaults to 4 not Siege-marker count in normal path (4.5.2) — FIX (critical).
- S5 Storm Sack: no Lord removal, no Lord-Spoils, no Stronghold-Spoils (4.5.2) — FIX (critical).
- S6 Surrender Ravaged count: whole-Taifa uncapped vs locale max-1 (4.5.1) — FIX.
- S7 Storm attacker absorbs with Armored units first (4.5.2) — FIX.
- S8 6-Melee cap per-step vs per-Lord (4.5.2) — FIX.
- S9 Sally defenders' Siegeworks-as-Walls missing (4.5.3) — FIX.
- S10 Storm Concede (attacker, after Round 1) (4.5.2) — FIX.
- S11 Storm Array/Front<=Capacity/Reserve (4.5.2) — FIX.

### Taifa / Conquest / Victory (§1.4, 5)
- T1 Sevilla 3x VP weighting (Reconquista 9 / Parias 3) missing (1.4.2/5.1) — FIX (critical).
- T2 Muslim Conquest Jihad: only reconquista+conquered>0; misses Parias + Seat-only; doesn't remove Christian markers (1.4.4) — FIX (critical).
- T3 adjust_taifa_status Jihad bypasses eligibility + hardcodes value (1.4.4 Important) — FIX.
- T4 adjust_taifa_status OR-choices auto-resolved (1.4.3 player choice) — ADJ.
- T5 Parias Coin transfer not applied in non-Disband paths (1.4.3) — FIX.
- T6 Curias deducts Christian score vs removing Taifas-box Conquered marker (5.1 note) — FIX.
- T7 Conquered-marker side inferred by territory, not tracked (1.3.1) — FIX (model).

### End-Season / Feed (§4.8-4.9)
- E1 Grow (Spring-2 Ravage halving) (4.9.2) missing — FIX (critical).
- E2 Harvest (Summer-2 Cart/Mule halving) (4.9.2) missing — FIX (critical).
- E3 Repairs (remove 1 Siege from 3-4 stacks, non-Winter) (4.9.3) missing — FIX (critical).
- E4 Feed: only active Lord, not both sides' Moved/Fought (4.8.1) — FIX.
- E5 Feed Sharing among same-Locale Lords (4.8.1) missing — FIX.
- E6 Feed Greed mule-discard option (4.8.1) missing — FIX.
- E7 Asset Sharing 1.5.2 not enforced (March/Pay/Avoid) — FIX.

### Verified OK
- Forces/Strongholds data; ratings (lords.json vs Lords.txt); player order; Service-marker model; Campaign Victory 5.2; tie=draw 5.3; Greed has NO wrong 8-cap; Supply route/transport/Forage/Tax correct; Wastage 4.9.4 correct; effective.is_friendly_locale matches 1.3.1.
