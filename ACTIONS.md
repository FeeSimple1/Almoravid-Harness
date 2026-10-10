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

On later Levies, `aow_implement_event` resolves the next card in
`pending_draw`. Immediate Events execute then; Hold Events go to
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
