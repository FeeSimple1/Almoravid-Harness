"""Game state model for the Almoravid harness.

This file defines the canonical state shape using Pydantic v2. It is
the Phase 0 scaffold: data classes only, no handlers, no rules logic,
no business methods. Later phases add mutators, legal_moves enumeration,
battle/storm resolution, etc.

Design decisions driven by the bug-pattern catalog in
FUTURE_PROJECTS_LESSONS.md:

- Pattern 4 (parallel Ways): `GameState.ways` is a list of `Way`
  objects each carrying an explicit `way_type`. Never key Ways by
  `(a, b)` alone.
- Pattern 5 (overlay markers): `Locale.base_type` is fixed at scenario
  setup; overlay state (Conquered, Jihad, Seat, Siege, Bypass) lives
  in separate fields. Phase 1 will add `effective_stronghold(locale)`
  helpers; raw `locale.base_type` reads outside those helpers are an
  audit smell.
- Pattern 6 (off-edge calendar): `Calendar` has explicit `off_left`,
  `off_right`, `off_left_service`, `off_right_service` lanes. Cylinder
  and Service marker off-edge lists are separate, per SMOKE-057.
- Pattern 11 (active-player desync): `Meta.active_player` is the
  single source of truth for whose turn it is. Future mutators must
  update it; tests should assert legal_moves never returns 0 while
  non-terminal.
- Pattern 14 (capability scope): each `CardInPlay` has an explicit
  `scope` field (`this_lord` vs `side_wide`); lookup helpers in
  Phase 4 will filter by scope.
- Pattern 3 (stale per-Lord flags): each per-Lord flag below carries a
  `# scope: ...` comment naming its expected reset boundary. Phase 1
  reset logic must honor these.
- Pattern 8 (lifecycle leaks): `Lord.cleanup_on_removal_fields` (class
  attribute below) enumerates the fields that MUST be cleared when a
  Lord is removed or Disbanded at limit.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["christian", "muslim"]
StrongholdType = Literal["city", "fortress", "town", "castle", "region"]
TaifaStatus = Literal["independent", "parias", "reconquista", "kingdoms"]
UnitType = Literal[
    "knights",
    "sergeants",
    "african_horse",
    "light_horse",
    "men_at_arms",
    "african_foot",
    "militia",
    "serfs",
]
# Assets the rules track. `coin`/`loot`/`prov` are general; `cart`/`mule`
# are Transport types per the Lord reference.
AssetType = Literal["coin", "loot", "prov", "cart", "mule"]
WayType = Literal["road", "pass"]
Season = Literal["spring", "summer", "autumn", "winter"]
TurnType = Literal["levy", "campaign", "curias", "winter"]
CardScope = Literal["this_lord", "side_wide"]
RavagedState = Literal["none", "yellow", "green"]
CylinderKind = Literal["calendar", "locale", "mat", "set_aside", "removed"]
LevyStep = Literal["arts_of_war", "pay", "service_disband", "muster", "call_to_arms", "done"]


class StrictModel(BaseModel):
    """Base for all state models: forbid extras, validate on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Meta(StrictModel):
    """Top-level game-meta state.

    `active_player` is the single source of truth for whose turn it is
    (Pattern 11). Any mutator that ends a step / passes the baton must
    update it.
    """

    scenario_id: str
    scenario_letter: Literal["A", "B", "C", "D", "E", "F"]
    seed: int = 0
    active_player: Side
    phase: Literal["setup", "levy", "campaign", "curias", "winter", "ended"] = "setup"
    turn_index: int = 0
    version: str = "0.2.0"

    # Levy sub-phase tracking (Pattern 1: state-set-but-unreachable —
    # each Levy step must be reachable via legal_moves; Pattern 11:
    # active_player above is the source of truth for whose turn it is).
    levy_step: LevyStep | None = None
    levy_step_completed_christian: bool = False
    levy_step_completed_muslim: bool = False
    first_levy_done: bool = False

    # Seeded RNG counter. Advanced by every roll_d6 / shuffle call.
    rng_state: int = 0


class Cylinder(StrictModel):
    """Where a Lord's cylinder currently is.

    Validation that (kind, box, locale_id) are consistent is deferred
    to Phase 1. Phase 0 just records the shape.
    """

    kind: CylinderKind
    box: int | None = None  # for kind="calendar"; 0..17 with 0/17 as off-edge sentinels
    locale_id: str | None = None  # for kind="locale"


class ServiceMarker(StrictModel):
    """A Lord's Service marker position on the Calendar.

    Off-edge handling: `box` may be 0 (off-left-service) or 17 (off-
    right-service). Cylinder and Service off-edges are independent
    (Pattern 6 / SMOKE-057).
    """

    lord_id: str
    box: int  # 0 = off_left_service, 1..16 in track, 17 = off_right_service


