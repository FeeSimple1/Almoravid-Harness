# Action Catalog

Every state mutation goes through `apply_action(state, action)` in
`almoravid.actions`. The `action` is a JSON-serializable dict with a
`type` field naming the handler and additional fields as required.

`legal_moves(state)` enumerates the actions currently legal for the
active player. Per Pattern 1 (state-set-but-unreachable), any new
handler in `actions.py` must add a corresponding enumerator in
`legal_moves.py` in the same PR.

## CLI state-file flow

States are persisted to JSON files via Pydantic round-trip. Actions
are also JSON files. The typical flow is:

```
$ almoravid new scenario_a_toledo_beset -o game.json --seed 1
$ almoravid state game.json
Scenario A (toledo_beset)  box 1 spring  phase=setup  active=christian  VP=C5/M8

$ almoravid legal game.json
{"type": "begin_levy"}

$ echo '{"type": "begin_levy"}' > a.json
$ almoravid do game.json a.json
OK: {"levy_step": "arts_of_war", "phase": "levy"}

$ almoravid view game.json --mode summary
[render output]

$ almoravid history game.json --tail 5
T0 system  load_scenario: Loaded scenario A: Toledo Beset, Spring 1085
T0 christian  begin_levy: Begin Levy phase (3.1 arts_of_war)
```

`do` overwrites `game.json` by default; use `--output game2.json` to
branch the state. Exit codes: 0 success, 1 usage error, 2 IllegalAction
(or malformed action JSON) — agents should branch on exit code 2 to
re-pick from the legal-moves palette.

## Alférez

The active Lord with C15 may spend one Command action to become the
Lieutenant of an eligible Lord at the same Locale. Use
`toggle_lieutenant` with `mode: "stack"` and `lower_lord_id`, or
`mode: "unstack"` to dissolve the active Lord's stack.

## Relief Sally

When a defender Stands & Fights against an Approach to a Locale with
Besieged Lords of the Approaching side, that side gets a `relief_sally`
decision. Choose any subset of the eligible Lords. Use an empty list
to fight a regular Approach Battle and leave all of them inside.

```json
{"type": "relief_sally", "side": "christian", "lord_ids": ["alvar_fanez"]}
```

This choice comes before combat Holds and before dice are rolled.
It works with both synchronous and interactive combat and can be
saved and reloaded.

## Combat Holds

Battle, Stand & Fight, Sally, Storm, and Sagrajas resolution open a
`combat_holds` decision when either side has Held cards. The attacker chooses first, followed
by the defender. Each owner may play any subset of applicable combat
Events, one card per action, and then finish by omitting `card_id`.
Unchosen cards stay Held. Follow `pending.waiting_on` or `legal_moves`
after each response. The defender can inspect the attacker's played
Events before choosing.

```json
{"type": "combat_holds", "side": "christian", "card_id": "C8", "lord_id": "alfonso"}
```

In Battle, Sally, Storm, and Relief Sally, the Cantador menu specifies a
participating Christian Lord with `lord_id`. Up to four of that Lord's
Knights and Sergeants gain one Melee Hit each in Round 1. In Storm the
bonus applies when the selected holder Strikes at Front. Older calls
that omit `lord_id` use the resolver's automatic holder selection.

Playing M7 Spear Wall requires `lord_ids` with two distinct Muslim
Lords participating in the Battle, or the sole Lord if only one is
participating. The menu offers each legal selection. The choice stays
with those Lords through save/load and is separate from the Round
when the bonus applies.

```json
{"type": "combat_holds", "side": "muslim", "card_id": "M7", "lord_ids": ["al_mundir", "al_mustain"]}
```

```json
{"type": "combat_holds", "side": "christian"}
```

Combat resumes after both owners finish. Dice and combat effects wait
for those decisions. The window supports save/load and keeps unplayed
opponent cards hidden. Scripted callers also answer this decision.
Direct combat-resolver callers can explicitly activate a Held Event
with `almoravid.battle.play_combat_hold` before resolving combat.

## Initial Storm Front

After combat Holds, a Storm with multiple besieged Lords pauses for the
defender's `storm_front` choice before any combat dice. The menu lists
every besieged Lord. The selected Lord begins at Front and the others
begin in Reserve. This choice works with synchronous and interactive
Storms and survives save/load.

```json
{"type": "storm_front", "side": "muslim", "lord_id": "al_mutamid"}
```

## Interactive Concede the Field

