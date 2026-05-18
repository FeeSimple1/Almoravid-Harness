"""Battle resolution (rule 4.4).

Phase 5e scope: single-Lord-each-side Battle with full Strike-Hit-
Protection-Rout resolution. Multi-Lord arrays (Flanking, Reserves,
Front center/left/right) are Phase 5e+ work; the structural shape is
in place (BattleSide carries lord_ids as a list, BattleResult tracks
rounds) so the round loop can be extended without revisiting call
sites.

Strike order per rule 4.4.2 (and SoP §4.4.2 strike substeps):
  1.a  Defending Missiles
  1.b  Attacking Missiles
  2.a  Defending Horse Melee
  2.b  Attacking Horse Melee
  2.c  Defending Foot Melee
  2.d  Attacking Foot Melee

Per-step resolution: TotalHits -> AssignTarget -> ProtectionRoll ->
Rout. Hits accumulate in halves; the per-step total rounds UP to the
next whole Hit before Protection rolls (rule 4.4.2 TOTAL HITS,
'rounding_halves' from the Battle & Storm Reference).

Bug-pattern preemption:
  - Pattern 2 (mirror gaps): aftermath helpers are role-aware via
    BattleSide.role and apply for BOTH winner and loser branches.
    Aftermath tests verify each combination.
  - Pattern 7 (card-text fidelity): every capability that grants a
    Strike row hands a card_ids list to build_strike_rows; the
    resolver only adds a row if all required cards are in play.
    Card effects can't drift from card metadata.
  - Pattern 12 (cap/floor): no asset mutations during Battle itself;
    Spoils transfers in Aftermath use min(8, ...) per rule 1.7.3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from almoravid.rng import roll_d6
from almoravid.state import GameState, Side, UnitType
from almoravid.static_data import load_forces


Role = Literal["attacker", "defender"]
StrikeKind = Literal["melee", "missiles", "javelins", "crossbows", "bowmen", "slingers"]
UnitClass = Literal["horse", "foot"]


# Rate string -> (numerator, denominator) for Hit computation
_RATE = {"x2": (2, 1), "x1": (1, 1), "x1/2": (1, 2)}

# Which side strikes in each substep
_BATTLE_STEPS: list[tuple[str, Role, str, UnitClass | None]] = [
    ("1.a", "defender", "missile", None),
    ("1.b", "attacker", "missile", None),
    ("2.a", "defender", "melee", "horse"),
    ("2.b", "attacker", "melee", "horse"),
    ("2.c", "defender", "melee", "foot"),
    ("2.d", "attacker", "melee", "foot"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StrikeRow:
    """One row in a Lord's Strike profile contributed by a unit-type stack."""

    unit_type: UnitType
    count: int                 # number of unrouted units of this type
    kind: StrikeKind
    rate: str                  # "x2", "x1", "x1/2"
    one_round_only: bool = False
    mark_used: bool = False
    card_ids: list[str] = field(default_factory=list)


@dataclass
class BattleSide:
    """One side of an engagement."""

    side: Side
    role: Role
    lord_ids: list[str]
    forces: dict[UnitType, int]
    capabilities_in_play: list[str] = field(default_factory=list)
    routed_units: dict[UnitType, int] = field(default_factory=dict)

    def has_unrouted(self) -> bool:
        return any(v > 0 for v in self.forces.values())

    def total_unrouted(self) -> int:
        return sum(self.forces.values())


@dataclass
class StepResolution:
    """Outcome of one Strike substep."""

    step: str                  # "1.a" etc.
    actor: Role
    raw_hits: float = 0.0      # accumulated halves before rounding
    rounded_hits: int = 0
    losses: dict[UnitType, int] = field(default_factory=dict)


@dataclass
class BattleRound:
    """One Strike Round (rule 4.4.2)."""

    index: int
    steps: list[StepResolution] = field(default_factory=list)


@dataclass
class BattleResult:
    """Outcome of one Battle (Phase 5e: single-Lord-each-side)."""

    engagement: Literal["battle", "storm", "sally"]
    attacker: BattleSide
    defender: BattleSide
    rounds: list[BattleRound] = field(default_factory=list)
    winner: Side | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Strike-row construction
# ---------------------------------------------------------------------------


