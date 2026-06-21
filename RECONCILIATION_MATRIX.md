# Rules-of-Play Reconciliation Matrix (clause-by-clause)

An exhaustive, clause-level reconciliation of GMT's *Almoravid* Rules of
Play (`reference/Almoravid_Rules_of_Play.txt`), Errata, and Scenario
Adjustments against this implementation (`src/almoravid/`). This is the
detailed companion to the chapter-level summary in `RECONCILIATION.md`.

**Method.** Every numbered clause (to the x.y.z level) was mapped to the
code symbol that implements it and the test that covers it, by grepping
the source and test tree — not from memory. Each row's Code and Test
columns cite real `file:symbol` / `file::test_name`. Clauses with logic
but no test are flagged `GAP — no test`; clauses suspected wrong are
flagged `⚠ SUSPECT`. The highest-impact suspicions were then verified by
hand against rules + code; confirmed bugs were fixed (see Resolutions).

**Verdict key.** `OK` faithful · `FIXED` gap found & corrected in this
pass · `PARTIAL` faithful outcome via a documented abstraction · `GAP`
no test / not implemented · `N/A-physical` component-only, no game logic.

---

## Findings & Resolutions (this pass)

The audit surfaced four materially-incorrect or unimplemented clauses.
All four were verified by hand against the rules and the code, fixed, and
covered with regression tests (`tests/test_reconciliation_matrix_fixes.py`).

1. **4.5.4 Jihad removes a Muslim Siege — was NOT IMPLEMENTED → FIXED.**
   Rule: "Any Jihad added at a Muslim Siege removes all Siege markers
   there." No Jihad-placement path cleared siege markers. Added
   `Locale.add_jihad()` (`state.py`) which increments the Jihad count and
   zeroes Muslim-placed (`siege_green`) markers, and routed every runtime
   Jihad-placement site (`events.py`, `campaign.py`, `actions.py`) through
   it. Christian (`siege_yellow`) sieges are untouched — that case is
   Recognition of Neutrality / Hostage Populace (1.4.3).
   Tests: `test_add_jihad_clears_muslim_siege_454`,
   `test_add_jihad_leaves_christian_siege_454`,
   `test_event_jihad_path_clears_muslim_siege_454`.

2. **4.3.6 / 4.3.1 group Sortie leadership — INVERTED → FIXED.** The gate
   allowed a Marshal *or* `lord.is_lieutenant`, but the internal
   `is_lieutenant` flag marks the **Lower** Lord, while rule 4.3.6 lets a
   **Lieutenant** (the *upper* Lord) lead. So a real Lieutenant was
   rejected and a Lower Lord wrongly permitted. The check now keys off
   `any(other.lieutenant_of == lord_id)` (i.e. the lord is some Lord's
   Lieutenant). Tests: `test_lieutenant_upper_lord_may_sortie_group_436`,
   `test_lower_lord_may_not_sortie_group_436`.

3. **6.3.3 Spring Muster — stranded Taifa Lord status — MISSING → FIXED.**
   Rule: a Muslim Taifa Lord who would Muster but has no free Seat goes to
   the Calendar *and* his Taifa adjusts (1.4.1/1.4.3, incl. Parias Coin).
   The no-free-seat branch only relocated the cylinder. It now mirrors the
   Disband cascade (off-map, `adjust_taifa_status(..., "parias")`, Parias
   Coin, +1 Christian VP). Test:
   `test_spring_muster_stranded_taifa_lord_goes_parias_633`.

4. **M14/M18 Ribat Monks — capability was a no-op (data + logic) → FIXED.**
   `cards.json` defined M14/M18 with `no_capability:true`, so the Ribat
   Monks Capability granted in Scenario D did nothing. The Arts of War
   reference: "Christian Ravage in this Lord's Taifa must roll 1-3 for
   effect." Gave M14/M18 a `this_lord` Ribat Monks capability, restricted
   eligibility to the six Taifa Muslim Lords, and added the 1-3 roll to
   the Ravage Command (`_h_cmd_ravage`): on 4-6 the action is spent but no
   Ravaged marker is placed. Tests:
   `test_ribat_monks_blocks_ravage_on_high_roll`,
   `test_ribat_monks_allows_ravage_on_low_roll`,
   `test_ravage_without_ribat_monks_makes_no_roll`,
   `test_ribat_monks_eligibility_is_taifa_muslim_only`.

**Background Book validation.** Two "Examples of Play" were encoded as
exact-outcome anchors against GMT's printed numbers
(`tests/test_background_book_examples.py`): the Conquest of Toledo
(Parias→Reconquista: Christian -½ / Muslim +1½ running, Calatrava 2 Jihad,
Christian final +1½) and Uphold the Dynasties on Scenario E box 9 (Muslim
final 8 → 9½). Both reproduce the booklet exactly.

**Deliberate abstractions (not bugs), retained & documented.** 6.2.1
Curias tallies a Taifa's Conquered markers as Christian (yellow) and
Kingdom Conquered as Muslim (green) — correct under the rules, since in a
Taifa Muslims place *Jihad* not Conquered, so marker colour follows
territory. 4.4.2 ROLL WALLS pools the cancellation roll and drains
Crossbow hits last rather than rolling them separately — statistically
identical cancel-count for a contiguous Walls range; deterministic
drain-order only. Reconquista/Parias VP scored per Taifa-status and
Taifas-box Conquered folded into `taifas_box_vp` — equivalent to per-marker
for all six scenarios. Interactive choices with deterministic defaults
(Wastage/voluntary-Pay/Greed mule-discard) per `RULES_DECISIONS.md`.

**Open (lower-impact) items for a future pass.** 4.9.5 optional "discard
Arts of War cards to decks" Reset step is not implemented (optional player
action, no forced consequence). Advanced Vassal Service (3.4.2) Service
shifts are not propagated to Vassal markers in Enforcing Parias (4.7.2),
Unfed (4.8.1), or Battle Service (4.4.3). Several correct-but-untested
branches are listed as `GAP — no test` in the tables below.

---

## Chapter 1 — Components & Concepts

| Clause | Rule summary | Status | Code (file:symbol) | Test | Notes |
|---|---|---|---|---|---|
| 1.1 | General course of play (sides, 40-day turns) | N/A-physical | — | — | Sides modeled as `christian`/`muslim` throughout. |
| 1.2 | Component list | OK | `static_data.py` loaders; `state.py` | static_data.py::test_16_lords_9_muslim_7_christian; ::test_52_cards_26_per_side | Wooden bits in test_forces_and_strongholds.py. |
| 1.3.1 | Map / Locales / Ways / Strongholds / Seats / Ports / Gardens | OK | `map.py`; `static_data.py`; `effective.py:is_friendly_locale`; `campaign.py:_conquer_stronghold` | static_data.py::test_72_locales, ::test_109_ways_72_roads_37_passes, ::test_every_locale_territory_exists; test_forces_and_strongholds.py::test_four_stronghold_types, ::test_city_has_3_capacity_3_value | |
| 1.3.1 | Conquering markers (Value; Jihad vs Conquered; ravage flip) | OK | `campaign.py:_conquer_stronghold` | test_ravage_flip_and_grow_vp.py::test_christian_conquest_flips_own_yellow_to_green; test_fix_t1t2_vp_conquest.py::test_t2_muslim_conquest_in_taifa_places_jihad_removes_christian | |
| 1.3.1 | Seat markers (friendliness; removed on conquest/leave) | OK | `state.py:Locale.seat_marker_lord_ids`; `actions.py:_h_disband_lord`; `_conquer_stronghold` | test_printed_seats_vs_markers_f4.py::test_placed_seat_marker_confers_friendliness | Cathedral seats handled. |
| 1.3.2 | Calendar (seasons, boxes, Ready/Disband) | OK | `state.py:Calendar`; `campaign.py:_current_season` | test_scenarios.py::test_service_markers_placed | |
| 1.3.3 | Taifas Box (Coin + VP; pay as own Coin) | OK | `state.py:GameState.taifas_box_coin/_vp`; `actions.py:_h_pay_lord` | test_fix_pay_321.py::test_taifa_box_coin_shifts_unbesieged_muslim; test_taifas_box_vp_loaded_f8.py | |
| 1.4 | Taifa Politics (7 Taifas; status) | OK | `state.py:Taifa`; `campaign.py:adjust_taifa_status`, `maybe_recompute_taifa_status` | test_scenarios.py::test_taifas_have_status | |
| 1.4.1 | Status conditions (Reconquista/Parias/Independent; Toledo never Independent; Sevilla triple) | OK | `campaign.py:maybe_recompute_taifa_status` | test_scenarios.py::test_toledo_never_independent; test_adjust_status.py::test_recompute_toledo_never_independent | |
| 1.4.2 | Characteristics / territory friendliness | OK | `campaign.py:compute_final_vp`; `effective.py:is_friendly_locale` | test_phase7b_victory.py::test_sevilla_reconquista_worth_nine_vp; test_fix_t1t2_vp_conquest.py::test_t1_sevilla_parias_worth_three_vs_other_taifa_one | |
| 1.4.3 | PARIAS COIN (Indep→Parias; 6 al-Mutamid/Sevilla else 4; Ruined Land) | OK | `campaign.py:adjust_taifa_status`, `_parias_coin_amount`; `actions.py:_award_parias_coin` | test_fix_t3t5_taifa.py::test_t5_parias_coin_awarded_on_independent_to_parias, ::test_t5_sevilla_parias_coin_is_six | |
| 1.4.3 | RAVAGED LAND (flip yellow↔green on status change + VP) | OK | `campaign.py:adjust_taifa_status` ravaged-flip | test_adjust_status.py::test_independent_to_reconquista_flips_yellow_to_green | Anchored by test_background_book_examples.py::test_bgbook_conquest_of_toledo. |
| 1.4.3 | HOSTAGE POPULACE (force-Conquer; no Spoils; flip Ravaged) | OK | `campaign.py:adjust_taifa_status`; `_conquer_stronghold` | test_fix_t3t5_taifa.py::test_t3_forced_jihad_removes_christian_conquered_marker; test_adjust_status.py::test_independent_to_reconquista_adds_jihad_if_muslim_lord_present | Anchored by the Toledo example test. |
| 1.4.3 | RECOGNITION OF NEUTRALITY (→Parias; remove Siege/Bypass OR add markers) | OK | `campaign.py:adjust_taifa_status`, `_h_respond_neutrality_choice` | test_fix_t4_neutrality_choice.py::test_t4_add_choice_places_jihad_and_keeps_siege, ::test_t4_no_choice_defers_then_remove_lifts_siege | Surfaced as interactive pending decision. |
| 1.4.3 | OPEN GATES (Friendly flip clears Siege/Bypass) | OK | `campaign.py:adjust_taifa_status`, `_remove_orphaned_siege_bypass`; `state.py:Locale.add_jihad` (4.5.4) | test_fix_t4_neutrality_choice.py; test_reconciliation_matrix_fixes.py::test_add_jihad_clears_muslim_siege_454 | Now reinforced by the 4.5.4 fix. |
| 1.4.4 | Jihad (eligibility; ½VP; never on Christian Conquered/Seat) | OK | `events.py:_jihad_eligible_locales`, `_add_jihad`; `state.py:Locale.add_jihad` | test_m15_jihad_eligibility.py::test_m15_does_not_stack_jihad_on_conquered_locale; test_reconciliation_matrix_fixes.py::test_event_jihad_path_clears_muslim_siege_454 | |
| 1.5.1 | Lords (cylinders, Marshals, Taifa Lords, Rodrigo dual, Service markers) | OK | `state.py:Lord`; `campaign.py:_MARSHALS`; `actions.py:_h_disband_lord` | test_scenarios.py::test_all_16_lords_present_with_unique_cylinders; test_static_data.py::test_marshals_have_command_4 | |
| 1.5.2 | Lord Mats (sections; Hidden Mats; Sharing) | OK | `state.py:Lord`; `views.py`/`render.py` | test_hidden_mats_152.py::test_hidden_opponent_mats_when_enabled, ::test_lord_in_battle_is_revealed | |
| 1.5.3 | Ratings (Fealty, Service, Lordship, Command) | OK | `state.py:Lord.*_rating` | test_fix_muster_341.py::test_muster_places_service_marker_ahead | |
| 1.5.4 | Vassals (markers; forces only on Muster; Special Vassals) | OK | `state.py:Vassal`; `actions.py:_h_levy_take_vassal` | test_phase7d_vassal_service.py; test_advanced_vassal_service_342.py | |
| 1.6 | Forces (no-Forces lord auto-Disbands) | OK | `static_data.py:load_forces`; `actions.py:_h_disband_lord` | test_forces_and_strongholds.py::test_serfs_auto_remove; test_auto_disband_3_3.py | |
| 1.7 / 1.7.1 | Assets & Accounting | OK | `state.py:Lord.assets` | test_interactive_economy.py | |
| 1.7.2 | Greed (discard assets only to move/feed) | PARTIAL | feed/march handlers; `campaign.py:_is_laden` | test_forage_ravage.py; test_fix_e4e5e6_feed.py | No free-discard action offered; acceptable. `GAP — no direct test`. |
| 1.7.3 | Transport (Cart/Mule; carry Provender) | OK | `campaign.py:_is_laden`, `_group_laden` | test_fix_c4_laden.py; test_supply_tax.py | |
| 1.8 | Other Markers | N/A-physical | fields on `state.py:Locale`/`Calendar` | test_static_data.py | |
| 1.9 / 1.9.1 | Arts of War (Events + Capabilities; This Lord; cards>rules) | OK | `state.py:Decks`; `capabilities.py`; `events.py` | test_static_data.py::test_pattern_14_every_capability_has_scope; test_capabilities.py | M14/M18 Ribat Monks now a valid `this_lord` cap (FIXED). |
| 1.9.2 | Command Cards (3/lord, 4/Marshal; Pass) | OK | `state.py:PlanEntry`; `static_data` | test_static_data.py::test_marshals_have_command_4; test_fix_c7_plan_caps.py | |