Set `interactive_concede: true` on `cmd_battle`, `cmd_sally`, or
`respond_stand_battle` to make Concede decisions one round at a time.
The attacker answers first. To pass, submit the action with its type
and side only. To Concede, add `attacker_concede: true`. If the attacker
passes, the defender may pass or submit `defender_concede: true`.
Use `battle_concede` for Battle and Sally and `relief_concede` for Relief
Sally. Follow the pending side or the legal menu after each response.

A concession resolves the current round with Pursuit and ends the
engagement. If both sides pass, the round resolves normally and the
attacker answers first again if combat continues. The synchronous
`*_concede_round` arguments are for referee-controlled play and replays.

For a Relief Sally, Stand & Fight also offers `interactive_concede` and
`interactive_timing` together. Before Round 1, each side with Javelins
gets an `oneround_timing` choice for its eligible Lords. `javelin_round`
sets a shared default of Round 1 when omitted. `javelin_rounds` overrides
the default by Lord. Use a positive round number or `null` to decline.
The chosen timing persists through save and reload.

```json
{"type": "oneround_timing", "side": "muslim", "javelin_rounds": {"al_mutamid": 1, "al_mundir": 2}}
```

## Choosing losing Lords' fates

Battle and Sally actions in the legal menu request `interactive_retreat`.
Set it to `true` when constructing a Battle, Stand, or Sally action by
hand. It works with either synchronous combat or `interactive_concede`.

When a choice is owed, `battle_fate` names the losing side, Lord, and
fate. A Retreat includes `retreat_to` and `retreat_way`. The player can
choose Lords in any order. The menu updates as Stronghold slots are
assigned. Once the last choice is made, the engine applies all fates,
Losses, Spoils, and Service and resumes the Command sequence.
Mandatory fates resolve automatically.

If co-retreating Lords Conceded and surviving shared Transport cannot
carry all their Provender, the losing player chooses how much each
eligible Lord keeps. The `retreat_provender` menu gives the legal
`amount` values for the named `lord_id`. Once only one mat remains on
that route, the engine assigns it the remaining capacity. Captured
Provender joins the winner's Spoils.

With Baggage Parapet in play, each retreating Christian Lord can add
`c7_pay` to the chosen Retreat. Set it to an Asset on that Lord's mat
to spend one and skip his Retreat Spoils and Service shift. Select the
Retreat without `c7_pay` to take the normal penalties.

Scripted callers that omit `interactive_retreat` use the automatic
resolution policy.

## Allocating Spoils

After Losses, the winning player allocates captured Assets when more
than one Lord can receive them. Use the `battle_spoils` action with
`lord_id`, `asset`, and a positive integer `amount` up to the amount
remaining. The menu offers one or all of each Asset for each eligible
Lord. Any intermediate amount is legal. The game resumes after the
pool is empty, and a partially allocated pool can be saved and loaded.

Battle and Sally actions with `interactive_retreat` enable this choice.
Storm actions in the legal menu set `interactive_spoils` for a Sack.
A successful Avoid offers the same allocation to the Approaching side
before any remaining defenders respond. Betrayal of Terms Spoils use
the same allocation.
A single recipient receives the full pool automatically. Scripted and
campaign-ending combats use automatic allocation after Losses.

## Surrender Holds

The normal Siege roll keeps any unplayed Held cards. The Siege menu
offers `mozarabes: true` when the Christian player can spend C21 to
succeed automatically in a Reconquista Taifa. A successful Christian
Surrender using the menu opens `betrayal_of_terms`. Decline to keep C9
or play it for `single` or `double` Spoils. A scripted Siege can set
`interactive_surrender: true` for the same response or predeclare
`c9_mode` as `single` or `double`.

After double Spoils are allocated, the Muslim player chooses an
eligible `target_locale_id` with `betrayal_jihad` if a Jihad marker
can be placed. The Christian Command sequence then resumes.

## Lifecycle

### `begin_levy`
Transitions setup or campaign -> levy/arts_of_war.

```
{"type": "begin_levy"}
```

### `pass_step`
The acting side ratifies that it is done with the current Levy step.
When both sides have ratified, the step advances (3.1 → 3.2 → 3.3 →
3.4 → 3.5 → done) and the phase transitions to campaign on completion.

```
{"type": "pass_step", "side": "christian"}
```

## 4.0 Campaign-entry Capability Discard

When a side has more board-edge Capabilities than Mustered Lords, Campaign
entry now sets `campaign_step="capability_discard"` and a matching pending
decision. Christians select first, then Muslims. Planning cannot start until
both sides are within their limits. Personal This-Lord cards do not count.

### `discard_capabilities`

