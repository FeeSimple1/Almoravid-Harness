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
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from almoravid.rng import roll_d6
from almoravid.state import AssetType, GameState, Lord, Side, UnitType
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
    # 4.4.1 "any 1 Round" timing (owner choice; default Round 1):
    # `oneround_round` is the Round this side's one_round_only Strikes
    # (Javelins) fire; `m7_round` is the Round M7 Spear Wall is in effect;
    # `m7_owned` marks that M7 was set up for this side (Muslim) so the
    # Round loop can gate its activation/discard to `m7_round`.
    oneround_round: int = 1
    m7_round: int = 1
    m7_owned: bool = False
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
    """Outcome of one Strike substep.

    raw_hits      = accumulated half-Hits before rounding.
    rounded_hits  = raw_hits rounded up (the actual Hits dealt this step,
                    BEFORE Protection). [resolver-fix (d)]
    units_routed  = number of target units actually Routed (post-Protection).
                    Previously the per-pair path overloaded `rounded_hits`
                    with this count, which was misleading.
    losses        = {unit_type: count} of units Routed this step.
    """

    step: str                  # "1.a" etc.
    actor: Role
    raw_hits: float = 0.0      # accumulated halves before rounding
    rounded_hits: int = 0      # raw_hits rounded up (Hits dealt, pre-Protection)
    units_routed: int = 0      # units actually Routed (post-Protection)
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
    # S11b: per-Lord post-Storm forces (multi-besieger Storms) so the
    # caller can commit each Lord exactly. Empty for non-Storm results.
    attacker_lord_forces: dict[str, Any] = field(default_factory=dict)
    defender_lord_forces: dict[str, Any] = field(default_factory=dict)
    attacker_lord_routed: dict[str, Any] = field(default_factory=dict)
    defender_lord_routed: dict[str, Any] = field(default_factory=dict)


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
    side.m7_owned = True
    contribs: list[tuple[int, str]] = []
    for lid in side.lord_ids:
        lord = state.lords.get(lid)
        if lord is None:
            continue
        af = (lord.forces.get("men_at_arms", 0)
              + lord.forces.get("african_foot", 0))
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

    # (b) Jabalinas (C7) / Harbah (M3,M6): "Up to 4 of this Lord's Unarmored
    # units have Missiles ... (mark)". Cap the Javelin-granted units at 4
    # ACROSS the Lord's Unarmored types, not per unit-type. build_strike_rows
    # runs over one Lord's force (the single-Lord pooled case; the per-pair
    # path caps per LordPosition in _build_strike_rows_for_position).
    javelin_budget = 4
    slinger_budget = 3   # C9/M7 Slingers: up to 3 Militia per Lord
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
                row_count = count
                cap_kind = cap_row.get("kind")
                if cap_row.get("cap_type") == "javelins" or \
                        cap_kind == "javelins":
                    row_count = min(count, javelin_budget)
                    javelin_budget -= row_count
                    if row_count <= 0:
                        continue
                elif cap_kind == "slingers" and cap_row.get("max_per_lord"):
                    row_count = min(count, slinger_budget)
                    slinger_budget -= row_count
                    if row_count <= 0:
                        continue
                cap_rate = cap_row["rate"]
                # 4.5.2: Javelins and Slingers fire x1/2 (not x1) in Storm.
                if (context == "storm" and cap_kind in ("javelins", "slingers")
                        and cap_rate == "x1"):
                    cap_rate = "x1/2"
                rows.append(StrikeRow(
                    unit_type=unit_type,
                    count=row_count,
                    kind=cap_row["kind"],
                    rate=cap_rate,
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
    absorb_policy: str = "weakest_first",
    striker_minus_armor: int = 0,
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
    pools: list[tuple[str, dict[UnitType, int]]] = []
    if context == "storm" and target_side.garrison_forces:
        pools.append(("garrison", target_side.garrison_forces))
    pools.append(("forces", target_side.forces))

    def _build_candidates(pool: dict[UnitType, int]) -> list[tuple[int, UnitType]]:
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
                # Crossbow: the FIRING side selects the target to
                # maximize routs — least-protected first.
                prio = {"auto_remove": 0, "unarmored": 1, "armored": 2,
                        "none": 3}.get(ptype, 4)
            elif absorb_policy == "armored_first":
                # Owner policy: armored soak Hits first (maximize cancels).
                prio = {"armored": 0, "unarmored": 1, "auto_remove": 2,
                        "none": 3}.get(ptype, 4)
            else:
                # Owner policy weakest_first (default): sacrifice the
                # least-protected first to shield strong units (4.4.2).
                prio = {"auto_remove": 0, "unarmored": 1, "armored": 2,
                        "none": 3}.get(ptype, 4)
            cs.append((prio, unit_type))
        cs.sort()
        return cs

    chosen = None
    chosen_pool = None
    for _pool_name, pool in pools:
        cands = _build_candidates(pool)
        if cands:
            _, chosen = cands[0]
            chosen_pool = pool
            break
    if chosen is None:
        return (False, None)
    assert chosen_pool is not None
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
        # Crossbows: -1 vs Armor (Quick Ref Table 1 / Errata).
        hi = hi - striker_minus_armor
        if lo <= rng <= hi:
            canceled = True
    elif ptype == "unarmored":
        if rng == 1:
            canceled = True
        # Bug H (Pattern 9 audit) — Evade Protection: unit's spec may
        # include an 'evade' clause with its own range that supplements
        # Unarmored, but ONLY for Battle Melee Hits (not Missiles, not
        # Storm). African Horse: Evade 1-2; Light Horse + M10
        # Andalusians: Evade 1-3 (the M10 side-wide capability is wired
        # just below). Apply when context='battle' and striker_kind=='melee'.
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
    melee_hits_override: int | None = None,
    c8_ctx: dict[str, Any] | None = None,
) -> StepResolution:
    # Phase 6f: per-pair Strike when both sides have multi-Lord arrays
    # AND context is Battle. Storm and single-Lord cases keep the legacy
    # pooled path verbatim.
    if (context == "battle"
            and attacker.array is not None
            and defender.array is not None):
        return _resolve_step_per_pair(
            state, step_id, actor_role, step_type, unit_class,
            attacker, defender, round_index=round_index, c8_ctx=c8_ctx,
        )

    actor = attacker if actor_role == "attacker" else defender
    target = defender if actor_role == "attacker" else attacker

    # S8 (4.5.2): for Storm Melee the caller supplies a per-Lord-capped,
    # horse+foot-combined Hit total (each Lord <= 6). Skip the pooled
    # strike computation, cap, and C8 folding (already accounted for).
    if melee_hits_override is not None:
        rounded = max(0, int(melee_hits_override))
        per_kind_hits = {"melee": rounded}
        result = StepResolution(step=step_id, actor=actor_role,
                                raw_hits=float(rounded), rounded_hits=rounded)
        _apply_step_cancellation_and_hits(
            state, actor_role, target, per_kind_hits, rounded,
            walls_range, siege_markers, context, unit_class, result)
        return result

    rows = build_strike_rows(state, actor, context=context)
    # (a) Javelins / other one_round_only Strikes fire on only ONE Round.
    # The owner may choose WHICH Round (Arts of War ref C7/M3 "any 1 Battle
    # Round"); we default to Round 1 (full-strength, max effect) and drop
    # one_round_only rows thereafter. (Owner round-choice TODO: a per-combat
    # policy, consistent with the atomic resolver's Concede/Reposition.)
    if round_index != actor.oneround_round:
        rows = [r for r in rows if not r.one_round_only]
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
        # Shared per-Round budget: Knights (Horse step) and Sergeants
        # (Foot step) draw from the SAME pool of 4 (combined cap). Falls
        # back to a local cap of 4 only if no Round context was threaded.
        budget = c8_ctx["budget"] if c8_ctx is not None else 4
        eligible = min(eligible, budget)
        if eligible > 0:
            if c8_ctx is not None:
                c8_ctx["budget"] -= eligible
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
    _apply_step_cancellation_and_hits(
        state, actor_role, target, per_kind_hits, rounded,
        walls_range, siege_markers, context, unit_class, result)
    return result


def _apply_step_cancellation_and_hits(
    state: GameState,
    actor_role: Role,
    target: BattleSide,
    per_kind_hits: dict[str, int],
    rounded: int,
    walls_range: tuple[int, int] | None,
    siege_markers: int,
    context: Literal["battle", "storm"],
    unit_class: UnitClass | None,
    result: StepResolution,
) -> None:
    """Walls/Siegeworks cancellation then Protection-roll Hit
    application (shared by the normal and Storm-melee-override paths
    of _resolve_step)."""
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
    # 4.4.2 ASSIGN HITS — the absorbing owner's policy (per-combat LLM
    # choice); the Storm Attacker is rule-forced to armored_first
    # (4.5.2 "must absorb Hits with any Armored units before others").
    if context == "storm" and target.role == "attacker":
        absorb_policy = "armored_first"
    else:
        absorb_policy = state.meta.absorption_policy.get(
            target.side, "weakest_first")
    for kind, count in hits_to_apply_by_kind.items():
        if count <= 0:
            continue
        striker_selects_target = (kind == "crossbows")
        protroll_kind: StrikeKind = "melee" if kind == "melee" else "missiles"
        minus_armor = 1 if kind == "crossbows" else 0
        for _ in range(count):
            if not target.has_unrouted():
                break
            _, routed = _resolve_protection_roll(
                state, target, protroll_kind,
                context=context,
                striker_selects=striker_selects_target,
                striker_unit_class=unit_class,
                absorb_policy=absorb_policy,
                striker_minus_armor=minus_armor,
            )
            if routed is not None:
                result.losses[routed] = result.losses.get(routed, 0) + 1


# ---------------------------------------------------------------------------
# Round / Battle loop
# ---------------------------------------------------------------------------


def _side_all_lords_routed(side: BattleSide) -> bool:
    """B4 (rule 4.4.2): a side is defeated when ALL its Lords have
    Routed -- i.e. no Lord in ANY Array position (Front or Reserve)
    still has unrouted units. For a multi-Lord array we check every
    LordPosition; for a pooled (single-Lord / legacy) side we fall back
    to the unit-level view (a pooled side's units belong to one Lord,
    so 'no unrouted units' == 'that Lord Routed'). Garrison units (Storm
    Defender) also keep the side alive."""
    if side.array is not None:
        any_lord_alive = any(lp.has_unrouted() for lp in side.array)
        any_garrison = any(v > 0 for v in side.garrison_forces.values())
        return not (any_lord_alive or any_garrison)
    return not side.has_unrouted()


def _battle_over(attacker: BattleSide, defender: BattleSide) -> bool:
    """Per rule 4.4.2 new_round_check: the Battle ends when either side
    has all its Lords Routed (not merely all *Front* Lords -- Reserve
    Lords keep the side in the Battle and Advance to Front at the next
    Reposition)."""
    return (_side_all_lords_routed(attacker)
            or _side_all_lords_routed(defender))


def battle_side_to_snapshot(bs: BattleSide) -> dict[str, Any]:
    """JSON-able snapshot of a BattleSide for suspend/resume of an
    interactive (round-stepped) Battle. All fields are primitive
    containers; `array` LordPositions are flattened by dataclasses.asdict.
    """
    return asdict(bs)


def battle_side_from_snapshot(d: dict[str, Any]) -> BattleSide:
    """Rebuild a BattleSide from battle_side_to_snapshot() output."""
    arr = d.get("array")
    array: list[LordPosition] | None = None
    if arr is not None:
        array = [
            LordPosition(
                lord_id=p["lord_id"],
                position=p["position"],
                forces=dict(p["forces"]),
                capabilities_in_play=list(p["capabilities_in_play"]),
                routed_units=dict(p["routed_units"]),
                m7_marked=p["m7_marked"],
            )
            for p in arr
        ]
    return BattleSide(
        side=d["side"],
        role=d["role"],
        lord_ids=list(d["lord_ids"]),
        forces=dict(d["forces"]),
        capabilities_in_play=list(d["capabilities_in_play"]),
        routed_units=dict(d["routed_units"]),
        garrison_forces=dict(d["garrison_forces"]),
        m7_boosts_remaining=d["m7_boosts_remaining"],
        oneround_round=d.get("oneround_round", 1),
        m7_round=d.get("m7_round", 1),
        m7_owned=d.get("m7_owned", False),
        array=array,
        conceded=d["conceded"],
    )


def _battle_one_round(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    round_idx: int,
    *,
    defender_walls_range: tuple[int, int] | None = None,
) -> BattleRound:
    """Resolve a single open-field Battle Round: Reposition (Round 2+),
    the Strike steps (M6 Feigned-Retreat reorder on Round 2), and the
    end-of-Round Hold-event discards. Mutates both sides in place.

    The Concede declaration, the end-of-Battle break, and the winner
    determination are the CALLER's responsibility -- shared by the
    synchronous resolve_battle (pre-declared concede) and the interactive
    round-stepped driver (reactive per-Round concede, 4.4.2)."""
    rnd = BattleRound(index=round_idx)
    # 4.4.1 one-Round timing: M7 Spear Wall is in effect only during its
    # owner-chosen Round (default 1). We gate its presence in
    # this_levy_events so the protection-roll hook (which keys on that
    # presence) fires only in `m7_round`: suppress it in earlier Rounds,
    # (re)activate it in `m7_round`, and discard it after.
    _mus = attacker if attacker.side == "muslim" else defender
    if _mus.m7_owned:
        _held = state.decks.this_levy_events.setdefault("muslim", [])
        if round_idx < _mus.m7_round:
            # Suppress (not "Used") before the chosen Round: just remove it
            # from the in-effect set. If the Battle ends before m7_round the
            # card never reaches decks.discard, but that is harmless -- the
            # AoW discard pile is a pure sink (no reshuffle) and
            # this_levy_events is fully cleared at Battle aftermath.
            if "M7" in _held:
                _held.remove("M7")
        elif round_idx == _mus.m7_round:
            if "M7" not in _held:
                _held.append("M7")
    # Phase 6e Reposition (Round 2+ only -- rule 4.4.2 skipped_round_1).
    if round_idx > 1:
        _reposition_array(
            attacker,
            center_fill=state.meta.array_center_fill.get(attacker.side, "left"),
            reserve_priority=state.meta.array_reserve_priority.get(
                attacker.side, []))
        _reposition_array(
            defender,
            center_fill=state.meta.array_center_fill.get(defender.side, "left"),
            reserve_priority=state.meta.array_reserve_priority.get(
                defender.side, []))
    # Phase 6i: M6 Feigned Retreat reorders Round 2 melee steps -- all
    # Muslim Melee Strikes before all Christian Melee, regardless of who
    # is Attacker.
    if (round_idx == 2
            and "M6" in state.decks.this_levy_events.get("muslim", [])):
        muslim_side: Role = ("attacker" if attacker.side == "muslim"
                             else "defender")
        christian_side: Role = ("attacker" if attacker.side == "christian"
                                else "defender")
        steps_this_round: list[tuple[str, Role, str, UnitClass | None]] = [
            ("1.a", "defender", "missile", None),
            ("1.b", "attacker", "missile", None),
            ("2.a", muslim_side, "melee", "horse"),
            ("2.b", muslim_side, "melee", "foot"),
            ("2.c", christian_side, "melee", "horse"),
            ("2.d", christian_side, "melee", "foot"),
        ]
    else:
        steps_this_round = _BATTLE_STEPS
    c8_ctx = _build_c8_ctx(state, attacker, defender, round_idx)
    for step_id, actor_role, step_type, unit_class in steps_this_round:
        step_res = _resolve_step(state, step_id, actor_role, step_type,
                                  unit_class, attacker, defender,
                                  round_index=round_idx,
                                  walls_range=defender_walls_range,
                                  c8_ctx=c8_ctx)
        rnd.steps.append(step_res)
        if _battle_over(attacker, defender):
            break
    # End-of-Round discards: C8 Cantador (Round 1 only, per card text);
    # M7 Spear Wall after its owner-chosen Round (default 1).
    if round_idx == 1:
        _discard_round1_events(state, ["C8"])
    if _mus.m7_owned and round_idx >= _mus.m7_round:
        _discard_round1_events(state, ["M7"])
    # End-of-Round-2 discard: M6 Feigned Retreat (Round 2 only).
    if round_idx == 2:
        _discard_round1_events(state, ["M6"])
    return rnd


def resolve_battle(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    *,
    max_rounds: int = 6,
    defender_walls_range: tuple[int, int] | None = None,
    attacker_concede_round: int | None = None,
    defender_concede_round: int | None = None,
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
        # 4.4.2 CONCEDE THE FIELD? Pre-declared per side via *_concede_round
        # here (the interactive driver sets these flags reactively instead).
        # Setting the flag before Strikes makes _resolve_step halve the
        # conceding side's Hits this Round (pursuit) and ends the Battle at
        # Round end with that side as the loser (winner logic below).
        if (attacker_concede_round is not None
                and round_idx >= attacker_concede_round):
            attacker.conceded = True
        if (defender_concede_round is not None
                and round_idx >= defender_concede_round):
            defender.conceded = True
        rnd = _battle_one_round(state, attacker, defender, round_idx,
                                defender_walls_range=defender_walls_range)
        result.rounds.append(rnd)
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
    elif (not _side_all_lords_routed(attacker)
          and _side_all_lords_routed(defender)):
        result.winner = attacker.side
    elif (not _side_all_lords_routed(defender)
          and _side_all_lords_routed(attacker)):
        result.winner = defender.side
    else:
        result.winner = None
        result.notes.append("Battle inconclusive after max rounds")
    return result


# ---------------------------------------------------------------------------
# Aftermath helpers (Pattern 2 mirror-gap audit applies — winner-side
# AND loser-side branches must both call the corresponding helpers).
# ---------------------------------------------------------------------------


def _losses_keep_threshold(utype: UnitType) -> int:
    """4.4.4: the unmodified Protection roll range a Routed unit must
    roll WITHIN to survive (un-rout). Armored -> high end; Unarmored
    -> 1; Serfs (auto_remove) -> 0 (always lost). African Horse ALWAYS
    uses its Evade range (per 4.4.4), not Unarmored. Ranges are
    unmodified by Events/Capabilities/Battle situation, so Light
    Horse uses Unarmored (1), not its M10 Evade."""
    fd = load_forces()
    rec = None
    for cat in ("horse", "foot"):
        if utype in fd[cat]:
            rec = fd[cat][utype]
            break
    if rec is None:
        return 0
    if utype == "african_horse":
        return int(rec["protection"]["evade"]["range"][1])
    ptype = rec["protection"]["type"]
    if ptype == "armored":
        return int(rec["protection"]["range"][1])
    if ptype == "unarmored":
        return 1
    return 0  # auto_remove (Serfs)


def apply_losses_rolls(state: GameState, lord_id: str, loser_state: str) -> dict[str, Any]:
    """4.4.4 Losses: roll 1d6 for each of a Lord's Routed units.

    Threshold by loser_state:
      - "retreated_no_concede" / "storm_attacker": keep only on a 1.
      - "winner" / "withdrew" / "conceded_then_retreated": keep on a
        roll within the unit's unmodified Protection range (African
        Horse uses Evade).
      - "removed": Lord is gone; discard the pile.
    Kept units return to lord.forces (un-Routed). Failed units go to
    the pool. Service markers stay put."""
    lord = state.lords.get(lord_id)
    if lord is None or not lord.routed_units:
        return {"lord_id": lord_id, "rolls": []}
    rolls = []
    for utype, n in list(lord.routed_units.items()):
        if loser_state == "removed":
            keep = 0
        elif loser_state in ("retreated_no_concede", "storm_attacker"):
            keep = 1
        else:  # winner / withdrew / conceded_then_retreated
            keep = _losses_keep_threshold(utype)
        kept = 0
        for _ in range(n):
            r = roll_d6(state)
            if r <= keep and keep > 0:
                kept += 1
        if kept > 0:
            lord.forces[utype] = lord.forces.get(utype, 0) + kept
        del lord.routed_units[utype]
        rolls.append({"unit": utype, "n_routed": n, "keep_threshold": keep,
                      "kept": kept, "lost": n - kept})
    return {"lord_id": lord_id, "rolls": rolls}


def apply_battle_losses(
    state: GameState,
    result: BattleResult,
    retreat_summary: dict[str, Any],
    *,
    storm: bool = False,
) -> dict[str, Any]:
    """Drive 4.4.4 Losses for BOTH sides after a Battle/Storm.

    Winner-side Lords roll vs Protection ("winner"). Loser-side Lords
    use the loser_state implied by their fate (from retreat_summary):
    withdraw -> "withdrew"; retreat -> "conceded_then_retreated" if the
    loser side Conceded else "retreated_no_concede"; removed -> already
    gone. In a Storm, the Attacking side's Routed units always need a
    1 ("storm_attacker", 4.5.2). Any Lord left with zero Forces is
    permanently removed (3.3.1)."""
    from almoravid.state import Cylinder
    out: dict[str, Any] = {}
    # 4.5.4 (rule line "becomes free of Enemy Lords ... remove all Siege or
    # Bypass markers there"): track Locales where a besieging Lord is
    # eliminated in combat so orphaned Siege/Bypass markers are cleared.
    # [P-2 playtest] -- combat is the elimination path the F7 Disband/March
    # cleanup did not cover; doing it here covers Storm, Sally, Battle, relief.
    _removed_locales: list[str] = []
    if result.winner is None:
        # Stalemate — both sides simply roll vs Protection.
        loser_side = None
    else:
        loser_side = (result.attacker.side
                      if result.winner == result.defender.side
                      else result.defender.side)
    conceded = {result.attacker.side: result.attacker.conceded,
                result.defender.side: result.defender.conceded}
    fate_by_lord = {e["lord_id"]: e.get("fate")
                    for e in retreat_summary.get("losers", [])}

    for side_obj in (result.attacker, result.defender):
        is_attacker = (side_obj is result.attacker)
        for lid in side_obj.lord_ids:
            if lid not in state.lords:
                continue
            if storm and is_attacker:
                lstate = "storm_attacker"
            elif loser_side is not None and side_obj.side == loser_side:
                fate = fate_by_lord.get(lid)
                if fate == "removed":
                    continue  # gone already
                if fate == "withdraw":
                    lstate = "withdrew"
                elif fate == "retreat":
                    lstate = ("conceded_then_retreated"
                              if conceded.get(side_obj.side) else
                              "retreated_no_concede")
                else:
                    lstate = "withdrew"  # default safe
            else:
                lstate = "winner"
            out[lid] = apply_losses_rolls(state, lid, lstate)
            # 3.3.1: a Lord who lost ALL Forces is permanently removed.
            lord = state.lords[lid]
            if (not lord.forces and not lord.routed_units
                    and lord.cylinder.kind == "locale"):
                from almoravid.actions import _shift_service_left as _ssl
                for fld in lord.cleanup_on_removal_fields:
                    try:
                        setattr(lord, fld, type(getattr(lord, fld))())
                    except Exception:
                        pass
                _gone_locale = lord.cylinder.locale_id
                lord.cylinder = Cylinder(kind="removed")
                _ssl(state, lid, boxes=20)
                out[lid]["permanently_removed"] = True
                if _gone_locale is not None:
                    _removed_locales.append(_gone_locale)
    # 4.5.4: clear Siege/Bypass markers at any Locale whose besieging side
    # has just lost its last Lord there to combat (becomes "free of Enemy
    # Lords"). _remove_orphaned_siege_bypass is per-side, so it leaves the
    # surviving side's markers intact. [P-2]
    if _removed_locales:
        from almoravid.campaign import _remove_orphaned_siege_bypass
        for _loc in dict.fromkeys(_removed_locales):
            _remove_orphaned_siege_bypass(state, _loc)
    return out


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

    # 4.4.4 Losses are applied separately (apply_battle_losses) BEFORE
    # aftermath; the old blanket winner-restore is gone — winners also
    # roll for their Routed units per the rule.

    # Bug J (Pattern 13): clear this_levy_events; discard the held cards.
    for _side_key, cards in list(state.decks.this_levy_events.items()):
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


def _front_lord_count(side: BattleSide) -> int:
    """Number of Front Lords (with unrouted units) currently arrayed on
    `side`. Used to cap the Defender's Front count to the Attacker's
    (rule 4.4.1). A single-Lord (pooled) side has exactly one Front
    Lord."""
    if side.array is None:
        return 1
    n = sum(1 for lp in side.array
            if lp.position in ("front_center", "front_left", "front_right")
            and lp.has_unrouted())
    return max(1, n)


def battleside_for_lords(
    state: GameState, lord_ids: list[str], side: Side, role: Role,
    *,
    active_lord_id: str | None = None,
    front_limit: int = 3,
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

    B4 (rule 4.4.1): `front_limit` caps how many Front positions this
    side may fill (1..3). The Attacker uses the default 3 (Active Lord
    at center, up to two others at left/right, rest Reserve). For the
    Defender the caller passes the Attacker's actual Front-Lord count
    so the Defender places exactly one Lord opposite each Attacking
    Front Lord and sends all extras to Reserve -- preventing a
    permanently-unopposed Front Defender that never takes Hits and
    spins the Battle to its round cap.

    For single-Lord BattleSides the pooled `forces` dict remains the
    sole source of truth and `array` stays None — preserving Phase
    5e/Phase 6c behavior verbatim.
    """
    forces: dict[UnitType, int] = {}
    caps: list[str] = []
    for lid in lord_ids:
        lord = state.lords[lid]
        for ut, n in lord.forces.items():
            forces[ut] = forces.get(ut, 0) + n
        caps.extend(lord.capabilities)

    side_obj = BattleSide(
        side=side, role=role, lord_ids=list(lord_ids),
        forces=forces, capabilities_in_play=caps,
    )

    # Phase 6e: populate per-Lord Array for multi-Lord Battles.
    if len(lord_ids) > 1:
        array: list[LordPosition] = []
        positions_order: list[ArrayPosition] = [
            "front_center", "front_left", "front_right"]
        # Number of Front positions this side may fill (1..3). B4: the
        # Defender is capped at the Attacker's Front-Lord count so each
        # extra Lord goes to Reserve.
        front_n = max(1, min(int(front_limit), 3))
        # Active Lord (or the first lord_id) occupies Front center.
        center_lid = active_lord_id if (active_lord_id in lord_ids)             else lord_ids[0]
        others = [lid for lid in lord_ids if lid != center_lid]
        slots: list[tuple[str, ArrayPosition]] = [(center_lid, "front_center")]
        for i, lid in enumerate(others):
            # center already filled position 0; remaining Front slots
            # are positions_order[1 .. front_n-1].
            if i + 1 < front_n:
                slots.append((lid, positions_order[i + 1]))
            else:
                slots.append((lid, "reserve"))
        for lid, pos in slots:
            lord = state.lords[lid]
            array.append(LordPosition(
                lord_id=lid, position=pos,
                forces=dict(lord.forces),
                capabilities_in_play=list(lord.capabilities),
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


def _garrison_for_locale(state: GameState, locale_id: str) -> dict[UnitType, int]:
    """Build a Garrison BattleSide partial (forces + cap modifiers) from
    strongholds.json. Returns dict suitable for BattleSide(forces=...).
    """
    from almoravid.static_data import load_strongholds
    loc = state.locales[locale_id]
    if loc.base_type == "region":
        return {}
    sh = load_strongholds()["strongholds"][loc.base_type]
    g = sh["garrison"]
    out: dict[UnitType, int] = {}
    if g.get("men_at_arms", 0):
        out["men_at_arms"] = g["men_at_arms"]
    if g.get("militia", 0):
        out["militia"] = g["militia"]
    return out


def _combined_melee_raw(
    state: GameState,
    forces: dict[UnitType, int],
    caps: list[str],
    *,
    garrison: dict[UnitType, int] | None = None,
) -> float:
    """Raw Melee Hits (in halves, horse + foot combined) for a Storm
    striker built from `forces` (+ optional garrison)."""
    side = BattleSide(side="christian", role="attacker", lord_ids=[],
                      forces=dict(forces), capabilities_in_play=list(caps),
                      garrison_forces=dict(garrison or {}))
    rows = build_strike_rows(state, side, context="storm")
    raw_h, _ = _step_hits(rows, "melee", "horse")
    raw_f, _ = _step_hits(rows, "melee", "foot")
    return raw_h + raw_f


def _c8_bonus_for_forces(forces: dict[UnitType, int]) -> int:
    """C8 Cantador eligible units (Knights + Sergeants) in a force dict."""
    return forces.get("knights", 0) + forces.get("sergeants", 0)


def _build_c8_ctx(
    state: GameState, attacker: BattleSide, defender: BattleSide,
    round_idx: int,
) -> dict[str, Any] | None:
    """Per-Round shared C8 Cantador context for an open-field Battle.

    Card C8 reads "up to four of *that Lord's* Knights and Sergeants ...
    cause one added Hit" in Round 1 only. Two corrections vs a naive
    per-step budget:

    * COMBINED cap of 4 across Knights (Horse Melee step) AND Sergeants
      (Foot Melee step) -- the two steps must share ONE budget, else the
      bonus doubles to 8.
    * Confined to the ONE Christian Lord whose mat holds the card. We pick
      the Front Christian Lord with the most eligible (Knights+Sergeants)
      units -- the placement a rational player makes -- and apply the
      bonus to that Lord only. (Single-Lord Battles: holder is that Lord.)

    Returns None when C8 is not in effect this Round.
    """
    if round_idx != 1:
        return None
    if "C8" not in state.decks.this_levy_events.get("christian", []):
        return None
    chr_side = attacker if attacker.side == "christian" else defender
    holder_id: int | None = None
    if chr_side.array is not None:
        best = -1
        for lp in chr_side.array:
            if lp.position not in ("front_center", "front_left",
                                   "front_right"):
                continue
            if not lp.has_unrouted():
                continue
            elig = _c8_bonus_for_forces(lp.forces)
            if elig > best:
                best = elig
                holder_id = id(lp)
    return {"budget": 4, "holder_id": holder_id}


def _storm_front_agg(ss: dict[str, Any], who: str) -> dict[UnitType, int]:
    agg: dict[UnitType, int] = {}
    for lid in ss[who + "_front"]:
        for ut, n in ss[who + "_lord_forces"][lid].items():
            if n > 0:
                agg[ut] = agg.get(ut, 0) + n
    return agg


def _storm_push_losses(ss: dict[str, Any], who: str, side_obj: BattleSide,
                       before: dict[UnitType, int]) -> None:
    front = ss[who + "_front"]
    forces = ss[who + "_lord_forces"]
    routed = ss[who + "_lord_routed"]
    now = side_obj.forces
    for ut, b in before.items():
        lost = b - now.get(ut, 0)
        for lid in front:
            if lost <= 0:
                break
            have = forces[lid].get(ut, 0)
            take = min(have, lost)
            if take:
                forces[lid][ut] = have - take
                if forces[lid][ut] <= 0:
                    forces[lid].pop(ut, None)
                routed[lid][ut] = routed[lid].get(ut, 0) + take
                lost -= take


def _storm_attacker_front_alive(ss: dict[str, Any]) -> bool:
    return any(ss["a_lord_forces"][lid] for lid in ss["a_front"])


def _storm_attacker_alive(ss: dict[str, Any]) -> bool:
    return (_storm_attacker_front_alive(ss)
            or any(ss["a_lord_forces"][lid] for lid in ss["a_reserve"]))


def _storm_defender_front_alive(ss: dict[str, Any]) -> bool:
    return any(ss["d_lord_forces"][lid] for lid in ss["d_front"])


def _storm_defender_alive(ss: dict[str, Any], defender: BattleSide) -> bool:
    return (_storm_defender_front_alive(ss)
            or any(ss["d_lord_forces"][lid] for lid in ss["d_reserve"])
            or any(v > 0 for v in defender.garrison_forces.values()))


def _storm_melee_hits(state: GameState, ss: dict[str, Any],
                      front_forces_list: list[dict[UnitType, int]],
                      caps: list[Any], *, side_is_christian: bool,
                      round_idx: int,
                      garrison: dict[UnitType, int] | None = None) -> int:
    c8_budget = 0
    if (side_is_christian and round_idx == 1
            and "C8" in state.decks.this_levy_events.get("christian", [])):
        c8_budget = 4
    total = 0
    for f in front_forces_list:
        raw = _combined_melee_raw(state, f, caps)
        if c8_budget > 0:
            add = min(c8_budget, _c8_bonus_for_forces(f))
            raw += float(add)
            c8_budget -= add
        total += min(6, math.ceil(raw))
    if garrison:
        total += math.ceil(_combined_melee_raw(state, {}, [],
                                               garrison=garrison))
    return total


def _storm_reserve_pick(reserve_ids: list[str],
                        priority: list[str]) -> int:
    """4.4.1 REPOSITION: index of the Reserve Lord to Advance to the Front.
    Honours the owner's `array_reserve_priority` (first listed lord_id that
    is in Reserve); falls back to the first Reserve (legacy `pop(0)`)."""
    if priority:
        for lid in priority:
            if lid in reserve_ids:
                return reserve_ids.index(lid)
    return 0


def _storm_run_round(state: GameState, attacker: BattleSide,
                     defender: BattleSide, ss: dict[str, Any],
                     round_idx: int) -> BattleRound:
    """Resolve a single Storm Round (S11 Reposition + the Storm Strike
    order), mutating the per-Lord lane state in `ss`. Shared by
    resolve_storm (synchronous) and the interactive Storm driver."""
    rnd = BattleRound(index=round_idx)
    capacity = ss["capacity"]
    wr = ss["walls_range"]
    walls_range = (int(wr[0]), int(wr[1])) if wr else None
    if round_idx >= 2:
        d_prio = state.meta.array_reserve_priority.get(defender.side, [])
        a_prio = state.meta.array_reserve_priority.get(attacker.side, [])
        # Defender: forced commit if Front wiped, else the optional "may add
        # one Lord from Reserve" (4.4.1); the owner's priority picks which.
        if (not _storm_defender_front_alive(ss)) and ss["d_reserve"]:
            ss["d_front"].append(
                ss["d_reserve"].pop(_storm_reserve_pick(ss["d_reserve"], d_prio)))
        elif (ss["reposition_defender"] and len(ss["d_front"]) < capacity
              and ss["d_reserve"]):
            ss["d_front"].append(
                ss["d_reserve"].pop(_storm_reserve_pick(ss["d_reserve"], d_prio)))
        if (not _storm_attacker_front_alive(ss)) and ss["a_reserve"]:
            ss["a_front"].append(
                ss["a_reserve"].pop(_storm_reserve_pick(ss["a_reserve"], a_prio)))
        elif (ss["reposition_attacker"] and len(ss["a_front"]) < capacity
              and ss["a_reserve"]):
            ss["a_front"].append(
                ss["a_reserve"].pop(_storm_reserve_pick(ss["a_reserve"], a_prio)))
    round_walls = walls_range
    if ss["siege_towers"] and round_idx >= 2 and walls_range is not None:
        round_walls = (walls_range[0], max(0, walls_range[1] - 1))
    sw = ss["siegeworks_count"]
    defender.forces = _storm_front_agg(ss, "d")
    attacker.forces = _storm_front_agg(ss, "a")
    # 1.a Defender Missile -> Attacker.
    before = dict(attacker.forces)
    rnd.steps.append(_resolve_step(
        state, "1.a", "defender", "missile", None, attacker, defender,
        context="storm", walls_range=round_walls, siege_markers=sw,
        round_index=round_idx))
    _storm_push_losses(ss, "a", attacker, before)
    attacker.forces = _storm_front_agg(ss, "a")
    # 1.b Attacker Missile -> Defender.
    if _storm_attacker_front_alive(ss):
        before_d = dict(defender.forces)
        rnd.steps.append(_resolve_step(
            state, "1.b", "attacker", "missile", None, attacker, defender,
            context="storm", walls_range=round_walls, siege_markers=sw,
            round_index=round_idx))
        _storm_push_losses(ss, "d", defender, before_d)
        defender.forces = _storm_front_agg(ss, "d")
    # 2.a Defender Melee (+ Garrison) -> Attacker.
    if _storm_defender_front_alive(ss) or defender.garrison_forces:
        dmelee = _storm_melee_hits(
            state, ss, [ss["d_lord_forces"][lid] for lid in ss["d_front"]],
            ss["d_caps"], side_is_christian=(defender.side == "christian"),
            round_idx=round_idx, garrison=defender.garrison_forces)
        before_a = dict(attacker.forces)
        rnd.steps.append(_resolve_step(
            state, "2.a", "defender", "melee", None, attacker, defender,
            context="storm", walls_range=round_walls, siege_markers=sw,
            round_index=round_idx, melee_hits_override=dmelee))
        _storm_push_losses(ss, "a", attacker, before_a)
        attacker.forces = _storm_front_agg(ss, "a")
    # 2.b Attacker Melee -> Defender.
    if (_storm_attacker_front_alive(ss)
            and _storm_defender_alive(ss, defender)):
        amelee = _storm_melee_hits(
            state, ss, [ss["a_lord_forces"][lid] for lid in ss["a_front"]],
            ss["a_caps"], side_is_christian=(attacker.side == "christian"),
            round_idx=round_idx)
        before_d = dict(defender.forces)
        rnd.steps.append(_resolve_step(
            state, "2.b", "attacker", "melee", None, attacker, defender,
            context="storm", walls_range=round_walls, siege_markers=sw,
            round_index=round_idx, melee_hits_override=amelee))
        _storm_push_losses(ss, "d", defender, before_d)
    if round_idx == 1:
        _discard_round1_events(state, ["C8"])
    return rnd


def _storm_setup(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    *,
    max_rounds: int | None = None,
    walls_range_override: tuple[int, int] | None = None,
    reposition_defender: bool = True,
    reposition_attacker: bool = True,
) -> tuple[dict[str, Any], int]:
    """Build the serializable per-Lord Storm context `ss` (Locale walls,
    Garrison, Front/Reserve, per-Lord force/rout dicts). Shared by
    resolve_storm and the interactive Storm driver."""
    from almoravid.capabilities import any_lord_with_capability
    from almoravid.static_data import load_strongholds

    # ---- Locale + Stronghold parameters -------------------------------
    locale_id = None
    for lid in defender.lord_ids:
        lord = state.lords.get(lid)
        if lord and lord.cylinder.kind == "locale":
            locale_id = lord.cylinder.locale_id
            break
    if locale_id is None:
        for lid in attacker.lord_ids:
            lord = state.lords.get(lid)
            if lord and lord.cylinder.kind == "locale":
                locale_id = lord.cylinder.locale_id
                break
    walls_range = (1, 4)
    capacity = 1
    if locale_id is not None:
        loc = state.locales[locale_id]
        if loc.base_type != "region":
            sh = load_strongholds()["strongholds"][loc.base_type]
            walls_range = tuple(sh["walls_range"])
            capacity = int(sh.get("capacity", 1))
        if max_rounds is None:
            siege = (loc.siege_yellow if attacker.side == "christian"
                     else loc.siege_green)
            max_rounds = max(1, siege)
    if walls_range_override is not None:
        walls_range = walls_range_override
    if max_rounds is None:
        max_rounds = 1

    siegeworks_count = 0
    if locale_id is not None:
        loc = state.locales[locale_id]
        siegeworks_count = (loc.siege_yellow if attacker.side == "christian"
                            else loc.siege_green)
    st_card = "C6" if attacker.side == "christian" else "M13"
    siege_towers = bool(
        set(any_lord_with_capability(state, attacker.side, st_card))
        & set(attacker.lord_ids))

    # ---- Garrison + per-Lord force tracking ---------------------------
    garrison = _garrison_for_locale(state, locale_id) if locale_id else {}
    defender.garrison_forces = dict(garrison)

    # Per-Lord Defender forces (source of truth for cap + reserve). The
    # Attacker is the single Active Lord (Front), no Reserves.
    d_lord_forces = {lid: dict(state.lords[lid].forces)
                     for lid in defender.lord_ids}
    d_lord_routed: dict[str, Any] = {lid: {} for lid in defender.lord_ids}
    d_front = [defender.lord_ids[0]] if defender.lord_ids else []
    d_reserve = list(defender.lord_ids[1:])
    d_caps = list(defender.capabilities_in_play)
    a_caps = list(attacker.capabilities_in_play)

    # S11b: per-Lord ATTACKER Front/Reserve (multi-besieger Storms). The
    # Active Lord (attacker.lord_ids[0]) begins at Front; other besieging
    # Lords start in Reserve. Front never exceeds Stronghold Capacity;
    # Reposition (Round 2+) brings one Reserve to Front (forced if all
    # Front Rout). For a single-besieger Storm a_front is just the one
    # Lord and a_reserve is empty (legacy behavior preserved).
    if len(attacker.lord_ids) == 1:
        # Single-besieger Storm: the side's pooled forces ARE the Active
        # Lord's forces (preserves legacy behavior and lets callers set
        # BattleSide.forces directly).
        a_lord_forces = {attacker.lord_ids[0]: dict(attacker.forces)}
    else:
        a_lord_forces = {lid: dict(state.lords[lid].forces)
                         for lid in attacker.lord_ids}
    a_front = [attacker.lord_ids[0]] if attacker.lord_ids else []
    a_reserve = list(attacker.lord_ids[1:])
    a_lord_routed: dict[str, Any] = {lid: {} for lid in attacker.lord_ids}

    ss: dict[str, Any] = {
        "a_lord_forces": a_lord_forces,
        "d_lord_forces": d_lord_forces,
        "a_lord_routed": a_lord_routed,
        "d_lord_routed": d_lord_routed,
        "a_front": a_front,
        "a_reserve": a_reserve,
        "d_front": d_front,
        "d_reserve": d_reserve,
        "a_caps": a_caps,
        "d_caps": d_caps,
        "walls_range": list(walls_range) if walls_range else None,
        "capacity": capacity,
        "siegeworks_count": siegeworks_count,
        "siege_towers": siege_towers,
        "max_rounds": max_rounds,
        "reposition_defender": reposition_defender,
        "reposition_attacker": reposition_attacker,
    }
    return ss, max_rounds


def _storm_winner(result: BattleResult, ss: dict[str, Any],
                  attacker: BattleSide, defender: BattleSide, *,
                  conceded: bool, max_rounds: int) -> None:
    """Decide the Storm winner (4.5.2). Attacker loses on Concede, on
    elimination, or when the Round cap is reached with Defenders alive."""
    if conceded:
        result.winner = defender.side
        result.notes.append("Attacker Conceded; attacker loses")
    elif not _storm_attacker_alive(ss):
        result.winner = defender.side
    elif not _storm_defender_alive(ss, defender):
        result.winner = attacker.side
    else:
        result.winner = defender.side
        result.notes.append(
            f"Storm round-cap reached ({max_rounds}); attacker loses")


def _storm_finalize(ss: dict[str, Any], attacker: BattleSide,
                    defender: BattleSide, result: BattleResult) -> None:
    """Commit surviving per-Lord Storm forces to the sides + result."""
    final_forces: dict[UnitType, int] = {}
    for lid in ss["d_front"] + ss["d_reserve"]:
        for ut, n in ss["d_lord_forces"][lid].items():
            if n > 0:
                final_forces[ut] = final_forces.get(ut, 0) + n
    defender.forces = final_forces
    defender.garrison_forces = {}
    a_final: dict[UnitType, int] = {}
    for lid in ss["a_front"] + ss["a_reserve"]:
        for ut, n in ss["a_lord_forces"][lid].items():
            if n > 0:
                a_final[ut] = a_final.get(ut, 0) + n
    attacker.forces = a_final
    result.attacker_lord_forces = {
        lid: {ut: n for ut, n in ss["a_lord_forces"][lid].items() if n > 0}
        for lid in attacker.lord_ids}
    result.defender_lord_forces = {
        lid: {ut: n for ut, n in ss["d_lord_forces"][lid].items() if n > 0}
        for lid in defender.lord_ids}
    result.attacker_lord_routed = {
        lid: {ut: n for ut, n in ss["a_lord_routed"][lid].items() if n > 0}
        for lid in attacker.lord_ids}
    result.defender_lord_routed = {
        lid: {ut: n for ut, n in ss["d_lord_routed"][lid].items() if n > 0}
        for lid in defender.lord_ids}


def resolve_storm(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    *,
    max_rounds: int | None = None,
    walls_range_override: tuple[int, int] | None = None,
    reposition_defender: bool = True,
    reposition_attacker: bool = True,
    concede_after_round: int | None = None,
) -> BattleResult:
    """4.5.2 Storm with per-Lord Array (S8/S10/S11).

    Front begins with at most one Lord per side (the Attacker's Active
    Lord); other Lords start in Reserve. Front never exceeds the
    Stronghold's Capacity. Only Front Lords (plus the Garrison, for the
    Defender) Strike and absorb Hits each Round; Reserve Lords sit out
    until Repositioned. Each Lord adds at most six Melee Hits per Round
    (combined horse + foot). After Round 1 the Defender may bring one
    Reserve Lord to the Front (Reposition); if all Front Lords Rout, a
    Reserve must advance. The Attacker may Concede at the start of any
    Round after the first (concede_after_round); the Storm also ends
    when Rounds completed equals the Siege-marker count.

    S11b: the Attacker also has a per-Lord Front/Reserve array — the
    Active Lord begins at Front, other besieging Lords start in Reserve
    and Advance via Reposition (forced when all Front Rout), Front capped
    by Stronghold Capacity. Per-Lord post-Storm forces are exposed on the
    result (attacker_lord_forces / defender_lord_forces).
    """
    ss, max_rounds = _storm_setup(
        state, attacker, defender, max_rounds=max_rounds,
        walls_range_override=walls_range_override,
        reposition_defender=reposition_defender,
        reposition_attacker=reposition_attacker)
    result = BattleResult(engagement="storm", attacker=attacker,
                          defender=defender)
    conceded = False
    for round_idx in range(1, max_rounds + 1):
        # S10 Concede — Attacker only, start of Round 2+ (pre-declared;
        # the interactive driver decides this reactively instead).
        if (round_idx >= 2 and concede_after_round is not None
                and round_idx >= concede_after_round):
            conceded = True
            result.notes.append(
                f"Attacker Concedes at start of Round {round_idx}")
            break
        result.rounds.append(
            _storm_run_round(state, attacker, defender, ss, round_idx))
        if (not _storm_attacker_alive(ss)
                or not _storm_defender_alive(ss, defender)):
            break
    _storm_finalize(ss, attacker, defender, result)
    _storm_winner(result, ss, attacker, defender, conceded=conceded,
                  max_rounds=max_rounds)
    return result
def resolve_sally(
    state: GameState,
    attacker: BattleSide,    # the BESIEGED Lord(s) — sallying out
    defender: BattleSide,    # the besieger
    *,
    attacker_concede_round: int | None = None,
    defender_concede_round: int | None = None,
) -> BattleResult:
    """4.5.3 Sally. The Besieged Lord attacks the besieger.

    Mechanics are like Battle (no Walls protection — the Sallying side
    is OUTSIDE the walls for this action). Phase 5f baseline:
    structurally a Battle with engagement='sally'. On attacker loss,
    Sallying Lords Withdraw back into the Stronghold and Siege markers
    there reduce to 1 (per rule 4.5.3 / SoP on_attacker_loss).
    """
    # 4.5.3 (S9): the Sallying Lords get NO Walls or Garrison, but the
    # DEFENDERS (besiegers) receive Siegeworks as if Storming — Walls
    # equal to the besieger's Siege-marker count at the Locale. Locate
    # the Locale via a Sallying (besieged) Lord, then read the besieger
    # side's Siege markers there.
    locale_id = None
    for lid in attacker.lord_ids:
        lord = state.lords.get(lid)
        if lord and lord.cylinder.kind == "locale":
            locale_id = lord.cylinder.locale_id
            break
    defender_walls = None
    if locale_id is not None:
        loc = state.locales[locale_id]
        siege = (loc.siege_yellow if defender.side == "christian"
                 else loc.siege_green)
        if siege > 0:
            defender_walls = (1, siege)
    result = resolve_battle(state, attacker, defender,
                            defender_walls_range=defender_walls,
                            attacker_concede_round=attacker_concede_round,
                            defender_concede_round=defender_concede_round)
    result.engagement = "sally"
    # Sally-specific aftermath flag — actual Withdraw-back and Siege
    # marker reduction happen in apply_sally_aftermath called from the
    # cmd_sally handler.
    return result


def apply_sally_aftermath(state: GameState, result: BattleResult,
                          locale_id: str) -> None:
    """Sally-specific aftermath (rule 4.5.3).

    4.5.3: "Losing Defenders Retreat normally, ending the Siege. Losing
    Attackers must Withdraw back into their Stronghold (4.4.3, not
    Retreat)." RAID: "If Sallying Attackers lose, remove all but one
    Siege marker at the Locale ... The Siege goes on."

    So:
      * Sallying Attackers (the Besieged) LOSE -> Withdraw back inside
        (in_stronghold=True); Siege markers reduce to one (RAID).
      * Besieging Defenders LOSE -> they Retreat normally, RELOCATING
        off the Locale (apply_retreat_aftermath), and the Siege ENDS
        (the besieger's Siege/Bypass markers are removed -- the Locale
        is now free of those Enemy Lords, 4.5.3/4.5.4).
    Mirrors the standard Battle order: relocate -> Losses -> Aftermath.
    [P-3 playtest] Previously the besieger-loss branch built a "retreat"
    fate but never called apply_retreat_aftermath, so a surviving losing
    besieger was left co-located with the (winning) Besieged Lord and
    the Siege never ended.
    """
    from almoravid.campaign import _remove_orphaned_siege_bypass
    sallying_side = result.attacker.side
    besieger_side = result.defender.side
    loc = state.locales[locale_id]

    if result.winner is not None and result.winner != sallying_side:
        # Sallying Attackers lost -> Withdraw back inside; Siege -> 1 (RAID).
        losers: list[dict[str, Any]] = []
        for lid in result.attacker.lord_ids:
            if lid in state.lords:
                state.lords[lid].in_stronghold = True
            losers.append({"lord_id": lid, "fate": "withdraw"})
        if sallying_side == "muslim":
            if loc.siege_yellow > 1:
                loc.siege_yellow = 1
        else:
            if loc.siege_green > 1:
                loc.siege_green = 1
        apply_battle_losses(state, result, {"losers": losers}, storm=False)
        apply_aftermath(state, result)
        result.notes.append(
            f"Sally raid: {sallying_side} withdrew, siege at {locale_id} "
            f"reduced to 1"
        )
        return

    # Besiegers lost (or stalemate): the losing Besieging DEFENDERS
    # Retreat normally (4.4.3) -- apply_retreat_aftermath relocates each
    # off the Locale (Retreat branch; no Friendly Stronghold there for
    # them) and rolls the Service penalty. Then Losses + Aftermath.
    retreat_summary = apply_retreat_aftermath(state, result)
    apply_battle_losses(state, result, retreat_summary, storm=False)
    apply_aftermath(state, result)
    if result.winner == sallying_side:
        # "...ending the Siege": the besieging side's Lords have left the
        # Locale, so clear that side's Siege/Bypass markers (per-side, so
        # the Besieged winner's own state is untouched). 4.5.3/4.5.4.
        _remove_orphaned_siege_bypass(state, locale_id)
        result.notes.append(
            f"Sally: {besieger_side} besiegers Retreated; siege at "
            f"{locale_id} ended"
        )




# ---------------------------------------------------------------------------
# B6 (rule 4.4.1 RELIEF SALLY): dual-lane resolution.
# ---------------------------------------------------------------------------


def _pooled_battleside(state: GameState, lord_ids: list[str],
                       side: Side, role: Role) -> BattleSide:
    """Build a pooled (array=None) BattleSide from a list of Lords. The
    pooled path is used for Relief Sally lanes because it supports
    Walls/Siegeworks cancellation (the per-pair path does not)."""
    forces: dict[UnitType, int] = {}
    caps: list[str] = []
    for lid in lord_ids:
        lord = state.lords[lid]
        for ut, n in lord.forces.items():
            forces[ut] = forces.get(ut, 0) + n
        caps.extend(lord.capabilities)
    return BattleSide(side=side, role=role, lord_ids=list(lord_ids),
                      forces=forces, capabilities_in_play=caps)


@dataclass
class _ReliefState:
    """Mutable per-Round state of a Relief Sally (4.4.1), threaded through
    the single-Round step so the resolution can run synchronously OR be
    suspended/resumed for interactive reactive Concede. Per-Lord lane
    Forces/Routed (lf/lr) are keyed by lane NAME ("M","S","DF","DR") rather
    than object id() so the whole state is JSON-serializable."""

    marchers: BattleSide
    sallyers: BattleSide
    def_front: BattleSide | None
    def_rear: BattleSide | None
    shared: bool
    result: BattleResult
    lf: dict[str, Any]
    lr: dict[str, Any]
    excess_ids: list[str]
    defender_ids: list[str]
    n_front: int
    walls: tuple[int, int] | None
    active_side: Side
    other: Side
    max_rounds: int
    locale_id: str


def _relief_name_of(rs: _ReliefState, side_obj: BattleSide) -> str:
    if side_obj is rs.marchers:
        return "M"
    if side_obj is rs.sallyers:
        return "S"
    if side_obj is rs.def_front:
        return "DF"
    if side_obj is rs.def_rear:
        return "DF" if rs.shared else "DR"
    raise KeyError("unknown relief-sally lane object")


def _relief_atk_alive(rs: _ReliefState) -> bool:
    return rs.marchers.has_unrouted() or rs.sallyers.has_unrouted()


def _relief_def_alive(state: GameState, rs: _ReliefState) -> bool:
    a = rs.def_front.has_unrouted() if rs.def_front is not None else False
    b = (rs.def_rear.has_unrouted()
         if (rs.def_rear is not None and not rs.shared) else False)
    c = any(bool(state.lords[r].forces) for r in rs.excess_ids)
    return a or b or c


def _relief_over(state: GameState, rs: _ReliefState) -> bool:
    return (not _relief_atk_alive(rs)) or (not _relief_def_alive(state, rs))


def _relief_push_lane(rs: _ReliefState, side_obj: BattleSide,
                      before: dict[UnitType, int]) -> None:
    nm = _relief_name_of(rs, side_obj)
    lf = rs.lf[nm]
    lr = rs.lr[nm]
    now = side_obj.forces
    for ut, b in before.items():
        lost = b - now.get(ut, 0)
        for lid in side_obj.lord_ids:
            if lost <= 0:
                break
            have = lf[lid].get(ut, 0)
            take = min(have, lost)
            if take:
                lf[lid][ut] = have - take
                if lf[lid][ut] <= 0:
                    lf[lid].pop(ut, None)
                lr[lid][ut] = lr[lid].get(ut, 0) + take
                lost -= take


def _relief_lane_step(state: GameState, rs: _ReliefState, actor_role: Role,
                      attacker_side: BattleSide, defender_side: BattleSide,
                      **kw: Any) -> StepResolution:
    target = defender_side if actor_role == "attacker" else attacker_side
    before = dict(target.forces)
    step = _resolve_step(state, kw["step_id"], actor_role,
                         kw["step_type"], kw["unit_class"],
                         attacker_side, defender_side, context="battle",
                         walls_range=kw.get("walls_range"))
    _relief_push_lane(rs, target, before)
    return step


def _relief_lane_alive(rs: _ReliefState, side_obj: BattleSide) -> int:
    nm = _relief_name_of(rs, side_obj)
    return sum(1 for lid in side_obj.lord_ids if rs.lf[nm][lid])


def _relief_advance_reserve(state: GameState, rs: _ReliefState,
                            side_obj: BattleSide, cap: int) -> list[str]:
    nm = _relief_name_of(rs, side_obj)
    advanced: list[str] = []
    while _relief_lane_alive(rs, side_obj) < cap and rs.excess_ids:
        lid = rs.excess_ids.pop(0)
        side_obj.lord_ids.append(lid)
        rs.lf[nm][lid] = dict(state.lords[lid].forces)
        rs.lr[nm][lid] = {}
        advanced.append(lid)
    if advanced:
        agg: dict[UnitType, int] = {}
        for f in rs.lf[nm].values():
            for ut, n in f.items():
                if n > 0:
                    agg[ut] = agg.get(ut, 0) + n
        side_obj.forces = agg
    return advanced


def _relief_setup(
    state: GameState,
    marcher_ids: list[str],
    sallyer_ids: list[str],
    defender_ids: list[str],
    *,
    besieger_side: Side,
    locale_id: str,
    max_rounds: int,
) -> _ReliefState:
    active_side: Side = state.lords[(marcher_ids or sallyer_ids)[0]].side
    other: Side = besieger_side
    loc = state.locales.get(locale_id)
    siege = 0
    if loc is not None:
        siege = (loc.siege_yellow if besieger_side == "christian"
                 else loc.siege_green)
    walls = (1, siege) if siege > 0 else None
    marchers = _pooled_battleside(state, marcher_ids, active_side, "attacker")
    sallyers = _pooled_battleside(state, sallyer_ids, active_side, "attacker")
    if marcher_ids:
        n_front = max(1, min(len(marcher_ids), 3))
        front_ids = defender_ids[:n_front]
        rear_ids = defender_ids[n_front:n_front + 3]
        excess_ids = defender_ids[n_front + 3:]
    else:
        n_front = 0
        front_ids = []
        rear_ids = defender_ids[:3]
        excess_ids = defender_ids[3:]
    def_front = (_pooled_battleside(state, front_ids, other, "defender")
                 if front_ids else None)
    shared = False
    if rear_ids:
        def_rear: BattleSide | None = _pooled_battleside(
            state, rear_ids, other, "defender")
    elif def_front is not None:
        def_rear = def_front
        shared = True
    else:
        def_rear = None
    result = BattleResult(
        engagement="battle",
        attacker=_pooled_battleside(
            state, list(marcher_ids) + list(sallyer_ids), active_side,
            "attacker"),
        defender=_pooled_battleside(state, list(defender_ids), other,
                                    "defender"),
    )
    for ds in (def_front, def_rear):
        if ds is not None and not (shared and ds is def_front
                                   and def_rear is def_front):
            init_m7_cap(state, ds)
    if def_front is not None:
        init_m7_cap(state, def_front)
    if marcher_ids and def_front is not None:
        _consume_camp_attack(state, marchers, def_front, result)
    rs = _ReliefState(
        marchers=marchers, sallyers=sallyers, def_front=def_front,
        def_rear=def_rear, shared=shared, result=result, lf={}, lr={},
        excess_ids=list(excess_ids), defender_ids=list(defender_ids),
        n_front=n_front, walls=walls, active_side=active_side, other=other,
        max_rounds=max_rounds, locale_id=locale_id)
    # Init per-Lord lane tracking (name-keyed).
    for nm, so in (("M", marchers), ("S", sallyers),
                   ("DF", def_front), ("DR", def_rear)):
        if so is None or nm in rs.lf:
            continue
        if shared and so is def_front and nm == "DR":
            continue
        if len(so.lord_ids) == 1:
            rs.lf[nm] = {so.lord_ids[0]: dict(so.forces)}
        else:
            rs.lf[nm] = {lid: dict(state.lords[lid].forces)
                         for lid in so.lord_ids}
        rs.lr[nm] = {lid: {} for lid in so.lord_ids}
    return rs


def _relief_run_round(state: GameState, rs: _ReliefState,
                      rnd_i: int) -> BattleRound:
    """Resolve one Relief-Sally Round (Reposition + two-lane Strikes +
    end-of-Round discards), mutating `rs`. Concede declaration / break /
    winner are the caller's responsibility."""
    rnd = BattleRound(index=rnd_i)
    marchers, sallyers = rs.marchers, rs.sallyers
    def_front, def_rear = rs.def_front, rs.def_rear
    # Reposition (Round 2+): advance excess Reserve Defenders.
    if rnd_i >= 2 and rs.excess_ids:
        if def_front is not None:
            _relief_advance_reserve(state, rs, def_front, rs.n_front)
        if def_rear is not None and not rs.shared:
            _relief_advance_reserve(state, rs, def_rear,
                                    min(3, len(rs.defender_ids)))
    # M6 Feigned Retreat (Round 2) step reorder.
    if (rnd_i == 2
            and "M6" in state.decks.this_levy_events.get("muslim", [])):
        m_role: Role = ("attacker" if rs.active_side == "muslim"
                        else "defender")
        c_role: Role = ("attacker" if rs.active_side == "christian"
                        else "defender")
        steps_this_round: list[tuple[str, Role, str, UnitClass | None]] = [
            ("1.a", "defender", "missile", None),
            ("1.b", "attacker", "missile", None),
            ("2.a", m_role, "melee", "horse"),
            ("2.b", m_role, "melee", "foot"),
            ("2.c", c_role, "melee", "horse"),
            ("2.d", c_role, "melee", "foot"),
        ]
    else:
        steps_this_round = _BATTLE_STEPS
    for step_id, actor_role, step_type, unit_class in steps_this_round:
        if (def_front is not None
                and (marchers.has_unrouted() or def_front.has_unrouted())):
            rnd.steps.append(_relief_lane_step(
                state, rs, actor_role, marchers, def_front,
                step_id=step_id, step_type=step_type, unit_class=unit_class))
        if def_rear is not None:
            run_step = (actor_role == "attacker"
                        or (actor_role == "defender" and not rs.shared))
            if run_step and (sallyers.has_unrouted()
                             or def_rear.has_unrouted()):
                rnd.steps.append(_relief_lane_step(
                    state, rs, actor_role, sallyers, def_rear,
                    step_id=step_id, step_type=step_type,
                    unit_class=unit_class, walls_range=rs.walls))
        if _relief_over(state, rs):
            break
    if rnd_i == 1:
        _discard_round1_events(state, ["C8", "M7"])
    if rnd_i == 2:
        _discard_round1_events(state, ["M6"])
    return rnd


def _relief_finalize(state: GameState, rs: _ReliefState) -> None:
    """Commit each Lord's exact post-battle Forces/Routed and set the
    winner (Concede before Rout; mutual Concede = no winner)."""
    written: set[str] = set()
    for nm, so in (("M", rs.marchers), ("S", rs.sallyers),
                   ("DF", rs.def_front), ("DR", rs.def_rear)):
        if so is None or nm not in rs.lf or nm in written:
            continue
        written.add(nm)
        lf = rs.lf[nm]
        lr = rs.lr[nm]
        for lid in so.lord_ids:
            if lid in state.lords:
                state.lords[lid].forces = {ut: n for ut, n
                                           in lf[lid].items() if n > 0}
                state.lords[lid].routed_units = {ut: n for ut, n
                                                 in lr[lid].items() if n > 0}
    result = rs.result
    if result.attacker.conceded and not result.defender.conceded:
        result.winner = rs.other
    elif result.defender.conceded and not result.attacker.conceded:
        result.winner = rs.active_side
    elif not _relief_atk_alive(rs) and _relief_def_alive(state, rs):
        result.winner = rs.other
    elif _relief_atk_alive(rs) and not _relief_def_alive(state, rs):
        result.winner = rs.active_side
    else:
        result.winner = None
        if not _relief_atk_alive(rs) and not _relief_def_alive(state, rs):
            result.notes.append("Relief Sally: mutual elimination")
        else:
            result.notes.append(
                "Relief Sally inconclusive after max rounds")


def _relief_declare_concede(rs: _ReliefState, *, atk_concedes: bool,
                            dfd_concedes: bool) -> None:
    """Set the Concede flags for this Round (relieving side = Attacker;
    besieger = Defender), on the pooled result sides (for the aftermath's
    'Conceded then Retreated' treatment) AND each lane object (so
    _resolve_step halves that side's Hits this Round)."""
    if atk_concedes:
        rs.result.attacker.conceded = True
        rs.marchers.conceded = True
        rs.sallyers.conceded = True
    if dfd_concedes:
        rs.result.defender.conceded = True
        for ds in (rs.def_front, rs.def_rear):
            if ds is not None:
                ds.conceded = True


def _relief_to_snapshot(rs: _ReliefState) -> dict[str, Any]:
    """JSON-able snapshot of a Relief-Sally state for suspend/resume."""
    return {
        "marchers": battle_side_to_snapshot(rs.marchers),
        "sallyers": battle_side_to_snapshot(rs.sallyers),
        "def_front": (battle_side_to_snapshot(rs.def_front)
                      if rs.def_front is not None else None),
        "def_rear": (battle_side_to_snapshot(rs.def_rear)
                     if (rs.def_rear is not None and not rs.shared)
                     else None),
        "shared": rs.shared,
        "result_attacker": battle_side_to_snapshot(rs.result.attacker),
        "result_defender": battle_side_to_snapshot(rs.result.defender),
        "result_notes": list(rs.result.notes),
        "rounds_done": len(rs.result.rounds),
        "lf": rs.lf,
        "lr": rs.lr,
        "excess_ids": list(rs.excess_ids),
        "defender_ids": list(rs.defender_ids),
        "n_front": rs.n_front,
        "walls": list(rs.walls) if rs.walls else None,
        "active_side": rs.active_side,
        "other": rs.other,
        "max_rounds": rs.max_rounds,
        "locale_id": rs.locale_id,
    }


def _relief_from_snapshot(state: GameState,
                          snap: dict[str, Any]) -> _ReliefState:
    marchers = battle_side_from_snapshot(snap["marchers"])
    sallyers = battle_side_from_snapshot(snap["sallyers"])
    def_front = (battle_side_from_snapshot(snap["def_front"])
                 if snap["def_front"] is not None else None)
    shared = snap["shared"]
    if shared:
        def_rear: BattleSide | None = def_front
    else:
        def_rear = (battle_side_from_snapshot(snap["def_rear"])
                    if snap["def_rear"] is not None else None)
    result = BattleResult(
        engagement="battle",
        attacker=battle_side_from_snapshot(snap["result_attacker"]),
        defender=battle_side_from_snapshot(snap["result_defender"]))
    result.notes = list(snap["result_notes"])
    result.rounds = [BattleRound(index=k)
                     for k in range(1, snap["rounds_done"] + 1)]
    wr = snap["walls"]
    walls = (int(wr[0]), int(wr[1])) if wr else None
    return _ReliefState(
        marchers=marchers, sallyers=sallyers, def_front=def_front,
        def_rear=def_rear, shared=shared, result=result,
        lf=dict(snap["lf"]), lr=dict(snap["lr"]),
        excess_ids=list(snap["excess_ids"]),
        defender_ids=list(snap["defender_ids"]),
        n_front=snap["n_front"], walls=walls,
        active_side=snap["active_side"], other=snap["other"],
        max_rounds=snap["max_rounds"], locale_id=snap["locale_id"])


def resolve_relief_sally(
    state: GameState,
    marcher_ids: list[str],
    sallyer_ids: list[str],
    defender_ids: list[str],
    *,
    besieger_side: Side,
    locale_id: str,
    max_rounds: int = 6,
    attacker_concede_round: int | None = None,
    defender_concede_round: int | None = None,
) -> tuple[BattleResult, tuple[
    BattleSide, BattleSide, BattleSide | None,
    BattleSide | None, bool]]:
    """Rule 4.4.1 RELIEF SALLY (synchronous). The relieving Marchers +
    Sallyers (Attacker) fight the besieging Defenders across two lanes;
    either side may Concede (pre-declared here, reactive in the driver)."""
    rs = _relief_setup(state, marcher_ids, sallyer_ids, defender_ids,
                       besieger_side=besieger_side, locale_id=locale_id,
                       max_rounds=max_rounds)
    for rnd_i in range(1, max_rounds + 1):
        atk_concedes = (attacker_concede_round is not None
                        and rnd_i >= attacker_concede_round)
        dfd_concedes = (defender_concede_round is not None
                        and rnd_i >= defender_concede_round)
        _relief_declare_concede(rs, atk_concedes=atk_concedes,
                                dfd_concedes=dfd_concedes)
        rs.result.rounds.append(_relief_run_round(state, rs, rnd_i))
        if atk_concedes or dfd_concedes:
            rs.result.notes.append(
                f"Round {rnd_i} ended with Concede; Relief Sally ends")
            break
        if _relief_over(state, rs):
            break
    _relief_finalize(state, rs)
    return rs.result, (rs.marchers, rs.sallyers, rs.def_front,
                       rs.def_rear, rs.shared)


def apply_relief_sally_aftermath(
    state: GameState,
    result: BattleResult,
    *,
    locale_id: str,
    besieger_side: Side,
    approach_from_locale: str | None = None,
    approach_way_type: str | None = None,
) -> dict[str, Any]:
    """Relief-Sally aftermath (rule 4.4.1 / 4.5.3).

    Movement uses the standard Battle aftermath: apply_retreat_aftermath
    Withdraws losing Attacker Lords into the friendly Stronghold at the
    Battle Locale (this is exactly the Sallying Lords going back inside)
    and Retreats the relieving Marchers to their Approach origin. Then
    4.4.4 Losses and 4.4.5 Aftermath run.

    Relief-Sally extra: if the Attackers lose, reduce the besieger's
    Siege markers at the Locale to one (4.5.3).
    """
    retreat_summary = apply_retreat_aftermath(
        state, result,
        approach_from_locale=approach_from_locale,
        approach_way_type=approach_way_type,
    )
    apply_battle_losses(state, result, retreat_summary, storm=False)
    apply_aftermath(state, result)
    if result.winner is not None and result.winner == besieger_side:
        loc = state.locales.get(locale_id)
        if loc is not None:
            if besieger_side == "christian":
                if loc.siege_yellow > 1:
                    loc.siege_yellow = 1
            else:
                if loc.siege_green > 1:
                    loc.siege_green = 1
        result.notes.append(
            f"Relief Sally failed: Sallying Lords withdrew, siege at "
            f"{locale_id} reduced to 1")
    return retreat_summary

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
        asset_drain_order: tuple[AssetType, ...] = (
            "coin", "loot", "prov", "cart", "mule")
        total_spoils: dict[AssetType, int] = {}
        for elid in enemy.lord_ids:
            elord = state.lords.get(elid)
            if elord is None:
                continue
            # Phase 1: take 2 as Spoils.
            taken = 0
            for atype in asset_drain_order:
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
            for atype in asset_drain_order:
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
    lord: Lord,
    fate: str,
    conceded: bool,
    winner_lord_ids: list[str],
) -> dict[AssetType, int]:
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
    take: dict[AssetType, int] = {}
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
        is_friendly_locale,
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
    if result.engagement == "sally" and loser_side_obj is result.attacker:
        # Losing Sallying Attackers Withdraw back inside (handled by
        # apply_sally_aftermath, 4.5.3 "Losing Attackers must Withdraw").
        # The losing Besieging DEFENDER, by contrast, "Retreat[s]
        # normally, ending the Siege" -- so fall through and relocate
        # it here via the standard Retreat branch. [P-3 playtest]
        return summary

    # Battle locale = first loser Lord's cylinder.locale_id.
    battle_locale = None
    for lid in loser_side_obj.lord_ids:
        lord_obj = state.lords.get(lid)
        if lord_obj is not None and lord_obj.cylinder.kind == "locale":
            battle_locale = lord_obj.cylinder.locale_id
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
        1 for lord_obj in state.lords.values()
        if lord_obj.cylinder.kind == "locale"
        and lord_obj.cylinder.locale_id == battle_locale
        and lord_obj.in_stronghold
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
            asset_pay_order: tuple[AssetType, ...] = (
                "loot", "mule", "cart", "prov", "coin")
            c7_held = "C7" in state.decks.this_levy_events.get("christian", [])
            opt_out_used = False
            if c7_held and loser_side == "christian":
                for atype in asset_pay_order:
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
    Stronghold (unless Besieged or Bypassed). A NEUTRAL Stronghold
    (e.g. an unmarked Parias-Taifa one) is not Enemy and does NOT
    block Retreat (1.3.1)."""
    from almoravid.effective import (
        is_besieged,
        is_bypassed,
        is_enemy_locale,
    )
    other = "muslim" if retreating_side == "christian" else "christian"
    for lord in state.lords.values():
        if (lord.side == other and lord.cylinder.kind == "locale"
                and lord.cylinder.locale_id == locale_id):
            if not (is_besieged(state, lord.id) or is_bypassed(state, lord.id)):
                return False
    loc = state.locales[locale_id]
    if loc.base_type != "region" and is_enemy_locale(
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


def _reposition_array(
    side: BattleSide,
    *,
    center_fill: str = "left",
    reserve_priority: list[str] | None = None,
) -> None:
    """Rule 4.4.2 reposition (Round 2+):
      1. rout_removal: Lord whose forces are empty -> position='routed'.
      2. advance: one Reserve Lord into each empty Front position.
      3. center: if Front center still empty after Advance, mandatory
         slide from Front left or Front right into center.
    No-op when array is None.

    Player choices (4.4.2): `reserve_priority` is an ordered list of
    lord_ids deciding which Reserve Lord Advances first (into the first
    empty Front slot, center-most first); Lords not listed keep Array
    order behind those listed. `center_fill` ("left"|"right") picks which
    side Front Lord slides into an empty center. Defaults reproduce the
    historical deterministic behaviour (Array order; left before right).
    """
    if side.array is None:
        return
    # Step 1: rout removal.
    for lp in side.array:
        if lp.position not in ("reserve", "routed") and not lp.has_unrouted():
            lp.position = "routed"
    # Step 2: advance Reserves into empty Front positions (one-for-one).
    front_slots: tuple[ArrayPosition, ...] = (
        "front_center", "front_left", "front_right")
    filled = {lp.position for lp in side.array if lp.position in front_slots}
    empties = [s for s in front_slots if s not in filled]
    reserves = [lp for lp in side.array if lp.position == "reserve"
                and lp.has_unrouted()]
    if reserve_priority:
        # Owner choice (4.4.2 Advance): listed lord_ids Advance first, in
        # the given order; unlisted Reserves keep Array order behind them.
        def _prio(lp: LordPosition) -> tuple[int, int]:
            if lp.lord_id in reserve_priority:
                return (0, reserve_priority.index(lp.lord_id))
            return (1, side.array.index(lp))   # type: ignore[union-attr]
        reserves = sorted(reserves, key=_prio)
    for slot, lp in zip(empties, reserves, strict=False):
        lp.position = slot
    # Step 3: center-fill (mandatory slide from left/right if center empty).
    has_center = any(lp.position == "front_center" for lp in side.array)
    if not has_center:
        # Owner choice (4.4.2 Center): pull from the chosen side first.
        fill_order = (("front_right", "front_left")
                      if center_fill == "right"
                      else ("front_left", "front_right"))
        for cand_pos in fill_order:
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
        if (lp.position in ("front_center", "front_left", "front_right")
                and lp.has_unrouted()
                and lp.position not in opp_filled):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Phase 6f: per-pair Strike resolution (multi-Lord Battles).
# ---------------------------------------------------------------------------


def _build_strike_rows_for_position(
    state: GameState,
    side: BattleSide,
    lp: LordPosition,
    *,
    context: Literal["battle", "storm"] = "battle",
) -> list[StrikeRow]:
    """Like build_strike_rows but for a single LordPosition. The
    capability set is the per-Lord capabilities (lp.capabilities_in_play)
    union the side-wide capabilities_in_play already on `side`."""
    forces_data = load_forces()
    caps_in_play = set(side.capabilities_in_play) | set(lp.capabilities_in_play)
    rows: list[StrikeRow] = []
    javelin_budget = 4   # (b) up to 4 Unarmored units per Lord (C7/M3/M6)
    slinger_budget = 3   # C9/M7 Slingers: up to 3 Militia per Lord
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
                row_count = count
                cap_kind = cap_row.get("kind")
                if cap_row.get("cap_type") == "javelins" or \
                        cap_kind == "javelins":
                    row_count = min(count, javelin_budget)
                    javelin_budget -= row_count
                    if row_count <= 0:
                        continue
                elif cap_kind == "slingers" and cap_row.get("max_per_lord"):
                    row_count = min(count, slinger_budget)
                    slinger_budget -= row_count
                    if row_count <= 0:
                        continue
                cap_rate = cap_row["rate"]
                # 4.5.2: Javelins and Slingers fire x1/2 (not x1) in Storm.
                if (context == "storm" and cap_kind in ("javelins", "slingers")
                        and cap_rate == "x1"):
                    cap_rate = "x1/2"
                rows.append(StrikeRow(
                    unit_type=unit_type, count=row_count,
                    kind=cap_row["kind"], rate=cap_rate,
                    one_round_only=cap_row.get("any_one_round", False),
                    card_ids=sorted(required & caps_in_play),
                ))
    return rows


def _resolve_protection_roll_for_lp(
    state: GameState,
    side: BattleSide,
    target_lp: LordPosition,
    striker_kind: StrikeKind,
    *,
    context: Literal["battle", "storm"] = "battle",
    striker_selects: bool = False,
    striker_unit_class: UnitClass | None = None,
    absorb_policy: str = "weakest_first",
    striker_minus_armor: int = 0,
) -> tuple[bool, UnitType | None]:
    """Protection roll that drains from a single LordPosition's forces.

    Mirrors _resolve_protection_roll but operates on lp.forces directly.
    Routed units update side.routed_units (so commit_forces_after_battle
    sees them at the side level too) and lp.routed_units (per-Lord).
    """
    forces_data = load_forces()

    def _build_candidates(pool: dict[UnitType, int]) -> list[tuple[int, UnitType]]:
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
            elif absorb_policy == "armored_first":
                prio = {"armored": 0, "unarmored": 1, "auto_remove": 2,
                        "none": 3}.get(ptype, 4)
            else:
                prio = {"auto_remove": 0, "unarmored": 1, "armored": 2,
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
        # Crossbows: -1 vs Armor (Quick Ref Table 1 / Errata).
        hi = hi - striker_minus_armor
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


def _pick_flank_target(side: BattleSide,
                       actor_pos: ArrayPosition,
                       *,
                       flank_choice: str = "larger") -> LordPosition | None:
    """4.4.2 Flanking: a Front Lord with no Enemy directly opposite Strikes
    the CLOSEST Front Enemy Lord. Positional closeness on the 3-slot Front:
    a left/right Flanker prefers the center, then the far slot; a center
    Flanker may choose left or right (equidistant) — the owner's choice
    (`flank_choice` = "left" | "right"), defaulting to "larger" (Flank the
    bigger Enemy Lord) when left unset."""
    if side.array is None:
        return None
    fronts = {
        lp.position: lp for lp in side.array
        if lp.position in ("front_center", "front_left", "front_right")
        and lp.has_unrouted()
    }
    if not fronts:
        return None
    if actor_pos == "front_left":
        order: list[ArrayPosition] = ["front_center", "front_right"]
    elif actor_pos == "front_right":
        order = ["front_center", "front_left"]
    else:  # center: left and right are equidistant — owner's choice.
        if flank_choice == "left" and "front_left" in fronts:
            return fronts["front_left"]
        if flank_choice == "right" and "front_right" in fronts:
            return fronts["front_right"]
        cands = [fronts[p] for p in ("front_left", "front_right")
                 if p in fronts]
        if cands:
            # Default "larger" (or chosen side absent): Flank the bigger.
            return max(cands, key=lambda lp: sum(lp.forces.values()))
        order = []
    for p in order:
        if p in fronts:
            return fronts[p]
    return next(iter(fronts.values()))


def _pick_flank_absorber(actor: BattleSide, target: BattleSide,
                         opposed_lp: LordPosition) -> LordPosition | None:
    """4.4.2 APPLY HITS: "A Player with a Flanking Lord selects either the
    Flanking or directly opposed Lord to take Hits." Returns a Front Lord on
    the TARGET side that is Flanking (its Front position is NOT opposed by an
    unrouted actor Lord) and can absorb on behalf of `opposed_lp` (the
    directly-opposed Lord), or None if the target side has no such Flanking
    Lord. When several qualify, the largest is chosen as the owner's default.
    """
    if actor.array is None or target.array is None:
        return None
    fronts: tuple[ArrayPosition, ...] = (
        "front_center", "front_left", "front_right")
    actor_filled = {lp.position for lp in actor.array
                    if lp.position in fronts and lp.has_unrouted()}
    flankers = [lp for lp in target.array
                if lp.position in fronts and lp.has_unrouted()
                and lp.position not in actor_filled
                and lp is not opposed_lp]
    if not flankers:
        return None
    return max(flankers, key=lambda lp: sum(lp.forces.values()))


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
    c8_ctx: dict[str, Any] | None = None,
) -> StepResolution:
    """Per-pair Strike resolution (rule 4.4.2 multi-Lord Array).

    For each Front position on actor (center/left/right):
      - If a Lord occupies that position with unrouted units, they
        Strike at the same-position target Lord on defender, OR
        if that target is empty, route as Flanking to the largest
        Front Lord on defender.
      - Hits are computed from THAT Lord's units only (not pooled).

    B2 (rule 4.4.2 TOTAL HITS / Flanking): all Hits landing on a given
    target Lord this step -- from the directly-opposed actor Lord PLUS
    any Flanking actor Lords -- are SUMMED in halves and rounded UP
    ONCE (with mixed-missile Crossbow priority applied to the combined
    total), NOT rounded per striking Lord. So we gather every actor
    Front Lord's raw contribution against its chosen target, accumulate
    per target, then round and apply once per target.

    Absorption drains from the paired/Flanked target Lord's forces
    only. Reserve Lords do NOT Strike and do NOT absorb Hits.
    """
    actor = attacker if actor_role == "attacker" else defender
    target = defender if actor_role == "attacker" else attacker
    assert actor.array is not None and target.array is not None

    step_res = StepResolution(step=step_id, actor=actor_role)

    # ---- Phase 1: gather each Front actor Lord's raw contribution and
    # route it to a target Lord (same position, else Flanking). Sum the
    # half-Hits per target so rounding happens ONCE per target (B2).
    # Keyed by id(target_lp) to combine opposed + Flanking strikers.
    contributions: dict[int, Any] = {}
    target_order: list[int] = []
    # (c) C8 Cantador adds +1 to up to 4 of ONE Christian Lord's Knights/
    # Sergeants in Round 1, confined to the single Lord whose mat holds the
    # card (c8_ctx["holder_id"]) and sharing ONE budget of 4 across the
    # Horse-Melee and Foot-Melee steps of the Round (Knights + Sergeants
    # combined). The budget/holder live in the per-Round c8_ctx so they do
    # not reset per step or per Lord.
    # Direct callers (unit tests) may not thread a per-Round context; build
    # a fallback so a single-step call still applies C8 correctly.
    if c8_ctx is None:
        c8_ctx = _build_c8_ctx(state, attacker, defender, round_index)
    cantador_holder = c8_ctx["holder_id"] if c8_ctx is not None else None

    for actor_pos in ("front_center", "front_left", "front_right"):
        actor_lp = next((lp for lp in actor.array
                         if lp.position == actor_pos
                         and lp.has_unrouted()), None)
        if actor_lp is None:
            continue
        # 4.4.2: Strike the directly-opposite Enemy if present, else
        # Flank to the closest Front Enemy Lord.
        target_lp = next((lp for lp in target.array
                          if lp.position == actor_pos
                          and lp.has_unrouted()), None)
        directly_opposed = target_lp is not None
        if target_lp is None:
            target_lp = _pick_flank_target(
                target, actor_pos,
                flank_choice=state.meta.array_flank_choice.get(
                    actor.side, "larger"))
        if target_lp is None:
            continue
        # 4.4.2 APPLY HITS: the target side may absorb a directly-opposed
        # Lord's Hits with a friendly Flanking Lord, at its option.
        if (directly_opposed
                and state.meta.array_flank_absorb.get(
                    target.side, "opposed") == "flanking"):
            absorber = _pick_flank_absorber(actor, target, target_lp)
            if absorber is not None:
                target_lp = absorber

        rows = _build_strike_rows_for_position(state, actor, actor_lp,
                                               context="battle")
        # (a) one_round_only Strikes (Javelins) fire on the owner's
        # chosen Round (4.4.1 "any 1 Round"; default Round 1).
        if round_index != actor.oneround_round:
            rows = [r for r in rows if not r.one_round_only]
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

        # C8 Cantador (Round 1, Christian, melee, up to 4 K+S). The
        # SIDE-WIDE cap of 4 is enforced exactly across the per-pair Lords
        # via the shared, decremented `cantador_budget` (each Lord draws
        # from the same pool of 4 in Front-position order).
        if (step_type == "melee" and round_index == 1
                and actor.side == "christian" and c8_ctx is not None
                and (cantador_holder is None or id(actor_lp) == cantador_holder)
                and "C8" in state.decks.this_levy_events.get("christian", [])):
            eligible = 0
            for r in rows:
                if (r.kind == "melee"
                        and r.unit_type in ("knights", "sergeants")
                        and _unit_class(r.unit_type) == unit_class):
                    eligible += r.count
            eligible = min(eligible, c8_ctx["budget"])   # combined cap of 4
            if eligible > 0:
                c8_ctx["budget"] -= eligible
                raw += float(eligible)
                by_kind["melee"] = by_kind.get("melee", 0.0) + float(eligible)

        # Phase 6e Concede halving (applied to this Lord's contribution
        # before it is summed into the target's total -- rule 4.4.2
        # "halve first, then round up by step").
        if actor.conceded:
            raw = raw / 2.0
            by_kind = {k: v / 2.0 for k, v in by_kind.items()}

        if raw <= 0 and not by_kind:
            continue
        key = id(target_lp)
        if key not in contributions:
            contributions[key] = {"lp": target_lp, "raw": 0.0,
                                  "by_kind": {}}
            target_order.append(key)
        contributions[key]["raw"] += raw
        for k, v in by_kind.items():
            contributions[key]["by_kind"][k] = (
                contributions[key]["by_kind"].get(k, 0.0) + v)

    # ---- Phase 2: per target, round the combined half-Hits ONCE, then
    # resolve Protection and Rout (Walls n/a in Battle).
    aggregate_raw = 0.0
    for key in target_order:
        entry = contributions[key]
        target_lp = entry["lp"]
        raw = entry["raw"]
        by_kind = entry["by_kind"]
        aggregate_raw += raw
        rounded = math.ceil(raw) if raw > 0 else 0

        if step_type == "missile":
            per_kind_hits = _allocate_rounded_hits(raw, by_kind)
        else:
            per_kind_hits = {"melee": rounded}
        step_res.rounded_hits += rounded   # (d) Hits dealt this step (pre-Protection)

        # 4.4.2 ASSIGN HITS -- absorbing owner's per-combat policy.
        absorb_policy = state.meta.absorption_policy.get(
            target.side, "weakest_first")
        for kind, count in per_kind_hits.items():
            if count <= 0:
                continue
            striker_selects_target = (kind == "crossbows")
            protroll_kind: StrikeKind = ("melee" if kind == "melee"
                                         else "missiles")
            minus_armor = 1 if kind == "crossbows" else 0
            for _ in range(count):
                if not target_lp.has_unrouted():
                    break
                _, routed = _resolve_protection_roll_for_lp(
                    state, target, target_lp, protroll_kind,
                    context="battle",
                    striker_selects=striker_selects_target,
                    striker_unit_class=unit_class,
                    absorb_policy=absorb_policy,
                    striker_minus_armor=minus_armor,
                )
                if routed is not None:
                    step_res.losses[routed] = (
                        step_res.losses.get(routed, 0) + 1)
                    step_res.units_routed += 1   # (d) post-Protection routs

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
    spoils: dict[AssetType, int],
) -> dict[str, dict[AssetType, int]]:
    """Distribute Spoils across friendly Lords round-robin.

    Per rule 4.4.3 winning player distributes among winning Lords at
    the Battle. Greedy/deterministic: iterate Lords in given order,
    handing them one Asset at a time per kind. Returns the per-Lord
    distribution dict.
    """
    out: dict[str, dict[AssetType, int]] = {lid: {} for lid in friendly_lord_ids}
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
