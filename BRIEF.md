# Almoravid Harness — Project Specification

## Goal

A Python harness for *Almoravid: Reconquista and Crusade in Spain, 1085–1086* (GMT Games). The harness holds full game state, validates and executes all rules-defined actions, runs Battle and Storm engagements automatically, rolls all dice, manages the Calendar / Levy / Campaign cycle, and exposes a structured interface designed to be consumed by an LLM (Claude or ChatGPT) playing one or both sides.

The user supplies strategic judgment via the LLM. The user adjudicates rules ambiguities surfaced during development. The harness supplies everything else: state, rules enforcement, mechanical resolution.

This is a private project. Code quality should be good enough for the user to maintain, not for external readers.

## Authoritative Sources (Priority Order)

1. **Almoravid Official Errata** AND **Almoravid Scenario Adjustments (2022-09)** — both override any conflict in the Rules of Play, Background Book, foldout, scenario mats, or card text. These two documents are co-equal at the top of the chain. The Errata file in the project's curated `.txt` collection is the text companion to the Errata PDF; both name the same corrections.
2. **The curated reference .txt files in the repo**: Lords, Battle and Storm Reference, Sequence of Play v2, Arts of War Reference, Scenario Reference, Map, Quick Reference, Strategy Notes. These are designer-clarified distillations and are the FIRST stop for any question about card text, capability mechanics, or rule interpretation. The Tips paragraphs in the Arts of War Reference in particular contain Volko Ruhnke's clarifications that resolve most apparent ambiguities without further escalation.
3. **Rules of Play PDF** (Almoravid rulebook). Used to confirm what's in the .txt references when something is missing from them. NOTE: the rulebook PDF is not yet in the repo's `source/` directory; until it is, the .txt references are the primary rules source and questions that would require rulebook confirmation should be logged as Q-NNN.
4. **Player Aid Sheet PDF** — procedural summary. Authoritative for the procedures and tables it reproduces (Sequence of Play, Battle/Storm steps, capacity, Spoils, etc.). When the Player Aid and a .txt reference state the same procedure, both are correct; when they differ, fall through to the consultation chain. Errata corrections apply to the Player Aid Sheet the same way they apply to other published materials.
5. **Background Book PDF** — scenario walkthroughs, design notes, examples. Read for mechanical content (worked examples of edge cases, capability interactions, sequencing). Ignore the historical claims. A worked example in the Background Book can resolve "how does X actually play out?" when the rules text is terse.
6. **Almoravid Taifa PDF** — campaign-aid document covering Taifa Politics in detail. Authoritative for what it documents about Taifa status, transitions, and Stronghold/marker effects.

All PDFs in the repo's `source/` directory are first-class build inputs, not just illustrative material. Treat them as ordinary readable files. The PDF-restriction language elsewhere in this project's tooling is about external/web PDFs, not the in-repo PDFs.

When sources conflict, higher priority wins. **Scenario Adjustments and Errata trump the printed scenario rules and card text.** For Q-NNN consultation, the FIRST step is always the relevant .txt reference file's section (Battle and Storm, Arts of War Reference, Sequence of Play v2, etc.). Skipping that step is a process bug. The .txt references are not optional starting material — they are the canonical answers.

## Scope of Inquiry — Hard Constraint

This is a software project to encode a board game's rules. It is NOT a historical research project. The game's setting in late-11th-century Iberia is theme, not subject matter.

**Sources you may consult:**

- The repo's reference .txt files.
- The repo's PDFs (Rules of Play, Background Book, PAC, foldout).
- Standard Python documentation, language references, and library docs needed to write the code.
- Files in the repo that the user has placed there.

**Sources you may NOT consult without explicit user instruction:**

- Wikipedia, encyclopedias, or any general-knowledge reference on the historical period, persons, places, battles, or events.
- Academic or popular history sources on the Reconquista, the Almoravid dynasty, the Taifas, or related topics — even when the rulebook or Background Book references them.
- Other GMT board games or board game databases (BoardGameGeek, Consimworld) for comparative rules interpretation, including the rest of the Levy & Campaign series (Nevsky, Inferno, Plantagenet, etc.). Almoravid's rules are not Nevsky's rules. Inferring an Almoravid mechanic from a Nevsky equivalent is a bug, not a shortcut. If a question arises about an Almoravid mechanic, the answer must come from Almoravid's own references, sources, errata, or the user — never from Nevsky.
- Your own pre-existing knowledge of Almoravid or its themes when that knowledge comes from outside the repo files. If you find yourself "remembering" something about Almoravid, treat that memory as if it doesn't exist; consult the repo files instead.
- Web searches of any kind related to the game's subject matter.