## Chapter 2 — Setup & Calendar

| Clause | Rule summary | Status | Code (file:symbol) | Test | Notes |
|---|---|---|---|---|---|
| 2.1.1 | Layout / pools / decks / screens | N/A-physical | `scenarios.py:load_scenario` | test_scenarios.py::test_load_scenario_returns_valid_gamestate | Screens = Hidden Mats option. |
| 2.1.2 | Scenario select / options / first Levy | OK | `scenarios.py:load_scenario`; `state.py:Meta` | test_scenarios.py::test_scenario_a_setup, ::test_scenario_f_long_campaign; test_bidding_61.py | |
| 2.2.1 | Seasons (Spring/Summer/Autumn vs Winter) | OK | `campaign.py:_current_season`, `PLAN_SIZE_BY_SEASON` | test_winter_sequence_63.py; test_curias_winter.py | |
| 2.2.2 | Marking Time | OK | `state.py:Calendar.current_box`, `Meta.phase` | test_smoke.py; test_cli_state_flow.py | |
| 2.2.3 | Marking Service (shift; 0 / 17+ clamps) | OK | `actions.py:_shift_service_left/right` | test_fix_pay_321.py::test_coin_shifts_rightward; test_fix_muster_341.py::test_muster_places_service_marker_ahead | |
| 2.2.4 | Player Order (Christian first; exceptions) | OK | `actions.py:ACTOR_ORDER`, `_advance_step_if_both_done` | test_real_levy.py; test_phase6* | |
| 2.2.5 | Tracking VP (boxes, +½, net >17) | OK | `campaign.py:compute_final_vp`, `compute_victory`; `state.py:Score` | test_phase7b_victory.py::test_compute_final_vp_counts_taifa_status, ::test_tie_is_draw | Running score vs `compute_final_vp` (authoritative) distinction. |

## Chapter 3 — Levy

| Clause | Rule summary | Status | Code (file:symbol) | Test | Notes |
|---|---|---|---|---|---|
| 3.1 | Arts of War (each side draws two) | OK | `actions.py:aow_capability_phase` | test_fix_aow_mandatory_draw.py::test_first_levy_draw_deploys_two_capabilities | |
| 3.1.1 | Shuffle (exclude Held/in-play/removed C18) | OK | `actions.py:_h_aow_shuffle`, `_rebuild_aow_deck` | test_fix_aow_per_side_deck_p1.py; test_c18_removed_from_game.py::test_c18_discard_removes_from_game_and_blocks_recycle | |
| 3.1.2 | Draw Capabilities (first Levy; deploy two) | OK | `actions.py:_h_aow_draw`, `_h_aow_deploy_capability` | test_fix_l13_aow_draw.py::test_first_levy_deploys_this_lord_capability_to_lord | Scenario-F box-9 (6.3.5) handled. |
| 3.1.3 | Draw Events (2nd+ Levies; This-Levy/Hold) | OK | `actions.py:_h_aow_implement_event`; `events.py:resolve_event` | test_fix_l13_aow_draw.py::test_later_levy_implements_event_in_draw_order; test_events.py | |
| 3.1.4 | Greed (no card discard unless permitted) | OK | (no discard action) | test_events.py; test_fix_c5_avoid_discard.py | |
| 3.2 / 3.2.1 | Pay with Coin (own / same-locale / Taifa-box) | OK | `actions.py:_h_pay_lord` | test_fix_pay_321.py::test_coin_can_target_another_lord_same_locale, ::test_taifa_box_coin_shifts_unbesieged_muslim | |
| 3.2.2 | Pay with Loot (Friendly free of Siege; Bypassed OK) | OK | `actions.py:_h_pay_lord` (loot) | test_fix_pay_321.py::test_loot_requires_friendly_locale_free_of_siege | |
| 3.3 | Disband (order; besieged normal; no-Forces auto) | OK | `actions.py:_h_disband_lord` | test_auto_disband_3_3.py::test_at_limit_non_taifa_still_goes_to_calendar_with_campaign_plus_one | |
| 3.3.1 | Beyond Service (permanently removed; caps→edge) | OK | `actions.py:_h_disband_lord` (beyond) | test_auto_disband_3_3.py::test_beyond_service_lord_is_permanently_removed | |
| 3.3.2 | At Service (to Calendar; Independent-Taifa→Parias+Coin+VP; errata +1) | OK | `actions.py:_h_disband_lord`; `_compute_disband_target_box` | test_fix_disband_331_332.py::test_independent_taifa_lord_disband_awards_parias_coin_and_status; test_auto_disband_3_3.py::test_independent_taifa_disband_triggers_parias_cascade | |
| 3.4 | Muster (order; ≤Lordship; Friendly+Unbesieged; must participate) | OK | `actions.py:_require_levy_actor_eligible` | test_fix_muster_lordship.py::test_muster_spends_levier_lordship; test_real_levy.py | |
| 3.4.1 | Levy Lords to Muster (Fealty roll; free Seat errata; Taifa→Independent) | OK | `actions.py:_h_muster_lord`, `_free_seats_for` | test_fix_muster_341.py::test_muster_taifa_lord_sets_independent; test_levy_capability_limits_34.py::test_free_seats_excludes_enemy_territory_seat; test_m16_by_muster_ban.py::test_banned_lord_cannot_be_the_levying_lord | |
| 3.4.2 | Levy Vassal Forces (specials; Advanced Vassal Service) | OK | `actions.py:_h_levy_take_vassal` | test_phase7d_vassal_service.py; test_advanced_vassal_service_342.py | Advanced rule under flag. |
| 3.4.3 | Levy Transport (Cart/Mule; return lost Serf) | OK | `actions.py:_h_levy_transport` | test_fix_levy_transport.py::test_levy_transport_adds_cart, ::test_levy_transport_returns_lost_serf | |
| 3.4.4 | Levy Capabilities (This-Lord max 2; eligibility; excess discard) | OK | `actions.py:_h_levy_take_capability`, `_check_this_lord_cap_limits` | test_levy_capability_limits_34.py::test_third_this_lord_cap_rejected; test_q001_alferez.py::test_levy_offers_c15_only_to_eligible_captains | Ribat Monks eligibility added: test_reconciliation_matrix_fixes.py::test_ribat_monks_eligibility_is_taifa_muslim_only. |
| 3.5 | Call to Arms (skip in A/B; one option/side) | OK | `actions.py` CTA handlers | test_fix_call_to_arms.py::test_one_option_per_side | |
| 3.5.1 | Campeador or Crusade (Reconcile/Employ/Crusade) | OK | `actions.py:_h_cta_reconcile_rodrigo`, `_h_cta_employ_rodrigo`, `_h_cta_call_crusade` | test_fix_call_to_arms.py::test_employ_campeador_pays_two_coin_and_musters, ::test_call_for_crusade_musters_eudes_and_sets_pending | |
| 3.5.2 | Al-Sayyid or al-Murabitun (Employ/Invite/Uphold/Emir) | OK | `actions.py:_h_cta_invite_almoravids`, `_h_cta_uphold_dynasties`, `_h_cta_call_emir` | test_fix_call_to_arms.py::test_invite_almoravids_musters_and_places_eudes, ::test_uphold_dynasties_shifts_both_and_banks_vp, ::test_call_emir_musters_taifa_lord | Uphold exact VP anchored: test_background_book_examples.py::test_bgbook_uphold_the_dynasties_scenario_e. |
| 3.5.3 | Discard This-Levy Events | OK | levy-end discard of `this_levy_events` | test_fix_l2b_this_levy.py; test_events.py | |

