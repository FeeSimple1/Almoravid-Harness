# Almoravid Vassal comparison — 2026-10-20

Compared repository baseline `b72ba8d` with Brian Reynolds and Stephen Stone's
**Almoravid 1.3** module. Found and corrected **eight map-data errors**: one
missing Road, five nonexistent Ways, and two incorrect Port flags.

## Sources and method

- [Official Vassal listing](https://vassalengine.org/wiki/Module:Almoravid).
- [Module download](https://obj.vassalengine.org/images/7/73/Almoravid_1.3.vmod).
- Module version: 1.3; listing date: 25 February 2023. The version notes say
  that its scenario setups incorporate the official errata.
- Module SHA-256:
  `945dbec93525f2ca841bbfe4d87c7c772fd32a2320fca848bdd10e50472b822a`.
- Printed board asset: `images/Almoravid Map on Table 3.png`, 7496 × 8352 pixels.
  SHA-256: `3ca60c5eb9397743722faa80b7dc5db511a649d535c99615a0e09f5a5f509ada`.
- Rules: repository Rules of Play §1.3.1 (Ways define adjacency; ship icons
  identify Ports), §4.3 (March), §4.6 (Supply), and the official errata.

Extracted the module's XML definitions, printed component artwork, and all six
scenario saves. Compared the board visually with `ways.json` and `locales.json`.
Compared Lord mats and creation definitions with the Lord data, and decoded the
six saved setups to check starting Forces, Assets, on-map Lord locations,
calendar placements, and assigned/held cards. The 72 named map regions also
agree with the harness's territory assignments. All 52 card identities were
cross-checked; this was not a complete audit of every card's executable rules.

The module is an independent comparison source, not an authority overriding
printed components or errata. Two module discrepancies below illustrate why.

## Confirmed harness errors

| Data | Before | Corrected behavior |
| --- | --- | --- |
| Palencia–Simancas | No connection | Add the printed Road, in both directions. |
| Calatayud–Zaragoza | Direct Road | Remove: no such Way is printed. |
| Barbastro–Lérida | Direct Road | Remove: the Roads connect each to Huesca. |
| Denia–Alicante | Direct Road | Remove: travel can go through Játiva, including its Pass to Alicante. |
| Sevilla–Morón | Direct Road | Remove: the Road north from Morón leads to Córdoba. |
| Lorca–Almería | Direct Pass | Remove: the printed Passes connect each to Granada. |
| Zaragoza | Port | Not a Port: no ship icon. |
| Lérida | Port | Not a Port: no ship icon. |

The corrected graph has **105 Ways: 69 Roads and 36 Passes**, connecting the
same 72 Locales. There are **11 Ports**: Algeciras, Málaga, Almería, Cartagena,
Alicante, Denia, Valencia, Tortosa, Jerez, Huelva, and Sevilla.

These are gameplay defects, not just labels. They change legal Marches,
Supply routes and distances, adjacency-dependent responses and effects, and
the Port eligibility used by Invite the Almoravids, African Fleet,
Guadalquivir, and Genoa & Pisa.

The errors were already present in the curated map reference, and existing
tests explicitly asserted the incorrect totals and Zaragoza's supposed
river port. Corrected the reference to v14 as well as runtime data and tests.
Updated synthetic approach fixtures to use the real Tudela–Zaragoza Road,
preserving their original Battle/Bypass/Withdraw assertions.

## Differences that must not be copied from Vassal

- **Al-Mundir's Fealty:** the XML `Stats Al-Mundir` property says 3, but the
  module's own `mat_almundir.png` shows a four-pip Fealty die. The harness's
  value of **4 is correct** and was retained.
- **Scenario D's Ribat Monks:** the saved module setup uses **M18**. The
  official 15 February 2023 errata explicitly specifies **M14**, which is
  already the harness's assignment. Retained M14. Both have the Ribat Monks
  Capability, but their Event halves differ, so the card identity matters.
- The module parks some set-aside cylinders in its window named "Removed
  From Game." That UI placement is not evidence that the harness should
  convert its explicit `set_aside` state into permanent removal.

Starting Forces, Assets, on-map Lord positions, and actual calendar boxes
matched across scenarios A–F. No scenario JSON changes were necessary.

## Verification

- Baseline: **1,515 tests passed**, despite the map defects.
- Added 28 regression cases covering both-direction movement, rejection of
  phantom Ways without state mutation, Supply over Palencia–Simancas,
  all-scenario Port initialization, nearest-Port enumeration, and M19's
  origin/destination restrictions.
- All **28 failed before** the map correction and **28 passed after** it.
- Full suite after fixture corrections: **1,543 passed**.
- `python -m ruff check src/almoravid/`: passed.
- CI's invariant smoke commands for scenarios A and F, all three profiles,
  seed 2, 400-step limit: **six sessions, no invariant/handler failures**.
  Four completed; two F sessions reached the configured step limit.
  These are smoke checks, not six complete campaign simulations.
- `git -c core.whitespace=cr-at-eol diff --check`: passed; the existing map
  reference's CRLF line endings were preserved.

## Scope and saved games

This comparison increases confidence in component data and initial setups;
it does not certify every rule interaction. Vassal is primarily a virtual
tabletop and cannot serve as a complete engine oracle.

The corrected map is used when initializing new games, including Sagrajas.
Previously serialized GameStates embed their own Ways and Port flags; loading
one does not automatically replace those values. No saved games were altered
or silently migrated by this change.
