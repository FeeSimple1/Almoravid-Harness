# Rules Questions (Q-NNN)

Open and resolved questions surfaced while implementing the harness.

Per the BRIEF (Ambiguity Policy), no Q-NNN may be logged until the
consultation chain has been worked through. Each entry must cite the
references checked and what each said.

## Entry format

```
## Q-NNN — short title

**Status:** open | resolved | superseded
**Filed:** YYYY-MM-DD
**Resolved:** YYYY-MM-DD (if applicable)

**Question:** ...

**Consultation chain:**
1. <.txt reference> §<section>: <what it said>
2. Errata / Scenario Adjustments: <what they said>
3. Rules of Play PDF p.<page>: <what it said>
4. Background Book: <if relevant>

**Resolution:** ...
**Affected code:** <file:section>
```

(No questions logged yet.)

## Q-001 — Alférez (C15 capability): scope and eligible Lords

**Status:** open
**Filed:** 2026-05-23

**Question:** How should the Alférez capability (the Capability half of card
C15; the Event half is Cluniacs) be wired? Two unknowns block a faithful
implementation:
1. **Scope.** cards data records `capability_scope: "side_wide"`, but the
   Arts of War reference describes it as "a Lord WITH Alférez" and Lords.txt
   marks specific Lords as "Eligible for Alferez capability" — which reads
   like a per-Lord (this_lord) association with an eligibility gate. Is
   Alférez deployed side-wide (board edge) and merely USABLE by an eligible
   Lord, or deployed this_lord onto an eligible Lord's mat?
2. **Eligible Lords.** Lords.txt explicitly names Álvar Fáñez ("Eligible for
   Alferez capability ... spend Command to become/stop being a Lieutenant")
   and references Rodrigo ("tied with Rodrigo" on Command). Is eligibility
   exactly {Álvar Fáñez, Rodrigo}, or is it defined by a rule (e.g. highest
   Command among non-Marshals) that could change with ratings/Events?

**Why it matters:** the `toggle_lieutenant` handler implements the Alférez
effect (4.1.3: spend a Command action to stack/unstack as a Lieutenant), but
its gate `lord_has_capability(lord, "C15")` returns False for a side_wide
card, so the handler is currently unreachable (dead). Until scope +
eligibility are settled, the move is intentionally NOT enumerated (no guess).

**Consultation chain:**
1. Arts of War Reference C15 (Alférez – Standard bearer), Tips: "A Lord with
   Alférez may use a Command action to immediately stack as a Lieutenant on
   top of another Christian Lord at the same Locale, or unstack (4.1.3) ...
   multiple times during a single card ... Alfonso may not be a Lower Lord
   (Marshal)." — Confirms the EFFECT, not the scope/eligibility mechanism.
2. Lords.txt [2] Álvar Fáñez Notes: "Eligible for Alferez capability". — Names
   an eligible Lord but does not define the full eligible set or the scope.
3. Rules of Play 4.1.3 (Lieutenants) + 3.4.4 (capability scope): not yet
   mapped to a definitive scope for Alférez specifically.

**Resolution:** (pending user adjudication)
**Affected code:** campaign._h_toggle_lieutenant (gate); legal_moves enumeration
(currently a documented no-op note where the toggle would be offered).