def build_strike_rows(
    state: GameState,
    side: BattleSide,
    *,
    context: Literal["battle", "storm"] = "battle",
) -> list[StrikeRow]:
    """Construct all StrikeRows a side will fire in a Round (Pattern 7).

    Includes base strikes_battle/strikes_storm rows AND capability-gated
    rows when the required card_ids are present in capabilities_in_play.
    """
    forces_data = load_forces()
    caps_in_play = set(side.capabilities_in_play)
    rows: list[StrikeRow] = []

    for unit_type, count in side.forces.items():
        if count <= 0:
            continue
        unit = None
        for category in ("horse", "foot"):
            if unit_type in forces_data[category]:
                unit = forces_data[category][unit_type]
                break
        if unit is None:
            continue
        # Base strikes
        for s in unit[f"strikes_{context}"]:
            rows.append(StrikeRow(
                unit_type=unit_type,
                count=count,
                kind=s["kind"],
                rate=s["rate"],
                one_round_only=s.get("any_one_round", False),
            ))
        # Capability-gated strikes (Pattern 7: card_ids must be in play).
        for cap_row in unit.get("strikes_by_capability", []):
            required = set(cap_row.get("card_ids", []))
            if required and required & caps_in_play:
                rows.append(StrikeRow(
                    unit_type=unit_type,
                    count=count,
                    kind=cap_row["kind"],
                    rate=cap_row["rate"],
                    one_round_only=cap_row.get("any_one_round", False),
                    card_ids=sorted(required & caps_in_play),
                ))
    return rows


def _unit_class(unit_type: UnitType) -> UnitClass:
    forces_data = load_forces()
    if unit_type in forces_data["horse"]:
        return "horse"
    return "foot"


# ---------------------------------------------------------------------------
# Strike step resolution
# ---------------------------------------------------------------------------


def _step_hits(
    rows: list[StrikeRow],
    step_type: str,
    unit_class: UnitClass | None,
) -> float:
    """Total raw Hits (in halves) for the named step.

    step_type == 'missile': sum all missile/crossbows/bowmen/slingers/
    javelins rows that aren't melee.
    step_type == 'melee': sum all melee rows for the given unit_class.
    """
    total = 0.0
    for r in rows:
        if step_type == "missile":
            if r.kind == "melee":
                continue
        else:  # melee
            if r.kind != "melee":
                continue
            if _unit_class(r.unit_type) != unit_class:
                continue
        num, den = _RATE.get(r.rate, (0, 1))
        total += (r.count * num) / den
    return total


def _resolve_protection_roll(
    state: GameState,
    target_side: BattleSide,
    striker_kind: StrikeKind,
    *,
    context: Literal["battle", "storm"] = "battle",
) -> tuple[bool, UnitType | None]:
    """Roll Protection for one Hit. Returns (canceled, unit_routed).

    Phase 5e: defender picks the unit that takes the Hit (rule 4.4.2
    ASSIGN HITS); for now we pick the first available unrouted unit
    deterministically (highest-Protection first to maximize cancel
    chance — a reasonable greedy default).

    Pattern 9 audit fix (Bug H): Evade Protection (rule 4.4.2 + Forces
    table 'Evade range') is applied for units with an evade row in their
    Protection spec, ONLY when the striker_kind is 'melee' AND
    context == 'battle'. Evade does NOT apply to Missile Hits or to
    any Storm Hits. Affected units: African Horse (Evade 1-2 vs Battle
    Melee per Quick Ref Table 1) and Light Horse with M10 Andalusians
    (Evade 1-3 vs Battle Melee).
    """
    forces_data = load_forces()

    # Build candidate units: prefer Armored over Unarmored, since Armored
    # has the best chance of canceling Hits.
    candidates: list[tuple[int, UnitType]] = []  # (priority, type)
    for unit_type, count in target_side.forces.items():
        if count <= 0:
            continue
        # Find unit record
        unit = None
        for cat in ("horse", "foot"):
            if unit_type in forces_data[cat]:
                unit = forces_data[cat][unit_type]
                break
        if unit is None:
            continue
        ptype = unit["protection"]["type"]
        # Pure deterministic priority: armored > unarmored > auto_remove
        # (so we save Serfs for last — but they auto-rout regardless).
        prio = {"armored": 0, "unarmored": 1, "auto_remove": 2,
                "none": 3}.get(ptype, 4)
        candidates.append((prio, unit_type))
    if not candidates:
        return (False, None)
    candidates.sort()
    _, chosen = candidates[0]
    unit = None
    for cat in ("horse", "foot"):
        if chosen in forces_data[cat]:
            unit = forces_data[cat][chosen]
            break
    assert unit is not None
    ptype = unit["protection"]["type"]
    # Serfs auto-rout
    if ptype == "auto_remove":
        target_side.forces[chosen] -= 1
        if target_side.forces[chosen] <= 0:
            target_side.forces.pop(chosen, None)
        target_side.routed_units[chosen] = target_side.routed_units.get(chosen, 0) + 1
        return (False, chosen)
    # Roll Protection
    rng = roll_d6(state)
    canceled = False
    if ptype == "armored":
        lo, hi = unit["protection"]["range"]
        if lo <= rng <= hi:
            canceled = True
    elif ptype == "unarmored":
        if rng == 1:
            canceled = True
        # Bug H (Pattern 9 audit) — Evade Protection: unit's spec may
        # include an 'evade' clause with its own range that supplements
        # Unarmored, but ONLY for Battle Melee Hits (not Missiles, not
        # Storm). African Horse: Evade 1-2; Light Horse + M10
        # Andalusians: Evade 1-3 (M10 not yet wired). Apply when
        # context='battle' and striker_kind=='melee'.
        if (not canceled
                and context == "battle"
                and striker_kind == "melee"
                and "evade" in unit["protection"]):
            elo, ehi = unit["protection"]["evade"]["range"]
            if elo <= rng <= ehi:
                canceled = True
    if canceled:
        return (True, None)
    # Failed Protection -> Rout
    target_side.forces[chosen] -= 1
    if target_side.forces[chosen] <= 0:
        target_side.forces.pop(chosen, None)
    target_side.routed_units[chosen] = target_side.routed_units.get(chosen, 0) + 1
    return (False, chosen)


