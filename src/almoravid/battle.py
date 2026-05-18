"""Battle resolution (rule 4.4).

Phase 3b scope: SKELETON ONLY. The data structures (BattleResult,
BattleRound), the round-by-round loop ordering, and the integration
hooks are in place; the actual Strike-to-Hit-to-Protection resolution
is a stub for now. Phase 4 wires it up with the per-card Capability
modifiers (Hills, Spear Wall, Camp Attack, etc.).

Bug-pattern preemption built into this file:
  - Pattern 2 (mirror gaps): the BattleSide dataclass below is symmetric;
    aftermath helpers must be invoked for BOTH winner and loser. Phase 4
    audit must verify _apply_aftermath fires for both sides in all
    branches (winner-by-no-retreat, loser-by-Conceded, winner-by-zero-
    forces, etc.) — SMOKE-098/099/101 in Nevsky.
  - Pattern 7 (card-text fidelity): no card effects coded yet; the
    StrikeRow type carries 'card_ids' so resolvers can target the right
    bonuses without rederiving them from text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from almoravid.state import GameState, Side, UnitType


Role = Literal["attacker", "defender"]
StrikeKind = Literal["melee", "missiles", "javelins", "crossbows", "bowmen", "slingers"]


@dataclass
class StrikeRow:
    """One row in a Lord's Strike profile contributed by a unit-type stack."""

    unit_type: UnitType
    count: int
    kind: StrikeKind
    rate: str            # "x2", "x1", "x1/2"
    one_round_only: bool = False
    mark_used: bool = False
    card_ids: list[str] = field(default_factory=list)


@dataclass
class BattleSide:
    """One side of a Battle / Storm / Sally engagement."""

    side: Side
    role: Role
    lord_ids: list[str]                  # all Lords participating
    forces: dict[UnitType, int]          # consolidated stack
    capabilities_in_play: list[str]      # card_ids contributing strikes
    routed_units: dict[UnitType, int] = field(default_factory=dict)


@dataclass
class BattleRound:
    """One Strike Round within a Battle (rule 4.4.2)."""

    index: int                           # 1, 2, ...
    attacker_strikes: list[StrikeRow] = field(default_factory=list)
    defender_strikes: list[StrikeRow] = field(default_factory=list)
    attacker_hits_dealt: int = 0
    defender_hits_dealt: int = 0
    losses_attacker: dict[UnitType, int] = field(default_factory=dict)
    losses_defender: dict[UnitType, int] = field(default_factory=dict)


@dataclass
class BattleResult:
    """Outcome of one Battle / Storm / Sally."""

    engagement: Literal["battle", "storm", "sally"]
    attacker: BattleSide
    defender: BattleSide
    rounds: list[BattleRound] = field(default_factory=list)
    winner: Side | None = None
    aftermath_notes: list[str] = field(default_factory=list)


def build_strike_rows(
    state: GameState,
    side: BattleSide,
    context: Literal["battle", "storm"],
) -> list[StrikeRow]:
    """Construct the StrikeRows a side will fire in a given Round.

    Phase 3b: returns the base profile from forces.json. Capability-gated
    rows are NOT yet applied (Phase 4 work). This API is the seam where
    Pattern 7 audits will live — every card text that adds/modifies a
    strike row passes through here.
    """
    from almoravid.static_data import load_forces
    forces_data = load_forces()
    rows: list[StrikeRow] = []
    for unit_type, count in side.forces.items():
        if count <= 0:
            continue
        # Find the unit in either horse or foot category
        unit: dict[str, Any] | None = None
        for category in ("horse", "foot"):
            if unit_type in forces_data[category]:
                unit = forces_data[category][unit_type]
                break
        if unit is None:
            continue
        base_strikes = unit[f"strikes_{context}"]
        for s in base_strikes:
            rows.append(StrikeRow(
                unit_type=unit_type,
                count=count,
                kind=s["kind"],
                rate=s["rate"],
                one_round_only=s.get("any_one_round", False),
            ))
    return rows


def resolve_battle(
    state: GameState,
    attacker: BattleSide,
    defender: BattleSide,
) -> BattleResult:
    """Full Battle resolution per rule 4.4.

    Phase 3b: SKELETON. Returns a BattleResult with empty rounds and
    winner=None. Phase 4 wires:
      - Round loop with archery-then-melee priority.
      - Strike-to-Hit conversion (rate x count -> d6 rolls).
      - Hit-to-Loss conversion (Protection rolls).
      - Aftermath: ransom (4.4.3), routed_units restore on winner
        (Pattern 2 mirror gap — also applies to Storm/Sally).

    The structural shape is committed now so Phase 4 can fill in the
    handlers without revisiting the call sites that produce
    BattleResult.
    """
    result = BattleResult(
        engagement="battle",
        attacker=attacker,
        defender=defender,
    )
    result.aftermath_notes.append(
        "Phase 3b skeleton: round-by-round Strike resolution is in Phase 4."
    )
    return result