Choose one or more of the waiting side's excess cards explicitly:

```json
{"type":"discard_capabilities","side":"christian","card_ids":["C22","C20"]}
```

`card_ids` must be a nonempty list of distinct, owned board-edge cards and
cannot exceed the pending excess. The legal palette offers each card as a
single-card action; the caller may also submit a batch. Invalid choices leave
state unchanged. The prompt is refreshed after each choice and survives a
save/load round trip. There is no default selection and no Pass option.

Discarding C18 **Milites** permanently removes the entire card, but leaves
recruited troops in place. Ordinary discard of its **Runaway Slaves** Event
half is unchanged and does not invoke this Capability-only removal rule.

## 3.1 Arts of War

### `aow_shuffle`
Shuffle the acting side's Arts of War deck. On first call, populates
the deck from `cards.json`.

```
{"type": "aow_shuffle", "side": "christian"}
```

### `aow_draw`
Draw `n` cards from the top of the deck into `decks.pending_draw[side]`.

```
{"type": "aow_draw", "side": "christian", "n": 3}
```

### Held Events (3.1.3)

On later Levies, `aow_implement_event` implements the next card in
`pending_draw`. Immediate Events begin resolving then. Hold Events go to
`decks.held[side]` without executing. Starting scenario Holds use the
same collection. Unplayed Holds survive Levy/Campaign boundaries and
unrelated Battles; legacy saves' event buckets remain supported.

`play_event` plays a held C18, C20, M8, M9, M10, M12, M15, M18, M20,
or M21 during that side's turn in Levy/Campaign with no pending decision.
Existing specific `play_*` actions and reactive combat/movement hooks
continue to handle the other Hold cards. Playing consumes the card once.

```
{"type": "play_event", "side": "muslim", "card_id": "M12",
 "payload": {"lord_ids": ["al_mutamid", "al_mutawakkil"]}}
```

M12 accepts up to two `lord_ids` for Calendar/Service shifts, or
`{"mode":"lordship","lord_id":"al_mutamid"}` during the Muslim
Muster segment for temporary +2 Lordship. C18/M18 are playable only
in their side's Muster segment; `payload.transport` chooses `cart`
or `mule` (default), and `transport_by_lord` overrides that choice
for individual Lords. M21 accepts `payload.lord_id` to Muster a Taifa
Lord instead of its Jihad effect. Other direct Events accept their
resolver's optional targets (`locale_id`, `jihad_targets`, or `mode`).

`legal_moves` includes executable examples for held Events, including
the Marriage card held at the start of Scenario A.

### Drought (C5 and M5)

If Drought offers a choice, the affected player answers with
`drought_choice`. Follow `pending.waiting_on` and `legal_moves` after
each response. The target prompt offers all pairs of eligible Lords
(one Lord if only one is eligible) and the Muslim option to submit
`"discard_camels": true` when M16 is in play. If no Lords are eligible,
Drought is discarded and Camels remain in play.

```json
{"type": "drought_choice", "side": "christian",
 "lord_ids": ["garcia_ordonez", "pedro_ansurez"]}
```

At the Greed prompt, use `discard_lords` for any chosen subset of eligible
Lords. An empty list keeps the Mules. At the Feed prompt, `feed_loot`
maps each payer to its total Loot expenditure for own Feed and Sharing.
The owner view lists the valid ranges and the action accepts multiple
payers in one submission. Omitted payers spend Provender first.

The pending choice can be saved and reloaded. After Drought resolves,
the drawing player resumes Arts of War. Pay and Disband take place in
their usual Levy steps.

## 3.2 Pay

Phase 2c: only `pass_step` is currently legal in this step. Payment
handlers (`pay_with_coin`, `pay_with_loot`) land in a future phase.

## 3.3 Service / Disband

Phase 2c: only `pass_step`. Beyond-Service Disband logic (3.3.1, 3.3.2
with Errata p.12 amendments) is wired alongside Calendar shift mechanics
in Phase 3.

## 3.4 Muster

### `muster_lord`
Place a Lord with Fealty rating from the Calendar to one of his free
Seats. Rolls a d6 against Fealty; on success places at the named Seat
and copies starting Forces / Assets from the Lord reference.

```
{"type": "muster_lord", "side": "christian",
 "lord_id": "pedro_ansurez", "seat": "simancas"}
```

Lords without a Fealty rating (Yusuf, Sir, Eudes, both Rodrigos) cannot
be Mustered via this handler — they must use Call to Arms triggers,
landing in Phase 4.

## 3.5 Call to Arms