def _resolve_step(
    state: GameState,
    step_id: str,
    actor_role: Role,
    step_type: str,
    unit_class: UnitClass | None,
    attacker: BattleSide,
    defender: BattleSide,
    context: Literal["battle", "storm"] = "battle",
    walls_range: tuple[int, int] | None = None,
    siege_markers: int = 0,
) -> StepResolution:
    actor = attacker if actor_role == "attacker" else defender
    target = defender if actor_role == "attacker" else attacker

    rows = build_strike_rows(state, actor, context=context)
    raw = _step_hits(rows, step_type, unit_class)
    rounded = math.ceil(raw)

    # Bug-fix E (Pattern 9 audit): rule 4.5.2 cap — in Storm each Lord
    # adds at most 6 Melee Hits per Round; Missiles unlimited. Apply
    # per-actor-side (single-Lord baseline; multi-Lord arrays are
    # Phase 5e+ and will cap per Lord).
    if context == "storm" and step_type == "melee":
        rounded = min(rounded, 6)

    result = StepResolution(step=step_id, actor=actor_role,
                            raw_hits=raw, rounded_hits=rounded)

    # Bug-fix D (Pattern 9 audit): rule 4.4.2 ROLL WALLS — in Storm /
    # Sally, side benefiting from Walls rolls dice = total Hits in
    # this step; each die <= walls_range cancels 1 Hit. Siegeworks-as-
    # Walls similarly. Defender side in Storm benefits from Walls;
    # attacker side benefits from Siegeworks. We apply Walls to Hits
    # FOR the side being struck (the target).
    hits_to_apply = rounded
    if walls_range is not None and rounded > 0:
        # Which side benefits depends on direction:
        # - If actor is attacker striking defender: Walls protect defender.
        # - If actor is defender striking attacker: Siegeworks (Siege
        #   markers acting as Walls) protect attacker.
        if actor_role == "attacker":
            wlo, whi = walls_range
            dice = [roll_d6(state) for _ in range(rounded)]
            canceled = sum(1 for d in dice if wlo <= d <= whi)
            hits_to_apply = rounded - canceled
        elif actor_role == "defender" and siege_markers > 0:
            # Siegeworks: attacker rolls dice = total Hits; each <=
            # siege_markers cancels 1 Hit (rule 4.4.2 / 4.5.2).
            dice = [roll_d6(state) for _ in range(rounded)]
            canceled = sum(1 for d in dice if d <= siege_markers)
            hits_to_apply = rounded - canceled

    # Apply each remaining Hit to the target.
    striker_kind: StrikeKind = "melee" if step_type == "melee" else "missiles"
    for _ in range(hits_to_apply):
        if not target.has_unrouted():
            break
        _, routed = _resolve_protection_roll(state, target, striker_kind,
                                                context=context)
        if routed is not None:
            result.losses[routed] = result.losses.get(routed, 0) + 1
    return result


