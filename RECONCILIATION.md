# Rules-of-Play Reconciliation

A clause-by-clause reconciliation of GMT's *Almoravid* Rules of Play
(`reference/Almoravid_Rules_of_Play.txt`), the Battle/Storm and Quick
Reference charts, and the Official Errata against this implementation
(`src/almoravid/`). Method: an automated first pass per chapter, then
manual verification of every flagged item against the code and rules,
then fixes. All confirmed rules-accuracy gaps were fixed (see "Fixes");
remaining deviations are choice-model abstractions or ambiguous readings,
recorded in `RULES_DECISIONS.md` (DECISION-003/004).

Verdict key: **OK** = faithful; **FIXED** = gap found and corrected in
this pass; **DOC** = deliberate documented deviation (RULES_DECISIONS).

## Chapter 1 — Components (1.1–1.9)
All mechanic-bearing clauses faithful. Verified: Taifa status/characteristics
/Jihad (1.4, incl. the Hostage-Populace erratum: no Spoils + flip Ravaged);
all 16 Lords' ratings/forces/assets/vassals match `Lords.txt` exactly; Greed
discard restriction (1.7.2) enforced by construction; Transport capacity
(1.7.3); cards/scopes (1.9). Component-only details (physical card counts,
victory-circle marker) are not modelled — no gameplay effect.
Verdict: **OK**.

## Chapter 2 — Setup & Calendar (2.1–2.2)
Player order Christian-then-Muslim (2.2.4), seasons/calendar (2.2.1-.3),
VP value tracking (2.2.5, abstract not physical). Verdict: **OK**.

## Chapter 3 — Levy (3.1–3.5)
- 3.1 Arts of War (Capabilities first Levy / Events later; Immediate/Hold/
  This-Levy types; Greed) — **OK** (C18 Milites removed-from-game on discard: **FIXED**).
- 3.2 Pay with Coin / Loot (rate, Taifa Coin, Friendly+unbesieged) — **OK**.
- 3.3 Disband Beyond-Service / At-Limit, incl. 1.4.3 Independent-Taifa
  Parias/Coin/VP and the "or Campaign" erratum — **OK**.
- 3.4 Muster (Lordship spend/retry, Fealty roll, Ready, free-Seat erratum,
  Vassals basic/advanced, Transport, Capability 2-cap + eligibility) — **OK**.
  M16/M17 "Muster of OR BY" ban — **FIXED** (earlier audit: the "by" ban was
  not enforced on the Levying Lord).
- 3.5 Call to Arms (all CtA Lords, one-option limit) — **OK**.

