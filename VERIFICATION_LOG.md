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
- L2 Call to Arms (3.5) entirely unimplemented; Fealty-less Lords can't enter — FIXED 2026-05-20. Implemented all 3.5.1/3.5.2 options as explicit actions (no greedy defaults): cta_reconcile_rodrigo, cta_employ_rodrigo (Campeador 2 Coin / al-Sayyid 3 Coin), cta_call_crusade (+ Muslim follow-up cta_add_crusade_jihad), cta_invite_almoravids, cta_uphold_dynasties, cta_call_emir (muster|shift). One-option-per-side enforced via Meta.cta_option_used_{side}; Christian-first/Muslim-then via active_player. Enumerator _call_to_arms_moves populated. Tests: tests/test_fix_call_to_arms.py (14). SUB-ITEM L2b (3.5.3 'This Levy' discard) RESOLVED 2026-05-20. The actual 'This Levy' Events (C19 Fitna, C22 Berbers, C23 Illness, C24 Abu Bakr ibn Umar, M16 Galician Revolt, M17 Leon y Castilla) are IMMEDIATE events: their resolver applies the Service shift, records the 'no Muster this Levy' ban in Meta.muster_banned_this_levy_lord_ids (enforced by _h_muster_lord + the muster enumerator), and discards the card at once. The ban — the only lingering 'This Levy' effect — is cleared at the Levy->Campaign transition (_advance_step_if_both_done), i.e. at the end of the Levy (3.5.3). The this_levy_events bucket holds HOLD/combat events that persist by design and are consumed by their own triggers (or discarded after a Battle), so no blanket discard is needed. With L13 these This-Levy events are now reachable via the AoW draw. Tests: tests/test_fix_l2b_this_levy.py (2). Minor pre-existing nuance: immediate cards go to discard rather than 'returned to deck' (deck-recycling simplification).
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
- L13 AoW draw: Capability-deploy (3.1.2) vs Event-implement (3.1.3) not modeled; pending_draw dumped — FIXED 2026-05-20. Drawn cards (pending_draw) are now PROCESSED, not dumped. First Levy (3.1.2): aow_deploy_capability deploys each drawn card as a Capability — side_wide -> board_edge + capabilities_in_play; this_lord -> a chosen Mustered Lord's mat (a card not assignable to a Mustered Lord, or with no Capability half, adds no Capability and is discarded). Second+ Levy (3.1.3): aow_implement_event implements each drawn card's Event in DRAW ORDER (FIFO) via the existing resolve_event registry (all 50 event cards have resolvers that handle payload=None; immediate Events apply, This-Levy/Hold Events are bucketed by their resolver). The enumerator offers deploy/implement when pending_draw is non-empty and BLOCKS pass_step until it is processed; the old Levy->step transition dump of pending_draw is now unreachable. Tests: tests/test_fix_l13_aow_draw.py (5); self-play sweep + enumerator/handler roundtrip green. NOTE: draw count remains agent-chosen (1..3) rather than the rule's fixed 2 — a minor pre-existing simplification; and immediate Events follow each resolver's existing discard vs return-to-deck handling.

### Campaign / March (§4.0-4.3)
- C1 Besiege-or-Bypass mandatory choice after Withdraw (4.3.5); Bypass markers never created — FIXED 2026-05-20. After a Withdraw (_h_respond_withdraw), _set_besiege_or_bypass_pending fires a `besiege_or_bypass` PendingDecision (waiting on the Active/Marching side) whenever that side has Lord(s) outside an Enemy Stronghold that is not already Besieged/Bypassed by it and Enemy Lords have just Withdrawn inside. Two handlers: respond_besiege places one Siege marker of the Active side's color (siege_yellow/green), zeroes actions_remaining (skip to Feed/Pay/Disband); respond_bypass sets the Active side's Bypass flag (bypass_yellow/green) and continues the card. The legal_moves enumerator gates on the pending kind and offers exactly {respond_besiege, respond_bypass}. Tests: tests/test_fix_c1_besiege_bypass.py (4). C1b FIXED 2026-05-20: both Battle handlers (_h_cmd_battle and _h_respond_stand_battle) now call _set_besiege_or_bypass_pending after the aftermath, so a losing Enemy that Withdraws into the Stronghold at the Battle Locale forces the winning Active side to Besiege or Bypass (4.3.5) before Feed/Pay/Disband. Tests: tests/test_fix_c1b_postbattle_besiege.py (2).
- C2 Approach cannot partition defenders (avoid some / withdraw some / fight rest) (4.3.4) — FIXED 2026-05-20. respond_avoid_battle and respond_withdraw accept an optional lord_ids SUBSET of the still-pending defenders (default: all, preserving whole-group behavior). After a subset acts, _resolve_or_repend_approach removes them from the pending payload and either re-pends the remaining defenders' march_arrival_response (they still owe Avoid/Withdraw/Battle) or, when none remain, resolves the Approach (triggers C1 Besiege-or-Bypass if any Enemy Withdrew inside, else restores the Active side). respond_stand_battle then fights whatever defenders remain outside. So a defender can split its Lords across Avoid/Withdraw/Battle. The enumerator keeps offering the whole-group responses (the subset is an explicit player option via lord_ids, avoiding a combinatorial blow-up). Tests: tests/test_fix_c2_partition.py (2).
- C3 Marshal Group March (4.3.1) unimplemented (only Lieutenant Lower-Lord moves) — FIXED 2026-05-20. _h_cmd_march accepts an explicit group_lord_ids: when the active Lord is a Marshal it may lead any/all Unbesieged same-Locale Lords (each validated: same side, same Locale, Unbesieged; non-Marshal leaders rejected with not_marshal). The full moving set is the Marshal + chosen Lords + every Lower Lord stacked under a mover (Lieutenants move their Lower Lord). SHARED TRANSPORT (4.3.2/1.5.2): _group_laden computes Laden from the COMBINED Provender/Loot/Carts/Mules of the whole group, so the group's action cost reflects pooled transport. All movers relocate together and are marked Moved/Fought; the Approach trigger and Battle then see the whole group at the destination. Tests: tests/test_fix_c3_group_march.py (4). SCOPE: like C2, the enumerator offers single-Lord March; the group is an explicit player option via group_lord_ids (avoids enumerating all co-located subsets). Sortie-a-group (4.3.6) and Arid-Terrain-feeds-whole-group remain single-Lord.
- C4 Laden simplified: ignores transport-carrying, mishandles Cart-over-Pass-with-1-Prov as illegal vs legal-laden (4.3.2) — FIXED 2026-05-20. _is_laden(lord, way_type=None) now: Laden if moving any Loot; Laden if Provender exceeds Transport count (a Cart/Mule must carry two); and, with way_type='pass', Laden if a Cart must carry Provender over a Pass (Provender beyond Mule capacity 2/Mule) — so a single Cart with one Provender across a Pass is LEGAL but Laden. _h_cmd_march computes laden=_is_laden(lord, way_type=way_type) and the old cart_over_pass_with_prov REJECTION is removed (it is now a 2-action Laden March; only Carts are hindered on Passes, Mules cross freely). Tests: tests/test_fix_c4_laden.py (5) + updated tests/test_march.py. Provender-capacity (1.7.2) FIXED 2026-05-20: _h_cmd_march now discards Provender the (shared) Transport cannot carry — capacity = 2 x (Carts + Mules) across the moving group; any excess is dropped to the pool when Marching (capacity is way-independent; the Pass affects only Laden, not capacity, for a March). Shared Transport for group March is covered by C3. Tests: tests/test_fix_prov_capacity.py (4).
- C5 Avoid-Battle discard-to-Unladen + Spoils transfer (4.3.4) — FIXED 2026-05-20. _h_respond_avoid_battle no longer rejects Laden defenders; instead each Avoiding Lord discards ALL Loot and Provender beyond what it may take (Provender up to its Transport on a Road; over a Pass only Mules carry Provender, so up to the Mule count), and the discarded Loot+Provender are distributed to the Approaching attacker Lords at the Locale as Spoils (distribute_spoils_round_robin, 4.4.3). The legal_moves enumerator now offers Avoid even for Laden defenders (the handler performs the discard). Tests: tests/test_fix_c5_avoid_discard.py (2) + rewritten test_bugs_pqrst Bug-Q.
- C6 Campaign-start Capability excess discard (4.0) — FIXED 2026-05-20. _apply_capability_discard (called at Campaign entry — both the Levy->Campaign transition and _h_begin_campaign, Christian first then Muslim) discards side-wide board_edge Capability cards in excess of that side's number of Mustered (on-map) Lords; 'This Lord' Capabilities (on mats) are not counted/discarded. Excess goes to the discard pile (deterministic from the list end). Tests: tests/test_fix_c6c8c9_misc.py.
- C7 Plan: no per-Lord card cap 3/4 (1.9.2/4.1.1), no 5-Pass cap, accepts un-Mustered Lords — FIXED 2026-05-20. _h_plan_add_card now enforces: (a) only Mustered (on-map) Lords' Command cards (code not_mustered); (b) per-Lord Command cap of 3 (4 for the side's Marshal) via _is_marshal (code lord_card_cap); (c) the five-Pass-cards-per-side limit (code pass_cap). The legal_moves Plan enumerator mirrors all three so enumerator/handler stay in lockstep (no illegal offers). Rule 5.2 is now also enforced at Campaign entry (both the Levy->Campaign transition in actions._advance_step_if_both_done and _h_begin_campaign): a side with no Mustered Lords loses immediately (it likewise cannot build a legal 7/8-card Plan with <=5 Pass). Test-harness note: the prior plan-padding idiom (1 command + 6-7 Pass) was illegal under the cap; added tests/_plan_helpers.legal_pad (pads <=5 Pass then minimum Command cards) and refactored 14 setup helpers + the inline test_campaign builders to build legal minimal Plans. Tests: tests/test_fix_c7_plan_caps.py (6).
- C8 Lieutenant/Lower-Lord disband-orphan cleanup (4.1.3) — FIXED 2026-05-20. _h_disband_lord now cleans up the partner: if the Disbanding Lord is a Lieutenant, its Lower Lord's lieutenant_of is cleared; if it is a Lower Lord, its Lieutenant reverts to a normal Lord (is_lieutenant=False) when it has no other Lower Lord. Tests: tests/test_fix_c6c8c9_misc.py.
- C9 Lieutenant+Lower-Lord may not Withdraw into Castle (4.1.3 note) — FIXED 2026-05-20. _h_respond_withdraw rejects a Withdraw that would SPLIT a Lieutenant/Lower pair (they always move together, 4.1.3; code lt_pair_split). Since a pair is two Lords, the existing Siege-Capacity check already forbids them entering a Castle (Capacity 1). Tests: tests/test_fix_c6c8c9_misc.py.

