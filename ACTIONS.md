# Action Catalog

Every state mutation goes through `apply_action(state, action)` in
`almoravid.actions`. The `action` is a JSON-serializable dict with a
`type` field naming the handler and additional fields as required.

`legal_moves(state)` enumerates the actions currently legal for the
active player. Per Pattern 1 (state-set-but-unreachable), any new
handler in `actions.py` must add a corresponding enumerator in
`legal_moves.py` in the same PR.

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
