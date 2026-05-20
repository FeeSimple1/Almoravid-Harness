# Rules Faithfulness Verification Log

Tracks the clause-by-clause audit of the harness against the official
Rules of Play (`reference/Almoravid_Rules_of_Play.txt`, extracted from
`source/Almoravid+Rules+of+Play+-+LIVING+RULES+(1).pdf`), the official
Errata, and printed card/component text. Per BRIEF "Rules Faithfulness
Is Non-Optional", no simplifications are permitted; every divergence is
either fixed or logged as a Q-NNN for user adjudication.

Status legend: VERIFIED (matches rules) | FIXED (diverged, corrected) |
Q-NNN (needs user adjudication, see RULES_QUESTIONS.md).

## Static data
- Forces (forces.json) — VERIFIED against Quick Reference Table 1
  (textual extraction of the image-only Player Aid Forces chart),
  cross-checked vs Almoravid Reference info.rtf. All 8 unit types'
  strikes (battle/storm), strikes-by-capability (Ballesteros/Aqqara,
  Arqueros/Alrama, Jabalinas/Harbah, Slingers), strikes-by-garrison,
  protection (armor/evade/auto-remove) match. Note: the .rtf omitted
  African Horse's Melee x1/2 secondary strike; Quick Reference Table 1
  and the engine include it (confirmed correct).
- Strongholds (strongholds.json) — VERIFIED against Quick Reference
  Table 2. City/Fortress/Town/Castle capacity, value, walls_range,
  garrison composition + capabilities, surrender dice, and Sack spoils
  all match.

## Subsystems
(in progress — audited section by section below)