### Battle (§4.4)
- B1 4.4.4 Losses rolls entirely missing (per-Routed-unit survival); winner restores ALL routed automatically — FIX (critical).
- B2 Flanking: rounds per-position instead of summing Flanking+opposed then rounding once (4.4.2) — FIXED 2026-05-20. _resolve_step_per_pair reworked into two phases: (1) gather each Front actor Lord's raw half-Hits and route to a target Lord (same position, else Flanking to the largest Front enemy), accumulating per target keyed by target identity so opposed + Flanking strikers COMBINE; (2) round each target's combined half-Hit total UP ONCE (mixed-missile Crossbow priority applied to the combined total via _allocate_rounded_hits), then resolve Protection/Rout. Previously each striking Lord rounded separately (two 0.5-Hit Lords on one target gave 2 Hits instead of 1). Per-Lord Hills/C8/Concede adjustments apply before summing. Tests: tests/test_fix_b2_flanking_rounding.py (3).
- B3 Pursuit marker mechanics / Concede-as-per-Round-action not run inside resolve_battle (4.4.2) — FIX/ADJ.
- B4 _battle_over uses all-units vs all-Lords; per-pair Reserve-only side spins to max_rounds — FIXED 2026-05-20. (a) Termination/winner now expressed as all-LORDS-routed via _side_all_lords_routed: when a side has an array, it is defeated only when NO LordPosition (Front OR Reserve) has unrouted units (Garrison also keeps a Storm Defender alive); pooled sides fall back to has_unrouted. _battle_over and the resolve_battle winner block both use this, so a side reduced to Reserve-only is NOT yet defeated (its Reserve Lords Advance to Front at the next Reposition). (b) Root cause of the spin — 4.4.1 Defender placement: battleside_for_lords gained a front_limit param; the campaign battle call sites (_h_cmd_battle, _h_respond_stand_battle) now build the Attacker first and pass front_limit=_front_lord_count(atk) to the Defender so the Defender places exactly one Lord opposite each Attacking Front Lord and sends all extras to Reserve (previously it always filled up to three Fronts, leaving a permanently-unopposed Front Defender that never took Hits). The Attacker build now also passes active_lord_id so the Active Lord starts at Front center (4.4.1). Tests: tests/test_fix_b4_battle_over.py (6).
- B5 Hit-assignment target selection greedy (4.4.2 ASSIGN HITS = owner choice) — ADJ (architecture).
- B6 Relief Sally array geometry (4.4.1) simplified — FIXED 2026-05-20. The relieving Marchers and the Sallying (Besieged) Lords are no longer merged into one Attacker side. New resolve_relief_sally runs the Battle as two lanes within one engagement: Lane M = Marchers vs Front Defenders (open field, no Walls); Lane S = Sallying Attackers vs up to three Reserve Defenders arrayed as a Front facing them (or the Front Defenders when the besieger has no Reserve, the `shared` case where the Front Defenders Strike only the Marchers to avoid double-counting). The besieging DEFENDER cancels the Sallying Attackers' Hits via Siegeworks-as-Walls (Walls 1..Siege markers) — applied to the Sallyers' Strikes ONLY, not the Marchers'. Sallyers pool their Forces ("Flank all equally closely"). _h_respond_stand_battle branches into this path when relief_sally_ids is non-empty; the standard Approach Battle path is unchanged. Aftermath (apply_relief_sally_aftermath): reuses apply_retreat_aftermath — the Sallying Lords Withdraw back into the Friendly Stronghold at the Locale (general 4.4.3 Withdraw rule) and the Marchers Retreat to the Approach origin — then on Attacker loss reduces the besieger's Siege markers at the Locale to one (4.5.3). Tests: tests/test_fix_b6_relief_sally.py (4). DOCUMENTED SCOPE/RESIDUALS: lanes are pooled (consistent with single-Lord Battle), so multi-Lord lanes take 4.4.4 Losses proportionally rather than per-Lord; round-level AoW reorders (M6 Feigned Retreat) are not applied within a Relief Sally (per-step C1/M1 Hills + C8 still apply); excess Defenders beyond Front + three Reserve-as-Front do not participate.

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
- S11 Storm Array (4.5.2) — FIXED 2026-05-20. resolve_storm tracks per-Lord Front/Reserve: Front begins with <=1 Lord, never exceeds Stronghold Capacity; only Front Lords (+ Garrison for the Defender) Strike/absorb; Reposition (Round 2+, reposition_defender policy) brings one Reserve to Front, with forced advance when all Front Lords Rout. Tests: test_fix_storm_array.py (front_begins_with_one, reposition_adds_reserve, front_never_exceeds_capacity). S11b FIXED 2026-05-20: resolve_storm now gives the ATTACKER a per-Lord Front/Reserve array symmetric to the Defender (a_lord_forces/a_front/a_reserve + _a_front_agg/_push_attacker_losses/_attacker_front_alive/_attacker_alive). The Active Lord begins Front; other besieging Lords start Reserve; Front never exceeds Stronghold Capacity; Reposition (reposition_attacker, Round 2+) brings one Reserve to Front (forced when all Front Rout). Attacker Melee is per-Front-Lord (cap 6 each). _h_cmd_storm gathers ALL besieging Lords at the Locale (Active first) as the Attacker. resolve_storm exposes per-Lord post-Storm forces (result.attacker_lord_forces / defender_lord_forces); _h_cmd_storm commits each besieger and each Defender Lord EXACTLY from those (so multi-Lord Defender survivors on Attacker-loss write back per-Lord, not proportionally). Single-besieger Storms use the BattleSide's own forces (legacy behavior preserved). Tests: tests/test_fix_s11b_multi_besieger.py (3); self-play green. Minor residual: 4.4.4 Storm Losses (Routed-unit removal) still use the aggregate side.routed_units rather than per-Lord piles.

  ARCHITECTURAL NOTE (S8/S10/S11, and FIX-C battle-array items): the combat resolver (resolve_battle/resolve_storm) runs ATOMICALLY — it plays all Rounds in one call with no opportunity for the controlling player to make mid-combat decisions. Several rules require exactly such decisions: Storm Concede (start of each Round after the first, 4.5.2), Reposition (each Round add one Reserve Lord to Front, 4.5.2), and per-Lord Front/Reserve placement. The engine already resolved one such case (Hit-absorption, 4.4.2) by making it a PER-COMBAT POLICY chosen up front rather than a per-Hit interactive choice. S8 (per-Lord 6-Melee cap) additionally needs per-Lord strike computation, which the pooled resolver lacks. RESOLUTION OPTIONS: (A) extend the per-combat-policy pattern — pre-declared Concede-after-Round-N, Reposition order, Front selection — keeping resolution atomic; (B) make combat step-wise interactive (pause for player decisions between Rounds), a larger change to the action/turn model. Pending user direction before implementing S8/S10/S11; BattleSide.conceded already exists but is set by no handler today. DECISION 2026-05-20 (user): use OPTION A — per-combat policies. The Storm resolver will be reworked to track Front vs Reserve Lords per side (Front begins with <=1 Lord — the Active Lord for the Attacker; Front never exceeds Stronghold Capacity), compute strikes PER FRONT LORD with each Lord's Melee capped at 6 (S8), and accept pre-declared policy parameters on cmd_storm: front-order / reposition-order per side (S11 Reposition, Round 2+; forced advance when all Front Rout) and an attacker concede_after_round (S10). Resolution stays atomic. Same pattern will extend to the FIX-C battle-array Concede/Reposition items.