## Why This Matters

Proper names and identifiers (Alfonso, Yusuf, al-Mutamid, al-Mundir, Álvar Fáñez, Sevilla, Lérida, Trujillo, Hasham, Mesnada, Ribat Monks) are tokens used by the rules to identify specific game pieces with specific game stats. Their historical referents are irrelevant to the harness. Encoding any historical "fact" as game logic is a bug, not a feature. Examples of forbidden reasoning:

- "Historically Yusuf landed in 1086, so he should enter on a specific Calendar box" — WRONG. The scenarios specify when each Lord becomes available; the rules override the history.
- "The Almoravids historically used drums in battle, so units should get a morale bonus" — WRONG. The rules specify which Arts of War cards exist and what they do; nothing else.
- "Knights historically had heavier armor than Sergeants, so Knights should have better Protection" — WRONG. The Forces table specifies Protection ranges; that is the only source.
- "The historical Sagrajas campaign ended in a Muslim victory, so the harness should weight victory conditions accordingly" — WRONG. Victory is whatever the Victory rules and the scenario specify.

## What to Do When the Rules Reference History

The Rules of Play and Background Book contain historical commentary, design notes, and flavor text. Read them only for the game-mechanical content they contain. Ignore the historical claims. If a Design Note explains that a particular capability card represents a real historical institution, the rule text on the card is the input; the design rationale is not.

## What to Do If You Think You Need Historical Context to Resolve an Ambiguity

You don't. If a rule is ambiguous, the resolution path is the consultation chain (below), then the user. Historical "what actually happened" is never an input. If you find yourself reaching for context outside the repo to formulate or resolve a question, that is itself a signal the question needs to go to the user. Do not fill in the gap from general knowledge.

## Names and Identifiers

You may and should use proper names from the game (Lords, Vassals, Locales, Capabilities, Strongholds, Taifas) for state tracking, code identifiers, file names, comments, and user-facing displays. Use them exactly as the rules use them. Do not annotate them with historical context, do not gloss them, do not transliterate alternates. The rules' spelling and form are canonical even where the historical record uses different conventions.

## Rules Accuracy Trumps Simplification — HARD CONSTRAINT

Where the rules are clear, the harness MUST implement them faithfully. Simplifications, approximations, "Phase N+ deferrals", and convenience shortcuts are NOT acceptable when the rules are explicit about a behavior.

The only acceptable reasons to depart from the rules are:

1. The rules are ambiguous (→ follow the Ambiguity Policy / Q-NNN consultation chain below).
2. The user has explicitly adjudicated a deviation (recorded in `RULES_DECISIONS.md` as `[HOUSE RULE]`).

Reasons that are NOT acceptable:

- "Easier to implement this way."
- "Phase N is just a stub; Phase N+1 will fix it."
- "Most games won't hit this case."
- "The simplification is conservative / lenient."

When implementing a feature, if the chosen approach diverges from the rules in any measurable way, the divergence MUST be either:

a. Fixed in the same PR before merge.
b. Logged as a Q-NNN in `RULES_QUESTIONS.md` and surfaced to the user before merge.

Code comments that say "simplified", "approximated", "deferred", or similar are flags for audit. Each must trace to either a Q-NNN, a `[HOUSE RULE]` decision, or a future-phase commitment with an explicit issue tracking it.

## Ambiguity Policy

The harness encodes rules deterministically. Every rule encoded in code must trace to a source. The user is the sole authority on rules interpretation when sources are silent or unclear.

### Consultation Chain — REQUIRED Before Logging Any Question

When you encounter anything ambiguous, work through this chain in order and document each step:

1. **Curated reference file.** Identify the most relevant .txt file (Battle and Storm Reference for combat, Sequence of Play v2 for turn order and Levy/Campaign structure, Arts of War Reference for card text and capability mechanics, Lords for Lord stats and Service, Scenario Reference for scenario-specific setup and special rules, Map for geography and Ways, Quick Reference for the synthesis tables on Forces, Strongholds, Commands, Taifa Politics, and Adjust Status) and read the relevant section IN FULL. The Tips paragraphs in the Arts of War Reference are designer-clarified text and resolve most apparent ambiguity about card mechanics on their own. If the answer is in the .txt reference, the consultation ends here and the question does not need to be logged.