class CalendarBox(StrictModel):
    """One box on the 16-box Calendar."""

    number: int  # 1..16
    season: Season
    turn_type: TurnType
    cylinder_lord_ids: list[str] = Field(default_factory=list)
    # Service markers are stored on `Calendar.service_markers` keyed by
    # lord_id; this list is only the cylinders sitting on this box.

    # Scenario decorations placed at this box (Levy marker, Scenario End,
    # Victory marker color, Curias marker, etc.). Phase 0 stores them as
    # opaque strings; phase 1 will type them.
    decorations: list[str] = Field(default_factory=list)


class Calendar(StrictModel):
    """The 16-box Calendar plus off-edge lanes.

    Off-edge lanes are separate for cylinders vs Service markers
    (Pattern 6 / SMOKE-057). Do NOT merge.
    """

    boxes: list[CalendarBox]  # length 16, indices 0..15 correspond to boxes 1..16
    current_box: int = 1  # the box the Levy/Campaign marker is on

    off_left: list[str] = Field(default_factory=list)  # cylinder lord_ids
    off_right: list[str] = Field(default_factory=list)  # cylinder lord_ids

    # Service markers live here (not per-box) so off-edge lanes work uniformly.
    service_markers: list[ServiceMarker] = Field(default_factory=list)
    off_left_service: list[str] = Field(default_factory=list)  # lord_ids
    off_right_service: list[str] = Field(default_factory=list)  # lord_ids


class Vassal(StrictModel):
    """A Lord's Vassal. Pure data per the Lords reference."""

    id: str
    name: str
    forces: dict[UnitType, int] = Field(default_factory=dict)
    service_cost: int  # Service marker advance when called
    ready: bool = True


class CardInPlay(StrictModel):
    """An Arts of War card currently in play.

    `scope` enforces the this_lord vs side_wide distinction
    (Pattern 14 / SMOKE-016). Helpers in Phase 4 must filter on this.
    """

    card_id: str
    scope: CardScope
    owner_side: Side
    owner_lord_id: str | None = None  # required iff scope == "this_lord"


class Lord(StrictModel):
    """A Lord (Christian or Muslim).

    Per-flag scope conventions (Pattern 3 / SMOKE-001, 035, 036, 037, 095):
        moved_fought:            scope = per-Levy
        just_arrived_this_levy:  scope = per-Levy (reset on Levy->Campaign->Levy)
        lordship_used:           scope = per-card (Muster segment)
        in_stronghold:           scope = lifecycle (cleared on move / re-Muster)
        routed_units:            scope = per-engagement (cleared on aftermath)
        first_march_used_this_card: scope = per-card
        raiders_used_this_card:  scope = per-card

    Lifecycle cleanup contract (Pattern 8 / SMOKE-033, 038, 087, 088, 095):
    `Lord.cleanup_on_removal_fields` lists every field that MUST be
    cleared when this Lord is permanently removed OR Disbanded at limit.
    Removal handlers added in later phases must consult this list.
    """

    id: str
    name: str
    side: Side
    is_taifa: bool = False  # one of the 6 Muslim Taifa Lords (Pattern 5/14-adjacent)
    home_taifa: str | None = None  # taifa_id if Muslim Taifa Lord
    seats: list[str] = Field(default_factory=list)  # locale_ids of printed pennants

    fealty: int | None = None  # None = Call to Arms only (no Fealty roll)
    service_rating: int  # Service-ahead boxes at Muster/Disband
    lordship_rating: int
    command_rating: int

    cylinder: Cylinder

    # Mat contents (Phase 0: simple dicts; refined in Phase 1).
    forces: dict[UnitType, int] = Field(default_factory=dict)
    assets: dict[AssetType, int] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)  # this_lord-scope card_ids
    vassals: list[Vassal] = Field(default_factory=list)

    # Stronghold occupancy (Pattern 5): NOT derived from base_type; tracked
    # explicitly so overlay-aware effective_stronghold() helpers in Phase 1
    # can answer "is this Lord inside walls" correctly.
    in_stronghold: bool = False

    # Per-card / per-Levy / per-engagement flags. See docstring above.
    moved_fought: bool = False
    just_arrived_this_levy: bool = False
    lordship_used: int = 0
    first_march_used_this_card: bool = False
    raiders_used_this_card: bool = False
    routed_units: dict[UnitType, int] = Field(default_factory=dict)

    # Lifecycle cleanup contract (Pattern 8). Class-level, not a field.
    cleanup_on_removal_fields: ClassVar[tuple[str, ...]] = (
        "forces",
        "assets",
        "capabilities",
        "vassals",
        "in_stronghold",
        "moved_fought",
        "just_arrived_this_levy",
        "lordship_used",
        "first_march_used_this_card",
        "raiders_used_this_card",
        "routed_units",
    )