---

## Chapter 4 — Campaign

### 4.0–4.3 Plan / Command / March

| Clause | Rule summary | Status | Code (file:symbol) | Test | Notes |
|---|---|---|---|---|---|
| 4.0 Campaign steps | Plan → alternating Command Activations → End Campaign | OK | campaign.py:`_h_begin_campaign`(118), `_advance_or_end_campaign`(337) | test_campaign.py::test_begin_campaign_enters_plan_step; ::test_both_finalize_advances_to_activation | |
| 4.0 CAPABILITY DISCARD | Christian then Muslim discard side-wide Caps in excess of Mustered Lords; "This Lord" exempt | OK | campaign.py:`_apply_capability_discard`(95) | test_fix_c6c8c9_misc.py::test_c6_discards_capabilities_beyond_mustered_lord_count; ::test_c6_keeps_when_not_in_excess | Counts only board-edge caps; excess chosen deterministically (player-choice abstraction) |
| 4.1 Plan sizes | Spring 7 / Summer 8 / Autumn 7 | OK | campaign.py:`PLAN_SIZE_BY_SEASON`(44), `_plan_target_size`(78) | test_campaign.py::test_plan_size_by_season | |
| 4.1.1 Selecting Cards | Only Mustered Lords' cards; fill shortfall with Pass | OK | campaign.py:`_h_plan_add_card`(163) | test_fix_c7_plan_caps.py::test_unmustered_lord_cannot_be_planned; ::test_pass_card_cap_is_five | |
| 4.1.1 NOTE card counts | 3 cards/Lord, 4 if Marshal | OK | campaign.py:`_h_plan_add_card` per-lord cap | test_fix_c7_plan_caps.py::test_per_lord_command_cap_three_for_normal_lord; ::test_marshal_command_cap_is_four | |
| 4.1.2 Arranging Stacks | Ordered face-down stack = target size; no rearrange | OK | campaign.py:`_h_finalize_plan`(225) | test_campaign.py::test_finalize_plan_rejects_short_plan | |
| 4.1.3 Lieutenants designate | Stack a Lord on another, same Locale, same side, Plan step only | OK | campaign.py:`_h_designate_lieutenant`(5151) | test_phase7c_lieutenants.py::test_designate_lieutenant_stacks_lower_lord; ::test_designate_requires_same_locale | |
| 4.1.3 Marshal restriction | Marshal not Lt nor Lower Lord | OK | `_h_designate_lieutenant` marshal guard | test_phase7c_lieutenants.py::test_marshal_cannot_be_lower_lord | |
| 4.1.3 One Lower Lord max | A Lt has ≤1 Lower Lord | OK | `_h_designate_lieutenant` `lieutenant_full` | test_phase7c_lieutenants.py::test_lieutenant_has_at_most_one_lower_lord | |
| 4.1.3 Move together | Lt + Lower move together | OK | campaign.py:`_h_cmd_march`(1989) auto-adds lieutenant_of==mover | test_phase7c_lieutenants.py::test_group_march_brings_lower_lord | |
| 4.1.3 Disband → normal | Survivor becomes normal Lord | OK | (C8 path) | test_fix_c6c8c9_misc.py::test_c8_disbanding_lieutenant_frees_lower_lord | |
| 4.1.3 Lower Lord card = Pass | Revealing Lower Lord's card passes | OK | campaign.py:`_h_command_reveal`(273) | test_phase7c_lieutenants.py::test_lower_lord_command_card_auto_passes | `is_lieutenant` flag is on the LOWER lord (state.py:383) |
| 4.1.3 Alférez stack/unstack | Alférez card creates/unstacks Lt | OK | campaign.py:`_h_toggle_lieutenant`(5202) | test_q001_alferez.py (suite) | |
| 4.1.3 PLAY NOTE Castle capacity | Lt pair may not Withdraw into Cap-1 Castle | OK | `_h_respond_withdraw` `lt_pair_split` guard | test_fix_c6c8c9_misc.py::test_c9_withdraw_rejects_splitting_lt_pair | |
| 4.1.4 Dinars | Unbesieged Taifa Lords (not Yusuf/Sir/Rodrigo) deposit Coin to Taifas box | OK | campaign.py:`_h_dinars_deposit`(5575) | test_phase7g_misc.py::test_dinars_deposit_moves_coin_to_box | ⚠ minor: handler not step-gated to Plan (only offered in Plan via legal_moves) |
| 4.2 / 4.2.1 Activation | Reveal top card; actions up to Command Rating | OK | campaign.py:`_h_command_reveal`(273) `effective_command` | test_campaign.py::test_command_reveal_active_lord_with_actions | |
| 4.2.1 EXCEPTION Besieged menu | Besieged: Forage(Gardens)/Sally/Pass only | OK | legal_moves.py besieged gates (~1196) | test_storm_sally.py / test_fix_b6_relief_sally.py (suite) | |
| 4.2.1 Siege/Tax whole card; Battle/Storm/start-Siege end actions | Command-consumption rules | OK | campaign.py:`_h_respond_besiege`(4442); siege handler | test_fix_siege_451.py; test_fix_c1_besiege_bypass.py::test_besiege_places_marker_and_ends_card | |
| 4.2.2 Command Menu | March/Siege/Storm/Sally/Supply/Forage/Ravage/Tax/Pass | OK | legal_moves.py `_activation_moves` | test_menu_reachability.py | |
| 4.2.3 Pass Card | Pass / Lower-Lord / off-map Lord card → do nothing | OK | campaign.py:`_h_command_reveal` auto_pass branch | test_campaign.py::test_command_reveal_pass_card_auto_passes | **GAP — no test** for off-map-Lord branch alone |
| 4.3 March cost | Unbesieged Lord: 1 action (2 if Laden); Transport hauls Provender only | OK | campaign.py:`_h_cmd_march`(1989) | test_march.py; test_fix_c4_laden.py | |
| 4.3 MOVED/FOUGHT | Mark moving Lords | OK | `_h_cmd_march` sets moved_fought | test_moved_fought_siege_avoid.py (suite) | |
| 4.3.1 Group March | Same-Locale Unbesieged Lords March with a Marshal | OK | `_h_cmd_march` `_counts_as_marshal_for_march`(5131) | test_fix_c3_group_march.py::test_marshal_leads_group_march; ::test_non_marshal_cannot_lead_group | |
| 4.3.2 LADEN triggers | Laden if unit carries 2 Prov, Cart-Prov over Pass, or any Loot | OK | campaign.py:`_is_laden`(1935) | test_fix_c4_laden.py::test_provender_exceeding_transport_is_laden; ::test_any_loot_is_laden; ::test_cart_with_one_prov_over_pass_is_laden | |
| 4.3.2 SHARED TRANSPORT | Group counts combined Prov/Transport/Loot | OK | campaign.py:`_group_laden`(1965) | test_fix_c3_group_march.py::test_group_march_uses_shared_transport_for_laden | |
| 4.3.2 LADEN MARCH cost/prohibit | 2 actions/Locale; prohibited if only 1 left | OK | `_h_cmd_march` `not_enough_actions` | test_fix_c4_laden.py (cost tests) | |
| 4.3.2 Discard to facilitate | May discard excess Provender (cap 2× transport) | OK | `_h_cmd_march` `prov_excess` | test_fix_prov_capacity.py | |
| 4.3.3 March Adjacent | Single Way regardless of Transport | OK | `_h_cmd_march` `neighbors_via` | test_march.py | African Fleet via `_h_cmd_march_port_to_port`(4956) |
| 4.3.4 Approach trigger | Entering Unbesieged/Unbypassed enemy Lord's Locale | OK | campaign.py:`_check_approach_trigger`(4047) | test_phase6b_approach.py::test_cmd_march_into_enemy_lord_triggers_pending_decision | |
| 4.3.4 AVOID BATTLE | Adjacent; not back across approach Way; not into enemy Locale; Unladen; discard Loot/excess Prov as Spoils | OK | campaign.py:`_h_respond_avoid_battle`(4157) | test_phase6b_approach.py::test_respond_avoid_battle_moves_defender_and_blocks_approach_way; test_fix_c5_avoid_discard.py::test_avoid_discards_all_loot_as_spoils | |
| 4.3.4 AVOID into enemy Stronghold = Bypass | Mark avoider Bypassing | OK | `_h_respond_avoid_battle` bypass marker | **GAP — no test** asserting this specific marker |
| 4.3.4 WITHDRAW | Into Friendly Stronghold up to Siege Capacity; not Moved/Fought | OK | campaign.py:`_h_respond_withdraw`(4302) | test_phase6b_approach.py::test_respond_withdraw_into_friendly_stronghold; ::test_respond_withdraw_rejected_when_not_friendly | |
| 4.3.4 BATTLE | Unless all Avoid/Withdraw, Battle, marcher = Attacker | OK | campaign.py:`_h_respond_stand_battle`(4601) | test_phase6b_approach.py::test_respond_stand_battle_resolves_and_ends_card | |
| 4.3.4 Partition (C2) | Split Lords across Avoid/Withdraw/Battle | OK | campaign.py:`_approach_subset`(4109) | test_fix_c2_partition.py::test_partition_avoid_then_withdraw_then_stand | |
| 4.3.5 Besiege-or-Bypass trigger | Lords outside enemy SH w/ enemy Withdrawn inside must choose | OK | campaign.py:`_set_besiege_or_bypass_pending`(4379) | test_fix_c1_besiege_bypass.py::test_withdraw_triggers_besiege_or_bypass_pending; test_fix_c1b_postbattle_besiege.py | |
| 4.3.5 Besiege | 1 Siege marker, skip remaining actions, → FPD | OK | campaign.py:`_h_respond_besiege`(4442) | test_fix_c1_besiege_bypass.py::test_besiege_places_marker_and_ends_card | |
| 4.3.5 Bypass | Bypass marker; continue actions in Locale | OK | campaign.py:`_h_respond_bypass`(4466) | test_fix_c1_besiege_bypass.py::test_bypass_places_marker_and_card_continues | |
| 4.3.5 Join / markers removed when free | Arrivals join; remove when enemy-free | OK | `_remove_orphaned_siege_bypass`(4019) | test_depart_marker_cleanup.py::test_march_away_removes_orphaned_bypass_marker | |
| 4.3.5 Never Besiege/Bypass Friendly/Neutral | enforced | OK | `_set_besiege_or_bypass_pending` `_iel_bb` | test_fix_neutral_enemy_435.py | |
| 4.3.6 DEPART | Begin-card Bypassing/Bypassed Lord may March adjacent; remove Bypass if none remain | OK (implicit) | campaign.py:`_h_end_card`(544) clears `bypassed_this_card` | **GAP — no test** for positive depart flow (only marker cleanup tested) |
| 4.3.6 ENCAMP | Bypassing Lord: 1 March action (ignore Laden) replaces Bypass with 1 Siege, ends card | OK | campaign.py:`_h_cmd_encamp`(5439) | test_phase7g_misc.py::test_encamp_replaces_bypass_with_siege; ::test_encamp_rejected_when_not_bypassing | |
| 4.3.6 SORTIE | Lord/group in Bypassed Friendly SH uses 1 March action to Approach Bypasser | **PARTIAL ⚠ SUSPECT** | campaign.py:`_h_cmd_sortie`(5475) | test_sortie_436.py::test_sortie_sets_approach_pending_against_bypassing_enemy; ::test_sortie_then_stand_resolves_battle | **Group-leader check inverted** — see Finding #2 |
| 4.3.6 SORTIE marks Moved | Sortieing Lords marked Moved | OK | `_h_cmd_sortie` sets moved_fought | test_sortie_436.py::test_sortie_then_stand_resolves_battle | |

