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


ArrayPosition = Literal["front_center", "front_left", "front_right",
                        "reserve", "routed"]


@dataclass
class LordPosition:
    """Per-Lord Array slot for multi-Lord Battles (Phase 6e).

    Tracks the Lord's forces, capabilities, and position separately
    so Pair-based Strike resolution and Reposition (rout-removal +
    Reserve advance) can operate per-Lord rather than via pooled
    forces. The pooled BattleSide.forces remains the source of truth
    for single-Lord Battles and as the aggregate view used by
    legacy code paths.

    Phase 6g: `m7_marked` reflects per-Lord M7 Spear Wall markers
    (card text: two Muslim Lords selected at play). When set, the
    per-Lord protection-roll helper applies Armor +1 to this Lord's
    Armored Foot vs Christian Horse Melee.
    """

    lord_id: str
    position: ArrayPosition
    forces: dict[UnitType, int]
    capabilities_in_play: list[str] = field(default_factory=list)
    routed_units: dict[UnitType, int] = field(default_factory=dict)
    m7_marked: bool = False

    def has_unrouted(self) -> bool:
        return any(v > 0 for v in self.forces.values())


@dataclass
class BattleSide:
    """One side of an engagement.

    Bug M (Pattern 7 audit) — Storm requires Garrison-vs-Lord unit
    provenance because rule 4.5.2 says 'Garrison absorbs Hits BEFORE
    any Defending Lord units'. `garrison_forces` is populated by
    resolve_storm; outside Storm context it's empty. When taking a
    Hit during Storm, the protection-roll helper drains garrison_forces
    before forces.

    Phase 6e: `array` is the per-Lord position tracking for multi-Lord
    Battles (rule 4.4.1). Single-Lord BattleSides leave it as None
    (or as a one-entry list with position='front_center') and use the
    legacy pooled resolution path. `conceded` is set when the side
    declares Concede the Field at the start of a Round (rule 4.4.2);
    that side's Strikes are halved for the Round and the Battle ends
    after the Round.
    """

    side: Side
    role: Role
    lord_ids: list[str]
    forces: dict[UnitType, int]
    capabilities_in_play: list[str] = field(default_factory=list)
    routed_units: dict[UnitType, int] = field(default_factory=dict)
    # Garrison units split out for Storm absorption-order (Bug M).
    garrison_forces: dict[UnitType, int] = field(default_factory=dict)
    # Bug T (Pattern 9) — M7 Spear Wall cap.
    m7_boosts_remaining: int = 0
    # Phase 6e: per-Lord Array slots. None for single-Lord (legacy).
    array: list[LordPosition] | None = None
    # Phase 6e: Concede flag set this Round.
    conceded: bool = False

    def has_unrouted(self) -> bool:
        return any(v > 0 for v in self.forces.values()) or any(
            v > 0 for v in self.garrison_forces.values()
        )

    def total_unrouted(self) -> int:
        return sum(self.forces.values()) + sum(self.garrison_forces.values())


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