class Locale(StrictModel):
    """A map location.

    `base_type` is fixed at scenario setup. Overlay state (Conquered,
    Jihad, Seat, Siege, Bypass, Ravaged) lives in separate fields and
    is queried via Phase 1 `effective_*` helpers (Pattern 5 / SMOKE-040,
    054, 065, 066, 073-077).
    """

    id: str
    name: str
    territory: str  # taifa_id for Muslim Taifas, or "leon"/"aragon" for Christian
    base_type: StrongholdType
    has_gardens: bool = False  # Y at Cities and Fortresses per Map reference
    has_port: bool = False
    is_reconquista_target: bool = False  # printed Y/N on map

    # Overlay markers (counts where applicable; lists where multiple).
    conquered_markers: int = 0  # 1 VP each (Christian on Muslim, or Muslim on Christian)
    jihad_markers: int = 0  # 1/2 VP each
    seat_marker_lord_ids: list[str] = Field(default_factory=list)
    siege_yellow: int = 0  # Christian-placed Siege progress markers
    siege_green: int = 0  # Muslim-placed Siege progress markers
    bypass_yellow: bool = False
    bypass_green: bool = False
    ravaged: RavagedState = "none"


class Taifa(StrictModel):
    """One of the 7 Muslim Taifas.

    Christian "Kingdoms" (León, Aragón) are NOT Taifas and live in their
    own structure (or implicitly as a territory string on Locales).
    """

    id: str
    name: str
    locale_ids: list[str] = Field(default_factory=list)
    status: TaifaStatus = "independent"
    # Sevilla has 3 status boxes per Map reference; status changes place
    # 3 markers. `status_marker_count` tracks how many are placed.
    status_marker_count: int = 0


class Way(StrictModel):
    """A connection between two Locales.

    Stored as a list on GameState, NOT a dict keyed by (a, b)
    (Pattern 4 / SMOKE-047, 067-069). Each Way carries its `way_type`
    so parallel Ways are distinguishable.
    """

    a: str  # locale_id
    b: str  # locale_id
    way_type: WayType


class Decks(StrictModel):
    """Arts of War deck state.

    `capabilities_in_play` holds side-wide-scope cards (Pattern 14).
    This-lord-scope cards live on `Lord.capabilities`.

    `this_levy_events` and `this_campaign_events` are the persistence
    buckets for hold-events drawn this turn (cleared at the relevant
    window boundary per Pattern 13).
    """

    draw: list[str] = Field(default_factory=list)
    discard: list[str] = Field(default_factory=list)
    held: dict[Side, list[str]] = Field(default_factory=dict)
    capabilities_in_play: list[CardInPlay] = Field(default_factory=list)
    # Christian/Muslim board-edge Capability cards available for Levy.
    board_edge: dict[Side, list[str]] = Field(default_factory=dict)

    # Per-Levy / per-Campaign event persistence buckets (Pattern 13).
    # Cleared at the end of their respective windows.
    this_levy_events: dict[Side, list[str]] = Field(default_factory=dict)
    this_campaign_events: dict[Side, list[str]] = Field(default_factory=dict)

    # Cards just drawn but not yet implemented (3.1 Arts of War step).
    pending_draw: dict[Side, list[str]] = Field(default_factory=dict)


class PendingDecision(StrictModel):
    """A response/choice owed by some side before play can continue.

    Phase 0 scaffold. Phase 2+ will populate `kind` with action-specific
    discriminators (battle strike select, siege response, event target
    pick, etc.) and may turn this into a discriminated union.

    Pattern 11 (active-player desync): when `pending` is set, the side
    in `waiting_on` must equal `Meta.active_player`. Tests should
    assert this invariant.
    """

    kind: str
    waiting_on: Side
    payload: dict[str, object] = Field(default_factory=dict)


class HistoryEntry(StrictModel):
    """One action recorded in the game history log."""

    turn_index: int
    actor: Side | Literal["system"]
    action: str
    args: dict[str, object] = Field(default_factory=dict)
    summary: str = ""


class Score(StrictModel):
    """Victory point totals, separated by side and source.

    Detail breakdown (Conquered, Jihad, Taifa-status, etc.) added in
    Phase 1 when scoring is wired up.
    """

    christian: float = 0.0
    muslim: float = 0.0


class GameState(StrictModel):
    """The full game state.

    Invariants future phases must enforce (and tests must check):

    1. Pattern 11: `pending.waiting_on == meta.active_player` whenever
       `pending` is not None.
    2. Pattern 6: any cylinder/Service marker not on the 16-box track
       must live in exactly one of the off-edge lanes.
    3. Pattern 14: every `CardInPlay` with `scope == "this_lord"` must
       have its `card_id` in exactly one `Lord.capabilities` list.
    4. Pattern 8: removed Lords have all `cleanup_on_removal_fields`
       fields cleared.
    """

    meta: Meta
    calendar: Calendar
    lords: dict[str, Lord] = Field(default_factory=dict)
    locales: dict[str, Locale] = Field(default_factory=dict)
    taifas: dict[str, Taifa] = Field(default_factory=dict)
    ways: list[Way] = Field(default_factory=list)
    decks: Decks = Field(default_factory=Decks)
    pending: PendingDecision | None = None
    history: list[HistoryEntry] = Field(default_factory=list)
    score: Score = Field(default_factory=Score)