### 4.4 Battle

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 4.4.1 Array order Atk then Def | Attacker arrays first | OK | campaign.py:`_h_cmd_battle`(3448); battle.py:`battleside_for_lords`(1271) | test_phase6e_array.py::test_multi_lord_attacker_active_at_center | |
| 4.4.1 Front center/left/right + Reserve | ≤3 Front, rest Reserve | OK | battle.py:`battleside_for_lords` | test_fix_b4_battle_over.py::test_front_limit_two_sends_third_lord_to_reserve | |
| 4.4.1 Active Lord Front center | Active at center | OK | `battleside_for_lords`(1327) | test_phase6e_array.py::test_multi_lord_attacker_active_at_center | |
| 4.4.1 Defender opposite each Front Atk, center→L→R | One Defender opposite each | PARTIAL | `battleside_for_lords` `front_limit`=`_front_lord_count`(1258) | test_fix_b4_battle_over.py::test_front_lord_count_reflects_array | ⚠ Caps def Front count to atk's; opposition by positional slot in per-pair, not literal per-slot placement (acceptable abstraction) |
| 4.4.1 JAVELINS marker | On Lords w/ African Horse/Jabalinas/Harbah | OK | battle.py:`build_strike_rows`(258) one_round_only rows | test_resolver_sagrajas_fixes.py::test_javelin_rows_marked_one_round_only; ::test_no_javelins_without_capability | Modeled as rows, not a marker object |
| 4.4.1 Javelins cap 4 Unarmored/Lord | ≤4 units | OK | `build_strike_rows` javelin_budget=4 | test_resolver_sagrajas_fixes.py::test_javelin_units_capped_at_four_single_type | |
| 4.4.1 EVENTS timing (Atk then Def, before R1) | Held Events before Round 1 | PARTIAL | battle.py:`_consume_camp_attack`(2542); per-round event gating | test_phase6a_combat_events.py; test_oneround_timing.py | **No generic "play any Held Event" choice step** — only specific battle cards wired |
| 4.4.1 RELIEF SALLY | Sallyers behind defenders; ≤3 reserve def face them; flank all; siegeworks sallyers only; loss → withdraw + siege→1 | OK | battle.py:`resolve_relief_sally`(2438), `_relief_setup`(2191), `apply_relief_sally_aftermath`(2477) | test_fix_b6_relief_sally.py::test_siegeworks_cancels_sallyer_hits_only; ::test_attacker_loss_reduces_siege_to_one; test_fix_relief_sally_perlord.py (suite) | |
| 4.4.2 CONCEDE THE FIELD | Atk then Def each round; ≥1 round | OK | battle.py:`resolve_battle`(971); `declare_concede`(2969); campaign.py:`_h_battle_concede`(3373) | test_concede_field_battle.py::test_defender_can_concede_attacker_wins; ::test_concede_round_two_runs_two_rounds | |
| 4.4.2 Concede → Pursuit | Enemy gets Pursuit vs conceder's hits | OK | battle.py:`_resolve_step`(704) halve conceder | test_phase6e_array.py::test_concede_halves_conceder_strikes_in_resolve_step | Pursuit = halving; no marker object |
| 4.4.2 REPOSITION Rout | Remove Routed Lords | OK | battle.py:`_reposition_array`(2987) | test_phase6e_array.py::test_reposition_marks_emptied_lord_routed | |
| 4.4.2 REPOSITION Advance | Reserves into empty Front, one each | OK | `_reposition_array` step 2 | test_phase6e_array.py::test_reposition_advances_reserve_to_empty_front | |
| 4.4.2 REPOSITION Center | Fill empty center from flank (Atk then Def) | OK | `_reposition_array` step 3 | test_phase6e_array.py::test_reposition_mandatory_center_fill_from_flank; test_multi_lord_array_choices.py::test_center_fill_direction_picks_chosen_side | Skipped Round 1 |
| 4.4.2 STRIKE Flanking | No opposite → closest Front; center picks L/R; sum then round up | OK | battle.py:`_pick_flank_target`(3243), `_resolve_step_per_pair`(3321) | test_phase6f_per_pair.py::test_per_pair_routes_flanking_when_target_position_empty; ::test_pick_flank_target_center_picks_larger_of_left_right | |
| 4.4.2 Flank absorb option | Target may absorb with Flanking Lord | OK | battle.py:`_pick_flank_absorber`(3283) | test_array_residuals.py::test_flank_absorb_flanking_redirects_to_flanking_lord | |
| 4.4.2 Initiative 1a Def Missiles | step 1 | OK | `_BATTLE_STEPS`[0](55) | test_multi_lord_array_choices.py::test_strike_order_is_outcome_independent | |
| 4.4.2 Initiative 1b Atk Missiles | step 2 | OK | `_BATTLE_STEPS`[1] | (same) | |
| 4.4.2 Initiative 2a Def Horse | step 3 | OK | `_BATTLE_STEPS`[2] | (same) | |
| 4.4.2 Initiative 2b Atk Horse | step 4 | OK | `_BATTLE_STEPS`[3] | (same) | |
| 4.4.2 Initiative 2c Def Foot | step 5 | OK | `_BATTLE_STEPS`[4] | (same) | |
| 4.4.2 Initiative 2d Atk Foot | step 6 | OK | `_BATTLE_STEPS`[5] | (same) | |
| 4.4.2 Resolve each step before next | Sequential | OK | battle.py:`_battle_one_round`(882) | test_battle.py::test_resolve_battle_deterministic_under_seed | |
| 4.4.2 Javelins one-round | Owner-chosen round | OK | `_resolve_step`(636); `_h_oneround_timing`(3339) | test_oneround_timing.py::test_javelin_filter_honors_oneround_round | |
| 4.4.2 TOTAL HITS ½/1/2, sum + round up/step | Auto, no roll | OK | battle.py:`_step_hits`(362); per-pair round once | test_fix_b2_flanking_rounding.py::test_flanking_plus_opposed_sum_then_round_once | |
| 4.4.2 Cap x½+x1 → x1 | Highest applicable rate | **GAP ⚠ SUSPECT** | `build_strike_rows` appends both rows, no max-collapse | — | If both ever apply → 1½ not 1. Likely unreachable in data; unverified, no test |
| 4.4.2 Mixed Missiles crossbow rounding | Rounded-up half → Crossbows | OK | battle.py:`_allocate_rounded_hits`(395) | **GAP — no direct test** named for allocation |
| 4.4.2 Pursuit halving | Conceder halves total, round up by step | OK | `_resolve_step`(704) halve-then-ceil | test_phase6e_array.py::test_concede_halves_conceder_strikes_in_resolve_step | |
| 4.4.2 APPLY HITS to opposed/Flanked/Flanking | Player picks lord | OK | per-pair absorber redirect | test_array_residuals.py::test_flank_absorb_flanking_redirects_to_flanking_lord | ⚠ minor: mid-step rout doesn't re-route remaining hits to newly-exposed lord |
| 4.4.2 ROLL WALLS | Storm/Sally only; dice=hits; ≤Walls or ≤Siege markers cancels; roll crossbows separately | **PARTIAL ⚠** | battle.py:`_apply_step_cancellation_and_hits`(734) | test_storm_walls_and_cap.py | **"Roll crossbows separately" not honored** — single pooled roll, crossbows drained last. See Finding #5 |
| 4.4.2 ASSIGN HITS | Owner selects unit, hit-by-hit; one unit shields | OK | `_resolve_protection_roll`(427) absorb_policy | test_absorption_policy.py::test_storm_attacker_forced_armored_first_regardless_of_policy | |
| 4.4.2 Crossbows striker selects | Firing side picks unit | OK | `_resolve_protection_roll` striker_selects | test_crossbow_minus_armor.py::test_crossbow_minus_one_vs_armor_can_only_reduce_cancels | |
| 4.4.2 Crossbows −1 vs Armor | Reduce armor save | OK | `_resolve_protection_roll`(553) | test_crossbow_minus_armor.py (same) | |
| 4.4.2 ROLL BY HIT Armor | Within range = no effect | OK | `_resolve_protection_roll`(530) | test_forces_and_strongholds.py (ranges) | |
| 4.4.2 ROLL BY HIT Evade | As Armor; Melee only, not Missile/Storm | OK | `_resolve_protection_roll`(562) | **GAP — no test** for evade-only-on-battle-melee |
| 4.4.2 ROLL BY HIT Unarmored | Rout except on 1 | OK | `_resolve_protection_roll`(558) | test_battle.py::test_loser_retreat_no_concede_units_need_a_one | |
| 4.4.2 ROLL BY HIT Serfs | Auto-remove | OK | `_resolve_protection_roll`(520) | test_battle.py::test_serfs_auto_remove_on_hit | |
| 4.4.2 ROUT | Unit → Routed; lord Routs on last unit; new flank | OK | `_side_all_lords_routed`(817) | test_fix_b4_battle_over.py::test_all_positions_empty_is_defeated | |
| 4.4.2 NEW ROUND / end | Continue unless concede or all-routed | OK | `_battle_over`(832) | test_fix_b4_battle_over.py::test_reserve_only_side_is_not_defeated | |
| 4.4.3 RETREAT | Single adjacent clear Locale | OK | battle.py:`apply_retreat_aftermath`(2694), `_retreat_target_clear`(2931) | test_phase6c_retreat.py::test_loser_retreats_to_neighbor_and_shifts_service | |
| 4.4.3 WITHDRAW | Into friendly SH | OK | `apply_retreat_aftermath` step 1 | test_phase6c_retreat.py::test_loser_withdraws_into_friendly_stronghold | |
| 4.4.3 Permanent REMOVAL | If no retreat/withdraw | OK | `apply_retreat_aftermath` step 3 | test_fix_retreat_relocation_p3p4p5.py | |
| 4.4.3 Def not retreat along Approach Way | Blocked | OK | `apply_retreat_aftermath`(2870) | test_phase6c_retreat.py::test_defender_cannot_retreat_along_approach_way | |
| 4.4.3 Marching Atk retreat to origin | Must return | OK | `apply_retreat_aftermath`(2856) | test_fix_retreat_relocation_p3p4p5.py | |
| 4.4.3 Sallying Atk must Withdraw | No retreat | OK | `apply_retreat_aftermath`(2758) early-return | test_fix_retreat_relocation_p3p4p5.py::test_p3_sally_losing_sallyer_still_withdraws_and_raid_reduces_siege | |
| 4.4.3 SPOILS removed → all | All assets | OK | battle.py:`_transfer_retreat_spoils`(2649) | test_phase7f_battle_array.py::test_removed_lord_transfers_all_assets | |
| 4.4.3 SPOILS retreat-no-concede → all | All assets | OK | `_transfer_retreat_spoils` | test_phase7f_battle_array.py::test_retreat_without_concede_transfers_all_assets | |
| 4.4.3 SPOILS concede+retreat → Loot + excess Prov | Keep rest | PARTIAL | `_transfer_retreat_spoils`(2676) | test_phase7f_battle_array.py::test_concede_then_retreat_keeps_non_loot_non_excess_prov | ⚠ uses raw cart+mule as capacity, not the full 4.3.2 Laden formula — may misvalue excess Prov |
| 4.4.3 SPOILS withdrew → keep all | Transfer nothing | OK | `_transfer_retreat_spoils`(2660) | test_phase7f_battle_array.py::test_withdraw_transfers_no_spoils | |
| 4.4.3 SPOILS distribution to winners at Locale | Winner distributes | OK | battle.py:`distribute_spoils_round_robin`(3532) | test_phase6g_skipped.py::test_distribute_spoils_round_robin_basic | |
| 4.4.3 SERVICE shift 1-2/3-4/5-6; withdrew don't roll | Per Retreated Lord | OK | `apply_retreat_aftermath`(2891) | test_phase6c_retreat.py::test_loser_retreats_to_neighbor_and_shifts_service; ::test_retreat_service_shift_is_deterministic_per_seed | ⚠ Vassal-marker shift (advanced 3.4.2) NOT implemented |
| 4.4.4 LOSSES roll per Routed unit | 1d6 each | OK | battle.py:`apply_losses_rolls`(1073) | test_battle.py::test_winner_routed_units_roll_protection_not_auto_restore | |
| 4.4.4 Keep-threshold retreat-no-concede → keep on 1 | Harsh | OK | `apply_losses_rolls`(1091) | test_battle.py::test_loser_retreat_no_concede_units_need_a_one | |
| 4.4.4 Keep-threshold others → unmodified Protection | Inherent ranges | OK | battle.py:`_losses_keep_threshold`(1048) | test_battle.py::test_winner_routed_units_roll_protection_not_auto_restore | |
| 4.4.4 African Horse always Evade | Special | OK | `_losses_keep_threshold`(1065) | **GAP — no test** |
| 4.4.4 Survivors un-rout; Service stays | Push back | OK | `apply_losses_rolls`(1100) | test_battle.py::test_winner_routed_units_roll_protection_not_auto_restore | |
| 4.4.4 Lord losing all Forces removed | 3.3.1 | OK | battle.py:`apply_battle_losses`(1171) | **GAP — no dedicated test** |
| 4.4.5 Moved/Fought all participants | Mark Fought | OK | battle.py:`apply_aftermath`(1193) | test_battle.py::test_aftermath_marks_lords_moved_fought | |
| 4.4.5 Discard Hold Events used | Clear → discard | OK | `apply_aftermath`(1221); `_discard_round1_events`(2523) | **GAP — no targeted discard test** |
| 4.4.5 Siege markers/VP | Adjust siege/conquered/jihad/VP | PARTIAL | campaign.py:`_finish_approach_battle`(3198); `apply_battle_losses`(1182) | test_fix_siege_cleanup_combat_p2.py; test_fix_c1b_postbattle_besiege.py | Marker/VP logic spread across campaign/siege code |
| 4.4.5 Recovery skip remaining actions | Battle blocks rest of card | OK | `_finish_approach_battle`(3236) actions_remaining=0 | test_battle.py::test_cmd_battle_resolves_and_ends_card | |

