# Cross-Project Lessons from Nevsky-Harness

A transferable summary of the bug patterns, audit techniques, and defensive
idioms that have proven valuable while bug-hunting Nevsky. Targeted at
sibling L&C (Levy & Command) harnesses — Almoravid, Inferno, and any
future ports — and at anyone joining a Nevsky-style rules-engine project
mid-stream.

The five most recent SMOKEs (118-122) drove most of these insights, but the
patterns have been seen across the full 188 rounds. Code shapes shown
below are lifted from the Nevsky source and are intended to be portable
with minimal renaming.

---

## 1. Legal-moves over-enumeration is endemic — audit it systematically

In any rules engine with a separation between an action **enumerator**
(`legal_moves.py` in Nevsky — emits the palette of currently-permissible
actions) and per-action **handlers** (`_h_*` functions in `campaign.py`
that validate and apply), the enumerator will diverge from the handlers
over time. Every `IllegalAction` raise in a handler is a candidate for an
enumerator gap.

Two recent Nevsky examples:

- **SMOKE-118 (R186):** `levy_capability` was enumerated as every
  `(by_lord, card_id)` pair, ignoring `capability_eligibility`, the
  per-Lord cap-2 limit, and the duplicate-capability-name rule the
  handler enforces. Agents and the LLM-play interface burned moves on
  `ineligible_levyer` / `ineligible_target` / `cap_limit` /
  `duplicate_capability` rejections.
- **SMOKE-122 (R188):** `cmd_ravage` was enumerated unconditionally,
  while `_h_cmd_ravage` rejects on own-territory, already-Conquered,
  Friendly-to-active-side, or already-Ravaged Locales.

### The cheap audit

For each project:

```bash
grep -n 'raise IllegalAction' src/<engine>/campaign.py | \
    sed -E 's/^([0-9]+):.*"([^"]+)".*/\1\t\2/'
```

Walk the list. For each pre-check raise (own-territory, eligibility,
capacity, friendly-locale, etc.), grep the enumerator for the
corresponding pre-filter. Misses are very likely SMOKEs.

### The defensive idiom

When mirroring a handler's pre-checks in the enumerator, gate the check
behind a try/except so a static-data load failure or shape mismatch
**suppresses** the option rather than crashes the enumerator. Bias
toward "miss a legal move" over "offer a phantom-legal move", because
the consumer (agent, LLM, UI) trusts the palette.

Shape from SMOKE-122 (`src/nevsky/legal_moves.py`):

```python
ravage_ok = False
if active.location is not None:
    try:
        from nevsky.static_data import load_locales as _ll_rv
        static_loc = _ll_rv().get(active.location)
        loc_state = state.locales.get(active.location)
        if static_loc is not None and loc_state is not None:
            if (
                static_loc.get("territory") != side
                and loc_state.russian_conquered == 0
                and loc_state.teutonic_conquered == 0
                and not _is_friendly_locale(state, active.location, side)
                and not loc_state.russian_ravaged
                and not loc_state.teutonic_ravaged
            ):
                ravage_ok = True
    except (ImportError, KeyError, AttributeError, FileNotFoundError):
        ravage_ok = False
if ravage_ok:
    out.append({"type": "cmd_ravage", ...})
```

---

## 2. Arg-shape/semantic mismatch is its own failure mode

Matching argument **names** between the enumerator and the handler is not
enough — the enumerator can emit values from the wrong **domain** while
the field name looks correct.

**SMOKE-119 (R186):** The `stand_battle` pseudo-option in `legal_moves`
emitted `{"concede": side}` (game side, `"teutonic"` / `"russian"`) but
`_h_stand_battle` expected `{"concede": "attacker" | "defender"}`
(battle role). The field name matched; the value domain didn't. Every
concede attempt the strategic agent made was rejected with
`bad_concede` until R186 surfaced it.

### The CI check

In a sweep test, replay every action shape the enumerator emits through
the handler in a representative state and assert no `bad_*` /
`missing_arg` / `ineligible_*` codes come back. The LLM-play interface
does this implicitly under load; codify it as a deterministic sweep so
the signal isn't lost in production noise.

Sketch:

