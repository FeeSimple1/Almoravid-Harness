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
- L2 Call to Arms (3.5) entirely unimplemented; Fealty-less Lords can't enter — FIXED 2026-05-20. Implemented all 3.5.1/3.5.2 options as explicit actions (no greedy defaults): cta_reconcile_rodrigo, cta_employ_rodrigo (Campeador 2 Coin / al-Sayyid 3 Coin), cta_call_crusade (+ Muslim follow-up cta_add_crusade_jihad), cta_invite_almoravids, cta_uphold_dynasties, cta_call_emir (muster|shift). One-option-per-side enforced via Meta.cta_option_used_{side}; Christian-first/Muslim-then via active_player. Enumerator _call_to_arms_moves populated. Tests: tests/test_fix_call_to_arms.py (14). SUB-ITEM REMAINING: 3.5.3 Discard 'This Levy' events — deferred, NOT a silent simplification. Reason: this_levy_events currently mixes Hold-persistence cards (kept into Campaign by design) with deliberately-retained immediate events (e.g. C6 Surprise, consumed by a Campaign March trigger). A blanket discard would break those mechanics; a scope-aware discard needs a per-card 'This Levy'-only flag that the card data does not yet expose. Tracked as L2b.
- L3 Pay shifts Service LEFT; rules shift RIGHT (3.2.1) — FIX (critical, inverted).
- L4 Pay-with-Coin missing same-Locale/Taifa-Coin/multi-Coin targeting (3.2.1) — FIX.
- L5 Pay-with-Loot (3.2.2) missing — FIX.
- L6 Disband doesn't split Beyond-Service permanent-removal (3.3.1) vs At-Limit to-Calendar (3.3.2); no eligibility gate — FIXED 2026-05-20. Disband now gated on Service-marker position (box <= current Levy/Campaign box; mandatory). box<current => permanent removal (cylinder 'removed', caps -> board_edge, Seat + Lord/Vassal Service markers removed); box==current => to Calendar (service_rating boxes right; caps discarded; Service markers set aside; Seat removed). pass_step blocked + pass_step de-listed in service_disband while a mandatory Disband is pending. Tests: test_real_levy.py (rewritten 4) + test_fix_disband_331_332.py.
- L7 Independent-Taifa-Lord Disband -> Parias + Coin + VP not triggered (3.3 Important) — FIXED 2026-05-20. Disband of an Independent Taifa Lord now calls adjust_taifa_status(->parias), awards Parias Coin (= the Lord's Service rating: 6 al-Mutamid / 4 others) to Unbesieged Christian Lords' mats (explicit parias_coin_targets, enumerator supplies a deterministic distribution), and +1 running Christian VP (final VP recomputed from Parias status). NOTE: which Christian Lord(s) receive the Coin is a minor Christian player choice surfaced via parias_coin_targets; totals/VP are unaffected by the distribution.
- L8 Muster ignores Friendly/Unbesieged + Ready(box<=levy) gating (3.4.1) — FIXED 2026-05-20. Ready gate (box<=levy) was added with L1; the 3.4-intro Friendly+Unbesieged (Bypassed OK) gate for Lordship-spending Levy actions is now enforced via _require_levy_actor_eligible on levy_take_vassal / levy_take_capability / levy_transport, and mirrored in _muster_moves. Besieging Lords at Enemy Locales are correctly excluded. Tests: test_fix_levy_transport.py.
- L9 Muster greedy seat default + no failed-roll retry via Lordship (3.4.1) — PARTIAL 2026-05-20. Seat is now an explicit player-choice param (enumerator lists each free Seat); failed Muster rolls leave the Lord on the Calendar so re-issuing muster_lord retries. REMAINING (L9b): Muster does not yet cost the LEVYING Lord a Lordship point (3.4.1 'A Lord may use a Levy action ... to enable another Lord to roll for Muster'). Today muster_lord is free with no designated levying Lord. Needs a levying_lord_id param + Lordship spend (and Arts-of-War auto-Muster cards bypass it). Tracked as L9b. — L9b FIXED 2026-05-20: muster_lord now requires an explicit levying_lord_id; the Levying Lord must be on the map, Friendly+Unbesieged, have spare Lordship, and not be newly Mustered this segment (3.4.1); each attempt (success or fail) spends 1 Lordship. Added per-Levy reset of just_arrived_this_levy (was set-but-never-read/never-reset). Enumerator emits per (rolling Lord, Seat, eligible levier). AoW auto-Muster cards bypass via their own handlers. Tests: test_fix_muster_lordship.py.
- L10 Muster of Taifa Lord → Independent adjust (3.4.1) — FIX.
- L11 Levy Transport (3.4.3) missing (incl. return lost Serf) — FIXED 2026-05-20. New action levy_transport: spend 1 Lordship to add one Cart or Mule; if the Lord has lost a Serf (current serfs < starting serfs from static data), return one Serf (required). Enumerated in _muster_moves. Tests: test_fix_levy_transport.py.
- L12 Vassal-associated Forces placed at Muster instead of withheld (3.4.1) — VERIFIED OK 2026-05-20. lords.json keeps each Lord's base `forces` separate from `vassals[].forces`; _h_muster_lord places only base forces, and vassal forces enter via levy_take_vassal. No double-count; rule satisfied.
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
- B2 Flanking: rounds per-position instead of summing Flanking+opposed then rounding once (4.4.2) — FIXED 2026-05-20. _resolve_step_per_pair reworked into two phases: (1) gather each Front actor Lord's raw half-Hits and route to a target Lord (same position, else Flanking to the largest Front enemy), accumulating per target keyed by target identity so opposed + Flanking strikers COMBINE; (2) round each target's combined half-Hit total UP ONCE (mixed-missile Crossbow priority applied to the combined total via _allocate_rounded_hits), then resolve Protection/Rout. Previously each striking Lord rounded separately (two 0.5-Hit Lords on one target gave 2 Hits instead of 1). Per-Lord Hills/C8/Concede adjustments apply before summing. Tests: tests/test_fix_b2_flanking_rounding.py (3).
- B3 Pursuit marker mechanics / Concede-as-per-Round-action not run inside resolve_battle (4.4.2) — FIX/ADJ.
- B4 _battle_over uses all-units vs all-Lords; per-pair Reserve-only side spins to max_rounds — FIXED 2026-05-20. (a) Termination/winner now expressed as all-LORDS-routed via _side_all_lords_routed: when a side has an array, it is defeated only when NO LordPosition (Front OR Reserve) has unrouted units (Garrison also keeps a Storm Defender alive); pooled sides fall back to has_unrouted. _battle_over and the resolve_battle winner block both use this, so a side reduced to Reserve-only is NOT yet defeated (its Reserve Lords Advance to Front at the next Reposition). (b) Root cause of the spin — 4.4.1 Defender placement: battleside_for_lords gained a front_limit param; the campaign battle call sites (_h_cmd_battle, _h_respond_stand_battle) now build the Attacker first and pass front_limit=_front_lord_count(atk) to the Defender so the Defender places exactly one Lord opposite each Attacking Front Lord and sends all extras to Reserve (previously it always filled up to three Fronts, leaving a permanently-unopposed Front Defender that never took Hits). The Attacker build now also passes active_lord_id so the Active Lord starts at Front center (4.4.1). Tests: tests/test_fix_b4_battle_over.py (6).
- B5 Hit-assignment target selection greedy (4.4.2 ASSIGN HITS = owner choice) — ADJ (architecture).
- B6 Relief Sally array geometry (4.4.1) simplified — FIX.

### Siege/Storm/Sally (§4.5)
- S1 Siegeworks adds +2 markers; rule = +1 max 4 (4.5.1) — FIXED (prior session): cmd_siege Siegeworks +1 (max 4), capacity-gated. Tests: test_fix_siege_451.py.
- S2 Surrender/Siegeworks order inverted (4.5.1) — FIXED (prior session): Surrender rolled FIRST vs existing markers, then Siegeworks +1. Tests: test_fix_siege_451.py.
- S3 Garrison never Strikes in Storm (4.5.2) — FIXED (prior session): Garrison MaA crossbows + Militia bowmen + melee strike rows in Storm. Tests: test_fix_garrison_strikes.py.
- S4 Storm round-cap (4.5.2) — FIXED (prior session): max_rounds = besieger Siege-marker count at the Locale. Tests: test_storm_walls_and_cap.py.
- S5 Storm Sack (4.5.2) — FIXED (prior session): losing Defenders permanently removed + Lord Spoils + Stronghold Spoils distributed; Conquest applied. Tests: test_fix_storm_sack.py.
- S6 Surrender Ravaged count (4.5.1) — FIXED (prior session): Ravaged bonus is the per-Locale flag (+1 if this Locale ravaged by besieger color), not whole-Taifa. Tests: test_fix_siege_451.py.
- S7 Storm attacker Armored-first absorption (4.5.2) — FIXED (prior session): Storm attacker forced absorb_policy='armored_first'. Tests: test_absorption_policy.py.
- S8 6-Melee cap per-step vs per-Lord (4.5.2) — FIXED 2026-05-20. resolve_storm now computes Melee per Front Lord, combining horse+foot and capping each Lord at 6 Hits/Round (this also fixes a latent bug where the old code capped each substep separately, allowing up to 12 for one Lord). Garrison Melee is added uncapped. Tests: test_fix_storm_array.py::test_attacker_combined_melee_capped_at_six.
- S9 Sally defenders' Siegeworks-as-Walls (4.5.3) — FIXED 2026-05-20. resolve_sally now passes defender_walls_range=(1, besieger Siege-marker count) into resolve_battle so the besieging DEFENDER cancels Sallying-attacker Hits via Siegeworks-as-Walls; the Sallying attacker still gets no Walls/Garrison. Tests: test_fix_sally_siegeworks.py (statistical: more survivors with Walls 1-4).
- S10 Storm Concede — attacker-only, start of each Round after the first (4.5.2) — FIXED 2026-05-20. cmd_storm accepts concede_after_round (>=2); resolve_storm ends the Storm at the start of that Round with the Attacker losing. Per-combat policy (Option A). Tests: test_fix_storm_array.py::test_attacker_concede_round_two_loses.
- S11 Storm Array (4.5.2) — FIXED 2026-05-20. resolve_storm tracks per-Lord Front/Reserve: Front begins with <=1 Lord, never exceeds Stronghold Capacity; only Front Lords (+ Garrison for the Defender) Strike/absorb; Reposition (Round 2+, reposition_defender policy) brings one Reserve to Front, with forced advance when all Front Lords Rout. Tests: test_fix_storm_array.py (front_begins_with_one, reposition_adds_reserve, front_never_exceeds_capacity). DOCUMENTED SCOPE: the Attacker is the single Active Lord (cmd_storm launches one-Lord Storms); multi-besieger Attacker Storms with Attacker Reserves/Reposition are not modeled (tracked S11b). Multi-Lord Defender survivor write-back on Attacker-loss is also not committed today (pre-existing; Sack removes all losing Defenders anyway).

  ARCHITECTURAL NOTE (S8/S10/S11, and FIX-C battle-array items): the combat resolver (resolve_battle/resolve_storm) runs ATOMICALLY — it plays all Rounds in one call with no opportunity for the controlling player to make mid-combat decisions. Several rules require exactly such decisions: Storm Concede (start of each Round after the first, 4.5.2), Reposition (each Round add one Reserve Lord to Front, 4.5.2), and per-Lord Front/Reserve placement. The engine already resolved one such case (Hit-absorption, 4.4.2) by making it a PER-COMBAT POLICY chosen up front rather than a per-Hit interactive choice. S8 (per-Lord 6-Melee cap) additionally needs per-Lord strike computation, which the pooled resolver lacks. RESOLUTION OPTIONS: (A) extend the per-combat-policy pattern — pre-declared Concede-after-Round-N, Reposition order, Front selection — keeping resolution atomic; (B) make combat step-wise interactive (pause for player decisions between Rounds), a larger change to the action/turn model. Pending user direction before implementing S8/S10/S11; BattleSide.conceded already exists but is set by no handler today. DECISION 2026-05-20 (user): use OPTION A — per-combat policies. The Storm resolver will be reworked to track Front vs Reserve Lords per side (Front begins with <=1 Lord — the Active Lord for the Attacker; Front never exceeds Stronghold Capacity), compute strikes PER FRONT LORD with each Lord's Melee capped at 6 (S8), and accept pre-declared policy parameters on cmd_storm: front-order / reposition-order per side (S11 Reposition, Round 2+; forced advance when all Front Rout) and an attacker concede_after_round (S10). Resolution stays atomic. Same pattern will extend to the FIX-C battle-array Concede/Reposition items.

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