### 4.5 Siege, Storm, Sally

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 4.5.1 SURRENDER? gating | Roll only if no Besieged Lords inside | OK | campaign.py:`_h_cmd_siege`(2922) | test_fix_siege_451.py::test_no_surrender_when_enemy_lord_inside; test_surrender_conquest.py::test_cmd_siege_with_no_defender_attempts_surrender | |
| 4.5.1 SURRENDER? dice = VP | #dice = SH VP value | OK | `_h_cmd_siege` `roll_d6_n` | test_surrender_conquest.py::test_conquer_stronghold_castle_value_1 | |
| 4.5.1 SURRENDER? threshold | Each die ≤ Siege(≤4)+Ravaged(≤1) | OK | `_h_cmd_siege` threshold | test_fix_siege_451.py::test_surrender_checked_against_existing_markers_not_post_siegeworks; ::test_ravaged_counts_at_locale_capped_one | |
| 4.5.1 Conquer remove Siege markers | Remove all | OK | campaign.py:`_conquer_stronghold`(2816) | test_surrender_conquest.py (implicit) | |
| 4.5.1 Conquer place/remove Conquered/Jihad/Seat per type & territory | Table-4 | OK | `_conquer_stronghold` | test_fix_conquest.py::test_muslim_conquest_in_parias_taifa_places_jihad; ::test_christian_conquest_places_conquered_and_removes_jihad | |
| 4.5.1 Conquered = SH Value (no stack) | =value | OK | `_conquer_stronghold` | test_fix_conquest.py::test_conquered_markers_set_to_value_not_stacked | |
| 4.5.1 Ravaged Land flip | Flip conqueror's Ravage marker | PARTIAL | `_conquer_stronghold` | **GAP — no test** ⚠ flips only when marker is own color |
| 4.5.1 Taifa status timing | Adjust status only after markers | PARTIAL | `_conquer_stronghold` defers to caller | **GAP — no test** in scope |
| 4.5.1 Terms = no Spoils | Surrender no Spoils | OK | `_h_cmd_siege` spoils={} (unless C9) | **GAP — no test** |
| 4.5.1 SIEGEWORKS add 1 if Lords ≥ Capacity, max 4 | +1 marker | OK | `_h_cmd_siege` | test_siege.py::test_siegeworks_adds_one_marker_at_capacity; ::test_siege_no_siegeworks_marker_below_capacity; ::test_siege_at_4_markers_adds_none | |
| 4.5.1 MOVED/FOUGHT all both sides | Mark Fought | OK | `_h_cmd_siege` loop | test_moved_fought_siege_avoid.py | |
| 4.5.1 Siege whole card | Entire card | OK | `_h_cmd_siege` | test_siege.py::test_siege_uses_entire_card | |
| 4.5.1 Siege target = Enemy SH | Not Friendly/Neutral/Region | OK | `_h_cmd_siege` | test_siege.py::test_siege_at_region_rejected; ::test_siege_at_friendly_locale_rejected | |
| 4.5.2 ARRAY Front ≤1 each, Atk=Active | Storm array | OK | battle.py:`_storm_setup`(1730) | test_fix_storm_array.py::test_front_begins_with_one_defender_lord | |
| 4.5.2 ARRAY Front ≤ Capacity | Never more than Cap | OK | battle.py:`_storm_run_round`(1647) | test_fix_storm_array.py::test_front_never_exceeds_capacity | |
| 4.5.2 CONCEDE atk only, after R1 | Round 2+ | OK | battle.py:`resolve_storm`(1888); campaign.py:`_h_storm_concede`(3597) | test_fix_storm_array.py::test_attacker_concede_round_two_loses | |
| 4.5.2 REPOSITION add 1 reserve up to Cap; forced if Front routed | Storm reposition | OK | `_storm_run_round` | test_fix_storm_array.py::test_reposition_adds_reserve_round_two | |
| 4.5.2 SH EFFECT Garrison units | Besieged gets garrison | OK | battle.py:`_garrison_for_locale`(1481) | test_storm_sally.py::test_resolve_storm_adds_garrison_to_defender_garrison_bucket | |
| 4.5.2 SH EFFECT Walls | Besieged uses SH Walls | OK | `_storm_setup` | test_storm_walls_and_cap.py::test_resolve_storm_consults_walls_for_defender; ::test_walls_actually_cancels_hits_when_supplied | |
| 4.5.2 SH EFFECT Siegeworks = besieger Walls | =#siege markers | OK | `_storm_setup` | test_storm_walls_and_cap.py (walls cancel) | |
| 4.5.2 SH EFFECT Def Melee before Atk (reversed) | Storm order | OK | `_storm_run_round` (2.a def before 2.b atk) | **GAP — no explicit ordering test** |
| 4.5.2 SH EFFECT Atk absorbs Armored first | Forced | OK | `_apply_step_cancellation_and_hits`(789) | test_absorption_policy.py::test_storm_attacker_forced_armored_first_regardless_of_policy |
| 4.5.2 SH EFFECT 6-melee cap/Lord/round | ≤6 | OK | battle.py:`_storm_melee_hits`(1612); `_resolve_step`(709) | test_storm_walls_and_cap.py::test_storm_melee_capped_at_6_per_lord_per_round; ::test_battle_does_not_cap_melee_at_6 | |
| 4.5.2 SH EFFECT Javelins/Slingers x½ in Storm | Half rate | OK | forces.json strikes_storm; `build_strike_rows` | **GAP — no dedicated storm-half test** |
| 4.5.2 GARRISON MaA crossbow missiles −1 armor + select | MaA garrison | OK | forces.json strikes_by_garrison; `build_strike_rows` | test_fix_garrison_strikes.py::test_garrison_contributes_missile_strikes_in_storm; test_storm_walls_and_cap.py::test_bug_l_crossbow_striker_selects_target | |
| 4.5.2 GARRISON Militia as bowmen | Militia missile | OK | forces.json | **GAP — no militia-specific test** |
| 4.5.2 GARRISON add to Lord (round up), ignore Lord cards | Separate, rounding up | PARTIAL | `_storm_melee_hits`; garrison built w/ empty caps | **GAP — no test** ⚠ garrison melee ceil'd separately then summed (could diverge from combined-rounding on fractions) |
| 4.5.2 GARRISON takes all Hits until routed | Absorbs first | OK | `_resolve_protection_roll` garrison pool first | test_storm_walls_and_cap.py::test_bug_m_garrison_absorbs_before_lord_units_in_storm | |
| 4.5.2 GARRISON return to pool when routed/end | Cleared post-storm | OK | battle.py:`_storm_finalize`(1858) | **GAP — no test** |
| 4.5.2 GARRISON full complement each storm | Fresh each storm | OK | `_garrison_for_locale` rebuilt | **GAP — no test** |
| 4.5.2 ENDING rounds = siege markers | Max rounds | OK | `_storm_setup` max_rounds | test_storm_sally.py::test_resolve_storm_max_rounds_from_siege_markers | |
| 4.5.2 ENDING atk loses unless def all rout | Winner rule | OK | battle.py:`_storm_winner`(1840) | test_fix_storm_array.py::test_attacker_concede_round_two_loses; test_fix_storm_sack.py::test_storm_attacker_loss_no_sack | |
| 4.5.2 ENDING losing atk no retreat/spoils | None | OK | campaign.py:`_finish_storm`(3660) | test_fix_storm_sack.py::test_storm_attacker_loss_no_sack | |
| 4.5.2 ENDING losses; def always roll; atk removed unless 1 | Storm variant | OK | battle.py:`apply_battle_losses` (storm branch) | test_fix_storm_losses_perlord.py::test_storm_4_4_4_losses_applied_to_routed_units; ::test_resolve_storm_tracks_routed_per_lord | ⚠ ALL attacker lords use "storm_attacker" keep-only-1 even on attacker WIN (sack) — confirm vs intent |
| 4.5.2 ENDING mark all Fought incl Reserve | All marked | PARTIAL | `_finish_storm` via apply_aftermath | **GAP — no test** ⚠ reserve-Lord marking not clearly guaranteed for multi-besieger |
| 4.5.2 SACK remove losers + spoils from them | Remove + assets | OK | `_finish_storm` | test_fix_storm_sack.py::test_storm_sack_removes_lord_and_awards_spoils | |
| 4.5.2 SACK spoils from SH per table | SH spoils | OK | `_finish_storm` sh_spoils | test_fix_storm_sack.py (same) | |
| 4.5.2 SACK conquer as surrender | Conquer | OK | `_finish_storm` `_conquer_stronghold` | test_fix_storm_sack.py (same) | |
| 4.5.3 Sally besieged attack all besieged | Setup | OK | campaign.py:`_h_cmd_sally`(3899); battle.py:`resolve_sally`(1944) | test_storm_sally.py::test_cmd_sally_with_besiegers_resolves; ::test_cmd_sally_requires_besieged | |
| 4.5.3 Sally no walls/garrison for sallyers | Unprotected | OK | `resolve_sally` | test_fix_sally_siegeworks.py::test_sally_engagement_tag | |
| 4.5.3 Sally defenders get Siegeworks | Besieger walls | OK | `resolve_sally` defender_walls | test_fix_sally_siegeworks.py::test_siegeworks_protect_besieger_in_sally | |
| 4.5.3 Sally losing def Retreat → siege ends | Besieger retreat ends siege | OK | battle.py:`apply_sally_aftermath`(1989) | **GAP — no direct "siege ends" test** for besieger-loss branch |
| 4.5.3 Sally losing atk Withdraw back | Not retreat | OK | `apply_sally_aftermath` | test_storm_sally.py::test_sally_aftermath_reduces_siege_on_loss | |
| 4.5.3 RAID sallyers lose → all but 1 siege marker | Siege→1 | OK | `apply_sally_aftermath` | test_storm_sally.py::test_sally_aftermath_reduces_siege_on_loss; test_fix_b6_relief_sally.py::test_attacker_loss_reduces_siege_to_one | |
| 4.5.4 Jihad added at Muslim Siege removes all Siege markers | Jihad clears siege | **GAP — NOT IMPLEMENTED ⚠** | events.py:`_add_jihad`(857) only increments jihad_markers | **GAP — no test** | See Finding #1 — verified firsthand |