```python
def test_enumerator_handler_roundtrip():
    for scenario in ALL_SCENARIOS:
        s = load_scenario(scenario, seed=1)
        for _ in range(50):
            for move in legal_moves(s, with_previews=False):
                snapshot = s.model_copy(deep=True)
                try:
                    apply_action(snapshot, move)
                except IllegalAction as e:
                    pytest.fail(
                        f"enumerator emitted illegal {move['type']}: "
                        f"{e.code} ({e.message}) in {scenario}"
                    )
            # advance one step under any policy
            apply_action(s, pick_first(legal_moves(s)))
```

Couple this with **source-marker regression tests** — a near-zero-cost
guardrail against silent refactors:

```python
def test_smoke_NNN_marker_present_in_source():
    import inspect, nevsky.legal_moves as lm
    assert "SMOKE-NNN" in inspect.getsource(lm)
```

Cheap insurance: a future refactor that removes the filter also removes
the comment, and CI fails immediately.

---

## 3. Event resolvers must no-op gracefully when their target isn't in state

Card-driven event resolvers (`R*` and `T*` in Nevsky) typically reference a
specific Lord, Stronghold-of-type-X, marker, or asset. If that referent
isn't currently on the map — because the relevant Lord was disbanded,
the Stronghold isn't part of the active scenario, or an earlier event
already removed it — the naive implementation crashes. Six SMOKEs in
this family so far: 112, 113, 114, 120, 121-batch (R11, R17, T11, T18).

### The pattern

```python
def _resolve_R11(state: GameState, args: dict) -> dict:
    """Bishop's-blessing-style: shift this-Levy's marker on the
    calendar. If the source Lord isn't mustered, no-op the shift
    but still preserve the block-this-Levy side-effect (the rule
    body fires regardless of the marker move)."""
    target = args.get("target")
    if target is None or target not in state.lords or \
            state.lords[target].state != "mustered":
        # SMOKE-121: no-op-on-missing-target. Preserve any
        # rule-body side-effect that doesn't require the target
        # (here: block this Levy step).
        state.meta.levy_blocked_this_lord = True
        return {"no_op": True,
                "reason": "no eligible target",
                "side_effects": ["levy_blocked_this_lord"]}
    # ... normal resolution ...
```

Two corollaries Nevsky has learned the hard way:

- **Partial resolution is sometimes correct.** Some events have a
  side-effect that fires unconditionally (block the Levy step, advance
  a marker) and a target-dependent side-effect. The no-op path must
  preserve the unconditional half. T18 in R187 needed this.
- **Returning `{"no_op": True}` is not enough by itself.** Downstream
  code (lifecycle bookkeeping, UI, replays) needs to know whether
  partial side-effects fired. Include a `side_effects` list in the
  return so the audit log is faithful.

### Audit shape

```bash
# Find every event resolver that touches a Lord/Locale/Asset without
# checking presence first.
grep -nA20 'def _resolve_[RT][0-9]' src/<engine>/events.py | \
    grep -E 'state\.lords\[|state\.locales\[|state\.assets\['
```

For each hit, confirm there's a `if target not in state.lords` (or
equivalent) guard upstream. If not, candidate SMOKE.

---

## 4. Different agent styles surface different bug classes

The Nevsky harness has accumulated four agent-shaped consumers of
`legal_moves`. Each finds a different bug class:

The **greedy agent** (`scripts/self_play.py`) scores moves on a fast
state-delta heuristic. It avoids combat (low expected value, high
variance), so it almost never exercises the combat-action shapes.
It found the no-target-no-op family (114, 120, 121-batch) and the
lifecycle leaks.

The **strategic agent** (`scripts/strategic_agent.py`) weights combat
shapes high (`cmd_storm: 92`, `cmd_sally: 88`, aggressive `cmd_march`).
It found SMOKE-118 and 119 — the levy-capability and concede-arg
gaps — because it actually opens battles and stands them.

The **LLM-play interface** (`src/nevsky/llm/`) can't pivot off an illegal
suggestion the way a greedy agent can — it just retries. So every
phantom-legal move in the palette burns a retry slot and surfaces
loudly. It found SMOKE-122 in a single Pleskau playthrough.

**Property-based tests** (Hypothesis) catch invariant violations no
agent will produce — accumulator overflow, off-by-one in calendar math,
state shapes that shouldn't be reachable but are. Worth running even
when the agent sweeps come back clean.

### The recommendation for new ports

Don't rely on one agent style. Wire up at least two: greedy (breadth)
plus either strategic (combat depth) or an LLM-style strict-follow
wrapper (enumerator correctness). For 200 sessions across all
scenarios × 50 seeds, the marginal cost of running both is small and
the SMOKE yield is meaningfully higher.

