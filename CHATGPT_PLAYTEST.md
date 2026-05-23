# Independent Playtest Guide (for ChatGPT / any LLM agent)

You are independently testing the **Almoravid Harness** — a rules-faithful
Python engine for GMT's *Almoravid* (a "Levy & Campaign" wargame). Your job is
to drive the game and surface bugs: rules the engine gets wrong, illegal moves
it offers, or illegal board states it produces. You are NOT expected to win.

## 0. Setup (no internet, no install needed)

- Requires **Python 3.10+** and **`pydantic` (>=2)**. That's it. The optional
  command-line tool uses `typer`, but the engine and the playtest harness do
  **not** — do not install anything.
- Everything is driven from `playtest_harness.py` at the repo root, which puts
  `src/` on the path itself. From the repo root:

```python
from playtest_harness import Harness, selfplay_smoke

print(Harness.scenarios())
# ['sagrajas', 'scenario_a_toledo_beset', 'scenario_b_quelling_of_tajo',
#  'scenario_c_parias_wars', 'scenario_d_arrival',
#  'scenario_e_alfonso', 'scenario_f_reconquista']
# 'sagrajas' is the battle-only Battle of Sagrajas minigame: it starts in a
# 'battle' phase, the Christian chooses sagrajas_attack/sagrajas_defend, then
# resolve_battle resolves a single Battle (whoever wins wins). h.start(...) and
# h.show() also work.

# A quick sanity run (random policy, validated palette + invariants active):
print(selfplay_smoke("scenario_a_toledo_beset", seed=1, steps=300))
# {'steps': ..., 'ended': ..., 'findings': []}  -> findings == [] means clean
```

If you prefer the optional CLI and `typer` happens to be installed:
`python -m almoravid.cli new <scenario> --output g.json --seed N`, then
`view`, `legal`, `do g.json action.json`, `pending`. But the harness above is
the recommended, dependency-light interface.

## 1. The driving loop

```python
h = Harness("scenario_f_reconquista", seed=7)
print(h.briefing())            # human-readable board state
menu = h.legal()               # numbered list of LEGAL action dicts
for i, m in enumerate(menu):
    print(i, m)
h.apply(0)                     # apply by menu index ...
h.apply({"type": "pass_step", "side": "christian"})   # ... or an action dict
print(h.pending())             # the pending decision (Avoid/Withdraw/Stand, etc.), if any
print(h.findings)              # structured anomaly log (see below)
h.save("game.json"); h2 = Harness.load("game.json")
```

- `legal()` returns a **validated palette**: every candidate is probed on a
  deep copy and any the executor would reject is **dropped and logged** to
  `h.findings` as `kind: "over_enumeration"`. So you never see an illegal
  move — but if one was offered, you still get the diagnostic. (Probing is
  safe: the RNG lives in the state, so it never disturbs the real dice.)
- After every `apply`, the harness runs cheap **invariants** and logs any
  violation as `kind: "invariant_violation"`.

## 2. What a finding looks like

`h.findings` is a list of dicts. Empty is good. Kinds:
- `over_enumeration` — the legal-move menu offered a move the executor
  rejected (`move`, `code`, `detail`). A correctness bug in the menu.
- `invariant_violation` — an illegal board state after an action
  (`after`, `violations`). The invariants checked: no negative
  forces/assets/counters; siege markers in 0..4; never both Conquered AND
  Jihad on a Locale; >2 This-Lord capabilities; pending/active desync; and
  **no two opposing field Lords (both outside a Stronghold) sharing a Locale
  when nothing is pending**.
- `handler_exception` — a candidate raised a non-rules exception (engine bug).
- `zero_legal_moves` — a non-ended state with no legal move (a stall).

When you find one, please report: the scenario + seed, the action history that
reached it (save the state with `h.save`), the finding dict, and — crucially —
**the rule it violates**, citing the reference file + section (see below).

## 3. Judging rules-correctness (the part only you can do)

The validated palette + invariants catch illegal *states*, but not every rule.
To check that an *outcome* matches the rules, read the authoritative sources in
the repo (no outside knowledge of the game — use these files only):

- `reference/Almoravid_Rules_of_Play.txt` — the rulebook (cite section, e.g. 4.4.4).
- `reference/Almoravid Errata.txt` — **overrides** the rulebook.
- `reference/Almoravid Arts of War Reference.txt` — card text + Tips (authoritative for capabilities/events).
- `reference/Almoravid Lords.txt`, `... Scenario Reference.txt`, `... Quick Reference.txt`,
  `... Battle and Storm Reference.txt`, `Almoravid_Sequence_of_Play_v2.txt` — Lords, scenario setup, tables, combat, turn order.

Project mandate (see `BRIEF.md`): the engine must reflect the rules EXACTLY —
no simplifications, and **no greedy defaults standing in for a player choice**.
If you think a rule is wrong, quote the rule text. If a rule is genuinely
ambiguous, say so rather than guessing.

## 4. High-yield things to probe (from prior cross-harness playtests)

1. **Combat reached live.** Steer two opposing Lords into one Locale (March →
   the defender Avoids/Withdraws/Stands → Battle), and besiege/Storm/Sally a
   Stronghold. Check Losses (4.4.4): both sides roll for Routed units; a Lord
   who Retreated-without-Conceding keeps each unit only on a "1", the winner
   keeps each within its Protection range.
2. **A losing-but-surviving Lord must RELOCATE on Retreat**, not just take a
   penalty (and the destination rules: adjacent, no enemy Lord/Stronghold; a
   marching attacker retreats to where it came from). This branch only fires
   when a battle ends with the loser's units alive — make it happen.
3. **Marker lifecycle.** When the last besieger leaves a Stronghold (March-out,
   Disband, Removal, Sail), its Siege/Bypass markers must clear.
4. **Placement.** Muster / Call-to-Arms / event-Muster must never drop a Lord
   onto an enemy-occupied Seat.
5. **Capabilities with effects** worth exercising: C8 Hueste (Marshal for a
   Taifa Group March), C14/C17 Cabalgadas + M24 Al-Garada (long-range Ravage),
   M9 Emir al-Muslimin (Yusuf adds Jihad), C15 Alférez (Lieutenant toggle),
   C16 Cathedrals, the Hold events (C14 Pope Gregory, C15 Cluniacs, M11).
6. **Scenario F** is the full game (Winter Sequence 6.3, Curias 6.2) — the
   least-trodden path.

## 5. Rotate the policy

A first-legal / greedy driver walks a narrow path and misses cold branches
(Concede, the rarely-chosen option). Drive with a **random** policy across
several seeds, an **aggressive/combat-seeking** policy, and your own strategic
judgment — each surfaces different bugs. `selfplay_smoke` uses random; write
your own loops for the others.

## 6. Reproducibility

The RNG is fully in the state (`meta.seed` + `meta.rng_state`), so a given
(scenario, seed, action sequence) is perfectly reproducible. Save the state at
any point with `h.save(path)` and attach it to a finding.

Thank you — independent eyes on a different model find bugs the authors' do not.
