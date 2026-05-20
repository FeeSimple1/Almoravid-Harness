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
    # S11b: per-Lord post-Storm forces (multi-besieger Storms) so the
    # caller can commit each Lord exactly. Empty for non-Storm results.
    attacker_lord_forces: dict[str, dict] = field(default_factory=dict)
    defender_lord_forces: dict[str, dict] = field(default_factory=dict)


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
    absorb_policy: str = "weakest_first",
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
    melee_hits_override: int | None = None,
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
        for _ in range(count):
            if not target.has_unrouted():
                break
            _, routed = _resolve_protection_roll(
                state, target, protroll_kind,
                context=context,
                striker_selects=striker_selects_target,
                striker_unit_class=unit_class,
                absorb_policy=absorb_policy,
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


def resolve_battle(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
    *,
    max_rounds: int = 6,
    defender_walls_range: tuple[int, int] | None = None,
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
                                      round_index=round_idx,
                                      walls_range=defender_walls_range)
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
        return rec["protection"]["evade"]["range"][1]
    ptype = rec["protection"]["type"]
    if ptype == "armored":
        return rec["protection"]["range"][1]
    if ptype == "unarmored":
        return 1
    return 0  # auto_remove (Serfs)


def apply_losses_rolls(state: GameState, lord_id: str, loser_state: str) -> dict:
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
    retreat_summary: dict,
    *,
    storm: bool = False,
) -> dict:
    """Drive 4.4.4 Losses for BOTH sides after a Battle/Storm.

    Winner-side Lords roll vs Protection ("winner"). Loser-side Lords
    use the loser_state implied by their fate (from retreat_summary):
    withdraw -> "withdrew"; retreat -> "conceded_then_retreated" if the
    loser side Conceded else "retreated_no_concede"; removed -> already
    gone. In a Storm, the Attacking side's Routed units always need a
    1 ("storm_attacker", 4.5.2). Any Lord left with zero Forces is
    permanently removed (3.3.1)."""
    from almoravid.state import Cylinder
    out: dict[str, dict] = {}
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
                lord.cylinder = Cylinder(kind="removed")
                _ssl(state, lid, boxes=20)
                out[lid]["permanently_removed"] = True
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
        # Number of Front positions this side may fill (1..3). B4: the
        # Defender is capped at the Attacker's Front-Lord count so each
        # extra Lord goes to Reserve.
        front_n = max(1, min(int(front_limit), 3))
        # Active Lord (or the first lord_id) occupies Front center.
        center_lid = active_lord_id if (active_lord_id in lord_ids)             else lord_ids[0]
        others = [lid for lid in lord_ids if lid != center_lid]
        slots = [(center_lid, "front_center")]
        for i, lid in enumerate(others):
            # center already filled position 0; remaining Front slots
            # are positions_order[1 .. front_n-1].
            if i + 1 < front_n:
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