# ---------------------------------------------------------------------------
# Round / Battle loop
# ---------------------------------------------------------------------------


def _battle_over(attacker: BattleSide, defender: BattleSide) -> bool:
    """Per rule 4.4.2 new_round_check: end when either side has all
    Lords (here: units) Routed. Multi-Lord arrays will refine to
    'all Lords Routed' once Reserves/Front are modeled."""
    return not attacker.has_unrouted() or not defender.has_unrouted()


def resolve_battle(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    *,
    max_rounds: int = 6,
) -> BattleResult:
    """Full Battle resolution per rule 4.4 (Phase 5e: single-Lord case).

    Loops Rounds until one side has no unrouted units, capped at
    max_rounds to bound runaway. Each Round runs the 6 Strike substeps
    in canonical order with full Protection rolls.

    Winner = side with unrouted units when battle ends.
    """
    result = BattleResult(
        engagement="battle",
        attacker=attacker,
        defender=defender,
    )
    for round_idx in range(1, max_rounds + 1):
        rnd = BattleRound(index=round_idx)
        for step_id, actor_role, step_type, unit_class in _BATTLE_STEPS:
            step_res = _resolve_step(state, step_id, actor_role, step_type,
                                      unit_class, attacker, defender)
            rnd.steps.append(step_res)
            if _battle_over(attacker, defender):
                break
        result.rounds.append(rnd)
        if _battle_over(attacker, defender):
            break
    if attacker.has_unrouted() and not defender.has_unrouted():
        result.winner = attacker.side
    elif defender.has_unrouted() and not attacker.has_unrouted():
        result.winner = defender.side
    else:
        result.winner = None
        result.notes.append("Battle inconclusive after max rounds")
    return result


# ---------------------------------------------------------------------------
# Aftermath helpers (Pattern 2 mirror-gap audit applies — winner-side
# AND loser-side branches must both call the corresponding helpers).
# ---------------------------------------------------------------------------


def apply_aftermath(
    state: GameState,
    result: BattleResult,
) -> None:
    """Battle aftermath (rule 4.4.5).

    Phase 5e baseline + Bug J fix (Pattern 13 audit):
      - Mark all participating Lords Moved/Fought.
      - Restore winner's routed_units back to forces (rule 4.4.3
        'winner doesn't suffer Losses' — SMOKE-098/099 in Nevsky).
        Pattern 2: this restore must fire for the winner regardless
        of which side won.
      - Discard all 'Hold' Events used in this Battle/Storm per rule
        4.4.5 — bug-fix J: this_levy_events bucket was accumulating
        forever; events now move to decks.discard at aftermath. Both
        sides' buckets clear (the cards triggered for this engagement
        regardless of which side held them).
      - Loser keeps routed_units in routed (they're 'Losses' that
        need Service-shift / permanent removal in real play; full
        implementation lands with the Service mutators).
    """
    for lord_id in result.attacker.lord_ids + result.defender.lord_ids:
        if lord_id in state.lords:
            state.lords[lord_id].moved_fought = True

    # Pattern 2: winner restores routed_units. Apply to whichever side
    # actually won — the helper is role-aware.
    if result.winner == result.attacker.side:
        _restore_routed_to_forces(state, result.attacker)
    elif result.winner == result.defender.side:
        _restore_routed_to_forces(state, result.defender)

    # Bug J (Pattern 13): clear this_levy_events; discard the held cards.
    for side_key, cards in list(state.decks.this_levy_events.items()):
        state.decks.discard.extend(cards)
    state.decks.this_levy_events = {}


def _restore_routed_to_forces(state: GameState, side: BattleSide) -> None:
    """Winner: push routed_units back to forces (rule 4.4.3)."""
    for ut, n in side.routed_units.items():
        side.forces[ut] = side.forces.get(ut, 0) + n
        # Also push to the Lord's state if a single Lord (Phase 5e baseline)
        if len(side.lord_ids) == 1:
            lord = state.lords[side.lord_ids[0]]
            lord.forces[ut] = lord.forces.get(ut, 0) + n
    side.routed_units = {}