---

## 5. The LLM-play interface design that worked

For any harness considering an LLM-driven play path, the architecture
that proved out in Nevsky R185b-R188:

- **Hidden-info filter at the boundary.** Strip the opposing side's
  hand, plan, and any face-down state before serializing. Don't trust
  the LLM to ignore visible information; just don't show it.
- **Pre-filter `legal_moves` to the active side.** The move palette
  the LLM sees is the same one a strict-follow agent would receive.
  No illegal options offered means fewer hallucinated illegal moves.
- **Curated ~3 KB briefing** beats dumping the full rulebook into the
  system prompt. Game state, current phase, recent history, and
  on-demand lookups for cards/strategy/rules references is enough
  context for competent play.
- **3-strike retry + safe phase-appropriate fallback.** If the LLM
  proposes three illegal moves in a row, fall through to a deterministic
  no-op move (`advance_step` / `cmd_pass` / `end_card` / `legate_skip`
  depending on phase). Don't deadlock; don't crash; don't let the
  whole game stall on one hallucination.
- **Post-game self-critique loop.** After terminal, hand the transcript
  back to the model with the simple prompt "what would you do
  differently?" The output is surprisingly useful for surfacing
  strategy and rule-edge cases that didn't crash but felt wrong.

See `src/nevsky/llm/` for the implementation and `LLM_PLAY_GUIDE.md` for
the system-prompt shape.

---

## 6. Audit patterns that have paid off across 188 rounds

In rough order of yield, these are the audit lenses that have produced
SMOKEs on Nevsky. Worth running once per harness:

The **dead-code-surfaces** audit. `grep` for functions defined but never
called, state fields set but never read, action types declared but
never enumerated. Often signals incomplete features that the rest of
the codebase has silently routed around.

The **mirror-gaps** audit. For each pair of symmetric capabilities
(Teutonic / Russian, Attacker / Defender, This-Lord / Side-Wide), confirm
both halves exist. Nevsky has had multiple SMOKEs where one side got a
fix and the other didn't.

The **state-set-but-unreachable** audit. Walk every `state.x = y` write
and confirm there's a code path that reads `state.x`. The inverse —
reads with no writes — is also valuable.

The **rule-cite-but-no-enforce** audit. Walk every comment that cites a
rule number (`# 4.7.2:`, `# SoP 4.1:`). For each cite, confirm the
adjacent code actually enforces what the rule says. Comment-drift is
a steady source of SMOKEs.

The **lifecycle-leak** audit. For each piece of state that has a
lifecycle (capability cards in play, Lords in service, markers on the
calendar), confirm every transition path correctly clears or moves the
state. The hardest class of bugs Nevsky has hit — many in this family
took two or three rounds to fully resolve.

Each of these is documented in more depth in `FUTURE_PROJECTS_LESSONS.md`
(769 lines, 14 catalogued patterns); this file is the executive summary.

---

## 7. Small idioms worth porting verbatim

`try/except` around static-data loads in `legal_moves`. Already covered
above. Bias: suppress over offer.

Source-marker regression tests. One-liner per SMOKE; CI catches silent
refactors. Already covered.

`inspect.getsource()` + `assert "SMOKE-NNN" in src` is the
implementation; per-test it's:

```python
def test_smoke_NNN_marker_present_in_source():
    import inspect, <engine>.<module> as m
    assert "SMOKE-NNN" in inspect.getsource(m)
```

Deterministic seeded RNG threaded through `state.meta.rng_state`. Avoids
the "works on my machine" reproduction problem on every flake. The
self-play and strategic sweep scripts both consume seeds from CLI args
so any failing session is bit-for-bit reproducible.

Append-only `SMOKE_TEST_FINDINGS.md`. Every round appends; nothing
overwrites. Cheap institutional memory; the audit history is the file.

---

## Closing

The single biggest lesson from 188 rounds on Nevsky: **the enumerator
and the handler will diverge.** Every other audit pattern, every agent
style, every test idiom in this doc is, at root, a way of catching
that divergence before a user does. If a sibling harness only adopts
one thing from this list, make it the enumerator/handler round-trip
sweep from §2.

Questions, corrections, or additions welcome — append to this file or
to `FUTURE_PROJECTS_LESSONS.md` as appropriate. The two docs are
intentionally redundant in the patterns they catalogue; this one is
the short version.