### Taifa / Conquest / Victory (§1.4, 5)
- T1 Sevilla 3x VP weighting (Reconquista 9 / Parias 3) (1.4.2/5.1) — VERIFIED OK 2026-05-20. compute_final_vp already weights Sevilla as 9 (Reconquista) / 3 (Parias) and other Taifas as 3/1; Conquered-marker and Ravaged VP are counted separately per the 5.1 bullets. Confirmed by tests/test_fix_t1t2_vp_conquest.py. Cathedral Seat VP (5.1) + C16 Cathedrals capability FIXED 2026-05-20: new GameState.cathedral_seat_locales (<=2) tracked; compute_final_vp adds +1 Christian VP each. New place_cathedral_seat action — Alfonso (active, with C16) at a Christian-Conquered City with no Cathedral Seat there places one (free/0-action, optional): it acts as a Christian Seat (adds 'alfonso' to seat_marker_lord_ids) AND triggers the +1 Jihad rider (1.4.4, via _add_jihad). Two-marker cap with relocate_from; Scenario-F gate (no Seats until Yusuf/Sir Muster). Removed when the Enemy Conquers the City (_conquer_stronghold) or Alfonso leaves the map (disband). Enumerated in legal_moves. Tests: tests/test_fix_cathedrals.py (5).
- T2 Muslim Conquest Jihad (1.4.4) — VERIFIED OK 2026-05-20. _conquer_stronghold already places Jihad (1 per Stronghold Value) for a Muslim Conquest in ANY Parias OR Reconquista Taifa, removing pre-existing Christian Conquered markers AND Christian Seat markers there, and never co-stacks Conquered+Jihad; Christian Conquest removes all Jihad and places Conquered. Confirmed by tests/test_fix_t1t2_vp_conquest.py.
- T3 adjust_taifa_status Jihad bypasses eligibility + hardcodes value (1.4.4) — FIXED 2026-05-20. The 1.4.3 HOSTAGE POPULACE forced Conquests in adjust_taifa_status now route through _conquer_stronghold (both the Muslim forced-Jihad and the Christian forced-Conquest), so marker counts come from the Stronghold Value, 1.4.4 eligibility is honoured (Christian Conquered + Christian Seat markers are removed before Jihad is placed; Jihad removed before Conquered), and Victory is adjusted. Result reporting (jihad_added/auto_conquered tuples) preserved. Tests: tests/test_fix_t3t5_taifa.py.
- T4 adjust_taifa_status OR-choices auto-resolved (1.4.3 player choice) — FIXED 2026-05-20. adjust_taifa_status gained a neutrality_choices param (locale_id -> 'remove'|'add'). For the RECOGNITION OF NEUTRALITY OR-clauses (a side Besieging a now-Neutral Enemy Stronghold): 'remove' lifts that side's Siege/Bypass (the conservative default when unspecified); 'add' instead places Enemy victory markers = Stronghold Value and KEEPS the Siege (Muslim besieger -> Christian Conquered; Christian besieger -> Jihad), per 1.4.3. The greedy hardcode is gone; the choice is caller-supplied. Tests: tests/test_fix_t4_neutrality_choice.py. RESIDUAL: full interactive enumeration of this choice in legal_moves (a pending-decision pause) is not wired; callers pass the choice (default 'remove').
- T5 Parias Coin transfer not applied in non-Disband paths (1.4.3) — FIXED 2026-05-20. adjust_taifa_status now awards Parias Coin (6 if Sevilla/al-Mutamid, else 4) on EVERY Independent->Parias transition (Muster, combat removal, recompute), via _award_parias_coin with a deterministic distribution. The Disband path passes award_parias_coin=False and keeps its own player-chosen distribution (L7) to avoid double-paying. Tests: tests/test_fix_t3t5_taifa.py.
- T6 Curias deducts Christian score vs removing Taifas-box Conquered marker (5.1 note) — FIXED 2026-05-20. apply_curias now reduces the Muslims' Taifas-box VP (state.taifas_box_vp) by one per Curias marker placed (6.2.2), instead of deducting from the Christian running score. Tests: test_fix_e1e2e3_endcampaign.py::test_t6_curias_reduces_taifas_box_not_christian_score.
- T7 Conquered-marker side inferred by territory (1.3.1) — VERIFIED OK 2026-05-20 (no model change needed). The territory inference (Conquered on Taifa territory = Christian; on a Kingdom = Muslim) is provably correct for all REACHABLE states: Muslim Conquest in a Taifa places Jihad not Conquered (1.4.4), so a Muslim Conquered marker never sits on Taifa territory; Conquest in Friendly territory only REMOVES enemy markers (1.3.1), so a Christian Conquered marker never lands on a Kingdom; and the Taifas box only ever receives Muslim 1VP markers in this engine (all three taifas_box_vp increments are Muslim gains). A full side-tracking refactor would touch ~15 sites + the schema for zero behavioural change, so it is intentionally not done.

### End-Season / Feed (§4.8-4.9)
- E1 Grow (Spring-2 Ravage halving) (4.9.2) — FIXED 2026-05-20. _apply_grow_harvest_repairs (called from _h_end_campaign when the game continues) reduces ENEMY Ravage markers to half rounded up at the end of the SECOND Spring box: Christian removes floor(n/2) green (Muslim) Ravaged markers, Muslim removes floor(n/2) yellow. Which markers are removed is a minor player choice with no VP-total effect; deterministic selection used. Tests: test_fix_e1e2e3_endcampaign.py.
- E2 Harvest (Summer-2 Cart/Mule halving) (4.9.2) — FIXED 2026-05-20. At the end of the SECOND Summer box each on-map Lord reduces Carts and Mules EACH to half rounded up. Tests: test_fix_e1e2e3_endcampaign.py.
- E3 Repairs (remove 1 Siege from 3-4 stacks, non-Winter) (4.9.3) — FIXED 2026-05-20. At the end of each non-Winter Campaign, every Siege Locale with three or four Siege markers (per besieger color: siege_yellow/siege_green) loses one. Skipped in Winter. Tests: test_fix_e1e2e3_endcampaign.py.
- E4 Feed: only active Lord, not both sides' Moved/Fought (4.8.1) — FIXED 2026-05-20. _h_end_card now calls _feed_all_moved_fought, which Feeds EVERY Lord marked Moved/Fought on both sides (Christians then Muslims) — a Battle/Storm or Group March marks several — and then clears all Moved/Fought markers (4.8.3). Tests: test_fix_e4e5e6_feed.py::test_e4_feeds_all_moved_fought_lords_both_sides.
- E5 Feed Sharing among same-Locale Lords (4.8.1) — FIXED 2026-05-20. After each Lord Feeds his own Forces+Mules, same-side Lords in the SAME Locale must expend their remaining Provender then Loot to Feed allies that came up short (mandatory, no withholding); the Unfed Service-shift is applied only to Lords still short AFTER Sharing. Tests: test_fix_e4e5e6_feed.py (sharing + unfed-when-no-ally).
- E6 Feed Greed mule-discard option (4.8.1) — FIXED 2026-05-20. _feed_consume_own/_feed_lord/_feed_all_moved_fought accept discard_excess_mules (rule 'may discard Mules in excess of those they can Feed'): when set, the Lord discards Mules beyond what his own Provender+Loot can Feed, keeping the maximum that capacity allows. Per the no-greedy-defaults rule this is an EXPLICIT option, NOT auto-exercised — the default end-card Feed keeps Mules and accepts any Unfed penalty (a valid 'keep the Mule' choice). Tests: test_fix_e4e5e6_feed.py::test_e6_greed_discards_excess_mules_to_avoid_unfed.
- E7 Asset Sharing 1.5.2 (March/Pay/Avoid) — PARTIAL/VERIFIED 2026-05-20. PAY Sharing is already supported and tested: _h_pay_lord lets a Lord spend his own Coin/Loot to shift a DIFFERENT same-Locale same-side Lord's Service marker, with a same-Locale gate and no transfer of markers (1.5.2) — tests/test_fix_pay_321.py::test_coin_can_target_another_lord_same_locale + test_coin_other_lord_must_be_same_locale. MARCH Shared Transport is handled by C3 Group March (_group_laden over the combined group). AVOID Shared Transport is now also handled: _h_respond_avoid_battle computes Provender capacity over the GROUP's combined Carts+Mules (Road) / Mules (Pass) so avoiding Lords pool transport (E7/1.5.2; tests/test_fix_c5_avoid_discard.py::test_avoid_shared_transport_group_capacity). The earlier note that Shared Transport had 'nothing to act on until Group March' — a single Lord has no group to Share with, so current single-Lord Laden uses that Lord's own Assets, which is correct for the modeled cases. Tracked as dependent on C3; NOT a silent simplification.

### Verified OK
- Forces/Strongholds data; ratings (lords.json vs Lords.txt); player order; Service-marker model; Campaign Victory 5.2; tie=draw 5.3; Greed has NO wrong 8-cap; Supply route/transport/Forage/Tax correct; Wastage 4.9.4 correct; effective.is_friendly_locale matches 1.3.1.