# ---------------------------------------------------------------------------
# Helpers for action-handler integration
# ---------------------------------------------------------------------------


def battleside_for_lord(
    state: GameState, lord_id: str, role: Role,
) -> BattleSide:
    """Construct a single-Lord BattleSide from state for use by handlers."""
    lord = state.lords[lord_id]
    return BattleSide(
        side=lord.side,
        role=role,
        lord_ids=[lord_id],
        forces=dict(lord.forces),
        capabilities_in_play=list(lord.capabilities),
    )


def commit_forces_after_battle(state: GameState, side: BattleSide) -> None:
    """Write the (post-Battle) forces dict back to each Lord's state.

    Only valid for single-Lord sides in Phase 5e. Multi-Lord aggregation
    needs per-Lord force tracking inside BattleSide.
    """
    if len(side.lord_ids) != 1:
        raise NotImplementedError(
            "multi-Lord force commit-back is Phase 5e+ work"
        )
    lord = state.lords[side.lord_ids[0]]
    lord.forces = dict(side.forces)
    # Routed units stay on the Lord's routed_units for Service-shift
    # processing in Phase 5h Feed/Pay/Disband.
    lord.routed_units = dict(side.routed_units)



# ---------------------------------------------------------------------------
# Storm (4.5.2) — variant Battle vs Garrison
# ---------------------------------------------------------------------------


def _garrison_for_locale(state: GameState, locale_id: str) -> dict:
    """Build a Garrison BattleSide partial (forces + cap modifiers) from
    strongholds.json. Returns dict suitable for BattleSide(forces=...).
    """
    from almoravid.static_data import load_strongholds
    loc = state.locales[locale_id]
    if loc.base_type == "region":
        return {}
    sh = load_strongholds()["strongholds"][loc.base_type]
    g = sh["garrison"]
    out = {}
    if g.get("men_at_arms", 0):
        out["men_at_arms"] = g["men_at_arms"]
    if g.get("militia", 0):
        out["militia"] = g["militia"]
    return out