## Chapter 4 — Campaign
- 4.1 Plan / Lieutenants — **OK** (internal `is_lieutenant` naming is inverted
  vs the rulebook's "Lieutenant = upper Lord"; behaviour correct).
- 4.2 Command / Activation / Pass — **OK**.
- 4.3 March / Laden / Approach (Avoid/Withdraw/Stand) / Besiege-or-Bypass /
  Depart / Encamp / Sortie — **OK**.
- 4.4 Battle:
  - Array, step order/Initiative, Hit math + mixed-missile rounding,
    Protection (Armored/Unarmored/Evade, M10), Rout, Reposition, the 4.4.3
    Spoils/Service matrix, 4.4.4 Losses — **OK**.
  - Concede the Field (4.4.2, both sides) — **OK** (now also reactive,
    DECISION-001/002).
  - **Crossbows -1 vs Armor** — **FIXED** (data flag was never applied; now
    in both protection paths).
  - **C1/M1 Hills** last the whole Battle — **FIXED** (was discarded after
    Round 1).
  - C8 Cantador confined to holder + combined +4 cap (**FIXED**); Flanking
    closest Front Lord (**FIXED**); M7/Javelin Round-1 owner-choice default —
    **DOC**.
- 4.5 Siege / Storm / Sally:
  - Storm in full (Garrison + absorption order, Walls/Siegeworks, Capacity,
    max-Rounds, attacker-only Concede, Sack) — **OK**.
  - Siege Surrender (dice = Value, threshold = min(4,markers)+Ravaged, C21
    Mozarabes, Conquest, Hostage Populace) — **OK**.
  - **Battering Ram (C1/M1 Capability)** — **FIXED** (reroll one Surrender
    die + counts as 2 Lords for Siegeworks Capacity).
  - **Sally: all Besieged Lords Attack** — **FIXED** (was only the Active
    Lord).
- 4.6 Supply (route BFS, enemy blocking + Besieged/Bypassed exemption,
  Transport) — **OK**; **dynamic Seat markers** (Rodrigo/Yusuf/Sir/Cathedral)
  as Supply/Tax Sources — **FIXED**.
- 4.7 Other Commands:
  - **Forage**: any Friendly Stronghold auto-succeeds (Gardens = even-if-
    Ravaged/Besieged) — **FIXED** (was Gardens-only).
  - **Ravage**: target must be un-Ravaged (either color) — **FIXED** (enemy-
    color re-Ravage exploit closed); ½VP/Rustling/Enforcing-Parias — **OK**.
  - Tax (own Seat, fresh card) — **OK** (Siege/Tax now require a FRESH card: **FIXED**).
- 4.8 Feed / Pay / Disband:
  - Feed (eat 1 Provender/Moved-Fought Lord, Sharing, Unfed penalty) — **OK**.
  - **Disband at limit**: now sweeps ALL on-map Lords (Christian then Muslim)
    — **FIXED** (was only the active Lord; the Feed Unfed penalty can push
    another Lord to its limit).
  - Greed mule-discard / voluntary Pay choices — **DOC**.
- 4.9 End Campaign (Game End, Grow/Harvest, Repairs, Wastage, Reset) — **OK**
  (Wastage discard auto-picked rather than player-chosen — **DOC**).

## Chapter 5 — Victory (5.1–5.3)
VP formula (Conquered 1×Value, Jihad ½×Value, Ravaged ½ by color, Taifa
status, Parias, Cathedral, Taifas-box VP) reproduces all six scenarios'
published starting VP exactly. Campaign / End-of-Scenario victory — **OK**.

## Chapter 6 — Scenarios / Curias / Winter (6.1–6.3)
- 6.1 Scenarios A–F setup + bidding (min-bid-2 in F) and all Official-Errata
  adjustments — **OK**; **Scenario D García start-Bypass at Tudela** —
  **FIXED**.
- 6.2 Curias condition/sequence — **OK**; **box-6 shift threshold when firing
  at box 5** — **FIXED**.
- 6.3 Winter Disband / Siege / Spring Muster / Plowing / box-9 Capabilities —
  **OK** (Winter-Disband Pay sub-step not exposed — **DOC**).
- **Ruined Land Parias Coin** (E/F: Service less Ravaged markers in the
  Taifa) — **FIXED** (flag was present in scenario data but never read).

## Fixes applied in this reconciliation (13)
Ravage re-target guard; Forage Friendly-Stronghold auto; Supply/Tax dynamic
Seats; FPD Disband sweep (all Lords); Curias box-6 threshold; Ruined Land
Parias Coin; Scenario D start-Bypass; Crossbows -1 vs Armor; Hills full-Battle
duration; Sally all-Besieged-Lords; Battering Ram (reroll + counts-as-2);
[+ earlier audit: M16/M17 "by" Muster ban]. Each shipped with tests; the full
suite, ruff, mypy --strict, and the greedy + strategic self-play sweeps stay
green.

## Documented deviations (not wrong-outcome bugs)
See RULES_DECISIONS DECISION-003 (one-round Javelins) and DECISION-004
(interactive-choice abstractions — Wastage/Pay/Greed; per-card defaults —
M7/Javelin Round default; Siege/Tax fresh-card, C8 holder/combined-cap,
Flanking closest, and C18 removed-from-game are now **FIXED**).
