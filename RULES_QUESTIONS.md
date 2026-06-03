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

**Status:** resolved
**Filed:** 2026-05-23
**Resolved:** 2026-05-23

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

**Resolution:** (user adjudication 2026-05-23) The cards-data "side_wide"
entry was the bug. Scope = **this_lord** (C15 reads "This Lord may use 1
Command to become or stop being a Lieutenant"; per 3.4.4, capabilities WITHOUT
an explicit "put X at the board edge" Tips line tuck under the bearer's mat —
every genuinely side-wide cap (C16/C18/C19/C20/C21/C22/C23, M10/M12/M16/M19...)
carries that line; C15 does not). Eligible bearers = a FIXED set of four
captains: Pedro Ansúrez, García Ordóñez, Álvar Fáñez, Rodrigo Campeador
(printed on the card; Background Book p.54). Identical to C8 Hueste and C24
García Jiménez -> factored as capabilities.CHRISTIAN_CAPTAINS_FOUR. NOT a
Command-rating predicate; does not recompute (e.g. via Mesnada). Rodrigo
eligibility binds to Rodrigo Campeador (Christian/yellow cylinder) only.
Implemented: cards.json C15 scope -> this_lord; eligibility enforced at deploy
(3.1.2) and Levy (3.4.4) via capability_eligible_lords, mirrored in both
enumerators; toggle_lieutenant (the 4.1.3 outside-Plan-step exception) is now
reachable and enumerated (stack onto a legal same-Locale target / unstack),
the standard 4.1.3 constraints applying (target Christian, same Locale, not the
Marshal, target/bearer not already a Lower Lord). Tests: tests/test_q001_alferez.py.
**Affected code:** campaign._h_toggle_lieutenant (gate); legal_moves enumeration
(currently a documented no-op note where the toggle would be offered).

## Q-002 — M24 Al-Garada (Muslim long-range Ravage): capability scope

**Status:** resolved
**Filed:** 2026-05-23
**Resolved:** 2026-05-23