def _combined_melee_raw(
    state: GameState,
    forces: dict,
    caps: list[str],
    *,
    garrison: dict | None = None,
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


def _c8_bonus_for_forces(forces: dict) -> int:
    """C8 Cantador eligible units (Knights + Sergeants) in a force dict."""
    return forces.get("knights", 0) + forces.get("sergeants", 0)


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
    from almoravid.static_data import load_strongholds
    from almoravid.capabilities import any_lord_with_capability

    # ---- Locale + Stronghold parameters -------------------------------
    locale_id = None
    for lid in defender.lord_ids:
        l = state.lords.get(lid)
        if l and l.cylinder.kind == "locale":
            locale_id = l.cylinder.locale_id
            break
    if locale_id is None:
        for lid in attacker.lord_ids:
            l = state.lords.get(lid)
            if l and l.cylinder.kind == "locale":
                locale_id = l.cylinder.locale_id
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

    def _a_front_agg() -> dict:
        agg: dict = {}
        for lid in a_front:
            for ut, n in a_lord_forces[lid].items():
                if n > 0:
                    agg[ut] = agg.get(ut, 0) + n
        return agg

    def _push_attacker_losses(before: dict) -> None:
        """Distribute Front-Attacker losses (before - now) back to the
        per-Lord force dicts (greedy across Front Lords)."""
        now = attacker.forces
        for ut, b in before.items():
            lost = b - now.get(ut, 0)
            for lid in a_front:
                if lost <= 0:
                    break
                have = a_lord_forces[lid].get(ut, 0)
                take = min(have, lost)
                if take:
                    a_lord_forces[lid][ut] = have - take
                    if a_lord_forces[lid][ut] <= 0:
                        a_lord_forces[lid].pop(ut, None)
                    lost -= take

    def _attacker_front_alive() -> bool:
        return any(a_lord_forces[lid] for lid in a_front)

    def _attacker_alive() -> bool:
        return (_attacker_front_alive()
                or any(a_lord_forces[lid] for lid in a_reserve))

    def _d_front_agg() -> dict:
        agg: dict = {}
        for lid in d_front:
            for ut, n in d_lord_forces[lid].items():
                if n > 0:
                    agg[ut] = agg.get(ut, 0) + n
        return agg

    def _push_defender_losses(before: dict) -> None:
        """Distribute Front-Defender losses (before - now) back to the
        per-Lord force dicts (greedy across Front Lords)."""
        now = defender.forces
        for ut, b in before.items():
            lost = b - now.get(ut, 0)
            for lid in d_front:
                if lost <= 0:
                    break
                have = d_lord_forces[lid].get(ut, 0)
                take = min(have, lost)
                if take:
                    d_lord_forces[lid][ut] = have - take
                    if d_lord_forces[lid][ut] <= 0:
                        d_lord_forces[lid].pop(ut, None)
                    lost -= take

    def _defender_front_alive() -> bool:
        return any(d_lord_forces[lid] for lid in d_front)

    def _defender_alive() -> bool:
        return (_defender_front_alive()
                or any(d_lord_forces[lid] for lid in d_reserve)
                or any(v > 0 for v in defender.garrison_forces.values()))

    def _melee_hits(front_forces_list, caps, *, side_is_christian,
                    round_idx, garrison=None) -> int:
        """Per-Lord-capped (<=6 each) combined Melee Hits, + Garrison
        Melee (uncapped), folding C8 Cantador (Round 1) into per-Lord
        raw before the cap."""
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

    result = BattleResult(engagement="storm", attacker=attacker,
                          defender=defender)
    conceded = False

    for round_idx in range(1, max_rounds + 1):
        rnd = BattleRound(index=round_idx)
        # S10 Concede — Attacker only, start of Round 2+.
        if (round_idx >= 2 and concede_after_round is not None
                and round_idx >= concede_after_round):
            conceded = True
            result.notes.append(
                f"Attacker Concedes at start of Round {round_idx}")
            break
        # S11 Reposition (Round 2+): Defender forced advance if all Front
        # Routed, else optional up to Capacity.
        if round_idx >= 2:
            if (not _defender_front_alive()) and d_reserve:
                d_front.append(d_reserve.pop(0))
            elif (reposition_defender and len(d_front) < capacity
                  and d_reserve):
                d_front.append(d_reserve.pop(0))
            # S11b: ATTACKER Reposition (forced if all Front Rout, else
            # optional up to Capacity).
            if (not _attacker_front_alive()) and a_reserve:
                a_front.append(a_reserve.pop(0))
            elif (reposition_attacker and len(a_front) < capacity
                  and a_reserve):
                a_front.append(a_reserve.pop(0))

        round_walls = walls_range
        if siege_towers and round_idx >= 2 and walls_range is not None:
            round_walls = (walls_range[0], max(0, walls_range[1] - 1))

        # Engaged Defender = Front aggregate (+ Garrison bucket); engaged
        # Attacker = Front aggregate (S11b).
        defender.forces = _d_front_agg()
        attacker.forces = _a_front_agg()

        # ---- Storm step order: Defender all Strikes, then Attacker ----
        # 1.a Defender Missile (Front + Garrison) -> Attacker.
        before = dict(attacker.forces)
        step = _resolve_step(state, "1.a", "defender", "missile", None,
                             attacker, defender, context="storm",
                             walls_range=round_walls,
                             siege_markers=siegeworks_count,
                             round_index=round_idx)
        rnd.steps.append(step)
        _push_attacker_losses(before)
        attacker.forces = _a_front_agg()
        # 1.b Attacker Missile -> Defender (Front aggregate + Garrison).
        if _attacker_front_alive():
            before_d = dict(defender.forces)
            step = _resolve_step(state, "1.b", "attacker", "missile", None,
                                 attacker, defender, context="storm",
                                 walls_range=round_walls,
                                 siege_markers=siegeworks_count,
                                 round_index=round_idx)
            rnd.steps.append(step)
            _push_defender_losses(before_d)
            defender.forces = _d_front_agg()
        # 2.a Defender Melee (per-Lord cap + Garrison) -> Attacker.
        if _defender_front_alive() or defender.garrison_forces:
            dmelee = _melee_hits(
                [d_lord_forces[lid] for lid in d_front], d_caps,
                side_is_christian=(defender.side == "christian"),
                round_idx=round_idx, garrison=defender.garrison_forces)
            before_a = dict(attacker.forces)
            step = _resolve_step(state, "2.a", "defender", "melee", None,
                                 attacker, defender, context="storm",
                                 walls_range=round_walls,
                                 siege_markers=siegeworks_count,
                                 round_index=round_idx,
                                 melee_hits_override=dmelee)
            rnd.steps.append(step)
            _push_attacker_losses(before_a)
            attacker.forces = _a_front_agg()
        # 2.b Attacker Melee (per Front Lord, cap 6 each) -> Defender.
        if _attacker_front_alive() and _defender_alive():
            amelee = _melee_hits(
                [a_lord_forces[lid] for lid in a_front], a_caps,
                side_is_christian=(attacker.side == "christian"),
                round_idx=round_idx)
            before_d = dict(defender.forces)
            step = _resolve_step(state, "2.b", "attacker", "melee", None,
                                 attacker, defender, context="storm",
                                 walls_range=round_walls,
                                 siege_markers=siegeworks_count,
                                 round_index=round_idx,
                                 melee_hits_override=amelee)
            rnd.steps.append(step)
            _push_defender_losses(before_d)

        result.rounds.append(rnd)
        if round_idx == 1:
            _discard_round1_events(state, ["C8"])
        if not _attacker_alive() or not _defender_alive():
            break

    # Final Defender forces = surviving Front + untouched Reserve units
    # (so downstream Losses/commit see the full picture).
    final_forces: dict = {}
    for lid in d_front + d_reserve:
        for ut, n in d_lord_forces[lid].items():
            if n > 0:
                final_forces[ut] = final_forces.get(ut, 0) + n
    defender.forces = final_forces
    defender.garrison_forces = {}  # Garrison returns to pool at Storm end.
    # S11b: surviving Attacker forces = Front + Reserve, and expose the
    # per-Lord post-Storm forces so the caller can commit each besieging
    # Lord exactly (not proportionally) — likewise for the Defenders.
    a_final: dict = {}
    for lid in a_front + a_reserve:
        for ut, n in a_lord_forces[lid].items():
            if n > 0:
                a_final[ut] = a_final.get(ut, 0) + n
    attacker.forces = a_final
    result.attacker_lord_forces = {
        lid: {ut: n for ut, n in a_lord_forces[lid].items() if n > 0}
        for lid in attacker.lord_ids}
    result.defender_lord_forces = {
        lid: {ut: n for ut, n in d_lord_forces[lid].items() if n > 0}
        for lid in defender.lord_ids}

    # ---- Winner (4.5.2 Ending the Storm) ------------------------------
    if conceded:
        result.winner = defender.side
        result.notes.append("Attacker Conceded; attacker loses")
    elif not _attacker_alive():
        result.winner = defender.side
    elif not _defender_alive():
        result.winner = attacker.side
    else:
        # Rounds ran out with Defenders surviving — Attacker loses.
        result.winner = defender.side
        result.notes.append(
            f"Storm round-cap reached ({max_rounds}); attacker loses")
    return result
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
    # 4.5.3 (S9): the Sallying Lords get NO Walls or Garrison, but the
    # DEFENDERS (besiegers) receive Siegeworks as if Storming — Walls
    # equal to the besieger's Siege-marker count at the Locale. Locate
    # the Locale via a Sallying (besieged) Lord, then read the besieger
    # side's Siege markers there.
    locale_id = None
    for lid in attacker.lord_ids:
        l = state.lords.get(lid)
        if l and l.cylinder.kind == "locale":
            locale_id = l.cylinder.locale_id
            break
    defender_walls = None
    if locale_id is not None:
        loc = state.locales[locale_id]
        siege = (loc.siege_yellow if defender.side == "christian"
                 else loc.siege_green)
        if siege > 0:
            defender_walls = (1, siege)
    result = resolve_battle(state, attacker, defender,
                            defender_walls_range=defender_walls)
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
    sallying_side = result.attacker.side
    loc = state.locales[locale_id]
    # Build the loser-fate summary (4.5.3): a losing Sallying side
    # Withdraws back into the Stronghold; losing Defenders (besiegers)
    # Retreat normally.
    losers: list[dict] = []
    if result.winner is not None and result.winner != sallying_side:
        # Sallying side lost -> Withdraw back inside; reduce Siege to 1.
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
    elif result.winner is not None and result.winner == sallying_side:
        # Besiegers lost -> they Retreat normally (4.5.3).
        for lid in result.defender.lord_ids:
            losers.append({"lord_id": lid, "fate": "retreat"})
    # 4.4.4 Losses for both sides, then 4.4.5 Aftermath.
    apply_battle_losses(state, result, {"losers": losers}, storm=False)
    apply_aftermath(state, result)
    if result.winner == sallying_side:
        return  # Sally succeeded; no further Siege-reduction note.
    result.notes.append(
        f"Sally raid: {sallying_side} withdrew, siege at {locale_id} "
        f"reduced to 1"
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
        l = state.lords[lid]
        for ut, n in l.forces.items():
            forces[ut] = forces.get(ut, 0) + n
        caps.extend(l.capabilities)
    return BattleSide(side=side, role=role, lord_ids=list(lord_ids),
                      forces=forces, capabilities_in_play=caps)


def resolve_relief_sally(
    state: GameState,
    marcher_ids: list[str],
    sallyer_ids: list[str],
    defender_ids: list[str],
    *,
    besieger_side: Side,
    locale_id: str,
    max_rounds: int = 6,
):
    """Rule 4.4.1 RELIEF SALLY. The Approaching (relieving) side's
    Besieged Lords Sally out to join the Attack against the besiegers.

    Array geometry (two lanes resolved within the SAME Battle):
      - Lane M (open field): the relieving Marchers Strike, and are
        Struck by, the Front Defenders directly opposite them. No Walls.
      - Lane S (Siegeworks): the Sallying Attackers, arrayed behind the
        Defenders, Attack up to three Reserve Defenders arrayed as a
        Front facing them -- or, if the Defender has no Reserve, the
        Front Defenders. The besieging DEFENDER cancels the Sallying
        Attackers' Hits via Siegeworks-as-Walls (Walls range 1..Siege
        markers). The Sallying Attackers themselves get NO Walls.
        Reserve-Defenders (when present) Strike the Sallying Attackers
        back; when the Sallying Attackers instead Flank the Front
        Defenders (no Reserve case), those Front Defenders Strike the
        Marchers in Lane M and are not double-counted Striking the
        Sallyers.

    The Sallying Attackers Strike "as if Flanking all of them equally
    closely": pooling each lane's Forces realises this (all Sallyer
    Hits combine into one rounded total against the pooled Reserve/Front
    Defenders).

    Returns (result, lanes) where lanes = (marchers, sallyers, def_front,
    def_rear, shared). The caller commits each lane and runs the standard
    Battle aftermath (apply_retreat_aftermath handles the Sallyers'
    Withdraw-back-into-Stronghold via the friendly-Stronghold-at-Locale
    rule); the Siege-marker reduction to one on Attacker loss is applied
    by the caller / apply_relief_sally_aftermath.

    DOCUMENTED SCOPE: lanes are pooled (consistent with single-Lord
    Battle resolution), so multi-Lord lanes commit Losses proportionally
    (4.4.4) rather than per-Lord. Round-level AoW reorders (M6 Feigned
    Retreat) are not applied within a Relief Sally; the per-step Hills
    (C1/M1) and C8 hooks inside _resolve_step still apply. Excess
    Defenders beyond Front + three Reserve-as-Front do not participate.
    """
    active_side: Side = state.lords[
        (marcher_ids or sallyer_ids)[0]].side
    other: Side = besieger_side

    # Siegeworks-as-Walls available to the besieging Defender vs the
    # Sallying Attackers' Strikes only (rule 4.5.3).
    loc = state.locales.get(locale_id)
    siege = 0
    if loc is not None:
        siege = (loc.siege_yellow if besieger_side == "christian"
                 else loc.siege_green)
    walls = (1, siege) if siege > 0 else None

    marchers = _pooled_battleside(state, marcher_ids, active_side, "attacker")
    sallyers = _pooled_battleside(state, sallyer_ids, active_side, "attacker")

    # Defender split. Front faces the Marchers (one opposite each, capped
    # at three); up to three of the REMAINDER face the Sallyers; any
    # further Defenders are true Reserve and do not participate.
    if marcher_ids:
        n_front = max(1, min(len(marcher_ids), 3))
        front_ids = defender_ids[:n_front]
        rear_ids = defender_ids[n_front:n_front + 3]
        excess_ids = defender_ids[n_front + 3:]
    else:
        front_ids = []
        rear_ids = defender_ids[:3]
        excess_ids = defender_ids[3:]

    def_front = (_pooled_battleside(state, front_ids, other, "defender")
                 if front_ids else None)
    shared = False
    if rear_ids:
        def_rear = _pooled_battleside(state, rear_ids, other, "defender")
    elif def_front is not None:
        # No Reserve Defenders: Sallyers Flank the Front Defenders.
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

    # Card hooks (parity with resolve_battle): M7 Spear Wall on Muslim
    # Defenders; Camp Attack consumed at Battle start in the open lane.
    for ds in (def_front, def_rear):
        if ds is not None and not (shared and ds is def_front
                                   and def_rear is def_front):
            init_m7_cap(state, ds)
    if def_front is not None:
        init_m7_cap(state, def_front)
    if marcher_ids and def_front is not None:
        _consume_camp_attack(state, marchers, def_front, result)

    def _atk_alive() -> bool:
        return marchers.has_unrouted() or sallyers.has_unrouted()

    def _def_alive() -> bool:
        a = def_front.has_unrouted() if def_front is not None else False
        b = (def_rear.has_unrouted()
             if (def_rear is not None and not shared) else False)
        c = any(bool(state.lords[r].forces) for r in excess_ids)
        return a or b or c

    def _over() -> bool:
        return (not _atk_alive()) or (not _def_alive())

    for rnd_i in range(1, max_rounds + 1):
        rnd = BattleRound(index=rnd_i)
        for step_id, actor_role, step_type, unit_class in _BATTLE_STEPS:
            # Lane M: Marchers <-> Front Defenders (open field).
            if (def_front is not None
                    and (marchers.has_unrouted()
                         or def_front.has_unrouted())):
                rnd.steps.append(_resolve_step(
                    state, step_id, actor_role, step_type, unit_class,
                    marchers, def_front, context="battle"))
            # Lane S: Sallyers <-> Reserve/Front Defenders. Siegeworks
            # cancels the Sallyers' (attacker) Hits only; when `shared`
            # the Defenders already Strike in Lane M, so skip Lane S
            # defender Strikes to avoid double-counting.
            if def_rear is not None:
                run_step = (actor_role == "attacker"
                            or (actor_role == "defender" and not shared))
                if run_step and (sallyers.has_unrouted()
                                 or def_rear.has_unrouted()):
                    rnd.steps.append(_resolve_step(
                        state, step_id, actor_role, step_type, unit_class,
                        sallyers, def_rear, context="battle",
                        walls_range=walls))
            if _over():
                break
        result.rounds.append(rnd)
        if rnd_i == 1:
            _discard_round1_events(state, ["C8", "M7", "C1", "M1"])
        if _over():
            break

    # Winner: a side is defeated when all its participants are Routed.
    if not _atk_alive() and _def_alive():
        result.winner = other
    elif _atk_alive() and not _def_alive():
        result.winner = active_side
    else:
        result.winner = None
        if not _atk_alive() and not _def_alive():
            result.notes.append("Relief Sally: mutual elimination")
        else:
            result.notes.append(
                "Relief Sally inconclusive after max rounds")
    return result, (marchers, sallyers, def_front, def_rear, shared)


def apply_relief_sally_aftermath(
    state: GameState,
    result: BattleResult,
    *,
    locale_id: str,
    besieger_side: Side,
    approach_from_locale: str | None = None,
    approach_way_type: str | None = None,
) -> dict:
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
    absorb_policy: str = "weakest_first",
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
    contributions: dict[int, dict] = {}
    target_order: list[int] = []

    for actor_pos in ("front_center", "front_left", "front_right"):
        actor_lp = next((lp for lp in actor.array
                         if lp.position == actor_pos
                         and lp.has_unrouted()), None)
        if actor_lp is None:
            continue
        # Find target: same position first, else Flanking to closest
        # (here: largest) Front enemy Lord.
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
        # giving each Lord up to min(4, its own K+S count) -- slightly
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

        # 4.4.2 ASSIGN HITS -- absorbing owner's per-combat policy.
        absorb_policy = state.meta.absorption_policy.get(
            target.side, "weakest_first")
        for kind, count in per_kind_hits.items():
            if count <= 0:
                continue
            striker_selects_target = (kind == "crossbows")
            protroll_kind: StrikeKind = ("melee" if kind == "melee"
                                         else "missiles")
            for _ in range(count):
                if not target_lp.has_unrouted():
                    break
                _, routed = _resolve_protection_roll_for_lp(
                    state, target, target_lp, protroll_kind,
                    context="battle",
                    striker_selects=striker_selects_target,
                    striker_unit_class=unit_class,
                    absorb_policy=absorb_policy,
                )
                if routed is not None:
                    step_res.losses[routed] = (
                        step_res.losses.get(routed, 0) + 1)
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