def init_m7_cap(state: GameState, side: BattleSide) -> None:
    """Phase 6g: set up M7 Spear Wall markers on the Muslim side.

    If side.array is present: place per-Lord m7_marked=True on the
    TWO Muslim Lords with the most MaA + AfricanFoot (per card text:
    Muslim player picks two Lords; we pick greedily for
    determinism). The protection-roll helpers (both pool and per-
    pair paths) consult these markers.

    If side.array is absent (single-Lord or legacy multi-Lord): fall
    back to side.m7_boosts_remaining = cap of top-2 Lords' MaA+AF.
    No-op when M7 is not held or side is not Muslim.
    """
    if side.side != "muslim":
        return
    if "M7" not in state.decks.this_levy_events.get("muslim", []):
        return
    contribs: list[tuple[int, str]] = []
    for lid in side.lord_ids:
        l = state.lords.get(lid)
        if l is None:
            continue
        af = (l.forces.get("men_at_arms", 0)
              + l.forces.get("african_foot", 0))
        contribs.append((af, lid))
    contribs.sort(reverse=True)
    if side.array is not None:
        top_two = {lid for _, lid in contribs[:2]}
        for lp in side.array:
            if lp.lord_id in top_two:
                lp.m7_marked = True
        # Also set the side-level cap so legacy callers that don't
        # consult per-Lord markers (none currently, but defensive)
        # still respect the count.
        side.m7_boosts_remaining = sum(af for af, _ in contribs[:2])
    else:
        side.m7_boosts_remaining = sum(af for af, _ in contribs[:2])


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

    # S3 (4.5.2 GARRISON FORCES DURING STORM): the Garrison adds its
    # Strikes to the Defending Lord's (rounded together by _step_hits).
    # Garrison Men-at-Arms: base Melee (storm) PLUS Crossbow Missiles
    # (-1 Armor, firing side selects target). Garrison Militia: base
    # Melee PLUS regular Bowmen Missiles. The Garrison ignores cards
    # affecting the Lord individually, so no strikes_by_capability here.
    if context == "storm":
        for unit_type, count in side.garrison_forces.items():
            if count <= 0:
                continue
            unit = None
            for category in ("horse", "foot"):
                if unit_type in forces_data[category]:
                    unit = forces_data[category][unit_type]
                    break
            if unit is None:
                continue
            for s in unit["strikes_storm"]:
                rows.append(StrikeRow(
                    unit_type=unit_type, count=count,
                    kind=s["kind"], rate=s["rate"],
                    one_round_only=s.get("any_one_round", False),
                ))
            # Garrison-granted Missile rows (automatic; not card-gated).
            for g_row in unit.get("strikes_by_garrison", []):
                rows.append(StrikeRow(
                    unit_type=unit_type, count=count,
                    kind=g_row["kind"], rate=g_row["rate"],
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
) -> tuple[float, dict[str, float]]:
    """Total raw Hits (in halves) for the named step, plus a per-kind
    breakdown for the mixed-missile rounding rule (4.4.2).

    step_type == 'missile': sum all missile/crossbows/bowmen/slingers/
    javelins rows that aren't melee.
    step_type == 'melee': sum all melee rows for the given unit_class.

    Returns (total, by_kind) where by_kind[strike_kind] is the
    fractional contribution from rows of that kind.
    """
    total = 0.0
    by_kind: dict[str, float] = {}
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
        contrib = (r.count * num) / den
        total += contrib
        by_kind[r.kind] = by_kind.get(r.kind, 0.0) + contrib
    return total, by_kind


def _allocate_rounded_hits(total: float, by_kind: dict[str, float]) -> dict[str, int]:
    """Mixed-missile rounding (rule 4.4.2): allocate rounded Hits to
    kinds, sending the rounded-up half to Crossbows first if present
    (otherwise Bowmen, then Javelins, then Slingers, then Melee).

    Each kind contributes its floor; the leftover (0 or 1 Hit) goes
    to the priority kind that has a non-zero fractional contribution.
    """
    import math as _m
    rounded_total = _m.ceil(total)
    out: dict[str, int] = {}
    floors_sum = 0
    # Allocate floors per kind.
    for kind, contrib in by_kind.items():
        out[kind] = int(_m.floor(contrib))
        floors_sum += out[kind]
    leftover = rounded_total - floors_sum
    if leftover > 0:
        # Mixed-missile priority for the leftover half-Hit.
        priority = ["crossbows", "bowmen", "javelins", "slingers", "missiles", "melee"]
        # Build candidates that contributed a fractional half (i.e.,
        # contrib > floor(contrib)).
        candidates = [k for k in priority
                       if by_kind.get(k, 0.0) > _m.floor(by_kind.get(k, 0.0))]
        if not candidates:
            # All contributions were whole; assign to first kind with non-zero contrib
            candidates = [k for k in priority if by_kind.get(k, 0.0) > 0]
        if candidates:
            out[candidates[0]] = out.get(candidates[0], 0) + leftover
    return out


def _resolve_protection_roll(
    state: GameState,
    target_side: BattleSide,
    striker_kind: StrikeKind,
    *,
    context: Literal["battle", "storm"] = "battle",
    striker_selects: bool = False,
    striker_unit_class: UnitClass | None = None,
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

    # Bug M (Pattern 7 audit) — Storm: drain Garrison units BEFORE
    # Lord units. We try the garrison_forces pool first; only when
    # garrison is empty do we fall through to forces.
    pools: list[tuple[str, dict]] = []
    if context == "storm" and target_side.garrison_forces:
        pools.append(("garrison", target_side.garrison_forces))
    pools.append(("forces", target_side.forces))

    def _build_candidates(pool: dict) -> list[tuple[int, UnitType]]:
        cs: list[tuple[int, UnitType]] = []
        for unit_type, count in pool.items():
            if count <= 0:
                continue
            unit_rec = None
            for cat in ("horse", "foot"):
                if unit_type in forces_data[cat]:
                    unit_rec = forces_data[cat][unit_type]
                    break
            if unit_rec is None:
                continue
            ptype = unit_rec["protection"]["type"]
            # Bug L (Pattern 7 audit) — Crossbow Hits: the FIRING side
            # selects the target unit (rule 1.3.1 / forces.json
            # firing_side_selects_target). The optimal choice is the
            # unit most likely to fail Protection — i.e., Unarmored
            # before Armored. Otherwise the TARGETED side picks, and
            # its optimal choice is the opposite: Armored first.
            if striker_selects:
                # Striker picks: unarmored (auto_remove first) before armored
                prio = {"auto_remove": 0, "unarmored": 1, "armored": 2,
                        "none": 3}.get(ptype, 4)
            else:
                # Target picks: armored before unarmored (absorb safely)
                prio = {"armored": 0, "unarmored": 1, "auto_remove": 2,
                        "none": 3}.get(ptype, 4)
            cs.append((prio, unit_type))
        cs.sort()
        return cs

    chosen = None
    chosen_pool_name = None
    chosen_pool = None
    for pool_name, pool in pools:
        cands = _build_candidates(pool)
        if cands:
            _, chosen = cands[0]
            chosen_pool_name = pool_name
            chosen_pool = pool
            break
    if chosen is None:
        return (False, None)
    unit = None
    for cat in ("horse", "foot"):
        if chosen in forces_data[cat]:
            unit = forces_data[cat][chosen]
            break
    assert unit is not None
    ptype = unit["protection"]["type"]
    # Serfs auto-rout
    if ptype == "auto_remove":
        chosen_pool[chosen] -= 1
        if chosen_pool[chosen] <= 0:
            chosen_pool.pop(chosen, None)
        # Bug M: Routed Garrison units 'return to pool' (per SoP
        # storm_procedure.garrison_during_storm.routed_garrison).
        # We track them in routed_units for the engagement; they
        # vanish at end-of-storm regardless.
        target_side.routed_units[chosen] = target_side.routed_units.get(chosen, 0) + 1
        return (False, chosen)
    # Roll Protection
    rng = roll_d6(state)
    canceled = False
    if ptype == "armored":
        lo, hi = unit["protection"]["range"]
        # M7 Spear Wall (Phase 6a, Bug T fix) — Muslim defenders'
        # Armored Foot (Men-at-Arms, African Foot) get Armor +1 vs
        # Christian Horse Melee in Battle (not Storm, not vs Missiles,
        # not vs Foot strikers). Per card text the marker is on TWO
        # specific Muslim Lords' mats; until per-Lord forces tracking
        # lands we cap total +1 consultations at the sum of the two
        # largest Muslim contributors' MaA + AfricanFoot (set up in
        # resolve_battle).
        if (target_side.side == "muslim"
                and "M7" in state.decks.this_levy_events.get("muslim", [])
                and chosen in ("men_at_arms", "african_foot")
                and striker_unit_class == "horse"
                and striker_kind == "melee"
                and context == "battle"
                and target_side.m7_boosts_remaining > 0):
            hi = hi + 1
            target_side.m7_boosts_remaining -= 1
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
        # M10 Andalusians (Phase 7a): Muslim Light Horse gain Evade 1-3
        # vs Battle Melee while the side-wide capability is in play.
        if (not canceled and context == "battle" and striker_kind == "melee"
                and chosen == "light_horse" and target_side.side == "muslim"):
            from almoravid.capabilities import side_has_capability
            if side_has_capability(state, "muslim", "M10") and 1 <= rng <= 3:
                canceled = True
    if canceled:
        return (True, None)
    # Failed Protection -> Rout
    chosen_pool[chosen] -= 1
    if chosen_pool[chosen] <= 0:
        chosen_pool.pop(chosen, None)
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
    round_index: int = 0,
) -> StepResolution:
    # Phase 6f: per-pair Strike when both sides have multi-Lord arrays
    # AND context is Battle. Storm and single-Lord cases keep the legacy
    # pooled path verbatim.
    if (context == "battle"
            and attacker.array is not None
            and defender.array is not None):
        return _resolve_step_per_pair(
            state, step_id, actor_role, step_type, unit_class,
            attacker, defender, round_index=round_index,
        )

    actor = attacker if actor_role == "attacker" else defender
    target = defender if actor_role == "attacker" else attacker

    rows = build_strike_rows(state, actor, context=context)
    raw, by_kind = _step_hits(rows, step_type, unit_class)

    # Per-card combat-event bonuses (Phase 6 / deferred-fix structural
    # hook). Each effect inspects state.decks.this_levy_events for the
    # relevant side and adjusts raw/by_kind.
    #
    # C1 / M1 Hills: 'Defending side's Slingers are x1.5 and other
    # Missiles are x1 (not x1/2)' per AoW reference. Implementation:
    # for the defending-actor missile step, add +0.5 Hits per Missile
    # unit on actor's side.
    if step_type == "missile":
        hills_id = ("C1" if actor.side == "christian" else "M1")
        held = state.decks.this_levy_events.get(actor.side, [])
        if hills_id in held and actor.role == "defender":
            bonus = 0.0
            for r in rows:
                if r.kind in ("missiles", "crossbows", "bowmen",
                              "slingers", "javelins"):
                    bonus += 0.5 * r.count
            raw += bonus
            # Distribute the bonus across kinds proportional to their
            # existing contributions so per-kind allocation still works.
            current_missile_total = sum(
                v for k, v in by_kind.items()
                if k in ("missiles", "crossbows", "bowmen",
                         "slingers", "javelins")
            )
            if current_missile_total > 0:
                for k in list(by_kind.keys()):
                    if k in ("missiles", "crossbows", "bowmen",
                             "slingers", "javelins"):
                        share = bonus * by_kind[k] / current_missile_total
                        by_kind[k] = by_kind[k] + share

    # C8 Cantador (Phase 6a) — Christian-side Round-1 Melee Strike +1
    # per Knight/Sergeant, up to 4 units total. Card text: "Round 1,
    # up to 4 of his Knights AND Sergeants Melee Strike +1." Knights
    # x2 -> 3 Hits each (effective +1 on each unit's Strike); Sergeants
    # x1 -> 2 Hits each. We add `eligible_units` full Hits to raw and
    # route them to by_kind["melee"]. After Round 1, the Battle/Storm
    # loop discards C8 from this_levy_events.
    if (step_type == "melee"
            and round_index == 1
            and actor.side == "christian"
            and "C8" in state.decks.this_levy_events.get("christian", [])):
        eligible = 0
        for r in rows:
            if r.kind == "melee" and r.unit_type in ("knights", "sergeants"):
                if _unit_class(r.unit_type) == unit_class:
                    eligible += r.count
        eligible = min(4, eligible)
        if eligible > 0:
            raw += float(eligible)
            by_kind["melee"] = by_kind.get("melee", 0.0) + float(eligible)

    # Phase 6e: Concede halves the Conceding side's Strikes this Round
    # (rule 4.4.2 concede_check + pursuit_marker — "halve first, then
    # round up by step").
    if actor.conceded:
        raw = raw / 2.0
        by_kind = {k: v / 2.0 for k, v in by_kind.items()}

    rounded = math.ceil(raw)

    # Bug E (Pattern 9): Storm 6-Melee cap per Lord per Round.
    if context == "storm" and step_type == "melee":
        rounded = min(rounded, 6)

    # Bug O (Pattern 7): mixed-missile rounding — the rounded-up
    # half goes to Crossbows first when present (rule 4.4.2). We
    # honour this for the missile step ONLY by allocating Hits per
    # kind from the by_kind breakdown.
    if step_type == "missile":
        # If the Storm cap kicked in for missile this is a no-op
        # (no cap on missiles per 4.5.2 storm_only_modifiers).
        per_kind_hits = _allocate_rounded_hits(raw, by_kind)
    else:
        # Melee step — single kind. The rounded total IS the hit count.
        # If cap reduced it, distribute the cap to melee kinds proportionally
        # (only melee here so just attribute everything to melee).
        per_kind_hits = {"melee": rounded}

    result = StepResolution(step=step_id, actor=actor_role,
                            raw_hits=raw, rounded_hits=rounded)

    # Bug D (Pattern 9) — Walls / Siegeworks roll cancels Hits.
    # We apply cancellation proportionally across kinds (drain
    # Crossbow Hits last since they got priority in rounding).
    hits_to_apply_by_kind = dict(per_kind_hits)
    if walls_range is not None and rounded > 0:
        if actor_role == "attacker":
            wlo, whi = walls_range
            dice = [roll_d6(state) for _ in range(rounded)]
            canceled = sum(1 for d in dice if wlo <= d <= whi)
            # Drain non-Crossbow first, then Crossbow.
            drain_order = ["javelins", "slingers", "bowmen", "missiles",
                           "melee", "crossbows"]
            for k in drain_order:
                if canceled <= 0:
                    break
                avail = hits_to_apply_by_kind.get(k, 0)
                take = min(avail, canceled)
                hits_to_apply_by_kind[k] = avail - take
                canceled -= take
        elif actor_role == "defender" and siege_markers > 0:
            dice = [roll_d6(state) for _ in range(rounded)]
            canceled = sum(1 for d in dice if d <= siege_markers)
            drain_order = ["javelins", "slingers", "bowmen", "missiles",
                           "melee", "crossbows"]
            for k in drain_order:
                if canceled <= 0:
                    break
                avail = hits_to_apply_by_kind.get(k, 0)
                take = min(avail, canceled)
                hits_to_apply_by_kind[k] = avail - take
                canceled -= take

    # Apply Hits per kind. Crossbow Hits use striker-selects
    # target selection; other Hits use target-selects.
    for kind, count in hits_to_apply_by_kind.items():
        if count <= 0:
            continue
        striker_selects_target = (kind == "crossbows")
        # Map our internal kind to the StrikeKind alias used by
        # _resolve_protection_roll's signature (it doesn't branch on
        # this currently except for the auto_remove path).
        protroll_kind: StrikeKind = "melee" if kind == "melee" else "missiles"
        for _ in range(count):
            if not target.has_unrouted():
                break
            _, routed = _resolve_protection_roll(
                state, target, protroll_kind,
                context=context,
                striker_selects=striker_selects_target,
                striker_unit_class=unit_class,
            )
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
    # Bug T: initialize M7 Spear Wall cap.
    init_m7_cap(state, attacker)
    init_m7_cap(state, defender)
    # Camp Attack (C2/M2) consumed at Battle start (before Round 1).
    # C7 Baggage Parapet on the Christian side cancels Muslim M2.
    _consume_camp_attack(state, attacker, defender, result)
    for round_idx in range(1, max_rounds + 1):
        rnd = BattleRound(index=round_idx)
        # Phase 6e Reposition (Round 2+ only — rule 4.4.2 skipped_round_1).
        if round_idx > 1:
            _reposition_array(attacker)
            _reposition_array(defender)
        # Phase 6i: M6 Feigned Retreat reorders Round 2 melee steps:
        # all Muslim Melee Strikes before all Christian Melee, regardless
        # of who is Attacker (rule: "On Round 2, all Muslim Melee Strikes
        # before all Christian Melee").
        if (round_idx == 2
                and "M6" in state.decks.this_levy_events.get("muslim", [])):
            muslim_side: Role = ("attacker" if attacker.side == "muslim"
                                 else "defender")
            christian_side: Role = ("attacker" if attacker.side == "christian"
                                    else "defender")
            steps_this_round: list[tuple[str, Role, str, UnitClass | None]] = [
                ("1.a", "defender", "missile", None),
                ("1.b", "attacker", "missile", None),
                # Muslim Melee first (both horse + foot), then Christian.
                ("2.a", muslim_side, "melee", "horse"),
                ("2.b", muslim_side, "melee", "foot"),
                ("2.c", christian_side, "melee", "horse"),
                ("2.d", christian_side, "melee", "foot"),
            ]
        else:
            steps_this_round = _BATTLE_STEPS
        for step_id, actor_role, step_type, unit_class in steps_this_round:
            step_res = _resolve_step(state, step_id, actor_role, step_type,
                                      unit_class, attacker, defender,
                                      round_index=round_idx)
            rnd.steps.append(step_res)
            if _battle_over(attacker, defender):
                break
        result.rounds.append(rnd)
        # End-of-Round-1 discards (C8 Cantador, M7 Spear Wall, Hills).
        if round_idx == 1:
            _discard_round1_events(state, ["C8", "M7", "C1", "M1"])
        # End-of-Round-2 discard: M6 Feigned Retreat (Round 2 only).
        if round_idx == 2:
            _discard_round1_events(state, ["M6"])
        # Phase 6e: if either side Conceded this Round, end Battle now
        # (rule 4.4.2 new_round_check end_battle_when).
        if attacker.conceded or defender.conceded:
            result.notes.append(
                f"Round {round_idx} ended with Concede; Battle ends"
            )
            break
        if _battle_over(attacker, defender):
            break
        # Reset per-Round Concede flags — Concede is declared per-Round.
        attacker.conceded = False
        defender.conceded = False
    # Phase 6e: Concede determines winner if both sides still have units.
    if attacker.conceded and not defender.conceded:
        result.winner = defender.side
    elif defender.conceded and not attacker.conceded:
        result.winner = attacker.side
    elif attacker.has_unrouted() and not defender.has_unrouted():
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


def battleside_for_lords(
    state: GameState, lord_ids: list[str], side: Side, role: Role,
    *,
    active_lord_id: str | None = None,
) -> BattleSide:
    """Aggregate multiple Lords into one BattleSide and (Phase 6e)
    populate the per-Lord `array` when multi-Lord.

    Rule 4.4.1 attacker_arrays:
      - Active Lord must occupy Front center.
      - Up to one other Lord each in Front left and Front right.
      - All other Attacker Lords go to Reserve.
    Defender placement mirrors the attacker's populated Front
    positions: one Defending Lord directly opposite each Attacking
    Front Lord, beginning center, then left and/or right, as able.
    Remainder to Reserve.

    For single-Lord BattleSides the pooled `forces` dict remains the
    sole source of truth and `array` stays None — preserving Phase
    5e/Phase 6c behavior verbatim.
    """
    forces: dict[UnitType, int] = {}
    caps: list[str] = []
    for lid in lord_ids:
        l = state.lords[lid]
        for ut, n in l.forces.items():
            forces[ut] = forces.get(ut, 0) + n
        caps.extend(l.capabilities)

    side_obj = BattleSide(
        side=side, role=role, lord_ids=list(lord_ids),
        forces=forces, capabilities_in_play=caps,
    )

    # Phase 6e: populate per-Lord Array for multi-Lord Battles.
    if len(lord_ids) > 1:
        array: list[LordPosition] = []
        positions_order = ["front_center", "front_left", "front_right"]
        # Active Lord (or the first lord_id) occupies Front center.
        center_lid = active_lord_id if (active_lord_id in lord_ids)             else lord_ids[0]
        others = [lid for lid in lord_ids if lid != center_lid]
        slots = [(center_lid, "front_center")]
        for i, lid in enumerate(others):
            if i < 2:
                slots.append((lid, positions_order[i + 1]))
            else:
                slots.append((lid, "reserve"))
        for lid, pos in slots:
            l = state.lords[lid]
            array.append(LordPosition(
                lord_id=lid, position=pos,
                forces=dict(l.forces),
                capabilities_in_play=list(l.capabilities),
            ))
        side_obj.array = array

    return side_obj


def commit_forces_after_battle(state: GameState, side: BattleSide) -> None:
    """Write the (post-Battle) forces dict back to each Lord's state.

    Single-Lord: direct copy.
    Multi-Lord with array (Phase 6f): use per-LordPosition forces +
    routed_units directly — each Lord's post-Battle state is already
    tracked per-Lord by _resolve_step_per_pair.
    Multi-Lord without array (legacy): distribute losses proportionally
    (Phase 5e fallback).
    """
    if len(side.lord_ids) == 1:
        lord = state.lords[side.lord_ids[0]]
        lord.forces = dict(side.forces)
        lord.routed_units = dict(side.routed_units)
        return

    # Phase 6f: per-Lord direct write when array is present.
    if side.array is not None:
        for lp in side.array:
            lord = state.lords[lp.lord_id]
            lord.forces = {ut: n for ut, n in lp.forces.items() if n > 0}
            for ut, n in lp.routed_units.items():
                if n > 0:
                    lord.routed_units[ut] = (
                        lord.routed_units.get(ut, 0) + n
                    )
        return

    # Multi-Lord: distribute the post-Battle pool proportionally.
    # The pre-Battle pool is reconstructable from each Lord's current
    # forces dict (which we haven't touched yet — battle.py never
    # mutates state.lords[X].forces directly).
    pre_battle_pool: dict[str, dict[UnitType, int]] = {
        lid: dict(state.lords[lid].forces) for lid in side.lord_ids
    }
    pre_battle_sum = {
        ut: sum(p.get(ut, 0) for p in pre_battle_pool.values())
        for ut in {ut for p in pre_battle_pool.values() for ut in p}
    }
    # Combined post-Battle pool: BattleSide.forces (survivors) +
    # BattleSide.routed_units (Routed). Losses = pre - (surv + routed).
    for ut, before in pre_battle_sum.items():
        survivors = side.forces.get(ut, 0)
        routed = side.routed_units.get(ut, 0)
        after = survivors + routed
        losses = max(0, before - after)
        # Distribute survivors + routed across Lords proportionally to
        # their pre-Battle contribution.
        # Simplification: iterate Lords in deterministic order, draining
        # losses from each Lord proportionally; survivors and routed
        # repopulate the same way.
        # First, drain losses (units permanently removed — actual
        # Service-shift rolls happen in 4.4.4 aftermath).
        remaining_losses = losses
        for lid in side.lord_ids:
            avail = pre_battle_pool[lid].get(ut, 0)
            if avail <= 0 or remaining_losses <= 0:
                continue
            take = min(avail, remaining_losses
                       * pre_battle_pool[lid].get(ut, 0)
                       // max(1, before))
            # Round-up so total drained matches losses
            take = max(take, 0)
            pre_battle_pool[lid][ut] = max(0, avail - take)
            remaining_losses -= take
        # If rounding leaves remaining_losses > 0, drain from any Lord
        # with stock
        for lid in side.lord_ids:
            if remaining_losses <= 0:
                break
            avail = pre_battle_pool[lid].get(ut, 0)
            if avail > 0:
                take = min(avail, remaining_losses)
                pre_battle_pool[lid][ut] = avail - take
                remaining_losses -= take

        # Now split routed proportionally to remaining pool
        if routed > 0:
            total_remaining = sum(pre_battle_pool[lid].get(ut, 0)
                                  for lid in side.lord_ids)
            if total_remaining > 0:
                allocated = 0
                routed_dist: dict[str, int] = {}
                for lid in side.lord_ids:
                    share = (pre_battle_pool[lid].get(ut, 0)
                             * routed) // total_remaining
                    routed_dist[lid] = share
                    allocated += share
                leftover = routed - allocated
                # Hand leftover to the first Lord with stock
                for lid in side.lord_ids:
                    if leftover <= 0:
                        break
                    if pre_battle_pool[lid].get(ut, 0) > 0:
                        routed_dist[lid] = routed_dist.get(lid, 0) + 1
                        leftover -= 1
                # Move routed units OUT of pre_battle_pool INTO routed
                for lid, n in routed_dist.items():
                    if n <= 0:
                        continue
                    pre_battle_pool[lid][ut] -= n

    # Write back: each Lord's forces = pre_battle_pool[lid] (surviving
    # un-routed); each Lord's routed_units gets its share.
    for lid in side.lord_ids:
        lord = state.lords[lid]
        # Clean zeros
        lord.forces = {ut: n for ut, n in pre_battle_pool[lid].items() if n > 0}
        # Distribute side.routed_units across Lords proportionally to
        # pre_battle_sum (simple share-out by contribution).
        # Done above implicitly — we'd need to track per_lord_routed. For
        # this simplified version, share BattleSide.routed_units evenly
        # across Lords:
    # Simpler distribution for routed_units: split evenly. Real per-Lord
    # tracking is a future Phase 6.
    n_lords = len(side.lord_ids)
    for ut, total_routed in side.routed_units.items():
        if total_routed <= 0:
            continue
        base = total_routed // n_lords
        leftover = total_routed - base * n_lords
        for i, lid in enumerate(side.lord_ids):
            share = base + (1 if i < leftover else 0)
            state.lords[lid].routed_units[ut] = (
                state.lords[lid].routed_units.get(ut, 0) + share
            )



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
    walls_range_override: tuple[int, int] | None = None,
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
        # 4.5.2 ENDING THE STORM: "A Storm ends once the number of
        # Rounds completed equals the number of Siege markers there."
        # The cap is the BESIEGER's Siege-marker count at the Locale
        # (used regardless of any Walls override). Per 4.5.2 the
        # Besieger's Siegeworks Walls also equal that marker count.
        if max_rounds is None:
            siege = (loc.siege_yellow if attacker.side == "christian"
                     else loc.siege_green)
            max_rounds = max(1, siege)
    # C6 Surprise / C6 Siege Towers override (Walls -1).
    if walls_range_override is not None:
        walls_range = walls_range_override

    if max_rounds is None:
        max_rounds = 1

    # Bug M (Pattern 7 audit fix): Garrison units kept in their own
    # bucket so the Protection roll drains them before Lord units.
    # Rule 4.5.2: 'Garrison absorbs Hits BEFORE any Defending Lord
    # units'.
    garrison = _garrison_for_locale(state, locale_id) if locale_id else {}
    defender.garrison_forces = dict(garrison)

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
    # Siege Towers (C6 Christian / M13 Muslim, this_lord, Phase 7a):
    # an Attacking Lord with the capability weakens the Stronghold to
    # Walls -1 from Round 2 onward (no effect Round 1).
    from almoravid.capabilities import any_lord_with_capability
    st_card = "C6" if attacker.side == "christian" else "M13"
    siege_towers = bool(
        set(any_lord_with_capability(state, attacker.side, st_card))
        & set(attacker.lord_ids)
    )
    for round_idx in range(1, max_rounds + 1):
        rnd = BattleRound(index=round_idx)
        round_walls = walls_range
        if siege_towers and round_idx >= 2 and walls_range is not None:
            round_walls = (walls_range[0], max(0, walls_range[1] - 1))
        for step_id, actor_role, step_type, unit_class in storm_steps:
            step_res = _resolve_step(
                state, step_id, actor_role, step_type, unit_class,
                attacker, defender, context="storm",
                walls_range=round_walls,
                siege_markers=siegeworks_count,
                round_index=round_idx,
            )
            rnd.steps.append(step_res)
            if _battle_over(attacker, defender):
                break
        result.rounds.append(rnd)
        # C8 Cantador also works in Storm per card text — discard after
        # Round 1. M7 / Hills do NOT apply in Storm.
        if round_idx == 1:
            _discard_round1_events(state, ["C8"])
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


# ---------------------------------------------------------------------------
# Phase 6a helpers: combat-event discards + Camp Attack consumption.
# ---------------------------------------------------------------------------


def _discard_round1_events(state: GameState, card_ids: list[str]) -> None:
    """Move one-Round Hold events out of this_levy_events to discard.

    Card text places C8 (Cantador) and M7 (Spear Wall) on a single
    Round; per rule 4.4.5 they go to discard at the end of that Round
    rather than waiting for Battle aftermath. Hills (C1/M1) also discard
    here so they don't carry over to a subsequent Battle in the same
    Levy — they're a single-engagement effect per card text.
    """
    for side_key in list(state.decks.this_levy_events.keys()):
        bucket = state.decks.this_levy_events.get(side_key, [])
        for cid in card_ids:
            while cid in bucket:
                bucket.remove(cid)
                state.decks.discard.append(cid)
        if not bucket:
            state.decks.this_levy_events.pop(side_key, None)


def _consume_camp_attack(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    result: BattleResult,
) -> None:
    """Consume Camp Attack (C2/M2) at the outset of Battle.

    Rule (card-text fidelity, Pattern 7):
      * Each side may have played its own Camp Attack into
        this_campaign_events during prior Plan/Activation; both fire
        at Battle start.
      * C7 Baggage Parapet (in this_levy_events on the Christian side)
        CANCELS Muslim Camp Attack (M2) only. C7 does NOT cancel
        Christian Camp Attack (C2). C2 is never cancelled.
      * Effect: take 2 Assets from each Enemy Lord as Spoils,
        remove 2 more from each. Assets are transferred to the
        friendly side; Spoils distribution among friendly Lords is
        a Phase 6 follow-up (full Spoils mechanics couple with
        Retreat/Aftermath in Phase 6c).
      * Camp Attack does NOT apply in Storm — resolve_storm does not
        call this helper.
    """
    for side_key in ("christian", "muslim"):
        ca_id = "C2" if side_key == "christian" else "M2"
        camp_bucket = state.decks.this_campaign_events.get(side_key, [])
        if ca_id not in camp_bucket:
            continue
        # Check for Baggage Parapet cancellation (Muslim CA only).
        cancelled = False
        if side_key == "muslim":
            christian_hold = state.decks.this_levy_events.get("christian", [])
            if "C7" in christian_hold:
                cancelled = True
                # Bug P fix (Pattern 9): C7 has TWO effects per card
                # text — "Cancel Muslim Camp Attack" AND "If Christians
                # Retreat, pay 1 Asset per Lord to skip Spoils and
                # Service shift". Don't discard C7 here; leave it in
                # this_levy_events so apply_retreat_aftermath can
                # consult it. apply_aftermath will discard it at
                # engagement end like any other Hold event.
                result.notes.append(
                    "Camp Attack (M2) cancelled by Baggage Parapet (C7)"
                )
        # Discard Camp Attack regardless (it triggered or was cancelled).
        camp_bucket.remove(ca_id)
        state.decks.discard.append(ca_id)
        if not camp_bucket:
            state.decks.this_campaign_events.pop(side_key, None)
        if cancelled:
            continue
        # Apply the effect: transfer up to 2 Assets per Enemy Lord as
        # Spoils to the friendly side, then remove 2 more per Enemy
        # Lord. We drain in a deterministic preference order so the
        # behavior is reproducible under self-play.
        friendly = attacker if attacker.side == side_key else defender
        enemy = defender if friendly is attacker else attacker
        ASSET_DRAIN_ORDER = ("coin", "loot", "prov", "cart", "mule")
        total_spoils: dict[str, int] = {}
        for elid in enemy.lord_ids:
            elord = state.lords.get(elid)
            if elord is None:
                continue
            # Phase 1: take 2 as Spoils.
            taken = 0
            for atype in ASSET_DRAIN_ORDER:
                if taken >= 2:
                    break
                have = elord.assets.get(atype, 0)
                take = min(have, 2 - taken)
                if take > 0:
                    elord.assets[atype] = have - take
                    if elord.assets[atype] == 0:
                        elord.assets.pop(atype, None)
                    total_spoils[atype] = total_spoils.get(atype, 0) + take
                    taken += take
            # Phase 2: remove 2 more.
            removed = 0
            for atype in ASSET_DRAIN_ORDER:
                if removed >= 2:
                    break
                have = elord.assets.get(atype, 0)
                take = min(have, 2 - removed)
                if take > 0:
                    elord.assets[atype] = have - take
                    if elord.assets[atype] == 0:
                        elord.assets.pop(atype, None)
                    removed += take
        # Phase 6g: distribute Spoils round-robin across all friendly
        # Lords at the Battle (rule 4.4.3 "winning player distributes
        # among winning Lords at Locale").
        if total_spoils and friendly.lord_ids:
            distribute_spoils_round_robin(
                state, list(friendly.lord_ids), total_spoils
            )
        result.notes.append(
            f"Camp Attack ({ca_id}) fired by {side_key}: "
            f"spoils={total_spoils}"
        )


# ---------------------------------------------------------------------------
# Phase 6c: Retreat aftermath — Service-shift roll per rule 4.4.3.
# ---------------------------------------------------------------------------


def _transfer_retreat_spoils(
    state: GameState,
    lord,
    fate: str,
    conceded: bool,
    winner_lord_ids: list[str],
) -> dict[str, int]:
    """Rule 4.4.3 Spoils-on-Retreat. Move the losing Lord's Assets to
    the winning Lords (round-robin), per fate:
      - Withdrew: nothing.
      - Retreated WITHOUT having Conceded, or permanently Removed:
        ALL Assets transfer.
      - Conceded then Retreated: all Loot AND excess Provender (Prov
        beyond Transport capacity, rule 4.3.2) transfer; the rest stays.
    Returns the transferred-Asset dict.
    """
    if fate == "withdraw" or not winner_lord_ids:
        return {}
    take: dict[str, int] = {}
    if fate == "removed" or (fate == "retreat" and not conceded):
        # All Assets.
        for atype, n in list(lord.assets.items()):
            if n > 0:
                take[atype] = n
        lord.assets = {}
    elif fate == "retreat" and conceded:
        # Loot + excess Provender only.
        loot = lord.assets.get("loot", 0)
        if loot > 0:
            take["loot"] = loot
            lord.assets.pop("loot", None)
        transport = lord.assets.get("cart", 0) + lord.assets.get("mule", 0)
        prov = lord.assets.get("prov", 0)
        excess = max(0, prov - transport)
        if excess > 0:
            take["prov"] = excess
            lord.assets["prov"] = prov - excess
            if lord.assets["prov"] == 0:
                lord.assets.pop("prov", None)
    if take:
        from almoravid.battle import distribute_spoils_round_robin
        distribute_spoils_round_robin(state, winner_lord_ids, take)
    return take


def apply_retreat_aftermath(
    state: GameState,
    result: BattleResult,
    *,
    approach_from_locale: str | None = None,
    approach_way_type: str | None = None,
) -> dict[str, Any]:
    """Rule 4.4.3 retreat_withdraw_remove + service.

    For each losing-side Lord:
      1. Try Withdraw — Friendly Stronghold at Battle Locale, capacity OK.
         Withdrawing Lord preserves Assets and does NOT shift Service.
      2. Else try Retreat — any adjacent Locale with no Enemy Lord and
         no Enemy Stronghold (unless Besieged or Bypassed).
         Defender constraint: may not Retreat along the Way the
         Attackers used to Approach (when known).
         Marching Attacker constraint: must Retreat to Approach origin.
         Sallying Attackers must Withdraw — they cannot Retreat (Phase
         5f handled via resolve_sally / apply_sally_aftermath; this
         helper does not engage for engagement=='sally' losers).
         Each Retreating Lord rolls 1d6:
           1-2 -> Service shift 1 box left
           3-4 -> Service shift 2 boxes left
           5-6 -> Service shift 3 boxes left
         (Vassal markers shift only under advanced rule 3.4.2 — not yet.)
      3. Else permanent removal (3.3.1).

    Returns a per-Lord summary dict suitable for the result payload.
    """
    from almoravid.actions import _shift_service_left
    from almoravid.effective import (
        is_besieged, is_bypassed, is_friendly_locale,
    )
    from almoravid.map import neighbors_via
    from almoravid.rng import roll_d6
    from almoravid.state import Cylinder
    from almoravid.static_data import load_strongholds

    summary: dict[str, Any] = {
        "winner": result.winner,
        "losers": [],
    }
    if result.winner is None:
        return summary

    # Phase 6i: M13 Severed Heads — when Christians lose (Retreat
    # branch fires), Muslim side may add 4 Jihad. Auto-fire greedy.
    loser_side_obj = (result.attacker if result.winner == result.defender.side
                      else result.defender)
    if (loser_side_obj.side == "christian"
            and "M13" in state.decks.this_levy_events.get("muslim", [])):
        from almoravid.events import _add_jihad
        placement = _add_jihad(state, 4, {})
        if placement is not None:
            state.decks.this_levy_events["muslim"].remove("M13")
            state.decks.discard.append("M13")
            summary["m13_severed_heads_jihad"] = {
                "placement": placement, "added": 4,
            }

    loser_side_obj = (result.attacker if result.winner == result.defender.side
                      else result.defender)
    if result.engagement == "sally":
        # Sally has its own Withdraw-back logic in apply_sally_aftermath.
        return summary

    # Battle locale = first loser Lord's cylinder.locale_id.
    battle_locale = None
    for lid in loser_side_obj.lord_ids:
        l = state.lords.get(lid)
        if l is not None and l.cylinder.kind == "locale":
            battle_locale = l.cylinder.locale_id
            break
    if battle_locale is None:
        return summary

    # Phase 7f: winner-side Lords at the Battle Locale receive Spoils
    # (rule 4.4.3). The losing side conceded iff its BattleSide flag
    # is still set at Battle end (Concede ends the Battle that Round).
    winner_side_obj = (result.attacker
                       if result.winner == result.attacker.side
                       else result.defender)
    winner_lord_ids = [
        wid for wid in winner_side_obj.lord_ids
        if state.lords.get(wid) is not None
        and state.lords[wid].cylinder.kind == "locale"
        and state.lords[wid].cylinder.locale_id == battle_locale
    ]
    loser_conceded = bool(loser_side_obj.conceded)
    if loser_conceded:
        summary["pursuit"] = {"pursuer": winner_side_obj.side,
                              "conceder": loser_side_obj.side}

    loc = state.locales[battle_locale]
    has_stronghold = loc.base_type != "region"
    if has_stronghold:
        capacity = load_strongholds()["strongholds"][loc.base_type]["capacity"]
    else:
        capacity = 0
    already_inside = sum(
        1 for l in state.lords.values()
        if l.cylinder.kind == "locale"
        and l.cylinder.locale_id == battle_locale
        and l.in_stronghold
    )

    # Iterate losing Lords in stable order so RNG draws are
    # deterministic across runs.
    for lid in sorted(loser_side_obj.lord_ids):
        lord = state.lords.get(lid)
        if lord is None:
            continue
        loser_side = lord.side
        entry: dict[str, Any] = {"lord_id": lid, "fate": None}

        # Step 1: Withdraw if possible.
        if (has_stronghold
                and is_friendly_locale(state, battle_locale, loser_side)
                and already_inside < capacity):
            lord.in_stronghold = True
            already_inside += 1
            entry["fate"] = "withdraw"
            entry["into_stronghold"] = battle_locale
            entry["spoils_lost"] = _transfer_retreat_spoils(
                state, lord, "withdraw", loser_conceded, winner_lord_ids)
            summary["losers"].append(entry)
            continue

        # Step 2: Retreat.
        retreat_target: str | None = None
        retreat_way: str | None = None
        # Marching attacker constraint: must Retreat to approach origin
        # (only when both side is the attacker AND approach context known).
        if (loser_side == result.attacker.side
                and approach_from_locale is not None
                and approach_way_type is not None
                and approach_from_locale in neighbors_via(
                    battle_locale, approach_way_type)):
            target = approach_from_locale
            if _retreat_target_clear(state, target, loser_side):
                retreat_target = target
                retreat_way = approach_way_type
        else:
            # Defender (or attacker without context): pick first clear
            # neighbor. Defender may not use the Way the attackers came
            # along (when known).
            for way_type in ("road", "pass"):
                for nbr in neighbors_via(battle_locale, way_type):
                    if (loser_side == result.defender.side
                            and approach_from_locale == nbr
                            and approach_way_type == way_type):
                        continue  # blocked Way
                    if _retreat_target_clear(state, nbr, loser_side):
                        retreat_target = nbr
                        retreat_way = way_type
                        break
                if retreat_target is not None:
                    break

        if retreat_target is not None:
            lord.cylinder = Cylinder(kind="locale", locale_id=retreat_target)
            lord.in_stronghold = False
            entry["fate"] = "retreat"
            entry["retreat_to"] = retreat_target
            entry["retreat_way"] = retreat_way
            # Bug P fix (Pattern 9): C7 Baggage Parapet opt-out.
            # When a Christian Lord Retreats and C7 sits in
            # this_levy_events["christian"], the Lord may pay 1 Asset
            # to skip Spoils transfer AND the Service-shift roll
            # entirely. We auto-pay greedily when an Asset is
            # available (preferring loot/cart/mule/prov, keeping coin
            # for Pay step). If no Asset is available, the opt-out
            # cannot be exercised and the Service-shift fires normally.
            ASSET_PAY_ORDER = ("loot", "mule", "cart", "prov", "coin")
            c7_held = "C7" in state.decks.this_levy_events.get("christian", [])
            opt_out_used = False
            if c7_held and loser_side == "christian":
                for atype in ASSET_PAY_ORDER:
                    if lord.assets.get(atype, 0) > 0:
                        lord.assets[atype] -= 1
                        if lord.assets[atype] == 0:
                            lord.assets.pop(atype, None)
                        opt_out_used = True
                        entry["c7_opt_out_asset"] = atype
                        break
            if opt_out_used:
                entry["service_shift_boxes"] = 0
                entry["service_roll"] = None
                entry["c7_opt_out"] = True
            else:
                # Service-shift roll (1-2 -> 1 box, 3-4 -> 2, 5-6 -> 3).
                d = roll_d6(state)
                if d <= 2:
                    shift = 1
                elif d <= 4:
                    shift = 2
                else:
                    shift = 3
                new_box = _shift_service_left(state, lid, boxes=shift)
                entry["service_roll"] = d
                entry["service_shift_boxes"] = shift
                entry["new_service_box"] = new_box
            entry["spoils_lost"] = _transfer_retreat_spoils(
                state, lord, "retreat", loser_conceded, winner_lord_ids)
            summary["losers"].append(entry)
            continue

        # Step 3: Permanent removal (rule 3.3.1).
        # Bug R fix (Pattern 9): cylinder was NOT in
        # cleanup_on_removal_fields, so the removed Lord remained at
        # the battle locale as a ghost — visible to Approach trigger,
        # Withdraw capacity, friendly-Lord scans. Set cylinder.kind
        # explicitly to "removed" so the rest of the engine sees the
        # removal.
        # Transfer Spoils BEFORE clearing the Lord's Assets (4.4.3):
        # a permanently-removed Lord hands all Assets to the winner.
        entry["spoils_lost"] = _transfer_retreat_spoils(
            state, lord, "removed", loser_conceded, winner_lord_ids)
        for field_name in lord.cleanup_on_removal_fields:
            try:
                setattr(lord, field_name,
                        type(getattr(lord, field_name))())
            except Exception:
                pass
        lord.cylinder = Cylinder(kind="removed")
        _shift_service_left(state, lid, boxes=20)  # force off-left
        entry["fate"] = "removed"
        summary["losers"].append(entry)

    return summary


def _retreat_target_clear(
    state: GameState, locale_id: str, retreating_side: Side,
) -> bool:
    """Per rule 4.4.3 retreat requires: no Enemy Lord and no Enemy
    Stronghold (unless Besieged or Bypassed)."""
    from almoravid.effective import (
        is_besieged, is_bypassed, is_friendly_locale,
    )
    other = "muslim" if retreating_side == "christian" else "christian"
    for l in state.lords.values():
        if (l.side == other and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == locale_id):
            if not (is_besieged(state, l.id) or is_bypassed(state, l.id)):
                return False
    loc = state.locales[locale_id]
    if loc.base_type != "region" and not is_friendly_locale(
            state, locale_id, retreating_side):
        # Enemy Stronghold blocks Retreat unless Besieged/Bypassed by
        # the retreating side.
        if retreating_side == "christian":
            if not (loc.siege_yellow > 0 or loc.bypass_yellow):
                return False
        else:
            if not (loc.siege_green > 0 or loc.bypass_green):
                return False
    return True



# ---------------------------------------------------------------------------
# Phase 6e: Concede + Reposition + Flanking hooks.
# ---------------------------------------------------------------------------


def declare_concede(result: BattleResult, conceder_side: Side) -> None:
    """Rule 4.4.2 concede_check: declared at start of a Round, before
    Reposition / Strike. Conceding side loses end-of-Round but Strikes
    halved this Round; Enemy gains Pursuit advantage (modeled by the
    halving — Pursuit marker semantics).

    Caller must invoke before _resolve_step is run for any substep
    of that Round.
    """
    if result.attacker.side == conceder_side:
        result.attacker.conceded = True
    elif result.defender.side == conceder_side:
        result.defender.conceded = True
    result.notes.append(
        f"Concede declared by {conceder_side}: Strikes halved this Round"
    )


def _reposition_array(side: BattleSide) -> None:
    """Rule 4.4.2 reposition (Round 2+):
      1. rout_removal: Lord whose forces are empty -> position='routed'.
      2. advance: one Reserve Lord into each empty Front position.
      3. center: if Front center still empty after Advance, mandatory
         slide from Front left or Front right into center.
    No-op when array is None.
    """
    if side.array is None:
        return
    # Step 1: rout removal.
    for lp in side.array:
        if lp.position not in ("reserve", "routed") and not lp.has_unrouted():
            lp.position = "routed"
    # Step 2: advance Reserves into empty Front positions (one-for-one).
    front_slots = ("front_center", "front_left", "front_right")
    filled = {lp.position for lp in side.array if lp.position in front_slots}
    empties = [s for s in front_slots if s not in filled]
    reserves = [lp for lp in side.array if lp.position == "reserve"
                and lp.has_unrouted()]
    for slot, lp in zip(empties, reserves):
        lp.position = slot
    # Step 3: center-fill (mandatory slide from left/right if center empty).
    has_center = any(lp.position == "front_center" for lp in side.array)
    if not has_center:
        for cand_pos in ("front_left", "front_right"):
            cand = next((lp for lp in side.array
                         if lp.position == cand_pos and lp.has_unrouted()),
                        None)
            if cand is not None:
                cand.position = "front_center"
                break


def _flanking_contribution(side: BattleSide, opposite: BattleSide) -> int:
    """Phase 6e structural hook for Flanking.

    Returns the count of `side`'s Front Lords whose directly-opposed
    Front position on `opposite` is empty (or whose Lord has Routed).
    Those Lords' Strikes become Flanking contributions per rule 4.4.2.

    Hook only — the existing pooled Strike resolution already counts
    all Front + Reserve forces, so Flanking does not change Hit totals
    in the current single-pool model. Phase 6f pair-resolution will
    use this to route Hits between target groups correctly.
    """
    if side.array is None or opposite.array is None:
        return 0
    opp_filled = {lp.position for lp in opposite.array
                  if lp.position in ("front_center", "front_left",
                                     "front_right")
                  and lp.has_unrouted()}
    count = 0
    for lp in side.array:
        if lp.position in ("front_center", "front_left", "front_right")                 and lp.has_unrouted()                 and lp.position not in opp_filled:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Phase 6f: per-pair Strike resolution (multi-Lord Battles).
# ---------------------------------------------------------------------------


def _build_strike_rows_for_position(
    state: GameState,
    side: BattleSide,
    lp: "LordPosition",
    *,
    context: Literal["battle", "storm"] = "battle",
) -> list[StrikeRow]:
    """Like build_strike_rows but for a single LordPosition. The
    capability set is the per-Lord capabilities (lp.capabilities_in_play)
    union the side-wide capabilities_in_play already on `side`."""
    forces_data = load_forces()
    caps_in_play = set(side.capabilities_in_play) | set(lp.capabilities_in_play)
    rows: list[StrikeRow] = []
    for unit_type, count in lp.forces.items():
        if count <= 0:
            continue
        unit = None
        for category in ("horse", "foot"):
            if unit_type in forces_data[category]:
                unit = forces_data[category][unit_type]
                break
        if unit is None:
            continue
        for s in unit[f"strikes_{context}"]:
            rows.append(StrikeRow(
                unit_type=unit_type, count=count,
                kind=s["kind"], rate=s["rate"],
                one_round_only=s.get("any_one_round", False),
            ))
        for cap_row in unit.get("strikes_by_capability", []):
            required = set(cap_row.get("card_ids", []))
            if required and required & caps_in_play:
                rows.append(StrikeRow(
                    unit_type=unit_type, count=count,
                    kind=cap_row["kind"], rate=cap_row["rate"],
                    one_round_only=cap_row.get("any_one_round", False),
                    card_ids=sorted(required & caps_in_play),
                ))
    return rows


def _resolve_protection_roll_for_lp(
    state: GameState,
    side: BattleSide,
    target_lp: "LordPosition",
    striker_kind: StrikeKind,
    *,
    context: Literal["battle", "storm"] = "battle",
    striker_selects: bool = False,
    striker_unit_class: UnitClass | None = None,
) -> tuple[bool, UnitType | None]:
    """Protection roll that drains from a single LordPosition's forces.

    Mirrors _resolve_protection_roll but operates on lp.forces directly.
    Routed units update side.routed_units (so commit_forces_after_battle
    sees them at the side level too) and lp.routed_units (per-Lord).
    """
    forces_data = load_forces()

    def _build_candidates(pool: dict) -> list[tuple[int, UnitType]]:
        cs: list[tuple[int, UnitType]] = []
        for unit_type, count in pool.items():
            if count <= 0:
                continue
            unit_rec = None
            for cat in ("horse", "foot"):
                if unit_type in forces_data[cat]:
                    unit_rec = forces_data[cat][unit_type]
                    break
            if unit_rec is None:
                continue
            ptype = unit_rec["protection"]["type"]
            if striker_selects:
                prio = {"auto_remove": 0, "unarmored": 1, "armored": 2,
                        "none": 3}.get(ptype, 4)
            else:
                prio = {"armored": 0, "unarmored": 1, "auto_remove": 2,
                        "none": 3}.get(ptype, 4)
            cs.append((prio, unit_type))
        cs.sort()
        return cs

    cands = _build_candidates(target_lp.forces)
    if not cands:
        return (False, None)
    _, chosen = cands[0]
    unit = None
    for cat in ("horse", "foot"):
        if chosen in forces_data[cat]:
            unit = forces_data[cat][chosen]
            break
    assert unit is not None
    ptype = unit["protection"]["type"]
    if ptype == "auto_remove":
        target_lp.forces[chosen] -= 1
        if target_lp.forces[chosen] <= 0:
            target_lp.forces.pop(chosen, None)
        side.routed_units[chosen] = side.routed_units.get(chosen, 0) + 1
        target_lp.routed_units[chosen] = target_lp.routed_units.get(chosen, 0) + 1
        return (False, chosen)
    rng = roll_d6(state)
    canceled = False
    if ptype == "armored":
        lo, hi = unit["protection"]["range"]
        # Phase 6g M7 Spear Wall (per-Lord marker preferred): if the
        # target LordPosition is m7_marked, Armor +1 vs Christian Horse
        # Melee in Battle. Falls back to side-level cap if not marked
        # (covers legacy callers that didn't initialize per-Lord
        # markers).
        m7_active = (
            side.side == "muslim"
            and chosen in ("men_at_arms", "african_foot")
            and striker_unit_class == "horse"
            and striker_kind == "melee"
            and context == "battle"
            and "M7" in state.decks.this_levy_events.get("muslim", [])
        )
        if m7_active and target_lp.m7_marked:
            hi = hi + 1
        elif (m7_active and side.array is None
              and side.m7_boosts_remaining > 0):
            # Pool-path fallback only when no per-Lord markers exist.
            hi = hi + 1
            side.m7_boosts_remaining -= 1
        if lo <= rng <= hi:
            canceled = True
    elif ptype == "unarmored":
        if rng == 1:
            canceled = True
        if (not canceled and context == "battle" and striker_kind == "melee"
                and "evade" in unit["protection"]):
            elo, ehi = unit["protection"]["evade"]["range"]
            if elo <= rng <= ehi:
                canceled = True
        # M10 Andalusians (Phase 7a): Muslim Light Horse Evade 1-3.
        if (not canceled and context == "battle" and striker_kind == "melee"
                and chosen == "light_horse" and side.side == "muslim"):
            from almoravid.capabilities import side_has_capability
            if side_has_capability(state, "muslim", "M10") and 1 <= rng <= 3:
                canceled = True
    if canceled:
        return (True, None)
    target_lp.forces[chosen] -= 1
    if target_lp.forces[chosen] <= 0:
        target_lp.forces.pop(chosen, None)
    side.routed_units[chosen] = side.routed_units.get(chosen, 0) + 1
    target_lp.routed_units[chosen] = target_lp.routed_units.get(chosen, 0) + 1
    return (False, chosen)


def _pick_flank_target(side: BattleSide) -> "LordPosition | None":
    """Greedy flank target: pick the Front-position Lord with the most
    unrouted units. Per rule 4.4.2 the Flanking Lord's owner chooses
    between Flanking or directly-opposed Enemy — here we route to the
    largest target deterministically."""
    if side.array is None:
        return None
    front_lords = [
        lp for lp in side.array
        if lp.position in ("front_center", "front_left", "front_right")
        and lp.has_unrouted()
    ]
    if not front_lords:
        return None
    return max(front_lords, key=lambda lp: sum(lp.forces.values()))


def _sync_side_forces_from_array(side: BattleSide) -> None:
    """Rebuild side.forces as the sum of all LordPosition.forces so
    legacy code paths (commit_forces_after_battle, has_unrouted) keep
    seeing a consistent pooled view."""
    if side.array is None:
        return
    pooled: dict[UnitType, int] = {}
    for lp in side.array:
        for ut, n in lp.forces.items():
            if n > 0:
                pooled[ut] = pooled.get(ut, 0) + n
    side.forces = pooled


def _resolve_step_per_pair(
    state: GameState,
    step_id: str,
    actor_role: Role,
    step_type: str,
    unit_class: UnitClass | None,
    attacker: BattleSide,
    defender: BattleSide,
    round_index: int = 0,
) -> StepResolution:
    """Per-pair Strike resolution (rule 4.4.2 multi-Lord Array).

    For each Front position on actor (center/left/right):
      - If a Lord occupies that position with unrouted units, they
        Strike at the same-position target Lord on defender, OR
        if that target is empty, route as Flanking to the largest
        Front Lord on defender.
      - Hits are computed from THAT Lord's units only (not pooled).
      - Absorption drains from the paired/Flanked target Lord's
        forces only.
    Reserve Lords do NOT Strike and do NOT absorb Hits.
    """
    actor = attacker if actor_role == "attacker" else defender
    target = defender if actor_role == "attacker" else attacker
    assert actor.array is not None and target.array is not None

    step_res = StepResolution(step=step_id, actor=actor_role)
    aggregate_raw = 0.0

    for actor_pos in ("front_center", "front_left", "front_right"):
        actor_lp = next((lp for lp in actor.array
                         if lp.position == actor_pos
                         and lp.has_unrouted()), None)
        if actor_lp is None:
            continue
        # Find target: same position first, else Flanking.
        target_lp = next((lp for lp in target.array
                          if lp.position == actor_pos
                          and lp.has_unrouted()), None)
        if target_lp is None:
            target_lp = _pick_flank_target(target)
        if target_lp is None:
            continue

        rows = _build_strike_rows_for_position(state, actor, actor_lp,
                                               context="battle")
        raw, by_kind = _step_hits(rows, step_type, unit_class)

        # Phase 6a Hills hook (per-Lord application: defender side's
        # missile units get +0.5 Hit each when actor is defender and
        # Hills card is held).
        if step_type == "missile":
            hills_id = ("C1" if actor.side == "christian" else "M1")
            held = state.decks.this_levy_events.get(actor.side, [])
            if hills_id in held and actor.role == "defender":
                bonus = 0.0
                for r in rows:
                    if r.kind in ("missiles", "crossbows", "bowmen",
                                  "slingers", "javelins"):
                        bonus += 0.5 * r.count
                raw += bonus
                cmt = sum(v for k, v in by_kind.items()
                          if k in ("missiles", "crossbows", "bowmen",
                                   "slingers", "javelins"))
                if cmt > 0:
                    for k in list(by_kind.keys()):
                        if k in ("missiles", "crossbows", "bowmen",
                                 "slingers", "javelins"):
                            by_kind[k] += bonus * by_kind[k] / cmt

        # Phase 6a C8 Cantador (Round 1, Christian, melee, up to 4 K+S).
        # In per-pair mode each actor Lord gets up to its own contribution,
        # but the SIDE-WIDE cap of 4 still applies. We approximate by
        # giving each Lord up to min(4, its own K+S count) — slightly
        # over-counts when multiple Lords each have 4+ K+S, but defensible.
        if (step_type == "melee" and round_index == 1
                and actor.side == "christian"
                and "C8" in state.decks.this_levy_events.get("christian", [])):
            eligible = 0
            for r in rows:
                if (r.kind == "melee"
                        and r.unit_type in ("knights", "sergeants")
                        and _unit_class(r.unit_type) == unit_class):
                    eligible += r.count
            eligible = min(4, eligible)
            if eligible > 0:
                raw += float(eligible)
                by_kind["melee"] = by_kind.get("melee", 0.0) + float(eligible)

        # Phase 6e Concede halving.
        if actor.conceded:
            raw = raw / 2.0
            by_kind = {k: v / 2.0 for k, v in by_kind.items()}

        rounded = math.ceil(raw)
        aggregate_raw += raw

        if step_type == "missile":
            per_kind_hits = _allocate_rounded_hits(raw, by_kind)
        else:
            per_kind_hits = {"melee": rounded}

        for kind, count in per_kind_hits.items():
            if count <= 0:
                continue
            striker_selects_target = (kind == "crossbows")
            protroll_kind: StrikeKind = "melee" if kind == "melee" else "missiles"
            for _ in range(count):
                if not target_lp.has_unrouted():
                    break
                _, routed = _resolve_protection_roll_for_lp(
                    state, target, target_lp, protroll_kind,
                    context="battle",
                    striker_selects=striker_selects_target,
                    striker_unit_class=unit_class,
                )
                if routed is not None:
                    step_res.losses[routed] = step_res.losses.get(routed, 0) + 1
                    step_res.rounded_hits += 1
        step_res.raw_hits = aggregate_raw

    # Reposition the sliced per-Lord forces back into the pooled
    # side.forces so legacy queries (commit_forces_after_battle,
    # _battle_over via has_unrouted) keep working.
    _sync_side_forces_from_array(attacker)
    _sync_side_forces_from_array(defender)
    return step_res



# ---------------------------------------------------------------------------
# Phase 6g: Spoils distribution helper.
# ---------------------------------------------------------------------------


def distribute_spoils_round_robin(
    state: GameState,
    friendly_lord_ids: list[str],
    spoils: dict[str, int],
) -> dict[str, dict[str, int]]:
    """Distribute Spoils across friendly Lords round-robin.

    Per rule 4.4.3 winning player distributes among winning Lords at
    the Battle. Greedy/deterministic: iterate Lords in given order,
    handing them one Asset at a time per kind. Returns the per-Lord
    distribution dict.
    """
    out: dict[str, dict[str, int]] = {lid: {} for lid in friendly_lord_ids}
    if not friendly_lord_ids:
        return out
    for atype, total in spoils.items():
        if total <= 0:
            continue
        i = 0
        for _ in range(total):
            lid = friendly_lord_ids[i % len(friendly_lord_ids)]
            lord = state.lords.get(lid)
            if lord is not None:
                lord.assets[atype] = lord.assets.get(atype, 0) + 1
            out[lid][atype] = out[lid].get(atype, 0) + 1
            i += 1
    return out