## Accepted limitations (re-assessed 2026-05-20)
Three former "accepted limitations" were re-examined and FIXED (they did not need accepting): the 3.1.1 deck reshuffle/immediate-Event recycling; Storm 4.4.4 per-Lord routed Losses; and the mandatory fixed-2 AoW draw (the Capability/Event subsystem was dormant in play). The remainder below are fixable but low-frequency edges with rules-legal conservative behavior:
- T4 RECOGNITION-OF-NEUTRALITY OR-choice FIXED 2026-05-20: now an interactive pending decision. adjust_taifa_status DEFERS the OR-clause (collects deferred_neutrality, applies nothing) when no explicit neutrality_choices param is given, and only at a stronghold that is genuinely Neutral after the transition (no Conquered/Jihad markers). _maybe_set_neutrality_pending (called from the Disband caller) sets a `neutrality_choice` PendingDecision for the besieging side (Christian then Muslim), saving the resume active player; legal_moves short-circuits to offer remove/add; _h_respond_neutrality_choice applies the side's choices (remove Siege/Bypass, or add Christian Conquered/Jihad = Value), then resolves the next side or restores the turn. Also fixed a pre-existing over-broad HOSTAGE POPULACE bug: a Muslim Lord no longer force-Conquers on Reconquista->Parias (the stronghold was Enemy, not Friendly, to him — that case is RECOGNITION OF NEUTRALITY). Tests: tests/test_fix_t4_pending.py (3) + updated mirror-gap/neutrality tests.
- Relief Sally (B6) per-Lord lane Losses FIXED 2026-05-20: resolve_relief_sally tracks per-Lord Forces + Routed units in each lane (via _init_lane/_push_lane/_lane_step, mirroring the Storm) and writes each Lord's post-battle state EXACTLY, so a multi-Lord lane no longer distributes Losses proportionally; _h_respond_stand_battle drops the proportional commit. Tests: tests/test_fix_relief_sally_perlord.py (2). M6 Feigned Retreat round-2 melee reorder is now applied within a Relief Sally (both lanes; discarded after Round 2), and excess Reserve Defenders now ADVANCE via Reposition (Round 2+): _advance_reserve brings them into emptied Front (Marcher lane) then Reserve-as-Front (Sallyer lane) slots up to capacity, so they are engaged instead of sidelined. Tests: tests/test_fix_relief_sally_rare.py (2).
- Storm 4.4.4 Losses are now per-Lord: resolve_storm tracks routed units per besieging/defending Lord (attacker_lord_routed/defender_lord_routed) and _h_cmd_storm commits each Lord's routed pile so apply_battle_losses(storm=True) rolls 4.4.4 per-Lord (storm attacker keeps each on a 1; survivors return to that Lord's Forces). This also FIXED a regression where S11b's per-Lord force commit had dropped the routed_units write, skipping storm 4.4.4 entirely. Tests: tests/test_fix_storm_losses_perlord.py.
- AoW draw is now MANDATORY and fixed at two (3.1.2/3.1.3) — NOT accepted/deferred. Previously drawing was optional and self-play skipped it entirely, leaving the whole Capability/Event subsystem dormant. Now Meta.aow_draw_done (reset each Levy) gates the Arts-of-War step: a side must draw exactly two cards (aow_draw draws min(2,deck), auto-rebuilding the deck via 3.1.1 if empty; drawing twice is rejected) and deploy/implement them (L13) before pass_step is legal (enforced in both the enumerator and _h_pass_step). Self-play now actively acquires Capabilities/Events. Immediate Events recycle to the deck via the 3.1.1 rebuild. Tests: tests/test_fix_aow_mandatory_draw.py + updated legal_moves/actions/campaign/cli helpers (shared tests/_plan_helpers.step_levy).


## Fresh exhaustive clause-by-clause audit (2026-05-20) — fixes
A second full read of the rulebook (5 independent read-only audit passes) surfaced
a punch list of residual base-game gaps. Fixes by group:

### Conquest / Ravage VP (1.3.1, 4.5, 4.9.2)
- Conquest now flips a Ravage marker (1.3.1 / 4.5 summary "Conquest flips Ravage to
  Enemy color" / 4.5.1 Surrender "Ravaged Land" bullet). Reading adopted: the marker
  ends up the NON-conquering (Enemy) side's color — i.e. only the conqueror's OWN-color
  marker flips (to Enemy); a marker already in the Enemy's color is unchanged. This is
  the reading that reconciles all three citations (the 4.5.1 bullet conditions the flip
  on "if the Conquering side has a Ravaged marker there"). Implemented in
  _conquer_stronghold; the ½VP moves between sides in the running tally. NOTE: the
  prior implementation had no flip at all. Tests: tests/test_ravage_flip_and_grow_vp.py,
  updated tests/test_surrender_conquest.py.
- Running-score sync for Ravage ½VP: state.score.{christian,muslim} is an incremental
  display tally (the Victory verdict uses count-based compute_final_vp, which was always
  correct). The tally was being credited at Ravage placement (4.7.2) but NOT debited at
  Grow removal (4.9.2 "adjust VP") nor moved at the adjust_taifa_status Allegiance flip
  (1.4.3). Both now keep the tally honest. Tests: tests/test_ravage_flip_and_grow_vp.py.

### Siege / Battle / March (4.5.1, 4.3.4, 4.3.6)
- 4.5.1 MOVED/FOUGHT: the Siege command now marks ALL Lords of both sides at the
  Locale as Fought ("Finally, mark all Lords of both sides there as Fought"; SoP
  siege.moved_fought_marks). Previously a Siege left no Moved/Fought marker, so Lords
  escaped the end-of-card Feed (4.8.1). Tests: tests/test_moved_fought_siege_avoid.py.
- 4.3.4 Avoid Battle now marks avoiding Lords Moved/Fought ("Mark Avoiding Lords as
  Moved/Fought"; 4.8.1 lists Avoid Battle). The prior code explicitly did NOT mark them
  (citing the withdraw definition) — but only Withdrawal alone is exempt (4.3.4 WITHDRAW).
  Tests: tests/test_moved_fought_siege_avoid.py.
- 4.3.4 Avoiding into an Unbesieged Enemy Stronghold's Locale now marks that side
  Bypassing it ("Mark Lords Avoiding Battle to an Unbesieged Enemy Stronghold as
  Bypassing it (4.3.5)") — a per-Locale Bypass marker of the avoider's color. Tests:
  tests/test_moved_fought_siege_avoid.py.
- 4.3.6 SORTIE implemented (new cmd_sortie): a Lord (or Marshal/Lieutenant-led group,
  4.3.1) inside a Bypassed Friendly Stronghold uses 1 March action (ignore Laden) to
  Approach the Bypassing Enemy in the same Locale. Builds the march_arrival_response
  pending directly (Sortie is the one Approach that targets a *Bypassed* Enemy, which
  4.3.4's normal trigger skips); the Enemy may Avoid/Withdraw/Stand; loss → normal
  Withdraw/Retreat aftermath. Enumerated in legal_moves (Encamp was also un-enumerated
  and is now offered too). Tests: tests/test_sortie_436.py.
- 4.3.5/4.3.6 DEPART: marching the last besieging/bypassing Lord out of a Stronghold's
  Locale now removes that side's Siege/Bypass markers there (new
  _remove_orphaned_siege_bypass; "becomes free of Enemy Lords ... remove markers").
  Tests: tests/test_depart_marker_cleanup.py.

### Winter sequence (6.3.1, 6.3.4, 6.3.5) — Scenario F
- 6.3.1 Winter Disband now (a) deposits Disbanding Taifa Lords' mat Coin into the Taifas
  box (state.taifas_box_coin) without adjusting Taifa status or awarding Parias Coin, and
  (b) handles Beyond-Service (3.3.1) FIRST: a Lord whose Service marker is left of
  (lower box than) the marker box is permanently removed (Forces/Assets to pools, This-Lord
  Capabilities to the deck, cylinder->removed, Seat markers stripped) — EXCEPTION Rodrigo,
  who goes to Calendar box 9. Remaining Mustered non-Siege Lords Disband to their mats
  (the 6.3.1 modification of 3.3.2) to auto-Muster at Spring Muster. Previously every
  non-Siege Lord went to the mat (Beyond-Service Lords wrongly survived to re-Muster) and
  Taifa Coin was silently dropped. Tests: tests/test_winter_sequence_63.py.
- 6.3.4 Plowing implemented (winter_plowing): at the end of box 8 each Lord at a Siege
  reduces Carts and Mules each to half (rounded up), mirroring Harvest but Siege-only.
  Wired before Spring Muster at the box-9 transition. Tests: tests/test_winter_sequence_63.py.
- 6.3.5 Arts of War box 9: the first Spring Levy after Winter (Calendar box 9, Scenario F)
  now draws/deploys Capabilities instead of Events. New aow_capability_phase(state) helper
  (first Levy OR Scenario-F box 9) replaces the bare first_levy_done gate in both the
  handlers (aow_deploy_capability / aow_implement_event) and the legal_moves enumerator.
  Tests: tests/test_winter_sequence_63.py + updated test_fix_l13_aow_draw.py error code.
- 6.3.2 Winter Siege — IMPLEMENTED 2026-05-21 (interactive, Scenario F). On entering box 7
  (after Winter Disband) the engine starts an interactive Winter sequence that OWNS the
  flow through boxes 7->8 and ends by entering the box-9 Spring Levy — the ordinary
  Levy/Campaign cycle no longer runs at winter boxes. Per box: (1) walk the Besieging
  Lords (a Lord outside a Stronghold where his side has a Siege marker), offering each ONE
  Supply or Ravage action, or pass (Forage is NOT offered) — winter_siege_action, driven
  via a saved/restored turn-context (_MetaCtx) that reuses the tested cmd_supply/cmd_ravage
  handlers; (2) auto-Feed EVERY Lord at a Siege Locale (both sides, incl. Besieged
  garrisons inside) via _winter_feed -> _feed_all_moved_fought (Sharing + Unfed shift);
  (3) Christian then Muslim Pay Lords at Sieges (winter_siege_pay, reuses _h_pay_lord),
  each side ending with done; (4) auto-Disband Lords at Sieges at/beyond Service limit per
  3.3 (_winter_siege_disband reuses _h_disband_lord). After box 8: Plowing (6.3.4) + Spring
  Muster (6.3.3), then box-9 Spring Levy (Capabilities, 6.3.5). The load-bearing ordering
  is honoured (Supply feeds the Provender that Feed consumes; Pay can advance Service to
  dodge the mandatory Disband) — both proven by tests. A winter box with no Siege Locales
  resolves fully automatically (no pointless pauses). Pending kind "winter_siege" with a
  legal_moves short-circuit; handlers registered in CAMPAIGN_HANDLERS. Tests:
  tests/test_winter_siege_632.py (8: no-siege fast path, besieger->Feed->Pay->box8->box9,
  Ravage marker, at-limit Disband, Pay-dodges-Disband, legal_moves, end_campaign wiring).

### Levy Muster / Capabilities (3.4.4, 3.4.1)
- 3.4.4 This-Lord Capability limits now enforced: a Lord may hold at most TWO This-Lord
  Capabilities and may not hold two with the same title (capability_name). New
  _check_this_lord_cap_limits gates both the Muster Levy path (levy_take_capability) and
  the 3.1.2 deploy path (aow_deploy_capability — over-limit/duplicate cards are discarded
  rather than assigned). legal_moves mirrors the gate so no phantom over-limit moves are
  surfaced. Tests: tests/test_levy_capability_limits_34.py. Implemented as a hard gate on
  ADDING (not a forced discard-down-to-two), since the discard-and-swap variant would need
  a separate player-choice action and there is no net gain in offering an immediately-
  discarded card.
- 3.4.1 free-Seat check (Errata p.12): _free_seats_for now excludes Seats that are Enemy
  Territory (Friendly to the other side per 1.3.1) in addition to the existing "no Enemy
  Lord present" check. A Neutral Seat (e.g. a Parias Taifa) is NOT Enemy and remains free.
  Tests: tests/test_levy_capability_limits_34.py.
- 3.4.4 Capability SOURCE pool — RESOLVED & FIXED 2026-05-21 (second-opinion confirmed).
  Levy Capabilities now select from ANY of the side's currently UNUSED Arts of War cards
  (the deck is a face-up "menu"), not just decks.board_edge. "Unused" follows the 3.1.1
  rebuild semantics: every card of the side EXCEPT deployed Capabilities (board edge +
  tucked under Lord mats), Held Events, and cards pending implementation this Levy; cards
  in the undrawn deck and in discard both count as unused (no permanent card-removal
  mechanic is active — C18 here is Runaway Slaves, not Milites). New helper
  _unused_capability_cards(state, side); board_edge is the DESTINATION for a Levied
  side_wide cap, not a separate source stock. The "Levying blocks the Event" note (3.4.4)
  is honoured because the card leaves the unused pool once in play. Handler
  _h_levy_take_capability + legal_moves enumerator both use the helper. Tests:
  tests/test_levy_capability_limits_34.py (full-deck source, board-edge-not-reselectable),
  updated tests/test_real_levy.py.

### Residual partials (4.7.2, 1.6, both-Concede)
- 4.7.2 Enforcing Parias Service-shift now gated on "if the Lord is Mustered": the odd-
  Christian-Ravage-marker Service shift only fires for a Taifa Lord whose cylinder is at a
  Locale (on the map). Previously it shifted a Disbanded/Calendar Lord's marker too. Tests:
  tests/test_enforcing_parias_mustered_472.py.
- 1.6 / 3.3 NOTE standalone no-Forces Disband — VERIFIED already handled where reachable.
  The only force-removal paths in this engine are combat (apply_battle_losses already
  permanently removes any Lord left with zero Forces, 3.3.1, at the end of the Losses pass)
  and the Advanced Vassal Service rule (3.4.2), which is not active in this harness. No
  Event reduces a Lord's Forces (they only add), and the Unfed penalty (4.8.1) is a Service
  shift, not a Force removal. So the "last unit removed outside of combat" trigger has no
  reachable non-combat path; no dead-code hook was added.
- Both-sides-Concede winner — ADJUDICATED as winner=None (current behavior is correct). Per
  4.4.2 each Conceding side "declare[s] that the Battle will end ... with that side as the
  loser"; if BOTH the Attacker and Defender Concede the same Round, both are losers and
  there is no victor (no Conquest/field-holder), which the resolver already yields. Both
  sides take the lenient ("conceded_then_retreated") Loss roll. RESIDUAL (rare): the
  winner=None aftermath shares the path with a max-Rounds stalemate and does not force BOTH
  sides to Retreat off the field; a full both-sides-retreat geometry for the dual-Concede
  case is a deferred low-frequency edge (a rational Defender never Concedes when winning).

## Optional / advanced rules (opt-in) — 2026-05-21
The rulebook's own optional/advanced layer, implemented as opt-in toggles so the standard
game is unaffected when they are off (all default off).

- 6.1 Bidding for Sides — IMPLEMENTED (opt-in setup action `bid_for_sides`). Two players
  bid; the LOWER bid takes Muslim and the Taifas-box 1VP count (state.taifas_box_vp) is
  reset to that bid; ties reset to that number and assign sides randomly (seeded). Scenario
  F minimum bid is 2 (enforced). The engine's two sides/pieces are fixed, so the only
  mechanical state effect is taifas_box_vp; the seat assignment is reported. One-time
  (meta.bidding_done). Intentionally NOT enumerated in the default legal-move stream (it is
  a pre-game agreement; auto-drivers shouldn't bid / perturb RNG) but is fully callable at
  setup. Tests: tests/test_bidding_61.py.
- 1.5.2 Hidden Mats — IMPLEMENTED (opt-in, meta.hidden_mats). New views.redacted_view(state,
  viewer_side) returns a per-viewer dict: with the option on, the opponent's on-map Lords'
  strength (Forces, Assets, Vassals, This-Lord Capabilities, Routed units) is hidden
  (replaced with None, `hidden_mat: True`), EXCEPT Lords in Battle/Storm (a pending
  march_arrival_response at their Locale reveals them); the opponent's pending AoW draw is
  also hidden. Identity, ratings, and map position stay public; side-wide Capabilities stay
  revealed (3.4.4). Purely a view — rules/legal-moves/resolution use full state. Tests:
  tests/test_hidden_mats_152.py.
- 3.4.2 Advanced Vassal Service — IMPLEMENTED (opt-in, meta.advanced_vassal_service).
  Mustered Vassals get their own Calendar Service marker placed right of the Levy marker by
  the Vassal's Service Rating (data `service_cost`); a Lord's Service shift (any direction/
  reason) cascades to his Vassal markers (both _shift_service_left and _shift_service_right).
  At each Disband step (Levy 3.3 via pass_step on service_disband; Campaign 4.8.2 via
  _h_end_card) `_disband_vassals_for_side` disbands Mustered Vassals at/beyond Service limit:
  beyond -> permanently removed (Forces returned, no re-Muster); at-limit -> Pennant-DOWN
  (Unready, Forces returned). If returning Forces leaves a Lord with none, he Disbands to
  the Calendar (1.6, 3.3.2, via _h_disband_lord with a bypass_limit_check). After a side's
  Muster segment, `_flip_up_pennants` flips Pennant-down Vassals back to Ready. Pennant-down
  Vassals may not Muster. New Vassal.pennant_down field (schema regenerated). Bishops/
  Crusaders (Capability-added) are not Calendar-vassals and are unaffected. Tests:
  tests/test_advanced_vassal_service_342.py + updated tests/test_phase7d_vassal_service.py.

## Deep invariant sweep (2026-05-21) — 3 bugs found & fixed
A 260-session deep test (greedy + random drivers, optional rules on/off, asserting state
invariants after EVERY action) surfaced three issues, now fixed:
- Scenario D data bug: jativa held both Conquered(1) AND Jihad(2) at setup (1.3.1: a Locale
  never holds both). The Scenario Reference (Scenario D) lists "one yellow Conquered ... at
  Játiva" and "two Jihad at Uclés"; the 2 Jihad were mis-placed onto jativa. Removed the
  stray jihad_markers from jativa in scenario_d_arrival.json (Uclés already correct).
- M15 Parias Revolt stacked Jihad on a Christian-Conquered Locale (1.4.4 eligibility
  violated -> both-markers state). Fixed to use _jihad_eligible_locales (no Conquered/Seat),
  mirroring M20. Tests: tests/test_m15_jihad_eligibility.py.
- C3/M3 Swollen River: legal_moves offered a cmd_march the handler then rejected with
  IllegalAction (Pattern 9 / harness-contract violation). Reading: declaring a March IS
  legal; the enemy's reactive Hold event INTERRUPTS it. cmd_march now returns a legal
  "blocked" outcome (no move, flag set, event discarded) instead of raising, and legal_moves
  suppresses further marches for an already-blocked Lord. Tests: updated test_phase6h_tier_a.py.
- New permanent gate tests/test_deep_invariants.py: greedy+random self-play across all
  scenarios x seeds 1-3, plus optional-rules-on runs, asserting invariants every step
  (no negative counters, siege<=4, never both Conquered+Jihad, service box 0..17, pending/
  active sync, legal_moves->apply_action total). After fixes the full 260-session deep run
  reports NO PROBLEMS.

## Independent LLM playtest — Scenario A (2026-05-22), 8 findings fixed
A separate Cowork chat played a full Scenario A game with the rulebook open and filed 8
findings (F1-F8). All verified against the rules and fixed (one was a misread):
- F8 (CRITICAL, fixed): Taifas-box green 1VP Conquered markers were never loaded into
  state.taifas_box_vp, so compute_final_vp dropped them (4 Muslim VP in Scenario A) and
  reported the WRONG WINNER. scenarios.py now seeds taifas_box_vp from the JSON. Tests:
  test_taifas_box_vp_loaded_f8.py.
- F4 (systemic, fixed): printed home-Seat pennants were loaded into seat_marker_lord_ids
  and conferred Friendliness via is_friendly_locale. Per 1.3.1 only PLACED Seat markers
  (Rodrigo/Yusuf-Sir/Cathedrals) confer Friendliness; printed Seats do not. Split into a
  new Locale.printed_seat_lord_ids; seat_marker_lord_ids now holds only placed markers
  (Yusuf/Sir double-Seat placed at Algeciras only when mustered; set-aside Lords get none).
  Fixed wrongly-Muslim-Friendly Parias capitals (Lerida/Badajoz/Granada). Tests:
  test_printed_seats_vs_markers_f4.py.
- F5 (fixed): M11 Al-Qadir is a HOLD event — now held on draw (not auto-fired), played via
  a discretionary play_al_qadir handler (base +1 Jihad; +3 if Yusuf/Sir is in a
  Reconquista/Parias Taifa or a Kingdom); re-tagged M11/M13 event_persistence=hold. The
  card's "Lords. Yusuf or Sir" line restricts the EVENT (an independent audit found the
  Capability "Hasham" is "Any Muslim", so that line is NOT the Capability's), so M11 may be
  played only with Yusuf or Sir on the map — which is exactly the playtest's concern (it
  could not legitimately fire in Scenario A, where both are set aside). Adopted the
  conservative reading (don't fabricate Jihad VP when neither Almoravid leader is in play);
  flagged as a Q-candidate. Tests: test_m11_hold_f5.py.
- F1/F2 (fixed, data): C14 & C17 now carry the Cabalgadas this_lord capability (were
  no_capability); C8 Hueste and M9 Emir al-Muslimin re-scoped side_wide -> this_lord.
  (Their special EFFECTS remain unwired — a separate known capability-effects gap.) Tests:
  test_capability_data_f1f2.py.
- F7 (fixed): orphaned Siege/Bypass markers are now removed when the sole besieging Lord
  leaves via Disband (to Calendar / permanent removal), not just via March (4.3.5). Tests:
  test_siege_cleanup_on_disband_f7.py.
- F3 (fixed, cosmetic): the Enforcing-Parias log no longer says "(Service shift TODO)" —
  the shift is and was applied.
- F6 (fixed, display): render now shows the AUTHORITATIVE board VP (compute_final_vp), not
  the lagging running state.score tracker, so mid-game VP is accurate.

## Combat-focused playtest (2026-05-22) — findings P-N
A live drive of Scenario A through the real legal_moves -> apply_action
pipeline, steering toward joined combat (Toledo is besieged by Álvar Fáñez
at setup). Findings prefixed P- to distinguish from the earlier F- playtest.

- P-1 (CRITICAL, fixed): each side must draw Arts of War cards from ITS OWN
  deck (1.9.1 "Each side has its own deck of Arts of War cards"; 3.1.1
  "shuffle all unused Christian ... do the same for the Muslim player";
  3.1.2/3.1.3 "draws two ... from the player's own deck"; SoP v2 arts_of_war
  step = shuffle THEN draw 2, per actor). BUG: state.decks.draw is a single
  shared pile and _h_aow_draw only collected+shuffled it when EMPTY. So in
  the first Levy the Christian player drew first (leaving ~20 Christian cards
  on the shared pile) and then the Muslim player's aow_draw pulled those
  leftover CHRISTIAN cards (observed: Muslim drew C5/C8). The deploy handler
  has no side check, so the Muslim side then deployed Christian Capabilities.
  Not caught earlier because the shared test helper (_plan_helpers.step_levy)
  only shuffles when the pile is empty (reproducing the bug) and no test
  asserted the side of drawn cards; the deep-invariant sweep checks no
  card-side invariant. FIX: _h_aow_draw now rebuilds (collects this side's
  unused cards via _rebuild_aow_deck) and shuffles before EVERY draw, not
  only when empty -- matching the per-Levy shuffle-then-draw of 3.1.1/SoP.
  No test hard-codes a real draw outcome, so no existing assertion changed.
  Tests: tests/test_fix_aow_per_side_deck_p1.py (2). Full suite green.

- P-2 (fixed): orphaned Siege/Bypass markers when the SOLE besieging Lord is
  eliminated in COMBAT. Rule 4.5.4 (Siege): "Whenever a Besieged or Bypassed
  Stronghold becomes free of Enemy Lords in the Locale, remove all Siege or
  Bypass markers there." Observed in the playtest: Álvar Fáñez (the only
  Christian Lord besieging Toledo) Stormed the City (walls 1-4, 6-unit
  garrison), lost, and was reduced to zero Forces -> permanently removed
  (3.3.1) inside apply_battle_losses. Toledo kept siege_yellow=1 with no
  besieging Lord present. The F7 fix cleared orphaned markers on the Disband
  and March departure paths but NOT on combat elimination. FIX: apply_battle_losses
  (the single chokepoint for Storm/Sally/Battle/relief Losses) now records the
  Locale of every Lord it permanently removes and calls
  campaign._remove_orphaned_siege_bypass on each afterward; that helper is
  per-side, so the surviving side's markers are untouched. Tests:
  tests/test_fix_siege_cleanup_combat_p2.py (2: live Scenario-A Storm + unit).

- Live combat coverage exercised (the gap the F- playtest left open):
  * BATTLE (open field) — VERIFIED OK. Drove Scenario A to a real March ->
    Approach (4.3.4) -> Stand -> Battle at Huesca (al-Mustain attacker vs
    Sancho defender, 2 rounds). 4.4.4 Losses verified against the rulebook:
    BOTH sides roll for Routed units; a Lord who Retreated without Conceding
    keeps each unit only on a "1"; all OTHER Lords (incl. the WINNER) keep
    each unit only within its unmodified Protection range ([1,N] in
    forces.json: Knights 1-4, Sergeants/MaA 1-3, AfricanFoot 1-2, Unarmored
    1, African-Horse Evade 1-2; Serfs auto-remove). So the winning al-Mustain
    correctly LOST his Routed Light Horse + Militia (Unarmored, survive only
    on a 1). apply_losses_rolls + _losses_keep_threshold match the rule.
  * SALLY (4.5.3) — VERIFIED OK. Drove a Besieged al-Mustain to cmd_sally vs
    besieger Sancho; the besieger defends with Siegeworks-as-Walls (S9), so
    al-Mustain (4 units) lost to Sancho (3 units) and on attacker loss the
    Siege markers reduced to one (2 -> 1, 4.5.3). The P-2 cleanup correctly
    did NOT clear the besieger's marker (the besieging side still has a Lord
    present), confirming P-2 is per-side.
  * STORM (4.5.2) — exercised (see P-2): attacker repelled by City walls 1-4
    + garrison strikes, eliminated, orphaned marker bug found and fixed.

## Cross-project "Retreat penalizes but never relocates" advisory (2026-05-22)
A sibling L&C engine (Inferno) reported a class where post-combat Retreat
applied the Service penalty but never moved the loser, leaving opposing
field Lords illegally co-located; it hid because Concede (the surviving-
loser branch) is cold under auto-play AND no invariant forbade co-location.
Audited Almoravid for the same shape.
- Battle Retreat — VERIFIED OK: apply_retreat_aftermath RELOCATES the loser
  (cylinder -> a legal adjacent Locale) and enforces destination rules
  (marching attacker -> approach origin; defender not back along the
  attacker's Way; _retreat_target_clear excludes Enemy Lords/Strongholds).
- P-3 (fixed): the SALLY besieger-loss path had the exact bug. 4.5.3:
  "Losing Defenders Retreat normally, ending the Siege." apply_sally_aftermath
  built a "retreat" fate but never called apply_retreat_aftermath, and
  apply_retreat_aftermath early-returned for ALL engagement=='sally'. So a
  surviving losing besieger stayed at the Locale (co-located with the winning
  Besieged Lord) and the Siege never ended. FIX: apply_retreat_aftermath now
  early-returns only when the loser is the SALLYING attacker (who Withdraws
  back inside); a losing besieging DEFENDER falls through and Retreats
  (relocates) via the standard branch. apply_sally_aftermath now mirrors the
  standard Battle order (relocate -> Losses -> Aftermath) for the besieger-
  loss case and calls _remove_orphaned_siege_bypass to END the Siege. Relief
  Sally is unaffected (engagement=='battle'). Tests:
  tests/test_fix_retreat_relocation_p3p4p5.py.
- Co-location INVARIANT added (advisory item #3) to the permanent gate
  tests/test_deep_invariants.py: no two opposing FIELD Lords (both
  in_stronghold=False) may share a Locale once nothing is pending (an
  Approach co-locates transiently until the defender responds). This single
  cheap invariant immediately surfaced TWO latent bugs the 100-seed sweep had
  laundered as "passing":
- P-4 (fixed, data): scenario_d_arrival.json started al-Mustain as a FIELD
  Lord at Zaragoza with NO Siege marker, co-located with the besieging
  Alfonso/Sancho. Scenario Reference: "Alfonso, Sancho, and one yellow Siege
  on al-Mustain at Zaragoza City." FIX: al-Mustain in_stronghold=true
  (Besieged inside), zaragoza siege_yellow=1; taught scenarios.py to read an
  in_stronghold flag from mustered_lords (defaults false).
- P-5 (fixed): CtA auto-Muster placed a Lord at a Friendly Stronghold without
  checking it was free of Enemy Lords, so Employing Rodrigo (3.5.1) Mustered
  him into an Enemy-occupied Locale -> co-located. Rule 3.4.1 PROCEDURE:
  "Place that Lord's cylinder at one of his Seats that is neither Enemy nor
  has any Enemy Lords present"; 3.4.1 ARTS OF WAR: CtA Musters "must otherwise
  still Muster by the usual rules." FIX: new _cta_seat_has_enemy_lord guard at
  the _cta_auto_muster chokepoint (covers Employ Rodrigo, Call for Crusade,
  Invite Almoravids, Call upon an Emir, Uphold Dynasties); enumerator mirrors
  added so no enemy-occupied Seat is offered (employ_rodrigo both sides,
  call_crusade), invite_almoravids port-selection skips Enemy-occupied Ports
  and the enumerator gates on a valid Port existing; explicit pre-payment
  check in _h_cta_employ_rodrigo. (call_emir already used _free_seats_for.)
  Tests: tests/test_fix_retreat_relocation_p3p4p5.py.

## Cross-project Advisory #2 — illegal co-location bug CLASS (2026-05-23)
Inferno/Seljuk generalized Advisory #1 into a class: any path that leaves two
opposing FIELD Lords (both outside a Stronghold, no pending Approach) sharing a
Locale. Audited all three "doors" independently; the §1 co-location invariant
(added with P-3) is the oracle and stays the permanent gate.

- Door A (combat disposition) — VERIFIED OK. apply_retreat_aftermath relocates
  the loser (Battle) and P-3 relocates a losing Sally besieger. Destination
  constraints are ENFORCED, not a dead pass-through: confirmed a marching
  attacker that loses Retreats to its approach origin (breadcrumb threaded
  March -> march_arrival_response payload {from_locale_id, via_way_type} ->
  apply_retreat_aftermath). The direct cmd_battle path has no march, so it
  correctly passes no breadcrumb (no Way restriction applies).
- Door B (marker lifecycle) — FIXED with a backstop. The per-handler sweeps
  (P-2 combat removal, P-3 sally, F7 Disband/March) did not cover M19 Sail
  (_h_cmd_march_port_to_port), event removal (C25 De Vivar reconcile), or
  Winter/Curias Disband — a sole besieger leaving via those orphaned its Siege
  marker (indirect harm: stale Siege corrupts Supply/Forage/Tax legality;
  direct harm: stale Bypass suppresses a later Approach -> co-location). FIX:
  new campaign._sweep_all_orphaned_markers(state) called at the end of EVERY
  apply_action (the single action chokepoint). It is per-side and idempotent —
  clears a Siege/Bypass marker only when the owning side has no Lord at the
  Locale, so it never touches a live siege (the besieger is still present).
  RoP 4.3.5/4.3.6/4.4.1 ("becomes free of Enemy Lords -> remove all Siege and
  Bypass markers there") holds unconditionally, so a marker with no owning-side
  Lord is always illegal and clearing is always correct. _conquer_stronghold
  already clears Siege on conquest, so the Storm/Surrender path was fine. Tests:
  tests/test_advisory2_doors_bc.py (backstop clears M19 orphan; keeps a live
  siege). Full + deep sweep green.
- Door C (placement onto a contested Locale) — FIXED. Normal Muster
  (_free_seats_for), CtA Muster (P-5), and spring_muster already excluded
  enemy-occupied Seats. But the three EVENT auto-Musters — M22 Massacre, M21
  Al-Sumaisir, C16 Bernard de Sedirac — placed the Lord at seats[0] blindly,
  so they could Muster onto an Enemy-occupied Seat (co-location with no battle,
  on a pure Levy/Event path). 3.4.1 PROCEDURE: place "at one of his Seats that
  is neither Enemy nor has any Enemy Lords present"; 3.4.1 ARTS OF WAR: these
  cards "must otherwise still Muster by the usual rules." FIX: all three now use
  _free_seats_for and Muster at the first free Seat; M21/M22 fall through to
  their Jihad branch when none is free, C16 no-ops. Almoravid has NO "Muster
  into a Besieged Stronghold (placed inside)" exception (3.4 requires a Friendly
  Locale free of Siege), so the advisory's inside-placement case is N/A; the
  Crusaders/Bishops events add Forces to already-placed Lords, not new cylinders.
  Tests: tests/test_advisory2_doors_bc.py (C16 + M21 reject enemy Seat).

  Door C follow-up (independent audit): the audit grep found TWO more
  auto-Muster paths with the same seats[0] bug — C14 Pope Gregory and C15
  Cluniacs (_h_play_pope_gregory / _h_play_cluniacs, mode=muster_from_calendar,
  campaign.py). Both are named in 3.4.1 ARTS OF WAR and now require a free Seat
  via _free_seats_for (reject with code no_free_seat if none; not enumerated in
  legal_moves, so no Pattern-9 risk). Tests: test_advisory2_doors_bc.py
  (C14 rejects an enemy-occupied Seat). Door B sweep does NOT rescue this — it
  clears markers, not co-located cylinders; the §1 invariant is the catch.

## Cross-harness Advisory #3 — enumerator/handler asymmetry (2026-05-23)
Nevsky's consolidated advisory: the dominant agent-harness bug class is the
legal-move MENU drifting from the authoritative executor (over- and under-
enumeration). Applied the §2 full-fanout round-trip detector and the §1
under-enumeration cross-check.
- Prerequisite (§2): RNG is fully in-state (meta.seed + atomic meta.rng_state,
  no module global), so deepcopy->apply->discard probing is safe. Confirmed.
- OVER-enumeration (§1/§2): drove random + combat-seeking trajectories across
  ALL scenarios/seeds, probing EVERY enumerated candidate at each step with
  deepcopy+apply. Result: ZERO over-enumeration found anywhere. The enumerator
  and handlers are in lockstep for reachable states. Made permanent: a trimmed
  random+combat full-fanout probe added to tests/test_enumerator_handler_roundtrip.py
  (the heavy full version lives as a standalone diagnostic; per §2/§9 the suite
  keeps a lighter smoke variant so it stays a fast gate).
- UNDER-enumeration (§1): cross-checked all 56 dispatchable handlers against
  what the menu can emit. Found working handlers with NO menu entry (a
  menu-driven/LLM player can never invoke them):
  * dinars_deposit (4.1.4) — FIXED. Enumerated at the Plan step for each
    Unbesieged Muslim Taifa Lord (not Yusuf/Sir/Rodrigo) with Coin.
  * designate_lieutenant (4.1.3) — FIXED. Enumerated at the Plan step for each
    valid (Lower Lord, Lieutenant) pair: same side, same Locale, neither the
    Marshal, the commander not itself a Lower Lord nor already leading one.
  Both mirror the handler gates exactly; the round-trip probe confirms no new
  over-enumeration was introduced. Tests: tests/test_advisory3_underenum.py
  (positive + negative enumerator tests per §9).
  REMAINING under-enumeration (identified, scoped for a focused follow-up):
  * play_pope_gregory (C14) and play_cluniacs (C15) — discretionary HOLD events
    (like M11 play_al_qadir, which IS enumerated). Each has three modes
    (muster_from_calendar / service_shift_right / lordship_plus_2) with distinct
    per-mode preconditions; enumerating them needs careful per-mode gating to
    avoid introducing over-enumeration, so deferred rather than rushed.
  * toggle_lieutenant (C15 Alferez CAPABILITY half) — activation-step action
    gated on the active Lord holding the C15 capability; low-frequency.
  NOT bugs: set_absorption_policy is settable as a combat-action parameter and
  its greedy default is the documented B5 ADJ (4.4.2 owner-choice); bid_for_sides
  is intentionally un-enumerated (pre-game, 6.1); begin_campaign is a recovery
  action; the rest of the "never-enumerated in a short walk" list have valid
  emission paths reached only under specific conditions (verified statically).
  NOTE on the advisory's "Papal Legate" example: that is Nevsky-specific content
  (out of scope per BRIEF); used here only as the under-enumeration bug-SHAPE.
  The Almoravid findings derive from Almoravid's own rules (4.1.3/4.1.4, C14/C15).

### Advisory #3 follow-up — C14/C15 Hold-event enumeration + Alférez Q-001
- play_pope_gregory (C14) and play_cluniacs (C15) — FIXED (under-enumeration).
  Both are discretionary Christian HOLD events ("play on a Lord any time to
  Muster from Calendar, OR shift Service, OR for Lordship +2"; Arts of War ref
  C14/C15). Now enumerated on the Christian's turn in Levy/Campaign once held
  (mirroring the M11 play_al_qadir pattern), per valid target Lord (Sancho/Eudes
  for C14; any Christian for C15), with each (lord, mode) gated by that mode's
  precondition: muster_from_calendar only for a Calendar Lord with a free Seat
  (3.4.1); service_shift only when a Service marker exists; lordship_plus_2 for
  any on-map/Calendar target. Round-trip full-fanout probe over C14/C15-held
  states across scenarios: no over-enumeration. Tests:
  tests/test_advisory3_underenum.py (C14 modes, C15 any-Christian, not-when-
  unheld, muster-mode-absent-without-free-Seat).
- toggle_lieutenant (Alférez, C15 Capability half) — NOT enumerated; logged as
  Q-001 instead of guessed. The capability's effect (4.1.3 stack/unstack a
  Lieutenant via a Command action) is real, but its data scope is side_wide
  while the handler gates on a this_lord check (so it is currently dead), and
  the eligible-Lord set (Lords.txt names Álvar Fáñez; references Rodrigo) is
  unmodeled. Faithful wiring needs the scope + eligibility adjudicated
  (RULES_QUESTIONS.md Q-001). Left a documented no-op note at the enumeration
  site so the gap is visible.

### Q-001 RESOLVED (2026-05-23) — Alférez (C15) wired
User adjudication: the cards-data scope was the bug. C15 capability_scope
this_lord (was side_wide); eligible bearers = fixed set
capabilities.CHRISTIAN_CAPTAINS_FOUR {pedro_ansurez, garcia_ordonez,
alvar_fanez, rodrigo_campeador} (printed card list; identical for C8 Hueste &
C24 García Jiménez), NOT a Command-rating predicate, Rodrigo = Campeador only.
Enforced eligibility at deploy (3.1.2 _h_aow_deploy_capability inline check)
and Levy (3.4.4 _check_this_lord_cap_limits), mirrored in both enumerators so
no over-/under-enumeration. With scope=this_lord the toggle_lieutenant handler
gate (lord_has_capability C15) is now reachable; re-enumerated the Alférez
(un)stack at activation (4.1.3 outside-Plan-step exception). Five tests in
tests/test_q001_alferez.py (scope+eligibility set, levy-offers-only-captains,
handler-rejects-non-captain, stack->unstack, Marshal-not-a-target). Five
test_capabilities/test_fix_l13 cases that used C15 as a side_wide EXAMPLE were
repointed to C22 Bishoprics (a genuine side_wide cap). Round-trip probe with
C15 in play: no over-enumeration. Suite 868 passed, 0 skipped.

## Capability EFFECTS wired (2026-05-23) — Hueste, Emir al-Muslimin, Cabalgadas
The original handoff flagged data-only-but-unwired capability effects. Wired
three (their cards were deployable but the abilities never fired):
- C8 Hueste (Arts of War ref C8) — the bearer counts as a Marshal for a Group
  March (4.3.1) with a Taifa endpoint (not Kingdom->Kingdom); may not take
  Alfonso (the Marshal) in the group; cannot use it as a Lower Lord. Extended
  the group-march gate via _counts_as_marshal_for_march; the group is a
  player-supplied param (not enumerated). Tests: tests/test_cap_hueste_c8.py (4).
- M9 Emir al-Muslimin (Arts of War ref M9) — Yusuf, if STRICTLY closer than any
  Christian (shortest chain of adjacent spaces; co-location = not closer) to a
  Jihad-eligible Locale (1.4.4), uses his entire Command card to add 1 Jihad
  there. New cmd_emir_jihad + _emir_jihad_targets helper + map.hop_distances
  BFS; enumerated for Yusuf. Tests: tests/test_cap_emir_m9.py (3).
- C14/C17 Cabalgadas (Arts of War ref) — long-range Ravage: pay 1 Provender
  (own or Shared 1.5.2) + the entire Command card to Ravage a Locale up to two
  Ways distant with NO Unbesieged Enemy Lord on the intervening or target
  Locale (even if Bypassed). New cmd_cabalgadas + _cabalgadas_targets/
  _cabalgadas_prov_holder/_has_unbesieged_enemy_lord helpers; the 4.7.2 Ravage
  effect was factored into _apply_ravage_effect (shared by cmd_ravage and
  cmd_cabalgadas). Enumerated per legal target. Tests: tests/test_cap_cabalgadas.py
  (4). NOTE: the Muslim twin M24 Al-Garada ("See Cabalgadas") is NOT yet wired —
  its data scope is side_wide despite "This Lord" text (same mismatch as C15);
  logged as Q-002. cmd_cabalgadas already supports any this_lord Cabalgadas-
  family capability, so M24 is a one-line addition once Q-002 is adjudicated.
Round-trip probe (random + combat) across scenarios with these in play: no
over-enumeration. Suite 879 passed, 0 skipped.

### Q-002 RESOLVED (2026-05-23) — M24 Al-Garada wired
Same fix pattern as Q-001: cards.json M24 capability_scope this_lord (was
side_wide); eligible bearers = capabilities.MUSLIM_RAIDERS_SEVEN = the six Taifa
Muslim Lords (abd_allah, abu_bakr, al_mundir, al_mustain, al_mutamid,
al_mutawakkil) + rodrigo_al_sayyid (Yusuf/Sir excluded — not Taifa Lords).
Eligibility enforced at deploy (3.1.2) + Levy (3.4.4) and mirrored in both
enumerators. _cabalgadas_capable now checks CABALGADAS_CAPS={C14,C17,M24}, so
the existing cmd_cabalgadas long-range-Ravage handler/enumeration cover the
Muslim twin with no new command. Tests: tests/test_cap_cabalgadas.py (3 M24
cases). Round-trip probe: no over-enumeration. Suite 882 passed, 0 skipped.

## Battle of Sagrajas battle-only minigame (2026-05-23) — Background Book pp.44-47
First-class, LLM-playable through the standard interface (list_scenarios /
load_scenario / Harness), no manual battle-state construction.
- Registered: sagrajas.json (battle_minigame flag) -> list_scenarios includes
  "sagrajas"; load_scenario routes to build_sagrajas(seed). list_campaign_
  scenarios() excludes it so campaign-flow tests skip it. Harness.start/show
  work.
- Setup (deterministic; seed only drives resolution): musters the Background
  Book rosters with all Vassal Forces (Sancho none; Abd Allah drops his Almeria
  Light Horse Vassal); Bishoprics (C22, +Bishop units to Alfonso/Pedro/Garcia),
  Milites (C18, +4 LH +2 Mi), Arqueros (C4/C5) on two Christians; Alrama (M4/M5)
  on two Taifa Lords; Muslims hold Spear Wall (M7). Enters phase 'battle' with a
  pending Christian "Who Attacks?" decision.
- Branches (req): sagrajas_attack (historical) adds Crusaders (+4 Knights),
  Jabalinas (C7) + Slingers (C9) + Cantador (C8 Held) -> Christians Attack
  (Marshal Alfonso Front center, 4.4.1). sagrajas_defend adds Saqalibah (M15,
  +2 MaA), Harbah (M3), Andalusians (M10 side-wide Evade), Feigned Retreat (M6
  Held) -> Yusuf Attacks. Then resolve_battle runs Battle 4.4; winner wins the
  game (loser's Lords leave the field so no post-game co-location). Recorded in
  score.winner / victory_reason; phase -> ended.
- render_sagrajas: a clear battle view (role, Attacker/Defender + Marshal, each
  side's Lords/Forces/Capabilities, Held Events, side-wide caps, a card key) so
  an agent never inspects raw objects. legal()/apply() expose the role choice
  and resolve_battle; the validated palette never offers a rejected action.
- Deep-invariant sweep + round-trip probe now drive "sagrajas" automatically
  (clean). Tests: tests/test_sagrajas_minigame.py (17). Limitation logged:
  Yusuf/Sir African-Horse Javelins marker not modeled (RULES_QUESTIONS). Card
  metadata gap C4/C5/M4/M5/M3/M6 logged as Q-003 (minigame unaffected).