Phase 2c: only `pass_step`. Trigger-specific handlers (`call_to_arms_employ_rodrigo`,
`call_to_arms_invite_almoravids`, etc.) land in Phase 4 alongside the
event resolver framework.

## Error model

Validation failures raise `almoravid.actions.IllegalAction(message,
code=...)`. Agents should branch on `e.code` rather than message text.
Common codes:

- `bad_phase`: wrong phase (setup vs levy vs campaign)
- `bad_levy_step`: action's step doesn't match `meta.levy_step`
- `not_active`: action's side isn't the active player
- `bad_side`: action missing or invalid `side`
- `bad_arg`: malformed argument
- `unknown_action`: action `type` not registered
- `unknown_lord`: lord_id doesn't exist
- `wrong_side`: trying to act on the other side's Lord
- `cta_only_lord`: Lord must be Mustered via Call to Arms (Fealty=None)
- `not_on_calendar`: Lord isn't on the Calendar
- `no_free_seat`: all Lord's Seats are Enemy-occupied
- `bad_seat`: named Seat is not a free Seat for this Lord
- `deck_underflow`: requested more cards than the deck contains

## Playtest corrections (2026-10-10)

Held C20 Al-Qadir requires an explicit marker selection:

```json
{"type":"play_event","side":"christian","card_id":"C20",
 "payload":{"locale_ids":["ucles","ucles"]}}
```

Repeat a Locale id to remove both markers there, or name two Locales in one
eligible Taifa. `payload.locale_id` is a single-Locale shorthand. Omitting
the selection does not choose targets automatically. Invalid choices preserve
the card and board. `legal_moves` provides each valid choice.

C21 Sisnando Davidez is an Alfonso-only, board-edge Capability. During Levy,
its free once-per-Levy action is:

```json
{"type":"cap_sisnando","side":"christian","target_locale":"ucles"}
```

See `PLAYTEST_FIXES_2026-10-10.md` for the source-rule references and other
Scenario D setup, Muster, and reconquest corrections.

## Bishoprics (C22): free marker placement at any time

`cap_bishoprics` places a **Ready Vassal marker**, not its troops, on a
Mustered Christian Lord other than Sancho. It costs no Lordship or Command
and is valid during Levy as well as Campaign (including planning and pending
responses). It leaves the active player, Command card, and pending decision
unchanged. The Christian may invoke it during the opponent's turn; the normal
legal menu offers it when the Christian is the active player.

```json
{"type":"cap_bishoprics","side":"christian","target_lord_id":"alfonso","bishop_id":"bishop_2"}
```

`bishop_id` chooses an available printed marker: `bishop_1` (Orense),
`bishop_2` (León), or `bishop_3` (Lugo). Omitting it selects the first available
marker. The menu enumerates every available marker/eligible-Lord combination.
There are at most three special Bishops and no more than one per Lord.

Use the ordinary `levy_take_vassal` action in Muster to recruit the Bishop's
troops, subject to normal Lord eligibility and Lordship cost. Special Bishops
never receive Calendar Service markers under advanced Vassal Service.
Discarding C22 removes its special Bishop markers and Mustered units and
resets availability. Sancho's printed Bishop of Jaca is unaffected.

## Troop Capability scope and lifetime (M15 / M20)

Saqalibah and Al-Rûm are **This Lord** Capabilities, eligible only for Taifa
Muslim Lords. They occupy personal mat slots, not board-edge capacity. Only
their holder may invoke `cap_saqalibah` or `cap_al_rum` during an eligible
Muster segment. Al-Rûm still costs one Coin, with Sharing and Taifas-box
payment allowed. Each acquisition can recruit once; discard removes the
tracked contingent and clears that acquisition's usage record. A new
acquisition may recruit again. A Lord staying at a Winter Siege keeps the
card and its existing usage status.

Returning the contingent immediately Disbands a Mustered Lord if no regular
or Routed Forces remain. Calendar placement counts from the current Levy
or the next Levy during Campaign. Normal mat cleanup and Taifa politics
apply. Wastage pauses for any Recognition of Neutrality decision, then
resumes its remaining discards. A final-Lord Campaign victory resolves
before advancing the Calendar.

## Fueros (C20)

Only Alfonso may Levy Fueros. It deploys at the board edge, not his mat.
Its Jihad-removal action is free once during each **Levy**, not Campaign.
The target must be in a Reconquista Taifa and strictly closer to Alfonso
than to every Muslim Lord. Choose one or two eligible markers:

```json
{"type":"cap_fueros","side":"christian","target_locale":"toledo","count":1}
```