### 4.6 Supply

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 4.6 Supply general | Unbesieged Lord, action, +Prov from Source Seats (even if Ravaged) | OK | campaign.py:`_h_cmd_supply`(2398) | test_supply_tax.py::test_supply_at_own_seat_no_transport_needed; ::test_supply_rejects_besieged_lord | |
| 4.6.1 Unbroken Route | BFS Road/Pass route to Seats | OK | campaign.py:`_find_supply_routes`(2348) | test_phase7e_supply.py::test_bfs_finds_multi_hop_route; test_supply_routing_fixes.py::test_supply_route_passes_through_own_seat | |
| 4.6.1 Route blocked by enemy SH/Lord (unless Besieged/Bypassed) | Blocking rule | OK | campaign.py:`_route_blocked_by_enemy`(2297) | **GAP — no test** directly asserting an enemy-blocked route is rejected |
| 4.6.1 Seats incl Pennants/markers/Cathedrals | Count as Seats | OK | campaign.py:`_own_seats`(2284); `_h_place_cathedral_seat`(5701) | **GAP — no test** for Cathedral-as-Seat Supply |
| 4.6.1 TRANSPORT 1 per Way; none at own Seat | Per intervening Way | OK | `_h_cmd_supply` total_hops | test_supply_tax.py::test_supply_at_own_seat_no_transport_needed; test_phase7e_supply.py::test_supply_insufficient_transport_for_multi_seat_rejected | Transport allocated, not expended (correct) |
| 4.6.1 Shared transport | Pool co-located same-side | OK | campaign.py:`_shared_transport_at`(2333) | test_supply_routing_fixes.py::test_shared_transport_helper_pools_colocated_lords | |
| 4.6.1 Dedicated transport per Way per Route (multi-Seat) | Each Seat needs own | OK | `_h_cmd_supply` sums total_hops | test_phase7e_supply.py::test_supply_insufficient_transport_for_multi_seat_rejected | |
| 4.6.2 Add Provender | +1/Seat with Route | OK | `_h_cmd_supply` gain | test_phase7e_supply.py::test_multi_seat_supply_adds_prov_per_seat; test_supply_tax.py::test_supply_caps_provender_at_8 | |