**Question:** M24 Al-Garada is the Muslim equivalent of Cabalgadas (Arts of War
ref M24: "This Lord may pay 1 Prov to use entire card to Ravage across up to 2
Ways, not at or past any Unbesieged Enemy Lord ... See ... Cabalgadas"). Its
card text says "This Lord", but cards.json records capability_scope =
"side_wide" — the same scope mismatch resolved for C15 Alférez in Q-001. Should
M24 be this_lord? And what is its eligible-Lord set (card "Lords." line: "Taifa
Muslim or Rodrigo al-Sayyid" — a CATEGORY, not a fixed name list like the four
captains)?

**Why it matters:** the long-range-Ravage command (cmd_cabalgadas) is wired and
keyed on this_lord Cabalgadas capabilities (C14/C17), so it covers the Christian
side now. The Muslim twin M24 will not trigger until its scope is this_lord and
its eligibility ("Taifa Muslim or Rodrigo al-Sayyid") is modeled. Not guessed.

**Consultation chain:**
1. Arts of War Reference M24 Al-Garada: "This Lord may pay 1 Prov to use entire
   card to Ravage across up to 2 Ways ... See Christian Capability #C14/C17
   Cabalgadas." Lords. "Taifa Muslim or Rodrigo al-Sayyid."
2. 3.4.4 capability scope + Q-001 precedent (the "This Lord" phrasing -> this_lord;
   side-wide caps carry an explicit "board edge" Tips line, which M24 lacks).

**Resolution:** (user adjudication 2026-05-23) Same pattern as Q-001 — the
cards-data "side_wide" was the bug. Scope = **this_lord** ("This Lord" text; the
M24 Tips invoke the 3.4.4 same-title cap, confirming it is mat-bound; every
genuine side-wide Muslim cap (M10/M12/M16/M19/M22) carries an explicit "board
edge, not a mat" Tips line, which M24 lacks). Eligible bearers = the seven
"Taifa Muslim or Rodrigo al-Sayyid": the six Taifa Lords (al-Mustain, Abu Bakr,
Abd Allah, al-Mutawakkil, al-Mutamid, al-Mundir; 1.5.1 design note) plus Rodrigo
al-Sayyid (green cylinder). Yusuf and Sir are NOT Taifa Lords -> NOT eligible.
Implemented: cards.json M24 scope -> this_lord; capabilities.MUSLIM_RAIDERS_SEVEN
+ capability_eligible_lords("M24") (enforced at deploy/Levy + enumerators, same
gates as Q-001); _cabalgadas_capable unified over CABALGADAS_CAPS={C14,C17,M24}
so the existing cmd_cabalgadas handler covers M24. Tests: tests/test_cap_cabalgadas.py.
**Affected code:** src/almoravid/data/static/cards.json (M24 scope);
campaign._cabalgadas_capable (add M24 + Muslim eligibility).

## Q-003 — Bowmen/Javelin capability metadata missing for dual-half cards

**Status:** resolved
**Filed:** 2026-05-23 (surfaced building the Sagrajas minigame)
**Resolved:** 2026-06-02

**Question:** cards.json records capability_name=None / capability_scope=None
for C4, C5 (Arqueros), M4, M5 (Alrama), M3, M6 (Harbah) — but the Arts of War
Reference lists these as real Capability halves: "C4 & C5. Arqueros – Bowmen",
"M4 & M5. Alrama – Bowmen", "M3 & M6. Harbah – Javelins" (dual-half cards, like
C7 Baggage Parapet / Jabalinas). The RESOLVER applies their effects correctly
(forces.json strikes_by_capability gates Bowmen on [C4,C5,M4,M5] and Javelins
on [C7,M3,M6] via capabilities_in_play), so combat is faithful when the card is
in play. But because the cards-data capability_scope is None, these capabilities
cannot be Levied/deployed in normal CAMPAIGN play (levy_take_capability /
aow_deploy_capability gate on capability_scope) — i.e. Arqueros/Alrama/Harbah
are unreachable as Levy Capabilities. Should cards.json carry
capability_name/scope=this_lord for C4/C5/M4/M5/M3/M6 (with the one-per-title
3.4.4 cap the AoW Tips cite: "A Lord may have only one Arqueros/Alrama/Harbah
card")? This is the same scope-data class as Q-001 (C15) and Q-002 (M24).

**Why it matters:** an LLM in a full scenario cannot Levy Bowmen/Javelin
capabilities. The Sagrajas minigame is unaffected (it deploys the cards
directly), so this is logged, not blocking.

**Consultation chain:**
1. Arts of War Reference: "C4 & C5. Arqueros – Bowmen", "M4 & M5. Alrama –
   Bowmen", "M3 & M6. Harbah – Javelins" — all this_lord-style ("this Lord's"
   units; one-per-title cap), no "board edge" line.
2. forces.json already gates the effects on these card_ids (resolver correct).
3. cards.json: capability_name/scope = None for these six (the bug).

**Resolution:** Per the Arts of War Reference (consultation chain below),
C4/C5 (Arqueros), M4/M5 (Alrama), M3/M6 (Harbah) are This-Lord Capabilities
with a one-per-title cap (3.4.4). cards.json now records
capability_name + capability_scope="this_lord" (no_capability=false) for all
six. They are deployable at the first Levy (3.1.2) and Levyable (3.4.4),
gated by the existing one-per-title rule (verified by
tests/test_q003_bowmen_javelin_caps.py). The combat resolver already gated
their effects on these card_ids, so in-play behavior is unchanged; only the
Levy/deploy reachability was added. Eligibility is any Lord of the right
side (capability_eligible_lords returns None for all six).
**Affected code:** src/almoravid/data/static/cards.json;
tests/test_q003_bowmen_javelin_caps.py.

## Sagrajas minigame — documented modeling limitation (not a Q)
The Background Book gives Yusuf and Sir a Javelins marker for their AFRICAN
HORSE. The harness models Javelins (C7/M3/M6) for Unarmored Foot + Light Horse
only (forces.json has no African-Horse Javelin row, and the Javelins MARKER's
owner-declared round-of-use is not modeled — see resolver-fix (a) TODO). So in
the minigame Yusuf/Sir's African Horse do not gain the Javelin Missile bonus.
All other Sagrajas setup is faithful. Wiring African-Horse Javelins + the
owner round-choice is broader resolver work (the Javelins-marker subsystem).