`count` may be one or two, within the number present; omitting it retains
the existing maximum-up-to-two payload behavior. Decline by not invoking
the action. The menu includes both counts when available.

## End Campaign sequence

`end_campaign` checks final scoring before applying Grow/Harvest, Repairs or
Wastage. If play continues, Grow/Harvest and Repairs precede Wastage. Their
completed results remain in `grow_harvest_repairs` across interactive Wastage
and saved-game continuations. The Calendar stays in the concluding Campaign's
box until those decisions finish; Reset then unstacks Lords and advances it.
The final Campaign ends in its existing box without those cleanup steps.

After unstacking, Reset now pauses for Christians and then Muslims to elect
voluntary Arts of War discards (4.9.5). The pending kind is `reset_discard`.
Each side may keep everything, discard any Held Events, or discard either
scope of Capability, even if none of its Lords qualified for Wastage.

```json
{"type":"reset_discard","side":"christian","card_ids":["C14","C3"]}
{"type":"reset_discard","side":"muslim","card_ids":[]}
```

By default a selection finishes that side's Reset election. Use `done:false`
to discard some cards and continue choosing. The menu lists each available
card with `done:false` plus an empty selection to finish, so every subset is
reachable without listing all combinations. Explicit batches are also accepted.
Only the owner sees Held-card choices. Both sides receive the public prompt
even with no cards, so the prompt does not disclose Hold ownership.

Discarding a Hold does not play its Event. Capability discards apply their
printed cleanup: temporary troops return, an empty Lord Disbands, and Milites
leaves the game while its recruited units remain. Political decisions pause
the remaining selections, which survive save/load. Immediate Campaign victory
ends play before further selections or Calendar advance. Otherwise, after the
Muslim election finishes, the Calendar advances once and the existing
Levy/Curias/Winter sequence resumes. No other action may bypass Reset.

## Avoid reaction and player visibility

A legal `respond_avoid_battle` declaration always returns a
`swollen_river_block` pending decision owned by the Approaching side. No
Lords move or discard Assets yet. That player submits
`respond_swollen_river_block` with `play: false` to complete the Avoid, or
`play: true` to use a Held C3/M3 and force Battle. The menu offers Play only
when available. This response step occurs with or without the card, keeping
an unplayed Hold private. A played card is reported as `swollen_river_played`.

With Hidden Mats enabled, Approach and this reaction window keep enemy mats
concealed. Committed combat decisions and synchronous combat inspection reveal
the actual participants. Other Lords remain concealed, including uninvolved
garrisons in the same Locale. Saved reaction and combat decisions retain the
same visibility rules.

## Severed Heads (M13)

A successful Muslim Ravage, Christian Retreat (including removal for lack
of a Retreat), or Sack of a Christian Stronghold opens a `severed_heads`
decision for the Muslim player. Withdrawal into a Stronghold does not qualify,
even if subsequent Losses remove the withdrawing Lord. Event-placed Ravage
and a Ravage blocked by Caballería Villana do not qualify. A final-Lord
Campaign victory ends play immediately, before optional card reactions.

The public response step occurs whether or not M13 is Held. Decline retains
the card and resumes any suspended response or the previous player's turn:

```json
{"type":"decline_severed_heads","side":"muslim"}
```

If M13 is Held, choose Jihad or Taifa Lord shifts. Ravage grants two Jihad
or one Lord; Retreat/Sack grants four Jihad or up to two distinct Lords:

```json
{"type":"play_severed_heads","side":"muslim","mode":"jihad","payload":{"jihad_targets":["toledo","toledo"]}}
{"type":"play_severed_heads","side":"muslim","mode":"shift","target_lords":["al_mutamid"]}
```

Explicit `jihad_targets` may repeat eligible Locales, up to the reward count;
omitting them uses the existing automatic placement, and a shorter list
automatically places the remainder. All eligible one-/two-Lord combinations
are in the menu. `target_lord` remains accepted for a single Lord. Shift each
chosen cylinder two boxes left if on the Calendar, or Service two boxes right
if on the map, including advanced Vassal Service. Play consumes M13 once;
unrelated commands cannot bypass the response. Save/load preserves the window.

Caballería Villana requires Muslim Ravage in León/Aragón to roll 1–3 for
effect, including Al-Garada long-range Ravage. A failed roll still spends the
action/card and any long-range Provender, but grants no Rustling, War Drums,
Ravaged marker, VP or M13 opportunity. Successful Rustling and War Drums
rewards have no eight-Asset ceiling (rule 1.7.1).