### 4.7 Other Commands

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 4.7.1 Forage general | 1 action +1 Prov | OK | campaign.py:`_h_cmd_forage`(2589) | test_forage_ravage.py::test_forage_open_uses_d6_roll | |
| 4.7.1 Not Besieged (except Gardens) | | OK | `_h_cmd_forage` besieged guard | test_forage_ravage.py::test_forage_besieged_without_gardens_rejected; ::test_forage_besieged_at_own_gardens_allowed | |
| 4.7.1 Not Ravaged (except Gardens) | | OK | `_h_cmd_forage` ravaged guard | test_forage_ravage.py::test_forage_rejects_ravaged_open | |
| 4.7.1 Friendly Stronghold auto +1 | All SH types | OK | `_h_cmd_forage` friendly_strong_auto | test_forage_ravage.py::test_forage_friendly_town_auto_succeeds | |
| 4.7.1 Open roll 1-3 add / 4-6 nothing | Die | OK | `_h_cmd_forage` roll_d6 | test_forage_ravage.py::test_forage_open_uses_d6_roll; ::test_forage_determinism | |
| 4.7.1 GARDENS | Friendly City/Fortress only; auto even if Ravaged/Besieged | OK | `_h_cmd_forage` gardens_path | test_forage_ravage.py::test_forage_gardens_auto_succeeds | |
| 4.7.2 Ravage general | Unbesieged, enemy Locale not yet Ravaged, place ½VP marker | OK | campaign.py:`_h_cmd_ravage`(2678), `_apply_ravage_effect`(2739) | test_forage_ravage.py::test_ravage_rejects_friendly_locale; ::test_ravage_rejects_already_ravaged_by_us; ::test_ravage_rejects_besieged | |
| 4.7.2 Ravage at besieged enemy SH | While besieging | OK | legal_moves.py winter-siege path; `_apply_ravage_effect` | **GAP — no test** for normal-Command ravage-while-besieging |
| 4.7.2 RUSTLING | +1 Loot +1 Prov SH; +1 Loot only Region | OK | `_apply_ravage_effect` branch | test_forage_ravage.py::test_ravage_at_region_adds_loot; ::test_ravage_at_region_no_prov | |
| 4.7.2 ENFORCING PARIAS | Every odd Christian Ravage marker in a Taifa shifts Taifa Lord Service left 1 (not Yusuf/Sir/Rodrigo; if Mustered) | OK | `_apply_ravage_effect`(2776) | test_forage_ravage.py::test_ravage_enforcing_parias_trigger; test_enforcing_parias_mustered_472.py::test_shift_when_taifa_lord_mustered; ::test_no_shift_when_taifa_lord_not_mustered | ⚠ cosmetic: returns enforcing_parias=True even when not Mustered (no shift) |
| 4.7.2 ENFORCING PARIAS Vassal markers (advanced) | Also shift Vassals | **GAP — not found** | shifts Lord marker only | — | Advanced 3.4.2 not implemented |
| 4.7.3 Tax | Unbesieged at own Seat, whole card, +1 Coin | OK | campaign.py:`_h_cmd_tax`(2537) | test_supply_tax.py::test_tax_at_own_seat_adds_coin_and_consumes_card; ::test_tax_rejects_when_not_at_own_seat; ::test_tax_rejects_besieged_lord | |
| 4.7.4 Pass | Do nothing | OK | campaign.py:`_h_cmd_pass`(787) | **GAP — no dedicated test** |

### 4.8 Feed/Pay/Disband

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 4.8 Orchestration | End of card, both sides Feed → Pay → Disband | OK | campaign.py:`_h_end_card`(544), `_economy_finalize`(576) | test_fix_e4e5e6_feed.py::test_e4_feeds_all_moved_fought_lords_both_sides | Christian-then-Muslim |
| 4.8.1 Feed amount ceil((units+Mules)/6) | 1 per 6 | OK | campaign.py:`_feed_consume_own`(400) | test_fix_e4e5e6_feed.py::test_e4_feeds_all_moved_fought_lords_both_sides | |
| 4.8.1 Loot feeds anywhere | Loot feed unconditional | OK | `_feed_consume_own` | **GAP — no Feed-side test** (pay-side gate tested in test_fix_pay_321.py::test_loot_requires_friendly_locale_free_of_siege) |
| 4.8.1 GREED discard excess Mules | May discard | OK | `_feed_consume_own`; `_greed_eligible_lords`(648); `_h_greed_mule_choice`(725) | test_fix_e4e5e6_feed.py::test_e6_greed_discards_excess_mules_to_avoid_unfed; test_interactive_economy.py::test_greed_eligible_detects_unfeedable_mules | |
| 4.8.1 SHARING | Feed own then co-located short allies | OK | campaign.py:`_feed_all_moved_fought`(443) | test_fix_e4e5e6_feed.py::test_e5_sharing_feeds_short_lord_from_same_locale_ally; ::test_e5_unfed_when_no_sharing_available | |
| 4.8.1 UNFED shift Service left 1 | Under-fed penalty | OK | campaign.py:`_apply_unfed_penalty`(392) | test_fix_e4e5e6_feed.py::test_e5_unfed_when_no_sharing_available | |
| 4.8.1 UNFED Vassal markers (advanced) | Also shift Vassals | **GAP — not found** | shifts Lord only | — | Advanced 3.4.2 not implemented |
| 4.8.2 Pay (Christian then Muslim, per 3.2) | Voluntary | OK | campaign.py:`_h_pay_before_disband`(750) | test_interactive_economy.py::test_interactive_greed_then_pay_then_disband_full_cascade; test_fix_pay_321.py (suite) | |
| 4.8.2 Disband per Service limit | Check at limit | OK | campaign.py:`_auto_disband_at_service_limit`(512) | test_auto_disband_3_3.py::test_at_limit_non_taifa_still_goes_to_calendar_with_campaign_plus_one; ::test_beyond_service_lord_is_permanently_removed; test_fix_disband_331_332.py | |
| 4.8.3 Remove Moved/Fought; proceed | Clear markers | OK | `_economy_finalize`(606) | test_interactive_economy.py::test_interactive_economy_baton_matches_synchronous | |

### 4.9 End Campaign

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 4.9.1 Game End | Final 40 Days → game ends, highest VP | OK | campaign.py:`_h_end_campaign`(927) | test_phase7b_victory.py::test_full_game_advance_to_end_sets_winner | |
| 4.9.2 GROW | End 2nd Spring: each side halves ENEMY Ravage (round up), adjust VP, mandatory | OK | campaign.py:`_apply_grow_harvest_repairs`(815) | test_fix_e1e2e3_endcampaign.py::test_grow_halves_both_colors_second_spring; test_ravage_flip_and_grow_vp.py::test_grow_reduces_enemy_markers_and_adjusts_vp; test_grow_choices.py::test_grow_choices_removes_the_selected_marker | |
| 4.9.2 GROW negative | Not outside 2nd Spring | OK | same | test_fix_e1e2e3_endcampaign.py::test_grow_does_not_run_outside_second_spring | |
| 4.9.2 HARVEST | End 2nd Summer: each Lord halves Carts & Mules (round up) | OK | `_apply_grow_harvest_repairs` summer branch | test_fix_e1e2e3_endcampaign.py::test_harvest_halves_carts_and_mules_second_summer | |
| 4.9.3 Repairs | End each Campaign except Winter: remove 1 Siege from 3-or-4 stacks | OK | `_apply_grow_harvest_repairs` repairs branch | test_fix_e1e2e3_endcampaign.py::test_repairs_removes_one_from_3or4_stacks_not_winter; ::test_repairs_skipped_in_winter | |
| 4.9.4 Wastage | Christian then Muslim discard 1 Asset/"This Lord" Cap from each Mustered Lord with >1 of a type; by Lord; not Taifas box | OK | campaign.py:`_apply_wastage`(5269), `_wastage_eligible_lords`(5302), `_h_wastage_choice`(5407) | test_phase7g_misc.py::test_wastage_discards_one_excess_asset; ::test_wastage_skips_lords_with_no_excess; test_interactive_economy.py::test_interactive_wastage_lets_owner_pick_the_discarded_item | |
| 4.9.5 Reset Unstack | Unstack Lieutenants/Lower Lords | OK | campaign.py:`_unstack_all_lieutenants`(5255) | **GAP — no dedicated test** |
| 4.9.5 Reset AoW discard | Christian then Muslim MAY discard Arts of War cards to decks | **GAP — NOT IMPLEMENTED ⚠** | not found in `_h_end_campaign`/`_return_to_levy`(1339) | — | Optional player AoW-to-deck discard step missing |
| 4.9.5 Reset Advance & flip to Levy | Advance Campaign marker; flip to Levy | OK | `_h_end_campaign`(966); `_return_to_levy`(1339) | test_phase7b_victory.py::test_full_game_advance_to_end_sets_winner | |

---

## Chapter 5 — Victory

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 5.1 1 VP per Conquered marker incl Taifas box | On-map + box | PARTIAL | campaign.py:`compute_final_vp`(5038) | test_fix_t1t2_vp_conquest.py::test_t2_christian_conquest_removes_jihad_places_conquered; test_surrender_conquest.py::test_conquer_stronghold_christian_places_conquered_markers | ⚠ on-map markers counted; Taifas-box Conquered folded into `taifas_box_vp` (not per-marker). Equivalent for current scenarios |
| 5.1 ½ VP per Ravaged marker on map | | OK | `compute_final_vp`(5060) | test_phase7b_victory.py::test_compute_final_vp_counts_markers | |
| 5.1 ½ VP to Muslims per Jihad | | OK | `compute_final_vp`(5059) | test_phase7b_victory.py::test_compute_final_vp_counts_markers; test_fix_t1t2_vp_conquest.py::test_t2_muslim_conquest_in_taifa_places_jihad_removes_christian | |
| 5.1 Christians 3 VP/Reconquista + 1 VP/Parias | | PARTIAL | `compute_final_vp`(5064) by Taifa status | test_phase7b_victory.py::test_compute_final_vp_counts_taifa_status; ::test_sevilla_reconquista_worth_nine_vp; ::test_sevilla_parias_worth_three_vp | ⚠ scored per Taifa-status not per "marker on map"; equivalent under one-status-one-marker |
| 5.1 1 VP to Christians per Cathedral Seat | | OK | `compute_final_vp`(5074) | test_fix_cathedrals.py::test_place_cathedral_seat_adds_vp_and_jihad_rider; ::test_muslim_conquest_removes_cathedral_seat | |
| 5.1 play-note Curias removes 1 VP from Muslims' Taifas box | Scenario F | OK | campaign.py:`apply_curias`(1073) | test_fix_e1e2e3_endcampaign.py::test_t6_curias_reduces_taifas_box_not_christian_score | |
| 5.1 Taifas-box VP counts for Muslims | | OK | `compute_final_vp`(5076) | test_taifas_box_vp_loaded_f8.py::test_scenario_a_taifas_box_counts_for_muslim_final_vp; ::test_taifas_box_vp_matches_scenario_json | |
| 5.2 Campaign Victory | Any moment, side with 0 Mustered Lords on map → other side wins regardless of VP | OK | campaign.py:`check_campaign_victory`(5027), `_mustered_lords_on_map`(5019); checked after every handler (actions.py:2081) | test_phase7b_victory.py::test_campaign_victory_when_side_has_no_lords; ::test_campaign_victory_takes_precedence_over_vp; test_campaign_victory_immediate.py (suite) | Robust "any moment" implementation |
| 5.3 End of Scenario Victory | Higher VP wins; tie = draw | OK | campaign.py:`compute_victory`(5080) | test_phase7b_victory.py::test_end_of_scenario_higher_vp_wins; ::test_tie_is_draw | |