def resolve_storm(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    *,
    max_rounds: int | None = None,
) -> BattleResult:
    """4.5.2 Storm. Attacker assaults the Stronghold's Garrison + any
    defending Lord units inside.

    Phase 5f baseline: defender's forces include Garrison (auto-loaded
    from strongholds.json) ADDED to whatever besieged Lord forces are
    inside the Stronghold. Walls roll cancels Hits (Pattern 5/6: roll
    within stronghold's walls_range cancels). Evade does NOT apply in
    Storm. Javelins/Slingers Strike x1/2 in Storm (forces.json already
    encodes this distinction in strikes_storm rows).

    max_rounds defaults to the number of Siege markers our side has
    at the Locale (rule 4.5.2 'Rounds completed >= Siege markers ->
    Attacker loses'). For Phase 5f baseline we use the count of our
    color's siege markers as the cap.
    """
    # Load walls range
    from almoravid.static_data import load_strongholds
    locale_id = None
    # Find the locale the defender is at
    for lid in defender.lord_ids:
        l = state.lords.get(lid)
        if l and l.cylinder.kind == "locale":
            locale_id = l.cylinder.locale_id
            break
    if locale_id is None:
        # Fallback: use attacker's location (besieger outside the walls)
        for lid in attacker.lord_ids:
            l = state.lords.get(lid)
            if l and l.cylinder.kind == "locale":
                locale_id = l.cylinder.locale_id
                break
    walls_range = (1, 4)
    if locale_id is not None:
        loc = state.locales[locale_id]
        if loc.base_type != "region":
            walls_range = tuple(
                load_strongholds()["strongholds"][loc.base_type]["walls_range"]
            )
        # Storm cap = Siege markers our side has (rule 4.5.2)
        if max_rounds is None:
            siege = (loc.siege_yellow if attacker.side == "christian"
                     else loc.siege_green)
            max_rounds = max(1, siege)

    if max_rounds is None:
        max_rounds = 4

    # Add Garrison to defender's forces (Phase 5f baseline).
    garrison = _garrison_for_locale(state, locale_id) if locale_id else {}
    for ut, n in garrison.items():
        defender.forces[ut] = defender.forces.get(ut, 0) + n

    # Storm strike order: defender (all stronghold defenders) -> attacker (all).
    # In Storm there are only 2 melee substeps after missiles (per SoP).
    result = BattleResult(
        engagement="storm",
        attacker=attacker,
        defender=defender,
    )
    storm_steps: list[tuple[str, Role, str, UnitClass | None]] = [
        ("1.a", "defender", "missile", None),
        ("1.b", "attacker", "missile", None),
        ("2.a", "defender", "melee", "horse"),   # combined with foot via 'all'
        ("2.a", "defender", "melee", "foot"),
        ("2.b", "attacker", "melee", "horse"),
        ("2.b", "attacker", "melee", "foot"),
    ]
    # Siegeworks count for attacker's protection (the besieger's Siege
    # markers serve as Walls for the attacker during Storm — rule
    # 4.5.2 'attacker_siegeworks_placement: place Siegeworks as Walls').
    siegeworks_count = 0
    if locale_id is not None:
        loc = state.locales[locale_id]
        siegeworks_count = (loc.siege_yellow if attacker.side == "christian"
                            else loc.siege_green)
    for round_idx in range(1, max_rounds + 1):
        rnd = BattleRound(index=round_idx)
        for step_id, actor_role, step_type, unit_class in storm_steps:
            step_res = _resolve_step(
                state, step_id, actor_role, step_type, unit_class,
                attacker, defender, context="storm",
                walls_range=walls_range,
                siege_markers=siegeworks_count,
            )
            rnd.steps.append(step_res)
            if _battle_over(attacker, defender):
                break
        result.rounds.append(rnd)
        if _battle_over(attacker, defender):
            break
    # Rule 4.5.2: 'Rounds completed >= Siege markers there (Attacker loses)'
    if attacker.has_unrouted() and not defender.has_unrouted():
        result.winner = attacker.side
    elif defender.has_unrouted() and not attacker.has_unrouted():
        result.winner = defender.side
    elif len(result.rounds) >= max_rounds:
        # Attacker loses if rounds run out
        result.winner = defender.side
        result.notes.append(
            f"Storm round-cap reached ({max_rounds}); attacker loses"
        )
    return result


# ---------------------------------------------------------------------------
# Sally (4.5.3) — besieged Lord attacks besieger
# ---------------------------------------------------------------------------


def resolve_sally(
    state: GameState,
    attacker: BattleSide,    # the BESIEGED Lord(s) — sallying out
    defender: BattleSide,    # the besieger
) -> BattleResult:
    """4.5.3 Sally. The Besieged Lord attacks the besieger.

    Mechanics are like Battle (no Walls protection — the Sallying side
    is OUTSIDE the walls for this action). Phase 5f baseline:
    structurally a Battle with engagement='sally'. On attacker loss,
    Sallying Lords Withdraw back into the Stronghold and Siege markers
    there reduce to 1 (per rule 4.5.3 / SoP on_attacker_loss).
    """
    result = resolve_battle(state, attacker, defender)
    result.engagement = "sally"
    # Sally-specific aftermath flag — actual Withdraw-back and Siege
    # marker reduction happen in apply_sally_aftermath called from the
    # cmd_sally handler.
    return result


def apply_sally_aftermath(state: GameState, result: BattleResult,
                          locale_id: str) -> None:
    """Sally-specific aftermath (rule 4.5.3 / SoP on_attacker_loss).

    If the Sallying side lost: their Lords Withdraw back into the
    Stronghold (in_stronghold=True) and Siege markers there reduce to 1.
    """
    apply_aftermath(state, result)
    sallying_side = result.attacker.side
    if result.winner == sallying_side:
        return  # Sally succeeded; no Siege-reduction trigger.
    # Sallying side lost: Withdraw back inside, reduce Siege to 1.
    for lid in result.attacker.lord_ids:
        if lid in state.lords:
            state.lords[lid].in_stronghold = True
    loc = state.locales[locale_id]
    if sallying_side == "muslim":
        if loc.siege_yellow > 1:
            loc.siege_yellow = 1
    else:
        if loc.siege_green > 1:
            loc.siege_green = 1
    result.notes.append(
        f"Sally raid: {sallying_side} withdrew, siege at {locale_id} "
        f"reduced to 1"
    )
