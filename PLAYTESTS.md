# Playtests

Notes from playthrough runs (manual and self-play). To be populated
in subsequent phases.

## Scenario F (Reconquista, full) — complete self-play playthrough (2026-05-23)
Drove Scenario F end-to-end through the real legal_moves -> apply_action
pipeline with a survivalist policy (keep Lords mustered/paid, advance the
Calendar, avoid combat losses) plus a FULL-FANOUT over-enumeration probe
(deepcopy+apply EVERY enumerated candidate) and the deep-invariant set asserted
after every step.

RESULT: clean full game. ~1,300+ applied actions across boxes 1 -> 15, the game
ending at box 15 (start of the second Winter, which is correctly never played
out, 1.3.2) by the End-of-scenario verdict (5.1/5.3): compute_final_vp Christian
6.5 vs Muslim 23.0 -> Muslim wins. Every phase was traversed live, including:
  - the interactive Winter sequence (6.3.2, boxes 7-8) -- auto-resolved (no
    Siege Locales that pass) and advanced into the box-9 Spring Levy;
  - Curias (6.2, the Autumn boxes);
  - both years of the Levy/Campaign cycle (1085 + 1086).
NEWLY-WIRED CAPABILITIES exercised live: cmd_cabalgadas (Muslim long-range
Ravage of Calahorra via M24/Al-Garada), cta_invite_almoravids (Yusuf/Sir enter),
cta_employ_rodrigo. NO over-enumeration, NO invariant violation (incl. the P-3
co-location invariant), NO stall (zero-legal-moves) at any step.

OBSERVATION (not a bug): the running state.score tally (C13.5/M21.0) diverges
from the authoritative compute_final_vp / score.*_final (C6.5/M23.0); this is
the documented lagging display tracker (F6) -- the verdict uses compute_final_vp.

A second, combat-seeking run ended earlier at box 4 by a CORRECT 5.2 ruling
(a side reduced to no Mustered Lords loses), also clean through that point.

## Independent playtest by ChatGPT (2026-05-23) — Scenario F, no bugs found
A second model (ChatGPT) drove Scenario F via the model-agnostic harness
(playtest_harness.py: validated palette + invariants) under four policies
(greedy/strategic/random/sustain, seeds 1/2/99) plus the built-in 20-session
sweep. RESULT: zero findings — no over-enumeration, invariant violations,
zero-legal stalls, handler exceptions, or apply rejections. The sustain policy
reached box 13, exercising the Curias/Winter path into the box-9 Spring Levy
before ending. (Outcomes: greedy s1 -> box3 Christian 5.2; strategic s1 -> box4
Christian 5.2; random s2 -> box5 Muslim 5.2; sustain s99 -> box13 Christian 5.2.)

VERIFIED (trust-but-verify): independently replayed ChatGPT's greedy-seed-1
action history (218 actions) through the engine with full-fanout over-enum
probing + invariants at every step -> reproduced exactly (box 3, Christian win,
0 over-enum / 0 invariant breaks / 0 rejections). The clean result is real, not
a harness-misuse artifact.

CONFIRMED CROSS-TESTER OBSERVATION (not a bug): naive automated policies tend to
end early by Campaign Victory (5.2 — a side reduced to no Mustered Lords),
because keeping both sides mustered+paid through the Calendar requires
deliberate play. Both this project's survivalist run (reached box 15, natural VP
end) and ChatGPT's sustain run (box 13) confirm the late game IS reachable; it
just needs a non-greedy policy. Not a defect — 5.2 fires correctly.

## 2026-06-11 — Scenario F long-scenario audit (Claude playtest session)

Played Scenario F (Reconquista and Riposte, boxes 1-15) via greedy +
strategic agents (30+ seeds), stress_invariants profiles (survival /
combat / siege), and manual history audits against the Rules of Play.
Calendar flow verified in play: Grow at boxes 2/10, Harvest 4/12, Repairs
each Campaign, Winter sequence 7-8 (Disband-to-mats, Winter Siege,
Spring Muster — Alfonso to León, Taifa Lords to free Seats), Scenario End
at box 15; rule 5.2 endings confirmed legitimate for naive agents.

FINDINGS (all fixed, see VERIFICATION_LOG 2026-06-11): Neutral-vs-Enemy
conflation cluster (Ravage/Siege/Storm at Neutral; Supply/Retreat blocked
by Neutral; Avoid-Battle Bypass marking at Neutral), missing 4.3.5 March
stop at empty Enemy Strongholds (lone-Lord sieges were impossible),
Bypass-then-March-away on the same card, end_card x T4 pending/active
desync, and Disband-at-own-Stronghold ordering (departing Taifa Lord
force-Conquered his own city via HOSTAGE POPULACE).