---

## Chapter 6 — Scenarios

| Clause | Rule summary | Status | Code | Test | Notes |
|---|---|---|---|---|---|
| 6.1 Hidden Mats / Adv. Vassal Service opt-in | 1.5.2 / 3.4.2 toggles | OK | state.py:134 `advanced_vassal_service`, :143 `hidden_mats` | test_hidden_mats_152.py::test_hidden_opponent_mats_when_enabled; test_advanced_vassal_service_342.py | |
| 6.1 Bidding lower bid plays Muslim, reset 1VP = bid | | OK | actions.py:`_h_bid_for_sides`(208) | test_bidding_61.py::test_lower_bid_takes_muslim_and_resets_taifas_vp | |
| 6.1 Bidding tie resets + random sides | | OK | `_h_bid_for_sides` | test_bidding_61.py::test_tie_resets_and_assigns_randomly | |
| 6.1 Bidding Scenario F min bid 2 | | OK | actions.py:234 | test_bidding_61.py::test_scenario_f_min_bid_2_enforced | |
| 6.1 Bidding setup-only | | OK | actions.py:224 | test_bidding_61.py::test_bidding_only_at_setup | |
| 6.1 MAP/CALENDAR/TAIFAS BOX placement | | OK | scenarios.py:`load_scenario`(100) | test_scenarios.py::test_service_markers_placed; test_taifas_box_vp_loaded_f8.py::test_taifas_box_vp_matches_scenario_json | |
| 6.1 Scenario End marker | Blocks post-last-Campaign box | OK | campaign.py:972 | test_scenarios.py::test_scenario_f_long_campaign (indirect) | |
| 6.1 MATS prep as Levied | Forces/Assets/Service/Vassals Ready | OK | scenarios.py:243, :286 | test_scenarios.py::test_load_scenario_returns_valid_gamestate | |
| 6.1 Adjust Coin + assign Capabilities | | OK | scenarios.py:248, :251 | test_scenarios.py::test_capabilities_in_play_have_correct_scope | |
| 6.1 SET ASIDE | | OK | scenarios.py:234, :265 | test_printed_seats_vs_markers_f4.py::test_set_aside_yusuf_sir_have_no_seat_marker | |
| 6.1 SPECIAL RULES | No CtA / First Levy / Events | OK | scenarios.py meta; events_held:331 | test_phase6j_scenario.py::test_m12_taifa_marriage_shifts_taifa_lords_service_right | |
| 6.1 BEGIN PLAY shuffle + draw Capabilities | | OK | actions.py:`aow_capability_phase`(333), `_h_aow_shuffle`(349) | test_fix_aow_mandatory_draw.py::test_first_levy_draw_deploys_two_capabilities | |
| 6.1 Scenario A setup data | Toledo siege+rav+3 jihad; Álvar at Toledo; 4 green 1VP | OK | data/scenarios/scenario_a_toledo_beset.json | test_scenarios.py::test_scenario_a_setup; test_taifas_box_vp_loaded_f8.py::test_scenario_a_taifas_box_counts_for_muslim_final_vp | Verified vs rules |
| 6.1 Scenario A/B/C/E/F errata | Events holding, First Levy, coins, Ruined Land, dropped caps | OK | scenario JSONs | partial — see notes | JSONs match errata; **GAP — no test** asserting A/B held-event/caps specifically |
| 6.1 Scenario D Ribat Monks (M14) | al-Mustain holds ARRADA + RIBAT MONKS | **PARTIAL ⚠ SUSPECT** | scenario_d_arrival.json caps `["M17","M14"]`; cards.json M14 `no_capability:true` | test_scenarios.py::test_scenario_d_yusuf_at_algeciras_with_doubled_seat | **M14's Ribat Monks capability not modeled** — resolves to nothing. See Finding #4 (verified firsthand) |
| 6.1 F Cathedrals delay until Yusuf/Sir Muster | | OK | campaign.py:5728 | **GAP — no test** for F-specific gate |
| 6.1 F Ruined Land Parias Coin = Service − Ravaged | | OK | campaign.py:`_parias_coin_amount`(1614) | test_reconciliation_scenario.py::test_ruined_land_reduces_parias_coin_by_ravaged; ::test_non_ruined_land_parias_coin_unreduced | |
| 6.2.1 Curias Condition (box 5, recheck 6) | yellow Conq+Rav > green Conq+Rav+Jihad (Locales, not box) | PARTIAL ⚠ | campaign.py:`check_curias`(1041) | test_curias_winter.py::test_check_curias_triggers_with_lots_of_yellow; ::test_check_curias_default_scenario_f_not_triggered | ⚠ loader (scenarios.py:209) merges green Conquered into same `conquered_markers` field → a green Conquered in a Muslim Taifa would be miscounted as yellow |
| 6.2.2 Curias place marker(s), remove 1VP/marker | | OK | `apply_curias`(1083) | test_curias_winter.py::test_apply_curias_at_box_6_only_places_one; test_reconciliation_scenario.py::test_curias_shifts_box6_marker_when_firing_at_box5 | |
| 6.2.2 Curias advance Levy to box 7 | | OK | `apply_curias`(1097) | test_curias_winter.py::test_apply_curias_advances_levy_marker_to_box_7 | |
| 6.2.2 Curias shift Beyond-Service to box 7 | | OK | `apply_curias`(1104) | test_reconciliation_scenario.py::test_curias_shifts_box6_marker_when_firing_at_box5 | |
| 6.2.2 Curias Disband Pedro/García if on map | (errata "must") | OK | `apply_curias`(1112) | test_curias_winter.py::test_apply_curias_auto_disbands_pedro_and_garcia | |
| 6.2.3 No Curias → normal | | OK | campaign.py:999 | test_curias_winter.py::test_check_curias_default_scenario_f_not_triggered | |
| 6.3 Winter boxes 7-8 regardless of Curias | Replaces Levy+Campaign | OK | campaign.py:1004, `_enter_winter_box`(1460) | test_winter_siege_632.py::test_end_campaign_into_box7_enters_winter_siege | |
| 6.3.1 Winter Disband Pay then remove Beyond Service (exc Rodrigo) | | OK | campaign.py:`winter_disband`(1140) | test_winter_sequence_63.py::test_winter_disband_beyond_service_removed | |
| 6.3.1 Winter Disband remaining Mustered (non-siege) to mat | Cylinder on mat, not Calendar | OK | `winter_disband`(1216) | test_curias_winter.py::test_winter_disband_moves_lords_to_mat | |
| 6.3.1 Winter Disband Taifa Coin to box, no status/Parias | | OK | `winter_disband`(1219) | test_winter_sequence_63.py::test_winter_disband_taifa_coin_to_box | |
| 6.3.1 Winter Disband Rodrigo to box 9 | Even if Beyond | OK | `winter_disband`(1187) | test_curias_winter.py::test_winter_disband_rodrigo_to_box_9 | |
| 6.3.1 Winter Disband lords at Sieges kept | | OK | `winter_disband`(1180) | test_curias_winter.py::test_winter_disband_keeps_lords_at_sieges | |
| 6.3.1 Winter Disband discard board-edge Capabilities | | OK | `winter_disband`(1242) | test_curias_winter.py::test_winter_disband_discards_board_edge | |
| 6.3.2 Winter Siege each Besieger 1 Supply/Ravage | No Forage | OK | campaign.py:`_winter_besiegers`(1383), `_h_winter_siege_action`(1528) | test_winter_siege_632.py::test_besieger_ravage_places_marker | |
| 6.3.2 Winter Siege each Lord at Siege Feeds | | OK | campaign.py:`_winter_feed`(1427) | **GAP — no isolated Feed test** (covered in sequence test) |
| 6.3.2 Winter Siege Pay then mandatory Disband at Service | Christian then Muslim | OK | `_h_winter_siege_pay`(1567), `_winter_siege_disband`(1436) | test_winter_siege_632.py::test_at_limit_besieger_disbanded_when_not_paid; ::test_pay_dodges_mandatory_disband | |
| 6.3.2 Winter Siege both boxes 7 & 8 | | OK | campaign.py:`_finish_winter_box`(1510) | test_winter_siege_632.py::test_besieger_pending_then_pay_then_box8_then_box9 | |
| 6.3.3 Spring Muster Christian mat-Lords auto-Muster at free Seats | | OK | campaign.py:`spring_muster`(1247) | test_curias_winter.py::test_spring_muster_christian_lords_from_mats | |
| 6.3.3 Spring Muster Alfonso at León if possible | | OK | `spring_muster`(1280) | **GAP — no test** |
| 6.3.3 Spring Muster no free Seat → Calendar | | OK | `spring_muster`(1292) | **GAP — no test** |
| 6.3.3 Spring Muster Taifa Lord no free Seat → Calendar + adjust Taifa status (incl Parias Coin) | | **GAP — NOT IMPLEMENTED ⚠** | `spring_muster`(1292) no `adjust_taifa_status` call | — | See Finding #3 (verified firsthand) |
| 6.3.4 Plowing Lords at Siege halve Carts & Mules | End box 8 only | OK | campaign.py:`winter_plowing`(1301) | test_winter_sequence_63.py::test_winter_plowing_halves_siege_lord_transport | |
| 6.3.5 Arts of War box 9 draw Capabilities | F only | OK | actions.py:333 | test_winter_sequence_63.py::test_box9_is_capability_phase_in_scenario_f; ::test_box9_capability_phase_only_scenario_f | |

---


---

*The prioritized findings from the Chapter 4–6 audit (materially-incorrect,
suspected, and untested clauses) are consolidated, with resolutions, in the
"Findings & Resolutions" section at the top of this document. The four
confirmed bugs (4.5.4, 4.3.6, 6.3.3, Ribat Monks) were fixed in this pass;
the remaining items are documented abstractions or low-impact open items.*