2. **Errata and Scenario Adjustments.** Check whether the area you're working in is touched by an Errata correction or by the Scenario Adjustments document. Both are terse but binding, and either can override card text, scenario mat text, or rules-of-play text.

3. **Rules of Play PDF.** Confirm or fill in details the .txt reference omits. The Rules of Play is the original source the .txt references distill from; if a `.txt` reference is silent on a detail the rulebook covers explicitly, the rulebook governs.

4. **Background Book.** Consult only for clarifying examples of game mechanics. Do not treat narrative or historical text as a rules source.

5. **Q-NNN in `RULES_QUESTIONS.md`.** If the chain above does not resolve the question, log it. Cite which sources you checked and what each said. Surface to the user before merging the affected code.

## Key Almoravid Concepts the Harness Must Model

This is a non-exhaustive orientation for someone (LLM or human) starting to navigate the codebase; it is not a substitute for the references. The list names the moving parts the harness must track and enforce.

- **Calendar** with Levy and Campaign turns; Curias on Scenario F (per Errata).
- **Lords** with Service, Command, Lordship, Seats, Vassals, mats holding Forces, Capabilities, and Assets (Coin, Loot, Provender, Transport).
- **Forces**: Knights, Sergeants, African Horse, Light Horse (Horse); Men-at-Arms, African Foot, Militia, Serfs (Foot). Each has a fixed Strikes profile, Protection range, and conditional Strikes-by-Capability and Strikes-by-Garrison rows.
- **Capabilities** drawn from the Arts of War deck (C-prefixed Christian, M-prefixed Muslim), as Capability (bottom-half) or Event (top-half). Each modifies Strikes, Protection, Lord ratings, or triggers a one-shot effect.
- **Strongholds**: City (with Gardens), Fortress (with Gardens), Town, Castle. Each has Capacity, Stronghold Value, Walls range, fixed Garrison composition, Surrender dice, and Spoils.
- **Taifa Politics** (1.4): four states — Independent, Parias, Reconquista, Kingdoms (Aragón, León). Status transitions per the Adjust Status table cascade Conquered / Jihad / Ravaged marker changes and can force Sieges or Conquests on Lords present at affected Strongholds.
- **Commands**: March (two actions if Laden), Siege, Storm, Sally, Supply, Forage (Unravaged or Friendly Fortress/City; Gardens for Besieged), Ravage, Tax, Pass.
- **Sharing** of Assets among Lords at the same Locale (1.5.2).
- **Conquest markers** (1 VP each) and **Jihad markers** (1/2 VP each), placed by Stronghold Value.
- **Ravaged state** of Locales, flipped yellow↔green by Taifa status transitions.
- **Battle** with Strike rounds and Hit/Protection resolution; **Storm** as a single round of strikes against and from the Garrison; **Sally** as the Besieged variant.
- **Service limit, At-Service and Beyond-Service behavior** per Errata 3.3.1/3.3.2.

## Project Layout (Anticipated)

Mirroring the Nevsky harness convention. Subject to change as the project develops.

- `src/almoravid/` — state, actions, legal_moves, battle, campaign, capabilities, events, map, scenarios, render, previews, rng, static_data, cli.
- `src/almoravid/data/scenarios/` — one JSON per scenario (A through F).
- `src/almoravid/data/static/` — lords, forces, cards, strongholds, locales (Taifas + Christian territories), ways.
- `src/almoravid/data/schema/` — JSON schema for state.
- `tests/` — playthrough harnesses and unit tests.
- `reference/` — the curated .txt files (the project's existing docs).
- `source/` — Rules of Play, Background Book, Player Aid Sheet, Errata, Scenario Adjustments, Taifa aid, foldout PDFs.
- `scripts/` — schema generation, self-play, sweeps.
- Top-level: `BRIEF.md` (this file), `ACTIONS.md`, `RULES_DECISIONS.md`, `RULES_QUESTIONS.md`, `STRATEGY_DIGEST.md`, `PLAYTESTS.md`, `SMOKE_TEST_FINDINGS.md`, `pyproject.toml`, `README.md`.

## Out of Scope (For Now)

- Solo bot AI; the harness is designed for an LLM to drive each side. Self-play is two LLM seats sharing the same interface.
- Networked multiplayer or a GUI. The interface is a CLI plus structured state for an LLM to consume.
- Variant rules, fan content, or unofficial errata beyond `Almoravid Errata.txt`.

## Development Process: Bug-Pattern C